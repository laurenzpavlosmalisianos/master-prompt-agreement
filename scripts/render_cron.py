#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import sys

import automation_orders_lint
import run_scheduled_job
import safe_paths

RENDERER_BACKEND = "Cronie-compatible crontab"


def render_job(
    job: dict[str, object],
    project_root: Path,
    manifest_path: Path,
) -> str:
    job_id = job.get("id")
    if (
        not isinstance(job_id, str)
        or automation_orders_lint.has_control(job_id)
        or automation_orders_lint.JOB_ID_RE.fullmatch(job_id) is None
    ):
        raise ValueError("cron rendering requires one control-free valid job id")
    for field in ("autonomy_level", "standard_of_care", "objective", "timezone"):
        value = job.get(field)
        if not isinstance(value, str) or automation_orders_lint.has_control(value):
            raise ValueError(f"{job_id}: cron rendering field {field} must be single-line text")
    if job.get("enabled") is not True:
        raise ValueError(f"{job_id}: disabled jobs must not be rendered")
    normalized_root = automation_orders_lint.normalize_project_root(project_root)
    automation_orders_lint.manifest_relative_to_project(
        normalized_root,
        manifest_path,
    )
    errors, _warnings = automation_orders_lint.validate_manifest(
        {
            "schema_version": automation_orders_lint.SCHEMA_VERSION,
            "preferred_backend": "cron",
            "jobs": [job],
        },
        target="cron",
        project_root=normalized_root,
        manifest_path=manifest_path,
    )
    if errors:
        raise ValueError(
            f"{job_id}: cron rendering refused: " + "; ".join(errors)
        )
    cwd_errors: list[str] = []
    automation_orders_lint.normalized_job_cwd(
        f"{job['id']}: cwd",
        job["cwd"],
        normalized_root,
        cwd_errors,
        require_existing=True,
    )
    if cwd_errors:
        raise ValueError("; ".join(cwd_errors))
    manifest = manifest_path.expanduser().absolute()
    helper = Path(__file__).resolve().with_name("run_scheduled_job.py")
    python = Path(sys.executable).resolve(strict=True)
    expected_job_sha256, expected_runtime_bundle_sha256 = (
        run_scheduled_job.cron_render_digests(
            job,
            normalized_root,
            manifest,
        )
    )
    runner = shlex.join(
        [
            str(python),
            *run_scheduled_job.CRON_HELPER_PYTHON_FLAGS,
            str(helper),
            "--project-root",
            str(normalized_root),
            "--manifest",
            str(manifest),
            "--job-id",
            str(job["id"]),
            "--expected-runtime-bundle-sha256",
            expected_runtime_bundle_sha256,
            "--expected-job-sha256",
            expected_job_sha256,
        ]
    )
    if automation_orders_lint.has_control(runner):
        raise ValueError("cron runner paths and arguments must be single-line text")
    if "%" in runner:
        raise ValueError(
            "cron runner paths must not contain '%' because cron treats it as a command delimiter"
        )
    return "\n".join(
        [
            f"# {job['id']} | {job['autonomy_level']} | {job['standard_of_care']} | {job['objective']}",
            f"CRON_TZ={shlex.quote(str(job['timezone']))}",
            f"{job['schedule']} {runner}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a Cronie-compatible crontab file from standing automation orders.",
        allow_abbrev=False,
    )
    parser.add_argument("manifest", help="Path to AUTOMATION_ORDERS.json")
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Absolute selected project root that owns the manifest and relative job cwd values.",
    )
    parser.add_argument("--output", help="Output file for rendered cron entries. Prints to stdout when omitted.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().absolute()
    try:
        project_root = automation_orders_lint.normalize_project_root(
            args.project_root.expanduser()
        )
        automation_orders_lint.manifest_relative_to_project(
            project_root,
            manifest_path,
        )
        data = automation_orders_lint.load_manifest(manifest_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: invalid automation manifest input: {exc}")
        return 1
    errors, warnings = automation_orders_lint.validate_manifest(
        data,
        target="cron",
        project_root=project_root,
        manifest_path=manifest_path,
    )
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    if not isinstance(data, dict):
        print("ERROR: manifest must be a JSON object")
        return 1
    rendered = [
        "# Generated by scripts/render_cron.py",
        f"# Target backend: {RENDERER_BACKEND}",
        "# Review the commands before installing into crontab.",
        "",
    ]
    for warning in warnings:
        rendered.append(f"# WARNING: {warning}")
    if warnings:
        rendered.append("")
    jobs = data.get("jobs", [])
    if not isinstance(jobs, list):
        print("ERROR: jobs must be a list")
        return 1
    enabled_jobs = [job for job in jobs if isinstance(job, dict) and job.get("enabled") is True]
    if not enabled_jobs:
        print("ERROR: automation manifest has no enabled cron jobs to render")
        return 1
    for index, job in enumerate(enabled_jobs):
        if index:
            rendered.append("")
        try:
            rendered.append(render_job(job, project_root, manifest_path))
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"ERROR: {exc}")
            return 1
    output = "\n".join(rendered) + "\n"
    if args.output:
        try:
            safe_paths.write_text(Path(args.output), output, force=args.force)
        except (FileExistsError, ValueError) as exc:
            print(str(exc))
            return 1
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
