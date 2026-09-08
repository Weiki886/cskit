from __future__ import annotations

import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cskit.errors import CskitConfigError
from cskit.fix import FixState, verify_state


def _state(**overrides):
    defaults = dict(
        provider="custom",
        model="ark-code-latest",
        config_path=pathlib.Path("/tmp/config.toml"),
        db_path=pathlib.Path("/tmp/state.sqlite"),
    )
    defaults.update(overrides)
    return FixState(**defaults)


class TestFixState(unittest.TestCase):
    def test_carries_provider_and_model(self):
        state = _state()
        self.assertEqual(state.provider, "custom")
        self.assertEqual(state.model, "ark-code-latest")

    def test_verify_accepts_complete_state(self):
        self.assertIsNone(verify_state(_state()))

    def test_verify_rejects_empty_provider(self):
        with self.assertRaises(CskitConfigError) as ctx:
            verify_state(_state(provider=""))
        self.assertIn("model_provider", str(ctx.exception))

    def test_verify_rejects_empty_model(self):
        with self.assertRaises(CskitConfigError) as ctx:
            verify_state(_state(model=""))
        message = str(ctx.exception)
        # Must name `model`, not be the model_provider message with a substring hit.
        self.assertIn("model", message)
        self.assertNotIn("model_provider", message)


if __name__ == "__main__":
    unittest.main()
