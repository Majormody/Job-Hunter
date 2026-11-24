"""Tests that docs and setup scripts stay in sync with the M9 CV pipeline."""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class DocsSyncTests(unittest.TestCase):
    def test_readme_cv_pipeline(self):
        text = read("README.md")
        for required in [
            "/generate-cv",
            "Customized_CV",
            "lualatex",
            "--render-only",
            "cv-verifier did not approve",
            "profile facts and the selected job",
        ]:
            self.assertIn(required, text, f"README missing: {required}")

    def test_quickstart_cv_pipeline(self):
        text = read("QUICKSTART.md")
        for required in [
            "/generate-cv --persona <name>",
            "--render-only",
            "LuaLaTeX",
        ]:
            self.assertIn(required, text, f"QUICKSTART missing: {required}")

    def test_architecture_cv_pipeline(self):
        text = read("docs/architecture.md")
        for required in [
            "generate_cv.py",
            "cv-verifier",
            "cv-writer",
            "Customized_CV",
            "never repaired silently",
        ]:
            self.assertIn(required, text, f"architecture missing: {required}")

    def test_privacy_cv_artifacts(self):
        text = read("docs/privacy.md")
        for required in [
            "Customized_CV",
            "state/scratch/",
            "/generate-cv` - plan/verdict",
            "/generate-cv` - build",
        ]:
            self.assertIn(required, text, f"privacy missing: {required}")

    def test_security_cv_rules(self):
        text = read("SECURITY.md")
        for required in [
            "Customized_CV",
            "cv-writer",
            "cv-verifier",
            "state/scratch/",
        ]:
            self.assertIn(required, text, f"SECURITY missing: {required}")

    def test_contributing_cv_rules(self):
        text = read("CONTRIBUTING.md")
        for required in [
            "source_ids",
            "fact-catalog/v1",
            "approved",
            "never repair",
        ]:
            self.assertIn(required, text, f"CONTRIBUTING missing: {required}")

    def test_templates_cv_output(self):
        text = read("templates/README.md")
        for required in [
            "Customized_CV",
            "LuaLaTeX",
            "--render-only",
        ]:
            self.assertIn(required, text, f"templates/README missing: {required}")

    def test_setup_optional_lualatex(self):
        text = read("setup.sh")
        self.assertIn("lualatex", text)
        self.assertIn("Needed only for /generate-cv build", text)
        self.assertNotIn("lualatex is not installed. Install", text)


if __name__ == "__main__":
    unittest.main()
