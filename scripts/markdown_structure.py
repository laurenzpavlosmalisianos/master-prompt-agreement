"""Small, shared structural primitives for Markdown-aware validators.

The helpers in this module deliberately implement only the fenced-code and
ATX-heading behavior that framework validators need.  They are not a Markdown
renderer and must not be used to infer semantic meaning from prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterator, Literal


FenceEvent = Literal["open", "content", "close"]

_FENCE_OPEN_RE = re.compile(
    r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<suffix>.*)$"
)


def _is_backslash_escaped(text: str, index: int) -> bool:
    """Return whether the character at ``index`` has an odd slash prefix."""

    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def _matching_backtick_run_end(text: str, start: int) -> int | None:
    """Return the end of a same-line code span beginning at ``start``."""

    opener_end = start
    while opener_end < len(text) and text[opener_end] == "`":
        opener_end += 1
    opener_length = opener_end - start
    cursor = opener_end
    while cursor < len(text):
        candidate = text.find("`", cursor)
        if candidate < 0:
            return None
        candidate_end = candidate
        while candidate_end < len(text) and text[candidate_end] == "`":
            candidate_end += 1
        if candidate_end - candidate == opener_length:
            return candidate_end
        cursor = candidate_end
    return None


def _find_html_comment_open(text: str, start: int) -> int:
    """Find an operative comment opener outside same-line code spans."""

    cursor = start
    while cursor < len(text):
        comment_start = text.find("<!--", cursor)
        if comment_start < 0:
            return -1
        tick_start = text.find("`", cursor, comment_start)
        if tick_start >= 0:
            if _is_backslash_escaped(text, tick_start):
                cursor = tick_start + 1
                continue
            span_end = _matching_backtick_run_end(text, tick_start)
            if span_end is not None:
                cursor = span_end
                continue
            cursor = tick_start + 1
            continue
        if _is_backslash_escaped(text, comment_start):
            cursor = comment_start + 1
            continue
        return comment_start
    return -1


@dataclass(slots=True)
class MarkdownFenceState:
    """Track the fenced-code subset shared by Markdown validators.

    Openers may have at most three leading spaces.  A closer must use the same
    delimiter character and at least the opener's delimiter length.  Backtick
    fence info strings containing a backtick are invalid openers.
    """

    character: str | None = None
    length: int = 0

    def consume(self, line: str) -> FenceEvent | None:
        """Classify ``line`` relative to this fence state and update it."""

        if self.character is not None:
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(self.character)}{{{self.length},}}[ \t]*",
                line,
            )
            if closing is not None:
                self.character = None
                self.length = 0
                return "close"
            return "content"

        opening = _FENCE_OPEN_RE.match(line)
        if opening is None:
            return None
        marker = opening.group("marker")
        suffix = opening.group("suffix")
        if marker.startswith("`") and "`" in suffix:
            return None
        self.character = marker[0]
        self.length = len(marker)
        return "open"


@dataclass(frozen=True, slots=True)
class MarkdownSection:
    """One unfenced ATX section and its original numbered body lines."""

    title: str
    heading_line: int
    lines: tuple[tuple[int, str], ...]


@dataclass(slots=True)
class MarkdownVisibilityState:
    """Track fences and multiline HTML comments for operative-line parsing."""

    fence: MarkdownFenceState = field(default_factory=MarkdownFenceState)
    in_html_comment: bool = False

    def consume(self, line: str) -> tuple[FenceEvent | None, str | None]:
        """Return a fence event or the line with HTML comments blanked."""

        if self.fence.character is not None:
            return self.fence.consume(line), None

        visible = list(line)
        cursor = 0
        while cursor < len(line):
            if self.in_html_comment:
                comment_start = cursor
                close_search_start = cursor
            else:
                comment_start = _find_html_comment_open(line, cursor)
                if comment_start < 0:
                    break
                # CommonMark permits the closing ``-->`` to overlap the final
                # two hyphens of short forms such as ``<!-->`` and ``<!--->``.
                close_search_start = comment_start + 2
            comment_end = line.find("-->", close_search_start)
            if comment_end < 0:
                visible[comment_start:] = " " * (len(line) - comment_start)
                self.in_html_comment = True
                break
            end = comment_end + 3
            visible[comment_start:end] = " " * (end - comment_start)
            self.in_html_comment = False
            cursor = end
        visible_line = "".join(visible)
        fence_event = self.fence.consume(visible_line)
        if fence_event is not None:
            return fence_event, None
        return None, visible_line


def operative_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield numbered non-fence lines with HTML comment spans blanked."""

    visibility = MarkdownVisibilityState()
    for line_number, line in enumerate(text.splitlines(), start=1):
        _fence_event, visible = visibility.consume(line)
        if visible is not None:
            yield line_number, visible


def markdown_sections(
    text: str,
    *,
    level: int = 2,
    include_fenced_content: bool = False,
) -> tuple[MarkdownSection, ...]:
    """Return unfenced, unindented ATX sections at exactly ``level``.

    Duplicate headings remain distinct and in source order.  Fenced examples
    are excluded by default.  A payload consumer may explicitly retain fences
    and their contents with ``include_fenced_content=True``.
    """

    if level < 1 or level > 6:
        raise ValueError("Markdown ATX heading level must be between 1 and 6")

    heading_re = re.compile(
        rf"^#{{{level}}}[ \t]+(?P<title>.+?)[ \t]*$"
    )
    visibility = MarkdownVisibilityState()
    sections: list[MarkdownSection] = []
    current_title: str | None = None
    current_heading_line = 0
    current_lines: list[tuple[int, str]] = []

    def finish_current() -> None:
        nonlocal current_title, current_heading_line, current_lines
        if current_title is None:
            return
        sections.append(
            MarkdownSection(
                title=current_title,
                heading_line=current_heading_line,
                lines=tuple(current_lines),
            )
        )

    for line_number, line in enumerate(text.splitlines(), start=1):
        fence_event, visible_line = visibility.consume(line)
        if fence_event is not None:
            if current_title is not None and include_fenced_content:
                current_lines.append((line_number, line))
            continue

        if visible_line is None:
            continue

        heading = heading_re.fullmatch(visible_line)
        if heading is not None:
            finish_current()
            current_title = heading.group("title").strip()
            current_heading_line = line_number
            current_lines = []
            continue

        if current_title is not None:
            current_lines.append((line_number, visible_line))

    finish_current()
    return tuple(sections)
