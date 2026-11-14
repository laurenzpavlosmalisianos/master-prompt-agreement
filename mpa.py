#!/usr/bin/env python3
"""Set up, update, and check Master Prompt Agreement files in a project."""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

__version__ = "7.1.0"
# The version of templates/block.md. It changes only when the block text changes.
BLOCK_VERSION = "7.1.0"

FRAMEWORK_DIR = Path(__file__).resolve().parent
TEMPLATES = FRAMEWORK_DIR / "templates"
SKILLS = FRAMEWORK_DIR / "skills"
VERSION = tuple(int(part) for part in BLOCK_VERSION.split("."))
MAX_READ = 1 << 20
NOTE_SIZE, MAX_SIZE = 16 << 10, 32 << 10
MAX_WALK = 2000
SKILL_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills", "generic": ".agents/skills"}
IMPORTS = (("CLAUDE.md", "@AGENTS.md"), (".claude/CLAUDE.md", "@../AGENTS.md"))
GROUPS = {
    "core": ("mpa-review", "mpa-external-contribution", "mpa-incident", "mpa-dependency-change",
             "mpa-root-cause", "mpa-migration", "mpa-release", "mpa-research"),
    "security": ("mpa-secure-coding", "mpa-security-audit", "mpa-agent-inputs",
                 "mpa-agent-instructions", "mpa-data-privacy", "mpa-database"),
    "infra": ("mpa-ci-pipeline", "mpa-containers", "mpa-kubernetes", "mpa-infrastructure-as-code"),
    "web": ("mpa-web-frontend", "mpa-seo"),
    "languages": ("mpa-python", "mpa-javascript-typescript", "mpa-go", "mpa-rust", "mpa-swift",
                  "mpa-php", "mpa-shell"),
}
RULES = ".codex/rules/mpa.rules"
# SHA-256 of the rules file of 7.0.0; update replaces that file without --force.
RULES_7_0 = "8f98b1d5d1caffe49dff28abb48ab6fd404f7d631d3549a07c73d4884f3780bb"
# Skill names that update removes from a project without --remove-skill.
RETIRED = ()
ADOPTED = ("Commands", "Approvals", "Code latitude", "Constraints")
BEGIN = "<!-- mpa:begin {} (replaced by mpa.py update; edit outside this block) -->"
END = "<!-- mpa:end -->"
BEGIN_RE = re.compile(r"^<!-- mpa:begin (\d{1,4})\.(\d{1,4})\.(\d{1,4}) [^\r\n]*-->\r?$", re.M)
END_RE = re.compile(r"^<!-- mpa:end -->\r?$", re.M)
MARK_RE = re.compile(r"^<!-- mpa:(?:begin|end)\b", re.M)
H1_RE = re.compile(r"#[ \t]+\S")
NAME_RE = re.compile(r"mpa-[a-z0-9]+(-[a-z0-9]+)*")
TITLE_RE = re.compile(r"[A-Za-z0-9 ._-]+")
FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
COMMENT_RE = re.compile(r" {0,3}<!--")
GUIDES = ("## Guides\n\nTask guides are the `SKILL.md` files in the `mpa-*` directories under `.agents/skills/`."
          " Each has a `description` line at the top that says when it applies."
          " Read a guide before work that its description matches.")
IGNORE_HEAD = "# MPA working notes (local)"
# Only rev-parse and ls-files run. They read the index and no objects, and they apply no
# filter, diff driver, or text conversion.
GIT = ("git", "--no-pager", "--no-optional-locks", "--literal-pathspecs", "-c", "core.fsmonitor=false",
       "-c", "safe.bareRepository=explicit", "-c", "core.hooksPath=" + os.devnull)
