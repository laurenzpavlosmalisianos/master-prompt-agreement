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


def mask_inline_code_spans(text: str) -> str:
    """Return ``text`` with same-line backtick code spans replaced by spaces."""

    chars = list(text)
    cursor = 0
    while cursor < len(text):
        tick_start = text.find("`", cursor)
        if tick_start < 0:
            break
        if _is_backslash_escaped(text, tick_start):
            cursor = tick_start + 1
            continue
        span_end = _matching_backtick_run_end(text, tick_start)
        if span_end is None:
            cursor = tick_start + 1
            continue
        chars[tick_start:span_end] = " " * (span_end - tick_start)
        cursor = span_end
    return "".join(chars)


@dataclass(frozen=True, slots=True)
class FencedCodeBlock:
    """One fenced Markdown code block with 1-based line numbers."""

    info_string: str
    language: str
    opening_line: int
    closing_line: int | None
    lines: tuple[tuple[int, str], ...]


def fenced_code_blocks(
    text: str,
    *,
    language: str | None = None,
) -> tuple[FencedCodeBlock, ...]:
    """Return fenced code blocks outside HTML comments in source order."""

    target_language = language.casefold() if language is not None else None
    visibility = MarkdownVisibilityState()
    blocks: list[FencedCodeBlock] = []
    current_info = ""
    current_lang = ""
    current_open_line = 0
    current_lines: list[tuple[int, str]] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        was_in_fence = visibility.fence.character is not None
        fence_event, _visible = visibility.consume(line)
        if fence_event == "open" and not was_in_fence:
            opening = _FENCE_OPEN_RE.match(line)
            suffix = opening.group("suffix").strip() if opening is not None else ""
            current_info = suffix
            current_lang = suffix.split(None, 1)[0].casefold() if suffix else ""
            current_open_line = line_number
            current_lines = []
        elif fence_event == "content":
            current_lines.append((line_number, line))
        elif fence_event == "close":
            if target_language is None or current_lang == target_language:
                blocks.append(
                    FencedCodeBlock(
                        info_string=current_info,
                        language=current_lang,
                        opening_line=current_open_line,
                        closing_line=line_number,
                        lines=tuple(current_lines),
                    )
                )

    if visibility.fence.character is not None:
        if target_language is None or current_lang == target_language:
            blocks.append(
                FencedCodeBlock(
                    info_string=current_info,
                    language=current_lang,
                    opening_line=current_open_line,
                    closing_line=None,
                    lines=tuple(current_lines),
                )
            )
    return tuple(blocks)


_MERMAID_HEADER_RE = re.compile(
    r"^(?:(?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR)|sequenceDiagram|stateDiagram(?:-v2)?|classDiagram|erDiagram|xychart-beta)\s*$"
)
_MERMAID_FLOWCHART_HEADER_RE = re.compile(r"^(?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR)\s*$")
_MERMAID_HTML_TAG_RE = re.compile(r"(?<!<)</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*)?/?>(?!>)")
_MERMAID_EDGE_OPERATOR_PATTERN = (
    r"(?:<--+>|<-\.+->|<==+>|--+>|-\.+->|==+>|---+>|-\.+-|===+|~~~+|--+[ox]|-\.+-[ox]|==+[ox]|---)"
)
_MERMAID_PIPE_LABEL_RE = re.compile(
    rf"{_MERMAID_EDGE_OPERATOR_PATTERN}\s*\|(?P<label>[^|]*)\|"
)
_MERMAID_EDGE_OP_RE = re.compile(_MERMAID_EDGE_OPERATOR_PATTERN)
_MERMAID_SUBGRAPH_RE = re.compile(r"^subgraph\s+(?P<rest>.+?)\s*$")
_MERMAID_END_RE = re.compile(r"^end\s*$")
_MERMAID_NODE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*")


def _strip_mermaid_node_shapes(text: str) -> str:
    """Strip node shape payloads (`[...]`, `(...)`, `{...}`) after pipe removal."""

    result: list[str] = []
    depth = 0
    in_quotes = False
    for index, char in enumerate(text):
        if char == '"' and not _is_backslash_escaped(text, index):
            in_quotes = not in_quotes
            continue
        if in_quotes:
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}" and depth > 0:
            depth -= 1
            continue
        if depth == 0:
            result.append(char)
    return "".join(result)


def _parse_subgraph_id(rest: str) -> str:
    match = _MERMAID_NODE_ID_RE.match(rest)
    if match is not None:
        return match.group(0)
    return rest.strip()


