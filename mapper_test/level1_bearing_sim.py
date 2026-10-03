#!/usr/bin/env python3
"""
Level 1 bearing simulator for mesh-mapper.py
============================================

Fakes two or three level 1 stations (level1-c5phy firmware: XIAO ESP32-C5 as
a 5.8 GHz analog video receiver with four patch antennas) watching one drone
that broadcasts nothing but its FPV video link. Each station reports exactly
what the firmware reports - a {"type":"analog_fm", ...} record with a bearing
relative to the box's face N - and a heartbeat, over the mapper's HTTP API,
so the LEVEL 1 STATIONS panel, the bearing rays and the bearing-fix
intersection can be exercised without hardware.

    python3 level1_bearing_sim.py                     # 3 stations, 5 minutes
    python3 level1_bearing_sim.py --stations 2 --duration 2 --noise-deg 10

The stations are placed in a triangle around --center and registered with
their positions and headings through /api/stations (the headings are
deliberately non-zero: the mapper must rotate the box-relative bearings).
The second station labels the carrier B1 (5733 MHz) instead of R3 (5732) to
exercise the overlapping-channel merge. The script prints the mapper's fix
against the true drone position every report.
"""
import argparse
import json
import math
import random
import time
import urllib.request
import urllib.error

R_EARTH = 6371000.0


def destination(lat, lon, bearing_deg, dist_m):
    br = math.radians(bearing_deg)
    la1, lo1 = math.radians(lat), math.radians(lon)
    d = dist_m / R_EARTH
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(br))
    lo2 = lo1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def initial_bearing(lat1, lon1, lat2, lon2):
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def haversine_m(lat1, lon1, lat2, lon2):
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dla = la2 - la1
    dlo = math.radians(lon2 - lon1)
    a = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


