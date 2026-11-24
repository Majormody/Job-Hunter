"""Tests for the /generate-cv command file."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMAND_PATH = ROOT / ".opencode" / "commands" / "generate-cv.md"


class GenerateCvCommandTests(unittest.TestCase):
    def test_command_file_exists_with_description(self):
        self.assertTrue(COMMAND_PATH.exists())
        text = COMMAND_PATH.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("description: Render a tailored CV PDF for one job from a report sidecar", text)

    def test_command_references_required_tools(self):
        text = COMMAND_PATH.read_text(encoding="utf-8")
        for required in [
            "tools/generate_cv.py reports",
            "tools/generate_cv.py jobs",
            "tools/generate_cv.py facts",
            "tools/generate_cv.py check",
            "tools/generate_cv.py render",
            "tools/generate_cv.py build",
            "cv-writer",
            "cv-verifier",
            "templates/CV_PATTERN.tex",
            "tools/policy.py",
        ]:
            self.assertIn(required, text, f"missing reference: {required}")

    def test_arguments_frontmatter(self):
        text = COMMAND_PATH.read_text(encoding="utf-8")
        for arg in ["--persona <slug>", "--sidecar <path>", "--job <n>", "--render-only"]:
            self.assertIn(arg, text, f"missing argument: {arg}")


if __name__ == "__main__":
    unittest.main()
