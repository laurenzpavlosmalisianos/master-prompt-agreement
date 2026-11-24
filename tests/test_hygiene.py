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
HTTP = "http" + "://"
HOME_PATH = "/ho" + "me/name/project"
CHROME_REPO = "github.com/GoogleChrome/modern-web-guidance-src"
CF_REPO = "github.com/cloudflare/security-audit-skill"
EXT_DOC = "docs/external-skills.md"
RUNTIMES_DOC = "docs/runtimes.md"

# rule: [(path, violating text)], then [(path, text that passes)]
CASES = {
    "state": ([("notes/TO" + "DO.md", "x"), ("templates/TO" + "DO.md", "x"), (".claude/settings.json", "{}"),
               (".gemini/settings.json", "{}"), (".agents/skills/x/SKILL.md", "x"), ("run.log", "x")],
              [("docs/todo-format.md", "x"), ("templates/block.md", "x")]),
    "link": ([("README.md", LINK + "code.claude.com/docs"), (RUNTIMES_DOC, LINK + "example.com/x"),
              (RUNTIMES_DOC, HTTP + "code.claude.com/docs"), (EXT_DOC, LINK + "github.com/other/repo")],
             [(RUNTIMES_DOC, LINK + "code.claude.com/docs"), (EXT_DOC, LINK + CHROME_REPO),
              ("LICENSE", LINK + "www.apache.org/licenses/"), ("a.md", "see docs/runtimes.md")]),
    "local": ([("a.md", HOME_PATH), ("a.md", "host 10.1." + "2.3"), ("a.md", "HOST=10.1." + "2.3"),
               ("a.md", "name@" + "host.example.org"), ("a.md", "/Us" + "ers/name")],
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
                with self.subTest(rule, rel=rel, text=text[:30]), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, text), {rule})
            for rel, text in good:
                with self.subTest(rule, rel=rel, text=text[:30]), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, text), set())

    def test_templates_todo_is_flagged_as_working_state(self):
        rel = "templates/TO" + "DO.md"
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Notes\n")
            self.assertEqual(hygiene.scan([rel], root), [("state", rel, 0, "working-state path")])

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


