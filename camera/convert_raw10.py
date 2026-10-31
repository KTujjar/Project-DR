#!/usr/bin/env python3
"""Mac-side pRAA / RGGB MIPI RAW10 converter. Never accesses camera hardware.

Format: https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/pixfmt-srggb10p.html
Reference CCMs: Raspberry Pi libcamera src/ipa/rpi/vc4/data/imx219.json, rpi.ccm.
Color/exposure defaults are viewing estimates, not recovered capture metadata.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageCms

CCM_SOURCE = 'https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/vc4/data/imx219.json'
CCMS = {
    2860: [[2.12089,-.52461,-.59629],[-.85342,2.80445,-.95103],[-.26897,-1.14788,2.41685]],
    4650: [[2.18174,-.70887,-.47287],[-.70196,2.76426,-1.06231],[-.25157,-.71978,1.97135]],
    5858: [[2.32392,-.88421,-.43971],[-.63821,2.58348,-.94527],[-.28541,-.54112,1.82653]],
    7580: [[2.21175,-.53242,-.67933],[-.57875,3.07922,-1.50047],[-.27709,-.73338,2.01048]],
}


def unpack_raw10(data, width, height, stride, frame=0):
    """Four 8-bit MSBs then one byte with pixel 0..3's LSBs at bits 0..7."""
    if width < 4 or width % 4 or height < 2 or height % 2:
        raise ValueError('RGGB width must be a positive multiple of 4; height must be positive and even')
    row_bytes = width // 4 * 5
    if stride < row_bytes:
        raise ValueError(f'Stride {stride} is smaller than packed row size {row_bytes}')
    frame_size = height * stride
    if not data or len(data) % frame_size:
        raise ValueError(f'Expected a whole number of {frame_size}-byte frames; got {len(data)} bytes (truncated data or wrong geometry)')
    if frame < 0 or frame >= len(data) // frame_size:
        raise ValueError('Frame index outside the input file')
    rows = np.frombuffer(data, np.uint8, count=frame_size, offset=frame*frame_size).reshape(height, stride)
    # Strip padding separately on every row before unpacking.
    groups = rows[:, :row_bytes].reshape(height, width//4, 5).astype(np.uint16)
    mosaic = np.empty((height, width), np.uint16)
    for i in range(4):
        mosaic[:, i::4] = (groups[:, :, i] << 2) | ((groups[:, :, 4] >> (2*i)) & 3)
    return mosaic


def estimate_gains(linear):
    """Gray-world estimate from matching, non-clipped 2x2 Bayer cells."""
    r = linear[::2, ::2]
    g = (linear[::2, 1::2] + linear[1::2, ::2]) * .5
    b = linear[1::2, 1::2]
    usable = (np.minimum(np.minimum(r,g),b) > .004) & (np.maximum(np.maximum(r,g),b) < .9)
    count = int(usable.sum())
    if count < 32:
        return np.ones(3, np.float32), count, 'Insufficient usable pixels; neutral gains used'
    means = np.array([r[usable].mean(), g[usable].mean(), b[usable].mean()])
    gains = np.clip(means[1] / means, .25, 8).astype(np.float32)
    return gains, count, 'Gray-world scene estimate; may be biased by dominant scene colors'


def demosaic_rggb(mosaic):
    """Normalized bilinear interpolation, explicit RGB order and reflected edges."""
    h, w = mosaic.shape
    result = np.empty((h,w,3), np.float32)
    for channel in range(3):
        mask = np.zeros((h,w), np.float32)
        if channel == 0:
            mask[::2,::2] = 1
        elif channel == 1:
            mask[::2,1::2] = 1
            mask[1::2,::2] = 1
        else:
            mask[1::2,1::2] = 1
        kernel = ((1,2,1),(2,4,2),(1,2,1)) if channel != 1 else ((0,1,0),(1,4,1),(0,1,0))
        values = np.pad(mosaic*mask, 1, mode='reflect')
        weights = np.pad(mask, 1, mode='reflect')
        numerator, denominator = np.zeros_like(mask), np.zeros_like(mask)
        for y in range(3):
            for x in range(3):
                if kernel[y][x]:
                    numerator += values[y:y+h,x:x+w]*kernel[y][x]
                    denominator += weights[y:y+h,x:x+w]*kernel[y][x]
        result[:,:,channel] = numerator / np.maximum(denominator, 1)
    return result


def color_matrix(setting, temperature):
    if setting == 'identity':
        return np.eye(3, dtype=np.float32)
    if setting == 'imx219':
        keys = sorted(CCMS)
        temp = np.clip(temperature, keys[0], keys[-1])
        high = next(k for k in keys if k >= temp)
        low = max(k for k in keys if k <= temp)
        fraction = 0 if high == low else (temp-low)/(high-low)
        return ((1-fraction)*np.array(CCMS[low]) + fraction*np.array(CCMS[high])).astype(np.float32)
    value = json.loads(Path(setting).read_text())
    matrix = np.asarray(value.get('matrix') if isinstance(value, dict) else value, dtype=np.float32)
    if matrix.shape != (3,3) or not np.isfinite(matrix).all():
        raise ValueError('CCM JSON must contain a finite 3x3 array, or {"matrix": [...]}')
    return matrix


def srgb_encode(linear):
    x = np.clip(linear, 0, 1)
    return np.where(x <= .0031308, 12.92*x, 1.055*np.power(x, 1/2.4)-.055)


def render(raw, black=64., white=1023., gains=None, wb='gray-world', ccm=None, exposure='auto'):
    if not math.isfinite(black) or not math.isfinite(white) or not 0 <= black < white <= 1023:
        raise ValueError('Require 0 <= black < white <= 1023 in 10-bit sensor units')
    linear = np.maximum(raw.astype(np.float32)-black, 0) / (white-black)
    if gains is not None:
        gains = np.asarray(gains, dtype=np.float32)
        count, note = 0, 'Explicit RGB gains supplied'
    elif wb == 'gray-world':
        gains, count, note = estimate_gains(linear)
    else:
        gains, count, note = np.ones(3, np.float32), 0, 'Neutral gains; no white balance'
    if gains.shape != (3,) or not np.isfinite(gains).all() or (gains <= 0).any():
        raise ValueError('RGB gains must be three finite positive numbers')
    linear[::2,::2] *= gains[0]
    linear[::2,1::2] *= gains[1]
    linear[1::2,::2] *= gains[1]
    linear[1::2,1::2] *= gains[2]
    rgb = demosaic_rggb(linear)
    matrix = np.eye(3, dtype=np.float32) if ccm is None else ccm
    rgb = rgb @ matrix.T  # linear sensor RGB -> linear display RGB
    luminance = rgb @ np.array([.2126,.7152,.0722], np.float32)
    reference = float(np.percentile(luminance[::4,::4], 99.5))
    if exposure == 'auto':
        # Viewability stretch, capped at +6 EV; do not present as capture exposure.
        multiplier = float(np.clip(.85/max(reference, 1e-6), 1/64, 64))
        ev = math.log2(multiplier)
    else:
        ev = float(exposure)
        if not math.isfinite(ev) or not -16 <= ev <= 16:
            raise ValueError('Exposure must be auto or an EV adjustment between -16 and 16')
        multiplier = 2**ev
    rgb *= multiplier
    stats = {'white_balance_gains_rgb': gains.tolist(), 'white_balance_usable_cells': count,
             'white_balance_note': note, 'ccm_matrix': matrix.tolist(), 'viewing_exposure_ev': ev,
             'reference_luminance_p99_5_before_exposure': reference,
             'display_pixel_fraction_any_channel_clipped': float(np.mean(np.max(rgb, axis=2) >= 1)),
             'raw_fraction_at_or_below_black': float(np.mean(raw <= black)),
             'raw_fraction_at_or_above_white': float(np.mean(raw >= white))}
    output = np.rint(srgb_encode(rgb)*255).astype(np.uint8)
    return output, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--width', type=int, default=3280)
    parser.add_argument('--height', type=int, default=2464)
    parser.add_argument('--stride', type=int, default=4128, help='bytes per padded row')
    parser.add_argument('--frame', type=int, default=0, help='zero-based frame for concatenated buffers')
    parser.add_argument('--black', type=float, default=64, help='assumed 10-bit black level, not capture metadata')
    parser.add_argument('--white', type=float, default=1023)
    parser.add_argument('--wb', choices=('gray-world','neutral'), default='gray-world')
    parser.add_argument('--gains', type=float, nargs=3, metavar=('R','G','B'))
    parser.add_argument('--ccm', default='imx219', help='imx219, identity, or custom 3x3 JSON filename')
    parser.add_argument('--temperature', type=float, default=5000, help='assumed CCM illuminant Kelvin, not estimated CCT')
    parser.add_argument('--exposure', default='auto', help='viewing EV adjustment or auto')
    parser.add_argument('--quality', type=int, default=95)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    output = args.output or args.input.with_suffix('.jpg')
    report_path = output.with_suffix(output.suffix+'.json')
    preview_path = output.with_name(output.stem+'-preview.jpg')
    try:
        if output.suffix.lower() not in ('.jpg','.jpeg'):
            raise ValueError('Output must use .jpg or .jpeg')
        if not math.isfinite(args.temperature) or args.temperature <= 0:
            raise ValueError('Temperature must be finite and positive')
        if not 1 <= args.quality <= 100:
            raise ValueError('JPEG quality must be between 1 and 100')
        destinations = (output, report_path, preview_path)
        if args.input.resolve() in [p.resolve() for p in destinations]:
            raise ValueError('Output would overwrite the raw input')
        if not args.force and any(p.exists() for p in destinations):
            raise ValueError('Output already exists; choose another filename or pass --force')
        started = time.monotonic()
        data = args.input.read_bytes()
        raw = unpack_raw10(data,args.width,args.height,args.stride,args.frame)
        matrix = color_matrix(args.ccm,args.temperature)
        rgb, stats = render(raw,args.black,args.white,args.gains,args.wb,matrix,args.exposure)
        report = {'input': str(args.input), 'input_sha256': hashlib.sha256(data).hexdigest(),
                  'input_bytes': len(data), 'format': 'pRAA / RGGB MIPI RAW10',
                  'width':args.width,'height':args.height,'stride':args.stride,
                  'row_payload_bytes': args.width//4*5,'row_padding_bytes':args.stride-args.width//4*5,
                  'frame_index':args.frame,'frames_in_file':len(data)//(args.height*args.stride),
                  'raw_percentiles':dict(zip(('min','p1','p50','p99','max'),np.percentile(raw,[0,1,50,99,100]).tolist())),
                  'assumed_black_level':args.black,'white_level':args.white,
                  'ccm':args.ccm,'assumed_ccm_temperature_k':args.temperature,
                  'ccm_reference_source': CCM_SOURCE if args.ccm=='imx219' else None,
                  'color_accuracy':'Approximate viewing render. No capture AWB, actual illuminant, exposure metadata or chart calibration available.',
                  'pipeline':['RAW10 unpack','per-row padding removal','black subtraction/white normalization','white balance in Bayer space','RGB bilinear demosaic','linear CCM','viewing exposure','sRGB encoding','8-bit JPEG'], **stats}
        if report['raw_percentiles']['p99'] < args.black+100:
            report['warning'] = 'Underexposed capture: most sensor values are close to black. Brightening amplifies noise; lost detail cannot be recovered.'
        output.parent.mkdir(parents=True,exist_ok=True)
        image = Image.fromarray(rgb)
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        image.save(output,quality=args.quality,subsampling=0,icc_profile=icc)
        image.thumbnail((1280,1280),Image.Resampling.LANCZOS)
        image.save(preview_path,quality=92,icc_profile=icc)
        report['processing_seconds'] = time.monotonic()-started
        report_path.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(f'JPEG: {output}\nPreview: {preview_path}\nProcessing report: {report_path}')
        print(f'RGB gains: {stats["white_balance_gains_rgb"]}; viewing exposure: {stats["viewing_exposure_ev"]:+.2f} EV')
        if 'warning' in report:
            print('Warning: '+report['warning'])
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())
