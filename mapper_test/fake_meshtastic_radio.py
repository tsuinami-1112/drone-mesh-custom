#!/usr/bin/env python3
"""
Fake Meshtastic radio for mesh-mapper.py
========================================

Speaks enough of Meshtastic's client stream protocol (the 0x94 0xC3 framed
protobufs a radio sends over its USB port or TCP port 4403) for the
meshtastic Python library, and so `mesh-mapper.py --mesh`, to connect to it.
It then plays the text messages that field stations' serial modules put on
the mesh, so the direct-radio path can be exercised without hardware.

    python3 fake_meshtastic_radio.py --tcp 4403 --demo
        then: python3 mesh-mapper.py --mesh tcp:127.0.0.1:4403
    python3 fake_meshtastic_radio.py --pty --demo
        prints the /dev/pts path to pass to --mesh

--demo loops a scenario: a Remote ID drone circling (node mode JSON from two
field stations), a 5.8 GHz emitter heard by two level 1 stations, and the
plain-text alerts of a standalone detector. The level 1 stations behave as if
flashed with their position and heading (level1 branch, Station setup): their
heartbeats carry lat/lon, so the mapper places them by itself and their
bearings cross into a fix. --mapper URL places them by hand through the
mapper's API instead, as a station without a flashed position needs.

The radio records everything a client sends it (`received`), which
test_mesh_direct.py uses to prove the mapper never transmits.
"""
import argparse
import json
import math
import os
import pty
import random
import select
import socket
import threading
import time
import tty
import urllib.request

from meshtastic.protobuf import channel_pb2, mesh_pb2, portnums_pb2, telemetry_pb2

START1, START2 = 0x94, 0xC3
BROADCAST = 0xFFFFFFFF


def frame(msg):
    body = msg.SerializeToString()
    return bytes([START1, START2, len(body) >> 8, len(body) & 0xFF]) + body


