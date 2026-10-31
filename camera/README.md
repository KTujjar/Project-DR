# Current live camera

The live hardware ISP/fixed-quality JPEG pipeline is implemented and measured.
A quality audit removed the old 7× viewing gain, added bounded AE/gray-world WB,
and selected hardware JPEG Q92. See ../diagnostics/camera-quality/REPORT.md and
[../OPERATOR.md](../OPERATOR.md) for launch/mode controls and
[../PERFORMANCE.md](../PERFORMANCE.md) for results. The converter guide and the earlier
streaming proposal below are retained for still-image processing/history.

# Convert the TurtleBot camera capture on your Mac

The capture is verified, headerless `pRAA` (RGGB MIPI RAW10), 3280×2464,
with 4128 bytes per row. This utility reads a file only. It changes no ROS,
boot, device, camera-control or capture-format settings and runs no Pi process.

## Install dependencies on the Mac

Python 3.12 or newer is required for these pinned dependencies. The verified
run used Python 3.15, NumPy 2.5.4 and Pillow 13.0.0 on Apple Silicon.
A separate environment keeps the dashboard environment intact:

```bash
cd /Users/coletriebold/Documents/Turtbot
python3 -m venv .camera-venv
.camera-venv/bin/python -m pip install -r camera/requirements.txt
mkdir -p camera/captures
```

Only NumPy and Pillow are required; no OpenCV, ROS, Homebrew repair or Pi package
installation is needed. The prepared environment and converted files already exist.

## Copy the raw frame from the Pi

From this Mac, with the direct Ethernet cable connected:

```bash
cd /Users/coletriebold/Documents/Turtbot
scp -o UserKnownHostsFile=/Users/coletriebold/Documents/Turtbot/.robot/known_hosts \
  'turtle@[fe80::ba27:ebff:fe79:d40f%en9]:/tmp/camera-test.raw' \
  camera/captures/camera-test.raw
```

The brackets protect the IPv6 host syntax; `%en9` selects the Mac's Ethernet
adapter. Quote the entire remote operand. If you change adapters, substitute
its interface name. SSH/scp may ask for the `turtle` account password; do not
put it in a command or source file. The host key was previously verified and
is saved in this project's `.robot/known_hosts`.

Optional integrity checks:

```bash
ssh -o UserKnownHostsFile=/Users/coletriebold/Documents/Turtbot/.robot/known_hosts \
  'turtle@fe80::ba27:ebff:fe79:d40f%en9' 'sha256sum /tmp/camera-test.raw'
shasum -a 256 camera/captures/camera-test.raw
```

Both copies of the verified capture have SHA-256
`ab75206ce4e3bb658a69fe8c2530459854b7d8f16006a682a40256297b1cb22a`.

## Convert and open

```bash
.camera-venv/bin/python camera/convert_raw10.py \
  camera/captures/camera-test.raw camera/captures/camera-test.jpg \
  --width 3280 --height 2464 --stride 4128
open camera/captures/camera-test.jpg
```

The three geometry flags shown are the defaults. The converter writes:

- `camera-test.jpg`: full-size RGB JPEG, quality 95, 4:4:4 chroma, embedded sRGB profile.
- `camera-test-preview.jpg`: a viewable preview up to 1280 pixels across.
- `camera-test.jpg.json`: checksum, geometry, assumptions, gains, CCM, exposure stretch and diagnostics.

Existing outputs are protected. Choose another output filename for comparisons,
or add `--force` to replace the existing JPEG, preview and processing report.
The raw input is never overwritten.

## How the conversion works

Each group of four pixels occupies five bytes. Bytes 0–3 hold the eight high
bits of each sample; byte 4 holds their two low bits in bit pairs 1:0, 3:2,
5:4 and 7:6. The pixel value is `(high_byte << 2) | low_pair`.
This is **not** a contiguous little-endian bit stream or a 16-bit Bayer file.

Each 3280-pixel row has `3280 / 4 * 5 = 4100` useful bytes. The last 28 bytes of
every 4128-byte row are discarded **before** unpacking. A complete frame is
`4128 * 2464 = 10,171,392` bytes. Truncated frames and mismatched geometry are
rejected. Concatenated complete frames are supported with `--frame N` (zero based).

The processing order is black subtraction and white normalization; Bayer-space
white balance; explicit RGGB-to-RGB bilinear demosaicing with reflected edges;
a 3×3 linear RGB color matrix; viewing exposure adjustment; the piecewise sRGB
transfer curve; then 8-bit JPEG encoding. It does not confuse RGB and BGR or
apply a color matrix to gamma-encoded pixels.

Color defaults are estimates, not recovered metadata:

- `--black 64 --white 1023`: a scalar 10-bit black-level assumption and full-scale white.
  The IMX219 reference tuning uses black level 4096 in a 16-bit domain, corresponding
  to 64 after a six-bit shift. The capture's actual black level is not recorded.
- `--wb gray-world`: estimates RGB gains from usable, unsaturated Bayer cells.
  A scene dominated by one color can bias it. `--wb neutral` disables the estimate;
  `--gains R G B` supplies explicit positive gains and takes precedence over `--wb`.
