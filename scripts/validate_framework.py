#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable

import integration_registry
import framework_contracts
import markdown_structure
import project_bootstrap
import project_contract_model
import prompt_load_report
import public_surface
import recommend_stack
import routing_policy
import safe_paths
import verification_plan
import verification_registry


DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = DEFAULT_REPO_ROOT
PROJECT_LOCAL_STATE = {
    "TODO.md",
    "DECISIONS.md",
    "FINDINGS.md",
    "FRAMEWORK_FEEDBACK.md",
    "REVIEWER_LANE_FEEDBACK.md",
    "PRECEDENTS.md",
    "SOURCE_PACKS.md",
    "SOURCE_UPDATE.md",
    "SOURCE_MONITOR_RESEARCHER.md",
    "SECURITY_VERIFICATION.md",
    "AUTOMATION_ORDERS.json",
}
PUBLIC_ROOTS = public_surface.PUBLIC_ROOTS
REQUIRED_GITIGNORE_PATTERNS = set(public_surface.PUBLIC_GITIGNORE_PATTERNS)
INTERNAL_LOCAL_STATE_PATTERNS = safe_paths.INTERNAL_LOCAL_STATE_PATTERNS
PUBLIC_TEMPLATE_ROOTS = (
    "AGENTS.md",
    "CLAUDE.md",
    "statement_of_work_template.md",
    "runtime/project_template.md",
    "project_state_templates",
    ".agents/skills/master-prompt-new-project",
    ".agents/skills/master-prompt-refresh-project",
    "annexes",
    "examples",
    "integrations/templates",
)
PUBLIC_TEMPLATE_INTERNAL_PHRASES = (
    "April 2026",
    "authoring workspace",
    "framework repo",
    "framework-repo",
    "framework-internal",
    "internal framework notes",
    "public framework repository",
    "weekly-framework-compliance",
    "working notes",
)
HOST_PATH_MARKER_ALLOWLIST = {
    ".gitignore": {
        "/" + "tmp" + "/",
    },
    "scripts/public_release_check.py": {
        "r'\"--output=/" + "tmp" + "/out\"',",
    },
}
TASK_ORDER_HEADING_PREFIX = "Task Order — "
TRIGGERLESS_GUIDES = {"risk_routing"}
CHECKLESS_TRIGGER_FLAGS: set[str] = set()
WRAPPER_STATUSES = {"not-applicable", "candidate", "required"}
PRACTICE_GUIDE_FIELDS = {"category", "name", "path", "trigger_flags", "wrapper_status"}
TEXT_SCAN_SUFFIXES = {".json", ".md", ".py", ".template", ".yaml", ".yml"}
TEXT_SCAN_FILENAMES = {".gitignore", "LICENSE", "NOTICE"}
STANDARD_SURFACE_LINKS = {
    "README.md": ("SPECIFICATION.md", "CONFORMANCE.md", "GOVERNANCE.md", "SECURITY.md"),
    "GETTING_STARTED.md": ("CONFORMANCE.md",),
    "ARCHITECTURE.md": ("SPECIFICATION.md", "CONFORMANCE.md"),
}
SECURITY_REQUIRED_HEADINGS = (
    "## Scope",
    "## Assets",
    "## Trust Boundaries",
    "## Threat Model",
    "## External Content And Prompt Injection",
    "## Tool Output And Generated Code Execution",
    "## Dependencies And Integrations",
    "## Automations And Source Registries",
    "## Public/Private Leakage",
    "## Reporting",
    "## Non-Guarantees",
)
SECURITY_AFFIRMATIVE_WORDING_GUARDS = (
    "prevents prompt injection",
    "eliminates prompt injection",
    "guarantees security",
    "secure by default in all cases",
    "safe generated code",
    "trusted tool output",
)
INTERACTIVE_DOC_FILES = (
    "docs/interactive/README.md",
    "docs/interactive/index.html",
    "docs/interactive/styles.css",
    "docs/interactive/app.ts",
    "docs/interactive/app.js",
    "docs/interactive/tsconfig.json",
)
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NEGATED_REFERENCE_RE = re.compile(r"\b(?:do not|don't|must not|never|avoid)\b", re.IGNORECASE)
HTML_ID_RE = re.compile(r"\bid=[\"']([^\"']+)[\"']")
HTML_LINKED_RESOURCE_RE = re.compile(r"\b(?:href|src)=[\"']([^\"']+)[\"']")
CSS_REMOTE_RESOURCE_RE = re.compile(r"@import\b|url\(\s*[\"']?(?:https?:)?//", re.IGNORECASE)
SCRIPT_REMOTE_RESOURCE_RE = re.compile(
    r"\b(?:fetch|XMLHttpRequest)\b|import\(\s*[\"'](?:https?:)?//|from\s+[\"'](?:https?:)?//",
    re.IGNORECASE,
)
SCRIPT_NAVIGATION_HREF_RE = re.compile(r"\bhref:\s*[\"']([^\"']+)[\"']")
MAX_INPUT_DIAGNOSTIC_CHARS = 512


def _directory_stability_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    # Entry membership is recorded separately. Omitting directory timestamps and
    # link count prevents excluded cache/private churn from invalidating a run.
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _entry_kind(metadata: os.stat_result) -> str:
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    return "special"


