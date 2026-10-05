"""
Level 1 station identity and location for PlatformIO (extra_scripts = pre:tools/station.py)

1. Per-station settings without -D quoting. An environment may set

       custom_node_id         = RX01
       custom_station_lat     = 33.494200
       custom_station_lon     = -111.926100
       custom_station_heading = 15

   and this script turns them into NODE_ID, STATION_LAT, STATION_LON and
   STATION_HEADING_DEG for the build (see include/config.h). stations.ini holds
   one such [env:<NODE_ID>] per station; PlatformIO reads it through
   extra_configs, so every station is its own entry in the task list.

2. "Station setup (map)", a custom project task (PROJECT TASKS -> env -> Custom):
   opens a map in the browser to pick a station's position and heading, and
   saves the station into stations.ini.

       pio run -e seeed_xiao_esp32c5 -t station_setup
"""
import json
import math
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

Import("env")  # noqa: F821  (SCons)

BASE_ENV = "seeed_xiao_esp32c5"
STATIONS_FILE = "stations.ini"
NODE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,23}$")      # what the firmware keeps (main.cpp make_node_id)
SETUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,23}$")       # also a valid PlatformIO environment name
OPTIONS = ("custom_node_id", "custom_station_lat", "custom_station_lon", "custom_station_heading")
SETUP_TIMEOUT_S = 30 * 60


class SettingError(ValueError):
    pass


def _number(name, text, lo, hi):
    try:
        v = float(text)
    except (TypeError, ValueError):
        raise SettingError(f"{name} = {text!r} is not a number")
    if not math.isfinite(v) or not lo <= v <= hi:
        raise SettingError(f"{name} = {text} is outside {lo:g}..{hi:g}")
    return v


def validate(node_id, lat, lon, heading, id_re=NODE_ID_RE):
    """Checked values, or SettingError with a message an installer can act on."""
    node_id = (node_id or "").strip()
    lat, lon = (str(lat).strip() if lat not in (None, "") else ""), (str(lon).strip() if lon not in (None, "") else "")
    heading = str(heading).strip() if heading not in (None, "") else ""
    out = {}
    if node_id:
        if not id_re.match(node_id):
            allowed = "letters, digits, _ and -" if id_re is SETUP_ID_RE else "letters, digits and _ . : -"
            raise SettingError(f"node id {node_id!r}: use 1-23 characters, {allowed}")
        out["node_id"] = node_id
    if bool(lat) != bool(lon):
        raise SettingError("set both custom_station_lat and custom_station_lon, or neither")
    if lat:
        out["lat"] = _number("custom_station_lat", lat, -90.0, 90.0)
        out["lon"] = _number("custom_station_lon", lon, -180.0, 180.0)
    if heading:
        h = _number("custom_station_heading", heading, 0.0, 360.0)
        out["heading"] = int(round(h)) % 360
    return out


# ---------------------------------------------------------------------------
# 1. custom_* options -> defines
# ---------------------------------------------------------------------------
def apply_station_options():
    values = {k: env.GetProjectOption(k, "") for k in OPTIONS}
    if not any(str(v).strip() for v in values.values()):
        return
    try:
        s = validate(values["custom_node_id"], values["custom_station_lat"],
                     values["custom_station_lon"], values["custom_station_heading"])
    except SettingError as e:
        print(f"\n*** [env:{env['PIOENV']}] station settings: {e}\n")
        env.Exit(1)
    flags = " ".join(env.GetProjectOption("build_flags", []) or [])
    defines = {"node_id": "NODE_ID", "lat": "STATION_LAT", "heading": "STATION_HEADING_DEG"}
    for key, macro in defines.items():
        if key in s and re.search(r"-D\s*" + macro + r"\b", flags):
            print(f"\n*** [env:{env['PIOENV']}] {macro} is set twice: by a custom_ option and by -D{macro} "
                  f"in build_flags. Keep one.\n")
            env.Exit(1)
    if "lat" in s and re.search(r"-D\s*STATION_LON\b", flags):
        print(f"\n*** [env:{env['PIOENV']}] STATION_LON is set twice. Keep one.\n")
        env.Exit(1)
    cppdefines = []
    if "node_id" in s:
        cppdefines.append(("NODE_ID", env.StringifyMacro(s["node_id"])))
    if "lat" in s:
        cppdefines += [("STATION_LAT", f"{s['lat']:.6f}"), ("STATION_LON", f"{s['lon']:.6f}")]
    if "heading" in s:
        cppdefines.append(("STATION_HEADING_DEG", str(s["heading"])))
    env.Append(CPPDEFINES=cppdefines)
    shown = ", ".join(f"{k}={v}" for k, v in s.items())
    print(f"Station [env:{env['PIOENV']}]: {shown}")


