#!/usr/bin/env python3

"""Closed identity markers for framework-rendered project state."""

from __future__ import annotations

import json


GENERATED_STATE_ORIGIN = "master-prompt-agreement/project-state/v1"
MARKDOWN_STATE_MARKER = (
    f"<!-- mpa-generated-state-origin: {GENERATED_STATE_ORIGIN} -->"
)
JSON_STATE_ORIGIN_KEY = "mpa_generated_state_origin"
JSON_STATE_ORIGIN_VALUE = GENERATED_STATE_ORIGIN
STATE_IDENTITY_PROBE_BYTES = 4096
STATE_INPUT_MAX_BYTES = 1024 * 1024

_MARKDOWN_MARKER_LINE_BY_BASENAME = {
    "TODO.md": 3,
    "DECISIONS.md": 4,
    "FINDINGS.md": 0,
    "FRAMEWORK_FEEDBACK.md": 0,
    "PRECEDENTS.md": 0,
    "REVIEWER_LANE_FEEDBACK.md": 0,
    "SECURITY_VERIFICATION.md": 0,
    "SOURCE_MONITOR_RESEARCHER.md": 0,
    "SOURCE_PACKS.md": 0,
    "SOURCE_UPDATE.md": 0,
}


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def inspect_generated_state_origin(
    name: str,
    raw: bytes,
) -> tuple[bool, str | None]:
    """Classify one safely read closed state basename by its exact origin marker."""

    if len(raw) > STATE_INPUT_MAX_BYTES:
        return False, f"state input exceeds its byte bound of {STATE_INPUT_MAX_BYTES}"
    if name in _MARKDOWN_MARKER_LINE_BY_BASENAME:
        marker = MARKDOWN_STATE_MARKER.encode("utf-8")
        marker_prefix = b"<!-- mpa-generated-state-origin:"
        lines = raw.splitlines()
        expected_line = _MARKDOWN_MARKER_LINE_BY_BASENAME[name]
        marker_lines = [
            index
            for index, line in enumerate(lines)
            if marker_prefix in line
        ]
        if (
            len(lines) > expected_line
            and lines[expected_line] == marker
            and marker_lines == [expected_line]
            and raw.find(marker) < STATE_IDENTITY_PROBE_BYTES
        ):
            return True, None
        if marker_lines:
            return False, (
                "generated-state origin marker is malformed or outside its "
                f"canonical line for {name}"
            )
        return False, None
    if name == "AUTOMATION_ORDERS.json":
        try:
            payload: object = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_object_without_duplicate_keys,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            return False, f"generated-state JSON identity is not inspectable: {exc}"
        if not isinstance(payload, dict):
            return False, None
        if JSON_STATE_ORIGIN_KEY not in payload:
            return False, None
        if payload[JSON_STATE_ORIGIN_KEY] != JSON_STATE_ORIGIN_VALUE:
            return False, "generated-state JSON origin marker is malformed"
        return True, None
    return False, f"basename is outside the closed generated-state set: {name}"


def has_generated_state_origin(name: str, raw: bytes) -> bool:
    """Return whether one closed state basename carries its exact origin marker."""

    recognized, _error = inspect_generated_state_origin(name, raw)
    return recognized
