"""Two-persona end-to-end acceptance tests for M5."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import extract_resume
import paths
import profile_build
import profile_query
import subprocess


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_cv(root: Path, name: str, content: str) -> Path:
    resumes = root / "resumes"
    resumes.mkdir(parents=True, exist_ok=True)
    path = resumes / name
    path.write_text(content, encoding="utf-8")
    return path


def make_persona(slug: str, title: str, resume_slug: str, resume_file: str, sha256: str, role_title: str) -> dict:
    return {
        "persona": slug,
        "title": title,
        "resumes": [
            {
                "slug": resume_slug,
                "file": resume_file,
                "sha256": sha256,
            }
        ],
        "skills": [
            {"name": "Python", "weight": "primary", "evidence": f"resume:{resume_slug}#L1"},
            {"name": "SQL", "weight": "secondary", "evidence": f"resume:{resume_slug}#L2"},
        ],
        "target_roles": [
            {"title": role_title, "priority": 1},
        ],
        "evidence_bullets": [
            {"text": "Placeholder bullet.", "source": f"resume:{resume_slug}#L3"},
        ],
        "identity": {"name": {"value": "Placeholder", "source": f"resume:{resume_slug}#L4"}},
        "education": [],
        "experience": [],
        "projects": [],
        "persona_exclusions": [],
        "conflicts": [],
    }


class TestPersonaWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="job-hunter-m5-"))
        self.root = self.tmpdir / "root"
        self.resumes = self.root / "resumes"
        self.profiles = self.root / "profiles"
        self.extracted = self.resumes / "extracted"
        for directory in (self.resumes, self.profiles, self.extracted):
            directory.mkdir(parents=True, exist_ok=True)
        (self.profiles / "inputs.yaml").write_text(
            "identity:\n  location: Cairo, Egypt\nsearch:\n  portals: {}\n", encoding="utf-8"
        )

        self.cv_a = write_cv(self.root, "owner-a-rag-ai-v20260101.txt", "CV A content for RAG AI role.\n")
        self.cv_b = write_cv(self.root, "owner-b-ml-backend-v20260102.txt", "CV B content for ML backend role.\n")
        self.slug_a = "owner-a-rag-ai-v20260101"
        self.slug_b = "owner-b-ml-backend-v20260102"
        self.persona_a = "persona-a"
        self.persona_b = "persona-b"

        self.path_patches = [
            patch.object(paths, "profile_index_path", return_value=self.profiles / "index.json"),
            patch.object(paths, "personas_dir", return_value=self.profiles),
            patch.object(paths, "profile_inputs_path", return_value=self.profiles / "inputs.yaml"),
            patch.object(profile_build, "ROOT", self.root),
            patch.object(extract_resume, "resumes_dir", return_value=self.resumes),
            patch.object(extract_resume, "extracted_dir", return_value=self.extracted),
            patch.object(subprocess, "run", return_value=type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()),
        ]
        for p in self.path_patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.path_patches):
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_profile_build(self, *args):
        old_argv = sys.argv
        old_stdout = sys.stdout
        sys.argv = ["tools/profile_build.py", *args]
        sys.stdout = StringIO()
        try:
            rc = profile_build.main()
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv
        return rc, output

    def _write_persona(self, slug, title, resume_slug, resume_file, sha256, role_title):
        persona = make_persona(slug, title, resume_slug, resume_file, sha256, role_title)
        (self.profiles / slug).mkdir(parents=True, exist_ok=True)
        (self.profiles / slug / "profile.yaml").write_text(json.dumps(persona), encoding="utf-8")
        return persona

    def _read_index(self):
        return json.loads((self.profiles / "index.json").read_text(encoding="utf-8"))

    def test_inventory_lists_two_cvs(self):
        inv = extract_resume.inventory()
        self.assertEqual({item["slug"] for item in inv["resumes"]}, {self.slug_a, self.slug_b})
        self.assertEqual(inv["slug_collisions"], [])
        self.assertEqual(inv["stale_extracted"], [])

    def test_finalize_a_registers_only_a(self):
        self._write_persona(
            self.persona_a, "Persona A", self.slug_a, f"resumes/{self.cv_a.name}", sha256_file(self.cv_a), "Applied AI Engineer"
        )
        rc, _ = self._run_profile_build("--persona", self.persona_a, "--finalize")
        self.assertEqual(rc, 0)
        index = self._read_index()
        self.assertEqual(index["active_persona"], self.persona_a)
        self.assertEqual(set(index["personas"]), {self.persona_a})
        self.assertEqual(index["personas"][self.persona_a]["resumes"], [self.slug_a])

    def test_finalize_b_registers_both_active_b(self):
        self._write_persona(
            self.persona_a, "Persona A", self.slug_a, f"resumes/{self.cv_a.name}", sha256_file(self.cv_a), "Applied AI Engineer"
        )
        self._run_profile_build("--persona", self.persona_a, "--finalize")
        self._write_persona(
            self.persona_b, "Persona B", self.slug_b, f"resumes/{self.cv_b.name}", sha256_file(self.cv_b), "ML Backend Engineer"
        )
        rc, _ = self._run_profile_build("--persona", self.persona_b, "--finalize")
        self.assertEqual(rc, 0)
        index = self._read_index()
        self.assertEqual(index["active_persona"], self.persona_b)
        self.assertEqual(set(index["personas"]), {self.persona_a, self.persona_b})
        self.assertEqual(index["personas"][self.persona_b]["resumes"], [self.slug_b])

    def test_contracts_are_persona_specific(self):
        self._write_persona(
            self.persona_a, "Persona A", self.slug_a, f"resumes/{self.cv_a.name}", sha256_file(self.cv_a), "Applied AI Engineer"
        )
        self._write_persona(
            self.persona_b, "Persona B", self.slug_b, f"resumes/{self.cv_b.name}", sha256_file(self.cv_b), "ML Backend Engineer"
        )
        inputs = {
            "identity": {"location": "Cairo, Egypt"},
            "preferences": {"locations": [{"place": "Egypt", "mode": "remote"}]},
            "search": {"portals": {}},
        }
        contract_a = profile_query.build_contract(
            make_persona(self.persona_a, "Persona A", self.slug_a, f"resumes/{self.cv_a.name}", sha256_file(self.cv_a), "Applied AI Engineer"),
            inputs,
        )
        contract_b = profile_query.build_contract(
            make_persona(self.persona_b, "Persona B", self.slug_b, f"resumes/{self.cv_b.name}", sha256_file(self.cv_b), "ML Backend Engineer"),
            inputs,
        )
        self.assertEqual({r["slug"] for r in contract_a["provenance"]["resumes"]}, {self.slug_a})
        self.assertEqual({r["slug"] for r in contract_b["provenance"]["resumes"]}, {self.slug_b})
        roles_a = {r["title"] for r in contract_a["target_roles"]}
        roles_b = {r["title"] for r in contract_b["target_roles"]}
        self.assertTrue(roles_a.isdisjoint(roles_b))
        self.assertNotEqual(contract_a["search_queries"], contract_b["search_queries"])

    def test_resolve_persona_ask_and_use(self):
        self.assertEqual(
            paths.resolve_persona(None, "", [self.persona_a, self.persona_b]),
            {"action": "ask", "slug": "", "reason": "multiple"},
        )
        self.assertEqual(
            paths.resolve_persona(self.persona_b, "", [self.persona_a, self.persona_b]),
            {"action": "use", "slug": self.persona_b, "reason": "argument"},
        )

    def test_modifying_cv_a_makes_only_a_stale(self):
        self._write_persona(
            self.persona_a, "Persona A", self.slug_a, f"resumes/{self.cv_a.name}", sha256_file(self.cv_a), "Applied AI Engineer"
        )
        self._write_persona(
            self.persona_b, "Persona B", self.slug_b, f"resumes/{self.cv_b.name}", sha256_file(self.cv_b), "ML Backend Engineer"
        )
        self._run_profile_build("--persona", self.persona_a, "--finalize")
        self._run_profile_build("--persona", self.persona_b, "--finalize")

        self.cv_a.write_text("CV A modified content for RAG AI role.\n", encoding="utf-8")

        rc_a, output_a = self._run_profile_build("--persona", self.persona_a, "--check")
        rc_b, output_b = self._run_profile_build("--persona", self.persona_b, "--check")
        self.assertEqual(rc_a, 1)
        self.assertEqual(rc_b, 0)
        self.assertIn(f"resume changed since the profile was built: resumes/{self.cv_a.name}", output_a)
        self.assertNotIn(f"resume changed since the profile was built: resumes/{self.cv_b.name}", output_b)


if __name__ == "__main__":
    unittest.main()
