"""Bounded parser for capture_worker v1 JSON-header/binary-frame protocol."""
import json


def read_frame(stream):
    line=stream.readline(2049)
    if not line: raise EOFError('Camera worker closed')
    if len(line)>2048 or not line.endswith(b'\n'): raise ValueError('Oversized camera header')
    header=json.loads(line)
    size=header.get('bytes')
    if header.get('protocol')!=1 or not isinstance(size,int) or not 0<size<=16_000_000: raise ValueError('Invalid camera protocol/size')
    if header.get('format')=='pRAA':
        if header.get('stride',0)*header.get('height',0)!=size:raise ValueError('Mismatched camera geometry')
    elif header.get('format')=='JPEG':
        if size>2_000_000 or not isinstance(header.get('width'),int) or not isinstance(header.get('height'),int) or not 0<header['width']*header['height']<=8_100_000:raise ValueError('Invalid JPEG geometry')
    else:raise ValueError('Unsupported frame format')
    parts=[];remaining=size
    while remaining:
        block=stream.read(remaining)
        if not block: raise EOFError('Truncated camera frame')
        parts.append(block);remaining-=len(block)
    return header,b''.join(parts)
