import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cskit.errors import CskitRolloutError
from cskit.rollout import (
    HistoryResolver,
    RolloutLineage,
    _iter_jsonl_prefix,
    iter_rollout_events,
)


def write_rollout(directory, thread_id, events, timestamp="2026-09-01T10-00-00"):
    path = pathlib.Path(directory) / f"rollout-{timestamp}-{thread_id}.jsonl"
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        encoding="utf-8",
    )
    return path


def meta(thread_id, history_base=None):
    payload = {"id": thread_id}
    if history_base is not None:
        payload["history_base"] = history_base
    return {"type": "session_meta", "timestamp": "2026-09-01T10:00:00.000Z", "payload": payload}


def msg(text, role="UserMessage"):
    return {
        "type": "event_msg",
        "timestamp": "2026-09-01T10:00:01.000Z",
        "payload": {
            "type": "item_completed",
            "item": {"type": role, "id": "x", "content": [{"type": "text", "text": text}]},
        },
    }


def meta_line(thread_id, parent_id, end_byte_offset):
    """Serialize a session_meta line exactly as write_rollout would."""
    return (
        json.dumps(
            meta(thread_id, {"thread_id": parent_id, "end_byte_offset": end_byte_offset}),
            ensure_ascii=False,
        )
        + "\n"
    )


class TestRolloutLineage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sessions = pathlib.Path(self.tmp) / "sessions"
        self.sessions.mkdir(parents=True)

    def test_returns_lineage_object_with_events_sources_and_warnings(self):
        path = write_rollout(self.sessions, "thread-a", [meta("thread-a"), msg("hello")])
        lineage = iter_rollout_events(path, HistoryResolver(self.tmp))
        self.assertIsInstance(lineage, RolloutLineage)
        events = list(lineage.events)
        self.assertEqual(len(events), 2)
        # source_paths is populated as the generator is consumed.
        self.assertEqual([p.name for p in lineage.source_paths], [path.name])
        self.assertEqual(lineage.warnings, [])

    def test_walks_paginated_parent_before_child(self):
        parent = write_rollout(
            self.sessions, "parent-1", [meta("parent-1"), msg("from parent")]
        )
        limit = parent.stat().st_size
        child = write_rollout(
            self.sessions,
            "child-1",
            [
                meta("child-1", {"thread_id": "parent-1", "end_byte_offset": limit}),
                msg("from child"),
            ],
        )
        lineage = iter_rollout_events(child, HistoryResolver(self.tmp))
        texts = []
        for e in lineage.events:
            item = e.get("payload", {}).get("item")
            if item:
                texts.append(item["content"][0]["text"])
        self.assertEqual(texts, ["from parent", "from child"])
        self.assertEqual(len(lineage.source_paths), 2)

    def test_detects_history_base_cycle(self):
        # Each offset must cover the *whole* session_meta line of the other
        # file, otherwise the parent's own history_base falls outside the read
        # window and the cycle never surfaces. Writing the files one after the
        # other cannot achieve that: the first offset would capture the other
        # file's size before it is rewritten. Solve the mutual dependency to a
        # fixed point first, then write both files.
        a_text = meta_line("cyc-a", "cyc-b", 0)
        for _ in range(5):
            b_text = meta_line("cyc-b", "cyc-a", len(a_text))
            a_text = meta_line("cyc-a", "cyc-b", len(b_text))

        a = pathlib.Path(self.sessions) / "rollout-2026-09-01T10-00-00-cyc-a.jsonl"
        b = pathlib.Path(self.sessions) / "rollout-2026-09-01T10-00-00-cyc-b.jsonl"
        a.write_text(a_text, encoding="utf-8")
        b.write_text(b_text, encoding="utf-8")

        # Guard the premise: if these drift the test would silently stop
        # exercising cycle detection and pass for the wrong reason.
        a_base = json.loads(a_text)["payload"]["history_base"]
        b_base = json.loads(b_text)["payload"]["history_base"]
        self.assertEqual(a_base["end_byte_offset"], b.stat().st_size)
        self.assertEqual(b_base["end_byte_offset"], a.stat().st_size)

        lineage = iter_rollout_events(a, HistoryResolver(self.tmp))
        with self.assertRaises(CskitRolloutError) as ctx:
            list(lineage.events)
        self.assertIn("循环", str(ctx.exception))

    def test_byte_offset_past_source_raises(self):
        parent = write_rollout(self.sessions, "p2", [meta("p2")])
        oversized = parent.stat().st_size + 5000
        child = write_rollout(
            self.sessions,
            "c2",
            [meta("c2", {"thread_id": "p2", "end_byte_offset": oversized})],
        )
        lineage = iter_rollout_events(child, HistoryResolver(self.tmp))
        with self.assertRaises(CskitRolloutError) as ctx:
            list(lineage.events)
        self.assertIn("超出", str(ctx.exception))

    def test_incomplete_history_base_raises(self):
        child = write_rollout(
            self.sessions, "c3", [meta("c3", {"thread_id": "p3"})]  # missing offset
        )
        lineage = iter_rollout_events(child, HistoryResolver(self.tmp))
        with self.assertRaises(CskitRolloutError) as ctx:
            list(lineage.events)
        self.assertIn("不完整", str(ctx.exception))

    def test_unparsable_line_is_warned_not_fatal(self):
        path = pathlib.Path(self.sessions) / "rollout-2026-09-01T10-00-00-bad.jsonl"
        path.write_text(
            json.dumps(meta("bad")) + "\n" + "{not json\n" + json.dumps(msg("ok")) + "\n",
            encoding="utf-8",
        )
        lineage = iter_rollout_events(path, HistoryResolver(self.tmp))
        events = list(lineage.events)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(lineage.warnings), 1)
        self.assertIn("无法解析", lineage.warnings[0])

    def test_missing_file_raises(self):
        lineage = iter_rollout_events(
            pathlib.Path(self.tmp) / "nope.jsonl", HistoryResolver(self.tmp)
        )
        with self.assertRaises(CskitRolloutError):
            list(lineage.events)

    def test_resolver_finds_archived_sessions(self):
        archived = pathlib.Path(self.tmp) / "archived_sessions"
        archived.mkdir()
        write_rollout(archived, "arch-1", [meta("arch-1")])
        resolver = HistoryResolver(self.tmp)
        found = resolver.resolve("arch-1", pathlib.Path(self.tmp) / "other.jsonl")
        self.assertIn("arch-1", found.name)

    def test_resolver_raises_when_parent_absent(self):
        resolver = HistoryResolver(self.tmp)
        with self.assertRaises(CskitRolloutError):
            resolver.resolve("ghost-id", pathlib.Path(self.tmp) / "cur.jsonl")


