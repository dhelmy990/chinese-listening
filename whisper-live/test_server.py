"""Checks for clip buffering, asynchronous submission, and model settings."""
import unittest
import asyncio
import time
import threading
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer
import numpy as np

from server import create_app, transcribe


class TranscriptionTests(unittest.TestCase):
    def test_partial_and_final_output_is_simplified(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(text='歡迎體驗語音識別，中文 English 123。')], None)
        for final in (False, True):
            result = transcribe(model, dict(id=0, final=final,
                                audio=np.zeros(16000), received_at=time.monotonic()))
            self.assertEqual(result['text'], '欢迎体验语音识别，中文 English 123。')


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'sessions.sqlite3'
        database_path = patch('server.SESSION_DB', self.database, create=True)
        database_path.start()
        self.addCleanup(database_path.stop)
        translation_loader = patch('server.load_translator', return_value=Mock(return_value='Hello'))
        self.translation_factory = translation_loader.start()
        self.addCleanup(translation_loader.stop)
        capabilities = patch('ctranslate2.get_supported_compute_types',
                             return_value={'int8', 'int8_float32', 'float32'})
        capabilities.start()
        self.addCleanup(capabilities.stop)
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

    def session_payload(self, session_id='11111111-1111-4111-8111-111111111111', words=('研究', '起源')):
        return dict(id=session_id, started_at='2026-10-18T10:00:00+00:00',
            ended_at='2026-10-18T10:01:00+00:00', words=[dict(word=word, pinyin='', level=4,
                meaning='Meaning', sentence='研究起源。', translation='Study origins.') for word in words])

    async def test_session_history_counts_saves_and_retries_only_once(self):
        initial = await self.client.get('/vocabulary')
        self.assertEqual(initial.status, 200)
        self.assertEqual(await initial.json(), dict(entries=[], sessions=[]))
        self.assertFalse(self.database.exists(), 'Reading must not create session data')
        payload = self.session_payload(words=('研究', '起源', '研究'))
        for _ in range(2):
            response = await self.client.post('/sessions', json=payload, headers=self.origin)
            self.assertEqual(response.status, 200)
        history = await (await self.client.get('/vocabulary')).json()
        self.assertEqual(len(history['sessions']), 1)
        entries = {entry['word']: entry for entry in history['entries']}
        self.assertEqual(set(entries), {'研究', '起源'})
        self.assertEqual({entry['save_count'] for entry in entries.values()}, {1})
        word_id = entries['研究']['id']
        self.assertEqual(len(history['sessions'][0]['words']), 2)
        second = self.session_payload('22222222-2222-4222-8222-222222222222', ('研究',))
        self.assertEqual((await self.client.post('/sessions', json=second, headers=self.origin)).status, 200)
        history = await (await self.client.get('/vocabulary')).json()
        entries = {entry['word']: entry for entry in history['entries']}
        self.assertEqual(entries['研究']['id'], word_id)
        self.assertEqual(entries['研究']['save_count'], 2)
        self.assertEqual(entries['起源']['save_count'], 1)
        # A new app instance reads the same on-disk history.
        async with TestClient(TestServer(create_app())) as other:
            self.assertEqual(await (await other.get('/vocabulary')).json(), history)

    async def test_session_save_validation_is_atomic_and_origin_protected(self):
        payload = self.session_payload()
        self.assertEqual((await self.client.post('/sessions', json=payload)).status, 403)
        for invalid in (None, {}, {**payload, 'id': '../file'}, {**payload, 'words': 'word'},
                        {**payload, 'ended_at': 'bad date'},
                        {**payload, 'words': payload['words'] + [dict(word=12)]}):
            response = await self.client.post('/sessions', json=invalid, headers=self.origin)
            self.assertEqual(response.status, 400)
        self.assertEqual(await (await self.client.get('/vocabulary')).json(), dict(entries=[], sessions=[]))

    async def test_session_empty_save_and_database_failure(self):
        payload = self.session_payload(words=())
        self.database.mkdir()  # Simulate an unavailable database path.
        response = await self.client.post('/sessions', json=payload, headers=self.origin)
        self.assertEqual(response.status, 503)
        self.database.rmdir()
        self.assertEqual((await self.client.post('/sessions', json=payload, headers=self.origin)).status, 200)
        history = await (await self.client.get('/vocabulary')).json()
        self.assertEqual(history['entries'], [])
        self.assertEqual(len(history['sessions']), 1)

    async def test_database_error_rolls_back_session_membership_and_counts(self):
        await self.client.post('/sessions', json=self.session_payload(), headers=self.origin)
        before = await (await self.client.get('/vocabulary')).json()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("""CREATE TRIGGER fail_new_word BEFORE INSERT ON words
                WHEN NEW.word = '新词' BEGIN SELECT RAISE(ABORT, 'Simulated storage error'); END""")
        payload = self.session_payload('22222222-2222-4222-8222-222222222222', ('研究', '新词'))
        response = await self.client.post('/sessions', json=payload, headers=self.origin)
        self.assertEqual(response.status, 503)
        self.assertEqual(await (await self.client.get('/vocabulary')).json(), before)

    async def test_switch_turbo_then_large(self):
        for name in ('turbo', 'large-v3'):
            self.assertEqual((await self.switch(name)).status, 202)
            state = await self.wait_ready()
            self.assertTrue(state['ready'])
            self.assertEqual(state['model'], name)
            self.assertEqual(self.factory.call_args.args[0], name)

    async def test_representation_switch_passes_precision_to_both_models(self):
        for name in ('turbo', 'large-v3'):
            for compute_type in ('float32', 'int8'):
                response = await self.client.post('/model', headers=self.origin,
                    json=dict(model=name, compute_type=compute_type))
                self.assertEqual(response.status, 202)
                state = await self.wait_ready()
                self.assertEqual(state.get('compute_type'), compute_type)
                self.assertEqual(state['model'], name)
                self.assertEqual(self.factory.call_args.kwargs['compute_type'], compute_type)

    async def test_model_only_switch_preserves_selected_representation(self):
        response = await self.client.post('/model', headers=self.origin,
            json=dict(model='turbo', compute_type='float32'))
        self.assertEqual(response.status, 202)
        await self.wait_ready()
        self.assertEqual((await self.switch('large-v3')).status, 202)
        state = await self.wait_ready()
        self.assertEqual(state.get('compute_type'), 'float32')

    async def test_unsupported_representation_does_not_replace_loaded_model(self):
        state = await (await self.client.get('/status')).json()
        self.assertEqual(set(state.get('compute_types', [])), {'int8', 'float32'})
        for compute_type in ('float16', 'unknown', None, [], True):
            response = await self.client.post('/model', headers=self.origin,
                json=dict(model='turbo', compute_type=compute_type))
            self.assertEqual(response.status, 400)
        self.assertEqual(self.factory.call_count, 1)
        self.assertTrue((await self.wait_ready())['ready'])

    async def test_representations_are_filtered_by_cpu_support(self):
        with patch('ctranslate2.get_supported_compute_types', return_value={'float32'}):
            with self.assertRaisesRegex(ValueError, 'Unsupported CPU representation'):
                create_app(compute_type='int8')
            async with TestClient(TestServer(create_app(compute_type='float32'))) as client:
                state = await (await client.get('/status')).json()
                self.assertEqual(state['compute_types'], ['float32'])
                self.assertEqual(state['compute_type'], 'float32')

    async def test_invalid_models_and_cross_origin_requests_are_rejected(self):
        self.assertEqual((await self.switch('../arbitrary-model')).status, 400)
        self.assertEqual((await self.switch('turbo', {})).status, 403)
        self.assertEqual(self.factory.call_count, 1)

    async def test_switch_is_blocked_during_recording(self):
        ws = await self.client.ws_connect('/listen', headers=self.origin)
        try:
            self.assertEqual((await self.switch('turbo')).status, 409)
            response = await self.client.post('/model', headers=self.origin,
                json=dict(model='large-v3', compute_type='float32'))
            self.assertEqual(response.status, 409)
            self.assertEqual(self.factory.call_count, 1)
            await ws.send_str('stop')
            self.assertEqual(await self.receive_result(ws), {'done': True})
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

    async def receive_result(self, ws):
        while True:
            result = await ws.receive_json(timeout=2)
            if result.get('status') != 'processing':
                return result

    async def test_live_mode_is_disabled(self):
        response = await self.client.get('/listen?mode=live', headers=self.origin)
        self.assertEqual(response.status, 400)
        self.assertIn('disabled', await response.text())

    async def test_multiple_clips_queue_while_first_runs_and_stop_drains_them(self):
        model = self.factory.return_value
        started, release = threading.Event(), threading.Event()
        captured = []

        def recognize(audio, **kwargs):
            captured.append(audio.copy())
            started.set()
            release.wait(5)
            return [SimpleNamespace(text=str(len(captured)))], None

        model.transcribe.side_effect = recognize
        ws = await self.client.ws_connect('/listen', headers=self.origin)
        try:
            await self.send_audio(ws, np.full(16000, .1))
            await ws.send_json(dict(type='parseLastNSeconds', id=10, seconds=1))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            await self.send_audio(ws, np.full(16000, .2))
            await ws.send_json(dict(type='parseLastNSeconds', id=11, seconds=1))
            await self.send_audio(ws, np.full(16000, .3))
            await ws.send_json(dict(type='parseLastNSeconds', id=12, seconds=1))
            await ws.send_str('stop')
            release.set()
            results = [await self.receive_result(ws) for _ in range(3)]
            self.assertEqual([result.get('id') for result in results], [10, 11, 12])
            self.assertEqual([result.get('text') for result in results], ['1', '2', '3'])
            self.assertEqual(await self.receive_result(ws), {'done': True})
            for samples, value in zip(captured, (.1, .2, .3)):
                np.testing.assert_array_equal(samples, np.full(16000, value, dtype=np.float32))
        finally:
            release.set()
            await ws.close()

    async def test_failed_clip_does_not_abort_next_clip(self):
        model = self.factory.return_value
        model.transcribe.side_effect = [RuntimeError('Test inference failure'),
                                       ([SimpleNamespace(text='下一段')], None)]
        ws = await self.client.ws_connect('/listen', headers=self.origin)
        await self.send_audio(ws, np.zeros(16000))
        for clip_id in (0, 1):
            await ws.send_json(dict(type='parseLastNSeconds', id=clip_id, seconds=1))
        await ws.send_str('stop')
        self.assertEqual(await self.receive_result(ws), {'id': 0, 'error': 'Test inference failure'})
        self.assertEqual((await self.receive_result(ws))['text'], '下一段')
        self.assertEqual(await self.receive_result(ws), {'done': True})
        await ws.close()

    async def test_queue_overflow_rejects_only_excess_clip_and_keeps_session(self):
        model = self.factory.return_value
        started, release = threading.Event(), threading.Event()

        def recognize(audio, **kwargs):
            started.set()
            release.wait(5)
            return [], None

        model.transcribe.side_effect = recognize
        ws = await self.client.ws_connect('/listen', headers=self.origin)
        try:
            await self.send_audio(ws, np.zeros(16000))
            await ws.send_json(dict(type='parseLastNSeconds', id=0, seconds=1))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            for clip_id in range(1, 10):
                await ws.send_json(dict(type='parseLastNSeconds', id=clip_id, seconds=1))
            error = await self.receive_result(ws)
            self.assertEqual(error.get('id'), 9)
            self.assertIn('Queue full', error.get('error', ''))
            release.set()
            results = [await self.receive_result(ws) for _ in range(9)]
            self.assertEqual([result['id'] for result in results], list(range(9)))
            await ws.send_json(dict(type='parseLastNSeconds', id=10, seconds=1))
            self.assertEqual((await self.receive_result(ws))['id'], 10)
            await ws.send_str('stop')
            self.assertEqual(await self.receive_result(ws), {'done': True})
        finally:
            release.set()
            await ws.close()

    async def send_audio(self, ws, audio):
        for offset in range(0, len(audio), 2048):
            await ws.send_bytes(audio[offset:offset + 2048].astype('<f4').tobytes())

    async def test_recall_uses_last_five_seconds_including_silence(self):
        model = self.factory.return_value
        model.transcribe.return_value = ([SimpleNamespace(text='這個詞很複雜。')], None)
        ws = await self.client.ws_connect('/listen?mode=recall', headers=self.origin)
        audio = np.concatenate((np.full(16000, .1), np.full(64000, .2), np.zeros(16000)))
        await self.send_audio(ws, audio)
        await ws.send_json(dict(type='parseLastNSeconds', seconds=5))
        result = await self.receive_result(ws)
        self.assertEqual(result['audio_seconds'], 5)
        self.assertEqual(result['text'], '这个词很复杂。')
        self.assertEqual(result.get('model'), 'large-v3')
        self.assertEqual(result.get('compute_type'), 'int8')
        self.assertTrue(result['final'])
        self.assertGreaterEqual(result['delay_seconds'], result['compute_seconds'])
        np.testing.assert_array_equal(model.transcribe.call_args.args[0], audio[-80000:].astype(np.float32))
        self.assertEqual(model.transcribe.call_count, 1)
        await ws.send_str('stop')
        self.assertEqual(await self.receive_result(ws), {'done': True})
        await ws.close()

    async def test_recall_short_buffer_and_custom_duration(self):
        model = self.factory.return_value
        model.transcribe.return_value = ([], None)
        ws = await self.client.ws_connect('/listen?mode=recall', headers=self.origin)
        await self.send_audio(ws, np.full(8000, .1))
        await ws.send_json(dict(type='parseLastNSeconds', seconds=5))
        self.assertEqual((await self.receive_result(ws))['audio_seconds'], .5)
        await self.send_audio(ws, np.full(48000, .2))
        await ws.send_json(dict(type='parseLastNSeconds', seconds=2))
        result = await self.receive_result(ws)
        self.assertEqual(result['audio_seconds'], 2)
        self.assertEqual(result['id'], 1)
        np.testing.assert_array_equal(model.transcribe.call_args.args[0], np.full(32000, .2, dtype=np.float32))
        await ws.send_str('stop')
        self.assertEqual(await self.receive_result(ws), {'done': True})
        await ws.close()

    async def test_recall_does_no_inference_without_a_request(self):
        model = self.factory.return_value
        model.transcribe.return_value = ([], None)
        ws = await self.client.ws_connect('/listen?mode=recall', headers=self.origin)
        await self.send_audio(ws, np.full(20 * 16000, .1))
        await ws.send_str('stop')
        self.assertEqual(await self.receive_result(ws), {'done': True})
        model.transcribe.assert_not_called()
        await ws.close()

    async def test_recall_rejects_invalid_duration_or_empty_audio(self):
        for seconds in (0, -1, 16, '5', True, None, float('nan'), float('inf')):
            with self.subTest(seconds=seconds):
                ws = await self.client.ws_connect('/listen?mode=recall', headers=self.origin)
                await self.send_audio(ws, np.zeros(1600))
                await ws.send_json(dict(type='parseLastNSeconds', seconds=seconds))
                self.assertIn('error', await self.receive_result(ws))
                await ws.close()
        ws = await self.client.ws_connect('/listen?mode=recall', headers=self.origin)
        await ws.send_json(dict(type='parseLastNSeconds', seconds=5))
        self.assertIn('error', await self.receive_result(ws))
        await ws.close()

    async def test_recall_keeps_capturing_while_frozen_clip_is_processed(self):
        model = self.factory.return_value
        started, release = threading.Event(), threading.Event()

        def recognize(audio, **kwargs):
            started.set()
            release.wait(3)
            return [], None

        model.transcribe.side_effect = recognize
        ws = await self.client.ws_connect('/listen?mode=recall', headers=self.origin)
        try:
            await self.send_audio(ws, np.full(80000, .1))
            await ws.send_json(dict(type='parseLastNSeconds', seconds=5))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            await self.send_audio(ws, np.full(96000, .2))
            release.set()
            self.assertTrue((await self.receive_result(ws))['final'])
            np.testing.assert_array_equal(model.transcribe.call_args.args[0], np.full(80000, .1, dtype=np.float32))
            await ws.send_json(dict(type='parseLastNSeconds', seconds=5))
            self.assertTrue((await self.receive_result(ws))['final'])
            np.testing.assert_array_equal(model.transcribe.call_args.args[0], np.full(80000, .2, dtype=np.float32))
            await ws.send_str('stop')
            self.assertEqual(await self.receive_result(ws), {'done': True})
        finally:
            release.set()
            await ws.close()

    async def translate(self, text, headers=None):
        return await self.client.post('/translate', json={'text': text},
            headers=self.origin if headers is None else headers)

    async def test_translation_overlaps_recognition_and_survives_stop(self):
        started, release = threading.Event(), threading.Event()
        def translate(text):
            started.set()
            release.wait(5)
            return 'Hello'
        self.translation_factory.return_value.side_effect = translate
        task = asyncio.create_task(self.translate('你好'))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            self.factory.return_value.transcribe.return_value = ([SimpleNamespace(text='下一段')], None)
            ws = await self.client.ws_connect('/listen', headers=self.origin)
            await self.send_audio(ws, np.zeros(16000))
            await ws.send_json(dict(type='parseLastNSeconds', seconds=1))
            self.assertEqual((await self.receive_result(ws))['text'], '下一段')
            await ws.send_str('stop')
            self.assertEqual(await self.receive_result(ws), {'done': True})
            self.assertFalse(task.done(), 'Translation must still be running independently')
            await ws.close()
        finally:
            release.set()
            response = await task
        self.assertEqual((await response.json())['text'], 'Hello')

    async def test_translation_queue_is_bounded_and_recovers(self):
        started, release = threading.Event(), threading.Event()
        def translate(text):
            started.set()
            release.wait(5)
            return 'Hello'
        self.translation_factory.return_value.side_effect = translate
        tasks = [asyncio.create_task(self.translate('你好'))]
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            tasks.extend(asyncio.create_task(self.translate('你好')) for _ in range(9))
            done, _ = await asyncio.wait(tasks, timeout=2, return_when=asyncio.FIRST_COMPLETED)
            self.assertEqual(len(done), 1)
            self.assertEqual(next(iter(done)).result().status, 429)
        finally:
            release.set()
            responses = await asyncio.gather(*tasks)
        self.assertEqual(sum(r.status == 200 for r in responses), 9)
        self.assertEqual((await self.translate('你好')).status, 200)

    async def test_pinyin_has_tone_marks(self):
        self.factory.return_value.transcribe.return_value = ([SimpleNamespace(text='你好，中国。')], None)
        ws = await self.client.ws_connect('/listen', headers=self.origin)
        await self.send_audio(ws, np.zeros(16000))
        await ws.send_json(dict(type='parseLastNSeconds', seconds=1))
        result = await self.receive_result(ws)
        self.assertEqual(result.get('pinyin'), 'nǐ hǎo ， zhōng guó 。')
        await ws.send_str('stop')
        await self.receive_result(ws)
        await ws.close()

    async def test_translation_validates_input_and_recovers_after_error(self):
        self.assertEqual((await self.translate('你好', {})).status, 403)
        for text in ('', '   ', None, [], '中' * 2001):
            self.assertEqual((await self.translate(text)).status, 400)
        self.translation_factory.return_value.side_effect = RuntimeError('Test translation failure')
        self.assertEqual((await self.translate('你好')).status, 503)
        self.translation_factory.return_value.side_effect = None
        response = await self.translate('你好')
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['text'], 'Hello')


if __name__ == '__main__':
    unittest.main()
