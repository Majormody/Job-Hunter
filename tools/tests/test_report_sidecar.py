"""Tests for tools/report_sidecar.py."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import paths
import report_sidecar


def write_input(tmpdir: Path, jobs: list[dict]) -> Path:
    path = tmpdir / "sidecar_input.json"
    path.write_text(
        json.dumps({"persona": "p", "jobs": jobs}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class ReportSidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.reports = self.temp / "reports"
        self.patch = patch.object(
            paths,
            "reports_dir",
            lambda persona=None: self.reports / (persona or paths.DEFAULT_PERSONA),
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_paths_prints_all_report_paths(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = report_sidecar.main(["paths", "--persona", "p"])
        self.assertEqual(code, 0)
        data = json.loads(buffer.getvalue())
        self.assertRegex(data["date_dir"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(data["ts"], r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}$")
        expected = self.reports / "p" / data["date_dir"]
        self.assertEqual(Path(data["markdown"]), expected / f"jobs-{data['ts']}.md")
        self.assertEqual(Path(data["html"]), expected / f"jobs-{data['ts']}.html")
        self.assertEqual(Path(data["sidecar"]), expected / f"jobs-{data['ts']}.json")

    def test_write_creates_sidecar_and_numbers_jobs(self):
        jobs = [
            {
                "title": "AI Engineer",
                "company": "Example",
                "portal": "freehire-search",
                "score": 80,
                "url": "https://example.invalid/job/1",
                "tailored_cv_suggestions": ["lead with RAG project"],
                "emphasis_signals": ["hands_on"],
            },
            {
                "title": "Backend Engineer",
                "company": "Example",
                "portal": "jobicy-search",
                "score": 60,
                "url": "https://example.invalid/job/2",
                "tailored_cv_suggestions": [],
            },
        ]
        input_path = write_input(self.temp, jobs)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = report_sidecar.main(
                [
                    "write",
                    "--persona",
                    "p",
                    "--date-dir",
                    "2026-01-01",
                    "--ts",
                    "2026-01-01-12-00",
                    "--input",
                    str(input_path),
                ]
            )
        self.assertEqual(code, 0)
        json.loads(buffer.getvalue())
        sidecar = self.reports / "p" / "2026-01-01" / "jobs-2026-01-01-12-00.json"
        self.assertTrue(sidecar.exists())
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "report-index/v1")
        self.assertEqual(data["persona"], "p")
        self.assertEqual(data["date"], "2026-01-01")
        self.assertEqual(data["report_sidecar"], "jobs-2026-01-01-12-00.json")
        self.assertEqual([job["number"] for job in data["jobs"]], [1, 2])
        self.assertEqual(data["jobs"][0]["emphasis_signals"], ["hands_on"])
        self.assertEqual(data["jobs"][1]["emphasis_signals"], [])
        self.assertEqual(data["jobs"][1]["tailored_cv_suggestions"], [])

    def test_unknown_signal_is_rejected(self):
        jobs = [
            {
                "title": "AI Engineer",
                "company": "Example",
                "portal": "freehire-search",
                "score": 80,
                "url": "https://example.invalid/job/1",
                "emphasis_signals": ["not_a_signal"],
            }
        ]
        input_path = write_input(self.temp, jobs)
        with self.assertRaises(SystemExit):
            report_sidecar.main(
                [
                    "write",
                    "--persona",
                    "p",
                    "--date-dir",
                    "2026-01-01",
                    "--ts",
                    "2026-01-01-12-00",
                    "--input",
                    str(input_path),
                ]
            )
        sidecar = self.reports / "p" / "2026-01-01" / "jobs-2026-01-01-12-00.json"
        self.assertFalse(sidecar.exists())


if __name__ == "__main__":
    unittest.main()