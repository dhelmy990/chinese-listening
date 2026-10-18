"""Android must keep its fixed runtime and private files behind its session cookie."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from aiohttp.test_utils import TestClient, TestServer
from server import create_app


class AndroidServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'data').mkdir()
        (self.root / 'index.html').write_text('Android shared interface')
        self.runtime = Mock()
        self.runtime.load_model.return_value = Mock()
        self.runtime.load_translator.return_value = lambda text: 'Hello'
        app = create_app('turbo', 4, 'int8', runtime=self.runtime,
                         root=self.root, database=self.root / 'history.sqlite3',
                         auth_token='private-test-token')
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.headers = {'Cookie': 'ning_session=private-test-token',
                        'Origin': str(self.client.make_url('/')).rstrip('/')}
        await asyncio.sleep(.02)

    async def test_requires_cookie_even_for_reads(self):
        for path in ('/', '/status', '/vocabulary'):
            self.assertEqual((await self.client.get(path)).status, 403)
        self.assertEqual(await (await self.client.get('/', headers=self.headers)).text(),
                         'Android shared interface')

    async def test_only_turbo_int8_and_injected_runtime(self):
        status = await (await self.client.get('/status', headers=self.headers)).json()
        self.assertEqual(status['models'], ['turbo'])
        self.assertEqual(status['compute_types'], ['int8'])
        self.assertTrue(status['fixed_model'])
        self.assertTrue(status['ready'])
        for settings in ({'model': 'large-v3'}, {'model': 'turbo', 'compute_type': 'float32'}):
            response = await self.client.post('/model', json=settings, headers=self.headers)
            self.assertEqual(response.status, 400)
        self.runtime.load_model.assert_called_once_with('turbo', 'int8', 4)
        response = await self.client.post('/translate', json={'text': '你好'}, headers=self.headers)
        self.assertEqual((await response.json())['text'], 'Hello')

    async def test_session_is_saved_in_private_database(self):
        payload = dict(id='11111111-1111-4111-8111-111111111111',
                       started_at='2026-10-18T10:00:00Z', ended_at='2026-10-18T10:01:00Z',
                       words=[dict(word='你好')])
        response = await self.client.post('/sessions', json=payload, headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertTrue((self.root / 'history.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
