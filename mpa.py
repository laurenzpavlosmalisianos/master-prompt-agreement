#!/usr/bin/env python3
"""Set up, update, and check Master Prompt Agreement files in a project."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import NamedTuple

__version__ = "8.0.0"
# The version of templates/block.md. It changes only when the block text changes.
BLOCK_VERSION = "8.0.0"

FRAMEWORK_DIR = Path(__file__).resolve().parent
TEMPLATES = FRAMEWORK_DIR / "templates"
SKILLS = FRAMEWORK_DIR / "skills"
VERSION = tuple(int(part) for part in BLOCK_VERSION.split("."))
MAX_READ = 1 << 20
NOTE_SIZE, MAX_SIZE = 16 << 10, 32 << 10
RULE_SIZE = 24000
SKILL_BUDGET = 8000
MAX_WALK = 2000
SKILL_DIRS = {
    "agents": ".agents/skills",
    "codex": ".agents/skills",
    "antigravity": ".agents/skills",
    "generic": ".agents/skills",
    "claude": ".claude/skills",
}
IMPORTS = (("CLAUDE.md", "@AGENTS.md"), (".claude/CLAUDE.md", "@../AGENTS.md"))
CATALOG = {
    "core": ("mpa-review", "mpa-external-contribution", "mpa-incident", "mpa-dependency-change",
             "mpa-root-cause", "mpa-migration", "mpa-release", "mpa-research"),
    "security": ("mpa-secure-coding", "mpa-security-audit"),
    "agents": ("mpa-agent-inputs", "mpa-agent-instructions"),
    "data": ("mpa-database", "mpa-data-privacy"),
    "infra": ("mpa-ci-pipeline", "mpa-containers", "mpa-kubernetes", "mpa-infrastructure-as-code"),
    "web": ("mpa-web-frontend", "mpa-seo"),
    "languages": ("mpa-python", "mpa-javascript-typescript", "mpa-go", "mpa-rust", "mpa-swift",
                  "mpa-php", "mpa-shell"),
    "platforms": ("mpa-hugo", "mpa-wordpress"),
}
INDIVIDUAL_ONLY = ("languages", "platforms")
BUNDLES = {name: items for name, items in CATALOG.items() if name not in INDIVIDUAL_ONLY}
# Skill names that update removes from a project without --remove-skill.
RETIRED = ()
ADOPTED = ("Approvals", "Commands", "Constraints")
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


def regular_size(path):
    """Return the byte size of path when it is a regular file (not a symbolic link), else None."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info.st_size if stat.S_ISREG(info.st_mode) else None


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
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              check=False, stdin=subprocess.DEVNULL, env={**env, **GIT_ENV})
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
    skip = 1 if text.startswith("\ufeff") else 0
    rows, fence, comment, offset = [], "", False, skip
    for row in text[skip:].splitlines(keepends=True):
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
    bom = "\ufeff" if text.startswith("\ufeff") else ""
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
    skip = len("\ufeff") if text.startswith("\ufeff") else 0
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
        raise Usage(f"unknown skill or bundle: {name}; skills/README.md lists the skill names")
    return lf(path.read_bytes())


def shipped_names():
    return sorted(p.name for p in SKILLS.glob("mpa-*") if (p / "SKILL.md").is_file())


def skill_name(item):
    return item if item.startswith("mpa-") else "mpa-" + item


def skill_listing_size(name):
    """Return the startup listing character count (name + description) of a shipped skill."""
    text = shipped(name).decode("utf-8")
    if not text.startswith("---\n"):
        return len(name)
    head, sep, _ = text[4:].partition("\n---\n")
    if not sep:
        return len(name)
    for line in head.splitlines():
        if line.startswith("description:"):
            raw = line[len("description:"):].strip()
            if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
                try:
                    desc = json.loads(raw)
                except ValueError:
                    desc = raw[1:-1]
            elif len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
                desc = raw[1:-1].replace("''", "'")
            else:
                desc = raw
            return len(name) + len(desc)
    return len(name)


