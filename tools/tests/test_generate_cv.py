"""Tests for tools/generate_cv.py."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import generate_cv


def write_tmp(content: dict | str, suffix: str = ".json") -> Path:
    path = Path(tempfile.mkdtemp()) / ("file" + suffix)
    path.write_text(json.dumps(content, ensure_ascii=False) if isinstance(content, dict) else content, encoding="utf-8")
    return path


class FactTests(unittest.TestCase):
    def test_slugify_and_escape(self):
        self.assertEqual(generate_cv.slugify("Acme Corp"), "acme-corp")
        self.assertEqual(generate_cv.slugify("   "), "unknown")
        self.assertEqual(generate_cv.escape_tex("a & b_c"), "a \\& b\\_c")


class ValidationTests(unittest.TestCase):
    def _minimal(self, **overrides):
        plan = {
            "schema": "cv-plan/v1",
            "status": "ok",
            "persona": "p",
            "job_number": 1,
            "headline": {"op": "select", "source_ids": ["role:0"], "text": "Engineer"},
            "summary": {"op": "select", "source_ids": ["summary:0"], "text": "Summary text."},
            "skills": [{"op": "select", "source_ids": ["skill:0"], "text": "Python"}],
            "experience": [],
            "projects": [],
            "education": [],
            "section_order": ["summary", "skills"],
            "order_reason": {"signals": [], "reason": "default order"},
        }
        plan.update(overrides)
        return plan

    def _facts(self):
        return {
            "schema": "fact-catalog/v1",
            "persona": "p",
            "facts": [
                {"id": "summary:0", "kind": "summary", "text": "Summary text.", "evidence": "resume:x#L5-8"},
                {"id": "role:0", "kind": "role", "text": "Engineer", "evidence": "resume:x#L1"},
                {"id": "skill:0", "kind": "skill", "text": "Python", "evidence": "resume:x#L2"},
            ],
        }

    def _job(self, signals=None):
        return {"number": 1, "company": "Example", "emphasis_signals": signals or []}

    def test_valid_plan_passes(self):
        plan = self._minimal()
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertEqual(violations, [])

    def test_unknown_source_id_is_rejected(self):
        plan = self._minimal(headline={"op": "select", "source_ids": ["role:9"], "text": "Engineer"})
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertTrue(any("unknown source id" in v for v in violations))

    def test_wrong_kind_is_rejected(self):
        plan = self._minimal(headline={"op": "select", "source_ids": ["skill:0"], "text": "Engineer"})
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertTrue(any("has kind 'skill'" in v for v in violations))

    def test_summary_requires_verbatim_select(self):
        plan = self._minimal()
        plan["summary"] = {"op": "select", "source_ids": ["summary:0"], "text": "Changed summary."}
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertTrue(any("must match the cited summary fact" in v for v in violations))

        plan["summary"]["text"] = "Summary text."
        self.assertEqual(generate_cv.validate_plan(plan, self._facts(), self._job(), "p"), [])

    def test_summary_duplicate_bullet_is_rejected(self):
        facts = {
            "schema": "fact-catalog/v1",
            "persona": "p",
            "facts": [
                {"id": "summary:0", "kind": "summary", "text": "Built things.", "evidence": "resume:x#L5-8"},
                {"id": "role:0", "kind": "role", "text": "Engineer", "evidence": "resume:x#L1"},
                {"id": "skill:0", "kind": "skill", "text": "Python", "evidence": "resume:x#L2"},
                {"id": "bullet:0", "kind": "bullet", "text": "Built things.", "evidence": "resume:x#L3"},
            ],
        }
        plan = {
            "schema": "cv-plan/v1",
            "status": "ok",
            "persona": "p",
            "job_number": 1,
            "headline": {"op": "select", "source_ids": ["role:0"], "text": "Engineer"},
            "summary": {"op": "select", "source_ids": ["summary:0"], "text": "Built things."},
            "skills": [{"op": "select", "source_ids": ["skill:0"], "text": "Python"}],
            "experience": [],
            "projects": [],
            "education": [],
            "section_order": ["summary", "skills"],
            "order_reason": {"signals": [], "reason": "default order"},
        }
        violations = generate_cv.validate_plan(plan, facts, self._job(), "p")
        self.assertTrue(any("duplicates bullet text" in v for v in violations))

    def test_validate_plan_requires_content_coverage(self):
        plan = self._minimal()
        plan["skills"] = []
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertTrue(any("unreferenced content facts" in v for v in violations))

    def test_project_bullets_accept_bullet_facts(self):
        facts = {
            "schema": "fact-catalog/v1",
            "persona": "p",
            "facts": [
                {"id": "summary:0", "kind": "summary", "text": "Summary text.", "evidence": "resume:x#L5-8"},
                {"id": "role:0", "kind": "role", "text": "Engineer", "evidence": "resume:x#L0"},
                {"id": "skill:0", "kind": "skill", "text": "Python", "evidence": "resume:x#L2"},
                {"id": "project:0:name", "kind": "project", "text": "RAG App", "evidence": "resume:x#L1"},
                {"id": "bullet:0", "kind": "bullet", "text": "Built things.", "evidence": "resume:x#L2"},
            ],
        }
        plan = {
            "schema": "cv-plan/v1",
            "status": "ok",
            "persona": "p",
            "job_number": 1,
            "headline": {"op": "select", "source_ids": ["role:0"], "text": "Engineer"},
            "summary": {"op": "select", "source_ids": ["summary:0"], "text": "Summary text."},
            "skills": [{"op": "select", "source_ids": ["skill:0"], "text": "Python"}],
            "experience": [],
            "projects": [
                {
                    "heading": {"op": "select", "source_ids": ["project:0:name"], "text": "RAG App"},
                    "bullets": [{"op": "rewrite", "source_ids": ["bullet:0"], "text": "Built things."}],
                }
            ],
            "education": [],
            "section_order": ["summary", "skills", "projects"],
            "order_reason": {"signals": [], "reason": "default order"},
        }
        violations = generate_cv.validate_plan(plan, facts, self._job(), "p")
        self.assertEqual(violations, [])

    def test_owned_bullet_must_stay_under_owner(self):
        facts = {
            "schema": "fact-catalog/v1",
            "persona": "p",
            "facts": [
                {"id": "summary:0", "kind": "summary", "text": "Summary text.", "evidence": "resume:x#L5-8"},
                {"id": "role:0", "kind": "role", "text": "Engineer", "evidence": "resume:x#L0"},
                {"id": "skill:0", "kind": "skill", "text": "Python", "evidence": "resume:x#L1"},
                {"id": "project:0:name", "kind": "project", "text": "RAG App", "evidence": "resume:x#L2"},
                {"id": "bullet:0", "kind": "bullet", "text": "Built things.", "evidence": "resume:x#L3", "owner": "experience:0"},
            ],
        }
        plan = {
            "schema": "cv-plan/v1",
            "status": "ok",
            "persona": "p",
            "job_number": 1,
            "headline": {"op": "select", "source_ids": ["role:0"], "text": "Engineer"},
            "summary": {"op": "select", "source_ids": ["summary:0"], "text": "Summary text."},
            "skills": [{"op": "select", "source_ids": ["skill:0"], "text": "Python"}],
            "experience": [],
            "projects": [
                {
                    "heading": {"op": "select", "source_ids": ["project:0:name"], "text": "RAG App"},
                    "bullets": [{"op": "rewrite", "source_ids": ["bullet:0"], "text": "Built things."}],
                }
            ],
            "education": [],
            "section_order": ["summary", "skills", "projects"],
            "order_reason": {"signals": [], "reason": "default order"},
        }
        violations = generate_cv.validate_plan(plan, facts, self._job(), "p")
        self.assertTrue(any("is owned by experience:0, expected project:0" in v for v in violations))

    def test_section_order_rules(self):
        plan = self._minimal(section_order=["skills", "summary"])
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertTrue(any("start with summary" in v for v in violations))

        plan = self._minimal(section_order=["summary", "summary"])
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(), "p")
        self.assertTrue(any("duplicate" in v for v in violations))

    def test_signal_subset_is_required(self):
        plan = self._minimal(order_reason={"signals": ["hands_on"], "reason": "projects first"})
        violations = generate_cv.validate_plan(plan, self._facts(), self._job(signals=["research"]), "p")
        self.assertTrue(any("subset of job emphasis_signals" in v for v in violations))


class RenderingTests(unittest.TestCase):
    def test_latex_escaping(self):
        plan = {
            "schema": "cv-plan/v1",
            "status": "ok",
            "persona": "p",
            "job_number": 1,
            "headline": {"op": "select", "source_ids": ["role:0"], "text": "a & b"},
            "summary": {"op": "rewrite", "source_ids": ["bullet:0"], "text": "summary"},
            "skills": [],
            "experience": [],
            "projects": [],
            "education": [],
            "section_order": ["summary"],
            "order_reason": {"signals": [], "reason": "default"},
        }
        latex = generate_cv.render_latex(plan, "Name", "email@example.com")
        self.assertIn("\\CVHeader{Name}{a \\& b}{email@example.com}", latex)
        self.assertNotIn("@@HEADER@@", latex)
        self.assertNotIn("@@SECTIONS@@", latex)

    def test_contact_separator_is_not_double_escaped(self):
        plan = {
            "schema": "cv-plan/v1",
            "status": "ok",
            "persona": "p",
            "job_number": 1,
            "headline": {"op": "select", "source_ids": ["role:0"], "text": "Engineer"},
            "summary": {"op": "rewrite", "source_ids": ["bullet:0"], "text": "summary"},
            "skills": [],
            "experience": [],
            "projects": [],
            "education": [],
            "section_order": ["summary"],
            "order_reason": {"signals": [], "reason": "default"},
        }
        latex = generate_cv.render_latex(
            plan, "Name", ["email@example.com", "+1 555", "github: github.com/user"]
        )
        self.assertIn(
            "\\CVHeader{Name}{Engineer}{email@example.com \\CVSep +1 555 \\CVSep github: github.com/user}",
            latex,
        )
        self.assertNotIn("\\textbackslash{}CVSep", latex)


class FactBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.profile_path = self.temp / "profile.yaml"
        self.inputs_path = self.temp / "inputs.yaml"
        self.profile_patch = patch.object(generate_cv, "persona_yaml", return_value=self.profile_path)
        self.inputs_patch = patch.object(generate_cv, "profile_inputs_path", return_value=self.inputs_path)
        self.profile_patch.start()
        self.inputs_patch.start()

    def tearDown(self):
        self.profile_patch.stop()
        self.inputs_patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_build_facts_ids(self):
        self.profile_path.write_text(
            """