# ---------------------------------------------------------------------------
# 2. Station setup (map)
# ---------------------------------------------------------------------------
SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$", re.M)
STATIONS_HEADER = """\
; Level 1 stations: one build environment per station, written by the
; "Station setup (map)" task (tools/station.py). Each [env:<NODE_ID>] is its own
; entry under PROJECT TASKS: use its Erase Flash and Upload to flash that station.
; You can also edit it by hand: the custom_* options are checked at build time.
; This file records where your stations are: it is not committed (.gitignore).
"""


def read_stations(path):
    """[{node_id, lat, lon, heading}] for every [env:...] in stations.ini with a custom_node_id."""
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    out = []
    marks = list(SECTION_RE.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        opts = dict(re.findall(r"^\s*(custom_[a-z_]+)\s*=\s*(.*?)\s*$", body, re.M))
        if not m.group("name").startswith("env:") or not opts.get("custom_node_id"):
            continue
        out.append({"env": m.group("name")[4:], "node_id": opts.get("custom_node_id"),
                    "lat": opts.get("custom_station_lat"), "lon": opts.get("custom_station_lon"),
                    "heading": opts.get("custom_station_heading")})
    return out


def write_station(path, s):
    """Add or replace [env:<node_id>] in stations.ini, leaving everything else as it is."""
    section = (f"[env:{s['node_id']}]\n"
               f"extends = env:{BASE_ENV}\n"
               f"custom_node_id = {s['node_id']}\n"
               f"custom_station_lat = {s['lat']:.6f}\n"
               f"custom_station_lon = {s['lon']:.6f}\n"
               f"custom_station_heading = {s.get('heading', 0)}\n")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else STATIONS_HEADER
    marks = list(SECTION_RE.finditer(text))
    for i, m in enumerate(marks):
        if m.group("name") == f"env:{s['node_id']}":
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            text = text[:m.start()] + section + ("\n" if i + 1 < len(marks) else "") + text[end:]
            break
    else:
        text = text.rstrip("\n") + "\n\n" + section
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def station_setup(target, source, env):  # noqa: ARG001  (SCons action signature)
    project_dir = env.subst("$PROJECT_DIR")
    path = os.path.join(project_dir, STATIONS_FILE)
    page = os.path.join(project_dir, "tools", "station_setup.html")
    done = threading.Event()
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.split("?")[0] in ("/", "/index.html"):
                self._send(200, open(page, "rb").read(), "text/html; charset=utf-8")
            elif self.path == "/api/stations":
                current = env.GetProjectOption("custom_node_id", "") or ""
                self._send(200, json.dumps({"stations": read_stations(path), "current": current,
                                            "file": path}))
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self):
            port = self.server.server_port
            if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                # only this page may write stations.ini, not some other site open in the browser
                self._send(403, json.dumps({"error": "forbidden"}))
                return
            if self.path == "/api/cancel":
                self._send(200, json.dumps({"ok": True}))
                done.set()
                return
            if self.path != "/api/save":
                self._send(404, json.dumps({"error": "not found"}))
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 4096:
                    raise SettingError("request too large")
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if not isinstance(data, dict):
                    raise SettingError("expected a JSON object")
                s = validate(data.get("node_id"), data.get("lat"), data.get("lon"), data.get("heading"),
                             id_re=SETUP_ID_RE)
                if "node_id" not in s or "lat" not in s:
                    raise SettingError("a station needs a node id and a position")
                s.setdefault("heading", 0)
                write_station(path, s)
            except (SettingError, ValueError) as e:
                self._send(400, json.dumps({"error": str(e)}))
                return
            result.update(s)
            self._send(200, json.dumps({"ok": True, "env": s["node_id"], "file": path}))
            done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"\nStation setup: {url}")
    print("Pick the station on the map and press Save (Ctrl+C here to stop).\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        done.wait(SETUP_TIMEOUT_S)
    except KeyboardInterrupt:
        pass
    server.shutdown()
    if not result:
        print("Station setup: nothing saved.")
        return 0
    print(f"Saved [env:{result['node_id']}] to {path}:")
    print(f"  node id {result['node_id']}, position {result['lat']:.6f}, {result['lon']:.6f}, "
          f"heading of face N {result['heading']} deg")
    print("Next: refresh PROJECT TASKS (or reload the window) so it lists "
          f"{result['node_id']}, then {result['node_id']} > Platform > Erase Flash and "
          f"{result['node_id']} > General > Upload.")
    print(f"From a terminal: pio run -e {result['node_id']} -t erase && pio run -e {result['node_id']} -t upload\n")
    return 0


apply_station_options()
env.AddCustomTarget(
    name="station_setup",
    dependencies=None,
    actions=[station_setup],
    title="Station setup (map)",
    description="Pick a station's position and heading on a map and save it to stations.ini",
    always_build=True,
)
