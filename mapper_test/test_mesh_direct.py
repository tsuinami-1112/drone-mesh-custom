#!/usr/bin/env python3
"""
End-to-end test of mesh-mapper.py reading Meshtastic radios directly
====================================================================

Starts a fake Meshtastic radio (fake_meshtastic_radio.py) on a pseudo-terminal
and on TCP, runs mesh-mapper.py from a scratch copy with `--mesh <pty> --mesh
tcp:127.0.0.1:<port>`, so every packet reaches the mapper through both links
(USB and WiFi), plays every message format the current firmware puts on the
mesh, and checks what the mapper made of each:

  - node mode (remote_node) JSON detection in one packet, split over two
    packets (also with each half heard by a different radio), and two lines
    merged into one packet
  - the same drone from a second field station inside 500 ms (dropped, as the
    ESP32 home node would)
  - level 1 stations: one flashed with its position and heading, placed from
    the position in its heartbeat (real lines built by the level 1 firmware's
    report.c), one older station placed by hand; their analog_fm bearing
    reports for the same emitter inside 500 ms (both kept, crossed into a
    fix); a position saved by hand overriding the flashed one, and clearing
    it going back; a station placed by hand before it reported a position
    staying there when it later reports one; heartbeat status merged across
    heartbeats that carry different fields
  - the standalone firmwares' text alerts: "Drone: ...", the C5's
    "Drone[5G]: ...", "Pilot: ..." and "Possible drone (...) ..."
  - chat text and a message on another channel (ignored)
  - power telemetry (reported per node by /api/meshtastic)
  - the TCP radio dropping off and coming back
  - the mapper never transmitting a text message

    pip install -r ../requirements.txt
    python3 test_mesh_direct.py
"""
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from fake_meshtastic_radio import FakeRadio, l1_mesh_heartbeat  # noqa: E402
from meshtastic.protobuf import portnums_pb2  # noqa: E402

FS1, FS2, RX1, RX3, SA, PHONE = 0xA1B2C3D4, 0xB2C3D4E5, 0xC3D4E5F6, 0xD4E5F6A7, 0xE5F6A7B8, 0x0F0F0F0F
RXL, RXB = 0x17171717, 0x18181818
DRONE = (-33.8600, 151.2100)
RX01_POS = (-33.8700, 151.2000)                     # older firmware: no position, placed by hand
RX03_POS, RX03_HEADING = (-33.864512, 151.208834), 135   # flashed into RX03 (Station setup)

# Mesh heartbeats exactly as the level 1 firmware builds them (level1 branch,
# level1-c5phy/src/report.c report_heartbeat_json(..., full=0), commit 54314fa)
# for a station flashed with NODE_ID RX03, STATION_LAT -33.864512,
# STATION_LON 151.208834 and STATION_HEADING_DEG 135. The ones carrying the
# position (the first 3 after boot, then every 5th) drop uptime_s and the
# counters to stay within 191 bytes.
L1_HB_RX03_POS = ('{"heartbeat":true,"node_id":"RX03","receiver":"c5phy","hw":"v3","heading":135,'
                  '"lat":-33.864512,"lon":151.208834,"scanning":true,"sweeps":10,"video_seen":0,'
                  '"nf_dbm":-96,"temp_c":38.6}')
L1_HB_RX03_NOPOS = ('{"heartbeat":true,"node_id":"RX03","receiver":"c5phy","hw":"v3","heading":135,'
                    '"scanning":true,"sweeps":431,"video_seen":23,"nf_dbm":-96,"temp_c":41.3,"uptime_s":860,'
                    '"tune_fail":0,"cap_err":0}')
L1_HB_LONG_POS = ('{"heartbeat":true,"node_id":"STATION-NORTH-TOWER-01","receiver":"c5phy","hw":"v3",'
                  '"heading":135,"lat":-33.864512,"lon":151.208834,"scanning":true,"sweeps":1296000,'
                  '"video_seen":1234}')

failures = []


def check(cond, what):
    print(('  ok   ' if cond else '  FAIL ') + what)
    if not cond:
        failures.append(what)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def api(base, path, obj=None):
    req = urllib.request.Request(base + path, data=json.dumps(obj).encode() if obj is not None else None,
                                 headers={'Content-Type': 'application/json'},
                                 method='POST' if obj is not None else 'GET')
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def wait_for(fn, timeout=30, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(step)
    return None


def detections(base):
    d = api(base, '/api/detections')
    items = d if isinstance(d, list) else list(d.values()) if isinstance(d, dict) else []
    return {x['mac'].lower(): x for x in items if isinstance(x, dict) and x.get('mac')}


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360)