def select_skills(raw, *, allow_all_none=True, require_shipped=True):
    """Expand a comma-separated string or list of tokens into skill names."""
    items = [raw] if isinstance(raw, str) else list(raw)
    names = []
    for item in (part.strip() for chunk in items for part in chunk.split(",") if part.strip()):
        if item in ("all", "none"):
            if not allow_all_none:
                raise Usage(f"{item} is only valid with init --skills; pass bundle or skill names instead")
            found = shipped_names() if item == "all" else []
        elif item in INDIVIDUAL_ONLY:
            raise Usage(f"{item} is not an install bundle; pick individual skills: {', '.join(CATALOG[item])}")
        elif item in BUNDLES:
            found = BUNDLES[item]
        else:
            found = [skill_name(item)]
        for name in found:
            if require_shipped:
                shipped(name)
            elif not NAME_RE.fullmatch(name):
                raise Usage(f"invalid skill name: {name}")
            if name not in names:
                names.append(name)
    return names


def select_runtimes(spec, required):
    names = [part.strip() for part in spec.split(",") if part.strip()]
    if [name for name in names if name not in SKILL_DIRS] or (required and not names):
        raise Usage(f"--runtime takes a comma list of {', '.join(SKILL_DIRS)}")
    return names


def default_runtimes(root):
    """Resolve omitted init --runtime from existing mpa-* skills, Claude Code files, or agents."""
    found = []
    for runtime, folder in (("claude", ".claude/skills"), ("agents", ".agents/skills")):
        if any((root / folder / name).is_dir() and not (root / folder / name).is_symlink()
               for name in installed(root, folder)):
            found.append(runtime)
    if found:
        return found
    if any(os.path.lexists(root / name) for name in ("CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json")):
        return ["claude"]
    return ["agents"]


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
            reason = (exc.strerror or str(exc)) if isinstance(exc, OSError) else str(exc)
            raise Refuse(f"{item.rel}: {reason}; completed: {', '.join(done) or 'nothing'}") from None
        done.append(item.rel)
    return len(done)


def plan_agents(root, runtimes, skills):
    """Return the plan steps for AGENTS.md and the bytes the file will hold."""
    current = read(root, "AGENTS.md")
    skeleton = template("AGENTS.template.md")
    guides = GUIDES if "generic" in runtimes and (skills or installed(root, SKILL_DIRS["generic"])) else ""
    if current is None:
        clean = root.name.strip()
        name = clean if clean and TITLE_RE.fullmatch(root.name) else "Project"
        text = skeleton.replace("{name}", name).replace("{block}", block_text())
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
    heads, _ = outline(text)
    present = {title for _, title in heads}
    missing = [title for title in ADOPTED if title not in present]
    parts = [section(skeleton, title) for title in missing]
    if guides and "Guides" not in present:
        missing.append("Guides")
        parts.append(guides)
    tail = "\n\n".join(parts)
    new, where = insert_top(text, block_text() + ("\n\n" + tail if tail else ""))
    detail = f"managed block {BLOCK_VERSION} {where}"
    if tail:
        detail += f"; {', '.join(missing)} {'section' if len(missing) == 1 else 'sections'} after the block"
    steps = [Step("insert", "AGENTS.md", detail, new.encode())]
    if "Approvals" in present:
        steps.append(Step("note", "AGENTS.md keeps its existing ## Approvals section. Review it."))
    if "Constraints" in present:
        steps.append(Step("note", "AGENTS.md keeps its existing ## Constraints section; add a scope rule if desired."))
    return steps, new.encode()


def claude_files(root, errors=None):
    """Return existing (path, import line, bytes or None, linked) entries among IMPORTS.

    linked is true when the path is a symbolic link to AGENTS.md. When errors is a list,
    per-file refusals are appended to it instead of stopping inspection of the other path.
    """
    found = []
    for rel, line in IMPORTS:
        try:
            parent = Path(rel).parent
            if parent != Path("."):
                target(root, parent.as_posix(), is_dir=True)
            path = root / rel
            if path.is_symlink() and path.resolve() == root / "AGENTS.md":
                found.append((rel, line, None, True))
                continue
            data = read(root, rel)
            if data is not None:
                found.append((rel, line, data, False))
        except Refuse as exc:
            if errors is None:
                raise
            errors.append(str(exc))
    return found


def plan_claude(root):
    entries = claude_files(root)
    if not entries:
        rel, line = IMPORTS[0]
        return Step("create", rel, "", (line + "\n").encode())
    decoded = []
    for rel, line, data, linked in entries:
        if linked:
            return Step("keep", rel, "symbolic link to AGENTS.md")
        text = decode(data, rel)
        if has_import(text, line):
            return Step("keep", rel, "import present")
        decoded.append((rel, line, text))
    rel, line, text = decoded[0]
    text, where = insert_top(text, line)
    return Step("insert", rel, f"import line {where}", text.encode())


