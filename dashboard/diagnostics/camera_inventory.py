"""Read-only camera binding/package inventory; run on the Pi."""
import json
import platform
import subprocess
from pathlib import Path

result = {"architecture": platform.machine(), "python": platform.python_version(),
          "os_release": {}, "i2c_sensor_devices": [], "camera_device_tree": [], "camera_boot_settings": []}
for line in Path("/etc/os-release").read_text().splitlines():
    if line.startswith(("ID=", "VERSION_ID=", "PRETTY_NAME=")):
        key, value = line.split("=", 1)
        result["os_release"][key] = value.strip('"')
for path in Path("/sys/bus/i2c/devices").glob("*/name"):
    try:
        name = path.read_text().strip()
        if any(x in name.lower() for x in ("imx", "ov", "camera", "unicam")):
            result["i2c_sensor_devices"].append({"path": str(path), "name": name})
    except OSError:
        pass
for path in Path("/proc/device-tree").glob("**/compatible"):
    try:
        value = path.read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        if any(x in value.lower() for x in ("imx219", "imx477", "imx708", "ov5647", "unicam")):
            result["camera_device_tree"].append({"path": str(path), "compatible": value})
    except OSError:
        pass
for filename in ("/boot/firmware/config.txt", "/boot/config.txt", "/boot/firmware/usercfg.txt"):
    try:
        for line in Path(filename).read_text().splitlines():
            setting = line.strip()
            if setting.startswith(("camera_auto_detect=", "start_x=", "gpu_mem=")) or (
                    setting.startswith("dtoverlay=") and any(x in setting.lower() for x in ("imx", "ov", "camera", "vc4"))):
                result["camera_boot_settings"].append({"file": filename, "setting": setting})
    except OSError:
        pass
packages = subprocess.run(["dpkg-query", "-W", "-f=${Package} ${Version}\n", "*libcamera*", "*rpicam*", "*picamera*", "*v4l-utils*"], capture_output=True, text=True)
result["existing_camera_packages"] = packages.stdout.strip().splitlines()
print(json.dumps(result, indent=2))
