# Mission upgrade: source changes

Pre-upgrade source backup: `.robot/backups/pre-mission-dashboard.tar.gz`.
The original project is preserved. No Git repository was present in this folder,
so this manifest identifies the implementation changes instead of a Git diff.

## Added

- `OPERATOR.md`, `ARCHITECTURE.md`, `PERFORMANCE.md`, this manifest.
- `scripts/start.sh`, `status.sh`, `stop.sh`, `restart.sh`, `diagnose.sh`, `install.sh`.
- `scripts/missionctl.py`, `supervisor.py`, `pi_runtime.py`.
- `camera/capture_worker.c`, `isp_worker.c`, `configure.py`, `relay.py`, `protocol.py`.
- `camera/benchmark.py`, `benchmark_isp.py`, `vendor/bcm2835-isp.h`.
- `dashboard/backend/features.py`, `mission.py`, `system_status.py`.
- `dashboard/static/video.js`, `mission.js`, `mission.css`.
- `dashboard/tests/test_mission.py`, `test_startup.py`.
- `models/README.md`, `example_client.py`.
- `diagnostics/mission_verify.py`, `mission_performance.py`, `recovery_test.py`.
- `diagnostics/mission/`: measured camera paths, complete application performance,
  process-recovery results, snapshot/export/recording validation and final status.

## Extended

- `dashboard/backend/app.py`: host checks, source revision, feature routes, mission
  snapshot events and telemetry model metadata.
- `dashboard/backend/ros_bridge.py`: live host telemetry, optional existing map
  subscription, accurate camera-wait status and watchdog-error disarming.
- `dashboard/backend/safety.py`: acceleration limits and immediate zero/stop behavior.
- `dashboard/backend/obstacle_guard.py`: bounded configurable distance envelope.
- `dashboard/backend/state.py`: optional occupancy grid state.
- `dashboard/backend/mock.py`: identifiable simulated frames.
- `dashboard/static/index.html`, `app.js`, `style.css`: camera-first mission layout,
  measured video indicators and reuse of existing controls/LiDAR interactions.
- `dashboard/tests/test_dashboard.py`: ramp and immediate-stop verification.
- `dashboard/start.sh`: bounded graceful shutdown.
- `dashboard/requirements.txt`: compatible Pillow range preserving both environments.
- Root/dashboard/camera documentation and `.gitignore` for private runtime data.

## Preserved

- `camera/convert_raw10.py`, its eight tests and camera dependency pins.
- Existing ROS 2 Humble, TurtleBot packages, OpenCR firmware and LiDAR driver.
- `turtlectl.py`, `opencr_interface.py`, programming helpers and their tests.
- Existing network/boot/kernel configuration. This mission upgrade applied only the
  user-approved runtime camera mode/exposure/gain and per-process ISP parameters.

No trained model, autonomous navigation, hardware emergency stop or live SLAM
installation is included. Controls remain locked until physical safety validation;
operator approval alone does not override an active LiDAR veto.

## Camera quality correction (2026-10-31)

Removed 7× ISP viewing gain and fixed WB cast; added camera/metering.h and C metering tests, bounded sensor AE and gray-world WB. Changed hardware codec to existing /dev/video31 fixed JPEG Q92; added no-stretch RAW fallback, image-quality telemetry/warnings, relay/ingest/video/model API SHA-256 integrity. Native 720p tested but active 640×480 retained for latency. Added diagnostics/verify_camera_quality.py and diagnostics/camera-quality/REPORT.md. Seventy tests pass. No ROS/boot/driver changes. Manual override remains enabled/disarmed.