class FrameParser:
    """Pulls ToRadio payloads out of a byte stream, skipping wake bytes and noise."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            i = self.buf.find(bytes([START1, START2]))
            if i < 0:
                self.buf = self.buf[-1:] if self.buf[-1:] == bytes([START1]) else bytearray()
                return out
            del self.buf[:i]
            if len(self.buf) < 4:
                return out
            n = (self.buf[2] << 8) | self.buf[3]
            if n > 512:
                del self.buf[:2]
                continue
            if len(self.buf) < 4 + n:
                return out
            out.append(bytes(self.buf[4:4 + n]))
            del self.buf[:4 + n]


class _Client:
    def __init__(self, radio, write, name):
        self.radio, self.write, self.name = radio, write, name
        self.parser = FrameParser()

    def on_bytes(self, data):
        for payload in self.parser.feed(data):
            msg = mesh_pb2.ToRadio()
            try:
                msg.ParseFromString(payload)
            except Exception:
                continue
            self.radio.received.append(msg)
            if msg.WhichOneof('payload_variant') == 'want_config_id':
                for f in self.radio.config_frames(msg.want_config_id):
                    self.write(f)


class FakeRadio:
    def __init__(self, my_num=0x0BA5E001, long_name='Home radio', short_name='HOME', channel_name='dronemesh'):
        self.my_num = my_num
        self.channel_name = channel_name
        self.nodes = {my_num: (long_name, short_name)}
        self.received = []           # every ToRadio a client sent
        self.clients = []
        self.lock = threading.Lock()
        self._pkt_id = random.randint(1, 1 << 30)

    def add_node(self, num, long_name, short_name):
        self.nodes[num] = (long_name, short_name)

    # ---- protocol ---------------------------------------------------------
    def config_frames(self, config_id):
        frames = [frame(mesh_pb2.FromRadio(my_info=mesh_pb2.MyNodeInfo(my_node_num=self.my_num))),
                  frame(mesh_pb2.FromRadio(metadata=mesh_pb2.DeviceMetadata(
                      firmware_version='2.7.15.fake', hw_model=mesh_pb2.HardwareModel.HELTEC_V4)))]
        for num, (ln, sn) in self.nodes.items():
            user = mesh_pb2.User(id=f'!{num:08x}', long_name=ln, short_name=sn,
                                 hw_model=mesh_pb2.HardwareModel.HELTEC_V4)
            frames.append(frame(mesh_pb2.FromRadio(node_info=mesh_pb2.NodeInfo(
                num=num, user=user, last_heard=int(time.time()), snr=7.5))))
        for idx in range(8):
            role = channel_pb2.Channel.Role.PRIMARY if idx == 0 else channel_pb2.Channel.Role.DISABLED
            settings = channel_pb2.ChannelSettings(name=self.channel_name if idx == 0 else '', psk=b'\x01')
            frames.append(frame(mesh_pb2.FromRadio(channel=channel_pb2.Channel(index=idx, role=role, settings=settings))))
        frames.append(frame(mesh_pb2.FromRadio(config_complete_id=config_id)))
        return frames

    def _broadcast(self, data, via=None):
        with self.lock:
            clients = [c for c in self.clients if via is None or c.name.startswith(via)]
        for c in clients:
            try:
                c.write(data)
            except OSError:
                pass

    def packet(self, from_num, portnum, payload, channel=0, pkt_id=None, snr=6.25, rssi=-97,
               hop_start=3, hop_limit=2, via=None):
        """via='tcp' or 'pty' delivers it to that transport's clients only, as if just
        one of two base radios had heard it."""
        if pkt_id is None:
            self._pkt_id += 1
            pkt_id = self._pkt_id
        p = mesh_pb2.MeshPacket(to=BROADCAST, channel=channel, id=pkt_id, rx_time=int(time.time()),
                                rx_snr=snr, rx_rssi=rssi, hop_start=hop_start, hop_limit=hop_limit,
                                decoded=mesh_pb2.Data(portnum=portnum, payload=payload))
        setattr(p, 'from', from_num)
        self._broadcast(frame(mesh_pb2.FromRadio(packet=p)), via)
        return pkt_id

    def text(self, from_num, text, **kw):
        """A text message as a station's serial module sends it (raw bytes)."""
        data = text.encode() if isinstance(text, str) else text
        return self.packet(from_num, portnums_pb2.PortNum.TEXT_MESSAGE_APP, data, **kw)

    def serial_line(self, from_num, line, chunk=233, **kw):
        """A line the XIAO wrote, cut the way the serial module cuts it."""
        data = (line + '\r\n').encode()
        ids = []
        for i in range(0, len(data), chunk):
            ids.append(self.text(from_num, data[i:i + chunk], **kw))
        return ids

    def telemetry(self, from_num, device=None, power=None, **kw):
        t = telemetry_pb2.Telemetry(time=int(time.time()))
        if device:
            t.device_metrics.CopyFrom(telemetry_pb2.DeviceMetrics(**device))
        elif power:
            t.power_metrics.CopyFrom(telemetry_pb2.PowerMetrics(**power))
        return self.packet(from_num, portnums_pb2.PortNum.TELEMETRY_APP, t.SerializeToString(), **kw)

    # ---- transports -------------------------------------------------------
    def serve_tcp(self, port, host='127.0.0.1'):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(4)
        self._tcp_server = srv

        def accept_loop():
            while True:
                try:
                    conn, addr = srv.accept()
                except OSError:
                    return
                threading.Thread(target=self._tcp_client, args=(conn, addr), daemon=True).start()

        threading.Thread(target=accept_loop, daemon=True).start()
        return srv.getsockname()[1]

    def _tcp_client(self, conn, addr):
        client = _Client(self, conn.sendall, f'tcp:{addr[0]}:{addr[1]}')
        client.conn = conn
        with self.lock:
            self.clients.append(client)
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                client.on_bytes(data)
        except OSError:
            pass
        finally:
            with self.lock:
                if client in self.clients:
                    self.clients.remove(client)
            try:
                conn.close()
            except OSError:
                pass

    def drop_tcp_clients(self):
        """Close every TCP connection, as a radio that rebooted or left WiFi would."""
        with self.lock:
            tcp = [c for c in self.clients if hasattr(c, 'conn')]
        for c in tcp:
            try:
                c.conn.shutdown(socket.SHUT_RDWR)
                c.conn.close()
            except OSError:
                pass

    def serve_pty(self):
        master, slave = pty.openpty()
        tty.setraw(slave)
        path = os.ttyname(slave)
        self._pty_slave = slave        # held open so the pty survives client reconnects
        os.set_blocking(master, False)

        def write(b):
            try:
                os.write(master, b)
            except BlockingIOError:
                pass                   # nobody reading the port right now: drop, as a radio would

        client = _Client(self, write, f'pty:{path}')
        with self.lock:
            self.clients.append(client)

        def reader():
            while True:
                r, _, _ = select.select([master], [], [], 1.0)
                if not r:
                    continue
                try:
                    data = os.read(master, 4096)
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    time.sleep(0.2)
                    continue
                if data:
                    client.on_bytes(data)

        threading.Thread(target=reader, daemon=True).start()
        return path

    def connected_clients(self):
        with self.lock:
            return len(self.clients)


