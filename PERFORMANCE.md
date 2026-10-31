# Camera quality follow-up — 2026-10-31

The original measurements below describe the earlier pipeline. The corrected
pipeline uses unity viewing gain, bounded sensor AE/gray-world WB, and the existing
hardware image encoder at fixed JPEG quality 92. A 720p stationary capture/encode
test delivered 8.12 fps (156.8 ms median / 185.6 ms p95). The full multi-client
720p pipeline in the noisy room delivered only 2.04 fps and 1069 ms median ACK,
so the live session returned to 640×480. See `diagnostics/camera-quality/REPORT.md`
for clipping and integrity results. The corrected 640×480 room-scene audit delivered
3.56 fps, 483 ms median / 671 ms p95 decode-ACK with multiple dashboards open.
All 44 JPEG hashes matched through video delivery. Prior performance
figures do not describe this corrected quality profile.

# Measured demo performance — 2026-10-31

Reports are under `diagnostics/mission/`. These are measured results, not configured
FPS targets. Scene brightness, JPEG entropy, concurrent viewers and Pi load change
throughput. All movement remained disabled during benchmarks and recovery tests.

## Camera path selection

| Tested path | Native sensor → delivered image | Observed rate | Relevant measured cost |
|---|---|---:|---|
| RAW10 → Mac demosaic/JPEG | 640×480 → 640×480 | 15.01 fps in capture/processing benchmark | 46.1 Mbit/s raw payload; mean Mac processing 15.8 ms |
| RAW10 → Mac resize/JPEG | 1920×1080 → 1280×720 | 4.27 fps | 88.6 Mbit/s raw payload; mean Mac processing 114 ms |
| RAW10 → Mac resize/JPEG | 1640×1232 → thumbnail | 4.47 fps | 91.6 Mbit/s raw payload; mean Mac processing 107 ms |
| Hardware ISP + MJPEG | 640×480 → 640×480 | 15.03 fps in 90-frame capture/encode/SSH benchmark | 29.0 ms median / 30.2 ms p95 capture-to-encoded; 4.70 Mbit/s JPEG payload; zero source skips |
| Hardware ISP + MJPEG | 1920×1080 → 1280×720 | 14.22 fps in 75-frame capture/encode/SSH benchmark | 123 ms median / 153 ms p95 capture-to-encoded; 4.47 Mbit/s JPEG payload; 4 source skips |
| Hardware ISP + MJPEG | 1640×1232 → 1280×960 | 12.45 fps in 60-frame benchmark before latest-frame optimization | 209 ms median capture-to-encoded; 11 source skips |

The native 1280×720 camera mode is not present; the proven 720p output is hardware
scaled from native 1920×1080. The default remains 640×480 for lower latency.
The larger-mode rows measure camera/encode/SSH delivery, not browser FPS. The final
640 worker's queue polling was improved to avoid busy-spinning; its short benchmark
showed roughly 13.5% of one CPU core and 1.3 MB RSS, excluding kernel/GPU buffers.
Larger modes were not rebenchmarked after that polling optimization.

No libcamera/rpicam/GStreamer/FFmpeg pipeline was assumed from device names.
A bounded existing-ISP test initially produced no frame, then succeeded when its
input stream remained active long enough. A real saved Bayer frame was processed
through the existing ISP and MJPEG encoder and decoded before the live worker was
selected. H.264 is advertised by the existing encoder but browser H.264 delivery
was not implemented or claimed. Pi camera-stack/OS upgrades were unnecessary.

## Complete application, 30-second two-client run

`diagnostics/mission/performance.json`: browser open plus a second client receiving,
fully decoding and acknowledging JPEGs. The measured interval was 29.98 seconds:

- **325 decoded/acknowledged frames; 10.81 fps delivered to that client.**
- Capture → backend: **110 ms median, 191 ms p95** (53–375 ms range).
- Capture → client decode/ACK back to Pi: **193 ms median, 310 ms p95**
  (87–506 ms range).
