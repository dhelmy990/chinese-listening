"""Browser PCM -> phrase snapshots -> local Whisper -> live Chinese text."""
import argparse
import asyncio
from pathlib import Path
import time

from aiohttp import web, WSMsgType
import numpy as np
from opencc import OpenCC

ROOT = Path(__file__).resolve().parent
RATE = 16000
PARTIAL_SECONDS = 2
PAUSE_SECONDS = 0.7
MAX_SECONDS = 15
VOICE_THRESHOLD = 0.008
SIMPLIFIED = OpenCC('t2s')
MODELS = ('large-v3', 'turbo')


class SpeechBuffer:
    def __init__(self):
        self.audio = np.empty(0, dtype=np.float32)
        self.speaking = False
        self.silence = self.last_partial = self.phrase_id = 0

    def add(self, samples):
        self.audio = np.concatenate((self.audio, samples))
        # shortcut: energy-based pauses; use a speech VAD for noisy rooms.
        voiced = np.sqrt(np.mean(samples ** 2)) >= VOICE_THRESHOLD
        if voiced:
            self.speaking = True
            self.silence = 0
        else:
            self.silence += len(samples)
        if not self.speaking:
            self.audio = self.audio[-RATE // 4:]  # Keep the start of quiet syllables.
            return None
        if self.silence >= PAUSE_SECONDS * RATE or len(self.audio) >= MAX_SECONDS * RATE:
            return self.finish()
        if len(self.audio) - self.last_partial >= PARTIAL_SECONDS * RATE:
            self.last_partial = len(self.audio)
            return self.snapshot(False)

    def snapshot(self, final):
        return dict(id=self.phrase_id, audio=self.audio.copy(), final=final,
                    received_at=time.monotonic())

    def finish(self):
        if not self.speaking:
            return None
        result = self.snapshot(True)
        self.audio = np.empty(0, dtype=np.float32)
        self.speaking = False
        self.silence = self.last_partial = 0
        self.phrase_id += 1
        return result


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
                audio_seconds=round(duration, 2), compute_seconds=round(elapsed, 2),
                delay_seconds=round(time.monotonic() - job['received_at'], 2),
                rtf=round(elapsed / duration, 2))


def create_app(model_name='large-v3', threads=8):
    app = web.Application()
    state = dict(model=None, name=model_name, error=None, busy=False, loading=True, task=None)

    async def load_model(name):
        try:
            from faster_whisper import WhisperModel
            print(f'Loading {name} on CPU (INT8). First run downloads weights.', flush=True)
            state['model'] = await asyncio.to_thread(
                WhisperModel, name, device='cpu', compute_type='int8',
                cpu_threads=threads, download_root=str(ROOT / '.models'),
            )
            print('Model ready. Open http://localhost:8765', flush=True)
        except Exception as error:
            state['error'] = str(error)
            print(f'Model load failed: {error}', flush=True)
        finally:
            state['loading'] = False

    async def lifecycle(app):
        state['task'] = asyncio.create_task(load_model(model_name))
        yield
        await state['task']

    async def status(request):
        return web.json_response(dict(ready=state['model'] is not None,
                                      model=state['name'], error=state['error'],
                                      loading=state['loading'], busy=state['busy'],
                                      device=f'CPU INT8 · {threads} threads'))

    def check_origin(request):
        if request.headers.get('Origin') != f'{request.scheme}://{request.host}':
            raise web.HTTPForbidden(text='Use this localhost page.')

    async def switch_model(request):
        check_origin(request)
        try:
            name = (await request.json())['model']
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text='Expected a model name.')
        if name not in MODELS:
            raise web.HTTPBadRequest(text='Choose large-v3 or turbo.')
        if state['busy'] or state['loading']:
            raise web.HTTPConflict(text='Wait for recording, transcription, or model loading to finish.')
        # Release the previous model; keep only one model in memory.
        state.update(model=None, name=name, error=None, loading=True)
        state['task'] = asyncio.create_task(load_model(name))
        return web.Response(status=202)

    async def microphone(request):
        check_origin(request)
        if state['model'] is None or state['busy']:
            raise web.HTTPServiceUnavailable(text='Model loading or another microphone is active.')
        ws = web.WebSocketResponse(max_msg_size=RATE * 4)
        state['busy'] = True
        try:
            await ws.prepare(request)
        except Exception:
            state['busy'] = False
            raise
        buffer = SpeechBuffer()
        pending = {}
        wake = asyncio.Event()
        stopping = False

        def submit(job):
            if job is not None:
                if job['id'] not in pending and len(pending) >= 8:
                    raise ValueError('Transcription cannot keep up. Stop and select Turbo.')
                # Replace an unprocessed partial with newer audio of the same phrase.
                pending[job['id']] = job
                wake.set()

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
                    result = await asyncio.to_thread(transcribe, state['model'], job)
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
                    submit(buffer.add(audio))
                elif message.type == WSMsgType.TEXT and message.data == 'stop':
                    submit(buffer.finish())
                    break
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
        return web.FileResponse(ROOT / 'index.html')

    async def audio_worklet(request):
        return web.FileResponse(ROOT / 'mic.js')

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/', page)
    app.router.add_get('/mic.js', audio_worklet)
    app.router.add_get('/status', status)
    app.router.add_post('/model', switch_model)
    app.router.add_get('/listen', microphone)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='large-v3', choices=MODELS)
    parser.add_argument('--threads', default=8, type=int)
    args = parser.parse_args()
    web.run_app(create_app(args.model, args.threads), host='127.0.0.1', port=8765)
