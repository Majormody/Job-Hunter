"""Central path resolution for Job Hunter.

Every tool that touches the filesystem resolves its paths through this module so
the layout is defined in exactly one place.

A *persona* is one search identity: a resume variant aimed at a role family,
plus the preferences that apply to it. A persona is a directory. The active
persona is chosen by the ``JOB_HUNTER_PERSONA`` environment variable, falling
back to ``profiles/index.json`` and then to ``default``.

Layout (see docs/architecture.md):

    resumes/                      user-supplied resume files (gitignored)
    resumes/extracted/            extracted-text cache (gitignored)
    profiles/inputs.yaml          user-authored preferences (gitignored)
    profiles/index.json           persona registry (gitignored)
    profiles/<persona>/profile.yaml   derived facts with provenance (gitignored)
    profiles/<persona>/PROFILE.md     generated aggregate (gitignored)
    profiles/<persona>/state/         per-persona job state (gitignored)
    reports/<persona>/                generated reports (gitignored)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PERSONA = "default"

ENV_VAR = "JOB_HUNTER_PERSONA"

CAIRO = timezone(timedelta(hours=2))


def personas_dir() -> Path:
    """Return the directory holding persona data."""
    return ROOT / "profiles"


def profile_index_path() -> Path:
    """Return the persona registry."""
    return personas_dir() / "index.json"


def profile_inputs_path() -> Path:
    """Return the user-authored inputs file."""
    return personas_dir() / "inputs.yaml"


def list_personas() -> list[str]:
    """Return every known persona slug, sorted.

    A persona is known either when it is listed in ``profiles/index.json`` or
    when its directory contains a ``profile.yaml``. Both sources are merged so
    a newly created persona is recognized before ``--finalize`` refreshes the
    registry.
    """
    known: set[str] = set()

    index = profile_index_path()
    if index.exists():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                entries = data.get("personas")
                if isinstance(entries, dict):
                    known.update(str(key) for key in entries)
                elif isinstance(entries, list):
                    known.update(str(item) for item in entries)
        except (OSError, json.JSONDecodeError):
            pass

    if personas_dir().is_dir():
        for path in personas_dir().iterdir():
            if path.is_dir() and (path / "profile.yaml").exists():
                known.add(path.name)

    return sorted(known)


def active_persona() -> str:
    """Return the persona slug this invocation operates on.

    Resolution order: the environment variable, then ``active_persona`` in the
    registry, then ``default``. Never a guess across multiple personas - the
    caller is expected to have selected one explicitly.
    """
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env
    index = profile_index_path()
    if index.exists():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            stored = data.get("active_persona")
            if isinstance(stored, str) and stored.strip():
                return stored.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_PERSONA


def persona_dir(persona: str | None = None) -> Path:
    """Return ``profiles/<persona>``."""
    return personas_dir() / (persona or active_persona())


def persona_yaml(persona: str | None = None) -> Path:
    """Return the persona's derived-facts file."""
    return persona_dir(persona) / "profile.yaml"


def profile_file(persona: str | None = None) -> Path:
    """Return the persona's generated profile aggregate."""
    return persona_dir(persona) / "PROFILE.md"


def state_dir(persona: str | None = None) -> Path:
    """Return the persona's state directory."""
    return persona_dir(persona) / "state"


def seen_jobs_path(persona: str | None = None) -> Path:
    """Return the persona's seen-jobs store."""
    return state_dir(persona) / "seen_jobs.json"


def tracker_path(persona: str | None = None) -> Path:
    """Return the persona's application tracker."""
    return state_dir(persona) / "tracker.csv"


def search_queries_path(persona: str | None = None) -> Path:
    """Return the persona's generated search-queries file."""
    return state_dir(persona) / "search-queries.md"


def scratch_dir(persona: str | None = None) -> Path:
    """Return the persona's scratch directory for run intermediates."""
    return state_dir(persona) / "scratch"


def reports_dir(persona: str | None = None) -> Path:
    """Return the persona's report output directory."""
    return ROOT / "reports" / (persona or active_persona())


def report_timestamp(now: datetime | None = None) -> tuple[str, str]:
    """Return Cairo ``(date_dir, ts)`` for report file names."""
    now = now or datetime.now(CAIRO)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d-%H-%M")


def report_date_dir(date_dir: str, persona: str | None = None) -> Path:
    """Return ``reports/<persona>/<date_dir>``."""
    return reports_dir(persona) / date_dir


def report_md_path(date_dir: str, ts: str, persona: str | None = None) -> Path:
    """Return ``reports/<persona>/<date_dir>/jobs-<ts>.md``."""
    return report_date_dir(date_dir, persona) / f"jobs-{ts}.md"


def report_html_path(date_dir: str, ts: str, persona: str | None = None) -> Path:
    """Return ``reports/<persona>/<date_dir>/jobs-<ts>.html``."""
    return report_date_dir(date_dir, persona) / f"jobs-{ts}.html"


def report_sidecar_path(date_dir: str, ts: str, persona: str | None = None) -> Path:
    """Return ``reports/<persona>/<date_dir>/jobs-<ts>.json``."""
    return report_date_dir(date_dir, persona) / f"jobs-{ts}.json"


