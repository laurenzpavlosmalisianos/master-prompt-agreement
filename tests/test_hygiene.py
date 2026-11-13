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

LINK = "https" + "://"
HOME_PATH = "/ho" + "me/name/project"
# rule: [(path, violating text)], then [(path, text that passes)]
CASES = {
    "state": ([("notes/TO" + "DO.md", "x"), (".claude/settings.json", "{}"), ("run.log", "x"),
               ("templates/TO" + "DO.md", "- item")],
              [("templates/TO" + "DO.md", "x"), ("docs/todo-format.md", "x")]),
    "link": ([("README.md", LINK + "code.claude.com/docs"), ("docs/runtimes.md", LINK + "example.com/x"),
              ("docs/runtimes.md", "http" + "://code.claude.com/docs")],
             [("docs/runtimes.md", LINK + "code.claude.com/docs"), ("a.md", "see docs/runtimes.md")]),
    "local": ([("a.md", HOME_PATH), ("a.md", "host 10.1." + "2.3"), ("a.md", "name@" + "host.example.org"),
               ("a.md", "/Us" + "ers/name")],
              [("a.md", "listens on 127.0.0.1"), ("a.md", "version 1.2." + "3.4 and v1.2." + "3.4"),
               ("a.md", "name@" + "example.com"), ("a.md", "the @AGENTS.md line")]),
    "secret": ([("a.md", "AKI" + "A" + "B" * 16), ("a.md", "github" + "_pat_" + "a" * 30),
                ("a.md", "xox" + "b-123456789012"), ("a.md", "glp" + "at-" + "a" * 20),
                ("a.md", "AI" + "za" + "a" * 35)],
               [("a.md", "an access key"), ("a.md", "task-" + "a" * 30)]),
    "size": ([("a.md", "x " * 3000)], [("a.md", "x " * 100)]),
}


def rules(root, rel, text):
    """Write text to root/rel and return the set of rules it breaks."""
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    found = hygiene.scan([rel], root)
    path.unlink()
    return {item[0] for item in found}


def main(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        return hygiene.main([str(item) for item in argv]), out.getvalue()


class RuleTests(unittest.TestCase):
    def test_repository_is_clean(self):
        code, out = main()
        self.assertEqual(code, 0, out)

    def test_each_rule_fires_and_has_a_passing_case(self):
        for rule, (bad, good) in CASES.items():
            for rel, text in bad:
                with self.subTest(rule, text=text[:30]), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, text), {rule})
            for rel, text in good:
                with self.subTest(rule, text=text[:30]), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, text), set())

    def test_file_names_are_checked(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(rules(root, "name@" + "host.example.org.md", "x"), {"local"})

    def test_unreadable_files_are_reported(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "b.bin").write_bytes(b"\xff\xfe")
            Path(root, "link").symlink_to("absent")
            odd = os.fsdecode(b"odd\xff.md")
            Path(root, odd).write_text("x\n")
            found = hygiene.scan(["b.bin", "link", odd], root)
            self.assertEqual([item[0] for item in found], ["file", "file", "file"])
            self.assertIn("name", found[2][3])
            self.assertEqual(hygiene.repository_files(root), sorted(["b.bin", "link", odd]))


class SelectionTests(unittest.TestCase):
    def test_directory_arguments_select_files(self):
        files = ["README.md", "docs/a.md", "docs/b.md"]
        self.assertEqual(hygiene.select(files, [], ROOT), files)
        self.assertEqual(hygiene.select(files, [ROOT], ROOT), files)
        self.assertEqual(hygiene.select(files, [ROOT / "docs", ROOT / "docs/a.md"], ROOT), files[1:])

    def test_bad_path_arguments_are_errors(self):
        for item in (ROOT.parent, ROOT / "absent.md"):
            with self.subTest(item.name):
                self.assertEqual(main(item)[0], 2)


class MessageTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.path = Path(holder.name) / "message"

    def code(self, text):
        self.path.write_text(text)
        return main("--commit-msg", self.path)[0]

    def test_plain_message_passes(self):
        self.assertEqual(self.code("Add --state option to init\n\n- Add the option.\n"), 0)

    def test_link_and_local_path_fail(self):
        self.assertEqual(self.code("Add option\n\nSee " + LINK + "code.claude.com\n"), 1)
        self.assertEqual(self.code("Add option\n\nTested in " + HOME_PATH + "\n"), 1)

    def test_comment_lines_are_checked_up_to_the_scissors_line(self):
        scissors = "# " + "-" * 24 + " >8 " + "-" * 24 + "\n"
        self.assertEqual(self.code("Add option\n# " + HOME_PATH + "\n"), 1)
        self.assertEqual(self.code("Add option\n" + scissors + "+" + HOME_PATH + "\n"), 0)

    def test_missing_message_file_is_an_error(self):
        self.assertEqual(main("--commit-msg", self.path)[0], 2)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class StagedTests(unittest.TestCase):
    def test_staged_content_is_checked_and_not_the_work_tree(self):
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
            path = Path(root) / "a.md"
            path.write_text(HOME_PATH + "\n")
            for args in (("init", "-q"), ("add", "a.md")):
                subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, env=env)
            path.write_text("clean\n")
            with mock.patch.object(hygiene, "ROOT", Path(root)), mock.patch.dict(os.environ, env):
                self.assertEqual(main()[0], 0)
                code, out = main("--staged")
            self.assertEqual(code, 1)
            self.assertIn("local a.md:1", out)
