from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cskit import __version__
from cskit.__main__ import COMMANDS, main


def run_main(args):
    """Run main() capturing stdout/stderr; returns (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestHelpAndVersion(unittest.TestCase):
    def test_no_arguments_prints_usage(self):
        code, out, _ = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("用法：", out)

    def test_help_lists_every_command(self):
        for flag in ("-h", "--help", "help"):
            with self.subTest(flag=flag):
                code, out, _ = run_main([flag])
                self.assertEqual(code, 0)
                for command in COMMANDS:
                    self.assertIn(command, out)

    def test_version_flags_report_package_version(self):
        for flag in ("-V", "--version", "version"):
            with self.subTest(flag=flag):
                code, out, _ = run_main([flag])
                self.assertEqual(code, 0)
                self.assertEqual(out.strip(), f"cskit {__version__}")


class TestUnknownCommand(unittest.TestCase):
    def test_exits_two_and_suggests_commands(self):
        code, _, err = run_main(["nonexistent"])
        self.assertEqual(code, 2)
        self.assertIn("未知命令", err)
        for command in COMMANDS:
            self.assertIn(command, err)

    def test_does_not_treat_unknown_command_as_success(self):
        code, _, _ = run_main(["nonexistent"])
        self.assertNotEqual(code, 0)


class TestErrorHandling(unittest.TestCase):
    def test_cskit_error_becomes_clean_message_not_traceback(self):
        from cskit import __main__ as entry
        from cskit.errors import CskitDataError

        original = entry._dispatch
        entry._dispatch = lambda *a: (_ for _ in ()).throw(CskitDataError("测试错误"))
        try:
            code, _, err = run_main(["export"])
        finally:
            entry._dispatch = original
        self.assertEqual(code, 1)
        self.assertIn("测试错误", err)
        self.assertNotIn("Traceback", err)

    def test_keyboard_interrupt_returns_130(self):
        from cskit import __main__ as entry

        original = entry._dispatch
        entry._dispatch = lambda *a: (_ for _ in ()).throw(KeyboardInterrupt)
        try:
            code, _, err = run_main(["export"])
        finally:
            entry._dispatch = original
        self.assertEqual(code, 130)
        self.assertIn("已取消", err)

    def test_broken_pipe_is_not_an_error(self):
        from cskit import __main__ as entry

        original = entry._dispatch
        entry._dispatch = lambda *a: (_ for _ in ()).throw(BrokenPipeError)
        try:
            code, _, _ = run_main(["export"])
        finally:
            entry._dispatch = original
        self.assertEqual(code, 0)

    def test_none_return_is_normalised_to_zero(self):
        from cskit import __main__ as entry

        original = entry._dispatch
        entry._dispatch = lambda *a: None
        try:
            code, _, _ = run_main(["export"])
        finally:
            entry._dispatch = original
        self.assertEqual(code, 0)


class TestSubcommandHelp(unittest.TestCase):
    """Each subcommand owns its parser, so --help must reach it."""

    def test_export_help_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            run_main(["export", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_clone_help_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            run_main(["clone", "--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
