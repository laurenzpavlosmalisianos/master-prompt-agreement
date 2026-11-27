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
    "learn.chatgpt.com",
    "agents.md",
    "agentskills.io",
    "antigravity.google",
    "docs.github.com",
    "geminicli.com",
})
ALLOWED_LINKS = {
    "LICENSE": ("any", None),
    "docs/runtimes.md": ("hosts", DOCS_HOSTS),
}
# The release-notes addresses, without the https:// scheme, that the coverage line of each stack
# skill names in this order. A skill listed here needs that line, and it is the only line of the
# skill that may hold a link. A www. host is split so that this file holds no link.
SKILL_SOURCES = {
    "mpa-agent-inputs": ("modelcontextprotocol.io/specification/",),
    "mpa-apache-httpd": ("downloads.apache.org/httpd/CHANGES_2.4",
                         "httpd.apache.org/security/vulnerabilities_24.html"),
    "mpa-go": ("go.dev/doc/devel/release",),
    "mpa-hugo": ("gohugo.io/news/",),
    "mpa-infrastructure-as-code": ("developer.hashicorp.com/terraform/language/upgrade-guides",
                                   "opentofu.org/blog/"),
    "mpa-javascript-typescript": ("www" + ".typescriptlang.org/docs/", "nodejs.org/en/blog/release"),
    "mpa-kubernetes": ("kubernetes.io/releases/", "github.com/kubernetes-sigs/gateway-api/releases"),
    "mpa-nginx": ("nginx.org/en/CHANGES", "nginx.org/en/security_advisories.html"),
    "mpa-php": ("www" + ".php.net/ChangeLog-8.php", "laravel.com/docs/releases"),
    "mpa-python": ("docs.python.org/3/whatsnew/",),
    "mpa-rust": ("doc.rust-lang.org/stable/releases.html", "doc.rust-lang.org/cargo/CHANGELOG.html"),
    "mpa-swift": ("raw.githubusercontent.com/swiftlang/swift/main/CHANGELOG.md",),
    "mpa-wordpress": ("wordpress.org/news/category/releases/",),
}
COVERAGE = re.compile(r"Current to .+, checked \d{4}-\d{2}-\d{2}\. For a newer .+, read what changed after .+"
                      r" in the release notes \(([^()]+)\) before relying on this file;"
                      r" up to .+ no lookup is needed\.")
