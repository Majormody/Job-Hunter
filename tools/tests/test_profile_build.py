"""Tests for tools/profile_build.py validators."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import profile_build


class TestValidSlug(unittest.TestCase):
    def test_valid(self):
        for slug in ("ai-llm-rag", "x", "a-b-c", "ml-backend", "v2"):
            self.assertEqual(profile_build.valid_slug(slug), [], slug)

    def test_invalid(self):
        for slug in ("", "AI-LLM", "ai llm", "ai__llm", "ai.llm", "-lead", "trailing-"):
            self.assertNotEqual(profile_build.valid_slug(slug), [], slug)


class TestEvidenceSlugs(unittest.TestCase):
    def test_extracts(self):
        persona = {
            "skills": [
                {"name": "Python", "weight": "primary", "evidence": "resume:mohamed--ai-llm-rag--v1#L10"}
            ],
            "identity": {
                "name": {"value": "X", "source": "resume:mohamed--ai-llm-rag--v1#L1"},
                "location": {"value": "Cairo", "source": "resume:mohamed--ai-llm-rag--v1#L3"},
            },
            "evidence_bullets": [{"text": "t", "source": "resume:mohamed--ai-llm-rag--v1#L5"}],
            "persona_exclusions": [{"reason": "r", "source": "resume:mohamed--ai-llm-rag--v1#L9"}],
            "target_roles": [{"title": "Engineer", "priority": 1}],
        }
        self.assertEqual(
            profile_build.evidence_slugs(persona),
            {"mohamed--ai-llm-rag--v1"},
        )

    def test_ignores_plain_text(self):
        persona = {"skills": [{"evidence": "no source here"}]}
        self.assertEqual(profile_build.evidence_slugs(persona), set())


class TestValidate(unittest.TestCase):
    def base_persona(self, slug="ai-llm-rag"):
        return {
            "persona": slug,
            "title": "T",
            "resumes": [
                {"slug": slug, "file": f"resumes/{slug}.pdf", "sha256": "ab" * 32}
            ],
            "skills": [
                {"name": "Python", "weight": "primary", "evidence": f"resume:{slug}#L1"}
            ],
            "target_roles": [{"title": "Engineer", "priority": 1}],
        }

    def test_valid(self):
        self.assertEqual(profile_build.validate(self.base_persona(), "ai-llm-rag"), [])

    def test_invalid_persona_slug(self):
        p = self.base_persona()
        self.assertNotEqual(profile_build.validate(p, "AI-LLM"), [])

    def test_duplicate_resume_slugs(self):
        p = self.base_persona()
        p["resumes"].append(dict(p["resumes"][0]))
        problems = profile_build.validate(p, "ai-llm-rag")
        self.assertTrue(any("duplicate slug" in pr for pr in problems))

    def test_evidence_slug_not_in_resumes(self):
        p = self.base_persona()
        p["skills"][0]["evidence"] = "resume:other-cv--v1#L1"
        problems = profile_build.validate(p, "ai-llm-rag")
        self.assertTrue(any("not in this persona's resumes list" in pr for pr in problems))


class TestCheckFreshness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, persona):
        with patch.object(profile_build, "ROOT", self.tmpdir):
            return profile_build.check_freshness(persona)

    def test_current(self):
        cv = self.tmpdir / "cv.pdf"
        cv.write_text("content")
        import hashlib

        digest = hashlib.sha256(cv.read_bytes()).hexdigest()
        persona = {"resumes": [{"slug": "cv", "file": str(cv), "sha256": digest}]}
        rows, problems = self._run(persona)
        self.assertEqual(rows[0]["state"], "current")
        self.assertEqual(problems, [])

    def test_stale(self):
        cv = self.tmpdir / "cv.pdf"
        cv.write_text("changed")
        persona = {"resumes": [{"slug": "cv", "file": str(cv), "sha256": "00" * 32}]}
        rows, problems = self._run(persona)
        self.assertEqual(rows[0]["state"], "stale")
        self.assertTrue(problems)

    def test_missing(self):
        persona = {
            "resumes": [
                {"slug": "cv", "file": str(self.tmpdir / "nope.pdf"), "sha256": "ab" * 32}
            ]
        }
        rows, problems = self._run(persona)
        self.assertEqual(rows[0]["state"], "missing")
        self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
