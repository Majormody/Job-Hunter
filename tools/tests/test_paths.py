"""Tests for tools/paths.py persona discovery."""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import paths
from paths import list_personas


class TestListPersonas(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.profiles = self.tmpdir / "profiles"
        self.profiles.mkdir()
        self.index_patch = patch.object(paths, "profile_index_path", return_value=self.profiles / "index.json")
        self.dir_patch = patch.object(paths, "personas_dir", return_value=self.profiles)
        self.index_patch.start()
        self.dir_patch.start()

    def tearDown(self):
        self.index_patch.stop()
        self.dir_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_index(self, personas):
        index = self.profiles / "index.json"
        if personas:
            index.write_text(
                json.dumps(
                    {"schema_version": 1, "personas": personas, "active_persona": sorted(personas)[0]}
                )
            )
        else:
            index.write_text(json.dumps({"schema_version": 1, "personas": {}, "active_persona": ""}))

    def _write_index_raw(self, text):
        index = self.profiles / "index.json"
        index.write_text(text)

    def _write_persona(self, slug):
        directory = self.profiles / slug
        directory.mkdir(parents=True)
        (directory / "profile.yaml").write_text("persona: " + slug + "\n")

    def test_empty(self):
        self.assertEqual(list_personas(), [])

    def test_registry_only(self):
        self._write_index({"a": {}, "b": {}})
        self.assertEqual(list_personas(), ["a", "b"])

    def test_directories_only(self):
        self._write_persona("x")
        self._write_persona("y")
        self.assertEqual(list_personas(), ["x", "y"])

    def test_union(self):
        self._write_index({"c": {}})
        self._write_persona("a")
        self._write_persona("b")
        self.assertEqual(list_personas(), ["a", "b", "c"])

    def test_registry_list_shape(self):
        self._write_index_raw(json.dumps({"schema_version": 1, "personas": ["p", "q"]}))
        self.assertEqual(list_personas(), ["p", "q"])

    def test_invalid_registry_falls_back_to_dirs(self):
        self._write_index_raw("{not json")
        self._write_persona("d")
        self.assertEqual(list_personas(), ["d"])

    def test_directory_without_profile_yaml_ignored(self):
        (self.profiles / "empty-dir").mkdir()
        self.assertEqual(list_personas(), [])


class TestReportPaths(unittest.TestCase):
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

    def test_report_timestamp_has_expected_shapes(self):
        date_dir, ts = paths.report_timestamp()
        self.assertRegex(date_dir, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}$")

    def test_report_paths_points_under_persona_date_dir(self):
        date_dir, ts = paths.report_timestamp()
        paths_dict = paths.report_paths(date_dir, ts, persona="p")
        expected = self.reports / "p" / date_dir
        self.assertEqual(paths_dict["markdown"], expected / f"jobs-{ts}.md")
        self.assertEqual(paths_dict["html"], expected / f"jobs-{ts}.html")
        self.assertEqual(paths_dict["sidecar"], expected / f"jobs-{ts}.json")
        self.assertEqual(paths_dict["date_dir"], date_dir)
        self.assertEqual(paths_dict["ts"], ts)