def _scan_framework_product_surface(root: Path) -> tuple[object, ...]:
    records: list[tuple[str, str, object, tuple[str, ...]]] = []

    def record_key(
        record: tuple[str, str, object, tuple[str, ...]],
    ) -> tuple[str, str]:
        return record[1], record[0]

    def scan(path: Path, rel: str) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"framework product path changed during inventory: {rel}"
            ) from exc
        kind = _entry_kind(metadata)
        if kind != "directory":
            records.append((kind, rel, safe_paths.stable_file_metadata(metadata), ()))
            return
        try:
            with os.scandir(path) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise RuntimeError(
                f"framework product directory could not be inventoried: {rel}"
            ) from exc
        included = [
            entry
            for entry in entries
            if not public_surface.is_public_excluded(
                f"{rel}/{entry.name}" if rel else entry.name
            )
        ]
        records.append(
            (
                kind,
                rel,
                _directory_stability_metadata(metadata),
                tuple(entry.name for entry in included),
            )
        )
        for entry in included:
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            scan(Path(entry.path), child_rel)

    for rel in PUBLIC_ROOTS:
        path = root / rel
        try:
            path.lstat()
        except FileNotFoundError:
            records.append(("missing", rel, None, ()))
        else:
            scan(path, rel)

    for rel in sorted(PROJECT_LOCAL_STATE):
        path = root / rel
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            records.append(("local-state-absent", rel, None, ()))
        else:
            records.append(
                (
                    f"local-state-{_entry_kind(metadata)}",
                    rel,
                    (
                        _directory_stability_metadata(metadata)
                        if stat.S_ISDIR(metadata.st_mode)
                        else safe_paths.stable_file_metadata(metadata)
                    ),
                    (),
                )
            )
    records.sort(key=record_key)
    return tuple(records)


def framework_product_surface_signature(root: Path) -> tuple[object, ...]:
    """Return a stable metadata signature of only validator-owned product inputs."""

    for _attempt in range(3):
        first = _scan_framework_product_surface(root)
        second = _scan_framework_product_surface(root)
        if first == second:
            return first
    raise RuntimeError("framework product surface kept changing during inventory")


def non_fenced_lines(text: str) -> list[str]:
    return [line for _line_number, line in markdown_structure.operative_lines(text)]


def markdown_heading_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    counts: dict[str, int] = {}
    for line in non_fenced_lines(text):
        match = MARKDOWN_HEADING_RE.match(line)
        if match is None:
            continue
        plain = re.sub(r"<[^>]*>", "", match.group(2)).casefold()
        base = re.sub(r"[^\w\s-]", "", plain)
        base = re.sub(r"\s+", "-", base.strip())
        if not base:
            continue
        count = counts.get(base, 0)
        counts[base] = count + 1
        fragments.add(base if count == 0 else f"{base}-{count}")
    return fragments


def interactive_navigation_errors(root: Path, rel: str, script_text: str) -> list[str]:
    errors: list[str] = []
    source = root / rel
    for href in SCRIPT_NAVIGATION_HREF_RE.findall(script_text):
        target_ref, separator, fragment = href.partition("#")
        if not target_ref or re.match(r"(?i)(?:[a-z][a-z0-9+.-]*:|//)", target_ref):
            errors.append(f"{rel} navigation href must be a local public file: {href}")
            continue
        target = source.parent / target_ref
        if (
            not safe_paths.path_within_root(target, root)
            or safe_paths.symlink_components(target, root)
            or not target.is_file()
        ):
            errors.append(f"{rel} navigation href must resolve to a regular public file: {href}")
            continue
        target_rel = target.resolve().relative_to(root.resolve()).as_posix()
        if target_rel not in public_surface.PUBLIC_REQUIRED_FILES:
            errors.append(f"{rel} navigation href target is absent from the public export: {href}")
            continue
        if not separator:
            continue
        if not fragment:
            errors.append(f"{rel} navigation href has an empty fragment: {href}")
            continue
        target_text = read_text_if_file(target, errors, target_rel)
        if target_text is None:
            continue
        if target.suffix.casefold() == ".md":
            fragments = markdown_heading_fragments(target_text)
        elif target.suffix.casefold() in {".html", ".htm"}:
            fragments = set(HTML_ID_RE.findall(target_text))
        else:
            errors.append(f"{rel} navigation href fragment target is not anchor-capable: {href}")
            continue
        if fragment not in fragments:
            errors.append(f"{rel} navigation href points to a missing fragment: {href}")
    return errors


def positive_text_reference(text: str, needle: str) -> bool:
    return any(needle in line and not NEGATED_REFERENCE_RE.search(line) for line in non_fenced_lines(text))


def markdown_heading_lines(text: str) -> set[str]:
    headings: set[str] = set()
    for line in non_fenced_lines(text):
        match = MARKDOWN_HEADING_RE.match(line)
        if match:
            headings.add(f"{match.group(1)} {match.group(2).strip()}")
    return headings


def _bounded_diagnostic(exc: BaseException) -> str:
    detail = " ".join(str(exc).splitlines()).strip() or exc.__class__.__name__
    if len(detail) <= MAX_INPUT_DIAGNOSTIC_CHARS:
        return detail
    return detail[: MAX_INPUT_DIAGNOSTIC_CHARS - 1] + "…"


def _collect_validation_phase(
    failures: list[str],
    label: str,
    operation: Callable[[], list[str]],
) -> None:
    """Keep independent validation phases running after bounded failures."""

    try:
        phase_failures = operation()
    except Exception as exc:
        failures.append(
            f"{label} could not complete: {type(exc).__name__}: "
            f"{_bounded_diagnostic(exc)}"
        )
        return
    if not isinstance(phase_failures, list) or not all(
        isinstance(item, str) for item in phase_failures
    ):
        failures.append(
            f"{label} returned an invalid diagnostic collection"
        )
        return
    failures.extend(phase_failures)


