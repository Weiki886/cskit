import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cskit.errors import CskitError, CskitRolloutError, CskitConfigError, CskitDataError


class TestErrors(unittest.TestCase):
    def test_cskit_error_is_base(self):
        self.assertTrue(issubclass(CskitRolloutError, CskitError))
        self.assertTrue(issubclass(CskitConfigError, CskitError))
        self.assertTrue(issubclass(CskitDataError, CskitError))

    def test_cskit_error_is_runtime_error(self):
        self.assertTrue(issubclass(CskitError, RuntimeError))

    def test_rollout_error_has_message(self):
        e = CskitRolloutError("rollout not found")
        self.assertEqual(str(e), "rollout not found")

    def test_config_error_has_message(self):
        e = CskitConfigError("bad config")
        self.assertEqual(str(e), "bad config")

    def test_data_error_has_message(self):
        e = CskitDataError("data corrupted")
        self.assertEqual(str(e), "data corrupted")


if __name__ == "__main__":
    unittest.main()
