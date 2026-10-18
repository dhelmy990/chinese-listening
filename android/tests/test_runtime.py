import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))


class RuntimeTests(unittest.TestCase):
    def test_android_adapter_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('ning_android.runtime'))

    def test_byte_level_chinese_decode_and_special_tokens(self):
        from ning_android.runtime import decode_tokens, byte_decoder
        encoder = {value: key for key, value in byte_decoder().items()}
        encoded = ''.join(encoder[value] for value in '你好 world'.encode())
        vocabulary = [encoded[:2], encoded[2:], '<|endoftext|>']
        self.assertEqual(decode_tokens([0, 1, 2], vocabulary), '你好 world')

    def test_download_verifies_and_reuses_file(self):
        from ning_android.download import ensure_file
        data = b'known model'
        item = dict(path='whisper/model.bin', url='https://example.invalid/model',
                    size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('ning_android.download.urlopen', return_value=io.BytesIO(data)) as request:
                ensure_file(root, item, lambda *_: None)
                ensure_file(root, item, lambda *_: None)
                self.assertEqual(request.call_count, 1)
            self.assertEqual((root / item['path']).read_bytes(), data)

    def test_failed_download_never_becomes_ready(self):
        from ning_android.download import ensure_file
        item = dict(path='whisper/model.bin', url='https://example.invalid/model',
                    size=4, sha256=hashlib.sha256(b'good').hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('ning_android.download.urlopen', return_value=io.BytesIO(b'bad!')):
                with self.assertRaises(ValueError):
                    ensure_file(root, item, lambda *_: None)
            self.assertFalse((root / item['path']).exists())

    def test_short_eof_preserves_partial_and_next_attempt_resumes(self):
        from ning_android.download import ensure_file
        data = b'0123456789'
        item = dict(path='whisper/model.bin', url='https://example.invalid/model',
                    size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('ning_android.download.urlopen', return_value=io.BytesIO(data[:5])):
                with self.assertRaises(ValueError):
                    ensure_file(root, item, lambda *_: None)
            self.assertEqual((root / 'whisper/model.bin.part').read_bytes(), data[:5])
            response = io.BytesIO(data[5:])
            response.status = 206
            response.headers = {'Content-Range': 'bytes 5-9/10'}
            with patch('ning_android.download.urlopen', return_value=response) as request:
                ensure_file(root, item, lambda *_: None)
                self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=5-')
            self.assertEqual((root / item['path']).read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
