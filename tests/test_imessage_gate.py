"""The 'Hey Warden' / 'End Warden' gate of the iMessage bot (front/imessage.py decide())."""
import unittest

from front import imessage

CHAT = "iMessage;-;+10000000000"


class DecideTests(unittest.TestCase):
    def setUp(self):
        self.open = {}

    def decide(self, text, now=1000.0, chat=CHAT):
        return imessage.decide(text, chat, self.open, now)

    def test_silent_until_activated(self):
        for text in ("hello", "send 0.001 to akul.eth", "0x" + "ab" * 20, "what's up", "warden"):
            self.assertEqual(self.decide(text), ("ignore", None), text)
        self.assertEqual(self.open, {})

    def test_hey_warden_activates_and_greets(self):
        for text in ("Hey Warden", "hey warden!", "  HEY, WARDEN.", "Hey Warden,"):
            self.open.clear()
            self.assertEqual(self.decide(text), ("greet", None), text)
            self.assertIn(CHAT, self.open)

    def test_activation_with_a_request_handles_the_rest(self):
        self.assertEqual(self.decide("Hey Warden send 0.001 to akul.eth"),
                         ("handle", "send 0.001 to akul.eth"))

    def test_messages_after_activation_are_handled(self):
        self.decide("Hey Warden", now=1000)
        self.assertEqual(self.decide("vault.eth", now=1010), ("handle", "vault.eth"))

    def test_end_warden_closes_the_chat(self):
        self.decide("Hey Warden", now=1000)
        self.assertEqual(self.decide("End Warden", now=1010), ("end", None))
        self.assertEqual(self.decide("vault.eth", now=1020), ("ignore", None))

    def test_end_warden_when_not_active_stays_silent(self):
        self.assertEqual(self.decide("end warden"), ("ignore", None))

    def test_chat_goes_quiet_after_idle_timeout(self):
        self.decide("Hey Warden", now=1000)
        later = 1000 + imessage.CHAT_IDLE_SECONDS + 1
        self.assertEqual(self.decide("vault.eth", now=later), ("ignore", None))
        self.assertEqual(self.decide("Hey Warden", now=later + 1), ("greet", None))

    def test_activation_is_per_chat(self):
        self.decide("Hey Warden", chat="chat-a")
        self.assertEqual(self.decide("vault.eth", chat="chat-b"), ("ignore", None))
        self.assertEqual(self.decide("vault.eth", chat="chat-a"), ("handle", "vault.eth"))

    def test_heywarden_inside_a_sentence_does_not_activate(self):
        self.assertEqual(self.decide("I told him hey warden yesterday"), ("ignore", None))


if __name__ == "__main__":
    unittest.main()
