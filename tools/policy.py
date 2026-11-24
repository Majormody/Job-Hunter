"""Shared policy constants for Job Hunter.

Kept separate from ``check_repo.py`` so that small tools can import a single
constant without pulling in the whole repository-audit module.
"""

from __future__ import annotations

# npm/bun lifecycle scripts that execute arbitrary code at install time. A portal
# CLI manifest declaring any of these is refused by the installer and flagged by
# the repository audit.
FORBIDDEN_SCRIPTS = {"preinstall", "install", "postinstall", "prepare", "prepack"}

# Paths that hold user data and must never be committed.
PII_PATHS = (
    "resumes/",
    "profiles/",
    "reports/",
    "tmp_searches/",
)

# Files that hold user data and must never be committed.
PII_FILES = (
    "salary_data.json",
    "job_search_tracker.csv",
    ".env",
)

# Required ignore rules, checked by tools/check_repo.py. Each entry is a
# gitignore pattern that must be present in the repository .gitignore.
#
# The personal input directories exclude their *contents* rather than the
# directory itself, so that a tracked README can be re-included and a fresh
# clone has the directory in place. Excluding the directory would make the
# negation impossible and leave a new user without the folders they need.
REQUIRED_IGNORE_RULES = (
    "/resumes/*",
    "/profiles/*",
    "/reports/",
    "/tmp_searches/",
    "node_modules/",
    "__pycache__/",
    ".env",
)

ALLOWED_SIGNALS = (
    "hands_on",
    "production",
    "research",
    "academic",
    "leadership",
    "cloud",
    "security",
    "data",
)

DEFAULT_CV_SECTION_ORDER = ("summary", "skills", "projects", "experience", "education")

CV_SIGNAL_ORDERS = {
    "hands_on": ("summary", "projects", "skills", "experience", "education"),
    "academic": ("summary", "education", "skills", "projects", "experience"),
    "research": ("summary", "education", "skills", "projects", "experience"),
}

CV_LIMITS = {
    "headline_chars": 80,
    "summary_chars": 480,
    "skills": 24,
    "experience": 6,
    "experience_bullets": 8,
    "projects": 8,
    "project_bullets": 8,
    "education": 6,
    "heading_chars": 120,
    "education_chars": 120,
    "bullet_chars": 220,
}

__all__ = [
    "FORBIDDEN_SCRIPTS",
    "PII_PATHS",
    "PII_FILES",
    "REQUIRED_IGNORE_RULES",
    "ALLOWED_SIGNALS",
    "DEFAULT_CV_SECTION_ORDER",
    "CV_SIGNAL_ORDERS",
    "CV_LIMITS",
]
