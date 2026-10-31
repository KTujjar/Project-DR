# Teammate model interface — API v1.0

Inference runs on your Mac or another privately connected machine. The Pi remains
responsible for robot communications. This API accepts observations only and
never converts detections into movement commands.

## First end-to-end check

Start the mission with `./scripts/start.sh`. Then:

```bash
cd /Users/coletriebold/Documents/Turtbot
.camera-venv/bin/python models/example_client.py --once
# Omit --once to run the explicitly labeled external mock continuously.
```

The example fetches the exact image associated with an input packet and submits
a **MOCK** bounding box. Replace the marked block with your inference. No model
weights or real recognition are included in this project.

Service base URL: `http://127.0.0.1:8872` through the private SSH tunnel.
Every model request includes `Authorization: Bearer <token>`. Read the token from
`.robot/runtime/service.token`, or set `TURTBOT_MODEL_TOKEN_FILE` to a secure copy.
Never commit the token, print it, place it in URLs, or hardcode it. The launcher
creates and deploys it with restricted file permissions.

For a different machine, establish an authorized private SSH tunnel to the Pi's
loopback backend and transfer the token securely. Use `--url` and `--token-file`.
Do not bind movement controls to public Wi-Fi or disable authentication/CORS.

## Input contract

`GET /api/v1/perception/input` returns:

```json
{
  "api_version": "1.0",
  "mode": "hardware",
  "frame": {
    "id": "session-sequence",
    "timestamp": 1793422000.123,
    "width": 640,
    "height": 480,
    "mime": "image/jpeg",
    "url": "/api/v1/perception/frames/session-sequence",
    "calibration": {
      "intrinsics": null,
      "color": "Approximate fixed WB and IMX219 5000K reference CCM"
    }
  },
  "lidar": {"status": "live", "stamp": 1793422000.1, "data": {}},
  "pose": {"status": "live", "stamp": 1793422000.12, "data": {"x": 0, "y": 0, "yaw": 0}}
}
```

The numbers above illustrate the shape; they are not test measurements. Sensor
packets additionally contain age and observed reception frequency. Optional
sensor data can be `null`/missing. Fetch the `frame.url` with the same bearer
header. This returns that exact retained JPEG, not an arbitrary newer image.
Expired frame URLs return 410; request a fresh input and retry.

Coordinates use the **delivered JPEG's dimensions**, not the original sensor
mode. A 1920×1080 sensor mode can produce a 1280×720 hardware-processed image.
Intrinsics/extrinsics have not been calibrated and must not be invented.
Sensor timestamps are from the Pi; do not replace them with model receipt time.
Input sensor samples are independently timestamped. They are not promised to be
hardware synchronized. Check freshness and timestamps yourself if fusion matters.
Mock mode is explicitly `mode: mock`, and its camera is an SVG illustration;
check `frame.mime` before passing bytes to a JPEG decoder.

## Output contract

`POST /api/v1/perception/results`, JSON body:

```json
{
  "api_version": "1.0",
  "model_id": "team-feature-detector",
  "mock": false,
  "frame_id": "session-sequence",
  "timestamp": 1793422000.123,
  "detections": [
    {
      "label": "feature-name",
      "confidence": 0.92,
      "bbox": [0.15, 0.20, 0.30, 0.40],
      "metadata": {"model_version": "demo-1"}
    }
  ]
}
```

`bbox` is normalized `[left, top, width, height]`, with the origin at the image's
upper-left corner. Values and confidence must be finite, within [0,1], and boxes
must remain inside the image. Up to 100 detections per result are accepted.
Set `mock: true` for every synthetic/test result; the operator sees amber MOCK
labels. Real model results remain unvalidated observations, not verified targets.

Optional polygon segmentation instead of, or alongside, a box:

```json
{
  "label": "region",
  "confidence": 0.8,
  "mask": {"polygons": [[[0.1, 0.1], [0.4, 0.1], [0.2, 0.5]]]}
}
```

Each polygon has 3–512 normalized vertices; at most 16 polygons per detection.
Raster masks/RLE are not accepted in v1.0. Convert them to contours first.
Use a distinct `model_id` per model. Up to 12 model streams can coexist.

Results must refer to a retained known frame. Hardware results older than two
seconds are rejected. Live overlays expire once the source frame is older than
750 ms or the result has been present for one second; labels include result age.
This is not object tracking: boxes from a slightly older frame can shift when
the robot or subject moves. Faster inference yields better alignment. Expired
results must never be relabeled as current detections. Empty detections clear
a model's boxes on the next video packet.

Success response includes `movement_generated: false`. Unsupported versions,
nonfinite values and malformed geometry are rejected. Input/result routes return
401 for a missing/wrong token, 409/410 for stale/expired frames, and 422 for invalid
payloads. Camera frames and model outputs have separate paths; there is no model
endpoint for velocity, navigation goals or arming.

The built-in **Enable mock detections** button tests overlays without an external
process. Its box is a placeholder, not a recognition result. Use real frame IDs
for external tests; do not fabricate hardware measurements.
