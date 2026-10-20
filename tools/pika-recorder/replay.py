#!/usr/bin/python3
"""Portable, hardware-free Pika frame source. See REPLAY.md for wire format/API."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time
from safeio import (open_file, exists, file_size, read_text, read_jsonl, write_text,
                    mkdir_new, MAX_ROWS, MAX_DURATION_US, MAX_GAP_US)
from analyze import load_index, uvc_records
from demux import classify, candidate_pairs

MAGIC = b'PKRPv1\r\n'
LENGTHS = struct.Struct('<III')
MAX_IMAGE = 8 * 1024 * 1024
MAX_META = 1024 * 1024


def sha256(path):
    with open_file(path,'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read_at(f, row):
    f.seek(row['offset'])
    data = f.read(row['length'])
    if len(data) != row['length']:
        raise ValueError('Truncated source payload')
    return data


def inspect_recording(root):
    """Validate originals and build portable events; never use device-clock ordering."""
    root = Path(root)
    manifest = json.loads(read_text(root / 'manifest.json'))
    if manifest.get('format_version') != 1 or manifest.get('status') != 'passed':
        raise ValueError('Replay packaging requires a passed format-v1 recording')
    if manifest.get('controls_restored') is not True:
        raise ValueError('Recording does not confirm restored controls')
    events, files, gaps, stereo = [], ['manifest.json'], {}, []
    for name in ('ir', 'color'):
        if not exists(root / (name + '.jsonl')):
            continue
        rows = load_index(root, name)
        metas = load_index(root, name + '-meta')
        byseq = defaultdict(list)
        for row in metas:
            byseq[row['sequence']].append(row)
        if not rows:
            raise ValueError('Empty stream')
        prior = None
        gaps[name] = 0
        with open_file(root / (name + '-meta.bin'),'rb') as f:
            for row in rows:
                if row['length'] <= 0 or row['length'] > MAX_IMAGE or row['flags'] & 0x40:
                    raise ValueError('Invalid image buffer')
                if name == 'ir' and row['length'] != 1280 * 960:
                    raise ValueError('Unexpected GREY image size')
                if row['v4l2_us'] < 0 or row['flags'] & 0xe000 != 0x2000:
                    raise ValueError('Expected common host-monotonic V4L2 timestamps')
                if prior:
                    delta = (row['sequence'] - prior['sequence']) & 0xffffffff
                    if not 0 < delta < (1 << 31) or row['v4l2_us'] < prior['v4l2_us']:
                        raise ValueError('Duplicate/out-of-order sequence or timestamp')
                    gaps[name] += delta - 1
                prior = row
                matches = byseq[row['sequence']]
                if len(matches) != 1:
                    raise ValueError('Missing/duplicate metadata for image sequence')
                meta = matches[0]
                if meta['flags'] & 0x40 or not 0 < meta['length'] <= MAX_META:
                    raise ValueError('Invalid metadata buffer')
                raw = read_at(f, meta)
                headers = uvc_records(raw)
                if not headers or any(h['flags'] & 0x40 for h in headers):
                    raise ValueError('Invalid UVC headers')
                info = classify(raw) if name == 'ir' else {
                    'camera': 'color', 'device_pts_raw': headers[0].get('pts'),
                    'phase_tag': None, 'sdk_light_type': None}
                event = {**row, **info, 'stream': name, 'width': 1280, 'height': 960,
                         'pixel_format': 'GREY' if name == 'ir' else 'MJPG',
                         'payload_file': name + '.bin', 'metadata_file': name + '-meta.bin',
                         'metadata_offset': meta['offset'], 'metadata_length': meta['length']}
                events.append(event)
                if name == 'ir':
                    stereo.append(event)
        files += [name + s for s in ('.bin', '.jsonl', '-meta.bin', '-meta.jsonl')]
    if not events:
        raise ValueError('No image streams')
    events.sort(key=lambda r: (r['v4l2_us'], r['stream'], r['sequence']))
    first = events[0]['v4l2_us']
    for i, event in enumerate(events):
        event['event_id'] = i
        event['time_ns'] = (event['v4l2_us'] - first) * 1000
    if len(events)>MAX_ROWS or events[-1]['time_ns']>MAX_DURATION_US*1000:
        raise ValueError('Aggregate event count/duration exceeds limit')
    pairs = candidate_pairs(stereo)
    report = {'format': 'pika-replay', 'version': 1, 'events': len(events),
              'duration_ns': events[-1]['time_ns'],
              'timing': 'Relative host-monotonic V4L2 image timestamps; raw device PTS retained',
              'groups': dict(Counter(r['camera'] + '/' + str(r['phase_tag']) for r in events)),
              'sequence_gaps': gaps, 'stereo_pair_candidates': len(pairs),
              'unpaired_ir_frames': len(stereo) - 2 * len(pairs),
              'tracking_performed': False, 'calibration_included': False,
              'files': {name: {'bytes': file_size(root / name), 'sha256': sha256(root / name)}
                        for name in files}}
    return events, report


def pack(root):
    events, report = inspect_recording(root)
    dest = Path(root) / 'replay-v1'
    mkdir_new(dest)  # no overwrite; originals are untouched
    with open_file(dest/'events.jsonl','x') as f:
        for row in events:f.write(json.dumps(row)+'\n')
    report['events_sha256'] = sha256(dest / 'events.jsonl')
    write_text(dest / 'manifest.json',json.dumps(report, indent=2) + '\n')
    return report


class Recording:
    """Use frames(speed=0) for deterministic fast processing, speed=1 for pacing.

    Yields (event dict, original image bytes, original UVCH metadata bytes).
    One image is loaded at a time. No camera, Wine or SDK is opened/imported.
    The caller owns processing; slow consumers are not silently dropped.
    """
    def __init__(self, folder, verify=True):
        self.root = Path(folder).absolute()
        self.events, self.report = inspect_recording(self.root)
        if verify:
            saved = json.loads(read_text(self.root / 'replay-v1/manifest.json'))
            if saved != self.report_with_index():
                raise ValueError('Replay integrity check failed: source or index changed')
            stored = read_jsonl(self.root / 'replay-v1/events.jsonl')
            if stored != self.events:
                raise ValueError('Replay event index differs from source metadata')

    def report_with_index(self):
        return {**self.report, 'events_sha256': sha256(self.root / 'replay-v1/events.jsonl')}

    def frames(self, speed=1, start=0, loops=1, clock=time.monotonic_ns, sleep=time.sleep):
        if not math.isfinite(speed) or speed < 0 or not math.isfinite(start) or start < 0 or type(loops)is not int or not 1<=loops<=100:
            raise ValueError('speed/start must be finite and nonnegative; loops must be positive')
        selected = [r for r in self.events if r['time_ns'] >= start * 1e9]
        if not selected:
            raise ValueError('Start time is beyond recording')
        duration=(selected[-1]['time_ns']-selected[0]['time_ns'])/1e9
        if speed and (duration/speed*loops>3600 or any((b['time_ns']-a['time_ns'])/1e9/speed>5 for a,b in zip(selected,selected[1:]))):
            raise ValueError('Paced replay exceeds duration/gap limit')
        with ExitStack() as stack:
            handles = {name: stack.enter_context(open_file(self.root / name,'rb'))
                       for name in {r[k] for r in selected for k in ('payload_file', 'metadata_file')}}
            for loop in range(loops):
                origin = clock()
                first = selected[0]['time_ns']
                for row in selected:
                    data = read_at(handles[row['payload_file']], row)
                    meta = read_at(handles[row['metadata_file']], {
                        'offset': row['metadata_offset'], 'length': row['metadata_length']})
                    due = origin + int((row['time_ns'] - first) / speed) if speed else clock()
                    if speed:
                        while (remaining := due - clock()) > 0:
                            sleep(min(remaining / 1e9, .1))
                    yield {**row, 'replay_loop': loop}, data, meta


def write_packet(stream, event, image, metadata):
    header = json.dumps(event, separators=(',', ':')).encode()
    if len(header) > 65536 or len(image) > MAX_IMAGE or len(metadata) > MAX_META:
        raise ValueError('Packet too large')
    stream.write(LENGTHS.pack(len(header), len(image), len(metadata)))
    stream.write(header); stream.write(image); stream.write(metadata)


def exact(stream, count, eof=False):
    parts = []
    remaining = count
    while remaining:
        part = stream.read(remaining)
        if not part:
            if eof and remaining == count:
                return None
            raise ValueError('Truncated replay stream')
        parts.append(part); remaining -= len(part)
    return b''.join(parts)


def read_packets(stream):
    """Read PKRPv1 from a pipe/file, including short reads; no hardware needed."""
    if exact(stream, len(MAGIC)) != MAGIC:
        raise ValueError('Invalid replay stream magic/version')
    while (lengths := exact(stream, LENGTHS.size, eof=True)) is not None:
        a, b, c = LENGTHS.unpack(lengths)
        if not 0 < a <= 65536 or not 0 < b <= MAX_IMAGE or not 0 < c <= MAX_META:
            raise ValueError('Invalid replay packet sizes')
        event = json.loads(exact(stream, a))
        yield event, exact(stream, b), exact(stream, c)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('recording', type=Path)
    ap.add_argument('--pack', action='store_true', help='Create portable replay index/checksums; never overwrite')
    ap.add_argument('--speed', type=float, default=1, help='1=original timing, 0=unpaced, 0.5=half speed')
    ap.add_argument('--start', type=float, default=0, help='Seek to seconds since first image')
    ap.add_argument('--loops', type=int, default=1)
    ap.add_argument('--packet-stream', action='store_true', help='Write PKRPv1 binary frames to stdout for an app')
    args = ap.parse_args()
    if args.pack:
        if args.packet_stream: ap.error('--pack and --packet-stream cannot combine')
        print(json.dumps(pack(args.recording), indent=2)); return
    recording = Recording(args.recording)
    count = 0; hashes = defaultdict(hashlib.sha256)
    if args.packet_stream: sys.stdout.buffer.write(MAGIC)
    begin = time.monotonic()
    for event, payload, meta in recording.frames(args.speed, args.start, args.loops):
        count += 1
        if args.packet_stream:
            write_packet(sys.stdout.buffer, event, payload, meta)
        else:
            hashes[event['stream']].update(payload)
    if args.packet_stream: sys.stdout.buffer.flush()
    print(json.dumps({'events_replayed': count, 'elapsed_seconds': time.monotonic() - begin,
                      'speed': args.speed, 'payload_stream_sha256': {k: v.hexdigest() for k, v in hashes.items()}}, indent=2),
          file=sys.stderr if args.packet_stream else sys.stdout)


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
    except (OSError, ValueError, KeyError) as e:
        print('Replay failed: ' + str(e), file=sys.stderr); sys.exit(1)
