"""Tests for tools/hygiene.py."""

import contextlib
import io
import os
import re
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
SCISSORS = "# " + "-" * 24 + " >8 " + "-" * 24 + "\n"
RUNTIMES_DOC = "docs/runtimes.md"
# The allowlists that the tests run with hold names reserved for examples (RFC 2606).
DOC_HOST = "docs.example.org"
ALLOWED = {"LICENSE": ("any", None), RUNTIMES_DOC: ("hosts", frozenset({DOC_HOST}))}
# Hosts that resemble a reserved name and are not one. None can exist in the DNS: most end in .alt,
# which RFC 9476 keeps out of it, and the others hold a label longer than the 63 characters that
# the DNS allows.
ALT = ".alt"
LONG = "x" * 64
RESERVED = ("example.com", "example.net", "example.org", "host.test", "host.example", "host.invalid")
LOOKALIKES = ([name + ALT for name in RESERVED] + [name + "x" + ALT for name in RESERVED]
              + [name + "-x" + ALT for name in RESERVED] + [LONG + name for name in RESERVED[:3]]
              + [LONG + "-" + name for name in RESERVED[:3]]
              + ["host." + LONG + name[5:] for name in RESERVED[3:]] + ["host" + ALT])
# The first three octets of the documentation ranges of RFC 5737, and one address next to each.
DOC_NETS = ((192, 0, 2), (198, 51, 100), (203, 0, 113))
NEXT_TO_DOC_NETS = [f"{a}.{b}.{c + 1}.1" for a, b, c in DOC_NETS]

