"""
Level 1 station identity and location for PlatformIO (extra_scripts = pre:tools/station.py)

1. Per-station settings without -D quoting. An environment may set

       custom_node_id         = RX01
       custom_station_lat     = 33.494200
       custom_station_lon     = -111.926100
       custom_station_heading = 15
       custom_antenna_dbi     = 8

   and this script turns them into NODE_ID, STATION_LAT, STATION_LON,
   STATION_HEADING_DEG and ANTENNA_GAIN_DBI for the build (see include/config.h).
   custom_antenna_beamwidth_deg and custom_bearing_k override what the firmware
   derives from the gain; the _24 forms (custom_antenna_dbi_24, ...) are the
   2.4 GHz patches of a dual-band station (extends = env:seeed_xiao_esp32c5_dualband).
   stations.ini holds one such [env:<NODE_ID>] per station; PlatformIO reads it
   through extra_configs, so every station is its own entry in the task list.

2. "Station setup (map)", a custom project task (PROJECT TASKS -> env -> Custom):
   opens a map in the browser to pick a station's position, heading and antennas,
   and saves the station into stations.ini.

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
DUALBAND_ENV = "seeed_xiao_esp32c5_dualband"            # BASE_ENV + -DDUAL_BAND=1: dual-band patches, 2.4 GHz swept too
STATIONS_FILE = "stations.ini"
NODE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,23}$")      # what the firmware keeps (main.cpp make_node_id)
SETUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,23}$")       # also a valid PlatformIO environment name
# antenna options: (custom_ option, key, define, lo, hi); the _24 rows are the 2.4 GHz patches of a dual-band station
ANTENNA_OPTIONS = (
    ("custom_antenna_dbi",              "antenna_dbi",      "ANTENNA_GAIN_DBI",         0.0,  20.0),
    ("custom_antenna_beamwidth_deg",    "beamwidth_deg",    "ANTENNA_BEAMWIDTH_DEG",   20.0, 180.0),
    ("custom_bearing_k",                "bearing_k",        "BEARING_K_DEG_PER_DB",     0.5,  20.0),
    ("custom_antenna_dbi_24",           "antenna_dbi_24",   "ANTENNA_GAIN_DBI_24",      0.0,  20.0),
    ("custom_antenna_beamwidth_deg_24", "beamwidth_deg_24", "ANTENNA_BEAMWIDTH_DEG_24", 20.0, 180.0),
    ("custom_bearing_k_24",             "bearing_k_24",     "BEARING_K_DEG_PER_DB_24",  0.5,  20.0),
)
OPTIONS = (("custom_node_id", "custom_station_lat", "custom_station_lon", "custom_station_heading")
           + tuple(option for option, *_ in ANTENNA_OPTIONS))
DEFAULT_DBI = {"": 8.0, "_24": 6.0}                      # config.h ANTENNA_GAIN_DBI / ANTENNA_GAIN_DBI_24
BEAMWIDTH_MIN_DEG = 60.0                                 # narrower: four sectors 90 deg apart leave holes between them
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


def validate_antenna(values):
    """{antenna_dbi, beamwidth_deg, bearing_k, *_24} for the custom_antenna_* / custom_bearing_k* options that are
    set (values: option -> text), or SettingError."""
    out = {}
    for option, key, _macro, lo, hi in ANTENNA_OPTIONS:
        text = str(values.get(option)).strip() if values.get(option) not in (None, "") else ""
        if text:
            out[key] = _number(option, text, lo, hi)
    return out


def beamwidth_deg(s, band=""):
    """The beamwidth the firmware will use for the band ("" 5.8 GHz, "_24" 2.4 GHz): the override, else derived
    from the gain as config.h does, sqrt(32400 / 10^(dBi/10)) (8 dBi -> 72 deg, 6 dBi -> 90 deg)."""
    if "beamwidth_deg" + band in s:
        return s["beamwidth_deg" + band]
    return math.sqrt(32400.0 / 10 ** (s.get("antenna_dbi" + band, DEFAULT_DBI[band]) / 10.0))


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
        s.update(validate_antenna(values))
    except SettingError as e:
        print(f"\n*** [env:{env['PIOENV']}] station settings: {e}\n")
        env.Exit(1)
    flags = " ".join(env.GetProjectOption("build_flags", []) or [])
    defines = {"node_id": "NODE_ID", "lat": "STATION_LAT", "heading": "STATION_HEADING_DEG"}
    defines.update((key, macro) for _option, key, macro, _lo, _hi in ANTENNA_OPTIONS)
    for key, macro in defines.items():
        if key in s and re.search(r"-D\s*" + macro + r"\b", flags):
            print(f"\n*** [env:{env['PIOENV']}] {macro} is set twice: by a custom_ option and by -D{macro} "
                  f"in build_flags. Keep one.\n")
            env.Exit(1)
    if "lat" in s and re.search(r"-D\s*STATION_LON\b", flags):
        print(f"\n*** [env:{env['PIOENV']}] STATION_LON is set twice. Keep one.\n")
        env.Exit(1)
    # -DDUAL_BAND comes with extends = env:seeed_xiao_esp32c5_dualband; without it 2.4 GHz is not swept
    dualband = re.search(r"-D\s*DUAL_BAND\b(?!=0\b)", flags) is not None
    unused = [option for option, key, *_ in ANTENNA_OPTIONS if key.endswith("_24") and key in s]
    if unused and not dualband:
        print(f"\n*** [env:{env['PIOENV']}] station settings: {', '.join(unused)} ignored: not a dual-band build "
              f"(extends = env:{DUALBAND_ENV} sweeps 2.4 GHz too)\n")
        for key in [k for k in s if k.endswith("_24")]:
            del s[key]
    for band in ("", "_24") if dualband else ("",):
        bw = beamwidth_deg(s, band)
        if bw < BEAMWIDTH_MIN_DEG:
            print(f"\n*** [env:{env['PIOENV']}] station settings: {'2.4 GHz ' if band else ''}antenna beamwidth "
                  f"~{bw:.0f} deg: four sectors 90 deg apart leave holes at the sector boundaries\n")
    cppdefines = []
    if "node_id" in s:
        cppdefines.append(("NODE_ID", env.StringifyMacro(s["node_id"])))
    if "lat" in s:
        cppdefines += [("STATION_LAT", f"{s['lat']:.6f}"), ("STATION_LON", f"{s['lon']:.6f}")]
    if "heading" in s:
        cppdefines.append(("STATION_HEADING_DEG", str(s["heading"])))
    for _option, key, macro, _lo, _hi in ANTENNA_OPTIONS:
        if key in s:
            cppdefines.append((macro, f"{s[key]:.2f}f"))
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
    """[{node_id, lat, lon, heading, dualband, antenna_dbi, ...}] for every [env:...] in stations.ini with a custom_node_id."""
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    out = []
    marks = list(SECTION_RE.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        opts = dict(re.findall(r"^\s*(custom_[a-z0-9_]+)\s*=\s*(.*?)\s*$", body, re.M))
        if not m.group("name").startswith("env:") or not opts.get("custom_node_id"):
            continue
        ext = re.search(r"^\s*extends\s*=\s*(.*?)\s*$", body, re.M)
        s = {"env": m.group("name")[4:], "node_id": opts.get("custom_node_id"),
             "lat": opts.get("custom_station_lat"), "lon": opts.get("custom_station_lon"),
             "heading": opts.get("custom_station_heading"),
             "dualband": bool(ext and f"env:{DUALBAND_ENV}" in re.split(r"[\s,]+", ext.group(1)))}
        s.update((key, opts.get(option)) for option, key, *_ in ANTENNA_OPTIONS)
        out.append(s)
    return out


def write_station(path, s):
    """Add or replace [env:<node_id>] in stations.ini, leaving everything else as it is."""
    lines = [f"[env:{s['node_id']}]",
             f"extends = env:{DUALBAND_ENV if s.get('dualband') else BASE_ENV}",
             f"custom_node_id = {s['node_id']}",
             f"custom_station_lat = {s['lat']:.6f}",
             f"custom_station_lon = {s['lon']:.6f}",
             f"custom_station_heading = {s.get('heading', 0)}"]
    lines += [f"{option} = {s[key]:g}" for option, key, *_ in ANTENNA_OPTIONS
              if key in s and (s.get("dualband") or not key.endswith("_24"))]
    section = "\n".join(lines) + "\n"
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
                s["dualband"] = bool(data.get("dualband"))
                s.update(validate_antenna({option: data.get(key) for option, key, *_ in ANTENNA_OPTIONS}))
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
    antennas = f"{result.get('antenna_dbi', DEFAULT_DBI['']):g} dBi patches"
    if result.get("dualband"):
        antennas = f"dual-band patches, {result.get('antenna_dbi', DEFAULT_DBI['']):g} dBi at 5.8 GHz and " \
                   f"{result.get('antenna_dbi_24', DEFAULT_DBI['_24']):g} dBi at 2.4 GHz"
    print(f"Saved [env:{result['node_id']}] to {path}:")
    print(f"  node id {result['node_id']}, position {result['lat']:.6f}, {result['lon']:.6f}, "
          f"heading of face N {result['heading']} deg, {antennas}")
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
    description="Pick a station's position, heading and antennas on a map and save it to stations.ini",
    always_build=True,
)
