"""Packaging and release-pipeline contract tests.

These protect the distribution guarantees from issue #12:

- the package declares a ``cskit`` console script pointing at ``main()``
- wheel metadata is complete enough for a public PyPI release
- the PyPI publish workflow uses OIDC Trusted Publisher (no stored token)
- the README documents the one-command install paths

Python 3.9 has no ``tomllib``; on 3.9 the metadata assertions use
structural text checks, while 3.11+ parses the TOML properly.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
README = ROOT / "README.md"


def _load_pyproject():
    text = PYPROJECT.read_text()
    try:
        import tomllib  # Python 3.11+

        return tomllib.loads(text), text
    except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.9
        return None, text


class PyProjectMetadataTest(unittest.TestCase):
    def setUp(self):
        self.data, self.text = _load_pyproject()

    def test_console_script_points_at_main(self):
        if self.data is not None:
            scripts = self.data["project"].get("scripts", {})
            self.assertEqual(scripts.get("cskit"), "cskit.__main__:main")
        else:
            self.assertIn("[project.scripts]", self.text)
            self.assertIn('cskit = "cskit.__main__:main"', self.text)

    def test_required_public_metadata(self):
        if self.data is not None:
            project = self.data["project"]
            self.assertEqual(project["name"], "cskit-cli")
            self.assertEqual(project["readme"], "README.md")
            self.assertEqual(project["requires-python"], ">=3.9")
            self.assertTrue(
                project["license"] in ("MIT", {"text": "MIT"})
                or project.get("license-files")
            )
            urls = project.get("urls", {})
            self.assertIn("https://github.com/Weiki886/cskit", urls.values())
            self.assertTrue(project.get("classifiers"))
        else:
            for fragment in (
                'readme = "README.md"',
                'requires-python = ">=3.9"',
                "[project.urls]",
                "classifiers",
            ):
                self.assertIn(fragment, self.text)

    def test_package_discovery_is_explicit(self):
        # Without explicit discovery a future top-level module (plans/, tests/)
        # could accidentally be shipped or the cskit package missed.
        if self.data is not None:
            find = self.data["tool"]["setuptools"]["packages"]["find"]
            include = find.get("include", [])
            self.assertTrue(
        any(item == "cskit*" or item == "cskit" for item in include),
                include,
            )
        else:
            self.assertIn("[tool.setuptools.packages.find]", self.text)
            self.assertIn('"cskit*"', self.text)

    def test_version_single_source_stays_in_sync(self):
        import cskit

        if self.data is not None:
            self.assertEqual(self.data["project"]["version"], cskit.__version__)
        else:
            self.assertIn(f'version = "{cskit.__version__}"', self.text)


class EntryPointTest(unittest.TestCase):
    def test_main_is_callable_and_returns_zero_for_version(self):
        from cskit.__main__ import main

        self.assertTrue(callable(main))
        result = subprocess.run(
            [sys.executable, "-m", "cskit", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cskit", result.stdout)


class PublishWorkflowTest(unittest.TestCase):
    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.exists(), "missing .github/workflows/publish.yml")

    def test_trusted_publisher_contract(self):
        text = WORKFLOW.read_text()
        # Tag-triggered release
        self.assertIn("v*", text)
        # OIDC Trusted Publisher, not a stored PyPI API token
        self.assertIn("id-token: write", text)
        self.assertIn("environment:", text)
        self.assertIn("pypi", text)
        self.assertIn("pypa/gh-action-pypi-publish", text)
        self.assertNotIn("PYPI_TOKEN", text)
        self.assertNotIn("password:", text.lower().replace("pypa/gh-action-pypi-publish", ""))


class ReadmeInstallTest(unittest.TestCase):
    def test_documents_both_install_paths(self):
        text = README.read_text()
        self.assertIn("uv tool install cskit-cli", text)
        self.assertIn("uv tool install git+https://github.com/Weiki886/cskit", text)


if __name__ == "__main__":
    unittest.main()