title: AI Persona
target_roles:
  - title: AI Engineer
    priority: 1
    evidence: resume:ai#L1
skills:
  - name: Python
    weight: primary
    evidence: resume:ai#L2
evidence_bullets:
  - text: Built RAG.
    source: resume:ai#L3
projects:
  - name: RAG App
    detail: Retrieved documents.
    evidence: resume:ai#L4
experience:
  - heading: Senior Engineer - Acme - 2020-2023
    detail: Led the team.
    evidence: resume:ai#L5
education:
  - text: MSc AI - University - 2020
""",
            encoding="utf-8",
        )
        catalog = generate_cv.build_facts("p")
        self.assertEqual(catalog["schema"], "fact-catalog/v1")
        ids = [fact["id"] for fact in catalog["facts"]]
        self.assertIn("role:0", ids)
        self.assertIn("skill:0", ids)
        self.assertIn("bullet:0", ids)
        self.assertIn("project:0:name", ids)
        self.assertIn("project:0:detail", ids)
        self.assertIn("experience:0:heading", ids)
        self.assertIn("experience:0:detail", ids)
        self.assertIn("education:0", ids)

    def test_build_facts_value_source_shape(self):
        self.profile_path.write_text(
            """
title: AI Persona
target_roles:
  - title: AI Engineer
    priority: 1
    evidence: resume:ai#L1
