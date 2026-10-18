"""Browser/native bridge contract and session durability checks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'whisper-live'))
from test_ui import InterfaceTests


class DeviceAudioTests(InterfaceTests):
    def install_bridge(self):
        self.assertTrue(self.page.evaluate("typeof initDeviceAudio === 'function'"),
                        'The native capture bridge must be connected to the session UI')
        self.page.evaluate('''() => {
            window.nativeState = {supported:true,running:false,requesting:false,error:null,clips:[]};
            window.acked = [];
            window.AndroidAudio = {
                state: () => JSON.stringify(nativeState),
                requestStart: () => { nativeState.running = true; },
                stop: () => { nativeState.running = nativeState.requesting = false; },
                capture: seconds => { window.capturedSeconds = seconds; },
                readClip: () => btoa(String.fromCharCode(...new Uint8Array(32000).fill(1))),
                ackClips: ids => { acked.push(...JSON.parse(ids)); nativeState.clips = nativeState.clips.filter(c => !acked.includes(c.id)); },
            };
            initDeviceAudio();
        }''')

    def add_native_clip(self, name='native-one'):
        self.page.evaluate('''id => nativeState.clips.push({id,seconds:1,createdAt:new Date().toISOString()})''', name)
        self.page.evaluate('deviceAudio.poll()')

    def test_playback_appends_to_current_session_and_deletes_only_after_save(self):
        self.install_bridge()
        self.page.locator('#device-audio').click()
        self.page.wait_for_function("audioInput === 'playback' && stream === null")
        self.assertEqual(len(self.connections), 1, 'Input switch must keep the current session connection')
        self.add_native_clip()
        self.wait_commands(1)
        self.send_result(0)
        self.assertEqual(self.page.evaluate('acked'), [])
        self.finish_session()
        self.page.wait_for_function('!sessionOpen')
        self.assertEqual(self.page.evaluate('acked'), ['native-one'])
        self.assertEqual(len(self.saved_requests), 1)

    def test_playback_session_survives_background_but_import_waits_for_foreground(self):
        self.install_bridge()
        self.page.locator('#device-audio').click()
        self.page.wait_for_function("audioInput === 'playback'")
        self.page.evaluate('setAndroidForeground(false)')
        self.add_native_clip()
        self.assertTrue(self.page.evaluate('sessionOpen && active'))
        self.assertEqual(self.commands, [])
        self.page.evaluate('setAndroidForeground(true); deviceAudio.poll()')
        self.wait_commands(1)
        self.assertTrue(self.page.locator('#recall').is_enabled())

    def test_recovered_capture_starts_new_session_without_opening_microphone(self):
        self.finish_session()
        self.page.wait_for_function('!sessionOpen')
        self.install_bridge()
        self.add_native_clip()
        self.assertEqual(self.commands, [], 'Recovery must wait for a user action')
        self.page.locator('#review-captures').click()
        self.wait_commands(1)
        self.assertTrue(self.page.evaluate('sessionOpen && stream === null'))
        self.assertEqual(len(self.connections), 2)

    def test_failed_session_save_keeps_audio_until_retry_succeeds(self):
        self.install_bridge()
        self.page.locator('#device-audio').click()
        self.page.wait_for_function("audioInput === 'playback'")
        self.add_native_clip()
        self.wait_commands(1)
        self.send_result(0)
        self.save_failures = 1
        self.finish_session()
        self.page.wait_for_function('!document.querySelector("#retry-save").hidden')
        self.assertEqual(self.page.evaluate('acked'), [])
        self.page.locator('#retry-save').click()
        self.page.wait_for_function('!sessionOpen')
        self.assertEqual(self.page.evaluate('acked'), ['native-one'])

    def test_denied_capture_leaves_session_saveable_and_retryable(self):
        self.install_bridge()
        self.page.evaluate("AndroidAudio.requestStart = () => { nativeState.error = 'Capture permission denied'; }")
        self.page.locator('#device-audio').click()
        self.page.wait_for_function("document.querySelector('#device-status').textContent.includes('denied')")
        self.assertFalse(self.page.locator('#device-audio').is_disabled())
        self.assertTrue(self.page.evaluate('sessionOpen'))
        self.finish_session()
        self.page.wait_for_function('!sessionOpen')

    def test_stop_waits_for_final_native_disk_write_before_saving(self):
        self.install_bridge()
        self.page.locator('#device-audio').click()
        self.page.wait_for_function("audioInput === 'playback'")
        self.page.evaluate('nativeState.pendingSaves = 1')
        self.page.locator('#start').click()
        self.page.wait_for_function('stoppingInput')
        self.assertFalse(self.stopped)
        self.assertEqual(self.saved_requests, [])
        self.page.evaluate("nativeState.clips.push({id:'last-clip',seconds:1,createdAt:new Date().toISOString()}); nativeState.pendingSaves = 0")
        self.wait_commands(1)
        self.send_result(0)
        self.page.wait_for_function('!stoppingInput')
        self.connections[-1].send('{"done":true}')
        self.connections[-1].close()
        self.page.wait_for_function('!sessionOpen')
        self.assertEqual(self.page.evaluate('acked'), ['last-clip'])

    def test_input_switch_flushes_a_just_released_microphone_clip(self):
        self.install_bridge()
        self.page.evaluate("parseLastNSeconds(1); document.querySelector('#device-audio').click()")
        self.page.wait_for_function("audioInput === 'playback' && stream === null")
        self.wait_commands(1)
        self.assertEqual(self.commands[0]['id'], 0)
        self.send_result(0)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    names = [name for name in DeviceAudioTests.__dict__ if name.startswith('test_')]
    result = unittest.TextTestRunner().run(unittest.TestSuite(DeviceAudioTests(name) for name in names))
    sys.exit(not result.wasSuccessful())
