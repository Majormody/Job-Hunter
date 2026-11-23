"""Tests for tools/extract_resume.py read-only inventory (--list)."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import extract_resume


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.resumes_dir = self.tmpdir / "resumes"
        self.extracted_dir = self.tmpdir / "extracted"
        self.resumes_dir.mkdir()
        self.extracted_dir.mkdir()
        self.rd_patch = patch.object(extract_resume, "resumes_dir", return_value=self.resumes_dir)
        self.ed_patch = patch.object(extract_resume, "extracted_dir", return_value=self.extracted_dir)
        self.rd_patch.start()
        self.ed_patch.start()

    def tearDown(self):
        self.rd_patch.stop()
        self.ed_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, text="content"):
        p = self.resumes_dir / name
        p.write_text(text)
        return p

    def test_empty(self):
        data = extract_resume.inventory()
        self.assertEqual(data, {"resumes": [], "stale_extracted": [], "slug_collisions": []})

    def test_one_resume(self):
        self._write("owner-a-rag-ai-v20260101.txt", "hello world")
        data = extract_resume.inventory()
        self.assertEqual(len(data["resumes"]), 1)
        entry = data["resumes"][0]
        self.assertEqual(entry["slug"], "owner-a-rag-ai-v20260101")
        self.assertTrue(entry["source"].endswith("owner-a-rag-ai-v20260101.txt"))
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertFalse(entry["extracted_present"])
        self.assertEqual(data["stale_extracted"], [])
        self.assertEqual(data["slug_collisions"], [])

    def test_stale_extracted(self):
        self.extracted_dir.joinpath("orphan.txt").write_text("old")
        data = extract_resume.inventory()
        self.assertEqual(len(data["stale_extracted"]), 1)
        self.assertTrue(data["stale_extracted"][0].endswith("orphan.txt"))

    def test_slug_collision(self):
        self._write("x--foo--v1.pdf")
        self._write("x--foo--v1.docx")
        data = extract_resume.inventory()
        self.assertEqual(len(data["slug_collisions"]), 1)
        self.assertEqual(data["slug_collisions"][0]["slug"], "x--foo--v1")
        self.assertEqual(len(data["slug_collisions"][0]["files"]), 2)
