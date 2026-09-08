from __future__ import annotations

import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cskit.errors import CskitDataError


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


if __name__ == "__main__":
    unittest.main()
