"""HTTP contract checks; fake inference avoids downloading or loading weights."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from aiohttp.test_utils import TestClient, TestServer

import home_server


class HomeServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.translate_entered = threading.Event()
        self.translate_release = threading.Event()
        self.translate_release.set()
        self.recognize_entered = threading.Event()
        self.recognize_release = threading.Event()
        self.recognize_release.set()
        self.failure = False
        self.calls = 0

        def recognize(model, job):
            self.calls += 1
            self.recognize_entered.set()
            if not self.recognize_release.wait(5):
                raise TimeoutError()
            if self.failure:
                raise RuntimeError('secret implementation details')
            return dict(id=job['id'], text='你好', pinyin='nǐ hǎo', compute_seconds=0.01)

        def translate(text):
            self.translate_entered.set()
            if not self.translate_release.wait(5):
                raise TimeoutError()
            return 'Hello'

        self.patch = patch('home_server.transcribe', recognize)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(TestServer(home_server.create_app(
            'test-secret', model_loader=lambda threads: object(),
            translator_loader=lambda: translate)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(self.translate_release.set)
        self.addCleanup(self.recognize_release.set)
        self.headers = {'Authorization': 'Bearer test-secret'}
        self.audio = np.zeros(160, dtype='<f4').tobytes()
        for _ in range(100):
            state = await (await self.client.get('/api/status', headers=self.headers)).json()
            if state['ready']:
                break
            await asyncio.sleep(.01)
        self.assertTrue(state['ready'])

    async def post(self, path='/api/transcribe', data=None):
        return await self.client.post(path, data=self.audio if data is None else data,
                                      headers=self.headers)

    async def event(self, response):
        return json.loads(await asyncio.wait_for(response.content.readline(), 2))

    async def test_every_route_requires_token(self):
        for method, path in [('get', '/api/status'), ('post', '/api/transcribe'),
                             ('post', '/api/translate'), ('get', '/unknown')]:
            for headers in ({}, {'Authorization': 'Bearer wrong'}):
                response = await getattr(self.client, method)(path, headers=headers)
                self.assertEqual(response.status, 401)
                self.assertNotIn('test-secret', await response.text())
        state = await (await self.client.get('/api/status', headers=self.headers)).json()
        self.assertEqual(state, dict(ready=True, model='turbo', compute_type='int8', error=None))

    async def test_transcript_streams_before_translation_and_next_transcript_overlaps(self):
        self.translate_release.clear()
        response = await self.post()
        self.assertEqual(response.content_type, 'application/x-ndjson')
        accepted = await self.event(response)
        self.assertEqual(accepted['type'], 'accepted')
        transcript = await self.event(response)
        self.assertEqual(transcript['type'], 'transcription')
        self.assertEqual(transcript['pinyin'], 'nǐ hǎo')
        self.assertEqual(transcript['id'], accepted['id'])
        self.assertEqual(transcript['compute_seconds'], .01)
        for _ in range(100):
            if self.translate_entered.is_set():
                break
            await asyncio.sleep(.01)
        self.assertTrue(self.translate_entered.is_set())
        second = await self.post('/api/transcribe?translate=0')
        self.assertEqual((await self.event(second))['type'], 'accepted')
        self.assertEqual((await self.event(second))['type'], 'transcription')
        self.assertEqual((await self.event(second))['type'], 'done')
        self.translate_release.set()
        self.assertEqual((await self.event(response))['text'], 'Hello')
        self.assertEqual((await self.event(response))['type'], 'done')

    async def test_rejects_invalid_audio_before_acceptance(self):
        invalid = [b'', b'123', np.array([np.nan], '<f4').tobytes(),
                   np.array([np.inf], '<f4').tobytes(), np.array([1.001], '<f4').tobytes(),
                   np.array([-1.001], '<f4').tobytes()]
        for audio in invalid:
            response = await self.post(data=audio)
            self.assertEqual(response.status, 400)
            self.assertIn('error', await response.json())
        response = await self.post(data=b'\0' * (16000 * 15 * 4 + 4))
        self.assertEqual(response.status, 413)
        self.assertEqual(self.calls, 0)
        response = await self.post('/api/transcribe?translate=0', data=b'\0' * (16000 * 15 * 4))
        self.assertEqual(response.status, 200)
        await response.read()

    async def test_nine_admissions_then_429_and_capacity_recovers(self):
        self.recognize_release.clear()
        responses = []
        try:
            for _ in range(9):
                response = await self.post('/api/transcribe?translate=0')
                self.assertEqual((await self.event(response))['type'], 'accepted')
                responses.append(response)
            extra = await self.post()
            self.assertEqual(extra.status, 429)
        finally:
            self.recognize_release.set()
        for response in responses:
            await response.read()
        recovered = await self.post('/api/transcribe?translate=0')
        self.assertEqual(recovered.status, 200)
        await recovered.read()

    async def test_inference_failure_is_safe_and_releases_admission(self):
        self.failure = True
        response = await self.post()
        self.assertEqual((await self.event(response))['type'], 'accepted')
        error = await self.event(response)
        self.assertEqual(error['type'], 'error')
        self.assertNotIn('secret', json.dumps(error))
        self.failure = False
        response = await self.post('/api/transcribe?translate=0')
        events = [json.loads(line) for line in (await response.text()).splitlines()]
        self.assertEqual([event['type'] for event in events], ['accepted', 'transcription', 'done'])

    async def test_word_translation_and_validation(self):
        response = await self.client.post('/api/translate', json={'text': '你好'}, headers=self.headers)
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(result['text'], 'Hello')
        self.assertIsInstance(result['compute_seconds'], (float, int))
        for body in ({}, {'text': ''}, {'text': ' '}, {'text': 3}, [], {'text': '字' * 2001}):
            response = await self.client.post('/api/translate', json=body, headers=self.headers)
            self.assertEqual(response.status, 400)

    async def test_failed_loader_reports_safe_status(self):
        def fail(threads):
            raise RuntimeError('private details')
        async with TestClient(TestServer(home_server.create_app('token', model_loader=fail,
                translator_loader=lambda: lambda text: text))) as client:
            for _ in range(100):
                state = await (await client.get('/api/status', headers={'Authorization': 'Bearer token'})).json()
                if state['error']:
                    break
                await asyncio.sleep(.01)
            self.assertFalse(state['ready'])
            self.assertTrue(state['error'])
            self.assertNotIn('private', state['error'])
            response = await client.post('/api/transcribe', data=self.audio,
                                        headers={'Authorization': 'Bearer token'})
            self.assertEqual(response.status, 503)

    async def test_disconnect_during_translation_releases_capacity(self):
        self.translate_release.clear()
        response = await self.post()
        await self.event(response)
        await self.event(response)
        response.close()
        self.translate_release.set()
        await asyncio.sleep(.02)
        recovered = await self.post('/api/transcribe?translate=0')
        self.assertEqual(recovered.status, 200)
        self.assertEqual([json.loads(line)['type'] for line in (await recovered.text()).splitlines()],
                         ['accepted', 'transcription', 'done'])

    async def test_word_translation_has_bounded_admission(self):
        self.translate_release.clear()
        pending = [asyncio.create_task(self.client.post('/api/translate', json={'text': '你好'},
                    headers=self.headers)) for _ in range(10)]
        try:
            done, _ = await asyncio.wait(pending, timeout=2, return_when=asyncio.FIRST_COMPLETED)
            self.assertEqual(len(done), 1)
            self.assertEqual(next(iter(done)).result().status, 429)
        finally:
            self.translate_release.set()
        responses = await asyncio.gather(*pending)
        self.assertEqual(sum(response.status == 200 for response in responses), 9)
        for response in responses:
            await response.read()

    async def test_invalid_translation_query_rejected_before_inference(self):
        response = await self.post('/api/transcribe?translate=bad')
        self.assertEqual(response.status, 400)
        self.assertEqual(self.calls, 0)


class TokenTests(unittest.TestCase):
    def test_token_is_private_stable_and_not_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'subdir' / 'token'
            token = home_server.load_token(path)
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(home_server.load_token(path), token)


class ClipClientTests(unittest.TestCase):
    def test_decodes_real_stereo_wav_with_installed_pyav(self):
        import wave
        from request_clip import read_clip
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stereo.wav'
            signal = np.full((6000, 2), 8192, dtype='<i2')
            with wave.open(str(path), 'wb') as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(24000)
                output.writeframes(signal.tobytes())
            samples = np.frombuffer(read_clip(path), dtype='<f4')
            self.assertEqual(len(samples), 4000)
            self.assertTrue(np.isfinite(samples).all())
            self.assertAlmostEqual(float(np.mean(samples)), .25, delta=.01)

    def test_requires_explicit_selection_for_long_audio(self):
        from request_clip import read_clip
        samples = np.zeros(16000 * 16, dtype=np.float32)
        with patch('request_clip.decode_audio', return_value=samples):
            with self.assertRaises(ValueError):
                read_clip('long.wav')
            clip = read_clip('long.wav', start=1, duration=15)
            self.assertEqual(len(clip), 16000 * 15 * 4)
            with self.assertRaises(ValueError):
                read_clip('long.wav', start=-1, duration=1)
            with self.assertRaises(ValueError):
                read_clip('long.wav', duration=16)
            with self.assertRaises(ValueError):
                read_clip('long.wav', start=16, duration=1)

    def test_client_flushes_events_and_requires_done(self):
        from io import StringIO
        from unittest.mock import Mock
        from request_clip import consume_events
        output = Mock()
        transcript = '{"type":"transcription","id":"abc","text":"你好"}\n'
        with patch('request_clip.sys.stdout', output), patch('request_clip.sys.stderr'):
            self.assertEqual(consume_events(StringIO(transcript + '{"type":"done","id":"abc"}\n')), 0)
            self.assertEqual(output.flush.call_count, 2)
            self.assertEqual(consume_events(StringIO(transcript)), 1)
            self.assertEqual(consume_events(StringIO('{"type":"error","id":"abc"}\n')), 1)


if __name__ == '__main__':
    unittest.main()
