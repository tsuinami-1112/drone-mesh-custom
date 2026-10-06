#!/usr/bin/env python3
"""Assemble the web flasher site that GitHub Pages serves.

    build_site.py IMAGES_DIR OUT_DIR VERSION [COMMIT]

Copies index.html and every manifest-*.json from this folder into OUT_DIR,
copies the images the manifests name from IMAGES_DIR into OUT_DIR/firmware/,
stamps VERSION into each manifest and writes version.json for the page
header. Fails if a manifest names an image IMAGES_DIR doesn't have, so a
publish never ships a button that can't install.

The Firmware workflow (.github/workflows/firmware.yml) runs this when it
publishes. It also works for a local preview:

    python3 flasher/build_site.py path/to/images /tmp/site v0-test
    python3 -m http.server -d /tmp/site      # then open http://localhost:8000
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv):
    if len(argv) not in (4, 5):
        sys.exit(__doc__)
    images, out, version = Path(argv[1]), Path(argv[2]), argv[3]
    commit = argv[4] if len(argv) == 5 else ""

    (out / "firmware").mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "index.html", out / "index.html")

    missing, used = [], set()
    manifests = sorted(HERE.glob("manifest-*.json"))
    for path in manifests:
        manifest = json.loads(path.read_text())
        manifest["version"] = version
        for build in manifest["builds"]:
            for part in build["parts"]:
                name = Path(part["path"]).name
                if part["path"] != f"firmware/{name}":
                    sys.exit(f"{path.name}: image paths must be firmware/<file>, got {part['path']}")
                if not (images / name).is_file():
                    missing.append(f"{path.name} ({build['chipFamily']}): {name}")
                    continue
                shutil.copy2(images / name, out / "firmware" / name)
                used.add(name)
        (out / path.name).write_text(json.dumps(manifest, indent=2) + "\n")

    if missing:
        sys.exit("Images missing from " + str(images) + ":\n  " + "\n  ".join(missing))
    for extra in sorted(p.name for p in images.glob("*.bin") if p.name not in used):
        print(f"note: {extra} is not on any button of the page")

    (out / "version.json").write_text(json.dumps({
        "version": version,
        "commit": commit,
        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
    }) + "\n")
    print(f"{out}: {len(manifests)} manifests, {len(used)} images, version {version}")


if __name__ == "__main__":
    main(sys.argv)
