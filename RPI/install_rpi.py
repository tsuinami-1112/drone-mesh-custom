#!/usr/bin/env python3
"""
Mesh-Mapper Raspberry Pi installer

Installs mesh-mapper.py from tsuinami-1112/drone-sentinel and starts it on
every boot:

  1. downloads the repository from GitHub and unpacks it into the install
     directory (default ~/mesh-mapper). The mapper needs the static/ folder
     next to it, not just mesh-mapper.py.
  2. creates a Python virtual environment in <install dir>/.venv and installs
     requirements.txt into it
  3. adds an @reboot cron job for the current user that starts the mapper
     from that environment

Running it again updates an existing install in place. Detections, settings
and cached map tiles in the install directory are kept.

Usage:
    python3 install_rpi.py
    python3 install_rpi.py --install-dir /opt/mesh-mapper
    python3 install_rpi.py --no-cron
"""

import os
import sys
import argparse
import subprocess
import getpass
import grp
import shlex
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("❌ This installer needs the Python 'requests' module.")
    print("   Install it with: sudo apt install python3-requests")
    sys.exit(1)

# GitHub repository configuration
GITHUB_REPO = "tsuinami-1112/drone-sentinel"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
TARGET_FILE = "mesh-mapper.py"
REQUIREMENTS_FILE = "requirements.txt"
# A file the web UI cannot work without; its absence means a broken unpack
STATIC_CHECK_FILE = os.path.join("static", "leaflet", "leaflet.js")
USER_AGENT = f"drone-sentinel-installer (+{GITHUB_URL})"

def get_current_user():
    """Get the current username"""
    return getpass.getuser()

def get_user_home():
    """Get the current user's home directory"""
    return str(Path.home())

def construct_download_url(branch):
    """Construct the GitHub archive URL for a branch (None = default branch)"""
    if branch is None:
        return f"{GITHUB_URL}/archive/HEAD.tar.gz"
    # Branch names may contain characters such as '(' that need escaping
    return f"{GITHUB_URL}/archive/refs/heads/{quote(branch, safe='/')}.tar.gz"

def download_file(url, destination):
    """Download a file from URL to destination"""
    print(f"📥 Downloading from: {url}")

    try:
        response = requests.get(url, stream=True, timeout=30,
                                headers={"User-Agent": USER_AGENT})
        if response.status_code == 404:
            print("❌ Not found. Check the branch name exists on GitHub:")
            print(f"   {GITHUB_URL}/branches")
            return False
        response.raise_for_status()

        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        size_mb = os.path.getsize(destination) / (1024 * 1024)
        print(f"✅ Downloaded {size_mb:.1f} MB")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading: {e}")
        return False
    except OSError as e:
        print(f"❌ Error saving download: {e}")
        return False

def extract_archive(archive_path, install_dir):
    """Unpack the GitHub archive into install_dir, dropping its top-level folder.

    Only regular files and directories are written, and only inside
    install_dir. Files not in the archive (detections, settings, tiles,
    the .venv) are left alone.
    """
    print(f"📦 Unpacking into: {install_dir}")
    written = 0
    try:
        with tarfile.open(archive_path, 'r:gz') as tar:
            for member in tar:
                # GitHub archives wrap everything in "<repo>-<ref>/"
                parts = PurePosixPath(member.name).parts[1:]
                if not parts:
                    continue
                if any(p in ('..', '') for p in parts) or PurePosixPath(*parts).is_absolute():
                    print(f"⚠️  Skipping unsafe path in archive: {member.name}")
                    continue
                target = os.path.join(install_dir, *parts)

                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                elif member.isfile():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    source = tar.extractfile(member)
                    with open(target, 'wb') as f:
                        shutil.copyfileobj(source, f)
                    os.chmod(target, member.mode & 0o755 | 0o644)
                    written += 1
                # Links and special files are not used by this repository
    except (tarfile.TarError, OSError) as e:
        print(f"❌ Error unpacking: {e}")
        return False

    if not os.path.isfile(os.path.join(install_dir, TARGET_FILE)):
        print(f"❌ The download did not contain {TARGET_FILE}")
        return False

    print(f"✅ Unpacked {written} files")
    return True

