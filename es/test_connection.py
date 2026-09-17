import json
import ssl
import time
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

CFG = json.load(open(Path(__file__).parent / "config.json", encoding="utf-8"))
REPORT_TOPIC = f"device/{CFG['serial']}/report"
REQUEST_TOPIC = f"device/{CFG['serial']}/request"

got_message = {"flag": False}


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"on_connect rc={rc}")
    if rc == 0:
        client.subscribe(REPORT_TOPIC)
        client.publish(REQUEST_TOPIC, json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
    else:
        print("CONEXION FALLIDA, revisa IP / codigo de acceso / que este en modo LAN")


def on_message(client, userdata, msg):
    got_message["flag"] = True
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("payload no-JSON:", e)
        return
    p = payload.get("print")
    if p:
        print("Estado actual de impresion:")
        print("  gcode_state:", p.get("gcode_state"))
        print("  gcode_file:", p.get("gcode_file"))
        print("  subtask_name:", p.get("subtask_name"))
        print("  mc_percent:", p.get("mc_percent"))
        print("  task_id:", p.get("task_id"))
    else:
        print("Mensaje recibido sin bloque 'print', keys:", list(payload.keys()))


client = mqtt.Client(client_id=f"bambu_test_{int(time.time())}", protocol=mqtt.MQTTv311)
client.username_pw_set("bblp", CFG["access_code"])
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)
client.on_connect = on_connect
client.on_message = on_message

print(f"Conectando a {CFG['printer_ip']}:8883 ...")
try:
    client.connect(CFG["printer_ip"], 8883, keepalive=10)
except (TimeoutError, OSError) as e:
    print(f"No se pudo alcanzar {CFG['printer_ip']}:8883 ({e}).")
    print("Revisa que la impresora este prendida y conectada al WiFi, y que la IP en config.json sea correcta.")
    sys.exit(1)
client.loop_start()
time.sleep(8)
client.loop_stop()
client.disconnect()

if not got_message["flag"]:
    print("NO se recibio ningun mensaje en 8s. Revisa que la impresora este encendida,")
    print("en la misma red, y que 'LAN Only Mode' este activado en Configuracion > Red.")
    sys.exit(1)
print("OK: conexion y datos verificados.")