def load_settings(data):
    """Return the settings object, or None when data is not a JSON object."""
    try:
        doc = json.loads(data)
    except (ValueError, RecursionError):
        return None
    return doc if isinstance(doc, dict) else None


def plan_init(root, runtimes, skills):
    claude = "claude" in runtimes
    claude_existing = claude_files(root) if claude else []
    held = {"AGENTS.md": read(root, "AGENTS.md"), **{rel: data for rel, _, data, _ in claude_existing}}
    steps, agents = plan_agents(root, runtimes, skills)
    adopted = steps[0].verb in ("create", "insert")
    if claude:
        steps.insert(1, plan_claude(root))
    skill_dirs = sorted({SKILL_DIRS[name] for name in runtimes})
    conflicts = []
    for folder in skill_dirs:
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
    if len(agents) > MAX_SIZE:
        raise Refuse("AGENTS.md would exceed 32 KiB, the default size at which Codex stops reading instruction files")
    existing = [name for name, content in held.items() if content is not None]
    if existing and adopted:
        verb = "keeps its" if len(existing) == 1 else "keep their"
        listed = existing[0] if len(existing) == 1 else (
            " and ".join(existing) if len(existing) == 2 else ", ".join(existing[:-1]) + ", and " + existing[-1]
        )
        steps.append(Step("note", f"{listed} {verb} existing text. This script does not review it."))
    if len(skill_dirs) > 1:
        steps.append(Step("note", "holding skills in both .claude/skills and .agents/skills doubles startup"
                                  " skill listings in tools that scan both."))
    if len(agents) > NOTE_SIZE:
        steps.append(Step("note", "AGENTS.md exceeds 16 KiB. Antigravity truncates a rule file at 24,000 bytes,"
                                  " and Codex stops reading instruction files at 32 KiB by default."))
    if (root / "AGENTS.override.md").exists():
        steps.append(Step("note", "AGENTS.override.md exists. Codex reads it in place of AGENTS.md in this directory."))
    if claude and (root / "CLAUDE.local.md").exists():
        steps.append(Step("note", "CLAUDE.local.md exists. Claude Code loads it together with CLAUDE.md."))
    if not claude:
        found_claude = claude_files(root, [])
        imported = False
        for rel, line, data, linked in found_claude:
            if linked:
                imported = True
                break
            try:
                if data is not None and has_import(decode(data, rel), line):
                    imported = True
                    break
            except Refuse:
                pass
        if found_claude and not imported:
            names = " and ".join(rel for rel, _, _, _ in found_claude)
            verb = "exists" if len(found_claude) == 1 else "exist"
            steps.append(Step("note", f"{names} {verb} without an AGENTS.md import and claude is not selected;"
                                      " Claude Code does not read AGENTS.md unless it imports it."))
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
    raw = read(root, "AGENTS.md")
    if raw is None:
        raise Refuse("AGENTS.md is missing; run init")
    text = decode(raw, "AGENTS.md")
    first, steps, guided = plan_block(text, force), [], False
    add = select_skills(add, allow_all_none=False, require_shipped=True)
    remove = set(select_skills(remove, allow_all_none=False, require_shipped=False))
    both = sorted(set(add) & remove)
    if both:
        raise Usage(f"cannot pass the same skill to --add-skill and --remove-skill: {', '.join(both)}")
    folders = sorted(set(SKILL_DIRS.values()))
    held = {folder: installed(root, folder) for folder in folders}
    active = [f for f in folders if any((root / f / n).is_dir() and not (root / f / n).is_symlink() for n in held[f])]
    receiving = sorted({SKILL_DIRS[name] for name in runtimes}) or active
    if add and not receiving:
        raise Refuse("no installed skill shows which runtimes the project uses; pass --runtime with --add-skill")
    available = set(shipped_names())
    for name in sorted(remove - {name for names in held.values() for name in names}):
        steps.append(Step("note", f"{name} is not installed."))
    for folder in folders:
        wanted = {*held[folder], *(add if folder in receiving else ())}
        for name in sorted(wanted):
            rel = f"{folder}/{name}/"
            entry = root / folder / name
            if name in held[folder] and (entry.is_symlink() or not entry.is_dir()):
                if name in remove or (name in add and folder in receiving):
                    target(root, rel, is_dir=True)
                steps.append(Step("note", f"{folder}/{name} is not a skill directory and is kept; check reports it as an error."))
                continue
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
    current = text if first is None else first.data.decode()
    if "generic" in runtimes and guided and "Guides" not in titles(current):
        new, where = add_guides(current)
        if first is None:
            first = Step("append", "AGENTS.md", f"Guides section {where}", new.encode())
        else:
            first = first._replace(detail=f"{first.detail}; Guides section {where}", data=new.encode())
    if first is not None:
        if len(first.data) > MAX_SIZE:
            raise Refuse("AGENTS.md would exceed 32 KiB, the default size at which Codex stops reading instruction files")
        if len(first.data) > NOTE_SIZE:
            steps.append(Step("note", "AGENTS.md exceeds 16 KiB. Antigravity truncates a rule file at 24,000 bytes,"
                                      " and Codex stops reading instruction files at 32 KiB by default."))
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
    before = [row for row in text[:start].lstrip("\ufeff").splitlines() if row.strip()]
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


