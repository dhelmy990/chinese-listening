"""Chrome interaction checks with microphone capture and intercepted inference.
Run with a Python environment containing playwright; uses installed Google Chrome.
No server, model weights, or recorded audio fixture is needed.
"""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(
            headless=True, executable_path='/usr/bin/google-chrome',
            args=['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'])
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(permissions=['microphone'], viewport={'width': 1280, 'height': 900})
        self.errors, self.commands, self.connections = [], [], []
        self.stopped = False
        self.translation_requests = []
        self.hold_translations = False
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('http://localhost:8765/**', self.route)
        self.page.route_web_socket(re.compile(r'.*/listen.*'), self.connect)
        self.page.goto('http://localhost:8765')
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual(self.page.locator('#mode-select').count(), 0)
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#recall").disabled')

    def route(self, route):
        path = urlparse(route.request.url).path
        if path == '/status':
            route.fulfill(json=dict(ready=True, model='turbo', compute_type='int8',
                compute_types=['int8', 'float32'], loading=False, busy=False, error=None, device='CPU'))
        elif path == '/translate':
            self.translation_requests.append(route)
            if not self.hold_translations:
                route.fulfill(json=dict(text='English translation', model='OPUS-MT zh-en', compute_seconds=.1, delay_seconds=.2))
        elif path in ('/', '/app.js', '/mic.js'):
            route.fulfill(path=str(ROOT / ('index.html' if path == '/' else path[1:])),
                          content_type='text/html' if path == '/' else 'text/javascript')
        else:
            route.fulfill(status=404)

    def connect(self, ws):
        self.connections.append(ws)
        def message(data):
            if data == 'stop':
                self.stopped = True
            elif isinstance(data, str):
                self.commands.append(json.loads(data))
        ws.on_message(message)

    def wait_commands(self, count):
        for _ in range(50):
            if len(self.commands) >= count:
                return
            self.page.wait_for_timeout(20)
        self.fail(f'Expected {count} commands, received {len(self.commands)}')

    def send_result(self, clip_id, text='测试文本'):
        self.connections[-1].send(json.dumps(dict(id=clip_id, final=True, text=text, model='turbo',
            compute_type='int8', pinyin='nǐ hǎo', audio_seconds=1, compute_seconds=.1, delay_seconds=.2, rtf=.1)))
        self.page.wait_for_function('(id) => !pendingClips.has(id)', arg=clip_id)

    def pill(self, clip_id):
        return self.page.locator(f'[data-clip-id="{clip_id}"] .pill').first

    def test_new_requests_stay_available_and_results_update_their_own_pills(self):
        for _ in range(3):
            self.page.keyboard.press('Space')
            self.assertTrue(self.page.locator('#recall').is_enabled())
        self.wait_commands(3)
        self.assertEqual([command['id'] for command in self.commands], [0, 1, 2])
        self.assertEqual(self.page.locator('.clip-row').count(), 3)
        self.connections[-1].send(json.dumps(dict(id=0, status='processing')))
        self.page.wait_for_function('document.querySelector(".pill").dataset.state === "processing"')
        self.assertTrue(self.page.locator('#recall').is_enabled())
        self.send_result(2, '第三段')
        self.assertIn('第三段', self.pill(2).inner_text())
        self.assertEqual(self.pill(0).get_attribute('data-state'), 'processing')
        self.connections[-1].send(json.dumps(dict(id=1, error='Queue full. Try again.')))
        self.page.wait_for_function('!pendingClips.has(1)')
        self.assertEqual(self.pill(1).get_attribute('data-state'), 'failed')
        self.send_result(0, '第一段')
        self.assertIn('第一段', self.pill(0).inner_text())
        self.assertEqual(self.page.locator('#pending-count').inner_text(), '0 pending')
        self.pill(0).locator('summary').focus()
        self.page.keyboard.press('Space')
        self.assertTrue(self.pill(0).locator('details').evaluate('(details) => details.open'))
        self.assertEqual(len(self.commands), 3)
        self.page.locator('h1').click()
        self.page.keyboard.press('Space')
        self.wait_commands(4)
        self.page.locator('#stop').click()
        self.page.wait_for_function('context === null && stream === null')
        self.assertTrue(self.page.locator('#start').is_disabled())
        self.assertTrue(self.stopped)
        self.send_result(3, '最后一段')
        self.connections[-1].send(json.dumps(dict(done=True)))
        self.connections[-1].close()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#recall").disabled')
        self.page.keyboard.press('Space')
        self.wait_commands(5)
        self.assertEqual(self.commands[-1]['id'], 4)
        self.assertEqual(self.page.locator('.clip-row').count(), 5)
        self.connections[-1].close()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual(self.pill(4).get_attribute('data-state'), 'failed')
        self.assertEqual(self.errors, [])

    def test_two_panels_share_scroll_and_long_pills_stay_aligned(self):
        for index in range(18):
            self.page.evaluate('parseLastNSeconds(1)')
            self.wait_commands(index + 1)
            self.send_result(index, '较长的中文转录会自然换行。' * (index % 3 + 1))
        self.assertEqual(self.page.locator('.panel-headings > div').count(), 2)
        self.assertIn('English', self.page.locator('.panel-headings > div').nth(1).inner_text())
        self.assertEqual(self.page.locator('.translation').count(), 18)
        self.assertEqual(self.page.locator('.pinyin').first.inner_text(), 'nǐ hǎo')
        viewport_height = self.page.locator('#timeline').bounding_box()['height']
        row_height = self.page.locator('.clip-row').first.bounding_box()['height']
        self.assertGreaterEqual(row_height, (viewport_height - 65) / 3 - 1)
        self.page.evaluate('timeline.scrollTop = 0')
        row = self.page.locator('.clip-row').nth(2)
        before = [cell.bounding_box() for cell in row.locator('.pill').all()]
        bounds = self.page.locator('#timeline').bounding_box()
        self.page.mouse.move(bounds['x'] + bounds['width'] / 2, bounds['y'] + 180)
        self.page.mouse.wheel(0, 300)
        self.page.wait_for_function('timeline.scrollTop > 0')
        self.page.wait_for_timeout(200)
        after = [cell.bounding_box() for cell in row.locator('.pill').all()]
        for left, right in zip(before, after):
            self.assertGreater(left['y'] - right['y'], 0)
            self.assertAlmostEqual(right['y'], after[0]['y'], delta=1)
            self.assertAlmostEqual(right['height'], after[0]['height'], delta=1)
        self.page.evaluate('timeline.scrollTop = 0')
        self.page.evaluate('parseLastNSeconds(1)')
        self.wait_commands(19)
        self.assertEqual(self.page.evaluate('timeline.scrollTop'), 0, 'Do not jump away from older clips')
        self.send_result(18)
        self.assertEqual(self.page.evaluate('timeline.scrollTop'), 0)
        (ROOT / '.checks').mkdir(exist_ok=True)
        self.page.screenshot(path=str(ROOT / '.checks' / 'two-panels.png'), full_page=True)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('timeline.scrollWidth > timeline.clientWidth'))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        self.assertEqual(self.errors, [])

    def test_translation_is_independent_and_errors_keep_chinese_text(self):
        self.hold_translations = True
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '你好')
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "processing"')
        self.page.keyboard.press('Space')
        self.wait_commands(2)
        self.assertTrue(self.page.locator('#recall').is_enabled())
        self.send_result(1, '谢谢')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.translation_requests), 2)
        self.translation_requests[1].fulfill(json=dict(text='Thank you', model='OPUS-MT zh-en', compute_seconds=.1, delay_seconds=.2))
        self.page.wait_for_function('document.querySelectorAll(".translation")[1].dataset.state === "ready"')
        self.assertIn('Thank you', self.page.locator('.translation').nth(1).inner_text())
        self.page.locator('#stop').click()
        self.connections[-1].send(json.dumps(dict(done=True)))
        self.connections[-1].close()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.translation_requests[0].fulfill(status=503, body='Translation failed')
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "failed"')
        self.assertIn('你好', self.pill(0).inner_text())
        self.assertIn('谢谢', self.pill(1).inner_text())
        self.assertEqual(self.errors, [])

    def test_scaling_pointer_keyboard_and_cancellation_while_clips_are_pending(self):
        self.page.evaluate('window.gestureClock = 10000; performance.now = () => window.gestureClock')
        for factor, expected in [(1, 2), (1.2, 2.2), (2, 3)]:
            self.page.locator('#scale').fill(str(factor))
            self.page.locator('h1').click()
            count = len(self.commands)
            self.page.keyboard.down('Space')
            self.page.evaluate('window.gestureClock += 1000')
            self.page.keyboard.down('Space')
            self.page.wait_for_timeout(100)
            self.assertEqual(len(self.commands), count)
            self.page.keyboard.up('Space')
            self.wait_commands(count + 1)
            self.assertEqual(self.commands[-1]['seconds'], expected)
        self.page.locator('#recall').hover()
        self.page.mouse.down()
        self.page.evaluate('window.gestureClock += 1000')
        self.page.mouse.up()
        self.wait_commands(4)
        self.assertEqual(self.commands[-1]['seconds'], 3)
        for cancel in ('escape', 'blur', 'focus'):
            self.page.keyboard.down('Space')
            if cancel == 'escape':
                self.page.keyboard.press('Escape')
            elif cancel == 'blur':
                self.page.evaluate("window.dispatchEvent(new Event('blur'))")
            else:
                self.page.locator('#scale').focus()
            self.page.keyboard.up('Space')
            self.page.wait_for_timeout(100)
            self.assertEqual(len(self.commands), 4)
            self.page.locator('h1').click()
        self.page.locator('#scale').fill('0')
        self.page.locator('h1').click()
        self.page.keyboard.press('Space')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.commands), 4)
        self.assertTrue(self.page.evaluate('active'))
        self.connections[-1].send(json.dumps(dict(error='Audio connection failed')))
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual(self.page.locator('#status').inner_text(), 'Audio connection failed')
        self.assertEqual(self.page.locator('.pill[data-state="failed"]').count(), 4)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
