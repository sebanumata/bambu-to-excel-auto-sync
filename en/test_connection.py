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
            print(f"  [{cfg['printer_label']}] CONNECTION FAILED (rc={rc}) - check the access code / serial")

    def on_message(client, userdata, msg):
        got["flag"] = True

    client = mqtt.Client(client_id=f"bambu_test_{cfg['serial']}_{int(time.time())}", protocol=mqtt.MQTTv311)
    client.username_pw_set("bblp", cfg["access_code"])
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to {cfg['printer_label']} ({cfg['printer_ip']}:8883) ...")
    try:
        client.connect(cfg["printer_ip"], 8883, keepalive=10)
    except (TimeoutError, OSError) as e:
        print(f"  Could not reach {cfg['printer_ip']}:8883 ({e}).")
        return False

    client.loop_start()
    time.sleep(6)
    client.loop_stop()
    client.disconnect()

    if not got["flag"]:
        print(f"  [{cfg['printer_label']}] No response in 6s. Check that it's on, on the same network,")
        print("  and that 'LAN Only Mode' is enabled under Settings > Network.")
        return False

    print(f"  [{cfg['printer_label']}] OK")
    return True


results = [test_one(cfg) for cfg in PRINTERS]

print()
if not any(results):
    print("No printer responded. Check the IP / access code / serial number in config.json.")
    sys.exit(1)
if not all(results):
    print("At least one printer connected, but other(s) failed - you can check those later if needed.")
else:
    print(f"OK: all {len(results)} configured printer(s) responded correctly.")