def glob_match(path, pattern):
    """Report whether a slash-separated path matches pattern (* stays inside a segment; ** crosses /)."""
    seen, todo, n, m = set(), [(0, 0)], len(path), len(pattern)
    while todo:
        i, j = todo.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == n and j == m:
            return True
        if pattern[j:j + 3] == "**/" and (j == 0 or pattern[j - 1] == "/"):
            if (i == 0 and j + 3 < m) or (i > 0 and path[i - 1] == "/"):
                todo.append((i, j + 3))
            if i < n:
                todo.append((i + 1, j))
        elif pattern[j:j + 2] == "**":
            todo.append((i, j + 2))
            if i < n:
                todo.append((i + 1, j))
        elif j < m and pattern[j] == "*":
            todo.append((i, j + 1))
            if i < n and path[i] != "/":
                todo.append((i + 1, j))
        elif j < m and pattern[j] == "?":
            if i < n and path[i] != "/":
                todo.append((i + 1, j + 1))
        elif i < n and j < m and path[i] == pattern[j]:
            todo.append((i + 1, j + 1))
    return False


def check_claude(root, errors, notes):
    file_errors = []
    entries = claude_files(root, file_errors)
    errors.extend(file_errors)
    if not entries and not file_errors:
        tail = "; init --runtime claude adds the import"
        try:
            has_claude_skills = bool(installed(root, SKILL_DIRS["claude"]))
        except Refuse:
            has_claude_skills = False
        if (root / "CLAUDE.local.md").exists():
            notes.append("CLAUDE.local.md exists and no CLAUDE.md imports AGENTS.md;"
                         " Claude Code then does not read AGENTS.md" + tail)
        elif has_claude_skills or (root / ".claude/settings.json").exists():
            notes.append("no CLAUDE.md imports AGENTS.md; Claude Code before 2.1.277, or with a CLAUDE.md"
                         " in a directory above, does not read AGENTS.md" + tail)
        return
    if len(entries) > 1:
        notes.append("both CLAUDE.md and .claude/CLAUDE.md exist; keep one file to avoid ambiguity")
    imported = False
    missing = []
    for rel, line, data, linked in entries:
        if linked:
            imported = True
            continue
        try:
            text = decode(data, rel)
        except Refuse as exc:
            errors.append(str(exc))
            continue
        if has_import(text, line):
            imported = True
        else:
            missing.append((rel, line))
    if not imported and missing:
        for rel, line in missing:
            errors.append(f"{rel}: no line that is exactly {line} outside code fences and HTML comments")


