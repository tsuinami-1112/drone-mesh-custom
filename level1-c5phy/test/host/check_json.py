#!/usr/bin/env python3
"""Validate the JSON lines printed by test_level1: each must parse, carry the
keys mesh-mapper.py keys on, and the mesh variants must fit one Meshtastic
text message as the v2 station proved it (191 bytes)."""
import json
import sys

MESH_MAX = 191
ok = True
count = 0
with open(sys.argv[1]) as fh:
    for lineno, line in enumerate(fh, 1):
        line = line.rstrip("\n")
        if not line.startswith("JSON_"):
            continue
        tag, _, payload = line.partition(" ")
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as exc:
            print(f"line {lineno}: invalid JSON ({exc}): {payload}")
            ok = False
            continue
        count += 1
        if "heartbeat" in obj:
            need = ("node_id", "receiver")
        else:
            need = ("type", "mac", "node_id", "freq_mhz", "rssi", "bearing_deg")
        for key in need:
            if key not in obj:
                print(f"line {lineno}: missing {key}: {payload}")
                ok = False
        if tag == "JSON_MESH" and len(payload) > MESH_MAX:
            print(f"line {lineno}: mesh JSON too long ({len(payload)} > {MESH_MAX})")
            ok = False
if count == 0:
    print("no JSON lines found")
    ok = False
print(f"check_json: {count} JSON lines {'OK' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
