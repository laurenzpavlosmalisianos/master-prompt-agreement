#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json

import recommend_stack
import verification_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a phased verification plan from task risk flags.",
        allow_abbrev=False,
    )
    for flag, help_text in recommend_stack.CLI_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
    return parser


def group_checks(
    checks: list[verification_registry.VerificationCheck],
) -> dict[str, list[dict[str, str | None]]]:
    """Group registry-owned check records without a parallel phase map."""

    grouped: dict[str, list[dict[str, str | None]]] = {
        phase: [] for phase in verification_registry.PHASES
    }
    for check in checks:
        canonical = verification_registry.get_check(check.check_id)
        if check != canonical:
            raise ValueError(
                f"non-canonical verification check object: {check.check_id}"
            )
        grouped[check.phase].append(check.as_report_item())
    return grouped


def main() -> int:
    args = build_parser().parse_args()
    schedule = recommend_stack.load_schedule()
    standard_of_care = recommend_stack.choose_standard_of_care(args)
    checks = recommend_stack.collect_required_checks(
        args, standard_of_care, schedule
    )
    result = {
        "schema_version": 1,
        "evidentiary_scope": recommend_stack.choose_evidentiary_scope(
            args, standard_of_care, schedule
        ),
        "phase_checks": group_checks(checks),
        "practice_guides": recommend_stack.collect_practice_guides(args, schedule),
        "second_review_recommended": recommend_stack.needs_second_review(
            args, standard_of_care
        ),
        "standard_of_care": standard_of_care,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
