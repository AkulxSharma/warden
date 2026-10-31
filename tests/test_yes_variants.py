"""YES and NO are recognised however they are typed."""
import unittest

from front.parse import parse


class YesNoTests(unittest.TestCase):
    def test_yes_in_any_case_spacing_and_punctuation(self):
        for text in ("yes", "YES", "Yes", "yEs", "Yes!", "yes.", "  yes  ", "YES\n", "\tyes\n", "Yes!!", "yes,",
                     "y", "Y", "yep", "Yeah", "confirm", "CONFIRM", "yes  send", "Send It"):
            self.assertEqual(parse(text).kind, "yes", repr(text))

    def test_no_in_any_case(self):
        for text in ("no", "NO", "No!", "cancel", "CANCEL", "n", "Never mind", " stop "):
            self.assertEqual(parse(text).kind, "no", repr(text))

    def test_other_words_are_not_a_confirmation(self):
        for text in ("yesterday", "yes please do it", "maybe", "hello", "eyes"):
            self.assertNotIn(parse(text).kind, ("yes", "no"), repr(text))


if __name__ == "__main__":
    unittest.main()