# ---- level 1 heartbeat -------------------------------------------------------
L1_MESH_JSON_MAX = 191


def l1_mesh_heartbeat(node_id, heading=0, pos=None, scanning=True, sweeps=0, video_seen=0, nf_dbm=-98.0,
                      temp_c=38.5, uptime_s=0, tune_fail=0, cap_err=0, bus_stuck=0, alias_drop=0):
    """The mesh heartbeat line of the level 1 firmware (level1 branch,
    level1-c5phy/src/report.c report_heartbeat_json(..., full=0)): fields in
    priority order, each added only while the line stays within 191 bytes, with
    lat/lon right after the heading when the station was flashed with its
    position. Byte-identical to lines built from report.c (test_mesh_direct.py
    checks it against them)."""
    out = ['{']

    def add(item):
        cur = ''.join(out)
        need = len(item) + (1 if cur != '{' else 0)
        if len(cur) + need + 2 > L1_MESH_JSON_MAX + 1:
            return False
        out.append((',' if cur != '{' else '') + item)
        return True

    for item in ('"heartbeat":true', f'"node_id":"{node_id}"', '"receiver":"c5phy"'):
        if not add(item):
            return None
    add('"hw":"v3"')
    add(f'"heading":{int(heading)}')
    if pos is not None:
        add(f'"lat":{pos[0]:.6f},"lon":{pos[1]:.6f}')
    add('"scanning":' + ('true' if scanning else 'false'))
    add(f'"sweeps":{int(sweeps)}')
    add(f'"video_seen":{int(video_seen)}')
    add(f'"nf_dbm":{nf_dbm:.0f}')
    add(f'"temp_c":{temp_c:.1f}')
    add(f'"uptime_s":{int(uptime_s)}')
    for k, v in (('tune_fail', tune_fail), ('cap_err', cap_err), ('bus_stuck', bus_stuck), ('alias_drop', alias_drop)):
        add(f'"{k}":{int(v)}')
    return ''.join(out) + '}'