GIT_ENV = {"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}


class Refuse(Exception):
    """A request that ends the run with exit code 1."""

    code = 1


class Usage(Refuse):
    """An invalid option value; exit code 2."""

    code = 2


class Step(NamedTuple):
    """One plan line. data is the bytes to write; extra is text printed under the line."""

    verb: str
    rel: str
    detail: str = ""
    data: bytes | None = None
    extra: str = ""


# --- files -------------------------------------------------------------------

def target(root, rel, is_dir=False):
    """Return root/rel after rejecting symbolic links, wrong file types, and escapes."""
    path, parts = root, Path(rel).parts
    for index, part in enumerate(parts):
        path = path / part
        folder = is_dir or index < len(parts) - 1
        if path.is_symlink():
            raise Refuse(f"{rel}: {path.relative_to(root).as_posix()} is a symbolic link")
        if path.exists() and not (path.is_dir() if folder else path.is_file()):
            kind = "a directory" if folder else "a regular file"
            raise Refuse(f"{rel}: {path.relative_to(root).as_posix()} is not {kind}")
    if root not in path.resolve().parents:
        raise Refuse(f"{rel}: outside the project")
    return path


def read(root, rel):
    """Return the bytes of root/rel, or None when the file is absent."""
    path = target(root, rel)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_READ:
        raise Refuse(f"{rel}: larger than 1 MiB")
    return path.read_bytes()


def lf(data):
    """Return data with CRLF line endings turned into LF; None stays None."""
    return None if data is None else data.replace(b"\r\n", b"\n")


def preset_bytes(name):
    return lf((TEMPLATES / "presets" / name).read_bytes())


def decode(data, rel):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refuse(f"{rel}: not UTF-8") from None


def write(root, rel, data):
    """Create root/rel exclusively, or replace it through a temporary file."""
    path = target(root, rel)
    os.makedirs(path.parent, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode & 0o7777
        fd, partial = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    else:
        mode, partial = None, path
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(partial, mode)
            os.replace(partial, path)
    except BaseException:
        if os.path.exists(partial):
            os.unlink(partial)
        raise


def preflight(root, steps):
    """Refuse a plan that would write to a file or directory without write permission."""
    for item in steps:
        if item.data is None and item.verb != "remove":
            continue
        path = target(root, item.rel, is_dir=item.verb == "remove")
        holder = path.parent
        while not holder.exists():
            holder = holder.parent
        for place in (path, holder):
            if place.exists() and not os.access(place, os.W_OK):
                raise Refuse(f"{place.relative_to(root).as_posix() or '.'} is not writable")


def git(root, *args):
    """Return the output of a git command run in root, or None when root is in no work tree
    that git accepts.

    git finds the repository itself, so its ownership check, GIT_CEILING_DIRECTORIES, and
    the filesystem boundary apply.
    """
    command = [*GIT, "-C", str(root), *args]
    env = {key: value for key, value in os.environ.items()
           if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    try:
        done = subprocess.run(command, capture_output=True, text=True, check=False,
                              stdin=subprocess.DEVNULL, env={**env, **GIT_ENV})
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def blob_id(data, width):
    """Return the git blob ID of data, as SHA-256 for a width of 64 and as SHA-1 otherwise."""
    digest = hashlib.sha256 if width == 64 else hashlib.sha1
    return digest(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


# --- text --------------------------------------------------------------------

def template(name):
    return (TEMPLATES / name).read_text(encoding="utf-8")


def newline(text):
    return "\r\n" if "\r\n" in text else "\n"


def scan(text):
    """Return the (offset, line, plain) triples of text, and whether it ends inside a code fence
    or an HTML comment that starts a line. plain is false for the lines of a fence or such a comment."""
    rows, fence, comment, offset = [], "", False, 0
    for row in text.splitlines(keepends=True):
        bare, plain = row.rstrip("\r\n"), False
        opener = FENCE_RE.match(bare)
        if fence:
            if re.fullmatch(rf" {{0,3}}{fence[0]}{{{len(fence)},}}[ \t]*", bare):
                fence = ""
        elif comment:
            comment = "-->" not in bare
        elif opener and not (opener[1][0] == "`" and "`" in opener[2]):
            fence = opener[1]
        elif COMMENT_RE.match(bare):
            comment = "-->" not in bare.split("<!--", 1)[1]
        else:
            plain = True
        rows.append((offset, bare, plain))
        offset += len(row)
    return rows, bool(fence) or comment


def outline(text):
    """Return the (offset, title) pairs of the H2 headings outside code fences and HTML comments,
    and whether the text ends inside either."""
    rows, unclosed = scan(text)
    heads = [(offset, bare[3:].strip()) for offset, bare, plain in rows
             if plain and bare.startswith("## ") and bare[3:].strip()]
    return heads, unclosed


def titles(text):
    return {title for _, title in outline(text)[0]}


def section(text, title):
    """Return one H2 section of text, heading included, or "" when it is absent."""
    text = text.replace("\r\n", "\n")
    heads = outline(text)[0]
    for index, (offset, name) in enumerate(heads):
        if name == title:
            end = heads[index + 1][0] if index + 1 < len(heads) else len(text)
            return text[offset:end].strip()
    return ""


def block_text():
    return f"{BEGIN.format(BLOCK_VERSION)}\n{template('block.md').strip()}\n{END}"


def insert_top(text, payload):
    """Insert payload after a leading H1 line, else at the top. Return (text, position)."""
    bom = "﻿" if text.startswith("﻿") else ""
    text = text[len(bom):]
    nl = newline(text)
    payload = payload.replace("\n", nl)
    cut = text.find("\n") + 1 or len(text)
    if not H1_RE.match(text):
        return bom + payload + nl + (nl + text if text else ""), "at the top"
    head, rest = text[:cut], text[cut:]
    if not head.endswith("\n"):
        head += nl
    gap = "" if not rest or rest.startswith(("\n", "\r\n")) else nl
    return bom + head + nl + payload + nl + gap + rest, "after line 1"


def append_end(text, payload):
    nl = newline(text)
    gap = "" if text.endswith("\n") else nl
    return text + gap + nl + payload.replace("\n", nl) + nl


def has_import(text, line):
    """Report whether a line outside code fences and HTML comments is exactly the import line."""
    return any(plain and bare.rstrip() == line for _, bare, plain in scan(text.lstrip("\ufeff"))[0])


def find_block(text):
    """Return (start, end, version) of the managed block, or None when no marker line exists."""
    skip = len("﻿") if text.startswith("﻿") else 0
    body = text[skip:]
    marks = len(MARK_RE.findall(body))
    if marks == 0:
        return None
    begins, ends = list(BEGIN_RE.finditer(body)), list(END_RE.finditer(body))
    if marks != 2 or len(begins) != 1 or len(ends) != 1 or ends[0].start() < begins[0].end():
        raise Refuse("AGENTS.md: block markers are malformed or duplicated")
    end = ends[0].end()
    if body[end - 1] == "\r":
        end -= 1
    return skip + begins[0].start(), skip + end, tuple(int(part) for part in begins[0].groups())


def ignore_lines(data):
    """Return .gitignore bytes with the notes entry added, or None when it is present."""
    text = decode(data or b"", ".gitignore")
    if re.search(r"^/?TODO\.md\r?$", text, re.M):
        return None
    nl = newline(text)
    lead = "" if not text else nl if text.endswith("\n") else nl * 2
    return f"{text}{lead}{IGNORE_HEAD}{nl}/TODO.md{nl}".encode()


def indent(text):
    return "\n".join("    " + row for row in text.splitlines())


def count(number, word):
    return f"{number} {word}{'' if number == 1 else 's'}"


def add_guides(text):
    """Add the Guides section at the end of the AGENTS.md text, or after the managed block
    when the text ends inside a code fence or an HTML comment. Return (text, position)."""
    if not outline(text)[1]:
        return append_end(text, GUIDES), "at the end"
    end, nl = find_block(text)[1], newline(text)
    return text[:end] + nl * 2 + GUIDES.replace("\n", nl) + text[end:], "after the block"


# --- skills ------------------------------------------------------------------

def shipped(name):
    path = SKILLS / name / "SKILL.md"
    if not NAME_RE.fullmatch(name) or not path.is_file():
        raise Usage(f"unknown skill or group: {name}")
    return lf(path.read_bytes())


def shipped_names():
    return sorted(p.name for p in SKILLS.glob("mpa-*") if (p / "SKILL.md").is_file())


def skill_name(item):
    return item if item.startswith("mpa-") else "mpa-" + item


def skill_names(option, items):
    """Return the skill names that an update option holds. A group name is a usage error."""
    for item in items:
        if item in (*GROUPS, "all", "none"):
            raise Usage(f"{option} takes skill names, and {item} is a group; only init --skills takes groups")
    return [skill_name(item) for item in items]


def select_skills(spec):
    """Expand a comma list of groups and skill names into skill names."""
    names = []
    for item in filter(None, (part.strip() for part in spec.split(","))):
        if item == "none":
            found = []
        elif item == "all":
            found = shipped_names()
        elif item in GROUPS:
            found = GROUPS[item]
        else:
            found = [skill_name(item)]
        for name in found:
            shipped(name)
            if name not in names:
                names.append(name)
    return names


def select_runtimes(spec, required):
    names = [part.strip() for part in spec.split(",") if part.strip()]
    if [name for name in names if name not in SKILL_DIRS] or (required and not names):
        raise Usage(f"--runtime takes a comma list of {', '.join(SKILL_DIRS)}")
    return names


def installed(root, rel):
    """Return the names of the mpa-* entries under one skills directory."""
    path = target(root, rel, is_dir=True)
    if not path.is_dir():
        return []
    return sorted(p.name for p in path.iterdir() if NAME_RE.fullmatch(p.name))


def other_files(root, rel):
    """Return the names in a skill directory other than SKILL.md."""
    target(root, rel + "SKILL.md")
    return sorted(p.name for p in (root / rel).iterdir() if p.name != "SKILL.md")


# --- plans -------------------------------------------------------------------

def show(steps):
    for item in steps:
        print(f"{item.verb:<9}{item.rel}" + (f"  ({item.detail})" if item.detail else ""))
        for row in item.extra.splitlines():
            print("    " + row)


def pending(steps):
    return [item for item in steps if item.data is not None or item.verb == "remove"]


def apply(root, steps):
    """Write every step that carries data, AGENTS.md last, and remove the marked skill directories."""
    done = []
    for item in sorted(pending(steps), key=lambda item: item.rel == "AGENTS.md"):
        try:
            if item.verb == "remove":
                path = target(root, item.rel + "SKILL.md")
                if path.exists():
                    os.unlink(path)
                os.rmdir(path.parent)
            else:
                write(root, item.rel, item.data)
        except (OSError, Refuse) as exc:
            reason = exc.strerror if isinstance(exc, OSError) else str(exc)
            raise Refuse(f"{item.rel}: {reason}; completed: {', '.join(done) or 'nothing'}") from None
        done.append(item.rel)
    return len(done)


def plan_agents(root, runtimes, skills):
    """Return the plan steps for AGENTS.md and the bytes the file will hold."""
    current = read(root, "AGENTS.md")
    skeleton = template("AGENTS.template.md")
    guides = GUIDES if "generic" in runtimes and (skills or installed(root, SKILL_DIRS["generic"])) else ""
    if current is None:
        name = root.name if TITLE_RE.fullmatch(root.name) else "Project"
        text = skeleton.replace("{block}", block_text()).replace("{name}", name)
        new = (text + (f"\n{guides}\n" if guides else "")).encode()
        return [Step("create", "AGENTS.md", "", new)], new
    text = decode(current, "AGENTS.md")
    found = find_block(text)
    if found is not None:
        if found[2] != VERSION:
            raise Refuse("AGENTS.md holds a managed block of another version; use update")
        if guides and "Guides" not in titles(text):
            new, where = add_guides(text)
            return [Step("append", "AGENTS.md", f"Guides section {where}", new.encode())], new.encode()
        return [Step("keep", "AGENTS.md", "managed block present")], current
    heads, unclosed = outline(text)
    present = {title for _, title in heads}
    missing = [title for title in ADOPTED if title not in present]
    parts = [section(skeleton, title) for title in missing]
    if guides and "Guides" not in present:
        missing.append("Guides")
        parts.append(guides)
    tail = "\n\n".join(parts)
    new, where = insert_top(text, block_text() + ("\n\n" + tail if tail and unclosed else ""))
    detail = f"managed block {BLOCK_VERSION} {where}"
    if tail:
        if not unclosed:
            new = append_end(new, tail)
        place = "after the block" if unclosed else "at the end"
        detail += f"; {', '.join(missing)} {'section' if len(missing) == 1 else 'sections'} {place}"
    steps = [Step("insert", "AGENTS.md", detail, new.encode())]
    if "Approvals" in present:
        steps.append(Step("note", "AGENTS.md keeps its existing ## Approvals section. Review it."))
    return steps, new.encode()


def claude_file(root):
    """Return (path, import line, bytes or None, linked) for the CLAUDE.md that carries the import.

    linked is true when the path is a symbolic link to AGENTS.md.
    """
    for rel, line in IMPORTS:
        path = root / rel
        if path.is_symlink() and path.resolve() == root / "AGENTS.md":
            return rel, line, None, True
        data = read(root, rel)
        if data is not None:
            return rel, line, data, False
    return *IMPORTS[0], None, False


def plan_claude(root):
    rel, line, data, linked = claude_file(root)
    if linked:
        return Step("keep", rel, "symbolic link to AGENTS.md")
    if data is None:
        return Step("create", rel, "", (line + "\n").encode())
    text = decode(data, rel)
    if has_import(text, line):
        return Step("keep", rel, "import present")
    text, where = insert_top(text, line)
    return Step("insert", rel, f"import line {where}", text.encode())


def load_settings(data):
    """Return the settings object, or None when data is not a JSON object."""
    try:
        doc = json.loads(data)
    except (ValueError, RecursionError):
        return None
    return doc if isinstance(doc, dict) else None


def merge_settings(doc, preset):
    """Add the missing preset rules to doc. Return (added, withheld) rules, or None when
    the permission lists are malformed.

    A `!` deny rule is withheld when the deny list already holds rules.
    """
    perms = doc.setdefault("permissions", {})
    if not isinstance(perms, dict) or not all(isinstance(perms.get(key, []), list) for key in ("allow", "ask", "deny")):
        return None
    added, withheld = [], []
    for key in ("ask", "deny"):
        rules = perms.setdefault(key, [])
        guarded = key == "deny" and bool(rules)
        for rule in preset["permissions"][key]:
            if rule in rules:
                continue
            if guarded and "(!" in rule:
                withheld.append(rule)
            else:
                rules.append(rule)
                added.append((key, rule))
    return added, withheld


def command_globs(rule):
    """Return the command patterns of a Bash permission rule; none for another rule.

    A trailing ":*" is the older spelling of " *". A trailing " *" that is the only
    wildcard also matches the command without arguments.
    """
    if rule == "Bash":
        return ["*"]
    if not (isinstance(rule, str) and rule.startswith("Bash(") and rule.endswith(")")):
        return []
    glob = rule[5:-1]
    if glob.endswith(":*"):
        glob = glob[:-2] + " *"
    return [glob, glob[:-2]] if glob.endswith(" *") and glob.count("*") == 1 else [glob]


def globs_meet(one, two):
    """Report whether some string matches both patterns; * is the only wildcard."""
    seen, todo = set(), [(0, 0)]
    while todo:
        i, j = todo.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(one) and j == len(two):
            return True
        a, b = one[i:i + 1], two[j:j + 1]
        if a == "*":
            todo += [(i + 1, j)] + ([(i, j + 1)] if b else [])
        if b == "*":
            todo += [(i, j + 1)] + ([(i + 1, j)] if a else [])
        if a and a == b and a != "*":
            todo.append((i + 1, j + 1))
    return False


def overlap(first, second):
    """Report whether two Bash permission rules can match the same command."""
    return any(globs_meet(one, two) for one in command_globs(first) for two in command_globs(second))


def plan_claude_preset(root):
    rel = ".claude/settings.json"
    preset = preset_bytes("claude-settings.json")
    current = read(root, rel)
    if current is None:
        return [Step("create", rel, "", preset)]
    doc = load_settings(current)
    merged = None if doc is None else merge_settings(doc, json.loads(preset))
    if merged is None:
        detail = "not a JSON object with permission lists; add the rules by hand"
        return [Step("keep", rel, detail, None, preset.decode())]
    added, withheld = merged
    perms = doc["permissions"]
    sets = [name for name in ("hooks", "env", "claudeMdExcludes") if name in doc]
    sets += [f"permissions.{name}" for name in ("allow", "defaultMode") if name in perms]
    steps = []
    rows = [f"{key:<5}{rule}" for key, rule in added]
    if withheld:
        rows.append("not added; a `!` rule also loosens the deny rules already in the file: " + ", ".join(withheld))
    covered = [rule for rule in perms.get("allow", [])
               if any(key == "ask" and overlap(rule, new) for key, new in added)]
    if covered:
        rows.append("added ask rules prompt for commands that these allow rules cover: " + ", ".join(covered))
    if added:
        asks = len([key for key, _ in added if key == "ask"])
        detail = f"+{asks} ask, +{len(added) - asks} deny; rewritten with two-space indentation"
        data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()
        steps.append(Step("merge", rel, detail, data, "\n".join(rows)))
    else:
        steps.append(Step("keep", rel, "preset rules present", None, "\n".join(rows)))
    if sets:
        steps.append(Step("note", f"{rel} sets {', '.join(sets)}. This script does not review it."))
    return steps


def plan_presets(root, runtimes):
    steps = plan_claude_preset(root) if "claude" in runtimes else []
    if "codex" in runtimes:
        for rel, name in ((".codex/config.toml", "codex-config.toml"), (RULES, "codex.rules")):
            preset = preset_bytes(name)
            current = read(root, rel)
            if current is None:
                steps.append(Step("create", rel, "", preset))
            elif lf(current) == preset:
                steps.append(Step("keep", rel, "identical"))
            elif rel == RULES:
                steps.append(Step("keep", rel, "differs from the shipped rules; run update"))
            else:
                steps.append(Step("keep", rel, "exists; add the content by hand", None, preset.decode()))
    return steps


def plan_state(root, state):
    if state == "none":
        return []
    steps = []
    if read(root, "TODO.md") is None:
        steps.append(Step("create", "TODO.md", "", template("TODO.md").encode()))
    else:
        local = "; git ignores it only while it is untracked" if state == "local" else ""
        steps.append(Step("keep", "TODO.md", "exists" + local))
    if state == "local":
        current = read(root, ".gitignore")
        new = ignore_lines(current)
        if new:
            steps.append(Step("create" if current is None else "append", ".gitignore", "/TODO.md", new))
    return steps


def plan_init(root, runtimes, skills, preset, state):
    claude = "claude" in runtimes
    rel, _, data, _ = claude_file(root) if claude else (None, None, None, False)
    held = {"AGENTS.md": read(root, "AGENTS.md"), rel: data}
    for name, content in held.items():
        if b"mpa-entrypoint-contract" in (content or b""):
            raise Refuse(f"{name} holds a 6.x setup; follow docs/migrating-from-v6.md")
    steps, agents = plan_agents(root, runtimes, skills)
    adopted = steps[0].verb in ("create", "insert")
    if claude:
        steps.insert(1, plan_claude(root))
    conflicts = []
    for folder in sorted({SKILL_DIRS[name] for name in runtimes}):
        for name in skills:
            path = f"{folder}/{name}/SKILL.md"
            current = read(root, path)
            if current is None:
                steps.append(Step("create", path, "", shipped(name)))
            elif lf(current) == shipped(name):
                steps.append(Step("keep", path, "identical"))
            else:
                conflicts.append(path)
    if conflicts:
        raise Refuse("existing files differ from the shipped skills: " + ", ".join(conflicts))
    if preset:
        steps += plan_presets(root, runtimes)
    steps += plan_state(root, state)
    if len(agents) > MAX_SIZE:
        raise Refuse("AGENTS.md would exceed 32 KiB, the default size at which Codex stops reading instruction files")
    existing = [name for name, content in held.items() if content is not None]
    if existing and adopted:
        verb = "keeps its" if len(existing) == 1 else "keep their"
        steps.append(Step("note", f"{' and '.join(existing)} {verb} existing text. This script does not review it."))
    if len(agents) > NOTE_SIZE:
        steps.append(Step("note", "AGENTS.md exceeds 16 KiB. Antigravity truncates a rule file at 24,000 bytes,"
                                  " and Codex stops reading instruction files at 32 KiB by default."))
    if (root / "AGENTS.override.md").exists():
        steps.append(Step("note", "AGENTS.override.md exists. Codex reads it in place of AGENTS.md in this directory."))
    if claude and (root / "CLAUDE.local.md").exists():
        steps.append(Step("note", "CLAUDE.local.md exists. Claude Code loads it together with CLAUDE.md."))
    return sorted(steps, key=lambda item: item.verb == "note")


def plan_block(text, force):
    """Return the step that replaces the managed block in the AGENTS.md text, or None."""
    found = find_block(text)
    if found is None:
        raise Refuse("AGENTS.md has no managed block; run init")
    start, end, version = found
    old, new = text[start:end].replace("\r\n", "\n"), block_text()
    label = ".".join(map(str, version))
    if version > VERSION:
        raise Refuse(f"block version {label} is newer than {BLOCK_VERSION}; use a newer checkout."
                     f" The block in AGENTS.md reads:\n{indent(old)}")
    if old == new:
        return None
    foreign = sorted(titles(old) - titles(new))
    if foreign and not force:
        raise Refuse(f"the managed block holds headings that the shipped block lacks ({', '.join(foreign)})."
                     " update replaces everything between the markers; move that text out of the block"
                     " or pass --force")
    detail = (f"managed block {label} -> {BLOCK_VERSION}; {count(len(old.splitlines()), 'line')}"
              f" replaced by {len(new.splitlines())}")
    return Step("replace", "AGENTS.md", detail, (text[:start] + new.replace("\n", newline(text)) + text[end:]).encode())


def plan_update(root, add, remove, runtimes, force):
    text = decode(read(root, "AGENTS.md") or b"", "AGENTS.md")
    first, steps, guided = plan_block(text, force), [], False
    add = skill_names("--add-skill", add)
    remove = set(skill_names("--remove-skill", remove))
    for name in add:
        if name not in shipped_names():
            raise Usage(f"unknown skill: {name}; skills/README.md lists the skill names")
    folders = sorted(set(SKILL_DIRS.values()))
    held = {folder: installed(root, folder) for folder in folders}
    receiving = sorted({SKILL_DIRS[name] for name in runtimes}) or [f for f in folders if held[f]]
    if add and not receiving:
        raise Refuse("no installed skill shows which runtimes the project uses; pass --runtime with --add-skill")
    available = set(shipped_names())
    for name in sorted(remove - {name for names in held.values() for name in names}):
        steps.append(Step("note", f"{name} is not installed."))
    for folder in folders:
        wanted = {*held[folder], *(add if folder in receiving else ())}
        for name in sorted(wanted):
            rel = f"{folder}/{name}/"
            if name in remove or name in RETIRED:
                if name not in held[folder]:
                    continue
                if other_files(root, rel):
                    steps.append(Step("keep", rel, "holds files other than SKILL.md"))
                else:
                    steps.append(Step("remove", rel))
                    continue
            elif name not in available:
                steps.append(Step("note", f"{rel} is not a shipped skill and is kept. check reports it as an error"
                                          f" until it is removed (--remove-skill {name}) or renamed without the"
                                          " mpa- prefix."))
            else:
                current = read(root, rel + "SKILL.md")
                if lf(current) != shipped(name):
                    verb = "create" if current is None else "replace"
                    steps.append(Step(verb, rel + "SKILL.md", "", shipped(name)))
            guided = guided or folder == SKILL_DIRS["generic"]
    rules = lf(read(root, RULES))
    if rules is not None and rules != preset_bytes("codex.rules"):
        if hashlib.sha256(rules).hexdigest() != RULES_7_0 and not force and not rules.startswith(b"# Managed by mpa.py"):
            raise Refuse(f"{RULES} holds project edits; move them to another .rules file in that directory,"
                         " or pass --force")
        steps.append(Step("replace", RULES, "", preset_bytes("codex.rules")))
    current = text if first is None else first.data.decode()
    if "generic" in runtimes and guided and "Guides" not in titles(current):
        new, where = add_guides(current)
        if first is None:
            first = Step("append", "AGENTS.md", f"Guides section {where}", new.encode())
        else:
            first = first._replace(detail=f"{first.detail}; Guides section {where}", data=new.encode())
    return ([] if first is None else [first]) + steps


def guard(root, steps):
    """Return why git cannot restore a file that the steps change or remove, or None when it can.

    A file passes when the index holds it once and its bytes hash to the indexed blob ID.
    The hash is computed here, so git runs no clean filter on the file.
    """
    paths = {item.rel + "SKILL.md" if item.verb == "remove" else item.rel
             for item in steps if item.verb in ("replace", "remove", "append")}
    paths = sorted(rel for rel in paths if (root / rel).is_file())
    if not paths:
        return None
    listed = git(root, "ls-files", "-s", "-z", "--", *paths)
    if listed is None:
        return "the project is not a git work tree; pass --force to update without one"
    index = {}
    for row in filter(None, listed.split("\0")):
        entry, _, rel = row.partition("\t")
        index.setdefault(rel, []).append(entry.split()[1])
    loose = [rel for rel in paths if rel not in index]
    if loose:
        return ("git does not track these files, so it cannot restore them: " + ", ".join(loose)
                + "; commit them or pass --force")
    changed = [rel for rel in paths if len(index[rel]) != 1 or index[rel][0] not in
               {blob_id(data, len(index[rel][0])) for data in (read(root, rel), lf(read(root, rel)))}]
    if changed:
        return ("these files have unstaged changes: " + ", ".join(changed)
                + "; stage or commit them or pass --force")
    return None


# --- check -------------------------------------------------------------------

def check_agents(root, errors, notes):
    data = read(root, "AGENTS.md")
    if data is None:
        raise Refuse("AGENTS.md is missing")
    text = decode(data, "AGENTS.md")
    found = find_block(text)
    if found is None:
        raise Refuse("AGENTS.md has no managed block; run init")
    start, end, version = found
    before = [row for row in text[:start].lstrip("﻿").splitlines() if row.strip()]
    if len(before) > 1 or (before and not H1_RE.match(before[0])):
        errors.append("AGENTS.md: text other than one H1 line precedes the managed block")
    label = ".".join(map(str, version))
    if version < VERSION:
        errors.append(f"AGENTS.md: block version {label} is older than {BLOCK_VERSION}; run update")
    elif version > VERSION:
        errors.append(f"AGENTS.md: block version {label} is newer than {BLOCK_VERSION}; use a newer checkout")
    elif text[start:end].replace("\r\n", "\n") != block_text():
        errors.append("AGENTS.md: managed block differs from the shipped text; run update")
    if len(data) > MAX_SIZE:
        errors.append("AGENTS.md is larger than 32 KiB; Codex stops reading instruction files at that size by default")
    elif len(data) > NOTE_SIZE:
        notes.append("AGENTS.md is larger than 16 KiB; Antigravity truncates a rule file at 24,000 bytes,"
                     " and Codex stops reading at 32 KiB by default")
    if "Approvals" not in titles(text):
        notes.append("AGENTS.md has no ## Approvals heading")
    rows = set(text.replace("\r\n", "\n").split("\n"))
    unedited = [row for row in template("AGENTS.template.md").splitlines() if row.startswith("<!--") and row in rows]
    if unedited:
        notes.append(f"AGENTS.md: {count(len(unedited), 'placeholder comment')} from the template"
                     f" {'is' if len(unedited) == 1 else 'are'} unedited")
    empty = re.findall(r"^- [^:\n]+:[ \t]*$", section(text, "Commands"), re.M)
    if empty:
        notes.append(f"AGENTS.md: {count(len(empty), 'command line')} under ## Commands"
                     f" {'is' if len(empty) == 1 else 'are'} empty")


def check_claude(root, errors, notes):
    rel, line, data, linked = claude_file(root)
    if data is None and not linked:
        tail = "; init --runtime claude adds the import"
        if (root / "CLAUDE.local.md").exists():
            notes.append("CLAUDE.local.md exists and no CLAUDE.md imports AGENTS.md;"
                         " Claude Code then does not read AGENTS.md" + tail)
        elif installed(root, SKILL_DIRS["claude"]) or (root / ".claude/settings.json").exists():
            notes.append("no CLAUDE.md imports AGENTS.md; Claude Code before 2.1.277, or with a CLAUDE.md"
                         " in a directory above, does not read AGENTS.md" + tail)
    if data is not None and not has_import(decode(data, rel), line):
        errors.append(f"{rel}: no line that is exactly {line} outside code fences and HTML comments")


def check_skills(root, errors, notes):
    known = set(shipped_names())
    for folder in sorted(set(SKILL_DIRS.values())):
        for name in installed(root, folder):
            rel = f"{folder}/{name}/"
            if name not in known:
                errors.append(f"{rel} is not a shipped skill; rename it without the mpa- prefix or remove it")
                continue
            extra = other_files(root, rel)
            if extra:
                errors.append(f"{rel} holds files other than SKILL.md: {', '.join(extra)}")
            if lf(read(root, rel + "SKILL.md")) != shipped(name):
                errors.append(f"{rel}SKILL.md differs from the shipped text; run update")


def check_settings(root, errors, notes):
    rel, _, data, linked = claude_file(root)
    watched = ["AGENTS.md", *([rel] if data is not None or linked else [])]
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        data = read(root, rel)
        if data is None:
            continue
        doc = load_settings(data)
        if doc is None:
            errors.append(f"{rel} is not a JSON object")
            continue
        patterns = doc.get("claudeMdExcludes")
        for pattern in patterns if isinstance(patterns, list) else []:
            if not isinstance(pattern, str) or len(pattern) > 500:
                continue
            hit = [name for name in watched
                   if fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase((root / name).as_posix(), pattern)]
            if hit:
                errors.append(f"{rel}: claudeMdExcludes entry {pattern} covers {hit[0]}")


def nested_files(root):
    """Return instruction files below the project root, outside hidden and node_modules directories,
    and whether the scan stopped at the directory limit."""
    found, seen = [], 0
    for folder, folders, names in os.walk(root):
        folders[:] = sorted(name for name in folders if not name.startswith(".") and name != "node_modules")
        seen += 1
        if seen > MAX_WALK:
            return found, True
        if Path(folder) != root:
            found += [(Path(folder) / name).relative_to(root).as_posix()
                      for name in ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md") if name in names]
    return found, False


def check_surfaces(root, errors, notes):
    if (root / "AGENTS.override.md").exists():
        errors.append("AGENTS.override.md exists; Codex reads it in place of AGENTS.md in this directory")
    if (root / "CLAUDE.local.md").exists():
        notes.append("CLAUDE.local.md exists; Claude Code loads it together with CLAUDE.md")
    if (root / ".claude/rules").exists():
        notes.append(".claude/rules exists; Claude Code loads the rule files in it")
    rules = read(root, RULES)
    if rules is not None and lf(rules) != preset_bytes("codex.rules"):
        errors.append(f"{RULES} differs from the shipped rules; run update")
    config = read(root, ".codex/config.toml")
    if config is not None and lf(config) != preset_bytes("codex-config.toml"):
        notes.append(".codex/config.toml differs from the preset; Codex applies it in a trusted project")
    nested, stopped = nested_files(root)
    if nested:
        more = f" and {len(nested) - 5} more" if len(nested) > 5 else ""
        notes.append("Codex reads an AGENTS.md in a subdirectory, and Claude Code reads it only through a CLAUDE.md"
                     f" beside it: {', '.join(nested[:5])}{more}")
    if stopped:
        notes.append(f"the scan for instruction files in subdirectories stopped after {MAX_WALK} directories")


def check_state(root, errors, notes):
    ignore = decode(read(root, ".gitignore") or b"", ".gitignore")
    listed = re.search(r"^/?TODO\.md\r?$", ignore, re.M)
    if listed and git(root, "ls-files", "--error-unmatch", "--", "TODO.md") is not None:
        notes.append("TODO.md is tracked by git and also listed in .gitignore")


# --- commands ----------------------------------------------------------------

def cmd_init(root, args):
    runtimes = select_runtimes(args.runtime, required=True)
    steps = plan_init(root, runtimes, select_skills(args.skills), args.preset, args.state)
    preflight(root, steps)
    for item in [item for item in steps if item.verb in ("insert", "merge", "append")]:
        if guard(root, [item._replace(verb="replace")]):
            steps.append(Step("note", f"{item.rel} is not committed; git cannot restore the old text"))
    show(steps)
    if not pending(steps):
        print("nothing to do")
    elif not args.write:
        print("dry run: nothing changed; add --write to apply")
    else:
        print(f"applied: {count(apply(root, steps), 'file')} written")
    return 0


def cmd_update(root, args):
    runtimes = select_runtimes(args.runtime, required=False)
    steps = plan_update(root, args.add_skill, args.remove_skill, runtimes, args.force)
    preflight(root, steps)
    blocked = None if args.force else guard(root, steps)
    kept = [item.rel for item in steps if item.verb == "keep"]
    show(steps)
    if not pending(steps):
        if not kept:
            print("up to date")
    elif blocked and args.write:
        raise Refuse(blocked)
    elif blocked:
        show([Step("refuse", blocked)])
        print("dry run: nothing changed; --write refuses this plan")
    elif not args.write:
        print("dry run: nothing changed; add --write to apply")
    else:
        print(f"applied: {count(apply(root, steps), 'change')}")
        if git(root, "rev-parse", "--is-inside-work-tree") == "true\n":
            print("review with: git status and git diff")
    if kept:
        print(f"not removed: {', '.join(kept)}; delete the files other than SKILL.md and run update again",
              file=sys.stderr)
        return 1
    return 0


def cmd_check(root, args):
    errors, notes = [], []
    for part in (check_agents, check_claude, check_skills, check_settings, check_surfaces, check_state):
        try:
            part(root, errors, notes)
        except Refuse as exc:
            errors.append(str(exc))
    for label, rows in (("error", errors), ("note", notes)):
        for row in rows:
            print(f"{label:<9}{row}")
    print(f"check: {count(len(errors), 'error')}, {count(len(notes), 'note')}")
    return 1 if errors else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(prog="mpa.py", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True, metavar="{init,update,check}")
    init = commands.add_parser("init", help="add the working agreement, skills, presets, and notes file;"
                                            " a second run adds what is missing")
    init.add_argument("project", metavar="PROJECT", help="project directory")
    init.add_argument("--runtime", default="claude,codex", metavar="LIST",
                      help="comma list of claude, codex, generic (default: claude,codex)")
    init.add_argument("--skills", default="core", metavar="SPEC",
                      help=f"all, none, or a comma list of skill names and groups: {', '.join(GROUPS)} (default: core)")
    init.add_argument("--preset", action="store_true", help="install the permission presets of the selected runtimes")
    init.add_argument("--state", default="local", choices=("local", "tracked", "none"),
                      help="TODO.md: local adds it to .gitignore, tracked leaves .gitignore alone, none creates no file")
    init.add_argument("--write", action="store_true", help="apply the plan; without it the plan is printed and nothing changes")
    update = commands.add_parser("update", help="replace the managed block, the installed mpa-* skills, and .codex/rules/mpa.rules")
    update.add_argument("project", metavar="PROJECT", help="project directory")
    update.add_argument("--add-skill", action="extend", nargs="+", default=[], metavar="NAME",
                        help="install more skills, by skill name")
    update.add_argument("--remove-skill", action="extend", nargs="+", default=[], metavar="NAME",
                        help="remove installed skills, by skill name")
    update.add_argument("--runtime", default="", metavar="LIST",
                        help="runtimes that receive --add-skill names (default: those that hold mpa-* skills);"
                             " generic also adds a missing ## Guides section")
    update.add_argument("--write", action="store_true", help="apply the plan; without it the plan is printed and nothing changes")
    update.add_argument("--force", action="store_true",
                        help="replace files that git cannot restore, and a block that holds other headings")
    check = commands.add_parser("check", help="report problems in an installed setup; changes nothing")
    check.add_argument("project", metavar="PROJECT", help="project directory")
    args = parser.parse_args(argv)
    try:
        root = Path(args.project).resolve()
        if not root.is_dir():
            raise Refuse(f"{args.project} is not a directory")
        return {"init": cmd_init, "update": cmd_update, "check": cmd_check}[args.command](root, args)
    except Refuse as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return exc.code
    except (OSError, ValueError, RecursionError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
