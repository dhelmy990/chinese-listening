"""Send a local audio clip to the home server and print events as they arrive."""
import argparse
import json
import itertools
import math
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

TOKEN_FILE = Path(__file__).resolve().parent.parent / '.checks' / 'home-server.token'
RATE = 16000


def decode_audio(path, sampling_rate=RATE):
    import av
    # PyAV 19 removed metadata_errors, which faster-whisper still passes to av.open.
    resampler = av.audio.resampler.AudioResampler(format='s16', layout='mono', rate=sampling_rate)
    chunks = []
    with av.open(str(path), mode='r') as container:
        for frame in itertools.chain(container.decode(audio=0), [None]):
            if frame is not None:
                frame.pts = None
            for output in resampler.resample(frame):
                chunks.append(output.to_ndarray().reshape(-1))
    if not chunks:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def read_clip(path, start=None, duration=None):
    if start is not None and (not math.isfinite(start) or start < 0):
        raise ValueError('--start must be a finite non-negative number of seconds.')
    if duration is not None and (not math.isfinite(duration) or not 0 < duration <= 15):
        raise ValueError('--duration must be greater than zero and at most 15 seconds.')
    audio = decode_audio(str(path), sampling_rate=RATE)
    first = int((start or 0) * RATE)
    last = first + int(duration * RATE) if duration is not None else len(audio)
    audio = audio[first:last]
    if not len(audio):
        raise ValueError('The selected clip contains no audio.')
    if len(audio) > RATE * 15:
        raise ValueError('Audio exceeds 15 seconds. Select a clip with --start and --duration (up to 15).')
    if not np.isfinite(audio).all() or np.any(np.abs(audio) > 1):
        raise ValueError('Decoded audio contains invalid samples.')
    return np.asarray(audio, dtype='<f4').tobytes()


def consume_events(response):
    for raw in response:
        try:
            event = json.loads(raw)
            kind = event['type']
        except (ValueError, KeyError, TypeError):
            print('Server returned an invalid event.', file=sys.stderr)
            return 1
        print(json.dumps(event, ensure_ascii=False), flush=True)
        if kind == 'error':
            return 1
        if kind == 'done':
            return 0
    print('Server closed the stream before completion.', file=sys.stderr)
    return 1


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the bearer token to a redirected host.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--server', default='http://127.0.0.1:8766')
    parser.add_argument('--token-file', type=Path, default=TOKEN_FILE)
    parser.add_argument('--start', type=float, help='Start time in seconds.')
    parser.add_argument('--duration', type=float, help='Select at most 15 seconds.')
    parser.add_argument('--no-translate', action='store_true')
    args = parser.parse_args()
    server = urllib.parse.urlsplit(args.server)
    if server.scheme not in ('http', 'https') or not server.hostname or server.username or server.password or server.query or server.fragment:
        parser.error('--server must be an HTTP(S) base URL without credentials, query, or fragment.')
    try:
        token = args.token_file.read_text().strip()
        if not token or not token.isascii() or any(char.isspace() for char in token):
            raise ValueError('Token file is invalid.')
        audio = read_clip(args.audio, start=args.start, duration=args.duration)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('Could not read the token file or decode the audio file.', file=sys.stderr)
        return 1
    endpoint = args.server.rstrip('/') + '/api/transcribe?translate=' + ('0' if args.no_translate else '1')
    request = urllib.request.Request(endpoint, data=audio, headers={
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/octet-stream',
        'Accept': 'application/x-ndjson',
    })
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=120) as response:
            return consume_events(response)
    except urllib.error.HTTPError as error:
        print(f'Server rejected the request (HTTP {error.code}).', file=sys.stderr)
    except (urllib.error.URLError, OSError, TimeoutError):
        print('Could not reach the server or the connection was interrupted.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
