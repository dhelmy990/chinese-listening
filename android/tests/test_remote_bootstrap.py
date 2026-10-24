import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'whisper-live'))


class RemoteBootstrapTests(unittest.TestCase):
    def tearDown(self):
        from ning_android import bootstrap
        if bootstrap._loop is not None:
            import asyncio
            asyncio.run_coroutine_threadsafe(bootstrap._runner.cleanup(), bootstrap._loop).result(5)
            bootstrap._loop.call_soon_threadsafe(bootstrap._loop.stop)
            bootstrap._thread.join(5)
            bootstrap._loop = bootstrap._runner = bootstrap._thread = None

    def test_reconnect_replaces_local_server_without_phone_models(self):
        from ning_android import bootstrap
        runtime = Mock(device_label='Home PC')
        runtime.load_translator.return_value = lambda text: 'hello'
        callback = SimpleNamespace(update=lambda text: None)
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap, 'RemoteRuntime', return_value=runtime), \
                patch('ning_android.download.ensure_models', side_effect=AssertionError('Must not download phone models')):
            (Path(directory)/'web/data').mkdir(parents=True)
            for _ in range(2):
                address = bootstrap.start(directory, 'private', callback, 'http://127.0.0.1:8766', 'key')
                with urlopen(Request(address+'status',headers={'Cookie':'ning_session=private'})) as response:
                    self.assertEqual(json.load(response)['device'], 'Home PC')
            self.assertFalse((Path(directory)/'models').exists())

    def test_reconnect_during_stalled_translation_finishes_within_ten_seconds(self):
        from ning_android import bootstrap
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def translate(text):
            entered.set()
            try:
                release.wait(30)
                return 'hello'
            finally:
                finished.set()

        runtime = Mock(device_label='Home PC')
        runtime.load_translator.return_value = translate
        callback = SimpleNamespace(update=lambda text: None)
        caller = None
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap, 'RemoteRuntime', return_value=runtime):
                (Path(directory)/'web/data').mkdir(parents=True)
                address = bootstrap.start(directory, 'private', callback, 'http://old-pc:8766', 'key')

                def request_translation():
                    request = Request(address+'translate', data=b'{"text":"hello"}', headers={
                        'Cookie': 'ning_session=private', 'Origin': address.rstrip('/'),
                        'Content-Type': 'application/json',
                    })
                    try:
                        with urlopen(request, timeout=20) as response:
                            response.read()
                    except OSError:
                        pass  # Replacing the server interrupts this old request.

                caller = threading.Thread(target=request_translation)
                caller.start()
                self.assertTrue(entered.wait(5), 'Translation never reached the old server.')
                started = time.monotonic()
                address = bootstrap.start(directory, 'private', callback, 'http://new-pc:8766', 'key')
                self.assertLess(time.monotonic() - started, 10)
                with urlopen(Request(address+'status', headers={'Cookie': 'ning_session=private'}), timeout=5) as response:
                    self.assertEqual(json.load(response)['device'], 'Home PC')
                self.assertFalse(release.is_set(), 'Restart must finish before translation unblocks.')
        finally:
            release.set()
            if caller is not None:
                caller.join(5)
                self.assertFalse(caller.is_alive())
            if entered.is_set():
                self.assertTrue(finished.wait(5), 'Blocked translation worker did not finish.')


if __name__ == '__main__': unittest.main()
