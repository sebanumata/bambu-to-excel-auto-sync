"""
Listens to the local MQTT of one or more Bambu Lab printers (LAN mode) and,
every time it detects a print finishing or being cancelled, appends a row
to the history spreadsheet (prints_log.xlsx) in this same folder.

Does not depend on Bambu's cloud or your account: it uses the LAN access
code configured in config.json, same as Bambu Studio's LAN mode.

Supports multiple printers at once (see printer_config.py), all writing to
the same spreadsheet, told apart by the "Printer" column.
"""
import json
import logging
import re
import ssl
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

from excel_lib import load_records, save_records, append_missing_records, format_hours
from printer_config import load_printers

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
RECORDS_PATH = BASE_DIR / "records.json"
XLSX_PATH = BASE_DIR / "prints_log.xlsx"
LOG_PATH = BASE_DIR / "bambu_sync.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bambu_sync")

PRINTERS = load_printers(CONFIG_PATH)

END_STATES = {"FINISH", "FAILED", "IDLE"}

# Several printers can finish around the same time: this lock keeps two
# threads from reading/writing records.json or the spreadsheet at once.
records_lock = threading.Lock()


def guess_plate(gcode_file: str) -> str:
    m = re.search(r"plate[_\-]?(\d+)", gcode_file or "", re.IGNORECASE)
    if m:
        return f"Plate {m.group(1)}"
    return "Plate 1"


def safe_sync_excel(records: list, path: Path, retries: int = 4, delay: int = 5) -> bool:
    """Appends only the rows missing from the sheet, so any manual edits the
    user made directly in Excel are preserved."""
    for attempt in range(1, retries + 1):
        try:
            added = append_missing_records(records, path)
            if added:
                log.info(f"Excel updated: {added} new row(s) added without touching the rest.")
            return True
        except PermissionError:
            log.warning(
                f"Couldn't write the Excel file (is it open?), "
                f"retry {attempt}/{retries} in {delay}s"
            )
            time.sleep(delay)
    log.warning(
        "Couldn't update the Excel file: it's probably still open. "
        "The data is already saved in records.json and the Excel file will "
        "catch up automatically on the next event, once it's closed."
    )
    return False


def append_record(dt: datetime, archivo: str, duracion_h: float, placa: str, estado: str, printer_label: str) -> None:
    with records_lock:
        records = load_records(RECORDS_PATH)
        records.append({
            "dt": dt,
            "archivo": archivo or "(unnamed)",
            "duracion": format_hours(duracion_h),
            "impresora": printer_label,
            "placa": placa,
            "estado": estado,
        })
        save_records(records, RECORDS_PATH)
        safe_sync_excel(records, XLSX_PATH)
    log.info(f"[{printer_label}] Row added: {archivo} | {format_hours(duracion_h)} | {placa} | {estado}")


class PrinterWatcher:
    """Tracks the state of ONE printer and appends rows when a print
    finishes or is cancelled. Each instance runs on its own thread."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.label = cfg["printer_label"]
        self.report_topic = f"device/{cfg['serial']}/report"
        self.request_topic = f"device/{cfg['serial']}/request"
        self.job = None  # {"start": datetime, "file": str, "task_id": str}

        self.client = mqtt.Client(
            client_id=f"bambu_sync_{cfg['serial']}_{int(time.time())}",
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set("bblp", cfg["access_code"])
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info(f"[{self.label}] Connected at {self.cfg['printer_ip']}")
            client.subscribe(self.report_topic)
            client.publish(self.request_topic, json.dumps({
                "pushing": {"sequence_id": "0", "command": "pushall"}
            }))
        else:
            log.error(f"[{self.label}] MQTT connection failed, rc={rc}")

    def on_disconnect(self, client, userdata, rc, properties=None, *args):
        log.warning(f"[{self.label}] Disconnected (rc={rc}), retrying...")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        p = payload.get("print")
        if p:
            try:
                self.handle_print_status(p)
            except Exception:
                log.exception(f"[{self.label}] Error processing status message")

    def handle_print_status(self, p: dict) -> None:
        state = p.get("gcode_state")
        if not state:
            return

        gcode_file = p.get("gcode_file", "") or ""
        subtask_name = p.get("subtask_name", "") or ""
        task_id = p.get("task_id", "")
        display_name = subtask_name or gcode_file or "(unnamed)"

        if state == "RUNNING":
            if self.job is None:
                self.job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
                log.info(f"[{self.label}] New print detected: {display_name} (task_id={task_id})")
            elif task_id and self.job.get("task_id") and task_id != self.job["task_id"]:
                # We missed the previous job's finish event (e.g. a network drop).
                log.warning(f"[{self.label}] task_id changed with no prior FINISH, closing previous job as an estimated Success: {self.job['file']}")
                duration_h = (datetime.now() - self.job["start"]).total_seconds() / 3600
                append_record(self.job["start"], self.job["file"], duration_h, guess_plate(self.job["file"]), "Success", self.label)
                self.job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
            return

        if state in END_STATES and self.job is not None:
            end_time = datetime.now()
            duration_h = (end_time - self.job["start"]).total_seconds() / 3600
            estado = "Success" if state == "FINISH" else "Cancelled"
            placa = guess_plate(self.job["file"])
            append_record(self.job["start"], self.job["file"], duration_h, placa, estado, self.label)
            self.job = None

    def run_forever(self):
        while True:
            try:
                self.client.connect(self.cfg["printer_ip"], 8883, keepalive=30)
                self.client.loop_forever(retry_first_connection=True)
            except Exception:
                log.exception(f"[{self.label}] Connection error, retrying in 15s")
                time.sleep(15)


def main():
    log.info(f"=== Starting bambu_sync ({len(PRINTERS)} printer(s)) ===")
    watchers = [PrinterWatcher(cfg) for cfg in PRINTERS]
    threads = [threading.Thread(target=w.run_forever, daemon=True, name=w.label) for w in watchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