def setup_virtualenv(install_dir):
    """Create <install_dir>/.venv and install requirements.txt into it.

    Returns the path of the environment's python, or None on failure.
    """
    venv_dir = os.path.join(install_dir, '.venv')
    venv_python = os.path.join(venv_dir, 'bin', 'python')

    # (Re)create the environment if it is missing or was left without pip,
    # e.g. by an earlier run on a system where python3-venv was missing
    pip_ok = os.path.exists(venv_python) and subprocess.run(
        [venv_python, '-m', 'pip', '--version'], capture_output=True).returncode == 0
    if not pip_ok:
        print(f"🐍 Creating virtual environment: {venv_dir}")
        result = subprocess.run([sys.executable, '-m', 'venv', '--clear', venv_dir],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Could not create the virtual environment:")
            print(f"   {result.stderr.strip()}")
            print("   Install venv support and run this installer again:")
            print("   sudo apt install python3-venv")
            return None

    print("📦 Installing Python packages (this can take a few minutes on a Pi)...")
    result = subprocess.run([venv_python, '-m', 'pip', 'install', '--upgrade',
                             '-r', os.path.join(install_dir, REQUIREMENTS_FILE)])
    if result.returncode != 0:
        print("❌ Installing the Python packages failed (see the pip output above)")
        return None

    print("✅ Python packages installed")
    return venv_python

def get_current_crontab():
    """Get current user's crontab"""
    try:
        result = subprocess.run(['crontab', '-l'],
                              capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return ""  # No crontab exists
    except Exception as e:
        print(f"⚠️  Error reading crontab: {e}")
        return ""

def is_our_cron_line(line, install_dir):
    """True for a mesh-mapper @reboot line that starts from install_dir.

    Also matches the line the older upstream installer wrote, so re-running
    over such an install replaces it instead of starting the mapper twice.
    """
    return (TARGET_FILE in line and
            any(f"cd {d} &&" in line for d in (install_dir, shlex.quote(install_dir))))

def install_cron_job(install_dir, venv_python):
    """Install the cron job for auto-start"""
    current_user = get_current_user()

    # Construct the cron job command
    cron_command = (f"@reboot sleep 5 && cd {shlex.quote(install_dir)} && "
                    f"{shlex.quote(venv_python)} {TARGET_FILE}")

    print(f"🔧 Setting up cron job for user: {current_user}")
    print(f"⚙️  Cron command: {cron_command}")

    # Get current crontab
    current_crontab = get_current_crontab()

    # Replace any existing entry for this install directory
    lines = current_crontab.split('\n') if current_crontab else []
    kept = [line for line in lines if not is_our_cron_line(line, install_dir)]
    if len(kept) != len(lines):
        print("ℹ️  Cron job already exists, updating...")
    new_crontab = '\n'.join(kept + [cron_command]).strip() + '\n'

    try:
        # Install the new crontab
        process = subprocess.Popen(['crontab', '-'],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 text=True)
        stdout, stderr = process.communicate(new_crontab)

        if process.returncode == 0:
            print("✅ Cron job installed successfully!")
            print("🔄 The mesh-mapper will auto-start on system reboot")
            return True
        else:
            print(f"❌ Error installing cron job: {stderr}")
            return False

    except Exception as e:
        print(f"❌ Error setting up cron job: {e}")
        return False

def check_serial_access():
    """Warn if the current user cannot open USB serial ports"""
    try:
        dialout_gid = grp.getgrnam('dialout').gr_gid
    except KeyError:
        return  # No dialout group on this system; nothing to check
    if dialout_gid not in os.getgroups():
        print(f"⚠️  User '{get_current_user()}' is not in the 'dialout' group, so the")
        print("   mapper cannot open the XIAO's serial port. Fix it with:")
        print("   sudo usermod -a -G dialout $USER")
        print("   then log out and back in (or reboot).")

def verify_installation(install_dir, venv_python, cron_expected=True):
    """Verify the installation"""
    print("\n🔍 Verifying installation...")
    ok = True

    for rel in (TARGET_FILE, STATIC_CHECK_FILE):
        if not os.path.isfile(os.path.join(install_dir, rel)):
            print(f"❌ Missing: {os.path.join(install_dir, rel)}")
            ok = False

    result = subprocess.run(
        [venv_python, '-c', 'import flask, flask_socketio, serial, requests'],
        capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ Python packages import correctly")
    else:
        print(f"❌ Python packages are not importable: {result.stderr.strip()}")
        ok = False

    # Verify cron job only if expected
    if cron_expected:
        if any(is_our_cron_line(line, install_dir) and line.startswith('@reboot')
               for line in get_current_crontab().split('\n')):
            print("✅ Cron job verified")
        else:
            print("⚠️  Cron job not found in crontab")
            ok = False
    else:
        print("ℹ️  Cron job verification skipped (--no-cron used)")

    if ok:
        print(f"✅ Installation verified: {install_dir}")
    return ok

def main():
    parser = argparse.ArgumentParser(
        description=f"Install mesh-mapper.py from {GITHUB_URL} and start it on boot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 install_rpi.py
  python3 install_rpi.py --install-dir /opt/mesh-mapper
  python3 install_rpi.py --no-cron
  python3 install_rpi.py --force          # update without asking
        """)

    parser.add_argument('--branch',
                       default=None,
                       help="GitHub branch to install from "
                            "(default: the repository's default branch)")

    parser.add_argument('--install-dir',
                       default=None,
                       help='Installation directory (default: ~/mesh-mapper)')

    parser.add_argument('--no-cron',
                       action='store_true',
                       help='Skip installing cron job')

    parser.add_argument('--force',
                       action='store_true',
                       help='Update an existing install without asking')

    args = parser.parse_args()

    # Determine installation directory
    if args.install_dir:
        install_dir = os.path.abspath(os.path.expanduser(args.install_dir))
    else:
        install_dir = os.path.join(get_user_home(), 'mesh-mapper')

    install_path = os.path.join(install_dir, TARGET_FILE)

    print("=" * 60)
    print("🚁 MESH-MAPPER RASPBERRY PI INSTALLER")
    print("=" * 60)
    print(f"📦 Repository: {GITHUB_URL}")
    print(f"🌿 Branch: {args.branch or 'default branch'}")
    print(f"👤 User: {get_current_user()}")
    print(f"📁 Install Dir: {install_dir}")
    print()

    # Check if an install already exists
    updating = os.path.exists(install_path)
    if updating and not args.force:
        print(f"An install already exists in {install_dir}.")
        print("Updating replaces the program files and keeps your detections,")
        print("settings and cached map tiles.")
        response = input("Update it? (y/N): ")
        if response.lower() != 'y':
            print("❌ Installation cancelled")
            return 1

    try:
        os.makedirs(install_dir, exist_ok=True)
    except OSError as e:
        print(f"❌ Cannot create {install_dir}: {e}")
        return 1

    # Download and unpack the repository
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, 'drone-sentinel.tar.gz')
        if not download_file(construct_download_url(args.branch), archive_path):
            print("❌ Download failed")
            return 1
        if not extract_archive(archive_path, install_dir):
            print("❌ Unpacking failed")
            return 1

    # Python environment
    venv_python = setup_virtualenv(install_dir)
    if not venv_python:
        return 1

    # Install cron job (if requested)
    if not args.no_cron:
        print("\n🕒 Setting up auto-start cron job...")
        if not install_cron_job(install_dir, venv_python):
            print("⚠️  Cron job installation failed, but the mapper was installed")
    else:
        print("⏭️  Skipping cron job installation (--no-cron specified)")

    check_serial_access()

    # Verify installation
    if verify_installation(install_dir, venv_python, not args.no_cron):
        print("\n🎉 Installation completed successfully!")
        print(f"📍 Mesh-mapper installed at: {install_path}")

        if not args.no_cron:
            print("🔄 Auto-start enabled: Will run on system reboot")

        print("\n📋 Next steps:")
        print("  1. Plug the home station's XIAO (or a standalone detector) into this computer")
        print("  2. Test the mapper by hand (stop it with Ctrl+C):")
        print(f"     cd {shlex.quote(install_dir)} && .venv/bin/python {TARGET_FILE}")
        print("  3. Open http://localhost:5000 (or http://<this computer's IP>:5000)")
        print("     and pick the XIAO's serial port")
        if not args.no_cron:
            print("  4. Reboot to check that it starts by itself")
        if updating:
            print("\n⚠️  If the mapper is already running, restart it (or reboot)")
            print("   so the updated version is loaded.")
        print(f"\n📝 The mapper logs to {os.path.join(install_dir, 'mapper.log')}")

        return 0
    else:
        print("❌ Installation verification failed")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Installation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)
