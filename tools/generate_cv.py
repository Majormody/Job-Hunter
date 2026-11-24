#!/usr/bin/env python3
"""Generate a deterministic, evidence-anchored CV and compile it to PDF.

Inputs:

- ``profiles/<persona>/inputs.yaml`` -- name/contact details (tool-owned header)
- ``profiles/<persona>/profile.yaml`` -- flattened fact catalog source
- A report sidecar ``jobs-<ts>.json`` for job number + emphasis signals
- A ``cv-plan/v1`` plan produced by cv-writer and a ``cv-verdict/v1`` verdict

Outputs:

- ``reports/<persona>/<date>/Customized_CV/<company-slug>/<name>.pdf``
- matching ``.tex`` and ``.log`` files in the same directory

Nothing in this tool applies to jobs, browses postings, or invents facts.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import yaml
except ImportError:
    print("generate_cv: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

from paths import (  # noqa: E402
    CAIRO,
    ROOT,
    profile_inputs_path,
    persona_yaml,
    report_sidecar_path,
    cv_paths,
)
from policy import (  # noqa: E402
    ALLOWED_SIGNALS,
    DEFAULT_CV_SECTION_ORDER,
    CV_LIMITS,
)
from location_gate import identity_location  # noqa: E402

TEMPLATE_PATH = ROOT / "templates" / "CV_PATTERN.tex"

TEX_SPECIAL = str.maketrans(
    {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
)


def die(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    return 1


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def whitespace_normalize(text: str) -> str:
    return " ".join(str(text).split())


def _entry_value(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("value") or entry.get("heading") or entry.get("text")
    if isinstance(entry, str):
        return entry
    return None


def _entry_source(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("source") or entry.get("evidence")
    return None


def evidence_line_numbers(evidence: str | None) -> set[int]:
    if not isinstance(evidence, str) or "#" not in evidence:
        return set()
    fragment = evidence.split("#", 1)[1]
    numbers: set[int] = set()
    for part in fragment.split(","):
        match = re.fullmatch(r"L?(\d+)(?:\s*-\s*L?(\d+))?", part.strip(), re.IGNORECASE)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end >= start:
            numbers.update(range(start, end + 1))
    return numbers


def infer_bullet_owners(profile: dict) -> dict[int, str]:
    owners: dict[int, str] = {}
    bullets = profile.get("evidence_bullets", []) or []
    projects = profile.get("projects", []) or []
    experiences = profile.get("experience", []) or []
    for index, bullet in enumerate(bullets):
        if not isinstance(bullet, dict):
            continue
        lines = evidence_line_numbers(bullet.get("source") or bullet.get("evidence"))
        if not lines:
            continue
        best_owner = ""
        best_overlap = 0
        for section, entries in (("project", projects), ("experience", experiences)):
            for entry_index, entry in enumerate(entries or []):
                if not isinstance(entry, dict):
                    continue
                entry_lines = evidence_line_numbers(entry.get("evidence") or entry.get("source"))
                overlap = len(lines & entry_lines)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_owner = f"{section}:{entry_index}"
        if best_owner:
            owners[index] = best_owner
    return owners


def slugify(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "unknown"


def escape_tex(text: str) -> str:
    return whitespace_normalize(text).translate(TEX_SPECIAL)


def validate_plan(plan: dict, facts: dict, job: dict, persona: str) -> list[str]:
    """Run deterministic structural checks. Semantic paraphrase belongs to cv-verifier."""
    violations: list[str] = []

    if not isinstance(plan, dict):
        return ["plan is not a JSON object"]
    if plan.get("schema") != "cv-plan/v1":
        violations.append("schema must be cv-plan/v1")
    if plan.get("status") != "ok":
        violations.append("status must be ok")
    if plan.get("persona") != persona:
        violations.append(f"persona must be {persona}")
    if plan.get("job_number") != job.get("number"):
        violations.append("job_number does not match sidecar job number")

    if not isinstance(facts, dict) or facts.get("schema") != "fact-catalog/v1":
        violations.append("facts must be fact-catalog/v1")
    fact_by_id: dict[str, dict] = {}
    for fact in facts.get("facts", []) or []:
        if isinstance(fact, dict) and isinstance(fact.get("id"), str):
            fact_by_id[fact["id"]] = fact

    def check_source_ids(path: str, ids: list, kinds: tuple[str, ...], exactly_one: bool) -> None:
        if not isinstance(ids, list) or (exactly_one and len(ids) != 1) or (not exactly_one and len(ids) < 1):
            violations.append(f"{path}: source_ids must contain exactly one id" if exactly_one else f"{path}: source_ids must contain one or more ids")
            return
        for ref in ids:
            fact = fact_by_id.get(ref)
            if fact is None:
                violations.append(f"{path}: unknown source id {ref!r}")
            elif fact.get("kind") not in kinds:
                violations.append(f"{path}: {ref!r} has kind {fact.get('kind')!r}, expected one of {kinds}")

    headline = plan.get("headline")
    if not isinstance(headline, dict) or headline.get("op") != "select":
        violations.append("headline must be select-only")
    else:
        check_source_ids("headline", headline.get("source_ids", []), ("role",), True)
        if isinstance(headline.get("text"), str) and len(headline["text"]) > CV_LIMITS["headline_chars"]:
            violations.append(f"headline.text exceeds {CV_LIMITS['headline_chars']} chars")

    summary = plan.get("summary")
    if not isinstance(summary, dict) or summary.get("op") != "select":
        violations.append("summary must be select-only")
    else:
        check_source_ids("summary", summary.get("source_ids", []), ("summary",), True)
        summary_refs = summary.get("source_ids", [])
        if isinstance(summary_refs, list) and len(summary_refs) == 1:
            summary_fact = fact_by_id.get(summary_refs[0])
            if isinstance(summary_fact, dict) and isinstance(summary.get("text"), str):
                if whitespace_normalize(summary_fact.get("text", "")) != whitespace_normalize(summary["text"]):
                    violations.append("summary.text must match the cited summary fact")
        if isinstance(summary.get("text"), str) and len(summary["text"]) > CV_LIMITS["summary_chars"]:
            violations.append(f"summary.text exceeds {CV_LIMITS['summary_chars']} chars")

    def section_list(key: str, select_kinds: tuple[str, ...], bullet_kinds: tuple[str, ...], max_count: int, max_bullets: int = CV_LIMITS["experience_bullets"]) -> None:
        items = plan.get(key, [])
        if not isinstance(items, list):
            violations.append(f"{key} must be a list")
            return
        if len(items) > max_count:
            violations.append(f"{key} has more than {max_count} entries")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                violations.append(f"{key}[{index}] is not a mapping")
                continue
            heading = item.get("heading")
            if heading is not None:
                if not isinstance(heading, dict) or heading.get("op") != "select":
                    violations.append(f"{key}[{index}].heading must be select-only")
                else:
                    check_source_ids(f"{key}[{index}].heading", heading.get("source_ids", []), select_kinds, True)
                    if isinstance(heading.get("text"), str) and len(heading["text"]) > CV_LIMITS["heading_chars"]:
                        violations.append(f"{key}[{index}].heading.text exceeds {CV_LIMITS['heading_chars']} chars")
            bullets = item.get("bullets", [])
            if not isinstance(bullets, list):
                violations.append(f"{key}[{index}].bullets must be a list")
                continue
            if len(bullets) > max_bullets:
                violations.append(f"{key}[{index}].bullets has more than {max_bullets} items")
            for bullet_index, bullet in enumerate(bullets):
                if not isinstance(bullet, dict) or bullet.get("op") != "rewrite":
                    violations.append(f"{key}[{index}].bullets[{bullet_index}] must be rewrite")
                    continue
                check_source_ids(
                    f"{key}[{index}].bullets[{bullet_index}]", bullet.get("source_ids", []), bullet_kinds, False
                )
                if key in ("experience", "projects") and isinstance(heading, dict):
                    heading_refs = heading.get("source_ids", [])
                    if isinstance(heading_refs, list) and heading_refs:
                        expected_owner = re.sub(r":(heading|name)$", "", str(heading_refs[0]))
                        for ref in bullet.get("source_ids", []) or []:
                            cited_fact = fact_by_id.get(ref)
                            owner = cited_fact.get("owner") if isinstance(cited_fact, dict) else None
                            if isinstance(owner, str) and owner.strip() and owner != expected_owner:
                                violations.append(
                                    f"{key}[{index}].bullets[{bullet_index}]: {ref} is owned by {owner}, expected {expected_owner}"
                                )
                if isinstance(bullet.get("text"), str) and len(bullet["text"]) > CV_LIMITS["bullet_chars"]:
                    violations.append(f"{key}[{index}].bullets[{bullet_index}].text exceeds {CV_LIMITS['bullet_chars']} chars")

    section_list("skills", ("skill",), (), CV_LIMITS["skills"])
    section_list("experience", ("experience",), ("experience", "bullet"), CV_LIMITS["experience"], CV_LIMITS["experience_bullets"])
    section_list("projects", ("project",), ("project", "bullet"), CV_LIMITS["projects"], CV_LIMITS["project_bullets"])

    education = plan.get("education", [])
    if not isinstance(education, list):
        violations.append("education must be a list")
    else:
        if len(education) > CV_LIMITS["education"]:
            violations.append("education has more than 6 entries")
        for index, item in enumerate(education):
            if not isinstance(item, dict) or item.get("op") != "select":
                violations.append(f"education[{index}] must be select-only")
                continue
            check_source_ids(f"education[{index}]", item.get("source_ids", []), ("education",), True)
            if isinstance(item.get("text"), str) and len(item["text"]) > CV_LIMITS["education_chars"]:
                violations.append(f"education[{index}].text exceeds {CV_LIMITS['education_chars']} chars")

    order = plan.get("section_order")
    if not isinstance(order, list):
        violations.append("section_order must be a list")
    else:
        seen = set()
        for section in order:
            if section not in DEFAULT_CV_SECTION_ORDER:
                violations.append(f"unknown section {section!r}")
            elif section in seen:
                violations.append(f"duplicate section {section!r}")
            else:
                seen.add(section)
        if order and order[0] != "summary":
            violations.append("section_order must start with summary")
        for section in ("summary", "skills", "experience", "projects", "education"):
            if plan.get(section) and section not in order:
                violations.append(f"{section} has items but is not in section_order")

    signals = plan.get("order_reason", {}).get("signals", []) if isinstance(plan.get("order_reason"), dict) else []
    if not isinstance(signals, list) or any(sig not in ALLOWED_SIGNALS for sig in signals):
        violations.append("order_reason.signals must be a subset of allowed signals")
    job_signals = job.get("emphasis_signals", [])
    if not set(signals or []).issubset(set(job_signals)):
        violations.append("order_reason.signals must be a subset of job emphasis_signals")

    content_kinds = {"summary", "skill", "bullet", "project", "experience", "education"}
    content_ids = {
        fact["id"]
        for fact in facts.get("facts", [])
        if isinstance(fact, dict) and isinstance(fact.get("id"), str) and fact.get("kind") in content_kinds
    }
    referenced_ids: set[str] = set()

    def collect(ids) -> None:
        if isinstance(ids, list):
            for ref in ids:
                if isinstance(ref, str):
                    referenced_ids.add(ref)

    headline = plan.get("headline", {})
    if isinstance(headline, dict):
        collect(headline.get("source_ids"))
    summary = plan.get("summary", {})
    if isinstance(summary, dict):
        collect(summary.get("source_ids"))
    for key in ("skills", "experience", "projects", "education"):
        items = plan.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            heading = item.get("heading")
            if isinstance(heading, dict):
                collect(heading.get("source_ids"))
            if key == "skills":
                collect(item.get("source_ids"))
            for bullet in item.get("bullets", []) or []:
                if isinstance(bullet, dict):
                    collect(bullet.get("source_ids"))
            if key == "education":
                collect(item.get("source_ids"))

    missing = sorted(content_ids - referenced_ids)
    if missing:
        violations.append(f"unreferenced content facts: {', '.join(missing)}")

    summary_text = whitespace_normalize(summary.get("text", "")) if isinstance(summary, dict) else ""
    if summary_text:
        bullet_texts = [
            whitespace_normalize(fact.get("text", ""))
            for fact in facts.get("facts", [])
            if isinstance(fact, dict) and fact.get("kind") == "bullet"
        ]
        for key in ("experience", "projects"):
            for item in plan.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                for bullet in item.get("bullets", []) or []:
                    if isinstance(bullet, dict) and isinstance(bullet.get("text"), str):
                        bullet_texts.append(whitespace_normalize(bullet["text"]))
        if summary_text in bullet_texts:
            violations.append("summary.text duplicates bullet text")

    return violations


def is_unapproved_verdict(verdict: dict) -> bool:
    if not isinstance(verdict, dict):
        return True
    if verdict.get("schema") != "cv-verdict/v1":
        return True
    if verdict.get("approved") is not True:
        return True
    violations = verdict.get("violations")
    if not isinstance(violations, list) or violations:
        return True
    return False


def build_facts(persona: str) -> dict:
    profile = load_yaml(persona_yaml(persona))
    inputs = load_yaml(profile_inputs_path())
    facts: list[dict] = []

    def add(
        text: str,
        fact_id: str,
        kind: str,
        evidence: str | None,
        owner: str | None = None,
        weight: str | None = None,
    ) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        fact = {
            "id": fact_id,
            "kind": kind,
            "text": whitespace_normalize(text),
            "evidence": evidence or "",
        }
        if owner:
            fact["owner"] = owner
        if weight:
            fact["weight"] = weight
        facts.append(fact)

    resume_summary = profile.get("resume_summary")
    if isinstance(resume_summary, dict) and resume_summary.get("value"):
        add(resume_summary["value"], "summary:0", "summary", resume_summary.get("source"))
    elif isinstance(resume_summary, str) and resume_summary.strip():
        add(resume_summary, "summary:0", "summary", None)

    roles = profile.get("target_roles", []) or []
    roles_sorted = sorted(
        [role for role in roles if isinstance(role, dict) and role.get("title")],
        key=lambda role: role.get("priority", 999),
    )
    for index, role in enumerate(roles_sorted):
        add(role["title"], f"role:{index}", "role", role.get("evidence"))

    skills = profile.get("skills", []) or []
    for index, skill in enumerate(skills):
        if isinstance(skill, dict) and skill.get("name"):
            add(skill["name"], f"skill:{index}", "skill", skill.get("evidence"), weight=skill.get("weight"))

    bullet_owners = infer_bullet_owners(profile)
    bullets = profile.get("evidence_bullets", []) or []
    for index, bullet in enumerate(bullets):
        if isinstance(bullet, dict) and bullet.get("text"):
            add(
                bullet["text"],
                f"bullet:{index}",
                "bullet",
                bullet.get("source"),
                owner=bullet_owners.get(index),
            )

    projects = profile.get("projects", []) or []
    for index, project in enumerate(projects):
        if not isinstance(project, dict):
            continue
        name = project.get("name")
        detail = project.get("detail")
        if isinstance(name, str) and name.strip():
            add(name, f"project:{index}:name", "project", project.get("evidence"))
        if isinstance(detail, str) and detail.strip():
            add(detail, f"project:{index}:detail", "project", project.get("evidence"))

    experiences = profile.get("experience", []) or []
    for index, entry in enumerate(experiences):
        if not isinstance(entry, dict):
            continue
        heading = _entry_value(entry)
        detail = entry.get("detail")
        if isinstance(heading, str) and heading.strip():
            add(heading, f"experience:{index}:heading", "experience", _entry_source(entry))
        if isinstance(detail, str) and detail.strip():
            add(detail, f"experience:{index}:detail", "experience", _entry_source(entry))

    education = profile.get("education", []) or []
    for index, entry in enumerate(education):
        if isinstance(entry, str) and entry.strip():
            add(entry, f"education:{index}", "education", None)
        elif isinstance(entry, dict):
            text = entry.get("value") or entry.get("text")
            if isinstance(text, str) and text.strip():
                add(text, f"education:{index}", "education", _entry_source(entry))

    return {
        "schema": "fact-catalog/v1",
        "persona": persona,
        "title": profile.get("title", ""),
        "inputs": str(profile_inputs_path()),
        "facts": facts,
    }


def load_job_from_sidecar(sidecar_path: Path, job_number: int) -> dict:
    sidecar = load_json(sidecar_path)
    if sidecar.get("schema") != "report-index/v1":
        raise ValueError(f"{sidecar_path} is not report-index/v1")
    persona = sidecar.get("persona")
    if not isinstance(persona, str) or not persona.strip():
        raise ValueError("sidecar missing persona")
    jobs = sidecar.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("sidecar jobs must be a list")
    for job in jobs:
        if isinstance(job, dict) and job.get("number") == job_number:
            return job
    raise ValueError(f"job number {job_number} not found in {sidecar_path}")


def render_section_block(section: str, items: list) -> str:
    lines: list[str] = []
    if section == "skills":
        skill_names = []
        for item in items:
            if isinstance(item, dict):
                skill_names.append(item.get("text", ""))
        if skill_names:
            lines.append(r"\noindent\textbf{Technical Skills:} " + r" \CVSep ".join(escape_tex(name) for name in skill_names) + r"\par")
    elif section == "experience":
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            heading = escape_tex(item.get("heading", {}).get("text", ""))
            macro = "\\CVFirstProjectHeading" if index == 0 else "\\CVProjectHeading"
            lines.append(f"{macro}{{{heading}}}{{}}")
            for bullet in item.get("bullets", []) or []:
                lines.append(f"\\begin{{CVBullets}}\\item {escape_tex(bullet.get('text',''))}\\end{{CVBullets}}")
    elif section == "projects":
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            heading = escape_tex(item.get("heading", {}).get("text", ""))
            macro = "\\CVFirstProjectHeading" if index == 0 else "\\CVProjectHeading"
            lines.append(f"{macro}{{{heading}}}{{}}")
            for bullet in item.get("bullets", []) or []:
                lines.append(f"\\begin{{CVBullets}}\\item {escape_tex(bullet.get('text',''))}\\end{{CVBullets}}")
    elif section == "education":
        for index, item in enumerate(items):
            text = escape_tex(item.get("text", "")) if isinstance(item, dict) else escape_tex(str(item))
            macro = "\\CVFirstProjectHeading" if index == 0 else "\\CVProjectHeading"
            lines.append(f"{macro}{{{text}}}{{}}")
    return "\n".join(lines)


def render_latex(plan: dict, header_text: str, contact_parts: list[str] | str) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    sections = plan.get("section_order", [])
    blocks: list[str] = []
    for section in sections:
        items = plan.get(section, [])
        if not items:
            continue
        title_map = {
            "skills": "Technical Skills",
            "experience": "Experience",
            "projects": "Projects",
            "education": "Education",
        }
        title = title_map.get(section, section.capitalize())
        blocks.append(r"\CVSection{" + escape_tex(title) + r"}")
        summary = plan.get("summary")
        if section == "summary" and isinstance(summary, dict):
            blocks.append(f"\\CVText{{{escape_tex(summary.get('text',''))}}}")
        blocks.append(render_section_block(section, items))
    if isinstance(contact_parts, list):
        contact_arg = r" \CVSep ".join(contact_parts)
    else:
        contact_arg = escape_tex(str(contact_parts))
    latex = template.replace("@@HEADER@@", r"\CVHeader{" + escape_tex(header_text) + r"}{" + escape_tex(plan.get("headline", {}).get("text", "")) + r"}{" + contact_arg + r"}")
    latex = latex.replace("@@SECTIONS@@", "\n".join(blocks))
    return latex


def cmd_facts(args: argparse.Namespace) -> int:
    persona = args.persona
    catalog = build_facts(persona)
    output = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(json.dumps({"out": str(out_path), "facts": len(catalog["facts"])}, ensure_ascii=False))
    else:
        print(output, end="")
    return 0


def cmd_reports(args: argparse.Namespace) -> int:
    persona = args.persona
    from paths import reports_dir

    base = reports_dir(persona)
    entries: list[dict] = []
    if base.is_dir():
        for date_dir in sorted(base.iterdir()):
            if not date_dir.is_dir():
                continue
            for sidecar in sorted(date_dir.glob("jobs-*.json")):
                try:
                    data = load_json(sidecar)
                except ValueError:
                    continue
                jobs = data.get("jobs", []) if isinstance(data, dict) else []
                entries.append(
                    {
                        "date": data.get("date"),
                        "ts": data.get("ts", "").replace(".json", ""),
                        "persona": data.get("persona"),
                        "sidecar": str(sidecar),
                        "jobs": len(jobs) if isinstance(jobs, list) else 0,
                    }
                )
    print(json.dumps({"persona": persona, "reports": entries}, ensure_ascii=False, indent=2))
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    sidecar_path = Path(args.sidecar)
    if not sidecar_path.exists():
        return die(f"sidecar not found: {sidecar_path}")
    sidecar = load_json(sidecar_path)
    jobs = sidecar.get("jobs", []) if isinstance(sidecar, dict) else []
    if not isinstance(jobs, list):
        return die("sidecar jobs must be a list")
    output = [
        {
            "number": job.get("number"),
            "title": job.get("title"),
            "company": job.get("company"),
            "portal": job.get("portal"),
            "score": job.get("score"),
            "emphasis_signals": job.get("emphasis_signals", []),
        }
        for job in jobs
    ]
    print(json.dumps({"sidecar": str(sidecar_path), "jobs": output}, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    sidecar_path = Path(args.sidecar)
    plan_path = Path(args.plan)
    facts_path = Path(args.facts)
    sidecar = load_json(sidecar_path)
    job = load_job_from_sidecar(sidecar_path, args.job_number)
    facts = load_json(facts_path)
    plan = load_json(plan_path)
    persona = sidecar.get("persona", "")
    violations = validate_plan(plan, facts, job, persona)
    verdict = {
        "schema": "cv-verdict/v1",
        "approved": not violations,
        "violations": [
            {"path": "plan", "result": "fail", "reason": violation} for violation in violations
        ],
        "checks": [
            {"path": "structure", "result": "pass" if not violations else "fail", "reason": "deterministic plan checks"}
        ],
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


def contact_parts(inputs: dict, profile: dict) -> list[str]:
    identity = inputs.get("identity", {}) if isinstance(inputs, dict) else {}
    parts: list[str] = []
    location = identity_location(inputs, profile)
    if location:
        parts.append(escape_tex(location))
    email = identity.get("email")
    phone = identity.get("phone")
    links = identity.get("links", {}) if isinstance(identity.get("links"), dict) else {}
    if isinstance(email, str) and email.strip():
        parts.append(escape_tex(email.strip()))
    if isinstance(phone, str) and phone.strip():
        parts.append(escape_tex(phone.strip()))
    for label, value in links.items():
        if isinstance(value, str) and value.strip():
            parts.append(escape_tex(f"{label}: {value.strip()}"))
    return parts


def contact_line(inputs: dict, profile: dict) -> str:
    parts = contact_parts(inputs, profile)
    return r" \CVSep ".join(parts) if parts else ""


def header_name(inputs: dict, profile: dict) -> str:
    identity = inputs.get("identity", {}) if isinstance(inputs, dict) else {}
    if isinstance(identity.get("name"), str) and identity["name"].strip():
        return identity["name"].strip()
    return profile.get("title", "")


CV_JUNIOR_TOKENS = (
    "junior", "jr.", "jr", "entry", "entry-level", "entry level",
    "graduate", "fresher", "new grad", "early career", "trainee",
    "intern", "internship", "associate", "0-1 years", "0-2 years",
    "0-1", "0-2",
)
CV_MID_TOKENS = (
    "mid", "middle", "mid-level", "mid level", "mid-senior", "mid/senior",
    "intermediate", "ii", "3+ years", "4+ years", "5+ years",
)
CV_SENIOR_TOKENS = (
    "senior", "sr.", "sr", "staff", "principal", "lead",
    "manager", "director", "head of", "architect",
)


def infer_cv_page_policy(facts: dict) -> dict:
    text = " ".join([facts.get("title", "")] + [fact.get("text", "") for fact in facts.get("facts", []) if fact.get("kind") == "role"]).lower()
    if any(token in text for token in CV_SENIOR_TOKENS):
        return {"seniority": "senior", "max_pages": 2}
    if any(token in text for token in CV_MID_TOKENS):
        return {"seniority": "mid", "max_pages": 2}
    if any(token in text for token in CV_JUNIOR_TOKENS):
        return {"seniority": "junior", "max_pages": 1}
    return {"seniority": "junior", "max_pages": 1}


def parse_lualatex_pages(stdout: str) -> int | None:
    match = re.search(r"Output written on [^\n]*\((\d+)\s+pages?", stdout)
    return int(match.group(1)) if match else None


CV_TRIM_MIN_SKILLS = 8
CV_TRIM_MIN_BULLETS_PER_ENTRY = 1
SKILL_TRIM_PRIORITY = {"primary": 0, "secondary": 1, "weak": 2}


def compile_cv_tex(paths: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "lualatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(paths["dir"]),
            str(paths["tex"]),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


def write_build_log(
    paths: dict,
    persona: str,
    job: dict,
    result: subprocess.CompletedProcess,
    pages: int | None,
    page_policy: dict,
    extra: dict | None,
) -> None:
    extra_text = "".join(f"{key}={value}\n" for key, value in (extra or {}).items())
    log_text = (
        f"generate_cv build log\n"
        f"persona={persona}\n"
        f"job_number={job.get('number')}\n"
        f"company={job.get('company')}\n"
        f"tex={paths['tex']}\n"
        f"exit_code={result.returncode}\n"
        f"pages={pages}\n"
        f"cv_page_policy={page_policy}\n"
        f"{extra_text}"
        f"--- lualatex stdout ---\n{result.stdout}\n"
        f"--- lualatex stderr ---\n{result.stderr}\n"
    )
    paths["log"].write_text(log_text, encoding="utf-8")


def trim_plan_for_page_fit(plan: dict, facts: dict) -> tuple[dict, list[dict]]:
    trimmed = json.loads(json.dumps(plan))
    fact_by_id = {
        fact["id"]: fact
        for fact in facts.get("facts", [])
        if isinstance(fact, dict) and isinstance(fact.get("id"), str)
    }
    removed: list[dict] = []

    def skill_priority(item: dict) -> int:
        refs = item.get("source_ids", []) if isinstance(item, dict) else []
        ref = refs[0] if isinstance(refs, list) and refs else ""
        fact = fact_by_id.get(ref, {})
        return SKILL_TRIM_PRIORITY.get(fact.get("weight"), 3)

    skills = trimmed.get("skills", [])
    if isinstance(skills, list):
        while len(skills) > CV_TRIM_MIN_SKILLS:
            drop_index = max(range(len(skills)), key=lambda i: (skill_priority(skills[i]), i))
            item = skills.pop(drop_index)
            refs = item.get("source_ids", []) if isinstance(item, dict) else []
            removed.append(
                {
                    "section": "skills",
                    "index": drop_index,
                    "source_ids": refs,
                    "reason": "lowest-priority skill",
                }
            )
        trimmed["skills"] = skills

    for section in ("projects", "experience"):
        items = trimmed.get(section, [])
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            bullets = item.get("bullets", [])
            if not isinstance(bullets, list):
                continue
            while len(bullets) > CV_TRIM_MIN_BULLETS_PER_ENTRY:
                bullet = bullets.pop()
                refs = bullet.get("source_ids", []) if isinstance(bullet, dict) else []
                removed.append(
                    {
                        "section": section,
                        "index": index,
                        "source_ids": refs,
                        "reason": "overflow trimming kept first bullet per entry",
                    }
                )
            item["bullets"] = bullets
        while len(items) > 1:
            item = items.pop()
            heading = item.get("heading", {}) if isinstance(item, dict) else {}
            refs = heading.get("source_ids", []) if isinstance(heading, dict) else []
            removed.append(
                {
                    "section": section,
                    "index": len(items),
                    "source_ids": refs,
                    "reason": "overflow trimming kept first entry per section",
                }
            )
        trimmed[section] = items

    return trimmed, removed


def cmd_render(args: argparse.Namespace, build_pdf: bool = False) -> int:
    sidecar_path = Path(args.sidecar)
    plan_path = Path(args.plan)
    facts_path = Path(args.facts)
    verdict_path = Path(args.verdict)

    sidecar = load_json(sidecar_path)
    if not isinstance(sidecar, dict) or sidecar.get("schema") != "report-index/v1":
        return die(f"{sidecar_path} is not report-index/v1")
    persona = sidecar.get("persona", "")
    if not persona:
        return die("sidecar missing persona")
    job = load_job_from_sidecar(sidecar_path, args.job_number)
    facts = load_json(facts_path)
    plan = load_json(plan_path)

    verdict = load_json(verdict_path)
    if is_unapproved_verdict(verdict):
        return die("refusing to render without an approved cv-verdict/v1")

    violations = validate_plan(plan, facts, job, persona)
    if violations:
        return die("deterministic checks failed: " + "; ".join(violations))

    profile = load_yaml(persona_yaml(persona))
    inputs = load_yaml(profile_inputs_path())
    company_slug = slugify(job.get("company", ""))
    name_slug = slugify(header_name(inputs, profile))
    paths = cv_paths(persona, sidecar.get("date", ""), company_slug, name_slug)
    paths["dir"].mkdir(parents=True, exist_ok=True)

    latex = render_latex(plan, header_name(inputs, profile), contact_parts(inputs, profile))
    paths["tex"].write_text(latex, encoding="utf-8")

    pages = None
    full_pages = None
    page_policy = infer_cv_page_policy(facts)
    warning = None
    trim_applied = False
    trimmed_plan_path = None
    trim_manifest_path = None
    final_result = None

    if build_pdf:
        try:
            final_result = compile_cv_tex(paths)
        except FileNotFoundError:
            return die("lualatex is not installed; install texlive-luatex to compile PDFs")
        except subprocess.SubprocessError as exc:
            return die(f"lualatex failed to run: {exc}")

        pages = parse_lualatex_pages(final_result.stdout)
        full_pages = pages
        if final_result.returncode != 0 or not paths["pdf"].exists():
            write_build_log(paths, persona, job, final_result, pages, page_policy, None)
            return die(f"lualatex failed with exit code {final_result.returncode}; see {paths['log']}")

        max_pages = page_policy.get("max_pages", 1)
        if pages is not None and pages > max_pages:
            if page_policy.get("seniority") == "junior":
                trimmed_plan, removed = trim_plan_for_page_fit(plan, facts)
                trimmed_plan_path = plan_path.with_name(f"{plan_path.stem}.trimmed.json")
                trim_manifest_path = plan_path.with_name(f"trim-manifest-job{args.job_number}.json")
                trimmed_plan_path.write_text(json.dumps(trimmed_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                latex = render_latex(trimmed_plan, header_name(inputs, profile), contact_parts(inputs, profile))
                paths["tex"].write_text(latex, encoding="utf-8")
                try:
                    final_result = compile_cv_tex(paths)
                except FileNotFoundError:
                    return die("lualatex is not installed; install texlive-luatex to compile PDFs")
                except subprocess.SubprocessError as exc:
                    return die(f"lualatex failed to run: {exc}")
                pages = parse_lualatex_pages(final_result.stdout)
                manifest = {
                    "schema": "cv-trim-manifest/v1",
                    "policy": page_policy,
                    "source_plan": str(plan_path),
                    "trimmed_plan": str(trimmed_plan_path),
                    "full_pages": full_pages,
                    "trimmed_pages": pages,
                    "removed": removed,
                }
                trim_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                trim_applied = True
                if final_result.returncode != 0 or not paths["pdf"].exists():
                    write_build_log(
                        paths,
                        persona,
                        job,
                        final_result,
                        pages,
                        page_policy,
                        {"trim_applied": True, "full_pages": full_pages, "trim_manifest": str(trim_manifest_path)},
                    )
                    return die(f"lualatex failed with exit code {final_result.returncode}; see {paths['log']}")
                if pages is not None and pages > max_pages:
                    warning = (
                        f"Trimmed junior CV still spans {pages} pages; target is {max_pages} page(s). "
                        f"See {trim_manifest_path}."
                    )
            else:
                warning = (
                    f"Full-fact CV spans {pages} pages; profile is {page_policy.get('seniority')}, "
                    f"target is {max_pages} page(s). No deterministic trim was applied."
                )

        extra = None
        if trim_applied:
            extra = {"trim_applied": True, "full_pages": full_pages, "trim_manifest": str(trim_manifest_path)}
        write_build_log(paths, persona, job, final_result, pages, page_policy, extra)

    print(json.dumps(
        {
            "persona": persona,
            "job_number": job.get("number"),
            "company": job.get("company"),
            "tex": str(paths["tex"]),
            "pdf": str(paths["pdf"]) if paths["pdf"].exists() else None,
            "log": str(paths["log"]) if build_pdf else None,
            "pages": pages,
            "full_pages": full_pages,
            "cv_page_policy": {**page_policy, "warning": warning},
            "trim_applied": trim_applied,
            "trimmed_plan": str(trimmed_plan_path) if trimmed_plan_path else None,
            "trim_manifest": str(trim_manifest_path) if trim_manifest_path else None,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and compile an evidence-anchored CV")
    sub = parser.add_subparsers(dest="command", required=True)

    facts_parser = sub.add_parser("facts", help="emit fact-catalog/v1 from profile.yaml")
    facts_parser.add_argument("--persona", required=True)
    facts_parser.add_argument("--out", type=Path, help="write catalog to this file instead of stdout")
    facts_parser.set_defaults(func=cmd_facts)

    reports_parser = sub.add_parser("reports", help="list report sidecars")
    reports_parser.add_argument("--persona", required=True)
    reports_parser.set_defaults(func=cmd_reports)

    jobs_parser = sub.add_parser("jobs", help="list jobs from a sidecar")
    jobs_parser.add_argument("--sidecar", type=Path, required=True)
    jobs_parser.set_defaults(func=cmd_jobs)

    check_parser = sub.add_parser("check", help="deterministic plan checks")
    check_parser.add_argument("--sidecar", type=Path, required=True)
    check_parser.add_argument("--job-number", type=int, required=True)
    check_parser.add_argument("--facts", type=Path, required=True)
    check_parser.add_argument("--plan", type=Path, required=True)
    check_parser.set_defaults(func=cmd_check)

    render_parser = sub.add_parser("render", help="render LaTeX only")
    render_parser.add_argument("--sidecar", type=Path, required=True)
    render_parser.add_argument("--job-number", type=int, required=True)
    render_parser.add_argument("--facts", type=Path, required=True)
    render_parser.add_argument("--plan", type=Path, required=True)
    render_parser.add_argument("--verdict", type=Path, required=True)
    render_parser.set_defaults(func=lambda args: cmd_render(args, build_pdf=False))

    build_parser_ = sub.add_parser("build", help="render and compile PDF with LuaLaTeX")
    build_parser_.add_argument("--sidecar", type=Path, required=True)
    build_parser_.add_argument("--job-number", type=int, required=True)
    build_parser_.add_argument("--facts", type=Path, required=True)
    build_parser_.add_argument("--plan", type=Path, required=True)
    build_parser_.add_argument("--verdict", type=Path, required=True)
    build_parser_.set_defaults(func=lambda args: cmd_render(args, build_pdf=True))

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
