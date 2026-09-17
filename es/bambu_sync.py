"""
Escucha el MQTT local de la impresora Bambu Lab (modo LAN) y, cada vez que
detecta que una impresion termina o se cancela, agrega una fila al Excel
de historial (impresiones_3d.xlsx) en esta misma carpeta.

No depende de la nube de Bambu ni de tu cuenta: usa el codigo de acceso LAN
configurado en config.json, igual que Bambu Studio en modo LAN.
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
XLSX_PATH = BASE_DIR / "impresiones_3d.xlsx"
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
        return f"Placa {m.group(1)}"
    return "Placa 1"


def safe_sync_excel(records: list, path: Path, retries: int = 4, delay: int = 5) -> bool:
    """Appends only the rows missing from the sheet, so any manual edits the
    user made directly in Excel are preserved."""
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


def append_record(dt: datetime, archivo: str, duracion_h: float, placa: str, estado: str) -> None:
    records = load_records(RECORDS_PATH)
    records.append({
        "dt": dt,
        "archivo": archivo or "(sin nombre)",
        "duracion": format_hours(duracion_h),
        "impresora": CFG["printer_label"],
        "placa": placa,
        "estado": estado,
    })
    save_records(records, RECORDS_PATH)
    safe_sync_excel(records, XLSX_PATH)
    log.info(f"Fila agregada: {archivo} | {format_hours(duracion_h)} | {placa} | {estado}")


def handle_print_status(p: dict) -> None:
    global job

    state = p.get("gcode_state")
    if not state:
        return

    gcode_file = p.get("gcode_file", "") or ""
    subtask_name = p.get("subtask_name", "") or ""
    task_id = p.get("task_id", "")
    display_name = subtask_name or gcode_file or "(sin nombre)"

    if state == "RUNNING":
        if job is None:
            job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
            log.info(f"Nueva impresion detectada: {display_name} (task_id={task_id})")
        elif task_id and job.get("task_id") and task_id != job["task_id"]:
            # Se perdio el evento de fin del trabajo anterior (ej. caida de red).
            log.warning(f"Cambio de task_id sin FINISH previo, cerrando job anterior como Exito estimado: {job['file']}")
            duration_h = (datetime.now() - job["start"]).total_seconds() / 3600
            append_record(job["start"], job["file"], duration_h, guess_plate(job["file"]), "Éxito")
            job = {"start": datetime.now(), "file": display_name, "task_id": task_id}
        return

    if state in END_STATES and job is not None:
        end_time = datetime.now()
        duration_h = (end_time - job["start"]).total_seconds() / 3600
        estado = "Éxito" if state == "FINISH" else "Cancelado"
        placa = guess_plate(job["file"])
        append_record(job["start"], job["file"], duration_h, placa, estado)
        job = None


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info(f"Conectado a la impresora en {CFG['printer_ip']}")
        client.subscribe(REPORT_TOPIC)
        client.publish(REQUEST_TOPIC, json.dumps({
            "pushing": {"sequence_id": "0", "command": "pushall"}
        }))
    else:
        log.error(f"Fallo de conexion MQTT, rc={rc}")


def on_disconnect(client, userdata, rc, properties=None, *args):
    log.warning(f"Desconectado de la impresora (rc={rc}), reintentando...")


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
            log.exception("Error procesando mensaje de estado")


def main():
    log.info("=== Iniciando bambu_sync ===")
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
            log.exception("Error de conexion, reintentando en 15s")
            time.sleep(15)


if __name__ == "__main__":
    main()
