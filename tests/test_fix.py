from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cskit.errors import CskitConfigError
from cskit.fix import FixState, backup_config, load_fix_state, verify_state


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


class TestLoadFixState(unittest.TestCase):
    def _config(self, text):
        path = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_top_level_provider_and_model(self):
        path = self._config(
            'model_provider = "custom"\n'
            'model = "ark-code-latest"\n'
            "\n"
            "[model_providers.custom]\n"
            'name = "ark"\n'
        )
        state = load_fix_state(path, db_path=pathlib.Path("/tmp/state.sqlite"))
        self.assertEqual(state.provider, "custom")
        self.assertEqual(state.model, "ark-code-latest")
        self.assertEqual(state.config_path, path)

    def test_section_scoped_key_does_not_win_over_top_level(self):
        """Regression: awk's `exit` took the first line match, ignoring scope."""
        path = self._config(
            "[model_providers.foo]\n"
            'model = "WRONG-from-section"\n'
            'model_provider = "WRONG-provider"\n'
        )
        with self.assertRaises(CskitConfigError):
            load_fix_state(path, db_path=pathlib.Path("/tmp/state.sqlite"))

    def test_rejects_missing_provider_section(self):
        """Plan A: never append a guessed provider template."""
        path = self._config(
            'model_provider = "custom"\nmodel = "ark-code-latest"\n'
        )
        with self.assertRaises(CskitConfigError) as ctx:
            load_fix_state(path, db_path=pathlib.Path("/tmp/state.sqlite"))
        self.assertIn("model_providers.custom", str(ctx.exception))

    def test_provider_section_may_carry_extra_whitespace(self):
        path = self._config(
            'model_provider = "custom"\n'
            'model = "ark-code-latest"\n'
            "\n"
            "  [model_providers.custom]  \n"
            'name = "ark"\n'
        )
        state = load_fix_state(path, db_path=pathlib.Path("/tmp/state.sqlite"))
        self.assertEqual(state.provider, "custom")

    def test_quoted_provider_section_header_is_accepted(self):
        path = self._config(
            'model_provider = "cc-switch-official"\n'
            'model = "gpt-5.6-sol"\n'
            "\n"
            '[model_providers."cc-switch-official"]\n'
            'name = "OpenAI"\n'
        )
        state = load_fix_state(path, db_path=pathlib.Path("/tmp/state.sqlite"))
        self.assertEqual(state.provider, "cc-switch-official")

    def test_missing_config_file_raises(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "absent.toml"
        with self.assertRaises(CskitConfigError):
            load_fix_state(path, db_path=pathlib.Path("/tmp/state.sqlite"))


class TestBackupConfig(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.config = self.home / "config.toml"
        self.config.write_text('model_provider = "custom"\n', encoding="utf-8")
        self.backup_dir = self.home / ".cskit-backups"

    def test_copies_content_verbatim(self):
        backup = backup_config(self.config, self.backup_dir)
        self.assertEqual(
            backup.read_text(encoding="utf-8"),
            self.config.read_text(encoding="utf-8"),
        )

    def test_backup_file_is_owner_read_write_only(self):
        """config.toml holds a bearer token, so the copy must not be world-readable."""
        backup = backup_config(self.config, self.backup_dir)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_backup_directory_is_owner_only(self):
        backup = backup_config(self.config, self.backup_dir)
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)

    def test_rejects_relative_backup_directory(self):
        with self.assertRaises(CskitConfigError):
            backup_config(self.config, pathlib.Path("relative-backups"))

    def test_rejects_directory_inside_a_git_worktree(self):
        """A backup containing a live token must never land where git can stage it."""
        (self.home / ".git").mkdir()
        with self.assertRaises(CskitConfigError) as ctx:
            backup_config(self.config, self.home / "backups")
        self.assertIn("git", str(ctx.exception).lower())

    def test_does_not_overwrite_an_earlier_backup(self):
        first = backup_config(self.config, self.backup_dir)
        self.config.write_text('model_provider = "changed"\n', encoding="utf-8")
        second = backup_config(self.config, self.backup_dir)
        self.assertNotEqual(first, second)
        self.assertIn("custom", first.read_text(encoding="utf-8"))
        self.assertIn("changed", second.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