class LinkAllowlistTests(unittest.TestCase):
    def test_external_skills_allows_exact_vendor_root_urls(self):
        for repo in (CHROME_REPO, CF_REPO):
            samples = (
                LINK + repo,
                LINK + repo + "/",
                f"[vendor]({LINK}{repo})",
                f"[vendor]({LINK}{repo}/).",
                f"`{LINK}{repo}`",
                f"See `{LINK}{repo}`.",
                f"See {LINK}{repo}.",
                f"See {LINK}{repo}/;",
            )
            for line in samples:
                with self.subTest(line=line), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, EXT_DOC, line), set())

    def test_external_skills_rejects_spoofs_subpaths_traversal_params_and_bypasses(self):
        bad_lines = (
            LINK + CHROME_REPO + "-evil",
            LINK + CF_REPO + "-evil",
            LINK + CHROME_REPO + "/blob/main/README.md",
            LINK + CF_REPO + "/blob/main/README.md",
            LINK + CF_REPO + "/../other/repo",
            LINK + CF_REPO + "/../",
            LINK + CF_REPO + "/..",
            LINK + CF_REPO + "/.",
            "[x](" + LINK + CF_REPO + "/..)",
            "[x](" + LINK + CF_REPO + "/.)",
            "[x](" + LINK + CF_REPO + "?)",
            LINK + CF_REPO + "?",
            LINK + CF_REPO + "/%2e%2e/other/repo",
            LINK + CF_REPO + "/%2E%2E/other/repo",
            LINK + "user" + "@" + CF_REPO,
            LINK + "user:@" + CHROME_REPO,
            LINK + "github.com:443/GoogleChrome/modern-web-guidance-src",
            LINK + "github.com:443/cloudflare/security-audit-skill",
            LINK + CF_REPO + "?a=1",
            LINK + CF_REPO + "#top",
            LINK + CF_REPO + "#",
            HTTP + CHROME_REPO,
            HTTP + CF_REPO,
            LINK + "github.com/other/repo",
            LINK + "github.com",
            LINK + "github.com/",
            "[x](" + LINK + CF_REPO + "'/../../other/repo)",
            "[x](" + LINK + CF_REPO + "`/../../other/repo)",
            "[x](" + LINK + CF_REPO + "\"/../../other/repo)",
            LINK + CF_REPO + "/" + LINK + "example.com/",
        )
        for line in bad_lines:
            with self.subTest(line=line), tempfile.TemporaryDirectory() as root:
                self.assertIn("link", rules(root, EXT_DOC, line))

    def test_vendor_urls_are_rejected_outside_external_skills_doc(self):
        for rel in ("README.md", RUNTIMES_DOC, "skills/mpa-web-frontend/SKILL.md"):
            for repo in (CHROME_REPO, CF_REPO):
                with self.subTest(rel=rel, repo=repo), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, LINK + repo), {"link"})

    def test_runtimes_allows_all_official_docs_hosts_and_rejects_bypasses(self):
        self.assertEqual(len(hygiene.DOCS_HOSTS), 7)
        for host in sorted(hygiene.DOCS_HOSTS):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as root:
                self.assertEqual(rules(root, RUNTIMES_DOC, f"See [docs]({LINK}{host}/guide)."), set())
        bad_lines = (
            LINK + "user" + "@" + "code.claude.com/docs",
            LINK + "user:@" + "code.claude.com/docs",
            LINK + "code.claude.com:443/docs",
            HTTP + "code.claude.com/docs",
            "[x](" + LINK + "code.claude.com'@other.example/)",
            "[x](" + LINK + "code.claude.com\"@other.example/)",
            "[x](" + LINK + "code.claude.com`@other.example/)",
            LINK + "example.com/docs",
        )
        for line in bad_lines:
            with self.subTest(line=line), tempfile.TemporaryDirectory() as root:
                self.assertIn("link", rules(root, RUNTIMES_DOC, line))


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
        self.assertEqual(self.code("Add Hugo and WordPress skills\n\n- Add the platform skills.\n"), 0)

    def test_link_and_local_path_fail(self):
        self.assertEqual(self.code("Add option\n\nSee " + LINK + "code.claude.com\n"), 1)
        self.assertEqual(self.code("Add option\n\nTested in " + HOME_PATH + "\n"), 1)

    def test_comment_lines_are_checked_up_to_the_scissors_line(self):
        scissors = "# " + "-" * 24 + " >8 " + "-" * 24 + "\n"
        self.assertEqual(self.code("Add option\n# " + HOME_PATH + "\n"), 1)
        self.assertEqual(self.code("Add option\n" + scissors + "+" + HOME_PATH + "\n"), 0)
        self.assertEqual(hygiene.scan_message("Add option\r\n" + scissors.replace("\n", "\r\n") + HOME_PATH, "m"), [])

    def test_secret_preview_and_non_git_walk_prune_git_dir(self):
        hits = list(hygiene.line_hits("AKI" + "A" + "B" * 16, "a.md"))
        self.assertEqual(hits, [("secret", "AKIABBBB...")])
        with tempfile.TemporaryDirectory() as root:
            Path(root, ".git").mkdir()
            Path(root, ".git/config").write_text(HOME_PATH + "\n")
            Path(root, "sub").mkdir()
            Path(root, "sub/a.md").write_text("clean\n")
            self.assertEqual(hygiene.repository_files(root), ["sub/a.md"])

    def test_missing_message_file_is_an_error(self):
        self.assertEqual(main("--commit-msg", self.path)[0], 2)

    def test_conflicting_mode_flags_are_errors(self):
        self.path.write_text("Clean\n")
        self.assertEqual(main("--commit-msg", self.path, "--log", "HEAD")[0], 2)
        self.assertEqual(main("--log", "HEAD", "README.md")[0], 2)
        self.assertEqual(main("--commit-msg", self.path, "--staged")[0], 2)
        self.assertEqual(main("--commit-msg", "")[0], 2)
        self.assertEqual(main("--log", "")[0], 2)
        self.assertEqual(main("--commit-msg", "", "--log", "HEAD")[0], 2)

    def test_multiple_hits_on_one_line_are_all_reported(self):
        hits = list(hygiene.line_hits(f"{HOME_PATH} and /Us" + "ers/other", "a.md"))
        self.assertEqual(len(hits), 2)


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

    def test_log_scans_commit_messages(self):
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
            Path(root, "a.md").write_text("ok\n")
            base = ["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.com"]
            for args in (("init", "-q"), ("add", "a.md"), ("commit", "-q", "-m", "Clean subject")):
                subprocess.run([*base, *args], check=True, capture_output=True, env=env)
            with mock.patch.object(hygiene, "ROOT", Path(root)), mock.patch.dict(os.environ, env):
                self.assertEqual(main("--log", "HEAD")[0], 0)
            Path(root, "a.md").write_text("ok2\n")
            for args in (("add", "a.md"), ("commit", "-q", "-m", "Bad " + HOME_PATH)):
                subprocess.run([*base, *args], check=True, capture_output=True, env=env)
            with mock.patch.object(hygiene, "ROOT", Path(root)), mock.patch.dict(os.environ, env):
                code, out = main("--log", "HEAD~1..HEAD")
            self.assertEqual(code, 1)
            self.assertIn("local ", out)
