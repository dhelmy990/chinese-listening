"""Browser PCM -> requested clips -> queued local Whisper -> Chinese text."""
import argparse
import asyncio
import json
import secrets
import sqlite3
from pathlib import Path
import time

from aiohttp import web, WSMsgType
import numpy as np
from opencc import OpenCC
from pypinyin import lazy_pinyin, Style
from sessions import validate_session, save_session, read_history

ROOT = Path(__file__).resolve().parent
SESSION_DB = ROOT / 'sessions.sqlite3'
RATE = 16000
MAX_SECONDS = 15
MAX_PENDING = 8
SIMPLIFIED = OpenCC('t2s')
MODELS = ('large-v3', 'turbo')
COMPUTE_TYPES = ('int8', 'float32')


def load_translator():
    from translation import load_translator as load
    return load()


def transcribe(model, job):
    started = time.monotonic()
    segments, _ = model.transcribe(
        job['audio'], language='zh', task='transcribe', beam_size=1,
        condition_on_previous_text=False, temperature=0, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    text = SIMPLIFIED.convert(''.join(segment.text for segment in segments).strip())
    elapsed = time.monotonic() - started
    duration = len(job['audio']) / RATE
    return dict(id=job['id'], final=job['final'], text=text,
                pinyin=' '.join(lazy_pinyin(text, style=Style.TONE)),
                audio_seconds=round(duration, 2), compute_seconds=round(elapsed, 2),
                delay_seconds=round(time.monotonic() - job['received_at'], 2),
                rtf=round(elapsed / duration, 2))


def create_app(model_name='large-v3', threads=8, compute_type='int8', *,
               runtime=None, root=None, database=None, auth_token=None):
    root = Path(root) if root is not None else ROOT
    database = Path(database) if database is not None else SESSION_DB

    @web.middleware
    async def authenticate(request, handler):
        if auth_token is not None and not secrets.compare_digest(
                request.cookies.get('ning_session', ''), auth_token):
            raise web.HTTPForbidden(text='Open this page from the Android application.')
        return await handler(request)

    app = web.Application(middlewares=[authenticate])
    if runtime is None:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types('cpu')
    else:
        supported = {'int8'}
    models = ('turbo',) if runtime is not None else MODELS
    if model_name not in models:
        raise ValueError('Unsupported model.')
    compute_types = [kind for kind in COMPUTE_TYPES if kind in supported]
    if compute_type not in compute_types:
        raise ValueError(f'Unsupported CPU representation. Choose from {compute_types}.')
    state = dict(model=None, name=model_name, compute_type=compute_type,
                 error=None, busy=False, loading=True, task=None)
    translator = None
    translation_lock = asyncio.Lock()
    translation_requests = 0

    async def vocabulary_history(request):
        try:
            return web.json_response(await asyncio.to_thread(read_history, database))
        except (sqlite3.Error, OSError):
            raise web.HTTPServiceUnavailable(text='Could not read the local vocabulary database.')

    async def complete_session(request):
        check_origin(request)
        try:
            session = validate_session(await request.json())
        except (ValueError, TypeError) as error:
            raise web.HTTPBadRequest(text=str(error))
        for word in session['words']:
            if not word['pinyin']:
                word['pinyin'] = ' '.join(lazy_pinyin(word['word'], style=Style.TONE))
        try:
            await asyncio.to_thread(save_session, database, session)
        except (sqlite3.Error, OSError):
            raise web.HTTPServiceUnavailable(text='Session could not be saved. Retry when local storage is available.')
        return web.json_response(dict(id=session['id']))

    async def translate(request):
        nonlocal translator, translation_requests
        check_origin(request)
        try:
            body = await request.json()
            text = body.get('text') if isinstance(body, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise ValueError()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Expected 1–2000 characters of Chinese text.')
        if translation_requests >= MAX_PENDING + 1:
            raise web.HTTPTooManyRequests(text='Translation queue full. Try again shortly.')
        translation_requests += 1
        received = time.monotonic()
        try:
            # Independent of Whisper: translation and recognition can run concurrently.
            async with translation_lock:
                if translator is None:
                    translator = await asyncio.to_thread(
                        runtime.load_translator if runtime is not None else load_translator)
                started = time.monotonic()
                output = await asyncio.to_thread(translator, text.strip())
            return web.json_response(dict(text=output, model='OPUS-MT zh-en',
                compute_seconds=round(time.monotonic() - started, 2),
                delay_seconds=round(time.monotonic() - received, 2)))
        except Exception as error:
            raise web.HTTPServiceUnavailable(text=f'Translation failed: {error}')
        finally:
            translation_requests -= 1

    async def load_model(name, compute_type):
        try:
            print(f'Loading {name} on CPU ({compute_type}). First run downloads weights.', flush=True)
            if runtime is not None:
                state['model'] = await asyncio.to_thread(runtime.load_model, name, compute_type, threads)
            else:
                from faster_whisper import WhisperModel
                state['model'] = await asyncio.to_thread(
                    WhisperModel, name, device='cpu', compute_type=compute_type,
                    cpu_threads=threads, download_root=str(root / '.models'),
                )
            print('Model ready. Open http://localhost:8765', flush=True)
        except Exception as error:
            state['error'] = str(error)
            print(f'Model load failed: {error}', flush=True)
        finally:
            state['loading'] = False

    async def lifecycle(app):
        state['task'] = asyncio.create_task(load_model(model_name, compute_type))
        yield
        await state['task']

    async def status(request):
        return web.json_response(dict(ready=state['model'] is not None,
                                      model=state['name'], error=state['error'],
                                      compute_type=state['compute_type'], compute_types=compute_types,
                                      models=models, fixed_model=runtime is not None,
                                      loading=state['loading'], busy=state['busy'],
                                      device=f'CPU · {threads} threads'))

    def check_origin(request):
        if request.headers.get('Origin') != f'{request.scheme}://{request.host}':
            raise web.HTTPForbidden(text='Use this localhost page.')

    async def switch_model(request):
        check_origin(request)
        try:
            settings = await request.json()
            name = settings['model']
            compute_type = settings.get('compute_type', state['compute_type'])
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text='Expected a model name.')
        if name not in models:
            raise web.HTTPBadRequest(text='Choose large-v3 or turbo.')
        if compute_type not in compute_types:
            raise web.HTTPBadRequest(text=f'Unsupported CPU representation. Choose from {compute_types}.')
        if state['busy'] or state['loading']:
            raise web.HTTPConflict(text='Wait for recording, transcription, or model loading to finish.')
        # Release the previous model; keep only one model in memory.
        state.update(model=None, name=name, compute_type=compute_type, error=None, loading=True)
        state['task'] = asyncio.create_task(load_model(name, compute_type))
        return web.Response(status=202)

    async def microphone(request):
        check_origin(request)
        if request.query.get('mode', 'recall') != 'recall':
            raise web.HTTPBadRequest(text='Live transcription is disabled. Request a clip instead.')
        if state['model'] is None or state['busy']:
            raise web.HTTPServiceUnavailable(text='Model loading or another microphone is active.')
        ws = web.WebSocketResponse(max_msg_size=RATE * 4)
        state['busy'] = True
        try:
            await ws.prepare(request)
        except Exception:
            state['busy'] = False
            raise
        recent = np.empty(0, dtype=np.float32)
        clip_id = 0
        pending = {}
        wake = asyncio.Event()
        stopping = False

        async def process():
            try:
                while not stopping or pending:
                    await wake.wait()
                    if not pending:
                        wake.clear()
                        continue
                    job = pending.pop(next(iter(pending)))
                    if not pending:
                        wake.clear()
                    if ws.closed:
                        return
                    await ws.send_json(dict(id=job['id'], status='processing'))
                    try:
                        result = await asyncio.to_thread(transcribe, state['model'], job)
                        result.update(model=state['name'], compute_type=state['compute_type'])
                    except Exception as error:
                        result = dict(id=job['id'], error=str(error))
                    if ws.closed:
                        return
                    await ws.send_json(result)
            except Exception as error:
                if not ws.closed:
                    await ws.send_json(dict(error=str(error)))
                    await ws.close()

        worker = asyncio.create_task(process())
        try:
            async for message in ws:
                if message.type == WSMsgType.BINARY:
                    if not message.data or len(message.data) % 4:
                        raise ValueError('Expected 16 kHz mono float32 audio.')
                    audio = np.frombuffer(message.data, dtype='<f4')
                    if not np.isfinite(audio).all() or np.max(np.abs(audio)) > 1.01:
                        raise ValueError('Invalid audio samples.')
                    recent = np.concatenate((recent, audio))[-MAX_SECONDS * RATE:]
                elif message.type == WSMsgType.TEXT and message.data == 'stop':
                    break
                elif message.type == WSMsgType.TEXT:
                    command = json.loads(message.data)
                    if not isinstance(command, dict) or command.get('type') != 'parseLastNSeconds':
                        raise ValueError('Expected parseLastNSeconds.')
                    request_id = command.get('id', clip_id)
                    if type(request_id) is not int or request_id < clip_id:
                        raise ValueError('Clip IDs must be increasing non-negative integers.')
                    clip_id = request_id + 1
                    seconds = command.get('seconds', 1)
                    if type(seconds) not in (int, float) or not 0 < seconds <= MAX_SECONDS:
                        raise ValueError(f'Seconds must be a number greater than 0 and at most {MAX_SECONDS}.')
                    if not len(recent) or int(seconds * RATE) < 1:
                        raise ValueError('No audio available for this clip yet.')
                    if len(pending) >= MAX_PENDING:
                        await ws.send_json(dict(id=request_id, error='Queue full. Try again after a clip finishes.'))
                        continue
                    pending[request_id] = dict(id=request_id,
                        audio=recent[-int(seconds * RATE):].copy(), final=True,
                        received_at=time.monotonic())
                    wake.set()
                else:
                    break
        except Exception as error:
            if not ws.closed:
                await ws.send_json(dict(error=str(error)))
        finally:
            stopping = True
            if ws.closed:
                pending.clear()
            wake.set()
            await worker  # Let in-flight inference finish before accepting another session.
            state['busy'] = False
            if not ws.closed:
                await ws.send_json(dict(done=True))
                await ws.close()
        return ws

    async def page(request):
        return web.FileResponse(root / 'index.html')

    async def audio_worklet(request):
        return web.FileResponse(root / 'mic.js')

    async def browser_script(request):
        return web.FileResponse(root / 'app.js')

    async def translation_script(request):
        return web.FileResponse(root / 'translations.js')

    async def vocabulary_script(request):
        return web.FileResponse(root / 'vocabulary.js')

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/', page)
    app.router.add_get('/mic.js', audio_worklet)
    app.router.add_get('/app.js', browser_script)
    app.router.add_get('/vocabulary.js', vocabulary_script)
    app.router.add_get('/translations.js', translation_script)
    app.router.add_static('/data/', root / 'data')
    app.router.add_get('/status', status)
    app.router.add_post('/model', switch_model)
    app.router.add_post('/translate', translate)
    app.router.add_get('/vocabulary', vocabulary_history)
    app.router.add_post('/sessions', complete_session)
    app.router.add_get('/listen', microphone)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='large-v3', choices=MODELS)
    parser.add_argument('--threads', default=8, type=int)
    parser.add_argument('--compute-type', default='int8', choices=COMPUTE_TYPES)
    args = parser.parse_args()
    web.run_app(create_app(args.model, args.threads, args.compute_type), host='127.0.0.1', port=8765)
