"""One-time user-approved camera boot change, run as root on the Pi."""
from datetime import datetime, timezone
import difflib
from pathlib import Path
import shutil
import subprocess
import sys

path = Path('/boot/firmware/config.txt')
if not Path('/boot/firmware/overlays/imx219.dtbo').exists():
    raise SystemExit('IMX219 overlay not present; no change made')
original = path.read_text()
if original.count('camera_auto_detect=1') != 1 or '\ndtoverlay=imx219' in original:
    raise SystemExit('Unexpected camera configuration; no change made')
updated = original.replace('camera_auto_detect=1', 'camera_auto_detect=0\ndtoverlay=imx219', 1)
backup = path.with_name('config.txt.before-imx219-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
if backup.exists():
    raise SystemExit('Backup already exists; no change made')
shutil.copy2(path, backup)
path.write_text(updated)
if path.read_text() != updated or backup.read_text() != original:
    path.write_text(original)
    raise SystemExit('Verification failed; original restored')
print('BACKUP:', backup, flush=True)
print(''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True), fromfile=str(backup), tofile=str(path))), flush=True)
subprocess.run(['sync'], check=True)
if '--reboot' in sys.argv:
    print('Verified approved camera change; rebooting now', flush=True)
    subprocess.run(['systemctl', 'reboot'], check=True)
