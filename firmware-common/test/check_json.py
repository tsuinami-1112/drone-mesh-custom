#!/usr/bin/env python3
"""Validate the JSON lines emitted by test_detect: each must parse, carry the
mandatory keys mesh-mapper.py relies on, and the mesh-sized variants must fit
a Meshtastic text message."""
import json
import sys

MESH_MAX = 230

ok = True
count = 0
with open(sys.argv[1]) as fh:
    for lineno, line in enumerate(fh, 1):
        line = line.rstrip("\n")
        if not line.startswith("JSON"):
            continue
        tag, _, payload = line.partition(" ")
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as exc:
            print(f"line {lineno}: invalid JSON ({exc}): {payload}")
            ok = False
            continue
        count += 1
        for key in ("mac", "rssi"):
            if key not in obj:
                print(f"line {lineno}: missing {key}: {payload}")
                ok = False
        if tag == "JSON_MESH" and len(payload) > MESH_MAX:
            print(f"line {lineno}: mesh JSON too long ({len(payload)} > {MESH_MAX})")
            ok = False
        if "drone_lat" in obj and not isinstance(obj["drone_lat"], (int, float)):
            print(f"line {lineno}: drone_lat not numeric")
            ok = False

if count == 0:
    print("no JSON lines found")
    ok = False
print(f"check_json: {count} JSON lines {'OK' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