# rule: [(path, violating text)], then [(path, text that passes)]
CASES = {
    "state": ([("notes/TO" + "DO.md", "x"), ("templates/TO" + "DO.md", "x"), (".claude/settings.json", "{}"),
               (".gemini/settings.json", "{}"), (".agents/skills/x/SKILL.md", "x"), ("run.log", "x")],
              [("docs/todo-format.md", "x"), ("templates/block.md", "x")]),
    "link": ([("README.md", LINK + DOC_HOST + "/docs"), (RUNTIMES_DOC, LINK + "other.example.org/x"),
              (RUNTIMES_DOC, HTTP + DOC_HOST + "/docs"),
              ("README.md", "ft" + "p://files.example.org/x"), ("LICENSE", "ft" + "p://files.example.org/x"),
              ("README.md", "See ww" + "w.example.org."), (RUNTIMES_DOC, "ww" + "w." + DOC_HOST + "/docs")],
             [(RUNTIMES_DOC, LINK + DOC_HOST + "/docs"),
              ("LICENSE", LINK + "ww" + "w.example.org/licenses/"), ("LICENSE", "see ww" + "w.example.org/licenses/."),
              ("a.md", "see docs/runtimes.md"), ("a.md", "the www directory"), ("a.md", "a.www.example"),
              ("a.md", "a.ww" + "w.example.org"), ("a.md", "name@ww" + "w.example.org"),
              ("a.md", "aww" + "w.example.org"), ("a.md", "dir/ww" + "w.example.org"),
              ("a.md", "host:ww" + "w.example.org"), ("a.md", "my-ww" + "w.example.org")]),
    "local": ([("a.md", HOME_PATH), ("a.md", "host 10.1." + "2.3"), ("a.md", "HOST=10.1." + "2.3"),
               ("a.md", "Connect to 10.20." + "30.40."), ("a.md", "/Us" + "ers/name"),
               *[("a.md", "name@" + host) for host in LOOKALIKES],
               ("a.md", "C:" + "\\Users\\name"), ("a.md", "D:" + "\\Users\\name"),
               ("a.md", '"C:' + '\\\\Users\\\\name"'), ("a.md", "path=C:" + "\\\\Users\\\\"),
               ("a.md", "C:" + "/Us" + "ers/name"), ("a.md", "c:" + "/users/"),
               *[("a.md", "host " + address) for address in NEXT_TO_DOC_NETS],
               ("a.md", "host 192.168." + "2.1"), ("a.md", "host 198.051." + "100.5")],
              [("a.md", "listens on 127.0.0.1"), ("a.md", "version 1.2." + "3.4 and v1.2." + "3.4"),
               ("a.md", "version 1.2." + "3.4."), ("a.md", "release 1.2." + "3.4.5"),
               ("a.md", "name@" + "example.com"), ("a.md", "Mail name@" + "example.org."),
               ("a.md", "name@" + "example.net"), ("a.md", "the @AGENTS.md line"),
               ("a.md", "name@" + "host.example.org"), ("a.md", "name@" + "mail.dev.example.net"),
               ("a.md", "name@" + "host.test"), ("a.md", "Mail name@" + "host.example."),
               ("a.md", "name@" + "host.invalid"), ("a.md", "NAME@" + "HOST.TEST"),
               ("a.md", "the D:" + "\\build folder"), ("a.md", "the C:" + "/Program Files folder"),
               ("a.md", "the C:" + "\\UsersGuide file"), ("a.md", "ABC:" + "\\Users\\x"),
               ("a.md", "host 192.0." + "2.1"), ("a.md", "host 198.51." + "100.7"),
               ("a.md", "host 203.0." + "113.255.")]),
    "secret": ([("a.md", "AKI" + "A" + "B" * 16), ("a.md", "github" + "_pat_" + "a" * 30),
                ("a.md", "xox" + "b-123456789012"), ("a.md", "glp" + "at-" + "a" * 20),
                ("a.md", "AI" + "za" + "a" * 35), ("a.md", "-----BEGIN PGP PRIVATE" + " KEY BLOCK-----"),
                ("a.md", "-----BEGIN RSA PRIVATE" + " KEY-----"), ("a.md", "sk_" + "live_" + "a1" * 12),
                ("a.md", "rk_" + "live_" + "a1" * 12), ("a.md", "np" + "m_" + "a1B2" * 9),
                ("a.md", "pyp" + "i-AgEIcHlwaS5vcmc" + "a" * 60)],
               [("a.md", "an access key"), ("a.md", "task-" + "a" * 30),
                ("a.md", "-----BEGIN PGP PUBLIC KEY BLOCK-----"), ("a.md", "sk_" + "live_ keys"),
                ("a.md", "sk_" + "test_" + "a1" * 12), ("a.md", "np" + "m_" + "a" * 20),
                ("a.md", "the pypi-attestations package")]),
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


class RepositoryTests(unittest.TestCase):
    def test_repository_is_clean(self):
        code, out = main()
        self.assertEqual(code, 0, out)

    def test_every_allowed_documentation_host_is_linked_from_the_runtimes_file(self):
        text = (ROOT / RUNTIMES_DOC).read_text(encoding="utf-8")
        for host in sorted(hygiene.DOCS_HOSTS):
            with self.subTest(host=host):
                self.assertRegex(text, re.escape(LINK + host) + r"(?![\w.-])")


class ListCase(unittest.TestCase):
    """Runs with link allowlists that hold reserved names."""

    def setUp(self):
        patch = mock.patch.dict(hygiene.ALLOWED_LINKS, ALLOWED)
        patch.start()
        self.addCleanup(patch.stop)


class RuleTests(ListCase):
    def test_each_rule_fires_and_has_a_passing_case(self):
        for rule, (bad, good) in CASES.items():
            for rel, text in bad:
                with self.subTest(rule, rel=rel, text=text[:30]), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, text), {rule})
            for rel, text in good:
                with self.subTest(rule, rel=rel, text=text[:30]), tempfile.TemporaryDirectory() as root:
                    self.assertEqual(rules(root, rel, text), set())

    def test_files_in_antigravity_agent_folders_are_flagged_as_working_state(self):
        with tempfile.TemporaryDirectory() as root:
            for folder in (".agent", "_agents", "_agent"):
                rel = folder + "/rules/style.md"
                with self.subTest(folder=folder):
                    self.assertEqual(rules(root, rel, "x"), {"state"})
            for rel in ("docs/_agents.md", "my_agents/notes.md", "_agents_guide/a.md"):
                with self.subTest(rel=rel):
                    self.assertEqual(rules(root, rel, "x"), set())

    def test_file_names_are_checked(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(rules(root, "name@host" + ALT, "x"), {"local"})

    def test_unreadable_files_are_reported(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "b.bin").write_bytes(b"\xff\xfe")
            Path(root, "link").symlink_to("absent")
            odd = os.fsdecode(b"odd\xff.md")
            Path(root, odd).write_text("x\n")
            found = hygiene.scan(["b.bin", "link", odd], root)
            self.assertEqual([item[0] for item in found], ["file", "file"])
            self.assertIn("name", found[1][3])
            self.assertEqual(hygiene.repository_files(root), sorted(["b.bin", "link", odd]))

    def test_symbolic_links_are_scanned_as_their_target_text(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "inside.md").write_text(HOME_PATH + "\n")
            Path(root, "folder").mkdir()
            Path(root, "clean.md").symlink_to("inside.md")
            Path(root, "dir-link").symlink_to("folder")
            Path(root, "home.md").symlink_to(HOME_PATH)
            self.assertEqual(hygiene.scan(["clean.md"], root), [])
            self.assertEqual(hygiene.scan(["dir-link"], root), [])
            self.assertEqual(hygiene.scan(["home.md"], root), [("local", "home.md", 1, HOME_PATH[:-8])])
            listed = hygiene.repository_files(root)
            self.assertIn("dir-link", listed)
            self.assertNotIn("folder", listed)


class LinkAllowlistTests(ListCase):
    def test_runtimes_allows_a_listed_host_only_and_rejects_bypasses(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(rules(root, RUNTIMES_DOC, f"See [docs]({LINK}{DOC_HOST}/guide)."), set())
            self.assertEqual(rules(root, "README.md", f"{LINK}{DOC_HOST}/docs"), {"link"})
        bad_lines = (
            LINK + "user" + "@" + DOC_HOST + "/docs",
            LINK + "user:@" + DOC_HOST + "/docs",
            LINK + DOC_HOST + ":443/docs",
            HTTP + DOC_HOST + "/docs",
            "[x](" + LINK + DOC_HOST + "'@other.example/)",
            "[x](" + LINK + DOC_HOST + "\"@other.example/)",
            "[x](" + LINK + DOC_HOST + "`@other.example/)",
            LINK + "sub." + DOC_HOST + "/docs",
            LINK + "example.com/docs",
        )
        for line in bad_lines:
            with self.subTest(line=line), tempfile.TemporaryDirectory() as root:
                self.assertIn("link", rules(root, RUNTIMES_DOC, line))


class SkillSourceTests(unittest.TestCase):
    def coverage(self, name):
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        return next(line for line in text.splitlines() if line.startswith("Current to "))

    def test_a_source_address_is_allowed_only_in_its_own_skill_and_coverage_line(self):
        rel = "skills/mpa-hugo/SKILL.md"
        line = self.coverage("mpa-hugo")
        address = LINK + hygiene.SKILL_SOURCES["mpa-hugo"][0]
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(rules(root, rel, line), set())
            self.assertEqual(rules(root, rel, line + "\n\nSee " + address), {"link"})
            self.assertEqual(rules(root, "skills/mpa-go/SKILL.md", line), {"link", "coverage"})
            self.assertEqual(rules(root, "skills/mpa-review/SKILL.md", line), {"link"})
            self.assertEqual(rules(root, "templates/block.md", line), {"link"})

    def test_a_coverage_line_with_another_address_or_none_is_reported(self):
        rel = "skills/mpa-hugo/SKILL.md"
        line = self.coverage("mpa-hugo")
        address = LINK + hygiene.SKILL_SOURCES["mpa-hugo"][0]
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(rules(root, rel, line.replace(address, address + "x")), {"link", "coverage"})
            self.assertEqual(rules(root, rel, line.replace(address, address + ", " + address)), {"link", "coverage"})
            self.assertEqual(rules(root, rel, line.replace(address, HTTP + address[len(LINK):])),
                             {"link", "coverage"})
            self.assertEqual(rules(root, rel, "No coverage line."), {"coverage"})


class SelectionTests(unittest.TestCase):
    def test_directory_arguments_select_files(self):
        files = ["README.md", "docs/a.md", "docs/b.md"]
        self.assertEqual(hygiene.select(files, [], ROOT), files)
        self.assertEqual(hygiene.select(files, [ROOT], ROOT), files)
        self.assertEqual(hygiene.select(files, [ROOT / "docs", ROOT / "docs/a.md"], ROOT), files[1:])

    def test_symbolic_link_arguments_select_the_link_itself(self):
        with tempfile.TemporaryDirectory() as holder:
            root = Path(holder).resolve()
            outside = root / "outside.md"
            outside.write_text("x\n")
            repo = root / "repo"
            (repo / "docs").mkdir(parents=True)
            (repo / "docs/a.md").write_text("x\n")
            (repo / "out-link").symlink_to("../outside.md")
            (repo / "in-link").symlink_to("docs/a.md")
            (repo / "loop").symlink_to("loop")
            files = ["docs/a.md", "in-link", "loop", "out-link"]
            for item, expected in (("out-link", ["out-link"]), ("in-link", ["in-link"]), ("loop", ["loop"])):
                with self.subTest(item):
                    self.assertEqual(hygiene.select(files, [repo / item], repo), expected)
            with mock.patch.object(hygiene, "ROOT", repo), mock.patch.object(hygiene, "repository_files",
                                                                             return_value=files):
                self.assertEqual(main(repo / "out-link")[0], 0)

    def test_a_runtime_error_in_path_selection_exits_with_2_and_no_traceback(self):
        with mock.patch.object(hygiene, "select", side_effect=RuntimeError("Symlink loop from 'x'")):
            code, out = main()
        self.assertEqual(code, 2)
        self.assertEqual(out, "hygiene: Symlink loop from 'x'\n")

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
        self.path.write_bytes(text.encode("utf-8"))
        return main("--commit-msg", self.path)[0]

    def test_plain_message_passes(self):
        self.assertEqual(self.code("Add Hugo and WordPress skills\n\n- Add the platform skills.\n"), 0)

    def test_link_and_local_path_fail(self):
        self.assertEqual(self.code("Add option\n\nSee " + LINK + "example.com\n"), 1)
        self.assertEqual(self.code("Add option\n\nTested in " + HOME_PATH + "\n"), 1)

    def test_comment_lines_are_checked_up_to_the_verbose_scissors_block(self):
        verbose = SCISSORS + "# Do not modify or remove the line above.\n# Everything below it will be ignored.\n"
        self.assertEqual(self.code("Add option\n# " + HOME_PATH + "\n"), 1)
        self.assertEqual(self.code("Add option\n" + verbose + "+" + HOME_PATH + "\n"), 0)
        lf_cut = "Add option\r\n" + SCISSORS + "# Do not modify or remove the line above.\r\n" + HOME_PATH
        self.assertEqual(self.code(lf_cut), 0)

    def test_a_crlf_scissors_line_does_not_end_the_scan(self):
        verbose = SCISSORS + "# Do not modify or remove the line above.\n"
        crlf = "Add option\r\n" + verbose.replace("\n", "\r\n") + HOME_PATH + "\r\n"
        self.assertEqual(self.code(crlf), 1)
        self.assertEqual(len(hygiene.scan_message(crlf, "m", editing=True)), 1)

    def test_a_scissors_line_with_a_translated_explanation_ends_the_scan(self):
        german = (SCISSORS + "# \u00c4ndern oder entfernen Sie nicht die obige Zeile.\n"
                  "# Alles unterhalb von ihr wird ignoriert.\n")
        self.assertEqual(self.code("Add option\n" + german + "+" + HOME_PATH + "\n"), 0)
        self.assertEqual(self.code(HOME_PATH + "\n" + german), 1)

    def test_a_bare_scissors_line_does_not_end_the_scan(self):
        self.assertEqual(self.code("Add option\n" + SCISSORS + HOME_PATH + "\n"), 1)
        verbose = SCISSORS + "# Do not modify or remove the line above.\n"
        self.assertEqual(len(hygiene.scan_message("Add option\n" + verbose + HOME_PATH + "\n", "c")), 1)

    def test_identity_comment_lines_from_git_are_skipped(self):
        mail = "a@host" + ALT
        identity = f"# Author:    A Person <{mail}>\n# Committer: B <{mail}>\n# Date:      Mon\n"
        self.assertEqual(self.code("Add option\n\n" + identity), 0)
        self.assertEqual(len(hygiene.scan_message("Add option\n\n" + identity, "c")), 2)
        self.assertEqual(self.code(f"Add option\n\n# Reviewer: {mail}\n"), 1)
        for line in (f"# Author: A Person <{mail}>", f"# Committer:  B <{mail}>",
                     f"# Date: Mon {mail}", f"# Author:     A <{mail}>"):
            with self.subTest(line=line):
                self.assertEqual(self.code("Add option\n\n" + line + "\n"), 1)
        self.assertEqual(self.code(f"Add option\n\nAuthor: {mail}\n"), 1)

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

    def test_staged_type_change_to_a_symbolic_link_is_checked(self):
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
            base = ["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.com"]
            path = Path(root) / "a.md"
            path.write_text("clean\n")
            for args in (("init", "-q"), ("add", "a.md"), ("commit", "-q", "-m", "Clean subject")):
                subprocess.run([*base, *args], check=True, capture_output=True, env=env)
            path.unlink()
            path.symlink_to(HOME_PATH)
            subprocess.run([*base, "add", "a.md"], check=True, capture_output=True, env=env)
            with mock.patch.object(hygiene, "ROOT", Path(root)), mock.patch.dict(os.environ, env):
                code, out = main("--staged")
            self.assertEqual(code, 1, out)
            self.assertIn("local a.md:1", out)

    def test_log_scans_text_after_a_scissors_line(self):
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
            base = ["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.com"]
            Path(root, "a.md").write_text("ok\n")
            message = Path(root, "message.txt")
            message.write_text("Clean subject\n\n" + SCISSORS + "# Do not modify or remove the line above.\n"
                               + HOME_PATH + "\n")
            for args in (("init", "-q"), ("add", "a.md"), ("commit", "-q", "-F", str(message))):
                subprocess.run([*base, *args], check=True, capture_output=True, env=env)
            logged = subprocess.run([*base, "log", "-1", "--format=%B"], check=True, capture_output=True, env=env)
            self.assertIn(HOME_PATH, logged.stdout.decode())
            with mock.patch.object(hygiene, "ROOT", Path(root)), mock.patch.dict(os.environ, env):
                code, out = main("--log", "HEAD")
            self.assertEqual(code, 1, out)
            self.assertIn("local ", out)

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
