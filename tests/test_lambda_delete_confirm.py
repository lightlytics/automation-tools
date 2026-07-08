import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.common.boto_common import confirm_deletion


class TestConfirmDeletion(unittest.TestCase):
    def test_typed_delete_on_tty_confirms(self):
        self.assertTrue(confirm_deletion(5, 2, lambda: True, lambda _p: "delete"))

    def test_wrong_word_aborts(self):
        self.assertFalse(confirm_deletion(5, 2, lambda: True, lambda _p: "yes"))

    def test_non_tty_refuses_without_prompting(self):
        def _input(_p):
            raise AssertionError("input must not be called on a non-tty")
        self.assertFalse(confirm_deletion(5, 2, lambda: False, _input))

    def test_eof_aborts(self):
        def _input(_p):
            raise EOFError()
        self.assertFalse(confirm_deletion(5, 2, lambda: True, _input))

    def test_keyboard_interrupt_aborts(self):
        def _input(_p):
            raise KeyboardInterrupt()
        self.assertFalse(confirm_deletion(5, 2, lambda: True, _input))


if __name__ == "__main__":
    unittest.main()