def check_skills(root, errors, notes):
    known = set(shipped_names())
    by_folder = {}
    for folder in sorted(set(SKILL_DIRS.values())):
        try:
            names = installed(root, folder)
        except Refuse as exc:
            errors.append(str(exc))
            continue
        by_folder[folder] = set()
        for name in names:
            rel = f"{folder}/{name}/"
            try:
                target(root, rel, is_dir=True)
                if name not in known:
                    errors.append(f"{rel} is not a shipped skill; rename it without the mpa- prefix or remove it")
                    continue
                by_folder[folder].add(name)
                extra = other_files(root, rel)
                if extra:
                    errors.append(f"{rel} holds files other than SKILL.md: {', '.join(extra)}")
                current = read(root, rel + "SKILL.md")
                if current is None:
                    errors.append(f"{rel}SKILL.md is missing; run update")
                elif lf(current) != shipped(name):
                    errors.append(f"{rel}SKILL.md differs from the shipped text; run update")
            except Refuse as exc:
                errors.append(str(exc))
        chars = sum(skill_listing_size(name) for name in by_folder[folder])
        if chars > SKILL_BUDGET:
            notes.append(f"{folder}: mpa-* startup skill listings total {chars:,} characters, exceeding {SKILL_BUDGET:,}")
        path = root / folder
        if path.is_dir():
            non_mpa = 0
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if entry.name.startswith(".") or NAME_RE.fullmatch(entry.name):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=True):
                                non_mpa += 1
                        except OSError:
                            pass
            except OSError:
                pass
            if non_mpa:
                word = "directory" if non_mpa == 1 else "directories"
                verb = "shares" if non_mpa == 1 else "share"
                notes.append(f"{folder}: {non_mpa} non-mpa skill {word} also {verb} the startup budget")
    sets = [names for names in by_folder.values() if names]
    if len(sets) == 2:
        notes.append("both .claude/skills and .agents/skills hold mpa-* skills;"
                     " tools that scan both list each installed skill twice at startup")
        if sets[0] != sets[1]:
            notes.append(".claude/skills and .agents/skills hold different mpa-* skill sets")


def check_settings(root, errors, notes):
    ignored = []
    watched = ["AGENTS.md", *(rel for rel, _, _, _ in claude_files(root, ignored))]
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        try:
            data = read(root, rel)
        except Refuse as exc:
            errors.append(str(exc))
            continue
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
                   if glob_match(name, pattern) or glob_match((root / name).as_posix(), pattern)]
            if hit:
                errors.append(f"{rel}: claudeMdExcludes entry {pattern} covers {', '.join(hit)}")


def nested_files(root):
    """Return nested instruction files by kind, outside hidden and node_modules directories,
    and whether the breadth-first scan stopped at the directory limit."""
    agents, claude, gemini = [], [], []
    queue, seen = deque([root]), 0
    while queue:
        folder = queue.popleft()
        seen += 1
        if seen > MAX_WALK:
            return agents, claude, gemini, True
        try:
            with os.scandir(folder) as entries:
                items = sorted(entries, key=lambda entry: entry.name)
        except OSError:
            continue
        dirs = []
        for entry in items:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not entry.name.startswith(".") and entry.name != "node_modules":
                        dirs.append(Path(entry.path))
                elif folder != root and entry.is_file(follow_symlinks=False):
                    rel = Path(entry.path).relative_to(root).as_posix()
                    if entry.name in ("AGENTS.md", "AGENTS.override.md"):
                        agents.append(rel)
                    elif entry.name == "CLAUDE.md":
                        claude.append(rel)
                    elif entry.name == "GEMINI.md":
                        gemini.append(rel)
            except OSError:
                continue
        queue.extend(dirs)
    return agents, claude, gemini, False


def preview(items):
    more = f" and {len(items) - 5} more" if len(items) > 5 else ""
    return f"{', '.join(items[:5])}{more}"


