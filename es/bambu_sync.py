"""
Escucha el MQTT local de una o varias impresoras Bambu Lab (modo LAN) y,
cada vez que detecta que una impresion termina o se cancela, agrega una
fila al Excel de historial (impresiones_3d.xlsx) en esta misma carpeta.

No depende de la nube de Bambu ni de tu cuenta: usa el codigo de acceso LAN
configurado en config.json, igual que Bambu Studio en modo LAN.

Soporta varias impresoras a la vez (ver printer_config.py) escribiendo
todas al mismo Excel, distinguidas por la columna "Impresora".
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
XLSX_PATH = BASE_DIR / "impresiones_3d.xlsx"
LOG_PATH = BASE_DIR / "bambu_sync.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bambu_sync")

PRINTERS = load_printers(CONFIG_PATH)

END_STATES = {"FINISH", "FAILED", "IDLE"}

# Varias impresoras pueden terminar casi al mismo tiempo: este lock evita que
# dos hilos lean/escriban records.json o el Excel al mismo tiempo.
records_lock = threading.Lock()


def guess_plate(gcode_file: str) -> str:
    m = re.search(r"plate[_\-]?(\d+)", gcode_file or "", re.IGNORECASE)
    if m:
        return f"Placa {m.group(1)}"
    return "Placa 1"


def safe_sync_excel(records: list, path: Path, retries: int = 4, delay: int = 5) -> bool:
    """Agrega solo las filas nuevas, asi las ediciones manuales del usuario
    en Excel se mantienen."""
    for attempt in range(1, retries + 1):
        try:
            added = append_missing_records(records, path)
            if added:
                log.info(f"Excel actualizado: {added} fila(s) nueva(s) agregada(s) sin tocar el resto.")
            return True
        except PermissionError:
            log.warning(
                f"No pude escribir el Excel (¿esta abierto en Excel?), "
                f"reintento {attempt}/{retries} en {delay}s"
            )
            time.sleep(delay)
    log.warning(
        "No se pudo actualizar el Excel: probablemente sigue abierto. "
        "Los datos ya estan guardados en records.json y el Excel se va a "
        "poner al dia solo en el proximo evento, una vez que lo cierres."
    )
    return False


def append_record(dt: datetime, archivo: str, duracion_h: float, placa: str, estado: str, printer_label: str) -> None:
    with records_lock:
        records = load_records(RECORDS_PATH)
        records.append({
            "dt": dt,
            "archivo": archivo or "(sin nombre)",
            "duracion": format_hours(duracion_h),
            "impresora": printer_label,
            "placa": placa,
            "estado": estado,
        })
        save_records(records, RECORDS_PATH)
        safe_sync_excel(records, XLSX_PATH)
    log.info(f"[{printer_label}] Fila agregada: {archivo} | {format_hours(duracion_h)} | {placa} | {estado}")


class PrinterWatcher:
    """Sigue el estado de UNA impresora y agrega filas cuando termina o
    cancela una impresion. Cada instancia corre en su propio hilo."""

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
            log.info(f"[{self.label}] Conectado en {self.cfg['printer_ip']}")
            client.subscribe(self.report_topic)
            client.publish(self.request_topic, json.dumps({
                "pushing": {"sequence_id": "0", "command": "pushall"}
            }))
        else:
            log.error(f"[{self.label}] Fallo de conexion MQTT, rc={rc}")

    def on_disconnect(self, client, userdata, rc, properties=None, *args):
        log.warning(f"[{self.label}] Desconectado (rc={rc}), reintentando...")

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
                log.exception(f"[{self.label}] Error procesando mensaje de estado")

    def handle_print_status(self, p: dict) -> None:
        state = p.get("gcode_state")
        if not state:
            return

        gcode_file = p.get("gcode_file", "") or ""
        subtask_name = p.get("subtask_name", "") or ""
        task_id = p.get("task_id", "")
        display_name = subtask_name or gcode_file or "(sin nombre)"

        if state == "RUNNING":
            if self.job is None:
                self.job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
                log.info(f"[{self.label}] Nueva impresion detectada: {display_name} (task_id={task_id})")
            elif task_id and self.job.get("task_id") and task_id != self.job["task_id"]:
                # Se perdio el evento de fin del trabajo anterior (ej. caida de red).
                log.warning(f"[{self.label}] Cambio de task_id sin FINISH previo, cerrando job anterior como Exito estimado: {self.job['file']}")
                duration_h = (datetime.now() - self.job["start"]).total_seconds() / 3600
                append_record(self.job["start"], self.job["file"], duration_h, guess_plate(self.job["file"]), "Éxito", self.label)
                self.job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
            return

        if state in END_STATES and self.job is not None:
            end_time = datetime.now()
            duration_h = (end_time - self.job["start"]).total_seconds() / 3600
            estado = "Éxito" if state == "FINISH" else "Cancelado"
            placa = guess_plate(self.job["file"])
            append_record(self.job["start"], self.job["file"], duration_h, placa, estado, self.label)
            self.job = None

    def run_forever(self):
        while True:
            try:
                self.client.connect(self.cfg["printer_ip"], 8883, keepalive=30)
                self.client.loop_forever(retry_first_connection=True)
            except Exception:
                log.exception(f"[{self.label}] Error de conexion, reintentando en 15s")
                time.sleep(15)


def main():
    log.info(f"=== Iniciando bambu_sync ({len(PRINTERS)} impresora(s)) ===")
    watchers = [PrinterWatcher(cfg) for cfg in PRINTERS]
    threads = [threading.Thread(target=w.run_forever, daemon=True, name=w.label) for w in watchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