def report_paths(date_dir: str, ts: str, persona: str | None = None) -> dict[str, Path]:
    """Return all report paths for a timestamp."""
    return {
        "date_dir": date_dir,
        "ts": ts,
        "markdown": report_md_path(date_dir, ts, persona),
        "html": report_html_path(date_dir, ts, persona),
        "sidecar": report_sidecar_path(date_dir, ts, persona),
    }


def resumes_dir() -> Path:
    """Return the directory holding user resumes."""
    return ROOT / "resumes"


def extracted_dir() -> Path:
    """Return the extracted-text cache directory."""
    return resumes_dir() / "extracted"


def ensure_persona_dirs(persona: str | None = None) -> None:
    """Create the directories a run needs. Safe to call repeatedly."""
    for directory in (state_dir(persona), scratch_dir(persona), reports_dir(persona), extracted_dir()):
        directory.mkdir(parents=True, exist_ok=True)


def job_hunter_data_dir() -> Path:
    """Return the Job Hunter data directory.

    Resolution order:
    1. JOB_HUNTER_DATA_DIR environment variable
    2. XDG_DATA_HOME/job-hunter (Linux/Unix)
    3. ~/Library/Application Support/job-hunter (macOS)
    4. %APPDATA%/job-hunter (Windows)
    5. ~/.local/share/job-hunter (fallback)
    """
    env = os.environ.get("JOB_HUNTER_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "job-hunter"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / "job-hunter"
        return Path.home() / "AppData" / "Local" / "job-hunter"

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "job-hunter"
    return Path.home() / ".local" / "share" / "job-hunter"


def job_hunter_db_path(major: int | str) -> Path:
    """Return the OpenCode database path for the given major version.

    The database lives at <data_dir>/v<major>/opencode/opencode.db
    which is where OpenCode expects it when XDG_DATA_HOME is set to <data_dir>/v<major>.
    """
    data_dir = job_hunter_data_dir()
    major_str = str(major)
    return data_dir / f"v{major_str}" / "opencode" / "opencode.db"


def cv_dir(persona: str | None = None, date_dir: str = "", company_slug: str = "") -> Path:
    return reports_dir(persona) / date_dir / "Customized_CV" / company_slug


def cv_tex_path(persona: str | None = None, date_dir: str = "", company_slug: str = "", name_slug: str = "") -> Path:
    return cv_dir(persona, date_dir, company_slug) / f"{name_slug}.tex"


def cv_pdf_path(persona: str | None = None, date_dir: str = "", company_slug: str = "", name_slug: str = "") -> Path:
    return cv_dir(persona, date_dir, company_slug) / f"{name_slug}.pdf"


def cv_log_path(persona: str | None = None, date_dir: str = "", company_slug: str = "", name_slug: str = "") -> Path:
    return cv_dir(persona, date_dir, company_slug) / f"{name_slug}.log"


def cv_paths(persona: str | None = None, date_dir: str = "", company_slug: str = "", name_slug: str = "") -> dict[str, Path]:
    directory = cv_dir(persona, date_dir, company_slug)
    return {
        "dir": directory,
        "tex": cv_tex_path(persona, date_dir, company_slug, name_slug),
        "pdf": cv_pdf_path(persona, date_dir, company_slug, name_slug),
        "log": cv_log_path(persona, date_dir, company_slug, name_slug),
    }


def resolve_persona(explicit: str | None, env_value: str | None, known: list[str]) -> dict:
    """Resolve the persona slug with precedence: explicit -> env -> single known -> stop/ask.

    Returns ``{"action": "use"|"ask"|"stop", "slug": "...", "reason": "..."}``.
    Blank inputs are treated as absent. For ``ask`` and ``stop`` the slug is empty.
    """
    explicit_clean = explicit.strip() if explicit else ""
    env_clean = env_value.strip() if env_value else ""

    if explicit_clean:
        return {"action": "use", "slug": explicit_clean, "reason": "argument"}
    if env_clean:
        return {"action": "use", "slug": env_clean, "reason": "environment"}
    if len(known) == 1:
        return {"action": "use", "slug": known[0], "reason": "only-persona"}
    if not known:
        return {"action": "stop", "slug": "", "reason": "none"}
    return {"action": "ask", "slug": "", "reason": "multiple"}


__all__ = [
    "ROOT",
    "DEFAULT_PERSONA",
    "ENV_VAR",
    "personas_dir",
    "profile_index_path",
    "profile_inputs_path",
    "list_personas",
    "active_persona",
    "persona_dir",
    "persona_yaml",
    "profile_file",
    "state_dir",
    "seen_jobs_path",
    "tracker_path",
    "search_queries_path",
    "scratch_dir",
    "reports_dir",
    "report_timestamp",
    "report_date_dir",
    "report_md_path",
    "report_html_path",
    "report_sidecar_path",
    "report_paths",
    "resumes_dir",
    "extracted_dir",
    "cv_dir",
    "cv_tex_path",
    "cv_pdf_path",
    "cv_log_path",
    "cv_paths",
    "resolve_persona",
]
