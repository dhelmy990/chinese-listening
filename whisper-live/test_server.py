"""Small checks for phrase boundaries; no model download needed."""
import unittest
import asyncio
import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer
import numpy as np

from server import SpeechBuffer, create_app, transcribe


class TranscriptionTests(unittest.TestCase):
    def test_partial_and_final_output_is_simplified(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(text='歡迎體驗語音識別，中文 English 123。')], None)
        for final in (False, True):
            result = transcribe(model, dict(id=0, final=final,
                                audio=np.zeros(16000), received_at=time.monotonic()))
            self.assertEqual(result['text'], '欢迎体验语音识别，中文 English 123。')


class ModelSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loader = patch('faster_whisper.WhisperModel', return_value=Mock())
        self.factory = self.loader.start()
        self.addCleanup(self.loader.stop)
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.origin = {'Origin': str(self.client.make_url('/')).rstrip('/')}
        await self.wait_ready()

    async def wait_ready(self):
        for _ in range(100):
            state = await (await self.client.get('/status')).json()
            if state['ready'] or state['error']:
                return state
            await asyncio.sleep(.01)
        self.fail('Model did not finish loading')

    async def switch(self, name, headers=None):
        return await self.client.post('/model', json={'model': name},
                                      headers=self.origin if headers is None else headers)

    async def test_switch_turbo_then_large(self):
        for name in ('turbo', 'large-v3'):
            self.assertEqual((await self.switch(name)).status, 202)
            state = await self.wait_ready()
            self.assertTrue(state['ready'])
            self.assertEqual(state['model'], name)
            self.assertEqual(self.factory.call_args.args[0], name)

    async def test_invalid_models_and_cross_origin_requests_are_rejected(self):
        self.assertEqual((await self.switch('../arbitrary-model')).status, 400)
        self.assertEqual((await self.switch('turbo', {})).status, 403)
        self.assertEqual(self.factory.call_count, 1)

    async def test_switch_is_blocked_during_recording(self):
        ws = await self.client.ws_connect('/listen', headers=self.origin)
        try:
            self.assertEqual((await self.switch('turbo')).status, 409)
            self.assertEqual(self.factory.call_count, 1)
            await ws.send_str('stop')
            self.assertEqual(await ws.receive_json(), {'done': True})
        finally:
            await ws.close()

    async def test_loading_blocks_another_switch_and_microphone(self):
        release = threading.Event()
        self.factory.side_effect = lambda *args, **kwargs: release.wait(5) or Mock()
        try:
            self.assertEqual((await self.switch('turbo')).status, 202)
            self.assertEqual((await self.switch('large-v3')).status, 409)
            response = await self.client.get('/listen', headers=self.origin)
            self.assertEqual(response.status, 503)
        finally:
            release.set()
            await self.wait_ready()

    async def test_failed_download_can_be_retried(self):
        self.factory.side_effect = RuntimeError('Download failed')
        self.assertEqual((await self.switch('turbo')).status, 202)
        state = await self.wait_ready()
        self.assertFalse(state['ready'])
        self.assertEqual(state['error'], 'Download failed')
        self.factory.side_effect = None
        self.assertEqual((await self.switch('large-v3')).status, 202)
        self.assertTrue((await self.wait_ready())['ready'])


class SpeechBufferTests(unittest.TestCase):
    def test_silence_never_creates_a_transcript(self):
        buffer = SpeechBuffer()
        for _ in range(40):
            self.assertIsNone(buffer.add(np.zeros(1600, dtype=np.float32)))
        self.assertIsNone(buffer.finish())

    def test_partial_and_final_share_id_then_next_phrase_gets_new_id(self):
        buffer = SpeechBuffer()
        partial = None
        for _ in range(20):
            partial = buffer.add(np.full(1600, 0.1, dtype=np.float32)) or partial
        self.assertIsNotNone(partial)
        self.assertFalse(partial['final'])
        final = None
        for _ in range(8):
            final = buffer.add(np.zeros(1600, dtype=np.float32)) or final
        self.assertTrue(final['final'])
        self.assertEqual(final['id'], partial['id'])
        self.assertGreater(len(final['audio']), len(partial['audio']))
        buffer.add(np.full(1600, 0.1, dtype=np.float32))
        self.assertEqual(buffer.finish()['id'], final['id'] + 1)

    def test_stop_flushes_short_speech_once(self):
        buffer = SpeechBuffer()
        buffer.add(np.full(1600, 0.1, dtype=np.float32))
        self.assertTrue(buffer.finish()['final'])
        self.assertIsNone(buffer.finish())

    def test_long_speech_is_bounded_without_losing_audio(self):
        buffer = SpeechBuffer()
        final = None
        for _ in range(150):
            result = buffer.add(np.full(1600, 0.1, dtype=np.float32))
            if result and result['final']:
                final = result
        self.assertIsNotNone(final)
        self.assertEqual(len(final['audio']), 15 * 16000)


if __name__ == '__main__':
    unittest.main()