def mermaid_diagram_errors(text: str, *, source: str = "<markdown>") -> list[str]:
    """Validate Mermaid fenced code blocks for lexer and subgraph invariants."""

    errors: list[str] = []
    for block in fenced_code_blocks(text, language="mermaid"):
        if block.closing_line is None:
            errors.append(
                f"{source}:{block.opening_line}: unclosed mermaid fenced code block"
            )
            continue

        statement_lines = [
            (line_no, raw.strip())
            for line_no, raw in block.lines
            if raw.strip() and not raw.strip().startswith("%%")
        ]
        if not statement_lines:
            errors.append(
                f"{source}:{block.opening_line}: empty mermaid fenced code block"
            )
            continue

        header_line_no, header_text = statement_lines[0]
        if _MERMAID_HEADER_RE.match(header_text) is None:
            errors.append(
                f"{source}:{header_line_no}: mermaid block must start with a supported diagram header"
            )
        is_flowchart = _MERMAID_FLOWCHART_HEADER_RE.match(header_text) is not None

        for line_no, raw in block.lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("%%"):
                continue
            html_match = _MERMAID_HTML_TAG_RE.search(stripped)
            if html_match is not None:
                errors.append(
                    f"{source}:{line_no}: mermaid block must not contain raw HTML tag {html_match.group(0)!r}"
                )
            for label_match in _MERMAID_PIPE_LABEL_RE.finditer(stripped):
                raw_label = label_match.group("label")
                inner = raw_label.strip()
                is_quoted = (
                    len(inner) >= 2
                    and inner.startswith('"')
                    and inner.endswith('"')
                    and '"' not in inner[1:-1].replace('\\"', "")
                )
                if not is_quoted and any(ch in inner for ch in "()[]{}"):
                    errors.append(
                        f"{source}:{line_no}: mermaid edge label |{raw_label}| contains unquoted shape delimiter"
                    )

        if not is_flowchart:
            continue

        subgraph_stack: list[tuple[str, int]] = []
        subgraph_ids: set[str] = set()
        subgraph_ancestry: dict[str, tuple[str, ...]] = {}
        explicit_node_owner: dict[str, str | None] = {}
        implicit_node_owner: dict[str, str | None] = {}
        edge_records: list[tuple[int, str, str | None, tuple[str, ...]]] = []

        for line_no, stripped in statement_lines[1:]:
            subgraph_match = _MERMAID_SUBGRAPH_RE.match(stripped)
            if subgraph_match is not None:
                sg_id = _parse_subgraph_id(subgraph_match.group("rest"))
                subgraph_ids.add(sg_id)
                subgraph_ancestry[sg_id] = tuple(s for s, _ in subgraph_stack) + (sg_id,)
                subgraph_stack.append((sg_id, line_no))
                continue
            if _MERMAID_END_RE.match(stripped) is not None:
                if not subgraph_stack:
                    errors.append(
                        f"{source}:{line_no}: unmatched 'end' in mermaid block"
                    )
                else:
                    subgraph_stack.pop()
                continue

            current_sg = subgraph_stack[-1][0] if subgraph_stack else None
            without_pipes = _MERMAID_PIPE_LABEL_RE.sub(
                lambda m: m.group(0).split("|", 1)[0] + " ",
                stripped,
            )
            bare_statement = _strip_mermaid_node_shapes(without_pipes)
            if _MERMAID_EDGE_OP_RE.search(bare_statement) is not None:
                endpoints: list[str] = []
                raw_segments = _MERMAID_EDGE_OP_RE.split(without_pipes)
                bare_segments = _MERMAID_EDGE_OP_RE.split(bare_statement)
                for raw_seg, bare_seg in zip(raw_segments, bare_segments):
                    for raw_part, bare_part in zip(raw_seg.split("&"), bare_seg.split("&")):
                        node_match = _MERMAID_NODE_ID_RE.match(bare_part.strip())
                        if node_match is not None:
                            node_id = node_match.group(0)
                            endpoints.append(node_id)
                            has_shape = any(ch in raw_part for ch in "([{")
                            if current_sg is not None:
                                if has_shape:
                                    explicit_node_owner.setdefault(node_id, current_sg)
                                else:
                                    implicit_node_owner.setdefault(node_id, current_sg)
                edge_records.append((line_no, stripped, current_sg, tuple(endpoints)))
            else:
                node_match = _MERMAID_NODE_ID_RE.match(bare_statement.strip())
                if node_match is not None:
                    node_id = node_match.group(0)
                    if node_id not in {"style", "classDef", "class", "click", "linkStyle", "direction"}:
                        if current_sg is not None:
                            explicit_node_owner.setdefault(node_id, current_sg)
                        else:
                            implicit_node_owner.setdefault(node_id, None)

        for sg_id, open_line in subgraph_stack:
            errors.append(
                f"{source}:{open_line}: unclosed 'subgraph {sg_id}' in mermaid block"
            )

        for line_no, raw_edge, edge_sg, edge_endpoints in edge_records:
            if edge_sg is None:
                continue
            for endpoint in edge_endpoints:
                if endpoint in subgraph_ids:
                    if edge_sg not in subgraph_ancestry.get(endpoint, ()):
                        errors.append(
                            f"{source}:{line_no}: cross-subgraph edge {raw_edge!r} declared inside subgraph {edge_sg!r}"
                        )
                        break
                    continue
                owner = explicit_node_owner.get(endpoint, implicit_node_owner.get(endpoint))
                if owner is not None and edge_sg not in subgraph_ancestry.get(owner, ()):
                    errors.append(
                        f"{source}:{line_no}: cross-subgraph edge {raw_edge!r} declared inside subgraph {edge_sg!r}"
                    )
                    break

    return errors