class TestJsonlPrefixBoundaries(unittest.TestCase):
    """`end_byte_offset` always lands on a line boundary in real rollouts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = pathlib.Path(self.tmp) / "rollout-2026-09-01T10-00-00-bound.jsonl"
        self.path.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        self.size = self.path.stat().st_size

    def test_limit_equal_to_file_size_reads_every_line(self):
        warnings = []
        events = list(_iter_jsonl_prefix(self.path, self.size, warnings))
        self.assertEqual(events, [{"a": 1}, {"b": 2}])
        self.assertEqual(warnings, [])

    def test_limit_on_inner_line_boundary_stops_cleanly(self):
        warnings = []
        events = list(_iter_jsonl_prefix(self.path, 9, warnings))
        self.assertEqual(events, [{"a": 1}])
        self.assertEqual(warnings, [])

    def test_limit_mid_line_drops_partial_line_with_warning(self):
        warnings = []
        events = list(_iter_jsonl_prefix(self.path, self.size - 1, warnings))
        self.assertEqual(events, [{"a": 1}])
        self.assertEqual(len(warnings), 1)
        self.assertIn("截断", warnings[0])

    def test_no_limit_reads_every_line(self):
        warnings = []
        events = list(_iter_jsonl_prefix(self.path, None, warnings))
        self.assertEqual(events, [{"a": 1}, {"b": 2}])
        self.assertEqual(warnings, [])

    def test_negative_limit_raises(self):
        with self.assertRaises(CskitRolloutError):
            list(_iter_jsonl_prefix(self.path, -1, []))


if __name__ == "__main__":
    unittest.main()
