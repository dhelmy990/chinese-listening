import importlib.util
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))


class RemoteTests(unittest.TestCase):
    def test_remote_adapter_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('ning_android.remote_runtime'))

    def test_remote_inference_and_translation_keep_token_off_url(self):
        from ning_android.remote_runtime import RemoteRuntime
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                requests.append((self.path, self.headers.get('Authorization'), b''))
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(dict(ready=True, model='turbo', compute_type='int8')).encode())
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.path, self.headers.get('Authorization'), body))
                self.send_response(200); self.end_headers()
                if self.path.startswith('/api/transcribe'):
                    self.wfile.write(b'{"type":"accepted","id":"1"}\n')
                    self.wfile.write((json.dumps(dict(type='transcription', id='1', text='你好'))+'\n').encode())
                    self.wfile.write(b'{"type":"done","id":"1"}\n')
                else:self.wfile.write(b'{"text":"Hello","compute_seconds":0.1}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            runtime = RemoteRuntime(f'http://127.0.0.1:{server.server_port}', 'test-secret')
            model = runtime.load_model('turbo', 'int8', 4)
            segments, _ = model.transcribe(np.array([0.25, -0.5], dtype=np.float32))
            self.assertEqual(''.join(s.text for s in segments), '你好')
            self.assertEqual(runtime.load_translator()('你好'), 'Hello')
            self.assertTrue(all(r[1] == 'Bearer test-secret' for r in requests))
            self.assertTrue(all('test-secret' not in r[0] for r in requests))
            self.assertEqual(requests[1][0], '/api/transcribe?translate=0')
            self.assertEqual(np.frombuffer(requests[1][2], dtype='<f4').tolist(), [0.25,-0.5])
        finally:server.shutdown();server.server_close()

    def test_redirect_is_rejected_without_forwarding_token(self):
        from ning_android.remote_runtime import RemoteRuntime
        requests = []
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                requests.append(self.path)
                if self.path == '/api/status':
                    self.send_response(302); self.send_header('Location', '/other'); self.end_headers()
                else:
                    self.send_response(200); self.end_headers()
                    self.wfile.write(b'{"ready":true,"model":"turbo","compute_type":"int8"}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            runtime = RemoteRuntime(f'http://127.0.0.1:{server.server_port}', 'secret')
            with self.assertRaises(RuntimeError): runtime.load_model('turbo','int8',4)
            self.assertEqual(requests, ['/api/status'])
        finally: server.shutdown(); server.server_close()

    def test_rejects_invalid_server_address_and_empty_token(self):
        from ning_android.remote_runtime import RemoteRuntime
        for url in ('file:///tmp/x','http://user:secret@host','http://host/a','http://host?secret=key','http://host/#x'):
            with self.assertRaises(ValueError):RemoteRuntime(url,'key')
        with self.assertRaises(ValueError):RemoteRuntime('http://127.0.0.1:8766','')


if __name__ == '__main__':unittest.main()
