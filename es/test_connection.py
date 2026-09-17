import json
import ssl
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from printer_config import load_printers

PRINTERS = load_printers(Path(__file__).parent / "config.json")


def test_one(cfg: dict) -> bool:
    got = {"flag": False}

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe(f"device/{cfg['serial']}/report")
            client.publish(f"device/{cfg['serial']}/request", json.dumps({
                "pushing": {"sequence_id": "0", "command": "pushall"}
            }))
        else:
            print(f"  [{cfg['printer_label']}] CONEXION FALLIDA (rc={rc}) - revisa el codigo de acceso / serie")

    def on_message(client, userdata, msg):
        got["flag"] = True

    client = mqtt.Client(client_id=f"bambu_test_{cfg['serial']}_{int(time.time())}", protocol=mqtt.MQTTv311)
    client.username_pw_set("bblp", cfg["access_code"])
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Conectando a {cfg['printer_label']} ({cfg['printer_ip']}:8883) ...")
    try:
        client.connect(cfg["printer_ip"], 8883, keepalive=10)
    except (TimeoutError, OSError) as e:
        print(f"  No se pudo alcanzar {cfg['printer_ip']}:8883 ({e}).")
        return False

    client.loop_start()
    time.sleep(6)
    client.loop_stop()
    client.disconnect()

    if not got["flag"]:
        print(f"  [{cfg['printer_label']}] No respondio en 6s. Revisa que este prendida, en la misma red,")
        print("  y que 'LAN Only Mode' este activado en Configuracion > Red.")
        return False

    print(f"  [{cfg['printer_label']}] OK")
    return True


results = [test_one(cfg) for cfg in PRINTERS]

print()
if not any(results):
    print("Ninguna impresora respondio. Revisa IP / codigo de acceso / numero de serie en config.json.")
    sys.exit(1)
if not all(results):
    print("Al menos una impresora conectada, pero otra(s) fallaron - revisa esas mas tarde si hace falta.")
else:
    print(f"OK: las {len(results)} impresora(s) configurada(s) respondieron correctamente.")