def _read_bounded_utf8(path: Path, *, description: str) -> str:
    raw = safe_paths.read_regular_file_bytes(
        path,
        description=description,
        max_bytes=safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
        require_single_link=True,
    )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{description} must contain valid UTF-8: {path}"
        ) from exc


def load_json(path: Path) -> Any:
    """Load one bounded, descriptor-bound JSON document.

    This strict loader raises on malformed input for callers that explicitly
    validate exceptions. Validator entrypoints should use
    ``load_json_object_if_file`` so malformed inputs become ordinary findings.
    """

    return safe_paths.loads_json_no_duplicates(
        _read_bounded_utf8(path, description="framework JSON input")
    )


def load_json_object_if_file(
    path: Path,
    errors: list[str],
    rel: str,
) -> dict[str, Any] | None:
    try:
        document = load_json(path)
    except FileNotFoundError:
        errors.append(f"missing file: {rel}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(
            f"invalid JSON in {rel}: {_bounded_diagnostic(exc)}"
        )
        return None
    except (OSError, RecursionError, ValueError) as exc:
        errors.append(
            f"unsafe or unreadable JSON file {rel}: {_bounded_diagnostic(exc)}"
        )
        return None
    if not isinstance(document, dict):
        errors.append(f"{rel} must contain a JSON object")
        return None
    return document


def read_text_if_file(path: Path, errors: list[str], rel: str) -> str | None:
    try:
        return _read_bounded_utf8(path, description=f"framework text input {rel}")
    except FileNotFoundError:
        errors.append(f"missing file: {rel}")
        return None
    except (OSError, ValueError) as exc:
        errors.append(
            f"unsafe or unreadable text file {rel}: {_bounded_diagnostic(exc)}"
        )
        return None


def iter_text_files(path: Path) -> list[Path]:
    if path.is_file():
        return [] if path.is_symlink() else [path]
    return [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and (candidate.suffix in TEXT_SCAN_SUFFIXES or candidate.name in TEXT_SCAN_FILENAMES)
    ]


def iter_stale_term_scan_files(path: Path) -> list[Path]:
    if path.is_symlink():
        return []
    if path.is_file():
        return [path]
    suffixes = {".json", ".md", ".template"}
    if path.name == "scripts":
        suffixes.add(".py")
    return [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and (candidate.suffix in suffixes or candidate.name in TEXT_SCAN_FILENAMES)
    ]


def public_symlink_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for rel in public_surface.PUBLIC_ROOTS:
        path = root / rel
        if path.is_symlink():
            errors.append(f"public surface contains symlink path: {rel}")
            continue
        if path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_symlink():
                    errors.append(f"public surface contains symlink path: {candidate.relative_to(root).as_posix()}")
    return errors


def public_text_files() -> list[Path]:
    return [
        path
        for path in public_surface.iter_public_root_files(REPO_ROOT)
        if path.suffix in TEXT_SCAN_SUFFIXES or path.name in TEXT_SCAN_FILENAMES
    ]


def is_public_excluded(rel: str) -> bool:
    return public_surface.is_public_excluded(rel)


def contains_internal_local_state_reference(text: str) -> bool:
    return any(pattern.search(text) for pattern in INTERNAL_LOCAL_STATE_PATTERNS)


def contains_host_path_marker(rel: str, text: str) -> bool:
    allowed_lines = HOST_PATH_MARKER_ALLOWLIST.get(rel, set())
    for line in text.splitlines():
        if line.strip() in allowed_lines:
            continue
        if safe_paths.local_absolute_path_matches(line):
            return True
    return False


def public_template_files() -> list[Path]:
    files: list[Path] = []
    for rel in PUBLIC_TEMPLATE_ROOTS:
        files.extend(iter_text_files(REPO_ROOT / rel))
    return files


def script_index_errors() -> list[str]:
    errors: list[str] = []
    index_path = REPO_ROOT / "scripts" / "README.md"
    text = read_text_if_file(index_path, errors, "scripts/README.md")
    if text is None:
        return errors
    operative_text = "\n".join(
        line for _line_number, line in markdown_structure.operative_lines(text)
    )
    linked = {
        f"scripts/{target}"
        for target in re.findall(r"\]\(([^)#?]+\.py)\)", operative_text)
        if "/" not in target and "\\" not in target
    }
    discovered = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "scripts").glob("*.py")
        if path.is_file() and not path.is_symlink()
    }
    for rel in sorted(discovered - linked):
        errors.append(f"public script missing from scripts/README.md: {rel}")
    for rel in sorted(linked - discovered):
        errors.append(f"scripts/README.md links unknown public script: {rel}")
    return errors


def project_state_template_inventory_errors() -> list[str]:
    errors: list[str] = []
    declared = {
        *project_bootstrap.STATE_TEMPLATES.values(),
        *project_bootstrap.MANUAL_STATE_TEMPLATES.values(),
    }
    discovered = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "project_state_templates").iterdir()
        if path.is_file()
        and not path.is_symlink()
        and not public_surface.is_public_excluded(path.relative_to(REPO_ROOT).as_posix())
    }
    for rel in sorted(discovered - declared):
        errors.append(f"project-state template lacks bootstrap/manual classification: {rel}")
    for rel in sorted(declared - discovered):
        errors.append(f"declared project-state template is missing: {rel}")
    for output_name, rel in sorted(project_bootstrap.STATE_TEMPLATES.items()):
        if Path(rel).name != output_name:
            errors.append(f"project-state template output/path mismatch: {output_name} -> {rel}")
    for output_name, rel in sorted(project_bootstrap.MANUAL_STATE_TEMPLATES.items()):
        if Path(rel).name != output_name:
            errors.append(f"manual project-state template output/path mismatch: {output_name} -> {rel}")
    for output_name, rel in sorted(project_bootstrap.BOOTSTRAP_STATE_TEMPLATES.items()):
        if output_name not in project_bootstrap.STATE_TEMPLATES:
            errors.append(f"bootstrap-safe state template has no main template: {output_name}")
        path = REPO_ROOT / rel
        if not path.is_file() or path.is_symlink():
            errors.append(f"bootstrap-safe state template is missing or a symlink: {rel}")
    return errors


