"""Tests for persona selection resolution and listing."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import paths
import profile_build


class TestResolvePersona(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(
            paths.resolve_persona("b", "a", ["a", "b"]),
            {"action": "use", "slug": "b", "reason": "argument"},
        )

    def test_env_when_no_explicit(self):
        self.assertEqual(
            paths.resolve_persona(None, "a", ["a", "b"]),
            {"action": "use", "slug": "a", "reason": "environment"},
        )

    def test_only_persona(self):
        self.assertEqual(
            paths.resolve_persona(None, None, ["a"]),
            {"action": "use", "slug": "a", "reason": "only-persona"},
        )

    def test_none_stops(self):
        self.assertEqual(
            paths.resolve_persona(None, None, []),
            {"action": "stop", "slug": "", "reason": "none"},
        )

    def test_multiple_asks(self):
        self.assertEqual(
            paths.resolve_persona(None, None, ["a", "b"]),
            {"action": "ask", "slug": "", "reason": "multiple"},
        )

    def test_blank_inputs_absent(self):
        self.assertEqual(
            paths.resolve_persona("  ", "   ", ["a"]),
            {"action": "use", "slug": "a", "reason": "only-persona"},
        )


class TestListPersonasOutput(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.profiles = self.tmpdir / "profiles"
        self.profiles.mkdir()
        self.index_patch = patch.object(
            profile_build, "profile_index_path", return_value=self.profiles / "index.json"
        )
        self.yaml_patch = patch.object(
            profile_build, "persona_yaml", lambda slug: self.profiles / slug / "profile.yaml"
        )
        self.list_patch = patch.object(profile_build, "list_personas", return_value=[])
        self.index_patch.start()
        self.yaml_patch.start()
        self.list_patch.start()

    def tearDown(self):
        self.index_patch.stop()
        self.yaml_patch.stop()
        self.list_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_index(self, personas, active=""):
        index = self.profiles / "index.json"
        index.write_text(
            json.dumps({"schema_version": 1, "personas": personas, "active_persona": active})
        )

    def _write_persona(self, slug, title=""):
        directory = self.profiles / slug
        directory.mkdir(parents=True)
        lines = ["persona: " + slug + "\n"]
        if title:
            lines.append("title: " + title + "\n")
        (directory / "profile.yaml").write_text("".join(lines))

    def test_empty(self):
        profile_build.list_personas.return_value = []
        self.assertEqual(profile_build.list_personas_output(), {"personas": [], "active_persona": ""})

    def test_registered_and_title(self):
        profile_build.list_personas.return_value = ["ai-llm-rag", "dir-only"]
        self._write_index({"ai-llm-rag": {}}, active="ai-llm-rag")
        self._write_persona("ai-llm-rag", "AI LLM RAG")
        self._write_persona("dir-only")
        output = profile_build.list_personas_output()
        self.assertEqual(output["active_persona"], "ai-llm-rag")
        by_slug = {entry["slug"]: entry for entry in output["personas"]}
        self.assertEqual(by_slug["ai-llm-rag"]["title"], "AI LLM RAG")
        self.assertTrue(by_slug["ai-llm-rag"]["registered"])
        self.assertFalse(by_slug["dir-only"]["registered"])
        self.assertEqual(by_slug["dir-only"]["file"], "profiles/dir-only/profile.yaml")


if __name__ == "__main__":
    unittest.main()
