#!/usr/bin/env python3

"""Neutral lexical grammar for text projected into generated Markdown SOWs."""

from __future__ import annotations

import re


# Generated contract text must not be able to create parser-hidden policy or
# an undeclared Markdown control row. Patterns intentionally match whole rows
# so ordinary prose containing colons, hashes, or dashes remains valid.
GENERATED_SOW_COMMENT_TOKENS = ("<!--", "-->")
PYTHON_SPLITLINES_BOUNDARIES = (
    "\n",
    "\r",
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)
ECMASCRIPT_SPLITLINES_BOUNDARY = (
    r"(?:\r\n|[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029])"
)
ECMASCRIPT_NON_SPLITLINE_TEXT = r"[^\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]*"
# These ECMAScript-compatible patterns are also compiled by the Python
# validators.  Multiline scalar prose intentionally permits TAB, LF, NEL, LS,
# and PS; single-line generated values permit none of those boundaries.  Both
# reject non-scalar surrogate code points and terminal-active C1 controls.
ECMASCRIPT_MULTILINE_FORBIDDEN_CONTROL = (
    r"[\u0000-\u0008\u000b-\u001f\u007f-\u0084\u0086-\u009f\ud800-\udfff]"
)
ECMASCRIPT_SINGLE_LINE_FORBIDDEN_CONTROL = (
    r"[\u0000-\u001f\u007f-\u009f\u2028\u2029\ud800-\udfff]"
)
MULTILINE_FORBIDDEN_CONTROL_RE = re.compile(
    ECMASCRIPT_MULTILINE_FORBIDDEN_CONTROL
)
SINGLE_LINE_FORBIDDEN_CONTROL_RE = re.compile(
    ECMASCRIPT_SINGLE_LINE_FORBIDDEN_CONTROL
)
GENERATED_SOW_CONTROL_LINE_SYNTAX = (
    (
        "ATX heading",
        rf"[ \t]*#{{1,6}}(?:[ \t]+{ECMASCRIPT_NON_SPLITLINE_TEXT})?[ \t]*",
    ),
    (
        "Setext heading",
        r"[ \t]*(?:=+|-+)[ \t]*",
    ),
    (
        "thematic break",
        r"[ \t]*(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})",
    ),
    (
        "Markdown fence",
        rf"[ \t]*(?:`{{3,}}|~{{3,}}){ECMASCRIPT_NON_SPLITLINE_TEXT}",
    ),
)


def contains_splitlines_boundary(value: str) -> bool:
    """Match every boundary recognized by Python ``str.splitlines``."""

    return any(boundary in value for boundary in PYTHON_SPLITLINES_BOUNDARIES)


def generated_sow_control_syntax_kind(line: str) -> str | None:
    """Classify one forbidden generated-SOW control row, if present."""

    if any(token in line for token in GENERATED_SOW_COMMENT_TOKENS):
        return "HTML comment syntax"
    for label, pattern in GENERATED_SOW_CONTROL_LINE_SYNTAX:
        if re.fullmatch(pattern, line) is not None:
            return label
    return None


def ecmascript_literal(value: str) -> str:
    """Escape one literal for the bounded ECMAScript schema patterns."""

    syntax = frozenset(r"\.^$|?*+()[]{}")
    return "".join(
        ("\\" + character) if character in syntax else character
        for character in value
    )


def generated_sow_text_schema(*, single_line: bool) -> dict[str, object]:
    """Return the lexical JSON Schema for text rendered into a generated SOW."""

    constraints: list[dict[str, object]] = [
        {
            "not": {
                "pattern": (
                    ECMASCRIPT_SINGLE_LINE_FORBIDDEN_CONTROL
                    if single_line
                    else ECMASCRIPT_MULTILINE_FORBIDDEN_CONTROL
                )
            }
        }
    ]
    comment_alternatives = "|".join(
        ecmascript_literal(token) for token in GENERATED_SOW_COMMENT_TOKENS
    )
    constraints.append({"not": {"pattern": rf"(?:{comment_alternatives})"}})
    control_alternatives = "|".join(
        f"(?:{pattern})" for _label, pattern in GENERATED_SOW_CONTROL_LINE_SYNTAX
    )
    constraints.append(
        {
            "not": {
                "pattern": (
                    rf"(?:^|{ECMASCRIPT_SPLITLINES_BOUNDARY})"
                    rf"(?:{control_alternatives})"
                    rf"(?:{ECMASCRIPT_SPLITLINES_BOUNDARY}|$)"
                )
            }
        }
    )
    if single_line:
        constraints.append({"not": {"pattern": ECMASCRIPT_SPLITLINES_BOUNDARY}})
    return {"type": "string", "allOf": constraints}


def control_free_text_schema(*, single_line: bool = True) -> dict[str, object]:
    """Return a string schema carrying only the shared control invariant."""

    return {
        "type": "string",
        "allOf": [
            {
                "not": {
                    "pattern": (
                        ECMASCRIPT_SINGLE_LINE_FORBIDDEN_CONTROL
                        if single_line
                        else ECMASCRIPT_MULTILINE_FORBIDDEN_CONTROL
                    )
                }
            }
        ],
    }