skills:
  - name: Python
    weight: primary
    evidence: resume:ai#L2
evidence_bullets:
  - text: Built RAG.
    source: resume:ai#L3
projects:
  - name: RAG App
    detail: Retrieved documents.
    evidence: resume:ai#L4
experience:
  - value: Senior Engineer - Acme - 2020-2023
    source: resume:ai#L5
education:
  - value: MSc AI - University - 2020
    source: resume:ai#L6
""",
            encoding="utf-8",
        )
        catalog = generate_cv.build_facts("p")
        ids = [fact["id"] for fact in catalog["facts"]]
        self.assertIn("role:0", ids)
        self.assertIn("skill:0", ids)
        self.assertIn("bullet:0", ids)
        self.assertIn("project:0:name", ids)
        self.assertIn("project:0:detail", ids)
        self.assertIn("experience:0:heading", ids)
        self.assertNotIn("experience:0:detail", ids)
        self.assertIn("education:0", ids)


class PagePolicyTests(unittest.TestCase):
    def test_infer_cv_page_policy(self):
        self.assertEqual(
            generate_cv.infer_cv_page_policy({"title": "AI / LLM / RAG Engineer (junior)", "facts": []}),
            {"seniority": "junior", "max_pages": 1},
        )
        self.assertEqual(
            generate_cv.infer_cv_page_policy({"title": "Senior AI Engineer", "facts": []}),
            {"seniority": "senior", "max_pages": 2},
        )
        self.assertEqual(
            generate_cv.infer_cv_page_policy({"title": "Mid-level AI Engineer", "facts": []}),
            {"seniority": "mid", "max_pages": 2},
        )
        self.assertEqual(
            generate_cv.infer_cv_page_policy({"title": "Unknown Engineer", "facts": []}),
            {"seniority": "junior", "max_pages": 1},
        )

    def test_parse_lualatex_pages(self):
        self.assertEqual(
            generate_cv.parse_lualatex_pages("Output written on /tmp/out.pdf (1 page, 30169 bytes)."), 1
        )
        self.assertEqual(
            generate_cv.parse_lualatex_pages("Output written on /tmp/out.pdf (2 pages, 50000 bytes)."), 2
        )
        self.assertIsNone(generate_cv.parse_lualatex_pages("no page info here"))


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.sidecar_path = write_tmp(
            {
                "schema": "report-index/v1",
                "persona": "p",
                "date": "2026-01-01",
                "ts": "2026-01-01-12-00",
                "report_sidecar": "jobs-2026-01-01-12-00.json",
                "jobs": [
                    {
                        "number": 1,
                        "title": "AI Engineer",
                        "company": "Example",
                        "portal": "freehire-search",
                        "score": 80,
                        "url": "https://example.invalid/job/1",
                        "emphasis_signals": ["hands_on"],
                    }
                ],
            }
        )
        self.facts_path = write_tmp(
            {
                "schema": "fact-catalog/v1",
                "persona": "p",
                "facts": [
                    {"id": "summary:0", "kind": "summary", "text": "Built RAG.", "evidence": "resume:x#L5-8"},
                    {"id": "role:0", "kind": "role", "text": "AI Engineer", "evidence": "resume:x#L1"},
                    {"id": "skill:0", "kind": "skill", "text": "Python", "evidence": "resume:x#L2"},
                ],
            }
        )
        self.plan_path = write_tmp(
            {
                "schema": "cv-plan/v1",
                "status": "ok",
                "persona": "p",
                "job_number": 1,
                "headline": {"op": "select", "source_ids": ["role:0"], "text": "AI Engineer"},
                "summary": {"op": "select", "source_ids": ["summary:0"], "text": "Built RAG."},
            "skills": [{"op": "select", "source_ids": ["skill:0"], "text": "Python"}],
            "experience": [],
            "projects": [],
            "education": [],
            "section_order": ["summary", "skills"],
                "order_reason": {"signals": [], "reason": "default"},
            }
        )
        self.approved_verdict_path = write_tmp(
            {"schema": "cv-verdict/v1", "approved": True, "violations": [], "checks": []}
        )
        self.bad_verdict_path = write_tmp(
            {"schema": "cv-verdict/v1", "approved": False, "violations": [{"path": "summary", "reason": "bad"}], "checks": []}
        )

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _run(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = generate_cv.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_check_approved_plan_passes(self):
        code, output, _ = self._run(
            "check",
            "--sidecar",
            str(self.sidecar_path),
            "--job-number",
            "1",
            "--facts",
            str(self.facts_path),
            "--plan",
            str(self.plan_path),
        )
        self.assertEqual(code, 0)
        verdict = json.loads(output)
        self.assertTrue(verdict["approved"])

    def test_render_refuses_unapproved_verdict(self):
        code, _out, err = self._run(
            "render",
            "--sidecar",
            str(self.sidecar_path),
            "--job-number",
            "1",
            "--facts",
            str(self.facts_path),
            "--plan",
            str(self.plan_path),
            "--verdict",
            str(self.bad_verdict_path),
        )
        self.assertNotEqual(code, 0)

    def test_build_refuses_missing_lualatex(self):
        with patch.object(generate_cv.subprocess, "run", side_effect=FileNotFoundError):
            code, _out, err = self._run(
                "build",
                "--sidecar",
                str(self.sidecar_path),
                "--job-number",
                "1",
                "--facts",
                str(self.facts_path),
                "--plan",
                str(self.plan_path),
                "--verdict",
                str(self.approved_verdict_path),
            )
        self.assertNotEqual(code, 0)
        self.assertIn("lualatex is not installed", err)


if __name__ == "__main__":
    unittest.main()
