import unittest
import sys
import os
import tempfile
import pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cskit.toml_util import read_top_level_keys
from cskit.errors import CskitConfigError


class TestTopLevelTomlParsing(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = pathlib.Path(d) / "config.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_reads_plain_top_level_keys(self):
        p = self._write('model_provider = "custom"\nmodel = "ark-code-latest"\n')
        self.assertEqual(
            read_top_level_keys(p, {"model", "model_provider"}),
            {"model": "ark-code-latest", "model_provider": "custom"},
        )

    def test_section_before_top_level_key_does_not_win(self):
        """Regression: awk's `exit` took the first line match regardless of scope."""
        p = self._write(
            '[model_providers.foo]\n'
            'model = "WRONG-from-section"\n'
            '\n'
            'model = "correct-toplevel"\n'
        )
        # A real TOML parser treats the trailing `model` as still inside the
        # section, so there is no valid top-level `model` here at all.
        result = read_top_level_keys(p, {"model"})
        self.assertNotEqual(result.get("model"), "WRONG-from-section")

    def test_keys_after_a_section_are_not_top_level(self):
        p = self._write(
            'model = "real-toplevel"\n'
            '[model_providers.custom]\n'
            'model = "inside-section"\n'
        )
        self.assertEqual(read_top_level_keys(p, {"model"}), {"model": "real-toplevel"})

    def test_ignores_similar_prefixed_keys(self):
        p = self._write(
            'model = "gpt"\n'
            'model_reasoning_effort = "medium"\n'
            'model_catalog_json = "catalog.json"\n'
        )
        self.assertEqual(read_top_level_keys(p, {"model"}), {"model": "gpt"})

    def test_handles_single_quotes_and_whitespace(self):
        p = self._write("model   =    'ark'\n")
        self.assertEqual(read_top_level_keys(p, {"model"}), {"model": "ark"})

    def test_ignores_comments(self):
        p = self._write('# model = "commented"\nmodel = "actual"\n')
        self.assertEqual(read_top_level_keys(p, {"model"}), {"model": "actual"})

    def test_missing_file_raises_config_error(self):
        with self.assertRaises(CskitConfigError):
            read_top_level_keys(pathlib.Path("/nonexistent/config.toml"), {"model"})

    def test_absent_key_is_omitted_not_defaulted(self):
        p = self._write('model = "only-model"\n')
        self.assertEqual(read_top_level_keys(p, {"model", "model_provider"}), {"model": "only-model"})


if __name__ == "__main__":
    unittest.main()