# ---- demo scenario ----------------------------------------------------------
def _dest(lat, lon, brg, dist):
    R = 6371000.0
    br, la1, lo1, d = math.radians(brg), math.radians(lat), math.radians(lon), dist / R
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(br))
    lo2 = lo1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def run_demo(radio, center, mapper=None, period=4.0):
    FS1, FS2, RX1, RX2, SA = 0xA1B2C3D4, 0xB2C3D4E5, 0xC3D4E5F6, 0xD4E5F6A7, 0xE5F6A7B8
    radio.add_node(FS1, 'Field station 1', 'FS1')
    radio.add_node(FS2, 'Field station 2', 'FS2')
    radio.add_node(RX1, 'Level 1 RX01', 'RX01')
    radio.add_node(RX2, 'Level 1 RX02', 'RX02')
    radio.add_node(SA, 'Standalone detector', 'SA1')
    clat, clon = center
    # node_id -> (radio node, flashed position, flashed heading of face N)
    st = {'RX01': (RX1, _dest(clat, clon, 225, 700), 30), 'RX02': (RX2, _dest(clat, clon, 135, 700), 300)}
    unplaced = set(st) if mapper else set()

    def place_stations():
        # Retried every cycle: the mapper may start after the radio
        for nid in list(unplaced):
            (lat, lon), heading = st[nid][1], st[nid][2]
            body = json.dumps({'node_id': nid, 'lat': lat, 'lon': lon, 'heading_deg': heading}).encode()
            req = urllib.request.Request(mapper.rstrip('/') + '/api/stations', data=body,
                                         headers={'Content-Type': 'application/json'}, method='POST')
            try:
                urllib.request.urlopen(req, timeout=5).close()
                unplaced.discard(nid)
                print(f'placed {nid} at {lat:.5f},{lon:.5f} in the mapper')
            except Exception:
                pass

    t0 = time.time()
    n = 0
    while True:
        if unplaced:
            place_stations()
        t = time.time() - t0
        dlat, dlon = _dest(clat, clon, (t * 3) % 360, 400)
        plat, plon = _dest(clat, clon, 300, 250)
        rid = {"mac": "60:60:1f:aa:bb:01", "rssi": -60 - int(10 * random.random()), "node_id": "A1B2",
               "drone_lat": round(dlat, 6), "drone_long": round(dlon, 6), "drone_altitude": 85,
               "pilot_lat": round(plat, 6), "pilot_long": round(plon, 6), "basic_id": "1581F5FHB229F00202DR",
               "op_id": "FIN87astrdge12k8", "id_type": 1, "src": "odid_ble5", "ua_type": 2,
               "eu_cat": 1, "eu_class": 2}
        radio.serial_line(FS1 if n % 2 == 0 else FS2, json.dumps(rid, separators=(',', ':')))
        flat, flon = _dest(clat, clon, (90 + t * 2) % 360, 300)
        for nid, (num, (slat, slon), heading) in st.items():
            if n % 4 == 0:
                # The firmware puts the position on its first 3 mesh heartbeats after
                # boot and then on every 5th (every 10 minutes). The demo sends it on
                # every heartbeat, so a mapper started later places the stations at once.
                radio.serial_line(num, l1_mesh_heartbeat(nid, heading, (slat, slon), sweeps=n * 2, video_seen=n,
                                                         nf_dbm=-97, temp_c=38.0 + (n % 10) / 10, uptime_s=int(t)))
            # bearing_deg is relative to the station's face N, as the firmware reports it
            b = round(_bearing(slat, slon, flat, flon) - heading + random.gauss(0, 4)) % 360
            radio.serial_line(num, json.dumps({"type": "analog_fm", "mac": "AF:00:52:03:16:64", "node_id": nid,
                                               "freq_mhz": 5732, "band": "R", "ch": 3, "rssi": -70, "bearing_deg": b,
                                               "bearing_sigma_deg": 10, "video": "NTSC", "fp": "NTSC/15736/5734"},
                                              separators=(',', ':')))
        if n % 3 == 0:
            alat, alon = _dest(clat, clon, 30, 900)
            radio.serial_line(SA, f"Drone: 9c:9c:1f:00:00:02 RSSI:-74 ID:1668A0000000000ABCDE "
                                  f"https://maps.google.com/?q={alat:.6f},{alon:.6f}")
            time.sleep(1.0)
            radio.serial_line(SA, f"Pilot: https://maps.google.com/?q={clat + 0.004:.6f},{clon + 0.006:.6f}")
            radio.serial_line(SA, "Possible drone (DJI Mini 2) 34:d2:62:00:00:03 RSSI:-82")
        n += 1
        time.sleep(period)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tcp', type=int, metavar='PORT', help='listen for TCP clients (a WiFi radio uses 4403)')
    ap.add_argument('--pty', action='store_true', help='present a pseudo-terminal (a USB radio)')
    ap.add_argument('--demo', action='store_true', help='loop the demo scenario')
    ap.add_argument('--center', default='33.4942,-111.9261', help='lat,lon of the demo area')
    ap.add_argument('--mapper', help='mapper URL: place the demo level 1 stations by hand through its API instead of '
                                     'relying on the position in their heartbeats (e.g. http://127.0.0.1:5000)')
    args = ap.parse_args()
    if not args.tcp and not args.pty:
        ap.error('give --tcp PORT and/or --pty')
    radio = FakeRadio()
    if args.tcp:
        print(f'fake radio listening on tcp:127.0.0.1:{radio.serve_tcp(args.tcp)}')
    if args.pty:
        print(f'fake radio on {radio.serve_pty()}')
    try:
        if args.demo:
            lat, lon = (float(x) for x in args.center.split(','))
            run_demo(radio, (lat, lon), args.mapper)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