STATE_NAMES = ("TODO.md", "*.log", "CLAUDE.local.md", "AGENTS.override.md")
STATE_DIRS = (".claude", ".codex", ".agents", ".gemini", ".agent", "_agents", "_agent")
LOCAL_ADDRESSES = ("127.0.0.1", "0.0.0.0")
# The first three octets of the IPv4 ranges that RFC 5737 reserves for documentation.
DOCUMENTATION_NETWORKS = ((192, 0, 2), (198, 51, 100), (203, 0, 113))
# A link with a scheme, or a scheme-less www. link, which is checked as an http link.
LINK = re.compile(r"(?:https?|ftp)://\S+|(?<![\w.@/:-])www\.[\w-]+\.\S+", re.I)
EMBEDDED_LINK = re.compile(r"(?:https?|ftp)://", re.I)
BARE_SCHEME = "http" + "://"
SECURE_SCHEME = "https" + "://"
TRAILING_PROSE_CHARS = ".,;:!"
TRAILING_WRAPPER_CHARS = ">'\"`"
FORBIDDEN_URL_CHARS = frozenset("'\"`<>\\")
IPV4 = re.compile(r"(?<![\w.-])(?<!version )\d{1,3}(?:\.\d{1,3}){3}(?!\.?[\w-])", re.I)
# The scissors line that git commit --verbose writes, followed by git's explanation comment line,
# whose wording depends on the locale. git drops the block and everything below it only in verbose
# mode (-v or commit.verbose), or with --cleanup=scissors when the editor opens. In every other case,
# a message given with -m or -F, or written in the editor, keeps the text below the block. A
# commit-msg hook cannot tell how git was invoked, so the --commit-msg scan stops at the block in
# every case; --log scans the recorded message in full. This pattern and IDENTITY assume git's
# default comment character #. With core.commentChar set to another character, neither the
# scissors block nor the identity lines are recognized, so the scan covers them.
SCISSORS = re.compile(r"^# -{24} >8 -{24}\n# [^\r\n]*\r?$", re.M)
# The comment lines, in git's exact English template layout, that git writes into the commit
# message template about the commit identity.
IDENTITY = re.compile(r"# (?:Author: {4}|Committer: |Date: {6})(?=\S)")
RULES = (
    # A Windows profile path with single, escaped, or forward slashes.
    ("local", re.compile(r"/home/[\w.-]+|/Users/[\w.-]+|(?<![\w])[A-Z]:(?:\\+|/)Users(?:\\+|/)", re.I)),
    # An email address, except at example.com, example.net, example.org, and their subdomains, and
    # under the .test, .example, and .invalid top-level domains (RFC 2606).
    ("local", re.compile(r"(?<![\w.+\\-])[\w.+-]+@(?!(?:(?:[\w-]+\.)*example\.(?:com|net|org)"
                         r"|(?:[\w-]+\.)+(?:test|example|invalid))(?!\.?[\w-]))"
                         r"(?:localhost\b|(?:[\w-]+\.)+[a-z]{2,})", re.I)),
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("secret", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}|\bgithub_pat_\w{20,}|\bglpat-[\w-]{20,}")),
    ("secret", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}|\bxox[abprs]-[0-9A-Za-z-]{10,}|\bAIza[\w-]{35}")),
    ("secret", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}|\bnpm_[0-9A-Za-z]{36}\b|\bpypi-AgE[\w-]{50,}")),
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


def skill_of(rel):
    """Return the skill name of a skills/<name>/SKILL.md path, else None."""
    parts = rel.split("/")
    return parts[1] if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md" else None


def link_policy(rel, line):
    """Return the link policy for one line of a file, or None when the line may hold no link."""
    name = skill_of(rel)
    if name in SKILL_SOURCES:
        match = COVERAGE.fullmatch(line)
        expected = [SECURE_SCHEME + address for address in SKILL_SOURCES[name]]
        return ("exact", expected) if match and match[1].split(", ") == expected else None
    return ALLOWED_LINKS.get(rel)


def link_allowed(rel, url, line=""):
    """Report whether a stripped URL may appear in the line of the file."""
    policy = link_policy(rel, line)
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
    if kind == "exact":
        return url in allowed
    if kind == "hosts":
        return netloc in allowed
    return False


def line_hits(line, rel):
    """Yield (rule, matched text) for one line of a file, a file name, or a commit message."""
    if len(line) > MAX_LINE:
        yield "size", f"line longer than {MAX_LINE} characters"
        return
    for match in LINK.finditer(line):
        url = strip_url(match.group())
        bare = url[:4].lower() == "www."
        if not link_allowed(rel, BARE_SCHEME + url if bare else url, line):
            yield "link", url
    for match in IPV4.finditer(line):
        octets = [int(part) for part in match.group().split(".")]
        # Only the canonical decimal form is exempt: some parsers read an octet with a leading zero,
        # such as 051, as octal, which can place the address outside the documentation ranges.
        canonical = match.group() == ".".join(map(str, octets))
        if (max(octets) <= 255 and match.group() not in LOCAL_ADDRESSES
                and not (canonical and tuple(octets[:3]) in DOCUMENTATION_NETWORKS)):
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
        path = Path(root) / rel
        try:
            # git stores a symbolic link as the text of its target, so that text is what is scanned.
            data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
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
            found.append(("file", shown, 0, "unreadable, not UTF-8, or larger than 1 MiB"))
            continue
        for number, line in enumerate(lines, 1):
            found += [(rule, shown, number, text) for rule, text in line_hits(line, rel)]
        if skill_of(rel) in SKILL_SOURCES and not any(link_policy(rel, line) for line in lines):
            found.append(("coverage", shown, 0, "no coverage line that names the addresses in SKILL_SOURCES"))
    return found


def scan_message(text, label, editing=False):
    """Return findings for one commit message.

    editing is true for a message file that git has not cleaned up yet. Then the scan stops at
    git's verbose scissors block and skips git's commit identity comment lines, which git removes.
    A recorded commit message is scanned whole."""
    cut = SCISSORS.search(text) if editing else None
    lines = text[:cut.start() if cut else len(text)].split("\n")
    return [(rule, label, number, hit) for number, line in enumerate(lines, 1)
            if not (editing and IDENTITY.match(line)) for rule, hit in line_hits(line, MESSAGE)]


def repository_files(root, staged=False):
    """Return the staged files, or the tracked and unignored files present in the work tree;
    every file when git is unavailable."""
    if staged:
        listed = git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT")
    else:
        listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listed is None:
        if staged:
            raise OSError("git cannot list the staged files")
        names = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name != ".git"]
            links = [name for name in dirs if os.path.islink(os.path.join(folder, name))]
            for name in files + links:
                names.append(Path(os.path.relpath(os.path.join(folder, name), root)).as_posix())
    else:
        names = [name for name in listed.decode("utf-8", "surrogateescape").split("\0") if name]
    if staged:
        return sorted(set(names))
    return sorted({rel for rel in names if os.path.lexists(Path(root) / rel)
                   and ((Path(root) / rel).is_symlink() or not (Path(root) / rel).is_dir())})


def select(files, items, root):
    """Return the files that the PATH arguments name. Raise ValueError for a bad argument."""
    chosen = []
    for item in items:
        path = Path(item)
        # A symbolic link names itself, as git tracks it, and not its target.
        full = path.absolute().parent.resolve() / path.name if path.is_symlink() else path.resolve()
        rel = Path(os.path.relpath(full, root)).as_posix()
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
            text = Path(args.commit_msg).read_bytes().decode("utf-8", "replace")
            found = scan_message(text, MESSAGE, editing=True)
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
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"hygiene: {exc}", file=sys.stderr)
        return 2
    for rule, where, number, text in found:
        print(f"{rule} {where}:{number}: {text}")
    print(f"hygiene: {len(found)} finding{'' if len(found) == 1 else 's'}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