def j(obj):
    return json.dumps(obj, separators=(',', ':'))


def main():
    radio = FakeRadio()
    for num, ln, sn in [(FS1, 'Field station 1', 'FS1'), (FS2, 'Field station 2', 'FS2'),
                        (RX1, 'Level 1 RX01', 'RX01'), (RX3, 'Level 1 RX03', 'RX03'),
                        (RXL, 'Level 1 north tower', 'NT01'), (RXB, 'Level 1 RX09', 'RX09'),
                        (SA, 'Standalone detector', 'SA1'), (PHONE, 'Someone', 'ME')]:
        radio.add_node(num, ln, sn)
    tcp_port = radio.serve_tcp(free_port())
    pty_path = radio.serve_pty()

    work = tempfile.mkdtemp(prefix='mesh-direct-')
    shutil.copy(os.path.join(REPO, 'mesh-mapper.py'), work)
    shutil.copytree(os.path.join(REPO, 'static'), os.path.join(work, 'static'))
    web = free_port()
    base = f'http://127.0.0.1:{web}'
    log = open(os.path.join(work, 'mapper.out'), 'w')
    proc = subprocess.Popen([sys.executable, os.path.join(work, 'mesh-mapper.py'), '--web-port', str(web),
                             '--no-auto-start', '--mesh', pty_path, '--mesh', f'tcp:127.0.0.1:{tcp_port}'],
                            cwd=work, stdout=log, stderr=subprocess.STDOUT)
    try:
        print(f'mapper on {base}, radio on {pty_path} and tcp:127.0.0.1:{tcp_port} (log: {work}/mapper.out)')

        print('\nconnection')
        st = wait_for(lambda: (lambda s: s if len(s['links']) == 2 and all(l['connected'] for l in s['links']) else None)(
            api(base, '/api/meshtastic')), timeout=60)
        check(st is not None, 'both links (USB pty and TCP) connect')
        if st is None:
            return
        check(all((l.get('radio') or {}).get('long_name') == 'Home radio' for l in st['links']),
              'each link reports the radio it is connected to')
        statuses = api(base, '/api/serial_status')['statuses']
        check(any(k.startswith('mesh radio ') and v for k, v in statuses.items()),
              'the USB status list shows the mesh radios')

        print('\nlevel 2 field stations (node mode JSON)')
        rid = {"mac": "aa:aa:aa:00:00:01", "rssi": -62, "node_id": "A1B2", "drone_lat": -33.8610,
               "drone_long": 151.2050, "drone_altitude": 120, "pilot_lat": -33.8620, "pilot_long": 151.2040,
               "basic_id": "1581F5FHB229F00202DR", "op_id": "FIN87astrdge12k8", "id_type": 1, "src": "odid_ble5",
               "ua_type": 2, "eu_cat": 1, "eu_class": 2}
        radio.serial_line(FS1, j(rid))
        dup = dict(rid, node_id="B2C3", rssi=-80)
        radio.serial_line(FS2, j(dup))                       # same drone, second station, < 500 ms later
        long_rec = {"mac": "bb:bb:bb:00:00:02", "rssi": -70, "node_id": "A1B2", "drone_lat": -33.8650,
                    "drone_long": 151.2150, "drone_altitude": 60, "basic_id": "1668A0000000000ABCDE",
                    "id_type": 1, "src": "odid_nan", "desc": "survey flight over the northern ridge line"}
        line = j(long_rec)
        radio.text(FS1, (line[:90]).encode())                # split across two packets
        time.sleep(0.3)
        radio.text(FS1, (line[90:] + '\r\n').encode())
        cross = j(dict(long_rec, mac="bc:bc:bc:00:00:09"))
        radio.text(FS1, cross[:90].encode(), via='pty')      # first half heard by the USB radio only,
        time.sleep(0.3)
        radio.text(FS1, (cross[90:] + '\r\n').encode(), via='tcp')   # second half by the WiFi one
        merged = j({"mac": "cc:cc:cc:00:00:03", "rssi": -75, "node_id": "B2C3", "drone_lat": -33.8580,
                    "drone_long": 151.2080, "basic_id": "ABC123", "id_type": 1, "src": "odid_bcn"}) + '\r\n' + \
            j({"mac": "dd:dd:dd:00:00:04", "rssi": -81, "node_id": "B2C3", "src": "wifi", "vendor": "DJI",
               "model": "Mini 2", "ssid": "Mini2-0A1B", "conf": "med"}) + '\r\n'
        radio.text(FS2, merged.encode())                     # two lines in one packet

        dets = wait_for(lambda: (lambda d: d if {'aa:aa:aa:00:00:01', 'bb:bb:bb:00:00:02', 'bc:bc:bc:00:00:09',
                                                 'cc:cc:cc:00:00:03', 'dd:dd:dd:00:00:04'} <= set(d) else None)(
            detections(base)))
        dets = dets or detections(base)
        a = dets.get('aa:aa:aa:00:00:01', {})
        check(a.get('basic_id') == '1581F5FHB229F00202DR' and a.get('drone_lat') == -33.861,
              'single-packet detection decoded with its position and Remote ID')
        check(a.get('node_id') == 'A1B2' and a.get('mesh_from') == '!a1b2c3d4',
              'first report wins; the record says which station and radio node sent it')
        check(isinstance(a.get('mesh_snr'), (int, float)) and a.get('mesh_hops') == 1,
              'mesh SNR and hop count are attached')
        check(dets.get('bb:bb:bb:00:00:02', {}).get('desc') == long_rec['desc'],
              'a line split across two packets is re-joined')
        check(dets.get('bc:bc:bc:00:00:09', {}).get('desc') == long_rec['desc'],
              'a split line whose halves arrive through different radios is re-joined')
        check('cc:cc:cc:00:00:03' in dets and dets.get('dd:dd:dd:00:00:04', {}).get('src') == 'wifi',
              'two lines in one packet are both read (Remote ID + fingerprint)')

        print('\nlevel 1 stations (flashed position, heartbeats, analog_fm bearings)')
        twin = [l1_mesh_heartbeat('RX03', 135, RX03_POS, sweeps=10, video_seen=0, nf_dbm=-95.7, temp_c=38.6,
                                  uptime_s=20),
                l1_mesh_heartbeat('RX03', 135, None, sweeps=431, video_seen=23, nf_dbm=-96.2, temp_c=41.3,
                                  uptime_s=860, alias_drop=1),
                l1_mesh_heartbeat('STATION-NORTH-TOWER-01', 135, RX03_POS, sweeps=1296000, video_seen=1234,
                                  nf_dbm=-96, temp_c=40.0, uptime_s=2592000, cap_err=12, alias_drop=3)]
        check(twin == [L1_HB_RX03_POS, L1_HB_RX03_NOPOS, L1_HB_LONG_POS],
              "the fake radio's level 1 heartbeat matches the firmware's lines byte for byte")

        def stations():
            return api(base, '/api/stations')

        # RX01 runs firmware without a position; RX03 was flashed with one, and the first
        # heartbeat this mapper hears from it is one between the position heartbeats
        radio.serial_line(RX1, l1_mesh_heartbeat('RX01', 0, None, sweeps=12, nf_dbm=-98, uptime_s=40))
        radio.serial_line(RX3, L1_HB_RX03_NOPOS)
        reg = wait_for(lambda: (lambda s: s if {'RX01', 'RX03'} <= set(s['stations']) else None)(stations()))
        check(reg is not None, 'both level 1 stations register from their heartbeats')
        if reg:
            r1, r3 = reg['stations']['RX01'], reg['stations']['RX03']
            check(r1.get('lat') is None and r3.get('lat') is None and r3.get('position_auto') is True,
                  'a heartbeat without a position leaves the station unplaced, waiting for one')
        radio.serial_line(RX3, L1_HB_RX03_POS)
        placed = wait_for(lambda: (lambda s: s if s['stations']['RX03'].get('lat') is not None else None)(stations()))
        r3 = (placed or {}).get('stations', {}).get('RX03', {})
        check((r3.get('lat'), r3.get('lon')) == RX03_POS and r3.get('position_auto') is True,
              'the flashed station is placed from the position in its mesh heartbeat, no API needed')
        check(r3.get('heading_deg') == RX03_HEADING and r3.get('heading_auto') is True,
              'its flashed heading is taken from the same heartbeat')
        stt = stations()['status'].get('RX03', {})
        check(stt.get('uptime_s') == 860 and stt.get('temp_c') == 38.6 and stt.get('sweeps') == 10,
              'status is merged: uptime_s from the earlier heartbeat survives one that carries the position')
        check(str(stt.get('source', '')).startswith('mesh radio '), 'the station status says it came over the mesh')

        api(base, '/api/stations', {'node_id': 'RX01', 'lat': RX01_POS[0], 'lon': RX01_POS[1], 'heading_deg': 0})
        check(stations()['stations']['RX01'].get('position_auto') is False,
              'the older station is placed by hand through the API')
        rx03_rel = (bearing(*RX03_POS, *DRONE) - RX03_HEADING) % 360     # relative to face N, as reported
        for num, nid, rel in ((RX1, 'RX01', bearing(*RX01_POS, *DRONE)), (RX3, 'RX03', rx03_rel)):
            radio.serial_line(num, j({"type": "analog_fm", "mac": "AF:00:52:03:16:64", "node_id": nid,
                                      "freq_mhz": 5732, "band": "R", "ch": 3, "rssi": -68, "bearing_deg": rel,
                                      "bearing_sigma_deg": 8, "video": "NTSC", "fp": "NTSC/15736/5734"}))
        fix = wait_for(lambda: (lambda d: d if d.get('pos_src') == 'bearing_fix' else None)(
            detections(base).get('af:00:52:03:16:64', {})))
        check(fix is not None and {'RX01', 'RX03'} <= set(fix.get('fix_stations') or []),
              'both bearings (hand-placed and flashed station) pass the dedup and cross into a position fix')
        if fix:
            err = math.hypot((fix['drone_lat'] - DRONE[0]) * 111320,
                             (fix['drone_long'] - DRONE[1]) * 111320 * math.cos(math.radians(DRONE[0])))
            check(err < 150, f'fix lands {err:.0f} m from the true position')

        moved = (-33.864600, 151.208900)
        api(base, '/api/stations', {'node_id': 'RX03', 'lat': moved[0], 'lon': moved[1]})
        radio.serial_line(RX3, L1_HB_RX03_POS)
        time.sleep(2.0)
        r3 = stations()['stations']['RX03']
        check((r3.get('lat'), r3.get('lon')) == moved and r3.get('position_auto') is False
              and (r3.get('rep_lat'), r3.get('rep_lon')) == RX03_POS,
              'a position saved by hand overrides the flashed one, and later heartbeats leave it alone')
        api(base, '/api/stations', {'node_id': 'RX03', 'lat': '', 'lon': ''})
        r3 = stations()['stations']['RX03']
        check((r3.get('lat'), r3.get('lon')) == RX03_POS and r3.get('position_auto') is True,
              'clearing both fields goes back to the flashed position')
        api(base, '/api/stations', {'node_id': 'RX03', 'name': 'North ridge'})
        r3 = stations()['stations']['RX03']
        check(r3.get('name') == 'North ridge' and r3.get('position_auto') is True and
              (r3.get('lat'), r3.get('lon')) == RX03_POS, 'renaming a flashed station keeps it following its position')
        # RX01 was placed by hand before it reported any position; reflashed with one, it stays put
        later = (round(DRONE[0] + 0.004, 6), round(DRONE[1] - 0.004, 6))
        radio.serial_line(RX1, l1_mesh_heartbeat('RX01', 0, later, sweeps=900, nf_dbm=-98, uptime_s=1800))
        time.sleep(2.0)
        r1 = stations()['stations']['RX01']
        check((r1.get('lat'), r1.get('lon')) == RX01_POS and r1.get('position_auto') is False
              and (r1.get('rep_lat'), r1.get('rep_lon')) == later,
              'a station placed by hand before it reported a position stays there when it later reports one')

        radio.serial_line(RXL, L1_HB_LONG_POS)
        radio.serial_line(RXB, j({"heartbeat": True, "node_id": "RX09", "receiver": "c5phy", "hw": "v3",
                                  "heading": 0, "lat": True, "lon": 151.2}))
        got = wait_for(lambda: (lambda s: s if {'STATION-NORTH-TOWER-01', 'RX09'} <= set(s['stations']) else None)(
            stations()))
        st_all = (got or {}).get('stations', {})
        check((st_all.get('STATION-NORTH-TOWER-01', {}).get('lat'),
               st_all.get('STATION-NORTH-TOWER-01', {}).get('lon')) == RX03_POS,
              'the longest firmware heartbeat (22-character NODE_ID) still carries the position')
        check('RX09' in st_all and st_all['RX09'].get('lat') is None,
              'a heartbeat with an invalid position (JSON true) registers the station unplaced')

        print('\nstandalone detector text alerts')
        radio.serial_line(SA, "Drone: ee:ee:ee:00:00:05 RSSI:-71 ID:1581F5FHB229F00999XX OP:GBR-OP-ABC123DEF456 "
                              "https://maps.google.com/?q=-33.855000,151.195000")
        time.sleep(1.0)
        radio.serial_line(SA, "Pilot: https://maps.google.com/?q=-33.856000,151.194000")
        radio.serial_line(SA, "Possible drone (Holy Stone HS720) 12:34:56:78:9a:bc RSSI:-80")
        radio.serial_line(SA, "Drone[5G]: 5a:5a:5a:00:00:06 RSSI:-77 ID:XYZ789")
        dets = wait_for(lambda: (lambda d: d if d.get('ee:ee:ee:00:00:05', {}).get('pilot_lat') and
                                 '12:34:56:78:9a:bc' in d and '5a:5a:5a:00:00:06' in d else None)(detections(base)))
        dets = dets or detections(base)
        e = dets.get('ee:ee:ee:00:00:05', {})
        check(e.get('basic_id') == '1581F5FHB229F00999XX' and e.get('op_id') == 'GBR-OP-ABC123DEF456'
              and e.get('drone_lat') == -33.855, '"Drone:" alert gives MAC, IDs and position')
        check(e.get('pilot_lat') == -33.856 and e.get('drone_lat') == -33.855,
              '"Pilot:" alert adds the pilot without losing the drone position')
        fp = dets.get('12:34:56:78:9a:bc', {})
        check(fp.get('src') == 'fingerprint' and fp.get('vendor') == 'Holy Stone HS720',
              '"Possible drone" alert becomes a fingerprint entry')
        check(dets.get('5a:5a:5a:00:00:06', {}).get('rf_band') == '5G', 'C5 "Drone[5G]:" alert is read')

        print('\nnoise the mapper must ignore')
        radio.text(PHONE, b'hello mesh, anyone on?')
        radio.text(FS1, (j({"mac": "ff:ff:ff:00:00:07", "rssi": -50, "drone_lat": -33.9, "drone_long": 151.3,
                            "basic_id": "OTHERCH"}) + '\r\n').encode(), channel=1)
        radio.telemetry(FS1, power={'ch1_voltage': 13.1, 'ch1_current': 182.0})
        radio.telemetry(FS1, device={'battery_level': 101, 'voltage': 5.02, 'channel_utilization': 4.5,
                                     'air_util_tx': 1.2, 'uptime_seconds': 3600})
        time.sleep(2.5)
        dets = detections(base)
        check('ff:ff:ff:00:00:07' not in dets, 'a detection on another channel is ignored')
        st = api(base, '/api/meshtastic')
        tot = {k: sum(l['stats'][k] for l in st['links']) for k in st['links'][0]['stats']}
        check(tot['other_channel'] >= 1 and tot['unparsed'] >= 1, f'chat and other-channel text counted, not mapped ({tot})')
        check(tot['duplicates'] >= 1, 'the second station\'s copy of the same drone was dropped')
        check(tot['repeats'] >= 10, 'each packet heard on both links is processed once')
        node = st['nodes'].get('!a1b2c3d4') or {}
        check((node.get('power') or {}).get('ch1Voltage') == 13.1 and node.get('voltage') == 5.02,
              'per-station battery voltage (power telemetry) shows in /api/meshtastic')

        print('\nreconnect')
        radio.drop_tcp_clients()
        back = wait_for(lambda: radio.connected_clients() >= 2 and all(
            l['connected'] for l in api(base, '/api/meshtastic')['links']), timeout=45)
        check(bool(back), 'the TCP link comes back after the radio drops it')
        radio.serial_line(FS1, j({"mac": "ab:ab:ab:00:00:08", "rssi": -66, "node_id": "A1B2", "drone_lat": -33.866,
                                  "drone_long": 151.201, "basic_id": "AFTERDROP", "id_type": 1, "src": "odid_ble"}))
        check(bool(wait_for(lambda: 'ab:ab:ab:00:00:08' in detections(base))), 'detections flow after the reconnect')

        print('\nthe mapper only listens')
        sent_text = [m for m in radio.received if m.WhichOneof('payload_variant') == 'packet'
                     and m.packet.decoded.portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP]
        check(not sent_text, f'no text message was sent into the mesh ({len(radio.received)} client messages seen)')
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    print()
    if failures:
        print(f'FAILED: {len(failures)} check(s); mapper log in {work}/mapper.out')
        sys.exit(1)
    shutil.rmtree(work, ignore_errors=True)
    print('PASS')


if __name__ == '__main__':
    main()
