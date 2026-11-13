#!/usr/bin/env python3
"""Check repository files and commit messages for secrets, local data, links, and working files."""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_READ = 1 << 20
MAX_LINE = 4000
MESSAGE = "commit message"
HOSTS = {"code.claude.com", "platform.claude.com", "learn.chatgpt.com", "developers.openai.com",
         "agents.md", "agentskills.io"}
STATE_NAMES = ("TODO.md", "*.log", "CLAUDE.local.md", "AGENTS.override.md")
STATE_DIRS = (".claude", ".codex", ".agents")
LOCAL_ADDRESSES = ("127.0.0.1", "0.0.0.0")
LINK = re.compile(r"http(s?)://([^/\s\"'`<>)\]]*)", re.I)
IPV4 = re.compile(r"(?<![\w.=-])(?<!version )\d{1,3}(?:\.\d{1,3}){3}(?![\w.-])", re.I)
ENTRY = re.compile(r"^\s*(?:[-*+]|\d+\.)\s|\d{4}-\d{2}-\d{2}")
SCISSORS = re.compile(r"^# -+ >8 -+$", re.M)
RULES = (
    ("local", re.compile(r"/home/[\w.-]+|/Users/[\w.-]+|C:\\Users\\", re.I)),
    ("local", re.compile(r"(?<![\w.+\\-])[\w.+-]+@(?!example\.)(?:localhost\b|(?:[\w-]+\.)+[a-z]{2,})", re.I)),
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("secret", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}|\bgithub_pat_\w{20,}|\bglpat-[\w-]{20,}")),
    ("secret", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}|\bxox[abprs]-[0-9A-Za-z-]{10,}|\bAIza[\w-]{35}")),
)


def link_allowed(rel, secure, host):
    """Report whether a link to host may appear in the file."""
    if rel == "LICENSE":
        return True
    return rel == "docs/runtimes.md" and bool(secure) and host.lower() in HOSTS


def line_hits(line, rel):
    """Yield (rule, matched text) for one line of a file, a file name, or a commit message."""
    if len(line) > MAX_LINE:
        yield "size", f"line longer than {MAX_LINE} characters"
        return
    for match in LINK.finditer(line):
        if not link_allowed(rel, match.group(1), match.group(2)):
            yield "link", match.group()
    for match in IPV4.finditer(line):
        octets = [int(part) for part in match.group().split(".")]
        if max(octets) <= 255 and match.group() not in LOCAL_ADDRESSES:
            yield "local", match.group()
    for rule, pattern in RULES:
        match = pattern.search(line)
        if match:
            yield rule, (match.group()[:12] + "..." if rule == "secret" else match.group())


def working_state(rel):
    """Report whether a path is one that holds notes, logs, or local agent state."""
    parts = Path(rel).parts
    if parts[0] == "templates":
        return False
    return (any(fnmatch.fnmatchcase(parts[-1], name) for name in STATE_NAMES)
            or any(part in STATE_DIRS for part in parts[:-1]))


def git(root, *args):
    """Return the output bytes of a git command, or None when it fails."""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def content(root, rel, staged):
    """Return the bytes of a work tree file or of its staged version, or None when unreadable."""
    if staged:
        data = git(root, "show", ":" + rel)
    else:
        try:
            data = (Path(root) / rel).read_bytes()
        except OSError:
            return None
    return None if data is None or len(data) > MAX_READ else data


def scan(paths, root, staged=False):
    """Return (rule, path, line number, text) findings for paths relative to root.

    Line number 0 is the file name or the file as a whole.
    """
    found = []
    for rel in sorted(paths):
        shown = rel.encode("utf-8", "backslashreplace").decode()
        if shown != rel:
            found.append(("file", shown, 0, "name is not UTF-8"))
        if working_state(rel):
            found.append(("state", shown, 0, "working-state path"))
        found += [(rule, shown, 0, text) for rule, text in line_hits(shown, rel)]
        data = content(root, rel, staged)
        try:
            lines = data.decode("utf-8").split("\n")
        except (AttributeError, ValueError):
            found.append(("file", shown, 0, "unreadable, a dangling link, not UTF-8, or larger than 1 MiB"))
            continue
        for number, line in enumerate(lines, 1):
            found += [(rule, shown, number, text) for rule, text in line_hits(line, rel)]
            if rel == "templates/TODO.md" and ENTRY.search(line):
                found.append(("state", shown, number, "entry in a template"))
    return found


def scan_message(text, label):
    """Return findings for one commit message, up to a scissors line."""
    cut = SCISSORS.search(text)
    lines = text[:cut.start() if cut else len(text)].split("\n")
    return [(rule, label, number, hit) for number, line in enumerate(lines, 1) for rule, hit in line_hits(line, MESSAGE)]


def repository_files(root, staged=False):
    """Return the staged files, or the tracked and unignored files present in the work tree;
    every file when git is unavailable."""
    if staged:
        listed = git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    else:
        listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listed is None:
        if staged:
            raise OSError("git cannot list the staged files")
        names = [os.path.relpath(os.path.join(folder, name), root)
                 for folder, _, names in os.walk(root) if ".git" not in Path(folder).parts for name in names]
    else:
        names = [name for name in listed.decode("utf-8", "surrogateescape").split("\0") if name]
    if staged:
        return sorted(set(names))
    return sorted({rel for rel in names if os.path.lexists(Path(root) / rel) and not (Path(root) / rel).is_dir()})


def select(files, items, root):
    """Return the files that the PATH arguments name. Raise ValueError for a bad argument."""
    chosen = []
    for item in items:
        rel = Path(os.path.relpath(Path(item).resolve(), root)).as_posix()
        if rel == ".." or rel.startswith("../"):
            raise ValueError(f"{item} is outside the repository")
        picked = files if rel == "." else [name for name in files if name == rel or name.startswith(rel + "/")]
        if not picked:
            raise ValueError(f"{item} selects no file")
        chosen += picked
    return sorted(set(chosen)) if items else files


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hygiene.py", description=__doc__)
    parser.add_argument("paths", nargs="*", metavar="PATH", help="limit the scan to these files and directories")
    parser.add_argument("--staged", action="store_true", help="check the staged content of the staged files")
    parser.add_argument("--commit-msg", metavar="FILE", help="check one commit message file")
    parser.add_argument("--log", metavar="RANGE", help="check the commit messages in a git revision range")
    args = parser.parse_args(argv)
    try:
        if args.commit_msg:
            found = scan_message(Path(args.commit_msg).read_text(encoding="utf-8", errors="replace"), MESSAGE)
        elif args.log:
            log = git(ROOT, "log", "--format=%h%n%B%x00", "--end-of-options", args.log)
            if log is None:
                raise OSError(f"git log failed for {args.log}")
            found = []
            for entry in filter(None, (part.strip() for part in log.decode("utf-8", "replace").split("\0"))):
                commit, _, text = entry.partition("\n")
                found += scan_message(text, commit)
        else:
            files = select(repository_files(ROOT, args.staged), args.paths, ROOT)
            found = scan(files, ROOT, args.staged)
    except (OSError, ValueError) as exc:
        print(f"hygiene: {exc}", file=sys.stderr)
        return 2
    for rule, where, number, text in found:
        print(f"{rule} {where}:{number}: {text}")
    print(f"hygiene: {len(found)} finding{'' if len(found) == 1 else 's'}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
