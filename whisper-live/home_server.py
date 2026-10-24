"""Temporary authenticated LAN inference, using in-memory clips only."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import time

from aiohttp import web
import numpy as np

from server import load_translator, transcribe

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT.parent / '.checks' / 'home-server.token'
RATE = 16000
MAX_BYTES = RATE * 15 * 4
MAX_REQUESTS = 9  # One active model call plus eight waiting requests.


def load_token(path=TOKEN_FILE):
    """Create a private token once; subsequent launches reuse it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Token path must be a regular file.')
        path.chmod(0o600)
        token = path.read_text().strip()
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(token + '\n')
    if len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
        raise ValueError('Invalid token file; use a private token of at least 32 ASCII characters.')
    return token


def load_model(threads):
    from faster_whisper import WhisperModel
    return WhisperModel('turbo', device='cpu', compute_type='int8', cpu_threads=threads,
                        download_root=str(ROOT / '.models'), local_files_only=True)


def create_app(token, threads=8, *, model_loader=load_model, translator_loader=load_translator):
    if not token:
        raise ValueError('A bearer token is required.')
    state = dict(model=None, translator=None, ready=False, error=None)
    transcription_lock = asyncio.Lock()
    translation_lock = asyncio.Lock()
    requests = 0
    translation_requests = 0

    @web.middleware
    async def authenticate(request, handler):
        supplied = request.headers.get('Authorization', '').encode('utf-8')
        if not secrets.compare_digest(supplied, ('Bearer ' + token).encode('utf-8')):
            return web.json_response({'error': 'Authentication required.'}, status=401,
                                     headers={'WWW-Authenticate': 'Bearer'})
        try:
            return await handler(request)
        except web.HTTPException as error:
            return web.json_response({'error': error.reason}, status=error.status)

    app = web.Application(middlewares=[authenticate], client_max_size=MAX_BYTES + 1)

    async def warmup():
        try:
            model, translator = await asyncio.gather(
                asyncio.to_thread(model_loader, threads), asyncio.to_thread(translator_loader))
            state.update(model=model, translator=translator, ready=True)
            print('Home inference ready: turbo INT8 and OPUS-MT.', flush=True)
        except Exception:
            state['error'] = 'Could not load cached inference models. Check local model installation.'
            print(state['error'], flush=True)

    async def lifecycle(app):
        task = asyncio.create_task(warmup())
        yield
        await task

    app.cleanup_ctx.append(lifecycle)

    async def status(request):
        return web.json_response(dict(ready=state['ready'], model='turbo',
                                      compute_type='int8', error=state['error']))

    async def translate_text(text):
        async with translation_lock:
            started = time.monotonic()
            output = await asyncio.to_thread(state['translator'], text)
            return dict(text=output, compute_seconds=round(time.monotonic() - started, 3))

    async def recognize(request):
        nonlocal requests
        selection = request.query.get('translate', '1')
        if selection not in ('0', '1'):
            return web.json_response({'error': 'translate must be 0 or 1.'}, status=400)
        if request.content_length is not None and request.content_length > MAX_BYTES:
            return web.json_response({'error': 'Clip exceeds 15 seconds.'}, status=413)
        raw = await request.read()
        if len(raw) > MAX_BYTES:
            return web.json_response({'error': 'Clip exceeds 15 seconds.'}, status=413)
        if not raw or len(raw) % 4:
            return web.json_response({'error': 'Expected 16 kHz mono little-endian float32 audio.'}, status=400)
        audio = np.frombuffer(raw, dtype='<f4')
        if not np.isfinite(audio).all() or np.any(np.abs(audio) > 1):
            return web.json_response({'error': 'Audio samples must be finite and between -1 and 1.'}, status=400)
        if not state['ready']:
            return web.json_response({'error': state['error'] or 'Models are loading.'}, status=503)
        if requests >= MAX_REQUESTS:
            return web.json_response({'error': 'Clip queue full. Try again shortly.'}, status=429)
        requests += 1
        request_id = secrets.token_hex(12)
        job = dict(id=request_id, audio=audio, final=True, received_at=time.monotonic())
        response = web.StreamResponse(headers={'Content-Type': 'application/x-ndjson',
                                               'Cache-Control': 'no-store',
                                               'X-Accel-Buffering': 'no'})

        async def event(kind, **fields):
            payload = dict(fields, type=kind, id=request_id)
            await response.write((json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8'))

        try:
            await response.prepare(request)
            await event('accepted')
            async with transcription_lock:
                result = await asyncio.to_thread(transcribe, state['model'], job)
            result.pop('id', None)
            await event('transcription', **result)
            if selection == '1':
                translation = await translate_text(result['text']) if result['text'] else dict(text='', compute_seconds=0)
                await event('translation', **translation)
            await event('done')
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception:
            try:
                await event('error', error='Inference failed. Try a shorter clip or retry.')
            except ConnectionError:
                pass
        finally:
            requests -= 1
        return response

    async def translate(request):
        nonlocal translation_requests
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return web.json_response({'error': 'Expected JSON with a text field.'}, status=400)
        text = body.get('text') if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            return web.json_response({'error': 'Expected 1–2000 characters of Chinese text.'}, status=400)
        if not state['ready']:
            return web.json_response({'error': state['error'] or 'Models are loading.'}, status=503)
        if translation_requests >= MAX_REQUESTS:
            return web.json_response({'error': 'Translation queue full. Try again shortly.'}, status=429)
        translation_requests += 1
        try:
            return web.json_response(await translate_text(text.strip()))
        except Exception:
            return web.json_response({'error': 'Translation failed. Try shorter text or retry.'}, status=503)
        finally:
            translation_requests -= 1

    app.router.add_get('/api/status', status)
    app.router.add_post('/api/transcribe', recognize)
    app.router.add_post('/api/translate', translate)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1', help='Use 0.0.0.0 to accept LAN clients.')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--token-file', type=Path, default=TOKEN_FILE)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error('--threads must be positive')
    try:
        token = load_token(args.token_file)
    except (OSError, ValueError):
        parser.error('Could not create/read a valid private token file.')
    print(f'Bearer token file: {args.token_file.resolve()} (contents hidden)', flush=True)
    web.run_app(create_app(token, args.threads), host=args.host, port=args.port,
                access_log=None, shutdown_timeout=10)


if __name__ == '__main__':
    main()
