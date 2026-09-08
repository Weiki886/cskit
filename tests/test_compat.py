"""Guards for Issue #1 acceptance criteria that are easy to regress silently.

These do not test behaviour; they enforce constraints on the source tree that
would otherwise only surface on a user's Python 3.9, or after a secret has
already been pushed to a public repo.
"""

import ast
import os
import pathlib
import re
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "cskit"
REPO = pathlib.Path(__file__).resolve().parent.parent

MODERN_ANNOTATION = re.compile(
    r"(?:\b(?:list|dict|set|frozenset|tuple|type)\[)"  # list[str]
    r"|(?:\w\s*\|\s*(?:None|\w))"                      # X | None
)


def package_sources():
    return sorted(PACKAGE.glob("*.py"))


def committed_text_files():
    """Every file that ships in the public repo, not just the Python package.

    install.sh and README.md are as public as the sources, so the secret scan
    must cover them too.
    """
    paths = []
    for pattern in ("cskit/*.py", "tests/*.py", "*.sh", "*.md", "*.toml"):
        paths.extend(REPO.glob(pattern))
    return sorted(p for p in paths if p.is_file())


class TestPython39Compatibility(unittest.TestCase):
    def test_package_is_non_empty(self):
        # Guards against the glob silently matching nothing, which would make
        # every other check in this class vacuously pass.
        self.assertTrue(package_sources(), f"no sources found under {PACKAGE}")

    def test_modern_annotations_require_future_import(self):
        offenders = []
        for path in package_sources():
            text = path.read_text(encoding="utf-8")
            if not MODERN_ANNOTATION.search(text):
                continue
            tree = ast.parse(text)
            has_future = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "__future__"
                and any(alias.name == "annotations" for alias in node.names)
                for node in tree.body
            )
            if not has_future:
                offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            "these files use modern annotations without "
            "`from __future__ import annotations` and will fail on 3.9: "
            + ", ".join(offenders),
        )

    def test_no_runtime_type_hint_evaluation(self):
        # `from __future__ import annotations` does not protect hints that are
        # evaluated at runtime.
        offenders = [
            path.name for path in package_sources()
            if "get_type_hints" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [], f"get_type_hints found in: {offenders}")

    def test_no_match_statement(self):
        # `match` is 3.10+. ast.parse on 3.9 would reject it, but the tests may
        # run on a newer interpreter, so check the tree explicitly.
        offenders = []
        for path in package_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(isinstance(node, getattr(ast, "Match", ())) for node in ast.walk(tree)):
                offenders.append(path.name)
        self.assertEqual(offenders, [], f"match statement found in: {offenders}")


class TestNoLeakedSecrets(unittest.TestCase):
    """The repo is public; these patterns must never be committed."""

    PATTERNS = (
        (re.compile(r"sk-[A-Za-z0-9]{16,}"), "OpenAI-style API key"),
        # Split so this file's own pattern literals cannot match themselves.
        (re.compile("experimental" + "_bearer_" + "token"), "bearer token config key"),
        (re.compile(r"/Users/[a-z]"), "personal absolute path"),
    )

    def test_repo_files_are_clean(self):
        findings = []
        for path in committed_text_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern, label in self.PATTERNS:
                if pattern.search(text):
                    findings.append(f"{path.relative_to(REPO)}: {label}")
        self.assertEqual(findings, [], f"secrets/paths committed: {findings}")

    def test_scan_covers_more_than_the_package(self):
        # Guards against the globs silently matching only cskit/*.py, which
        # would make the scan above pass while ignoring install.sh.
        names = {p.name for p in committed_text_files()}
        self.assertIn("install.sh", names)
        self.assertIn("README.md", names)


if __name__ == "__main__":
    unittest.main()