def standards_surface_errors() -> list[str]:
    errors: list[str] = []
    for rel, required_refs in STANDARD_SURFACE_LINKS.items():
        text = read_text_if_file(REPO_ROOT / rel, errors, rel)
        if text is None:
            continue
        for required_ref in required_refs:
            if not positive_text_reference(text, required_ref):
                errors.append(f"{rel} must reference standards surface {required_ref}")

    security_text = read_text_if_file(REPO_ROOT / "SECURITY.md", errors, "SECURITY.md")
    if security_text is not None:
        security_headings = markdown_heading_lines(security_text)
        for heading in SECURITY_REQUIRED_HEADINGS:
            if heading not in security_headings:
                errors.append(f"SECURITY.md missing required heading: {heading}")

    for path in public_text_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("tests/") or rel == "scripts/validate_framework.py":
            continue
        text = read_text_if_file(path, errors, rel)
        if text is None:
            continue
        folded_text = text.casefold()
        for phrase in SECURITY_AFFIRMATIVE_WORDING_GUARDS:
            if positive_text_reference(folded_text, phrase):
                errors.append(
                    f"security affirmative-wording guard matched phrase {phrase!r} "
                    f"in public file: {rel}"
                )
    return errors


def practice_guide_integration_errors(schedule: dict, required_files: list[str]) -> list[str]:
    errors: list[str] = []
    scheduled_guides: dict[str, dict[str, Any]] = {}
    raw_guides = schedule.get("practice_guides", [])
    if not isinstance(raw_guides, list):
        errors.append("operative schedule practice_guides must be a list")
        raw_guides = []
    for index, guide in enumerate(raw_guides):
        if not isinstance(guide, dict):
            errors.append(f"operative schedule practice_guides[{index}] must be an object")
            continue
        name = guide.get("name")
        rel_path = guide.get("path")
        trigger_flags = guide.get("trigger_flags", [])
        if not isinstance(name, str) or not name:
            errors.append(f"operative schedule practice_guides[{index}] must define name")
            continue
        if not isinstance(rel_path, str) or not rel_path:
            errors.append(f"operative schedule Practice Guide {name} must define path")
            continue
        if not isinstance(trigger_flags, list) or not all(isinstance(flag, str) for flag in trigger_flags):
            errors.append(f"operative schedule Practice Guide {name} trigger_flags must be a list of strings")
            continue
        scheduled_guides[name] = guide
    scheduled_paths = {guide["path"] for guide in scheduled_guides.values()}
    root_guides = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "practice_guides").glob("*.md")
    }

    for rel in sorted(root_guides - scheduled_paths):
        errors.append(f"Practice Guide missing from operative schedule: {rel}")
    for rel in sorted(scheduled_paths - root_guides):
        errors.append(f"operative schedule points outside root Practice Guide set: {rel}")
    for rel in sorted(scheduled_paths - set(required_files)):
        errors.append(f"scheduled Practice Guide missing from required file manifest: {rel}")

    readme_text = read_text_if_file(REPO_ROOT / "README.md", errors, "README.md") or ""
    risk_routing_text = read_text_if_file(
        REPO_ROOT / "practice_guides" / "risk_routing.md",
        errors,
        "practice_guides/risk_routing.md",
    ) or ""
    if readme_text and ("runtime/operative_schedule.json" not in readme_text or "practice_guides/" not in readme_text):
        errors.append("README must point to the operative schedule and Practice Guide directory")
    allowed_flags = routing_policy.allowed_trigger_flags()
    for name, guide in sorted(scheduled_guides.items()):
        rel = guide["path"]
        trigger_flags = guide.get("trigger_flags", [])
        if name not in TRIGGERLESS_GUIDES and not trigger_flags:
            errors.append(f"scheduled Practice Guide has no trigger flags: {name}")
        if name not in TRIGGERLESS_GUIDES and f"`{name}`" not in risk_routing_text:
            errors.append(f"risk_routing does not mention scheduled Practice Guide: {name}")
        for flag in trigger_flags:
            if flag not in allowed_flags:
                continue
            parser = recommend_stack.build_parser()
            args = parser.parse_args([f"--{flag.replace('_', '-')}"])
            routed = set(recommend_stack.collect_practice_guides(args, schedule))
            if name not in routed:
                errors.append(f"trigger flag --{flag.replace('_', '-')} does not route to Practice Guide: {name}")
            standard = recommend_stack.choose_standard_of_care(args)
            checks = recommend_stack.collect_required_checks(args, standard)
            if not checks and flag not in CHECKLESS_TRIGGER_FLAGS:
                errors.append(f"trigger flag --{flag.replace('_', '-')} routes no required checks")
            verification_plan.group_checks(checks)

    errors.extend(
        verification_registry.registry_errors(
            allowed_flags=allowed_flags,
            known_guides=set(scheduled_guides),
        )
    )
    evidence_matrix = schedule.get("minimum_evidence_by_risk", {})
    if isinstance(evidence_matrix, dict):
        for risk, evidence_rule in evidence_matrix.items():
            if not isinstance(evidence_rule, dict):
                continue
            required_checks = evidence_rule.get("required_checks", [])
            if not isinstance(required_checks, list):
                continue
            for check_id in required_checks:
                if (
                    isinstance(check_id, str)
                    and check_id not in verification_registry.CHECKS_BY_ID
                ):
                    errors.append(
                        "operative schedule minimum_evidence_by_risk "
                        f"{risk} references unknown verification check: {check_id}"
                    )
    return errors


