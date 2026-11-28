"""Tests for tools/hygiene.py."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import hygiene

# Samples hold placeholder names and values that belong to nobody, and each sample that the scanner
# reports is assembled from parts, so that this file passes the scan.
HOME_PATH = "/ho" + "me/name/project"
# An address under .alt, which RFC 9476 keeps out of the DNS.
MAIL = "name@" + "host.alt"
SCISSORS = "# " + "-" * 24 + " >8 " + "-" * 24 + "\n"
# One row per pattern: (rule, a line that is reported, a line that passes).
CASES = (
    ("local", "host 10.1." + "2.3", "host 192.0." + "2.1 and 127.0.0.1, version 1.2." + "3.4"),
    ("local", HOME_PATH, "the C:" + "\\UsersGuide file"),
    ("local", MAIL, "name@" + "example.com and name@" + "host.test"),
    ("secret", "-----BEGIN RSA PRIVATE" + " KEY-----", "-----BEGIN PGP PUBLIC KEY BLOCK-----"),
    ("secret", "github" + "_pat_" + "a" * 30, "github" + "_pat_" + "a" * 5),
    ("secret", "xox" + "b-123456789012", "xox" + "b-123"),
    ("secret", "sk_" + "live_" + "a1" * 12, "sk_" + "test_" + "a1" * 12),
)


def main(*argv):
    """Return (exit code, printed text) of hygiene.main."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        return hygiene.main([str(item) for item in argv]), out.getvalue()


def in_work_tree():
    """Return True when this repository is the top level of a git work tree."""
    top = hygiene.git(ROOT, "rev-parse", "--show-toplevel")
    return top is not None and Path(os.fsdecode(top.rstrip(b"\r\n"))).resolve() == ROOT


class HygieneTests(unittest.TestCase):
    @unittest.skipUnless(in_work_tree(), "the scanner lists files through git, and this copy is not a git work tree")
    def test_repository_is_clean(self):
        code, out = main()
        self.assertEqual(code, 0, out)

    def test_each_pattern_reports_one_sample_and_passes_another(self):
        for rule, reported, passing in CASES:
            with self.subTest(reported=reported):
                self.assertEqual({hit[0] for hit in hygiene.line_hits(reported)}, {rule})
                self.assertEqual(list(hygiene.line_hits(passing)), [])

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_staged_content_is_checked_and_not_the_work_tree(self):
        env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, env):
            path = Path(root) / "a.md"
            path.write_text(HOME_PATH + "\n", encoding="utf-8")
            for args in (("init", "-q"), ("add", "a.md")):
                subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)
            path.write_text("clean\n", encoding="utf-8")
            self.assertEqual(hygiene.scan(root), [])
            self.assertEqual(hygiene.scan(root, staged=True), [("local", "a.md", 1, HOME_PATH.rsplit("/", 1)[0])])

    def test_a_commit_message_is_checked_up_to_the_scissors_line(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "message"

            def code(text):
                path.write_text(text, encoding="utf-8")
                return main("--commit-msg", path)[0]

            self.assertEqual(main("--commit-msg", path)[0], 2, "a missing file is an error")
            self.assertEqual(code("Add option\n\n- Add the option.\n"), 0)
            self.assertEqual(code("Add option\n\nTested in " + HOME_PATH + "\n"), 1)
            self.assertEqual(code("Add option\n" + SCISSORS + "-" + HOME_PATH + "\n"), 0)
            self.assertEqual(code(f"Add option\n\n# Author:    A Person <{MAIL}>\n# Committer: B <{MAIL}>\n"), 0)
            self.assertEqual(code(f"Add option\n\n# Reviewer: {MAIL}\n"), 1)

    def test_a_secret_is_shown_by_its_first_eight_characters_only(self):
        self.assertEqual(list(hygiene.line_hits("AKI" + "A" + "B" * 16)), [("secret", "AKIABBBB...")])


if __name__ == "__main__":
    unittest.main()