class Api:
    def __init__(self, base):
        self.base = base.rstrip('/')

    def post(self, path, obj):
        data = json.dumps(obj).encode()
        req = urllib.request.Request(self.base + path, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode() or '{}')

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return json.loads(r.read().decode() or '{}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--duration', type=float, default=5.0, help='minutes')
    ap.add_argument('--interval', type=float, default=2.0, help='seconds between reports')
    ap.add_argument('--stations', type=int, default=3, choices=(2, 3))
    ap.add_argument('--center', default='33.4942,-111.9261', help='lat,lon of the test area')
    ap.add_argument('--spacing', type=float, default=600.0, help='station spacing, metres')
    ap.add_argument('--noise-deg', type=float, default=6.0, help='1-sigma bearing noise per report')
    ap.add_argument('--no-register', action='store_true', help='do not set station positions (exercise the "not placed" path)')
    args = ap.parse_args()

    clat, clon = (float(v) for v in args.center.split(','))
    api = Api(f'http://{args.host}:{args.port}')
    rng = random.Random(7)

    # Stations on a triangle around the centre, faces deliberately not north.
    plan = [('RX01', 0.0, 'R', 3, 5732, 15.0), ('RX02', 120.0, 'B', 1, 5733, 350.0), ('RX03', 240.0, 'R', 3, 5732, 42.0)]
    stations = []
    for i in range(args.stations):
        node_id, az, band, ch, freq, heading = plan[i]
        lat, lon = destination(clat, clon, az, args.spacing / math.sqrt(3))
        stations.append({'node_id': node_id, 'lat': lat, 'lon': lon, 'heading': heading, 'band': band, 'ch': ch, 'freq': freq})

    for st in stations:
        hb = {'heartbeat': True, 'node_id': st['node_id'], 'receiver': 'c5phy', 'hw': 'v3', 'scanning': True,
              'channels': 40, 'sectors': 4, 'heading': int(st['heading']), 'threshold_dbm': -87.0, 'video_seen': 0,
              'gain_max': 62, 'bw40': 1, 'tune_fail': 0, 'cap_err': 0, 'sweeps': 0, 'nf_dbm': -98, 'temp_c': 38.5,
              'uptime_s': 0, 'seq': 0}
        api.post('/api/detections', hb)
        if not args.no_register:
            api.post('/api/stations', {'node_id': st['node_id'], 'name': st['node_id'] + ' sim',
                                       'lat': st['lat'], 'lon': st['lon'], 'heading_deg': st['heading']})
        print(f"station {st['node_id']}: {st['lat']:.6f},{st['lon']:.6f} heading {st['heading']:.0f} deg")

    t0 = time.time()
    seq = 0
    sweeps = 0
    last_hb = t0
    print(f"flying one analog FPV drone around {clat:.5f},{clon:.5f} for {args.duration} min ...")
    while time.time() - t0 < args.duration * 60:
        t = time.time() - t0
        # a slow loop 400-900 m from the centre
        ang = (t / 180.0) * 360.0
        rad = 650 + 250 * math.sin(t / 47.0)
        dlat, dlon = destination(clat, clon, ang, rad)
        seq += 1
        sweeps += 1
        for st in stations:
            dist = haversine_m(st['lat'], st['lon'], dlat, dlon)
            true_brg = initial_bearing(st['lat'], st['lon'], dlat, dlon)
            rel = (true_brg - st['heading'] + rng.gauss(0, args.noise_deg)) % 360.0
            rssi_dbm = -45 - 20 * math.log10(max(dist, 30) / 50.0) + rng.gauss(0, 1.5)
            level = max(0.0, rssi_dbm + 95)
            sector = int(((rel + 45) % 360) // 90)
            sectors = [round(rssi_dbm - (0 if s == sector else 8 + 6 * rng.random()), 1) for s in range(4)]
            det = {
                'type': 'analog_fm', 'receiver': 'c5phy', 'hw': 'v3',
                'mac': f"AF:00:{ord(st['band']):02X}:{st['ch']:02X}:{st['freq'] >> 8:02X}:{st['freq'] & 0xFF:02X}",
                'freq_mhz': st['freq'], 'band': st['band'], 'ch': st['ch'],
                'rssi': int(round(rssi_dbm)), 'rssi_dbm': round(rssi_dbm, 1),
                'rssi_raw': int(max(0, min(1023, (rssi_dbm + 110) / 80 * 1023))),
                'rssi_min': int(round(rssi_dbm - 2)), 'rssi_max': int(round(rssi_dbm + 2)), 'rssi_n': 3,
                'level_db': round(level, 1), 'gain': 62 if level < 20 else 50, 'q_phase': 70 + int(10 * rng.random()),
                'cfo_khz': 1840, 'carrier': 'fm', 'sectors': sectors, 'sector': sector,
                'bearing_deg': int(round(rel)) % 360, 'bearing_sigma_deg': int(round(max(8.0, args.noise_deg * 1.5))),
                'heading': int(st['heading']), 'freq_peak': st['freq'] + 2,
                'video': 'NTSC', 'sync_hz': 15736, 'field_hz': 60, 'sync_q': 88, 'sync_score': 91, 'video_windows': 8,
                'fp': f"NTSC/15736/{st['freq'] + 2}", 'basic_id': f"5.8G-{st['band']}{st['ch']}-{st['freq']}MHz",
                'node_id': st['node_id'], 'seq': seq,
            }
            try:
                api.post('/api/detections', det)
            except urllib.error.URLError as e:
                print('post failed:', e)
                time.sleep(2)
                continue
        if time.time() - last_hb > 30:
            last_hb = time.time()
            for st in stations:
                api.post('/api/detections', {'heartbeat': True, 'node_id': st['node_id'], 'receiver': 'c5phy', 'hw': 'v3',
                                             'scanning': True, 'heading': int(st['heading']), 'sweeps': sweeps,
                                             'nf_dbm': -98, 'temp_c': 39.0, 'uptime_s': int(t)})
        # what did the mapper make of it?
        try:
            tracked = api.get('/api/detections')
            fixes = [d for d in tracked.values() if d.get('type') == 'analog_fm']
            for d in fixes:
                if d.get('pos_src') == 'bearing_fix':
                    err = haversine_m(d['drone_lat'], d['drone_long'], dlat, dlon)
                    print(f"t={t:5.0f}s {d['mac']} fix {d['drone_lat']:.5f},{d['drone_long']:.5f} "
                          f"±{d.get('fix_error_m')} m from {d.get('fix_stations')} | true error {err:.0f} m")
                else:
                    print(f"t={t:5.0f}s {d['mac']} bearing only ({len(d.get('bearings', []))} bearings, stations {d.get('fix_stations')})")
        except Exception as e:
            print('status failed:', e)
        time.sleep(args.interval)
    print('done')


if __name__ == '__main__':
    main()
