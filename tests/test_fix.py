from __future__ import annotations

import contextlib
import io
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cskit.errors import CskitConfigError
from cskit.fix import FixState, backup_config, build_parser, format_preview, format_result, load_fix_state, run, sync_threads, verify_state


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


class TestSyncThreads(unittest.TestCase):
    def _db(self, rows):
        d = pathlib.Path(tempfile.mkdtemp())
        db = d / "state.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, model_provider TEXT NOT NULL, model TEXT)"
        )
        for i, (mp, m) in enumerate(rows):
            conn.execute("INSERT INTO threads (id, model_provider, model) VALUES (?, ?, ?)", (f"t{i}", mp, m))
        conn.commit()
        conn.close()
        return db

    def test_updates_all_rows(self):
        db = self._db([("old", "old"), ("other", "other")])
        affected = sync_threads(db, "new", "new")
        self.assertEqual(affected, 2)
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT model_provider, model FROM threads").fetchall()
        conn.close()
        self.assertEqual(rows, [("new", "new"), ("new", "new")])

    def test_uses_parameterized_query(self):
        db = self._db([("old", "old")])
        sync_threads(db, "custom", "o'brien-model")
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT model_provider, model FROM threads").fetchone()
        conn.close()
        self.assertEqual(row, ("custom", "o'brien-model"))

    def test_failed_write_leaves_every_row_untouched(self):
        """The write is all-or-nothing: one rejected row reverts the whole batch.

        A trigger aborts on the third row, so the update fails after the first
        two were already rewritten. Note this test does not discriminate the
        explicit BEGIN IMMEDIATE: SQLite reverts a single failed statement on its
        own, verified separately. It guards the observable contract, so it would
        catch a future refactor that splits the write into several statements.
        """
        db = self._db([("old", "old"), ("old", "old"), ("old", "old")])
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TRIGGER reject_one BEFORE UPDATE ON threads "
            "WHEN NEW.id = 't2' BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )
        conn.commit()
        conn.close()

        with self.assertRaises(sqlite3.Error):
            sync_threads(db, "new", "new")

        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT model_provider, model FROM threads").fetchall()
        conn.close()
        self.assertEqual(rows, [("old", "old"), ("old", "old"), ("old", "old")])

    def test_missing_threads_table_raises(self):
        d = pathlib.Path(tempfile.mkdtemp())
        db = d / "empty.db"
        sqlite3.connect(str(db)).close()
        with self.assertRaises(sqlite3.Error):
            sync_threads(db, "new", "new")

    def test_empty_db_returns_zero(self):
        db = self._db([])
        affected = sync_threads(db, "new", "new")
        self.assertEqual(affected, 0)


class TestFormatPreview(unittest.TestCase):
    def setUp(self):
        self.state = FixState(provider="custom", model="ark-code-latest",
                               config_path=pathlib.Path("/tmp/c.toml"),
                               db_path=pathlib.Path("/tmp/s.db"))

    def test_contains_provider_and_model(self):
        text = format_preview(self.state, 42, dry_run=True)
        self.assertIn("custom", text)
        self.assertIn("ark-code-latest", text)

    def test_contains_thread_count(self):
        text = format_preview(self.state, 42, dry_run=True)
        self.assertIn("42", text)

    def test_dry_run_banner(self):
        text = format_preview(self.state, 42, dry_run=True)
        self.assertIn("预览", text)

    def test_live_preview_has_no_completion_banner(self):
        """Before writing, nothing may claim the write already happened."""
        text = format_preview(self.state, 42, dry_run=False)
        self.assertNotIn("✓", text)

    def test_result_line_reports_what_was_written(self):
        text = format_result(self.state, 42)
        self.assertIn("✓", text)
        self.assertIn("42", text)
        self.assertIn("custom", text)
        self.assertIn("ark-code-latest", text)

    def test_no_token_leak(self):
        """Even if the provider or model were a token — they aren't, but the
        implementation must not echo the entire config.toml or any secret-likely
        value referenced by name."""
        text = format_preview(self.state, 42, dry_run=True)
        self.assertNotIn("experimental" + "_bearer_" + "token", text)
        self.assertNotIn("api_key", text)
        self.assertNotIn("base_url", text)


