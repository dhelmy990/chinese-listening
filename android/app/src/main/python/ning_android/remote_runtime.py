"""Keep the UI/history on the phone and send inference to the user's PC."""
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import numpy as np


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A server redirect must never receive the private bearer token.


class RemoteRuntime:
    device_label = 'Home PC · Turbo INT8'

    def __init__(self, url, token):
        parsed = urlsplit(url.strip())
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Use a server address such as http://192.168.1.20:8766 with no path or login details.')
        try:
            parsed.port
        except ValueError:
            raise ValueError('Invalid server port.') from None
        if not token.strip() or any(c.isspace() for c in token.strip()):
            raise ValueError('Enter the server access token.')
        self.url = url.strip().rstrip('/')
        self.token = token.strip()
        self.opener = build_opener(NoRedirect())

    def request(self, path, data=None, content_type='application/json', timeout=120):
        request = Request(self.url + path, data=data, headers={
            'Authorization': 'Bearer ' + self.token, 'Content-Type': content_type})
        try:
            return self.opener.open(request, timeout=timeout)
        except HTTPError as error:
            messages = {401: 'Access token rejected. Check the token on your PC.',
                        403: 'Access token rejected. Check the token on your PC.',
                        429: 'PC queue is full. Try again after a clip finishes.',
                        503: 'PC models are loading or unavailable. Check the server terminal.'}
            error.close()
            raise RuntimeError(messages.get(error.code, f'PC returned HTTP {error.code}.')) from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError('Cannot reach the PC. Check that the server is running and both devices are on the same network.') from None

    def load_model(self, name, compute_type, threads):
        if (name, compute_type) != ('turbo', 'int8'):
            raise ValueError('PC mode uses Turbo INT8 only.')
        with self.request('/api/status', timeout=8) as response:
            state = json.load(response)
        if not state.get('ready'):
            raise RuntimeError('PC models are not ready. Check the server terminal, then retry.')
        if (state.get('model'), state.get('compute_type')) != ('turbo', 'int8'):
            raise RuntimeError('PC server must use Turbo INT8.')
        return self

    def transcribe(self, audio, **kwargs):
        data = np.asarray(audio, dtype='<f4').tobytes()
        with self.request('/api/transcribe?translate=0', data, 'application/octet-stream') as response:
            for line in response:
                event = json.loads(line)
                if event.get('type') == 'error':
                    raise RuntimeError('PC transcription failed. Check the server terminal and retry the clip.')
                if event.get('type') == 'transcription':
                    text = event.get('text')
                    if not isinstance(text, str):
                        raise RuntimeError('Invalid transcription response from PC.')
                    return [SimpleNamespace(text=text)], None
        raise RuntimeError('PC disconnected before returning a transcription. Retry the clip.')

    def load_translator(self):
        def translate(text):
            with self.request('/api/translate', json.dumps({'text': text}).encode()) as response:
                result = json.load(response)
            if not isinstance(result.get('text'), str):
                raise RuntimeError('Invalid translation response from PC.')
            return result['text']
        return translate
