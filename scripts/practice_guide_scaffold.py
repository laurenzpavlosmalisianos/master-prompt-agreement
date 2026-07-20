#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import routing_policy
import safe_paths

PROMPT_BOUNDARY_RE = re.compile(r"</?(?:system|developer|user|assistant|tool)\b", re.IGNORECASE)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        raise SystemExit("name must contain ASCII letters or digits")
    return slug


def plain_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise SystemExit(f"{label} must be non-empty")
    if any(char in text for char in "\r\n\x00<>`"):
        raise SystemExit(f"{label} must be plain single-line text")
    if PROMPT_BOUNDARY_RE.search(text):
        raise SystemExit(f"{label} must not contain prompt-boundary markup")
    return text


def template(title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "Explain when this Practice Guide should be loaded and what repeated failure mode it prevents.",
        "",
        "## Workflow",
        "",
        "1. Define the exact goal, risk, or failure mode.",
        "2. Gather the smallest sufficient evidence.",
        "3. Apply the guide-specific checks in order.",
        "4. Verify the result and record residual risk.",
        "",
        "## Output",
        "",
        "Provide the findings, recommended action, and verification plan.",
        "",
        "## Guardrails",
        "",
        "- Keep the procedure evidence-first.",
        "- Escalate only when the risk or ambiguity justifies it.",
        "- Record durable findings or precedents when the same failure pattern is likely to recur.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a new Practice Guide scaffold bundle.",
        allow_abbrev=False,
    )
    parser.add_argument("--name", required=True, help="Practice Guide id, for example release_readiness.")
    parser.add_argument("--title", required=True, help="Human-readable title.")
    parser.add_argument("--category", required=True, help="Operative schedule category.")
    parser.add_argument("--trigger-flag", action="append", default=[], help="Schedule trigger flag.")
    parser.add_argument("--output-dir", required=True, help="Directory where the scaffold bundle will be written.")
    parser.add_argument("--force", action="store_true", help="Overwrite files in the scaffold bundle.")
    args = parser.parse_args()
    unknown_flags = sorted(set(args.trigger_flag) - routing_policy.allowed_trigger_flags())
    if unknown_flags:
        raise SystemExit(f"unknown trigger flags: {', '.join(unknown_flags)}")
    name = slugify(args.name)
    title = plain_text(args.title, "--title")
    category = plain_text(args.category, "--category")
    raw_bundle = Path(args.output_dir).expanduser()
    try:
        safe_paths.require_output_path(raw_bundle)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    bundle = raw_bundle.resolve()
    guide_path = bundle / "practice_guides" / f"{name}.md"
    schedule_path = bundle / "runtime_schedule_entry.json"
    outputs = {"practice_guide": str(guide_path), "schedule_entry": str(schedule_path)}
    preflight_scaffold_outputs((guide_path, schedule_path), args.force)
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    write_scaffold(guide_path, template(title), args.force)
    entry = {
        "category": category,
        "name": name,
        "path": f"practice_guides/{name}.md",
        "trigger_flags": args.trigger_flag,
        "wrapper_status": "not-applicable",
    }
    write_scaffold(schedule_path, json.dumps(entry, indent=2, sort_keys=True) + "\n", args.force)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


def preflight_scaffold_outputs(paths: tuple[Path, ...], force: bool) -> None:
    for path in paths:
        try:
            safe_paths.require_output_path(path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if path.exists() and not force:
            raise SystemExit(f"refusing to overwrite existing output without --force: {path}")


def write_scaffold(path: Path, content: str, force: bool) -> None:
    try:
        safe_paths.write_text(path, content, force=force)
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
