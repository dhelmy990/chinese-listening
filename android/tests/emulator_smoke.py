"""Exercise real backend inference through a running debug WebView's DevTools socket.

Run after setup: adb forward tcp:9223 localabstract:webview_devtools_remote_<app-pid>
Then: python3 tests/emulator_smoke.py ../whisper-live/.checks/mandarin.wav
Requires websocket-client on the development machine, not in the Android app.
"""
import array
import base64
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen
import wave

import websocket


class Page:
    def __init__(self):
        target = json.load(urlopen('http://127.0.0.1:9223/json'))[0]
        self.socket = websocket.create_connection(target['webSocketDebuggerUrl'],
                                                  suppress_origin=True, timeout=600)
        self.sequence = 0

    def evaluate(self, expression):
        self.sequence += 1
        self.socket.send(json.dumps(dict(id=self.sequence, method='Runtime.evaluate',
            params=dict(expression=expression, returnByValue=True, awaitPromise=True))))
        while True:
            result = json.loads(self.socket.recv())
            if result.get('id') != self.sequence:
                continue
            if 'error' in result or 'exceptionDetails' in result.get('result', {}):
                raise RuntimeError(result)
            return result['result']['result'].get('value')


def main():
    with wave.open(sys.argv[1]) as source:
        assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (16000, 1, 2)
        pcm16 = array.array('h', source.readframes(80000))
    pcm = array.array('f', (value / 32768 for value in pcm16))
    if sys.byteorder != 'little':
        pcm.byteswap()
    encoded = base64.b64encode(pcm.tobytes()).decode()
    page = Page()
    assert page.evaluate("fetch('/status').then(r=>r.json())")['compute_types'] == ['int8']
    assert not page.evaluate('sessionOpen'), 'Stop and save any active session before testing.'
    translation = page.evaluate("fetch('/translate', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:'你好'})}).then(r=>r.json())")
    assert 'Hello' in translation['text'], translation
    expression = '''new Promise((resolve, reject) => {
        const bytes = Uint8Array.from(atob(ENCODED), c => c.charCodeAt(0));
        const socket = new WebSocket('ws://' + location.host + '/listen');
        const timer = setTimeout(() => { socket.close(); reject(new Error('Inference timeout')); }, 540000);
        socket.onerror = () => { clearTimeout(timer); reject(new Error('WebSocket failed')); };
        socket.onopen = () => {
            for (let offset=0; offset<bytes.length; offset+=64000) socket.send(bytes.slice(offset,offset+64000));
            socket.send(JSON.stringify({type:'parseLastNSeconds',id:0,seconds:5}));
            socket.send('stop');
        };
        socket.onmessage = event => {
            const result = JSON.parse(event.data);
            if (result.error) { clearTimeout(timer); socket.close(); reject(new Error(result.error)); }
            if (result.text !== undefined) { clearTimeout(timer); resolve(result); }
        };
    })'''.replace('ENCODED', json.dumps(encoded))
    started = time.monotonic()
    transcription = page.evaluate(expression)
    assert transcription['text'].strip(), transcription
    assert transcription['model'] == 'turbo' and transcription['compute_type'] == 'int8'
    report = dict(translation=translation, transcription=transcription,
                  emulator_wall_seconds=round(time.monotonic() - started, 2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    page.socket.close()


if __name__ == '__main__':
    main()
