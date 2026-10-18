"""Phone layout regression checks against the real shared page."""
import unittest
from test_ui import InterfaceTests


class PhoneTests(InterfaceTests):
    def test_phone_transcript_and_english_fit_without_sideways_scrolling(self):
        for width, height in ((360, 740), (390, 844), (740, 360)):
            self.page.set_viewport_size(dict(width=width, height=height))
            expected = len(self.commands) + 1
            self.page.evaluate('parseLastNSeconds(1)')
            self.wait_commands(expected)
            clip_id = self.commands[-1]['id']
            self.send_result(clip_id, '我喜欢学习中文。')
            bounds = self.page.locator(f'[data-clip-id="{clip_id}"]').evaluate('''row => {
                const chinese = row.querySelector('.pill').getBoundingClientRect();
                const english = row.querySelector('.translation').getBoundingClientRect();
                return {left: english.left, right: english.right, englishTop: english.top,
                    chineseBottom: chinese.bottom, viewport: innerWidth,
                    pageWidth: document.documentElement.scrollWidth};
            }''')
            self.assertLessEqual(bounds['pageWidth'], width)
            self.assertGreaterEqual(bounds['left'], 0)
            self.assertLessEqual(bounds['right'], width)
            self.assertGreaterEqual(bounds['englishTop'], bounds['chineseBottom'])

    def test_phone_words_and_settings_are_accessible(self):
        self.page.set_viewport_size(dict(width=360, height=740))
        self.assertEqual(self.page.locator('#words-tab').count(), 1)
        self.page.locator('#words-tab').click()
        self.assertTrue(self.page.locator('.middle-panel').is_visible())
        self.assertFalse(self.page.locator('#timeline').is_visible())
        self.page.locator('#listen-tab').click()
        self.assertTrue(self.page.locator('#timeline').is_visible())
        self.page.locator('#settings-toggle').click()
        self.assertTrue(self.page.locator('#hsk-threshold').is_visible())
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 360)

    def test_long_phone_result_keeps_the_chinese_start_in_view(self):
        self.page.set_viewport_size(dict(width=390, height=844))
        self.page.evaluate('parseLastNSeconds(1)')
        self.wait_commands(1)
        self.send_result(0, '我们一起学习中文，了解世界。' * 8)
        top = self.pill(0).bounding_box()['y']
        heading = self.page.locator('.panel-headings').bounding_box()
        self.assertGreaterEqual(top, heading['y'] + heading['height'])


if __name__ == '__main__':
    names = [name for name in PhoneTests.__dict__ if name.startswith('test_')]
    result = unittest.TextTestRunner().run(unittest.TestSuite(PhoneTests(name) for name in names))
    raise SystemExit(not result.wasSuccessful())
