"""iMessage send() retries so a busy or closed Messages app does not drop a reply."""
import types
import unittest
from unittest import mock

from front import imessage


def run_send(osascript_codes):
    codes = list(osascript_codes)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "osascript":
            code = codes.pop(0)
            return types.SimpleNamespace(returncode=code, stderr="boom" if code else "")
        return types.SimpleNamespace(returncode=0, stderr="")

    with mock.patch.object(imessage.subprocess, "run", side_effect=fake_run), \
            mock.patch.object(imessage.time, "sleep"):
        ok = imessage.send("hi", "chat-guid", "+10000000000")
    return ok, calls


class SendRetryTests(unittest.TestCase):
    def test_first_try_succeeds(self):
        self.assertEqual(run_send([0]), (True, ["osascript"]))

    def test_falls_back_to_the_handle_when_the_chat_id_fails(self):
        self.assertEqual(run_send([1, 0]), (True, ["osascript", "osascript"]))

    def test_reopens_messages_and_retries(self):
        ok, calls = run_send([1, 1, 0])
        self.assertTrue(ok)
        self.assertEqual(calls, ["osascript", "osascript", "open", "osascript"])

    def test_gives_up_after_three_attempts(self):
        ok, calls = run_send([1] * 6)
        self.assertFalse(ok)
        self.assertEqual((calls.count("osascript"), calls.count("open")), (6, 2))

    def test_no_targets_does_not_loop_forever(self):
        with mock.patch.object(imessage.subprocess, "run") as run, mock.patch.object(imessage.time, "sleep"):
            self.assertFalse(imessage.send("hi", None, None))
        self.assertEqual([c.args[0][0] for c in run.call_args_list], ["open", "open"])


if __name__ == "__main__":
    unittest.main()
