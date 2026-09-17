"""Loads one or more printers from config.json.

Supports two formats:
  - Single printer (default):
      {"printer_ip": "...", "access_code": "...", "serial": "...", "printer_label": "..."}
  - Multiple printers:
      {"printers": [
          {"printer_ip": "...", "access_code": "...", "serial": "...", "printer_label": "..."},
          {"printer_ip": "...", "access_code": "...", "serial": "...", "printer_label": "..."}
      ]}
"""
import json
from pathlib import Path


def load_printers(config_path: Path) -> list[dict]:
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    printers = cfg["printers"] if "printers" in cfg else [cfg]

    for i, p in enumerate(printers, start=1):
        for field in ("printer_ip", "access_code", "serial"):
            if not p.get(field):
                raise ValueError(f"Missing '{field}' for printer #{i} in config.json")
        p.setdefault("printer_label", f"Printer {i} ({p['serial']})")

    return printers
