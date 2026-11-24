#!/usr/bin/env python3
"""Deterministic report sidecar writer.

Writes report-index/v1 JSON next to a report's Markdown and HTML. The model
supplies the job payload; this tool owns schema, job numbering, signal
validation, path layout, and atomic write.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import CAIRO, report_paths, report_sidecar_path, report_timestamp  # noqa: E402
from policy import ALLOWED_SIGNALS  # noqa: E402

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}$")


def die(message: str) -> None:
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


def require_str(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{field} must be a non-empty string")
    return value.strip()


def require_int_range(value, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        die(f"{field} must be an integer")
    if value < low or value > high:
        die(f"{field} must be between {low} and {high}")
    return value


def require_list_str(value, field: str, max_items: int) -> list[str]:
    if not isinstance(value, list):
        die(f"{field} must be a list")
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            die(f"{field} items must be non-empty strings")
        text = item.strip()
        if text not in items:
            items.append(text)
    if len(items) > max_items:
        die(f"{field} must have at most {max_items} items")
    return items


def require_signals(value) -> list[str]:
    items = require_list_str(value, "emphasis_signals", 5)
    for item in items:
        if item not in ALLOWED_SIGNALS:
            die(f"unknown emphasis signal {item!r}; allowed: {', '.join(ALLOWED_SIGNALS)}")
    return items


def normalize_job(job, number: int) -> dict:
    return {
        "number": number,
        "title": require_str(job.get("title"), "title"),
        "company": require_str(job.get("company"), "company"),
        "portal": require_str(job.get("portal"), "portal"),
        "score": require_int_range(job.get("score"), "score", 0, 100),
        "url": require_str(job.get("url"), "url"),
        "tailored_cv_suggestions": require_list_str(job.get("tailored_cv_suggestions"), "tailored_cv_suggestions", 5),
        "emphasis_signals": require_signals(job.get("emphasis_signals", [])),
    }


def cmd_paths(args) -> int:
    date_dir, ts = report_timestamp()
    paths = report_paths(date_dir, ts, args.persona)
    print(json.dumps(
        {
            "date_dir": paths["date_dir"],
            "ts": paths["ts"],
            "markdown": str(paths["markdown"]),
            "html": str(paths["html"]),
            "sidecar": str(paths["sidecar"]),
        },
        ensure_ascii=False,
    ))
    return 0


def cmd_write(args) -> int:
    if args.input == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.input).read_text(encoding="utf-8")
        except OSError as exc:
            die(f"cannot read input {args.input}: {exc}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        die(f"input is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        die("input must be a JSON object")
    persona = payload.get("persona")
    if not isinstance(persona, str) or not persona.strip():
        die("persona must be a non-empty string")
    if args.persona and persona != args.persona:
        die("input persona does not match --persona")
    if not DATE_RE.match(args.date_dir):
        die("--date-dir must be YYYY-MM-DD")
    if not TS_RE.match(args.ts):
        die("--ts must be YYYY-MM-DD-HH-MM")
    jobs_payload = payload.get("jobs")
    if not isinstance(jobs_payload, list):
        die("jobs must be a list")
    jobs = [normalize_job(job, index + 1) for index, job in enumerate(jobs_payload)]
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        generated_at = datetime.now(CAIRO).isoformat()
    sidecar = {
        "schema": "report-index/v1",
        "persona": persona,
        "date": args.date_dir,
        "report_markdown": f"jobs-{args.ts}.md",
        "report_html": f"jobs-{args.ts}.html",
        "report_sidecar": f"jobs-{args.ts}.json",
        "generated_at": generated_at,
        "jobs": jobs,
        "section_default": ["summary", "skills", "projects", "experience", "education"],
    }
    target = report_sidecar_path(args.date_dir, args.ts, persona)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="jobs-", suffix=".json.tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(sidecar, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    print(json.dumps(
        {
            "sidecar": str(target),
            "date_dir": args.date_dir,
            "ts": args.ts,
            "jobs": len(jobs),
            "written": True,
        },
        ensure_ascii=False,
    ))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write report sidecar JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    paths_parser = sub.add_parser("paths", help="print report paths")
    paths_parser.add_argument("--persona", help="persona slug")
    paths_parser.set_defaults(func=cmd_paths)
    write_parser = sub.add_parser("write", help="write sidecar JSON")
    write_parser.add_argument("--persona", help="persona slug")
    write_parser.add_argument("--date-dir", required=True)
    write_parser.add_argument("--ts", required=True)
    write_parser.add_argument("--input", required=True, help="JSON payload file or - for stdin")
    write_parser.set_defaults(func=cmd_write)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())