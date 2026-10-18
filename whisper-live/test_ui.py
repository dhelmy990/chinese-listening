"""Chrome interaction checks with microphone capture and intercepted inference.
Run with a Python environment containing playwright; uses installed Google Chrome.
A temporary static asset server serves AudioWorklet modules; inference is intercepted.
No model weights or recorded audio fixture is needed.
"""
import json
from pathlib import Path
import re
import unittest
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from sessions import read_history, save_session, validate_session

ROOT = Path(__file__).resolve().parent


class AssetsHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'sessions.sqlite3'
        # Chrome may fetch AudioWorklet modules outside Playwright's route interception.
        self.asset_server = ThreadingHTTPServer(('127.0.0.1', 0), partial(AssetsHandler, directory=str(ROOT)))
        self.asset_thread = threading.Thread(target=self.asset_server.serve_forever, daemon=True)
        self.asset_thread.start()
        self.addCleanup(self.asset_server.server_close)
        self.addCleanup(self.asset_server.shutdown)
        self.base_url = f'http://127.0.0.1:{self.asset_server.server_port}'
        self.saved_requests = []
        self.save_failures = 0
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(
            headless=True, executable_path='/usr/bin/google-chrome',
            args=['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'])
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context(permissions=['microphone'], viewport={'width': 1280, 'height': 900})
        self.page = self.context.new_page()
        self.errors, self.commands, self.connections = [], [], []
        self.stopped = False
        self.translation_requests = []
        self.hold_translations = False
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.context.route(self.base_url + '/**', self.route)
        self.page.route_web_socket(re.compile(r'.*/listen.*'), self.connect)
        self.page.goto(self.base_url)
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
        elif path == '/data/hsk.json':
            route.fulfill(path=str(ROOT / 'data' / 'hsk.json'), content_type='application/json')
        elif path == '/vocabulary':
            route.fulfill(json=read_history(self.database))
        elif path == '/sessions':
            data = route.request.post_data_json
            self.saved_requests.append(data)
            save_session(self.database, validate_session(data))
            if self.save_failures:
                self.save_failures -= 1
                route.fulfill(status=503, body='Save response lost; retry.')
            else:
                route.fulfill(json=dict(id=data['id']))
        elif path in ('/', '/app.js', '/mic.js', '/vocabulary.js', '/translations.js', '/device-audio.js'):
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

    def finish_session(self):
        self.page.locator('#start').click()
        self.page.wait_for_function('context === null && stream === null')
        self.connections[-1].send(json.dumps(dict(done=True)))
        self.connections[-1].close()

    def test_manual_selection_saves_only_at_session_end_and_reuses_ids(self):
        self.page.select_option('#hsk-threshold', '8')
        self.page.locator('h1').click()
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '我们研究起源。研究需要时间。')
        self.assertEqual(len(self.translation_requests), 0)
        word = self.pill(0).locator('[data-word="研究"]').first
        self.assertEqual(word.count(), 1, 'Every Chinese word should be selectable')
        word.click()
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "ready"')
        self.assertEqual(self.pill(0).locator('.hsk-word').all_text_contents(), ['研究', '研究'])
        self.assertEqual({r.request.post_data_json['text'] for r in self.translation_requests}, {'研究'})
        self.assertEqual(self.saved_requests, [])
        self.assertFalse(self.database.exists())
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        first = read_history(self.database)
        self.assertEqual(first['entries'][0]['save_count'], 1)
        word_id = first['entries'][0]['id']
        self.assertEqual([w['word'] for w in self.saved_requests[0]['words']], ['研究'])
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#recall").disabled')
        self.assertEqual(self.page.locator('.word-card').count(), 0)
        self.page.keyboard.press('Space')
        self.wait_commands(2)
        self.send_result(1, '研究')
        self.pill(1).locator('[data-word="研究"]').click()
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        second = read_history(self.database)
        self.assertEqual(len(second['sessions']), 2)
        self.assertEqual(second['entries'][0]['id'], word_id)
        self.assertEqual(second['entries'][0]['save_count'], 2)
        self.page.reload()
        self.page.wait_for_function('document.querySelector("#vocabulary-count").textContent === "1"')
        self.page.locator('#open-vocabulary').click()
        self.assertIn('Saved 2 times', self.page.locator('#vocabulary-list').inner_text())
        self.assertEqual(self.page.locator('#session-list details').count(), 2)
        self.assertEqual(self.errors, [])

    def test_space_always_transcribes_from_focused_controls(self):
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '研究起源。')
        for selector in ('#scale', '#hsk-threshold', '#start', '#open-vocabulary',
                         '.translation', 'summary', '[aria-label="Dismiss 研究"]', '#word-list'):
            self.page.locator(selector).first.focus()
            count = len(self.commands)
            self.page.keyboard.press('Space')
            self.wait_commands(count + 1)
            self.assertTrue(self.page.evaluate('active'))
        self.assertEqual(self.page.locator('.translation').first.get_attribute('aria-pressed'), 'false')
        self.assertFalse(self.pill(0).locator('details').evaluate('(el) => el.open'))
        self.assertEqual(self.page.locator('.word-card').count(), 2)
        self.page.locator('#open-vocabulary').click()
        self.page.locator('#close-vocabulary').focus()
        count = len(self.commands)
        self.page.keyboard.press('Space')
        self.wait_commands(count + 1)
        self.assertTrue(self.page.locator('#vocabulary-dialog').evaluate('(el) => el.open'))
        self.assertEqual(self.errors, [])

    def test_stop_drains_work_and_failed_save_can_retry_without_double_counting(self):
        self.hold_translations = True
        self.save_failures = 1
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.page.locator('#start').click()
        self.page.wait_for_function('context === null')
        self.assertEqual(self.saved_requests, [])
        self.send_result(0, '研究')
        self.connections[-1].send(json.dumps(dict(done=True)))
        self.connections[-1].close()
        self.page.wait_for_timeout(100)
        self.assertTrue(self.page.locator('#start').is_disabled())
        self.assertEqual(self.saved_requests, [])
        self.translation_requests[0].fulfill(json=dict(text='Research'))
        self.page.wait_for_selector('#retry-save:visible')
        self.assertTrue(self.page.locator('#start').is_disabled())
        self.page.locator('#retry-save').click()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual(len(self.saved_requests), 2)
        self.assertEqual(self.saved_requests[0], self.saved_requests[1])
        self.assertEqual(read_history(self.database)['entries'][0]['save_count'], 1)
        self.assertEqual(read_history(self.database)['entries'][0]['meaning'], 'Research')
        self.assertEqual(self.errors, [])

    def test_result_updates_preserve_focused_word_and_a_space_hold(self):
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '研究起源。')
        word = self.pill(0).locator('[data-word="研究"]')
        word.focus()
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate('document.activeElement.dataset.word'), '研究')
        self.page.keyboard.press('Enter')
        self.page.keyboard.press('Space')
        self.wait_commands(2)
        self.page.get_by_role('button', name='Dismiss 研究', exact=True).focus()
        self.page.keyboard.down('Space')
        self.send_result(1, '起源')
        self.assertTrue(self.page.evaluate('holdStartedAt !== null'))
        self.page.keyboard.up('Space')
        self.wait_commands(3)
        self.assertEqual(self.errors, [])

    def test_disconnect_requires_explicit_end_and_does_not_save_on_its_own(self):
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '研究')
        self.connections[-1].close()
        self.page.wait_for_function('context === null && !document.querySelector("#start").disabled')
        self.assertEqual(self.saved_requests, [])
        self.assertEqual(self.page.locator('#start').inner_text(), 'End session & save')
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual(len(self.saved_requests), 1)
        self.assertEqual(read_history(self.database)['entries'][0]['save_count'], 1)
        self.assertEqual(self.errors, [])

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
        self.page.keyboard.press('Enter')
        self.assertTrue(self.pill(0).locator('details').evaluate('(details) => details.open'))
        self.assertEqual(len(self.commands), 3)
        self.page.locator('h1').click()
        self.page.keyboard.press('Space')
        self.wait_commands(4)
        self.page.locator('#start').click()
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
        self.assertEqual(self.page.locator('.panel-headings > div').count(), 3)
        self.assertIn('English', self.page.locator('.panel-headings > div').nth(2).inner_text())
        self.assertEqual(self.page.locator('.translation').count(), 18)
        self.assertEqual(self.page.locator('.pinyin').first.inner_text(), 'nǐ hǎo')
        viewport_height = self.page.locator('#timeline').bounding_box()['height']
        row_height = self.page.locator('.clip-row').first.bounding_box()['height']
        self.assertGreaterEqual(row_height, (viewport_height - 65) / 3 - 1)
        self.page.evaluate('timeline.scrollTop = 0')
        row = self.page.locator('.clip-row').nth(2)
        before = [cell.bounding_box() for cell in row.locator('.pill').all()]
        bounds = self.page.locator('#timeline').bounding_box()
        self.page.mouse.move(bounds['x'] + bounds['width'] / 6, bounds['y'] + 180)
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
        self.assertTrue(self.page.evaluate("document.querySelector('.workspace').scrollWidth <= document.querySelector('.workspace').clientWidth"))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        self.assertEqual(self.errors, [])

    def test_translation_is_independent_and_errors_keep_chinese_text(self):
        self.hold_translations = True
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '研究')
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "processing"')
        self.page.keyboard.press('Space')
        self.wait_commands(2)
        self.assertTrue(self.page.locator('#recall').is_enabled())
        self.send_result(1, '起源')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.translation_requests), 2)
        self.translation_requests[1].fulfill(json=dict(text='Thank you', model='OPUS-MT zh-en', compute_seconds=.1, delay_seconds=.2))
        self.page.wait_for_function('document.querySelectorAll(".translation")[1].dataset.state === "ready"')
        self.assertIn('Thank you', self.page.locator('.translation').nth(1).inner_text())
        self.page.locator('#start').click()
        self.connections[-1].send(json.dumps(dict(done=True)))
        self.connections[-1].close()
        self.assertTrue(self.page.locator('#start').is_disabled())
        self.translation_requests[0].fulfill(status=503, body='Translation failed')
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "failed"')
        self.assertIn('研究', self.pill(0).inner_text())
        self.assertIn('起源', self.pill(1).inner_text())
        self.assertEqual(self.errors, [])

    def test_words_only_dismiss_save_and_reveal_full_fragment(self):
        text = '我们研究起源。研究需要时间。'
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, text)
        self.page.wait_for_selector('#word-list .word-card', timeout=2000)
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "ready"')
        self.assertEqual({r.request.post_data_json['text'] for r in self.translation_requests}, {'研究', '起源'})
        self.assertEqual(self.page.locator('#word-list .word-card').count(), 2)
        self.assertIn('yánjiū', self.page.locator('#word-list').inner_text())
        self.assertEqual(self.page.locator('#vocabulary-count').inner_text(), '0')
        self.page.get_by_role('button', name='Dismiss 研究', exact=True).click()
        self.assertEqual(self.page.locator('#word-list .word-card').count(), 1)
        self.assertEqual(self.pill(0).locator('.hsk-word').all_text_contents(), ['起源'])
        self.assertNotIn('研究', self.page.locator('.translation').inner_text())
        self.assertEqual(self.page.locator('#vocabulary-count').inner_text(), '0')
        card = self.page.locator('.translation')
        dark = card.evaluate('(element) => getComputedStyle(element).backgroundColor')
        card.click()
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "ready"')
        self.assertEqual(card.get_attribute('aria-pressed'), 'true')
        self.assertNotEqual(card.evaluate('(element) => getComputedStyle(element).backgroundColor'), dark)
        self.assertEqual(self.translation_requests[-1].request.post_data_json, {'text': text})
        card.focus()
        self.page.keyboard.press('Enter')
        self.assertEqual(card.get_attribute('aria-pressed'), 'false')
        self.assertEqual(len(self.commands), 1, 'Enter on a translation must only flip it')
        card.click()
        self.assertEqual(len(self.translation_requests), 3, 'Full translation should be cached')
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.locator('#open-vocabulary').click()
        self.assertIn('起源', self.page.locator('#vocabulary-list').inner_text())
        self.assertIn(text, self.page.locator('#vocabulary-list').inner_text())
        self.assertIn('English translation', self.page.locator('#vocabulary-list').inner_text())
        self.page.reload()
        self.page.wait_for_function('document.querySelector("#vocabulary-count").textContent === "1"')
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#recall").disabled')
        self.page.keyboard.press('Space')
        self.wait_commands(2)
        self.send_result(0, text)
        self.page.wait_for_selector('[aria-label="Dismiss 研究"]')
        self.assertEqual(self.errors, [])

    def test_unknown_words_can_be_selected_and_deselected_with_hsk_off(self):
        self.page.select_option('#hsk-threshold', '8')
        self.page.locator('h1').click()
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '我们研究龘。')
        self.assertEqual(len(self.translation_requests), 0)
        self.pill(0).locator('[data-word="龘"]').click()
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "ready"')
        self.assertIn('Unclassified', self.page.locator('#word-list').inner_text())
        self.pill(0).locator('[data-word="龘"]').click()
        self.assertEqual(self.page.locator('.word-card').count(), 0)
        self.pill(0).locator('[data-word="我们"]').focus()
        self.page.keyboard.press('Enter')
        self.assertIn('我们', self.page.locator('#word-list').inner_text())
        self.page.evaluate("() => { Storage.prototype.setItem = () => { throw new Error('Storage full'); }; }")
        self.page.select_option('#hsk-threshold', '4')
        self.assertIn('preference could not be saved', self.page.locator('#vocabulary-status').inner_text())
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual({entry['word'] for entry in read_history(self.database)['entries']}, {'我们', '研究'})
        self.assertEqual(self.errors, [])

    def test_late_hsk_data_does_not_translate_whole_fragment_automatically(self):
        requests = []
        self.page.route('**/data/hsk.json', lambda route: requests.append(route))
        self.page.reload()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#recall").disabled')
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '我们研究起源。')
        self.assertEqual(len(self.translation_requests), 0)
        requests[0].fulfill(path=str(ROOT / 'data' / 'hsk.json'), content_type='application/json')
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "ready"')
        self.assertEqual({r.request.post_data_json['text'] for r in self.translation_requests}, {'研究', '起源'})
        self.assertEqual(self.page.locator('#vocabulary-count').inner_text(), '0')
        self.assertEqual(self.errors, [])

    def test_middle_scroll_is_independent_and_session_status_stays_below_it(self):
        data = json.loads((ROOT / 'data' / 'hsk.json').read_text())
        terms = [word for word, entry in data.items() if entry[0] >= 4 and len(word) >= 2][:30]
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '，'.join(terms))
        self.page.wait_for_function('document.querySelectorAll(".word-card").length >= 10')
        self.page.evaluate('timeline.scrollTop = 0')
        save_before = self.page.locator('#session-status').bounding_box()
        bounds = self.page.locator('#word-list').bounding_box()
        self.page.mouse.move(bounds['x'] + bounds['width'] / 2, bounds['y'] + 100)
        self.page.mouse.wheel(0, 350)
        self.page.wait_for_function('document.querySelector("#word-list").scrollTop > 0')
        self.assertEqual(self.page.evaluate('timeline.scrollTop'), 0)
        self.assertAlmostEqual(self.page.locator('#session-status').bounding_box()['y'], save_before['y'], delta=1)
        middle_position = self.page.locator('#word-list').evaluate('(el) => el.scrollTop')
        self.page.evaluate('timeline.scrollTop = 100')
        self.assertEqual(self.page.locator('#word-list').evaluate('(el) => el.scrollTop'), middle_position)
        (ROOT / '.checks').mkdir(exist_ok=True)
        self.page.screenshot(path=str(ROOT / '.checks' / 'dark-three-panels.png'), full_page=True)
        self.assertEqual(self.errors, [])

    def test_session_waits_for_translations_and_full_flip_does_not_replace_word_view(self):
        self.hold_translations = True
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '研究起源和三明治。')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.translation_requests), 2)
        self.assertEqual(self.page.locator('#vocabulary-count').inner_text(), '0')
        card = self.page.locator('.translation')
        card.click()
        card.click()
        self.translation_requests[0].fulfill(json=dict(text='Research'))
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.translation_requests), 3)
        self.assertEqual(self.translation_requests[2].request.post_data_json['text'], '研究起源和三明治。')
        self.translation_requests[2].fulfill(json=dict(text='Study origins and sandwiches.'))
        self.page.wait_for_timeout(100)
        self.assertEqual(card.get_attribute('aria-pressed'), 'false')
        self.assertNotIn('Study origins and sandwiches.', card.inner_text())
        self.translation_requests[1].fulfill(json=dict(text='Origin'))
        self.page.wait_for_timeout(100)
        self.translation_requests[3].fulfill(json=dict(text='Sandwich'))
        self.page.wait_for_function('document.querySelector(".translation").dataset.state === "ready"')
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.locator('#open-vocabulary').click()
        bank = self.page.locator('#vocabulary-list').inner_text()
        self.assertIn('Research', bank)
        self.assertIn('Study origins and sandwiches.', bank)
        self.assertEqual(self.errors, [])

    def test_existing_bank_and_stale_tab_settings_preserve_saved_words(self):
        legacy = {'threshold': 4, 'entries': [dict(word='旧词', pinyin='jiù cí', level=4,
            sentence='以前的句子。', translation='An older sentence.')]}
        self.page.evaluate('(data) => localStorage.setItem("chinese-listening-vocabulary-v1", JSON.stringify(data))', legacy)
        self.page.reload()
        other = self.context.new_page()
        self.addCleanup(other.close)
        other.add_init_script("window.addEventListener('storage', event => event.stopImmediatePropagation())")
        other.route(self.base_url + '/**', self.route)
        other.goto(self.base_url)
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.page.locator('#start').click()
        self.page.wait_for_function('!document.querySelector("#recall").disabled')
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '我们研究起源。')
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#start").disabled')
        self.assertEqual(self.page.locator('#vocabulary-count').inner_text(), '3')
        other.select_option('#hsk-threshold', '7')
        stored = other.evaluate('JSON.parse(localStorage.getItem("chinese-listening-vocabulary-v1"))')
        self.assertEqual(stored, legacy)
        other.locator('#open-vocabulary').click()
        other.wait_for_function('document.querySelector("#vocabulary-count").textContent === "3"')
        self.assertEqual(stored['entries'][0]['translation'], 'An older sentence.')
        self.assertEqual(self.errors, [])

    def test_enter_dismisses_and_space_transcribes_from_the_word_list(self):
        self.page.keyboard.press('Space')
        self.wait_commands(1)
        self.send_result(0, '我们研究起源。')
        self.page.wait_for_selector('[aria-label="Dismiss 研究"]')
        self.page.get_by_role('button', name='Dismiss 研究', exact=True).focus()
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate('document.activeElement.getAttribute("aria-label")'), 'Dismiss 起源')
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'word-list')
        self.page.keyboard.press('Space')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.commands), 2)
        self.assertEqual(self.page.locator('.word-card').count(), 0)
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
