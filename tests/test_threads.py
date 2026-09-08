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


if __name__ == "__main__":
    unittest.main()