def native_wrapper_registration_errors() -> list[str]:
    errors: list[str] = []
    registry = integration_registry.load_registry(REPO_ROOT)
    registered = {
        wrapper_config["path"]
        for family in registry["families"].values()
        for wrapper_config in family.get("wrappers", {}).values()
    }
    discovered = {
        path.relative_to(REPO_ROOT).as_posix()
        for pattern in (
            "integrations/templates/codex/skills/*/SKILL.md.template",
            "integrations/templates/claude-code/.claude/agents/*.template",
        )
        for path in REPO_ROOT.glob(pattern)
    }
    for rel in sorted(discovered - registered):
        errors.append(f"native wrapper template is not registered: {rel}")
    for rel in sorted(registered - discovered):
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"registered native wrapper path missing: {rel}")
    return errors


def interactive_docs_errors(root: Path) -> list[str]:
    errors: list[str] = []
    texts: dict[str, str] = {}
    for rel in INTERACTIVE_DOC_FILES:
        text = read_text_if_file(root / rel, errors, rel)
        if text is not None:
            texts[rel] = text

    index_text = texts.get("docs/interactive/index.html", "")
    readme_text = texts.get("docs/interactive/README.md", "")
    if "This page illustrates concepts for humans" not in index_text:
        errors.append("docs/interactive/index.html must state its human-facing source-of-truth boundary")
    if "Agents may use this page when explaining the framework to a human" not in readme_text:
        errors.append("docs/interactive/README.md must state the allowed human-explanation use")
    if "The source of truth remains the markdown framework" not in readme_text:
        errors.append("docs/interactive/README.md must keep markdown as the source of truth")
    if "TypeScript 7.0.2" not in readme_text or "--noEmit" not in readme_text or "--outDir" not in readme_text:
        errors.append("docs/interactive/README.md must retain the pinned non-mutating compiler verification contract")
    for forbidden in ("npm exec --package", "typescript@latest"):
        if forbidden in readme_text:
            errors.append(
                f"docs/interactive/README.md must not fetch or select an unpinned compiler: {forbidden}"
            )
    if 'rel="stylesheet" href="styles.css"' not in index_text:
        errors.append("docs/interactive/index.html must load only the local stylesheet")
    if '<script defer src="app.js"></script>' not in index_text:
        errors.append("docs/interactive/index.html must defer-load the local generated script")

    ids = set(HTML_ID_RE.findall(index_text))
    fragment_targets = {
        value[1:]
        for value in HTML_LINKED_RESOURCE_RE.findall(index_text)
        if value.startswith("#") and len(value) > 1
    }
    for missing in sorted(fragment_targets - ids):
        errors.append(f"docs/interactive/index.html fragment link points to missing id: #{missing}")

    for value in HTML_LINKED_RESOURCE_RE.findall(index_text):
        if re.match(r"(?i)(?:https?:)?//|file:", value):
            errors.append(f"docs/interactive/index.html must not load external or file resource: {value}")

    style_text = texts.get("docs/interactive/styles.css", "")
    if CSS_REMOTE_RESOURCE_RE.search(style_text):
        errors.append("docs/interactive/styles.css must not import or reference remote resources")

    for rel in ("docs/interactive/app.ts", "docs/interactive/app.js"):
        script_text = texts.get(rel, "")
        if SCRIPT_REMOTE_RESOURCE_RE.search(script_text):
            errors.append(f"{rel} must not fetch or import remote resources")
        errors.extend(interactive_navigation_errors(root, rel, script_text))

    if "createElementNS" not in texts.get("docs/interactive/app.ts", ""):
        errors.append("docs/interactive/app.ts must build SVG through DOM namespace APIs")

    tsconfig_text = texts.get("docs/interactive/tsconfig.json", "")
    try:
        tsconfig = safe_paths.loads_json_no_duplicates(tsconfig_text)
    except json.JSONDecodeError as exc:
        errors.append(f"docs/interactive/tsconfig.json is invalid JSON: {exc}")
    else:
        compiler_options = tsconfig.get("compilerOptions") if isinstance(tsconfig, dict) else None
        if not isinstance(compiler_options, dict):
            errors.append("docs/interactive/tsconfig.json must define compilerOptions")
        else:
            if compiler_options.get("target") != "ES2022":
                errors.append("docs/interactive/tsconfig.json target must be ES2022")
            raw_lib = compiler_options.get("lib")
            if not isinstance(raw_lib, list) or set(raw_lib) != {"DOM", "DOM.Iterable", "ES2022"}:
                errors.append("docs/interactive/tsconfig.json lib contract drift")
            if compiler_options.get("strict") is not True or compiler_options.get("noEmitOnError") is not True:
                errors.append("docs/interactive/tsconfig.json must retain strict no-error emit guards")

    return errors