- JPEG payload to measured client: **1.76 Mbit/s** for that scene.
- Actual Ethernet counters during the interval: **2.21 Mbit/s RX, 6.13 Mbit/s TX**,
  including camera relay, both clients and other application traffic.
- Pi total CPU averaged **52.4% across all cores**. Backend was about 108% using
  the convention where one fully used core equals 100%; worker about 23%.
- Backend RSS about **91 MB**; camera helper RSS about **1.1 MB**, excluding
  kernel/GPU buffers. The UI showed roughly 397 MB of 905 MB system RAM used.
- Temperature samples: **65.5–66.6°C**.
- LiDAR **4.98 Hz**; odometry/IMU/battery/joints about **20 Hz**, all fresh.
- Source worker reported **zero source skips**. The relay deliberately skipped
  frames for bounded latency; this client observed 126 sequence gaps. These are
  not hidden or reported as delivered video.

Single-browser live HUD checks commonly showed about 12–13 decoded fps. That is a
rolling observation, distinct from the full two-client benchmark above. Browser
recording produced **1949 frames across 179.96 seconds: 10.82 fps**, 640×480 VP8,
8.9 MB. The downloaded WebM was fully decoded by the Mac's existing FFmpeg without
errors; see `diagnostics/mission/recording.json` and
`camera/captures/mission-recording.webm`. No Pi FFmpeg package was installed.

Latency begins at V4L2 **end of frame**. Sensor exposure is about 61 ms at the
chosen 15 fps runtime setting and is not included before that timestamp.
ACK latency includes return travel and client decode; it is not optical
glass-to-glass measurement or a guarantee of worst-case stopping latency.

## Recovery and data validation

- Owned backend process killed with motion disabled: restored in **14.76 s**,
  camera and scan live again, controller disarmed.
- Owned camera worker terminated: restored in **3.63 s**, new worker PID, no
  hardware-driver restart. The polling test did not observe a stale-state interval.
- LDS/OpenCR driver PIDs stayed unchanged in both tests; no velocity publisher
  or nonzero motion command was created for diagnostics.
- These are process/session failure tests, **not physical Ethernet/camera cable
  unplug tests**. Password-only SSH cannot silently reauthenticate after the
  authenticated master expires; restart can prompt the operator again.
- A real JPEG/LiDAR/odom capture was saved with **65.2 ms** header-timestamp spread,
  below the 250 ms approximate alignment tolerance, with no missing/stale required
  sensor. See `snapshot-proof.json`.
- Mission ZIP was downloaded, integrity checked, and confirmed to exclude runtime
  tokens. See `export-validation.json`.
- UI mock detections rendered over real video, and an external mock API client
  fetched an exact frame and submitted a result with `movement_generated: false`.
- 390 px responsive check had no horizontal overflow. Physical controls remained
  locked throughout; initial wheel-test prechecks remained blocked by LiDAR
  coverage/nearby returns. No physical driving or stopping result is claimed.

## Reproduce

```bash
.camera-venv/bin/python diagnostics/mission_performance.py --seconds 30
# Non-motion fault tests explicitly refuse an enabled/armed controller:
.camera-venv/bin/python diagnostics/recovery_test.py backend
.camera-venv/bin/python diagnostics/recovery_test.py camera
```

Native mode benchmarks require stopping the camera service first and deliberately
change the approved runtime mode. Their results are not substitutes for the
complete application's browser benchmark. Do not run them during driving.

Useful primary references:
[Raspberry Pi camera/ISP interfaces](https://www.raspberrypi.com/documentation/accessories/camera-software.html),
[existing ISP UAPI](https://github.com/raspberrypi/linux/blob/rpi-5.15.y/include/uapi/linux/bcm2835-isp.h),
[LDS-01 limits](https://emanual.robotis.com/docs/en/platform/turtlebot3/appendix_lds_01/),
[SLAM Toolbox ROS package](https://index.ros.org/p/slam_toolbox/).
