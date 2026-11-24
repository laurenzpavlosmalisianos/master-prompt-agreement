#!/usr/bin/env python3
"""Check repository files and commit messages for secrets, local data, links, and working files."""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
MAX_READ = 1 << 20
MAX_LINE = 4000
MESSAGE = "commit message"
DOCS_HOSTS = frozenset({
    "code.claude.com",
    "platform.claude.com",
    "learn.chatgpt.com",
    "developers.openai.com",
    "agents.md",
    "agentskills.io",
    "antigravity.google",
})
EXACT_REPOS = frozenset({
    ("github.com", "/GoogleChrome/modern-web-guidance-src"),
    ("github.com", "/cloudflare/security-audit-skill"),
})
ALLOWED_LINKS = {
    "LICENSE": ("any", None),
    "docs/runtimes.md": ("hosts", DOCS_HOSTS),
    "docs/external-skills.md": ("repos", EXACT_REPOS),
}
STATE_NAMES = ("TODO.md", "*.log", "CLAUDE.local.md", "AGENTS.override.md")
STATE_DIRS = (".claude", ".codex", ".agents", ".gemini", ".agent")
LOCAL_ADDRESSES = ("127.0.0.1", "0.0.0.0")
LINK = re.compile(r"https?://\S+", re.I)
EMBEDDED_LINK = re.compile(r"https?://", re.I)
TRAILING_PROSE_CHARS = ".,;:!"
TRAILING_WRAPPER_CHARS = ">'\"`"
FORBIDDEN_URL_CHARS = frozenset("'\"`<>\\")
IPV4 = re.compile(r"(?<![\w.-])(?<!version )\d{1,3}(?:\.\d{1,3}){3}(?![\w.-])", re.I)
SCISSORS = re.compile(r"^# -+ >8 -+\r?$", re.M)
RULES = (
    ("local", re.compile(r"/home/[\w.-]+|/Users/[\w.-]+|C:\\Users\\", re.I)),
    ("local", re.compile(r"(?<![\w.+\\-])[\w.+-]+@(?!example\.)(?:localhost\b|(?:[\w-]+\.)+[a-z]{2,})", re.I)),
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("secret", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}|\bgithub_pat_\w{20,}|\bglpat-[\w-]{20,}")),
    ("secret", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}|\bxox[abprs]-[0-9A-Za-z-]{10,}|\bAIza[\w-]{35}")),
)


def strip_url(token):
    """Strip trailing outer punctuation and closing wrapper characters from a matched URL run."""
    unwrapped = False
    while token:
        last = token[-1]
        if last in TRAILING_WRAPPER_CHARS:
            token = token[:-1]
            unwrapped = True
        elif last == ")" and token.count(")") > token.count("("):
            token = token[:-1]
            unwrapped = True
        elif last == "]" and token.count("]") > token.count("["):
            token = token[:-1]
            unwrapped = True
        elif not unwrapped and last in TRAILING_PROSE_CHARS:
            if last == "." and len(token) >= 2 and token[-2] in ("/", "."):
                break
            token = token[:-1]
        else:
            break
    return token


def link_allowed(rel, url):
    """Report whether a stripped URL may appear in the file."""
    policy = ALLOWED_LINKS.get(rel)
    if policy is None:
        return False
    if any(ch in FORBIDDEN_URL_CHARS or ch.isspace() or not ch.isprintable() for ch in url):
        return False
    if EMBEDDED_LINK.search(url, 1):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    kind, allowed = policy
    if kind == "any":
        return scheme in {"http", "https"} and bool(netloc)
    if scheme != "https":
        return False
    if kind == "hosts":
        return netloc in allowed
    if kind == "repos":
        return ((netloc, parsed.path.rstrip("/")) in allowed
                and not parsed.query and not parsed.fragment
                and "?" not in url and "#" not in url)
    return False


def line_hits(line, rel):
    """Yield (rule, matched text) for one line of a file, a file name, or a commit message."""
    if len(line) > MAX_LINE:
        yield "size", f"line longer than {MAX_LINE} characters"
        return
    for match in LINK.finditer(line):
        url = strip_url(match.group())
        if not link_allowed(rel, url):
            yield "link", url
    for match in IPV4.finditer(line):
        octets = [int(part) for part in match.group().split(".")]
        if max(octets) <= 255 and match.group() not in LOCAL_ADDRESSES:
            yield "local", match.group()
    for rule, pattern in RULES:
        for match in pattern.finditer(line):
            yield rule, (match.group()[:8] + "..." if rule == "secret" else match.group())


def working_state(rel):
    """Report whether a path is one that holds notes, logs, or local agent state."""
    parts = Path(rel).parts
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
        names = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name != ".git"]
            for name in files:
                names.append(Path(os.path.relpath(os.path.join(folder, name), root)).as_posix())
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
        modes = sum(flag for flag in (args.commit_msg is not None, args.log is not None, args.staged))
        if modes > 1 or ((args.commit_msg is not None or args.log is not None) and args.paths):
            raise ValueError("--commit-msg and --log cannot be combined with each other, --staged, or PATH")
        if args.commit_msg is not None:
            if not args.commit_msg:
                raise ValueError("--commit-msg requires a file path")
            found = scan_message(Path(args.commit_msg).read_text(encoding="utf-8", errors="replace"), MESSAGE)
        elif args.log is not None:
            if not args.log:
                raise ValueError("--log requires a revision range")
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