def check_surfaces(root, errors, notes):
    if (root / "AGENTS.override.md").exists():
        errors.append("AGENTS.override.md exists; Codex reads it in place of AGENTS.md in this directory")
    if (root / "CLAUDE.local.md").exists():
        notes.append("CLAUDE.local.md exists; Claude Code loads it together with CLAUDE.md")
    if (root / ".claude/rules").exists():
        notes.append(".claude/rules exists; Claude Code loads the rule files in it")
    if (root / "GEMINI.md").exists():
        notes.append("GEMINI.md exists; Antigravity loads it alongside AGENTS.md")
    if (root / ".agents/rules").exists():
        notes.append(".agents/rules exists; Antigravity loads the rule files in it")
    if (root / ".codex/config.toml").exists():
        notes.append(".codex/config.toml exists; Codex applies it in a trusted project")
    agents, claude, gemini, stopped = nested_files(root)
    if agents:
        notes.append("Codex reads an AGENTS.md in a subdirectory, and Claude Code reads it only through a CLAUDE.md"
                     f" beside it: {preview(agents)}")
        by_dir = {}
        root_override = regular_size(root / "AGENTS.override.md")
        root_agents = regular_size(root / "AGENTS.md")
        if root_override is not None:
            by_dir[()] = ("AGENTS.override.md", root_override)
        elif root_agents is not None:
            by_dir[()] = ("AGENTS.md", root_agents)
        for rel in agents:
            size = regular_size(root / rel)
            if size is None:
                continue
            parts = Path(rel).parent.parts
            if parts not in by_dir or Path(rel).name == "AGENTS.override.md":
                by_dir[parts] = (rel, size)
        best_total, best_chain = 0, []
        for leaf in sorted(key for key in by_dir if key):
            chain = [by_dir[leaf[:i]] for i in range(len(leaf) + 1) if leaf[:i] in by_dir]
            total = sum(size for _, size in chain)
            if total > best_total:
                best_total, best_chain = total, [rel for rel, _ in chain]
        if best_total > MAX_SIZE:
            notes.append(f"combined instruction files along {' -> '.join(best_chain)} total {best_total:,} bytes,"
                         " exceeding 32 KiB; Codex stops reading instruction files at that size by default")
        elif best_total > NOTE_SIZE and (root_agents or 0) <= NOTE_SIZE:
            notes.append(f"combined instruction files along {' -> '.join(best_chain)} total {best_total:,} bytes,"
                         " exceeding 16 KiB; Codex stops reading instruction files at 32 KiB by default")
    if claude:
        notes.append(f"CLAUDE.md files in subdirectories load in Claude Code only: {preview(claude)}")
    if gemini:
        notes.append(f"GEMINI.md files in subdirectories load in Antigravity alongside AGENTS.md: {preview(gemini)}")
    for rel in ("GEMINI.md", *(r for r in agents if Path(r).name == "AGENTS.md"), *gemini):
        size = regular_size(root / rel)
        if size is not None and size > RULE_SIZE:
            notes.append(f"{rel} is {size:,} bytes; Antigravity truncates a rule file at 24,000 bytes")
    if stopped:
        notes.append(f"the scan for instruction files in subdirectories stopped after {MAX_WALK} directories")


# --- commands ----------------------------------------------------------------

def cmd_init(root, args):
    runtimes = default_runtimes(root) if args.runtime is None else select_runtimes(args.runtime, required=True)
    steps = plan_init(root, runtimes, select_skills(args.skills))
    if (args.runtime is None and runtimes == ["agents"]
            and any(item.verb in ("create", "insert") and item.rel == "AGENTS.md" for item in steps)):
        steps.append(Step("note", "using --runtime agents (.agents/skills/); pass --runtime claude for Claude Code,"
                                  " or --runtime claude,agents for both."))
    preflight(root, steps)
    for item in [item for item in steps if item.verb in ("insert", "append")]:
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
    for part in (check_agents, check_claude, check_skills, check_settings, check_surfaces):
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
    init = commands.add_parser("init", help="add the working agreement and skills;"
                                            " a second run adds what is missing")
    init.add_argument("project", metavar="PROJECT", help="project directory")
    init.add_argument("--runtime", default=None, metavar="LIST",
                      help="comma list of agents, codex, antigravity, generic, claude"
                           " (default: existing mpa-* skills, claude if CLAUDE.md/.claude exists, else agents)")
    init.add_argument("--skills", default="core", metavar="SPEC",
                      help=f"all, none, or a comma list of skill names and bundles: {', '.join(BUNDLES)} (default: core)")
    init.add_argument("--write", action="store_true", help="apply the plan; without it the plan is printed and nothing changes")
    update = commands.add_parser("update", help="replace the managed block and the installed mpa-* skills")
    update.add_argument("project", metavar="PROJECT", help="project directory")
    update.add_argument("--add-skill", action="extend", nargs="+", default=[], metavar="NAME",
                        help="install more skills, by skill or bundle name (space- or comma-separated)")
    update.add_argument("--remove-skill", action="extend", nargs="+", default=[], metavar="NAME",
                        help="remove installed skills, by skill or bundle name (space- or comma-separated)")
    update.add_argument("--runtime", default="", metavar="LIST",
                        help="runtimes that receive --add-skill names (default: those that hold mpa-* skills);"
                             " generic also adds a missing ## Guides section")
    update.add_argument("--write", action="store_true", help="apply the plan; without it the plan is printed and nothing changes")
    update.add_argument("--force", action="store_true",
                        help="replace files that git cannot restore, or a block with other headings")
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
