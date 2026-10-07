#!/usr/bin/env python3
"""Assemble the web flasher site that GitHub Pages serves.

    build_site.py IMAGES_DIR OUT_DIR VERSION [COMMIT]

Copies index.html, release.js and every manifest-*.json from this folder
into OUT_DIR, copies the images the manifests name from IMAGES_DIR into
OUT_DIR/firmware/ and writes firmware/SHA256SUMS for them, stamps VERSION
into each manifest and writes version.json for the page header. Fails if
a manifest names an image IMAGES_DIR doesn't have, so a publish never
ships a button that can't install.

It also puts the flashing library, esp-web-tools, under OUT_DIR/vendor/,
so the page loads it from the site itself instead of from a CDN. The
release is pinned below together with the SHA-256 of its npm tarball:
the tarball is downloaded from the npm registry and refused if the hash
differs. To move to a newer esp-web-tools, change both constants
together; the hash is `sha256sum esp-web-tools-<version>.tgz` of the
file at https://registry.npmjs.org/esp-web-tools/-/esp-web-tools-<version>.tgz
Set ESP_WEB_TOOLS_TGZ to a local copy of the tarball to build offline.

The Firmware workflow (.github/workflows/firmware.yml) runs this when it
publishes. It also works for a local preview:

    python3 flasher/build_site.py path/to/images /tmp/site v0-test
    python3 -m http.server -d /tmp/site      # then open http://localhost:8000
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The flashing library. Bump the version and the hash together.
ESP_WEB_TOOLS_VERSION = "10.4.0"
ESP_WEB_TOOLS_SHA256 = "f18da75335d2f0dca044c4bb052848c0696e7b03cc23d61d8530dd6eba0a9008"
ESP_WEB_TOOLS_URL = (
    "https://registry.npmjs.org/esp-web-tools/-/"
    f"esp-web-tools-{ESP_WEB_TOOLS_VERSION}.tgz"
)
# The browser bundle inside the tarball; index.html loads install-button.js
# from vendor/esp-web-tools/ and that file pulls in the rest.
ESP_WEB_TOOLS_BUNDLE = "package/dist/web/"


def fetch_esp_web_tools():
    """Return the pinned esp-web-tools tarball's bytes, or exit if the hash is off."""
    local = os.environ.get("ESP_WEB_TOOLS_TGZ")
    if local:
        data = Path(local).read_bytes()
        source = local
    else:
        with urllib.request.urlopen(ESP_WEB_TOOLS_URL, timeout=60) as response:
            data = response.read()
        source = ESP_WEB_TOOLS_URL
    digest = hashlib.sha256(data).hexdigest()
    if digest != ESP_WEB_TOOLS_SHA256:
        sys.exit(
            f"esp-web-tools {ESP_WEB_TOOLS_VERSION} from {source}:\n"
            f"  SHA-256 is {digest}\n"
            f"  expected  {ESP_WEB_TOOLS_SHA256}\n"
            "Refusing to build: this isn't the release the script is pinned to."
        )
    return data


def vendor_esp_web_tools(out):
    """Unpack the esp-web-tools browser bundle into OUT/vendor/esp-web-tools/."""
    dest = out / "vendor" / "esp-web-tools"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(fetch_esp_web_tools()), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith(ESP_WEB_TOOLS_BUNDLE):
                continue
            rel = Path(member.name[len(ESP_WEB_TOOLS_BUNDLE):])
            if rel.is_absolute() or ".." in rel.parts:
                sys.exit(f"esp-web-tools tarball has an unsafe path: {member.name}")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
            count += 1
    if not (dest / "install-button.js").is_file():
        sys.exit(f"esp-web-tools tarball has no {ESP_WEB_TOOLS_BUNDLE}install-button.js")
    return count


def main(argv):
    if len(argv) not in (4, 5):
        sys.exit(__doc__)
    images, out, version = Path(argv[1]), Path(argv[2]), argv[3]
    commit = argv[4] if len(argv) == 5 else ""

    (out / "firmware").mkdir(parents=True, exist_ok=True)
    for page_file in ("index.html", "release.js"):
        shutil.copy2(HERE / page_file, out / page_file)
    vendored = vendor_esp_web_tools(out)

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

    # Same format as `sha256sum`, so `sha256sum -c SHA256SUMS` checks a download.
    (out / "firmware" / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((out / 'firmware' / name).read_bytes()).hexdigest()}  {name}\n"
        for name in sorted(used)
    ))

    (out / "version.json").write_text(json.dumps({
        "version": version,
        "commit": commit,
        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
    }) + "\n")
    print(f"{out}: {len(manifests)} manifests, {len(used)} images, "
          f"esp-web-tools {ESP_WEB_TOOLS_VERSION} ({vendored} files), version {version}")


if __name__ == "__main__":
    main(sys.argv)
