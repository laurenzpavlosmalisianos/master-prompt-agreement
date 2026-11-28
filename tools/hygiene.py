#!/usr/bin/env python3
"""Check repository files and commit messages for local paths, addresses, and secrets."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESSAGE = "commit message"
LOCAL_ADDRESSES = ("127.0.0.1", "0.0.0.0")
# The first three octets of the IPv4 ranges that RFC 5737 reserves for documentation.
DOCUMENTATION_NETWORKS = ((192, 0, 2), (198, 51, 100), (203, 0, 113))
IPV4 = re.compile(r"(?<![\w.-])(?<!version )\d{1,3}(?:\.\d{1,3}){3}(?!\.?[\w-])", re.I)
# The scissors line that git commit --verbose writes above the diff. The scan of a message stops there.
SCISSORS = re.compile(r"^# -{24} >8 -{24}$", re.M)
# The comment lines about the commit identity that git writes into the message template. The scan skips them.
IDENTITY = re.compile(r"# (?:Author: {4}|Committer: |Date: {6})(?=\S)")
RULES = (
    # A home directory on Linux or macOS, or a Windows profile path with single, escaped, or forward slashes.
    ("local", re.compile(r"/home/[\w.-]+|/Users/[\w.-]+|(?<![\w])[A-Z]:(?:\\+|/)Users(?:\\+|/)", re.I)),
    # An email address, except at example.com, example.net, example.org, and their subdomains, and
    # under the .test, .example, and .invalid top-level domains (RFC 2606). The lookbehind excludes a backslash
    # so that an escape sequence before an at sign, as in a string that holds a newline and then an import
    # line, is not read as an address.
    ("local", re.compile(r"(?<![\w.+\\-])[\w.+-]+@(?!(?:(?:[\w-]+\.)*example\.(?:com|net|org)"
                         r"|(?:[\w-]+\.)+(?:test|example|invalid))(?!\.?[\w-]))"
                         r"(?:localhost\b|(?:[\w-]+\.)+[a-z]{2,})", re.I)),
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("secret", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}|\bgithub_pat_\w{20,}|\bglpat-[\w-]{20,}")),
    ("secret", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}|\bxox[abprs]-[0-9A-Za-z-]{10,}|\bAIza[\w-]{35}")),
    ("secret", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}|\bnpm_[0-9A-Za-z]{36}\b|\bpypi-AgE[\w-]{50,}")),
)


def line_hits(line):
    """Yield (rule, matched text) for one line of a file or of a commit message."""
    for match in IPV4.finditer(line):
        octets = tuple(int(part) for part in match.group().split("."))
        exempt = match.group() in LOCAL_ADDRESSES or octets[:3] in DOCUMENTATION_NETWORKS
        if max(octets) <= 255 and not exempt:
            yield "local", match.group()
    for rule, pattern in RULES:
        for match in pattern.finditer(line):
            yield rule, (match.group()[:8] + "..." if rule == "secret" else match.group())


def git(root, *args):
    """Return the output bytes of a git command, or None when it fails."""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def scan(root, staged=False):
    """Return (rule, path, line number, text) findings for the staged content of the staged files,
    or for the tracked and unignored files in the work tree."""
    if staged:
        listed = git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT")
    else:
        listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listed is None:
        raise OSError("git cannot list the files")
    found = []
    for rel in sorted({name for name in listed.decode("utf-8", "replace").split("\0") if name}):
        path = Path(root) / rel
        if staged:
            data = git(root, "show", ":" + rel)
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        if data is None:
            found.append(("file", rel, 0, "unreadable"))
            continue
        for number, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
            found += [(rule, rel, number, text) for rule, text in line_hits(line)]
    return found


def scan_message(text):
    """Return findings for a commit message file as git hands it to a commit-msg hook."""
    cut = SCISSORS.search(text)
    lines = text[:cut.start() if cut else len(text)].split("\n")
    return [(rule, MESSAGE, number, hit) for number, line in enumerate(lines, 1)
            if not IDENTITY.match(line) for rule, hit in line_hits(line)]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hygiene.py", description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="check the staged content of the staged files")
    mode.add_argument("--commit-msg", metavar="FILE", help="check one commit message file")
    args = parser.parse_args(argv)
    try:
        if args.commit_msg is not None:
            found = scan_message(Path(args.commit_msg).read_bytes().decode("utf-8", "replace"))
        else:
            found = scan(ROOT, args.staged)
    except OSError as exc:
        print(f"hygiene: {exc}", file=sys.stderr)
        return 2
    for rule, where, number, text in found:
        print(f"{rule} {where}:{number}: {text}")
    print(f"hygiene: {len(found)} finding{'' if len(found) == 1 else 's'}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
