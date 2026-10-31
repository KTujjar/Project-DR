# Camera quality audit — 2026-10-31

The live white-out was caused mainly by our earlier fixed **7× ISP digital gain**,
on top of 4× sensor analogue gain and approximately 61 ms exposure. The fixed
WB gains 1.7/1/2.45 also produced a pink cast in the neutral ceiling scene.
These settings were not preserving highlight detail in the JPEG.

## Controlled same-RAW comparison

`original.raw` is a newly captured 640×480 pRAA RAW10 fixture, stride 800 bytes.
Unpacking/padding/Bayer layout use the preserved converter and tested C meter.
Only **1.175%** of its sensor samples were >=1020; RAW detail was still present.
The exact same RAW bytes were processed separately through the existing ISP:

| Processing | Pixels with all RGB channels >=250 | Mean RGB |
|---|---:|---|
| Old 7× gain + fixed WB | 97.580% | 254.4 / 253.8 / 254.1 |
| Unity gain, same fixed WB | 1.297% | 206.4 / 139.5 / 165.7 |
| Unity gain + estimated WB | 1.340% | 161.9 / 164.6 / 161.8 |

That comparison isolates processing from scene/exposure changes. JPEG quantization
was identical for those three fixture renders. The remaining clipped region is
mostly the ceiling light, consistent with RAW saturation. No calibrated color
accuracy, focus/MTF, SNR gain or recovered saturated detail is claimed.
The separate `before.jpg` live frame was 99.994% near white; its scene/time differs.

## Current processing

1. Native RAW10 capture with actual per-row stride; original RAW is not overwritten.
2. ISP black subtraction: 64 in 10-bit units (4096 in ISP 16-bit units).
3. Bounded, smoothed gray-world WB from non-dark, unclipped Bayer cells. The
   ceiling estimate was ~1.265/1/2.275, avoiding the old excessive red gain.
4. Original IMX219 5000 K reference 3×3 CCM and one sRGB gamma curve. Color remains
   approximate; a scene dominated by one color can bias gray-world WB.
5. ISP viewing gain **1×**, sensor digital gain **1×**. A RAW histogram meters
   capture exposure/gain twice per second: middle-grey target .18, broad-highlight
   cap .82, bounded .5–2× adjustment, 10% deadband, exposure <=33.33 ms and analogue
   gain 1–4×. Saturated tiny lights can remain clipped. In dim room views the meter
   can reach its exposure/gain limits without reaching target; more light helps.
6. Existing `/dev/video31` hardware JPEG encoder at fixed **quality 92**. The old
   `/dev/video11` MJPEG bitrate controller changed quantization considerably,
   especially at 720p. Fixed-Q quantization was identical across every final frame.
   Hardware JPEG uses 4:2:0 chroma sampling; it is lossy 8-bit display video.
7. SSH transports the encoded JPEG. Mac decodes for validation/statistics and
   forwards the **same JPEG bytes**; no ISP-path Mac resizing, added exposure,
   contrast filter, sharpening, denoising or JPEG re-encoding. Browser displays
   the JPEG with aspect-fit sizing and no image color/brightness CSS filter.
8. RAW fallback: black/WB/demosaic/CCM/gamma on Mac, **zero viewing EV**, optional
   Lanczos downsize, one JPEG Q92 4:4:4 encode. It keeps the last sensor settings;
   automatic sensor exposure currently runs only in the ISP worker.

The source factory/firmware ISP demosaic and resampler are existing hardware
operations; no claim of RAW-lossless conversion is made. Original converter
behavior for standalone still images is preserved, including explicit EV options.

## Live delivery and byte integrity

The operator repositioned toward room objects. Live 720p output was checked first,
then returned to 640×480 because full-dashboard latency was excessive.

| Corrected fixed-Q92 mode | Delivered decode/ACK FPS | Median / p95 decode-ACK |
|---|---:|---:|
| 1280×720 | 2.04 | 1069 / 1303 ms |
| **640×480 (active)** | **3.56** | **483 / 671 ms** |

These are real multi-client room-scene checks, including this audit client and
already-open dashboards. ACK also includes audit-side image analysis; timestamps
start at Pi end-of-frame, so this is not optical glass-to-glass latency.
Stand-alone fixed-Q92 720p capture/encode was 8.12 fps and 156.8 ms median; that
is not the whole-dashboard delivery rate. Scene entropy and client count matter.

All **44** decoded final video frames matched their relay/ingest SHA-256.
The exact-frame model API returned identical JPEG bytes to the video stream.
One quantization table appeared across all frames. Last live 640 frame: near-white
0.0000%, near-black 0.0000%.
These checks prove preservation of the encoded JPEG through delivery, not lossless
sensor-to-display imaging or calibrated color. Room scene retains visible low-light
noise and the operator's current camera orientation; no automatic rotation was added.

## Changes and verification

- Source backup: `.robot/backups/pre-camera-quality.tar.gz`.
- Changed camera/isp_worker.c, new camera/metering.h and camera/test_metering.py,
  camera/relay.py, camera/configure.py, scripts/missionctl.py, dashboard/backend/features.py,
  dashboard/static/app.js/index.html and docs. Added diagnostics/verify_camera_quality.py.
- 70 tests pass, including compiled C metering tests for RAW10 low bits, row padding,
  black subtraction, bounded WB, saturated/dark frames and exposure deadband; original
  eight converter tests pass. Worker compiled on Pi with -Wall -Wextra -Werror.
- Camera changes use existing runtime sensor controls/ISP/encoder only. No boot,
  driver, firmware, OS, ROS configuration or hardware driver restart performed.
- The armed controller was stopped/disarmed before camera work. Requested manual
  obstacle override remains enabled, controller disarmed after restart; no nonzero
  motion commands were issued by this audit. Original drivers remain PID2877/2879.

Re-run the read-only delivery check on the Mac:

```bash
.camera-venv/bin/python diagnostics/verify_camera_quality.py --seconds 15
```

Evidence: same-raw images, raw metadata/statistics, adaptive-test.json,
fixed-quality-720-test.json, delivery-quality-720.json, delivery-quality.json,
image-statistics.json, after-live.jpg and after-health.json in this directory.

Implementation references: [Raspberry Pi camera pipeline documentation](https://www.raspberrypi.com/documentation/accessories/camera-software.html), [official kernel hardware JPEG controls](https://raw.githubusercontent.com/raspberrypi/linux/rpi-5.15.y/drivers/staging/vc04_services/bcm2835-codec/bcm2835-v4l2-codec.c), [IMX219 sensor driver](https://github.com/raspberrypi/linux/blob/rpi-5.15.y/drivers/media/i2c/imx219.c). These support control semantics; numerical image results above are local measurements.