class TestRunIsolation(unittest.TestCase):
    """`fix` is the only writing subcommand, so the suite must never be able to
    touch the developer's own Codex data. This locks the two escape routes."""

    def test_default_paths_point_at_the_real_codex_home(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.codex_home.expanduser(), pathlib.Path.home() / ".codex")
        self.assertTrue(str(args.backup_dir).startswith("~/.codex"))

    def test_every_run_invocation_in_this_file_is_sandboxed(self):
        """Every real invocation must pass --codex-home, and pass either
        --no-backup or a --backup-dir, or it would write to the real ~/.codex."""
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        calls = re.findall(r"run\(\[\s*([\"'].*?)\]\)", source, re.DOTALL)
        self.assertGreater(len(calls), 0)
        for call in calls:
            self.assertIn("--codex-home", call)
            if "--dry-run" not in call:
                self.assertTrue(
                    "--no-backup" in call or "--backup-dir" in call,
                    f"未沙箱化的写入调用：{call.strip()}",
                )


class TestRun(unittest.TestCase):
    def _setup(self, config_text, rows=None, backup_dir=None):
        d = pathlib.Path(tempfile.mkdtemp())
        config = d / "config.toml"
        config.write_text(config_text, encoding="utf-8")
        db = d / "state_5.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, model_provider TEXT NOT NULL, model TEXT)")
        if rows:
            for i, (mp, m) in enumerate(rows):
                conn.execute("INSERT INTO threads (id, model_provider, model) VALUES (?, ?, ?)", (f"t{i}", mp, m))
        conn.commit()
        conn.close()
        if backup_dir is not None:
            return config, db, backup_dir
        return config, db

    def test_dry_run_does_not_mutate(self):
        config, db = self._setup(
            'model_provider = "custom"\nmodel = "gpt-4"\n\n[model_providers.custom]\nname = "t"\n',
            [("old", "old")],
        )
        code = run(["--codex-home", str(config.parent), "--dry-run", "--no-backup"])
        self.assertEqual(code, 0)
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT model_provider, model FROM threads").fetchone()
        conn.close()
        self.assertEqual(row, ("old", "old"))

    def test_yes_skips_confirmation(self):
        config, db, bd = self._setup(
            'model_provider = "custom"\nmodel = "gpt-4"\n\n[model_providers.custom]\nname = "t"\n',
            [("old", "old")],
            backup_dir=pathlib.Path(tempfile.mkdtemp()),
        )
        code = run(["--codex-home", str(config.parent), "--backup-dir", str(bd), "--yes"])
        self.assertEqual(code, 0)
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT model_provider, model FROM threads").fetchone()
        conn.close()
        self.assertEqual(row, ("custom", "gpt-4"))

    def test_errors_on_missing_config(self):
        with self.assertRaises(CskitConfigError):
            run(["--codex-home", "/nonexistent", "--no-backup"])

    def test_missing_config_exits_one_through_the_cli(self):
        from cskit.__main__ import main

        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            self.assertEqual(main(["fix", "--codex-home", "/nonexistent"]), 1)

    def test_creates_a_backup_before_writing(self):
        config, _ = self._setup(
            'model_provider = "custom"\nmodel = "gpt-4"\n\n[model_providers.custom]\nname = "t"\n',
            [("old", "old")],
        )
        backups = config.parent / "backups-out"
        code = run([
            "--codex-home", str(config.parent),
            "--backup-dir", str(backups),
            "--yes",
        ])
        self.assertEqual(code, 0)
        made = list(backups.glob("config.toml.*.bak"))
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].read_text(encoding="utf-8"), config.read_text(encoding="utf-8"))

    def test_dry_run_creates_no_backup(self):
        config, _ = self._setup(
            'model_provider = "custom"\nmodel = "gpt-4"\n\n[model_providers.custom]\nname = "t"\n',
            [("old", "old")],
        )
        backups = config.parent / "backups-out"
        run([
            "--codex-home", str(config.parent),
            "--backup-dir", str(backups),
            "--dry-run",
        ])
        self.assertFalse(backups.exists())

    def test_errors_on_missing_provider_section(self):
        config, _ = self._setup(
            'model_provider = "custom"\nmodel = "gpt-4"\n',  # no [model_providers.custom]
        )
        with self.assertRaises(CskitConfigError) as ctx:
            run(["--codex-home", str(config.parent), "--no-backup"])
        self.assertIn("model_providers.custom", str(ctx.exception))

    def test_build_parser_accepts_known_flags(self):
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "--yes"])
        self.assertTrue(args.dry_run)
        self.assertTrue(args.yes)


if __name__ == "__main__":
    unittest.main()