- `--ccm imx219 --temperature 5000`: linearly interpolates reference Raspberry Pi
  IMX219 color matrices at an **assumed** 5000 K. It does not estimate scene CCT or
  calibrate this sensor. This profile assumes an ordinary color Module 2, not NoIR.
- `--ccm identity` disables matrix correction. A JSON file containing a 3×3 matrix,
  or `{"matrix": [[...], [...], [...]]}`, can supply a calibrated replacement.
- `--exposure auto`: scales the 99.5th-percentile linear luminance toward 0.85,
  limited to ±6 EV. This is a viewing stretch, not a change to captured exposure.
  `--exposure 0` disables it; a numeric value supplies a manual EV correction.

For a neutral diagnostic rendering with no estimated white balance or matrix:

```bash
.camera-venv/bin/python camera/convert_raw10.py camera/captures/camera-test.raw \
  camera/captures/camera-neutral.jpg --wb neutral --ccm identity --exposure 0
```

No denoising, lens-shading correction, HDR reconstruction, sharpening or focus
correction is applied. A color target plus capture metadata would be needed for
reliable color accuracy. Brightening cannot recover missing signal or remove blur.

## Validation of this capture

The remote and local file hashes match; the size is exactly one padded frame.
The JPEG was reopened and fully decoded as RGB, 3280×2464. The preview was visually
inspected: it contains a recognizable scene with cables and bright background
areas, without obvious row shearing or residual Bayer checkerboarding at preview
scale. This validates a usable image path, not focus, calibrated color or video FPS.

Raw minimum/median/99th percentile/maximum: **58 / 66 / 121 / 373** (out of 1023).
With assumed black 64, most samples have little signal. Approximately 15.4% are
at or below that level; none reaches the sensor white level. The default viewing
render used gains **R=1.685, G=1.000, B=2.470**, exposure **+3.61 EV**, and about
0.48% of display pixels clip in at least one channel after processing. The result
is visibly noisy and partly dark. Correct capture exposure/illumination should be
addressed before judging final streaming quality, as a separately authorized step.
The full conversion took about 0.67 seconds on this Mac in one measured run;
this is not a streaming throughput benchmark.

```bash
.camera-venv/bin/python -m unittest camera.test_convert_raw10 -v
```

Eight tests verify known RAW10 byte fixtures including all low-bit positions,
per-row padding, truncation/multiframe handling, RGGB channel order and edges,
white balance, linear color-matrix application, sRGB transfer and decodable JPEGs.

## Proposed live streaming — not started or installed

The read-only inventory now confirms `/dev/video0` is `unicam-image`, linked to
IMX219, with the exact raw format above. `v4l2-ctl` is installed. No `rpicam-vid`,
`libcamera-vid`, `cam` or `ffmpeg` command was found in the inspected PATH.
The Unicam capture node's broad format enumeration is not proof that the sensor
can directly output JPEG or arbitrary resized RGB. No live configuration was changed.

**First stage, preserving the working raw configuration:** run one explicit camera
worker on the Pi using its existing V4L2 setup. It owns the camera exclusively,
continuously dequeues capture buffers, and drops obsolete frames. Send only the
newest complete frame at about **0.5 fps** over SSH, including sequence number,
format, dimensions, stride and original Pi capture timestamp. Keep the full RAW10
unpack/demosaic/color conversion on the Mac; resize to 640×480 and JPEG-encode there.
A future loopback-only authenticated ingest endpoint can return JPEGs through the
existing SSH tunnel into the Pi dashboard's camera store. The existing browser
camera preview can then show them without ROS camera publishers or driver changes.

This path is light on Pi processing but not bandwidth efficient: a full frame is
10.17 MB, approximately **40.7 Mbit/s at 0.5 fps** or **81.4 Mbit/s at 1 fps**, before
transport overhead. Start at 0.5 fps and measure actual latency/CPU/network load;
don't promise 10–30 fps on the previously observed 100 Mbit/s Ethernet link.
Discard old frames instead of queuing them. Preserve capture timestamps through
conversion; receipt timestamps cannot establish sensor synchronization. Expired
frames must show stale/unavailable and never become simulated images.

**Later, for a smoother and lower-bandwidth feed:** use a verified compatible
Pi ISP/libcamera userspace pipeline for demosaicing, exposure/AWB and downscaling,
then JPEG/MJPEG at an initial target of 640×480, 5–10 fps. Feed JPEGs directly to
the dashboard or a separate loopback sidecar over SSH. This target needs benchmarking
on the Pi 3. Existing camera software is not currently sufficient to claim that
path works; any additional installation or capture-mode/control change should be
proposed and approved separately. ROS and working robot drivers can stay intact.
Avoid software-converting the 8MP Bayer stream on the Pi or launching a second
camera owner. No streaming service or automatic camera process was added here.

## Sources

- [Linux pRAA/RAW10 layout](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/pixfmt-srggb10p.html).
- [Raspberry Pi IMX219 reference tuning](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/vc4/data/imx219.json): reference black level and CCM entries, copied into the converter on 2026-10-30.
- [Raspberry Pi camera software](https://www.raspberrypi.com/documentation/accessories/camera-software.html): ISP-based camera pipeline and camera applications. Package availability must be checked for the existing Ubuntu installation.
