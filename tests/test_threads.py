from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cskit.errors import CskitDataError


def write_index(path, records):
    """Write a session_index.jsonl-style append-only file."""
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )
    return path


class TestOpenDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_raises(self):
        from cskit.threads import open_database
        missing = self.tmp / "nope.sqlite"
        with self.assertRaises(CskitDataError) as ctx:
            open_database(missing)
        self.assertIn("找不到", str(ctx.exception))

    def test_opens_existing_db_read_only(self):
        from cskit.threads import open_database
        db = self.tmp / "test.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT)")
        conn.execute("INSERT INTO threads VALUES ('t1')")
        conn.commit()
        conn.close()

        opened = open_database(db)
        row = opened.execute("SELECT id FROM threads").fetchone()
        self.assertEqual(row["id"], "t1")
        # Writing should fail — read-only mode
        with self.assertRaises(sqlite3.Error):
            opened.execute("INSERT INTO threads VALUES ('t2')")
        opened.close()


class TestLoadSessionTitles(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.index = self.tmp / "session_index.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty_dict(self):
        from cskit.threads import load_session_titles
        self.assertEqual(load_session_titles(self.tmp / "absent.jsonl"), {})

    def test_latest_updated_at_wins(self):
        from cskit.threads import load_session_titles
        write_index(self.index, [
            {"id": "t1", "thread_name": "旧名字", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": "t1", "thread_name": "新名字", "updated_at": "2026-06-01T00:00:00Z"},
        ])
        self.assertEqual(load_session_titles(self.index), {"t1": "新名字"})

    def test_later_line_wins_when_updated_at_absent(self):
        from cskit.threads import load_session_titles
        write_index(self.index, [
            {"id": "t1", "thread_name": "first"},
            {"id": "t1", "thread_name": "second"},
        ])
        self.assertEqual(load_session_titles(self.index), {"t1": "second"})

    def test_earlier_updated_at_does_not_override_later(self):
        from cskit.threads import load_session_titles
        write_index(self.index, [
            {"id": "t1", "thread_name": "keep", "updated_at": "2026-06-01T00:00:00Z"},
            {"id": "t1", "thread_name": "stale", "updated_at": "2026-01-01T00:00:00Z"},
        ])
        self.assertEqual(load_session_titles(self.index), {"t1": "keep"})

    def test_partial_final_line_is_skipped_not_fatal(self):
        from cskit.threads import load_session_titles
        self.index.write_text(
            json.dumps({"id": "t1", "thread_name": "ok"}) + "\n{\"id\": \"t2\", \"thre",
            encoding="utf-8",
        )
        self.assertEqual(load_session_titles(self.index), {"t1": "ok"})

    def test_blank_and_untyped_names_are_ignored(self):
        from cskit.threads import load_session_titles
        write_index(self.index, [
            {"id": "t1", "thread_name": "   "},
            {"id": "t2", "thread_name": 123},
            {"id": "t3"},
            {"thread_name": "no id"},
            {"id": "t4", "thread_name": "  trimmed  "},
        ])
        self.assertEqual(load_session_titles(self.index), {"t4": "trimmed"})


class TestLoadSidebarProjectNames(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.state = self.tmp / "state.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty_dict(self):
        from cskit.threads import load_sidebar_project_names
        self.assertEqual(load_sidebar_project_names(self.tmp / "absent.json"), {})

    def test_maps_thread_to_project_name(self):
        from cskit.threads import load_sidebar_project_names
        self.state.write_text(json.dumps({
            "thread-project-assignments": {
                "t1": {"projectId": "p1"},
                "t2": {"projectId": "p2"},
            },
            "local-projects": {
                "p1": {"name": "OpenSourceProjects"},
                "p2": {"name": "  知识库  "},
            },
        }), encoding="utf-8")
        self.assertEqual(
            load_sidebar_project_names(self.state),
            {"t1": "OpenSourceProjects", "t2": "知识库"},
        )

    def test_unknown_project_id_is_skipped(self):
        from cskit.threads import load_sidebar_project_names
        self.state.write_text(json.dumps({
            "thread-project-assignments": {"t1": {"projectId": "ghost"}},
            "local-projects": {"p1": {"name": "Real"}},
        }), encoding="utf-8")
        self.assertEqual(load_sidebar_project_names(self.state), {})

    def test_malformed_json_returns_empty_dict(self):
        from cskit.threads import load_sidebar_project_names
        self.state.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_sidebar_project_names(self.state), {})

    def test_missing_required_keys_returns_empty_dict(self):
        from cskit.threads import load_sidebar_project_names
        self.state.write_text(json.dumps({"other": 1}), encoding="utf-8")
        self.assertEqual(load_sidebar_project_names(self.state), {})


class TestListThreads(unittest.TestCase):
    """list_threads is the union of exportcode's list_active_threads and
    clonecode's list_threads, parameterized by required_columns."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.db = self.tmp / "state.sqlite"
        conn = sqlite3.connect(str(self.db))
        conn.execute("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                title TEXT,
                rollout_path TEXT,
                archived INTEGER DEFAULT 0,
                thread_source TEXT DEFAULT 'user',
                cwd TEXT DEFAULT '',
                model_provider TEXT DEFAULT '',
                model TEXT DEFAULT '',
                history_mode TEXT DEFAULT '',
                updated_at_ms INTEGER DEFAULT 0,
                name TEXT DEFAULT ''
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_requires_columns_by_default(self):
        from cskit.threads import list_threads
        # Drop a column that's in the union set
        conn = sqlite3.connect(str(self.db))
        conn.execute("ALTER TABLE threads DROP COLUMN model_provider")
        conn.commit()
        conn.close()
        with self.assertRaises(CskitDataError) as ctx:
            list_threads(self.db)
        self.assertIn("model_provider", str(ctx.exception))

    def test_required_columns_parameter_can_override(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        conn.execute("ALTER TABLE threads DROP COLUMN model_provider")
        conn.commit()
        conn.close()
        # With a smaller required set, it should pass
        rows = list_threads(
            self.db,
            required_columns={"id", "rollout_path", "title", "archived", "thread_source"},
        )
        self.assertEqual(rows, [])

    def test_returns_thread_records_with_display_name_fallback(self):
        from cskit.threads import list_threads, ThreadRecord
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path, name) VALUES (?, ?, ?, ?)",
            ("t1", "fallback title", "/r/1.jsonl", "My Name"),
        )
        conn.commit()
        conn.close()
        rows = list_threads(self.db)
        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0], ThreadRecord)
        # name > title, so display_name should be "My Name"
        self.assertEqual(rows[0].display_name, "My Name")

    def test_display_name_fallback_chain(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path) VALUES (?, ?, ?)",
            ("t2", "仅标题", "/r/2.jsonl"),
        )
        conn.commit()
        conn.close()
        rows = list_threads(self.db)
        self.assertEqual(rows[0].display_name, "仅标题")

    def test_display_name_falls_back_to_unnamed(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO threads (id, rollout_path, title) VALUES (?, ?, ?)",
            ("t3", "/r/3.jsonl", ""),
        )
        conn.commit()
        conn.close()
        rows = list_threads(self.db)
        self.assertEqual(rows[0].display_name, "未命名对话")

    def test_sidebar_only_filters_threads_not_in_titles(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path, name) VALUES (?, ?, ?, ?)",
            ("t1", "in sidebar", "/r/1.jsonl", "Visible"),
        )
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path, name) VALUES (?, ?, ?, ?)",
            ("t2", "no name no index", "/r/2.jsonl", ""),
        )
        conn.commit()
        conn.close()
        rows = list_threads(self.db, sidebar_only=True, session_titles={"t1": "Visible"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, "t1")

    def test_max_per_project_limits(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        for i in range(5):
            conn.execute(
                "INSERT INTO threads (id, title, rollout_path) VALUES (?, ?, ?)",
                (f"t{i}", f"Thread {i}", f"/r/{i}.jsonl"),
            )
        conn.commit()
        conn.close()
        rows = list_threads(self.db, max_per_project=2)
        self.assertEqual(len(rows), 2)

    def test_archived_threads_excluded(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path) VALUES (?, ?, ?)",
            ("active", "Active", "/r/a.jsonl"),
        )
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path, archived) VALUES (?, ?, ?, ?)",
            ("arch", "Archived", "/r/arch.jsonl", 1),
        )
        conn.commit()
        conn.close()
        rows = list_threads(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, "active")

    def test_non_user_threads_excluded(self):
        from cskit.threads import list_threads
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path, thread_source) VALUES (?, ?, ?, ?)",
            ("user", "User", "/r/u.jsonl", "user"),
        )
        conn.execute(
            "INSERT INTO threads (id, title, rollout_path, thread_source) VALUES (?, ?, ?, ?)",
            ("guard", "Guard", "/r/g.jsonl", "guardian"),
        )
        conn.commit()
        conn.close()
        rows = list_threads(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, "user")


if __name__ == "__main__":
    unittest.main()