def operative_schedule_schema_errors(schedule: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    risk_names: set[str] = set()
    standards = schedule.get("standards_of_care", [])
    if not isinstance(standards, list):
        errors.append("operative schedule standards_of_care must be a list")
        standards = []
    for item in standards:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                risk_names.add(name)
    evidence_scopes: set[str] = set()
    scopes = schedule.get("evidentiary_scopes", [])
    if not isinstance(scopes, list):
        errors.append("operative schedule evidentiary_scopes must be a list")
        scopes = []
    for item in scopes:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                evidence_scopes.add(name)
    matrix = schedule.get("minimum_evidence_by_risk")
    if not isinstance(matrix, dict):
        errors.append("operative schedule minimum_evidence_by_risk must be an object")
    else:
        matrix_keys: set[str] = set()
        for key in matrix:
            if isinstance(key, str):
                matrix_keys.add(key)
            else:
                errors.append("operative schedule minimum_evidence_by_risk keys must be strings")
        missing = sorted(risk_names - matrix_keys)
        extra = sorted(matrix_keys - risk_names)
        if missing:
            errors.append(f"operative schedule minimum_evidence_by_risk missing risks: {', '.join(missing)}")
        if extra:
            errors.append(f"operative schedule minimum_evidence_by_risk has unknown risks: {', '.join(extra)}")
        for risk in sorted(matrix_keys):
            entry = matrix[risk]
            if not isinstance(entry, dict):
                errors.append(f"operative schedule minimum_evidence_by_risk {risk} must be an object")
                continue
            if entry.get("minimum_scope") not in evidence_scopes:
                errors.append(
                    "operative schedule minimum_evidence_by_risk "
                    f"{risk} uses unknown minimum_scope: {entry.get('minimum_scope')}"
                )
            required_checks = entry.get("required_checks")
            if not isinstance(required_checks, list) or not required_checks or not all(
                isinstance(item, str) and item for item in required_checks
            ):
                errors.append(
                    f"operative schedule minimum_evidence_by_risk {risk} must define non-empty required_checks"
                )
    return errors


def gitignore_contract_errors(root: Path) -> list[str]:
    failures: list[str] = []
    path = root / ".gitignore"
    text = read_text_if_file(path, failures, ".gitignore")
    if text is None:
        return failures
    lines = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for pattern in sorted(REQUIRED_GITIGNORE_PATTERNS - lines):
        failures.append(f".gitignore missing required leak-prevention pattern: {pattern}")
    for prefix in public_surface.PUBLIC_EXCLUDED_PREFIXES:
        pattern = f"/{prefix}" if not prefix.startswith("/") else prefix
        alternatives = {pattern}
        if pattern.endswith("/"):
            alternatives.update({pattern + "*", pattern + "**"})
        if not alternatives.intersection(lines):
            failures.append(f".gitignore missing public-surface excluded prefix: {pattern}")
    return failures


def required_surface_errors(root: Path) -> tuple[list[str], list[str]]:
    failures = public_symlink_errors(root)
    try:
        required_templates = integration_registry.required_template_files(root)
    except Exception as exc:
        required_templates = []
        failures.append(
            "integration registry required-template inventory could not complete: "
            f"{type(exc).__name__}: {_bounded_diagnostic(exc)}"
        )
    required_files = [
        *public_surface.PUBLIC_REQUIRED_FILES,
        *required_templates,
    ]
    for rel in required_files:
        path = root / rel
        if path.is_symlink():
            failures.append(f"required public file is symlink: {rel}")
        elif not path.exists():
            failures.append(f"missing file: {rel}")
    _collect_validation_phase(
        failures,
        "prompt-load surface-budget validation",
        lambda: prompt_load_report.loaded_surface_budget_errors(root),
    )
    for rel in sorted(PROJECT_LOCAL_STATE):
        if (root / rel).exists():
            failures.append(
                f"redundant root state file present: {rel}; use project_state_templates/ instead"
            )
    for label, operation in (
        ("standards-surface validation", standards_surface_errors),
        ("interactive documentation validation", lambda: interactive_docs_errors(root)),
        ("script-index validation", script_index_errors),
        ("project-state template inventory", project_state_template_inventory_errors),
        (
            "generated contract asset validation",
            lambda: project_contract_model.generated_asset_errors(root),
        ),
    ):
        _collect_validation_phase(failures, label, operation)
    return required_files, failures


def task_order_catalog_errors(root: Path) -> list[str]:
    failures: list[str] = []
    task_order_files = sorted(
        path for path in (root / "task_orders").glob("*.md") if path.name != "README.md"
    )
    workflow_catalog = load_json_object_if_file(
        root / "runtime/workflow_catalog.json",
        failures,
        "runtime/workflow_catalog.json",
    )
    if workflow_catalog is None:
        return failures
    raw_task_orders = workflow_catalog.get("task_orders", [])
    if not isinstance(raw_task_orders, list):
        return ["runtime/workflow_catalog.json task_orders must be a list"]
    workflow_paths = {
        item.get("path")
        for item in raw_task_orders
        if isinstance(item, dict)
    }
    for path in task_order_files:
        rel = path.relative_to(root).as_posix()
        text = read_text_if_file(path, failures, rel)
        if text is None:
            continue
        lines = text.splitlines()
        first_line = lines[0] if lines else ""
        if not first_line.startswith(TASK_ORDER_HEADING_PREFIX):
            failures.append(f"Task Order heading must start with {TASK_ORDER_HEADING_PREFIX!r}: {rel}")
        if rel not in workflow_paths:
            failures.append(f"Task Order missing from workflow catalog: {rel}")
    catalog_paths = sorted(
        path
        for path in workflow_paths
        if isinstance(path, str) and path.startswith("task_orders/")
    )
    for rel in catalog_paths:
        if rel != "task_orders/README.md" and not (root / rel).exists():
            failures.append(f"workflow catalog Task Order path missing: {rel}")
    return failures


def stale_terminology_errors(root: Path) -> list[str]:
    failures: list[str] = []
    stale_terms = {
        "playbooks/": ["README.md", "ARCHITECTURE.md", "integrations/templates", "runtime", "practice_guides", "task_orders"],
        "adapters/": ["README.md", "ARCHITECTURE.md", "integrations/templates", "runtime", "practice_guides", "task_orders"],
        "runtime/tasks/": ["README.md", "ARCHITECTURE.md", "integrations/templates", "runtime", "practice_guides", "task_orders"],
        "SKILLS.md": ["README.md", "ARCHITECTURE.md", "integrations/templates", "runtime", "practice_guides", "task_orders", "annexes"],
    }
    for needle, locations in stale_terms.items():
        for rel in locations:
            for path in iter_stale_term_scan_files(root / rel):
                if path.relative_to(root).as_posix() == "runtime/consistency_contract.json":
                    continue
                path_rel = path.relative_to(root).as_posix()
                text = read_text_if_file(path, failures, path_rel)
                if text is not None and needle in text:
                    failures.append(f"stale term {needle!r} present in {path.relative_to(root)}")
    return failures


def public_content_boundary_errors(root: Path) -> list[str]:
    failures: list[str] = []
    for path in public_text_files():
        rel = path.relative_to(root)
        if rel.as_posix().startswith("tests/"):
            continue
        text = read_text_if_file(path, failures, rel.as_posix())
        if text is None:
            continue
        if contains_internal_local_state_reference(text):
            failures.append(f"internal local-state reference leaked into public file: {rel}")
        if contains_host_path_marker(rel.as_posix(), text):
            failures.append(f"host-specific absolute path leaked into public file: {rel}")
    for path in public_template_files():
        rel = path.relative_to(root)
        text = read_text_if_file(path, failures, rel.as_posix())
        if text is None:
            continue
        for phrase in PUBLIC_TEMPLATE_INTERNAL_PHRASES:
            if phrase in text:
                failures.append(f"template contains internal-maintenance phrase {phrase!r}: {rel}")
    return failures


def scheduled_practice_guide_errors(schedule: dict[str, Any], root: Path) -> list[str]:
    failures: list[str] = []
    allowed_flags = routing_policy.allowed_trigger_flags()
    seen_guides: set[str] = set()
    raw_guides = schedule.get("practice_guides", [])
    if not isinstance(raw_guides, list):
        return ["operative schedule practice_guides must be a list"]
    for index, guide in enumerate(raw_guides):
        if not isinstance(guide, dict):
            failures.append(f"operative schedule practice_guides[{index}] must be an object")
            continue
        name = guide.get("name")
        if not isinstance(name, str) or not name:
            failures.append(f"operative schedule Practice Guide {index} must define name")
            continue
        unknown_fields = sorted(set(guide) - PRACTICE_GUIDE_FIELDS)
        if unknown_fields:
            failures.append(
                f"operative schedule Practice Guide {name} has unknown fields: "
                + ", ".join(unknown_fields)
            )
        if guide.get("wrapper_status") not in WRAPPER_STATUSES:
            failures.append(
                f"operative schedule Practice Guide {name} has invalid wrapper_status: "
                f"{guide.get('wrapper_status')}"
            )
        if name in seen_guides:
            failures.append(f"duplicate Practice Guide in operative schedule: {name}")
        seen_guides.add(name)
        guide_path_value = guide.get("path")
        if not isinstance(guide_path_value, str) or not guide_path_value:
            failures.append(f"operative schedule Practice Guide {name} must define path")
            continue
        if not (root / guide_path_value).exists():
            failures.append(f"operative schedule Practice Guide path missing: {guide_path_value}")
        trigger_flags = guide.get("trigger_flags", [])
        if not isinstance(trigger_flags, list) or not all(
            isinstance(flag, str) for flag in trigger_flags
        ):
            failures.append(
                f"operative schedule Practice Guide {name} trigger_flags must be a list of strings"
            )
            continue
        for flag in trigger_flags:
            if flag not in allowed_flags:
                failures.append(
                    f"operative schedule Practice Guide {name} uses unknown trigger flag: {flag}"
                )
    return failures


def scheduled_level_path_errors(schedule: dict[str, Any], root: Path) -> list[str]:
    failures: list[str] = []
    for section, label in (
        ("standards_of_care", "Risk Level"),
        ("evidentiary_scopes", "Evidence Scope"),
    ):
        seen: set[str] = set()
        items = schedule.get(section, [])
        if not isinstance(items, list):
            failures.append(f"operative schedule {section} must be a list")
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                failures.append(f"operative schedule {section}[{index}] must be an object")
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                failures.append(f"operative schedule {section}[{index}] must define name")
                continue
            if name in seen:
                failures.append(f"duplicate {label} in operative schedule: {name}")
            seen.add(name)
            rel_path = item.get("path")
            if rel_path and not (root / rel_path).exists():
                failures.append(f"operative schedule path missing: {rel_path}")
    return failures


def schedule_contract_errors(
    root: Path,
    schedule: dict[str, Any],
    required_files: list[str],
) -> list[str]:
    failures: list[str] = []
    if schedule.get("purpose") != "routing-table-not-doctrine":
        failures.append("operative schedule must identify itself as routing-table-not-doctrine")

    def authority_scope_errors() -> list[str]:
        errors: list[str] = []
        framework_contracts.validate_operative_schedule_authority_scope(
            schedule,
            errors,
        )
        return errors

    phases: tuple[tuple[str, Callable[[], list[str]]], ...] = (
        ("operative schedule authority validation", authority_scope_errors),
        (
            "operative schedule schema validation",
            lambda: operative_schedule_schema_errors(schedule),
        ),
        (
            "scheduled Practice Guide validation",
            lambda: scheduled_practice_guide_errors(schedule, root),
        ),
        (
            "Practice Guide integration validation",
            lambda: practice_guide_integration_errors(schedule, required_files),
        ),
        ("native wrapper registration validation", native_wrapper_registration_errors),
        (
            "scheduled level path validation",
            lambda: scheduled_level_path_errors(schedule, root),
        ),
    )
    for label, operation in phases:
        _collect_validation_phase(failures, label, operation)
    return failures


def clause_and_entrypoint_errors(root: Path) -> list[str]:
    failures: list[str] = []
    clause_map = load_json_object_if_file(
        root / "runtime/msa_clause_map.json",
        failures,
        "runtime/msa_clause_map.json",
    )
    if clause_map is None:
        clause_rows: list[object] = []
    elif not isinstance(clause_map.get("clauses"), list):
        failures.append("runtime/msa_clause_map.json must be a versioned object with a clauses list")
        clause_rows = []
    else:
        clause_rows = clause_map["clauses"]
    for row in clause_rows:
        if not isinstance(row, dict):
            failures.append("runtime/msa_clause_map.json clause rows must be objects")
            continue
        source = row.get("source")
        operative_homes = row.get("operative_home", [])
        if not isinstance(operative_homes, list):
            failures.append(f"clause map operative_home must be a list for {source}")
            continue
        for rel_path in operative_homes:
            if not isinstance(rel_path, str):
                failures.append(f"clause map operative_home contains a non-string path for {source}")
            elif rel_path not in PROJECT_LOCAL_STATE and not (root / rel_path).exists():
                failures.append(f"clause map path missing for {source}: {rel_path}")
    for rel in integration_registry.entrypoint_paths(root):
        text = read_text_if_file(root / rel, failures, rel)
        if text is None:
            continue
        for _line_number, line in markdown_structure.operative_lines(text):
            stripped = line.strip()
            if stripped.startswith("@") and "practice_guides/" in stripped:
                failures.append(f"entrypoint imports Practice Guide eagerly: {rel} contains {stripped}")
    return failures


def _main_with_selected_root(argv: list[str] | None = None) -> int:
    global REPO_ROOT

    parser = argparse.ArgumentParser(
        description="Validate the framework product surface.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_REPO_ROOT, help="Framework tree to inspect.")
    args = parser.parse_args(argv)

    REPO_ROOT = args.root.expanduser().absolute()

    try:
        initial_surface = framework_product_surface_signature(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        print("FAIL")
        print(f"- framework product surface could not be inventoried stably: {exc}")
        return 1

    failures: list[str] = []
    _collect_validation_phase(
        failures,
        "gitignore contract validation",
        lambda: gitignore_contract_errors(REPO_ROOT),
    )
    required_files: list[str]
    try:
        required_files, surface_failures = required_surface_errors(REPO_ROOT)
    except Exception as exc:
        required_files = [str(item) for item in public_surface.PUBLIC_REQUIRED_FILES]
        failures.append(
            "required-surface validation could not complete: "
            f"{type(exc).__name__}: {_bounded_diagnostic(exc)}"
        )
    else:
        if not isinstance(required_files, list) or not all(
            isinstance(item, str) for item in required_files
        ):
            failures.append(
                "required-surface validation returned an invalid required-file collection"
            )
            required_files = [
                str(item) for item in public_surface.PUBLIC_REQUIRED_FILES
            ]
        if not isinstance(surface_failures, list) or not all(
            isinstance(item, str) for item in surface_failures
        ):
            failures.append(
                "required-surface validation returned an invalid diagnostic collection"
            )
        else:
            failures.extend(surface_failures)

    for label, operation in (
        (
            "Task Order catalog validation",
            lambda: task_order_catalog_errors(REPO_ROOT),
        ),
        (
            "stale terminology validation",
            lambda: stale_terminology_errors(REPO_ROOT),
        ),
        (
            "public content-boundary validation",
            lambda: public_content_boundary_errors(REPO_ROOT),
        ),
    ):
        _collect_validation_phase(failures, label, operation)

    schedule = load_json_object_if_file(
        REPO_ROOT / "runtime/operative_schedule.json",
        failures,
        "runtime/operative_schedule.json",
    )
    if schedule is not None:
        _collect_validation_phase(
            failures,
            "operative schedule contract validation",
            lambda: schedule_contract_errors(
                REPO_ROOT,
                schedule,
                required_files,
            ),
        )
    _collect_validation_phase(
        failures,
        "clause and entrypoint validation",
        lambda: clause_and_entrypoint_errors(REPO_ROOT),
    )

    try:
        final_surface = framework_product_surface_signature(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        failures.append(
            f"framework product surface could not be inventoried stably: {exc}"
        )
    else:
        if final_surface != initial_surface:
            failures.append(
                "framework product surface changed while validation was running"
            )

    failures = list(dict.fromkeys(failures))
    if failures:
        print("FAIL")
        for item in failures:
            print(f"- {item}")
        return 1

    print("PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run validation without leaking the selected root into later callers."""

    global REPO_ROOT

    previous_root = REPO_ROOT
    try:
        return _main_with_selected_root(argv)
    finally:
        REPO_ROOT = previous_root


if __name__ == "__main__":
    sys.exit(main())
