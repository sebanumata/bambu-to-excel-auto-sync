"""
Listens to the Bambu Lab printer's local MQTT (LAN mode) and, every time it
detects a print finishing or being cancelled, appends a row to the history
spreadsheet (prints_log.xlsx) in this same folder.

Does not depend on Bambu's cloud or your account: it uses the LAN access
code configured in config.json, same as Bambu Studio's LAN mode.
"""
import json
import logging
import re
import ssl
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

from excel_lib import load_records, save_records, append_missing_records, format_hours

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

with open(CONFIG_PATH, encoding="utf-8") as f:
    CFG = json.load(f)

REPORT_TOPIC = f"device/{CFG['serial']}/report"
REQUEST_TOPIC = f"device/{CFG['serial']}/request"

ACTIVE_STATES = {"RUNNING", "PAUSE"}
END_STATES = {"FINISH", "FAILED", "IDLE"}

# In-memory tracker of the print currently being watched.
job = None  # {"start": datetime, "file": str, "task_id": str}


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


def append_record(dt: datetime, archivo: str, duracion_h: float, placa: str, estado: str) -> None:
    records = load_records(RECORDS_PATH)
    records.append({
        "dt": dt,
        "archivo": archivo or "(unnamed)",
        "duracion": format_hours(duracion_h),
        "impresora": CFG["printer_label"],
        "placa": placa,
        "estado": estado,
    })
    save_records(records, RECORDS_PATH)
    safe_sync_excel(records, XLSX_PATH)
    log.info(f"Row added: {archivo} | {format_hours(duracion_h)} | {placa} | {estado}")


def handle_print_status(p: dict) -> None:
    global job

    state = p.get("gcode_state")
    if not state:
        return

    gcode_file = p.get("gcode_file", "") or ""
    subtask_name = p.get("subtask_name", "") or ""
    task_id = p.get("task_id", "")
    display_name = subtask_name or gcode_file or "(unnamed)"

    if state == "RUNNING":
        if job is None:
            job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
            log.info(f"New print detected: {display_name} (task_id={task_id})")
        elif task_id and job.get("task_id") and task_id != job["task_id"]:
            # We missed the previous job's finish event (e.g. a network drop).
            log.warning(f"task_id changed with no prior FINISH, closing previous job as an estimated Success: {job['file']}")
            duration_h = (datetime.now() - job["start"]).total_seconds() / 3600
            append_record(job["start"], job["file"], duration_h, guess_plate(job["file"]), "Success")
            job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
        return

    if state in END_STATES and job is not None:
        end_time = datetime.now()
        duration_h = (end_time - job["start"]).total_seconds() / 3600
        estado = "Success" if state == "FINISH" else "Cancelled"
        placa = guess_plate(job["file"])
        append_record(job["start"], job["file"], duration_h, placa, estado)
        job = None


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info(f"Connected to the printer at {CFG['printer_ip']}")
        client.subscribe(REPORT_TOPIC)
        client.publish(REQUEST_TOPIC, json.dumps({
            "pushing": {"sequence_id": "0", "command": "pushall"}
        }))
    else:
        log.error(f"MQTT connection failed, rc={rc}")


def on_disconnect(client, userdata, rc, properties=None, *args):
    log.warning(f"Disconnected from the printer (rc={rc}), retrying...")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    p = payload.get("print")
    if p:
        try:
            handle_print_status(p)
        except Exception:
            log.exception("Error processing status message")


def main():
    log.info("=== Starting bambu_sync ===")
    client = mqtt.Client(client_id=f"bambu_sync_{int(time.time())}", protocol=mqtt.MQTTv311)
    client.username_pw_set("bblp", CFG["access_code"])
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try:
            client.connect(CFG["printer_ip"], 8883, keepalive=30)
            client.loop_forever(retry_first_connection=True)
        except Exception:
            log.exception("Connection error, retrying in 15s")
            time.sleep(15)


if __name__ == "__main__":
    main()
