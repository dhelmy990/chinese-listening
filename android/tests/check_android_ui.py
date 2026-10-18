"""Android-specific UI checks using the shared browser fixture."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'whisper-live'))
from test_ui import InterfaceTests


class AndroidInterfaceTests(InterfaceTests):
    def test_background_cancels_a_pending_microphone_start(self):
        self.finish_session()
        self.page.wait_for_function('!sessionOpen')
        self.page.evaluate('''() => {
            const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = () => new Promise(resolve => {
                window.finishPermission = async () => {
                    window.lateStream = await original({audio: true});
                    resolve(window.lateStream);
                };
            });
        }''')
        self.page.locator('#start').click()
        self.page.wait_for_function('typeof finishPermission === "function"')
        self.page.evaluate('setAndroidForeground(false)')
        self.page.evaluate('finishPermission()')
        self.page.wait_for_function('lateStream.getTracks().every(track => track.readyState === "ended")')
        self.assertFalse(self.page.evaluate('active || sessionOpen'))
        self.assertIsNone(self.page.evaluate('context'))

    def test_android_model_is_fixed_after_stop_and_save(self):
        self.page.route('**/status', lambda route: route.fulfill(json=dict(
            ready=True, model='turbo', compute_type='int8', models=['turbo'], fixed_model=True,
            compute_types=['int8'], loading=False, busy=False, error=None, device='CPU')))
        self.page.evaluate('checkModel()')
        self.assertEqual(self.page.locator('#model-select option').all_text_contents(), ['Turbo'])
        self.finish_session()
        self.page.wait_for_function('!sessionOpen')
        self.assertTrue(self.page.locator('#model-select').is_disabled())
        self.assertTrue(self.page.locator('#compute-select').is_disabled())

    def test_licenses_do_not_navigate_or_discard_live_session(self):
        self.page.route('**/status', lambda route: route.fulfill(json=dict(
            ready=True, model='turbo', compute_type='int8', fixed_model=True,
            compute_types=['int8'], loading=False, busy=False, error=None, device='CPU')))
        self.page.route('**/data/android-notices.txt', lambda route: route.fulfill(body='Model attribution'))
        self.page.evaluate('checkModel()')
        self.page.locator('#android-licenses').click()
        self.page.wait_for_function('document.querySelector("dialog[open] pre")?.textContent === "Model attribution"')
        self.assertEqual(self.page.url, self.base_url + '/')
        self.assertTrue(self.page.evaluate('active && sessionOpen'))
        self.page.locator('dialog[open] button').click()
        self.assertEqual(self.page.locator('dialog[open]').count(), 0)


if __name__ == '__main__':
    suite = unittest.TestSuite(AndroidInterfaceTests(name) for name in (
        'test_background_cancels_a_pending_microphone_start',
        'test_android_model_is_fixed_after_stop_and_save',
        'test_licenses_do_not_navigate_or_discard_live_session'))
    result = unittest.TextTestRunner().run(suite)
    sys.exit(not result.wasSuccessful())
