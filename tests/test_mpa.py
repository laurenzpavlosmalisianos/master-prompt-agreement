"""Tests for mpa.py and the shipped files."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mpa

sys.path.insert(0, str(ROOT / "tools"))

import hygiene

BOM = "\ufeff"


def run(*argv):
    """Return (exit code, printed text) of mpa.main."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = mpa.main([str(item) for item in argv])
    return code, out.getvalue()


def tree(root):
    """Return {path: bytes} for the files below root, outside .git."""
    files = (p for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.parts)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in files}


class ProjectCase(unittest.TestCase):
    """An empty project directory and fixture skills."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name).resolve()
        self.dir = self.tmp / "project"
        self.dir.mkdir()
        self.agents = self.dir / "AGENTS.md"
        self.skills = self.tmp / "skills"
        for items in mpa.CATALOG.values():
            for name in items:
                (self.skills / name).mkdir(parents=True)
                (self.skills / name / "SKILL.md").write_text(
                    f'---\nname: {name}\ndescription: "Fixture."\n---\nBody.\n',
                    encoding="utf-8",
                )
        patch = mock.patch.object(mpa, "SKILLS", self.skills)
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, rel, data):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def init(self, *args):
        return run("init", self.dir, "--write", *args)

    def check(self):
        return run("check", self.dir)

    def assert_refused(self, command="init", *args):
        before = tree(self.dir)
        code, text = run(command, self.dir, "--write", *args)
        self.assertEqual(code, 1, text)
        self.assertEqual(tree(self.dir), before)
        return text

    def assert_clean(self):
        code, text = self.check()
        self.assertEqual(code, 0, text)

    def git(self, *args):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        base = ["git", "-C", str(self.dir), "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run([*base, *args], check=True, capture_output=True, env=env)


class InitTests(ProjectCase):
    def test_dry_run_writes_nothing(self):
        code, text = run("init", self.dir)
        self.assertEqual(code, 0)
        self.assertIn("create   AGENTS.md", text)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_init_defaults_to_agents_on_a_fresh_project(self):
        code, text = self.init()
        self.assertEqual(code, 0, text)
        self.assertIn("pass --runtime claude for Claude Code", text)
        expected = {"AGENTS.md"} | {f".agents/skills/{name}/SKILL.md" for name in mpa.CATALOG["core"]}
        files = tree(self.dir)
        self.assertEqual(set(files), expected)
        self.assertNotIn("CLAUDE.md", files)
        content = files["AGENTS.md"].decode()
        lines = content.split("\n")
        self.assertEqual(lines[0], "# project")
        self.assertTrue(lines[2].startswith(f"<!-- mpa:begin {mpa.BLOCK_VERSION} "))
        self.assertEqual(
            [title for _, title in mpa.outline(content)[0]],
            ["Working agreement", "Approvals", "Project", "Commands", "Constraints"],
        )
        self.assertIn("check: 0 errors, 0 notes", self.check()[1])
        # Second flagless run does not repeat the fresh-project runtime note.
        code, again = self.init()
        self.assertEqual(code, 0, again)
        self.assertNotIn("pass --runtime claude", again)

    def test_flagless_init_notes_the_runtime_when_agents_md_exists(self):
        (self.dir / "AGENTS.md").write_text("# project\n", encoding="utf-8")
        code, text = self.init()
        self.assertEqual(code, 0, text)
        self.assertIn("pass --runtime claude for Claude Code", text)

    def test_flagless_init_selects_claude_when_claude_files_exist(self):
        cases = (
            ("CLAUDE.md", "# Notes\nKeep.\n", "CLAUDE.md", "@AGENTS.md"),
            (".claude/settings.json", "{}\n", "CLAUDE.md", "@AGENTS.md"),
            (".claude/CLAUDE.md", "Local rules.\n", ".claude/CLAUDE.md", "@../AGENTS.md"),
        )
        for seed_rel, seed_body, import_rel, import_line in cases:
            with self.subTest(seed=seed_rel):
                shutil.rmtree(self.dir)
                self.dir.mkdir()
                self.put(seed_rel, seed_body)
                code, text = self.init()
                self.assertEqual(code, 0, text)
                files = set(tree(self.dir))
                self.assertTrue(all(f".claude/skills/{n}/SKILL.md" in files for n in mpa.CATALOG["core"]))
                self.assertFalse(any(p.startswith(".agents/") for p in files))
                self.assertTrue(mpa.has_import((self.dir / import_rel).read_text(), import_line))
                self.assert_clean()

        # Personal git-ignored CLAUDE.local.md alone does not override the default agents runtime.
        shutil.rmtree(self.dir)
        self.dir.mkdir()
        self.put("CLAUDE.local.md", "Personal.\n")
        code, text = self.init()
        self.assertEqual(code, 0, text)
        self.assertTrue((self.dir / ".agents/skills/mpa-review/SKILL.md").is_file())
        self.assertFalse((self.dir / "CLAUDE.md").exists())

    def test_explicit_agents_runtime_notes_existing_claude_md(self):
        self.put("CLAUDE.md", "# Existing\n")
        code, text = self.init("--runtime", "agents")
        self.assertEqual(code, 0, text)
        self.assertIn("CLAUDE.md exists without an AGENTS.md import and claude is not selected; by default Claude Code"
                      " reads only CLAUDE.md files when one exists, so AGENTS.md loads only through an import.", text)
        self.assertTrue((self.dir / ".agents/skills/mpa-review/SKILL.md").is_file())
        self.assertFalse((self.dir / ".claude").exists())

        # No note once CLAUDE.md already imports AGENTS.md.
        self.put("CLAUDE.md", "@AGENTS.md\n")
        code, text = self.init("--runtime", "agents")
        self.assertEqual(code, 0, text)
        self.assertNotIn("without an AGENTS.md import", text)

        # Names .claude/CLAUDE.md accurately when only that file exists without import.
        (self.dir / "CLAUDE.md").unlink()
        self.put(".claude/CLAUDE.md", "# Nested\n")
        code, text = self.init("--runtime", "agents")
        self.assertEqual(code, 0, text)
        self.assertIn(".claude/CLAUDE.md exists without an AGENTS.md import and claude is not selected", text)

    def test_flagless_init_rerun_preserves_existing_skill_directories(self):
        for runtime, expected_dirs in (
            ("agents", {".agents"}),
            ("claude", {".claude"}),
            ("claude,agents", {".claude", ".agents"}),
        ):
            with self.subTest(runtime=runtime):
                shutil.rmtree(self.dir)
                self.dir.mkdir()
                self.assertEqual(self.init("--runtime", runtime)[0], 0)
                before = tree(self.dir)
                code, text = self.init()
                self.assertEqual(code, 0, text)
                self.assertIn("nothing to do", text)
                self.assertEqual(tree(self.dir), before)
                present_dirs = {p.split("/")[0] for p in before if "/skills/" in p}
                self.assertEqual(present_dirs, expected_dirs)

    def test_runtime_claude_antigravity_and_dual_copy(self):
        self.assertEqual(self.init("--runtime", "claude")[0], 0)
        files = tree(self.dir)
        expected = {"AGENTS.md", "CLAUDE.md"} | {f".claude/skills/{n}/SKILL.md" for n in mpa.CATALOG["core"]}
        self.assertEqual(set(files), expected)
        self.assertEqual(files["CLAUDE.md"], b"@AGENTS.md\n")
        self.assert_clean()

        shutil.rmtree(self.dir)
        self.dir.mkdir()
        self.assertEqual(self.init("--runtime", "antigravity")[0], 0)
        files = tree(self.dir)
        expected = {"AGENTS.md"} | {f".agents/skills/{n}/SKILL.md" for n in mpa.CATALOG["core"]}
        self.assertEqual(set(files), expected)
        self.assert_clean()

        shutil.rmtree(self.dir)
        self.dir.mkdir()
        code, text = self.init("--runtime", "claude,agents")
        self.assertEqual(code, 0, text)
        self.assertIn("doubles startup skill listings", text)
        files = set(tree(self.dir))
        self.assertIn("CLAUDE.md", files)
        for folder in (".claude/skills", ".agents/skills"):
            self.assertTrue(all(f"{folder}/{n}/SKILL.md" in files for n in mpa.CATALOG["core"]))
        self.assert_clean()

    def test_copilot_and_gemini_runtimes_install_the_agents_layout(self):
        for names in ("copilot", "gemini", "agents,copilot", "copilot,gemini"):
            with self.subTest(names=names):
                self.assertEqual(mpa.select_runtimes(names, required=True), ["agents"])
        self.assertEqual(mpa.select_runtimes("claude,gemini", required=True), ["claude", "agents"])
        code, text = self.init("--runtime", "copilot")
        self.assertEqual(code, 0, text)
        self.assertEqual(mpa.installed(self.dir, ".agents/skills"), sorted(mpa.CATALOG["core"]))
        self.assertFalse((self.dir / ".claude").exists())
        self.assert_clean()
        self.assertNotIn("context.fileName", text)
        with tempfile.TemporaryDirectory() as holder:
            code, text = run("init", holder, "--runtime", "claude,gemini")
            self.assertEqual(code, 0, text)
            self.assertIn("note     Gemini CLI reads AGENTS.md only when its context.fileName setting lists it.", text)
        code, text = run("init", self.dir, "--runtime", "copilots")
        self.assertEqual(code, 2)
        self.assertIn("agents, codex, antigravity, generic, claude, copilot, gemini", text)

    def test_individual_only_categories_are_refused_with_skill_list_hint(self):
        for category in mpa.INDIVIDUAL_ONLY:
            with self.subTest(category=category):
                code, text = run("init", self.dir, "--skills", category)
                self.assertEqual(code, 2, text)
                self.assertIn("not an install bundle", text)
                for skill in mpa.CATALOG[category]:
                    self.assertIn(skill, text)

    def test_second_init_changes_nothing(self):
        self.init()
        before = tree(self.dir)
        code, text = self.init()
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", text)
        self.assertEqual(tree(self.dir), before)

    def test_failed_write_leaves_agents_file_for_the_next_run(self):
        real = mpa.write

        def failing(root, rel, data):
            if rel.endswith("mpa-review/SKILL.md"):
                raise OSError(28, "No space left on device")
            real(root, rel, data)

        with mock.patch.object(mpa, "write", failing):
            code, text = self.init("--runtime", "claude")
        self.assertEqual(code, 1)
        self.assertIn("completed: CLAUDE.md", text)
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.init("--runtime", "claude")[0], 0)
        self.assert_clean()

    def test_failed_create_leaves_no_partial_file(self):
        with mock.patch.object(mpa.os, "fsync", side_effect=OSError(5, "Input/output error")):
            self.assertEqual(self.init("--skills=none", "--runtime=agents")[0], 1)
        self.assertEqual(tree(self.dir), {})

    def test_oversized_file_is_refused(self):
        self.put("AGENTS.md", "x" * mpa.MAX_SIZE)
        self.assert_refused()

    def test_init_keeps_an_oversized_agents_file_that_it_does_not_change(self):
        self.init("--skills=none")
        self.agents.write_text(self.agents.read_text() + "x" * mpa.MAX_SIZE + "\n")
        before = self.agents.read_bytes()
        code, text = self.init("--skills", "review")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"keep +AGENTS.md  \(managed block present\)")
        self.assertIn("AGENTS.md exceeds 32 KiB. Codex stops reading instruction files at that size by default,"
                      " Antigravity truncates a rule file at 24,000 bytes, and check reports it as an error.", text)
        self.assertNotIn("exceeds 16 KiB", text)
        self.assertEqual(self.agents.read_bytes(), before)
        self.assertTrue((self.dir / ".agents/skills/mpa-review/SKILL.md").is_file())
        self.assertIn("32 KiB", self.assert_refused("init", "--runtime", "generic", "--skills", "review"))

    def test_init_notes_a_kept_agents_file_above_16_kib(self):
        self.init("--skills=none")
        self.agents.write_text(self.agents.read_text() + "x" * mpa.NOTE_SIZE + "\n")
        code, text = self.init("--skills=none")
        self.assertEqual(code, 0, text)
        self.assertIn("AGENTS.md exceeds 16 KiB", text)
        self.assertNotIn("exceeds 32 KiB", text)

    def test_symbolic_link_loops_are_refused_without_a_traceback(self):
        (self.dir / "CLAUDE.md").symlink_to("CLAUDE.md")
        for command in ("init", "check"):
            with self.subTest(command):
                code, text = run(command, self.dir)
                self.assertEqual(code, 1, text)
                self.assertIn("CLAUDE.md is a symbolic link", text)
                self.assertNotIn("Traceback", text)
        loop = self.tmp / "loop"
        loop.symlink_to("loop")
        for command in ("init", "update", "check"):
            with self.subTest(command, project="loop"):
                code, text = run(command, loop)
                self.assertEqual(code, 1, text)
                self.assertTrue(text.startswith("refused: "), text)

    def test_runtime_errors_from_path_handling_are_refusals(self):
        with mock.patch.object(mpa, "cmd_check", side_effect=RuntimeError("Symlink loop from 'x'")):
            code, text = run("check", self.dir)
        self.assertEqual(code, 1)
        self.assertEqual(text, "refused: RuntimeError: Symlink loop from 'x'\n")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "the platform has no O_NOFOLLOW")
    def test_read_does_not_follow_a_link_that_replaces_a_checked_file(self):
        outside = self.tmp / "outside.md"
        outside.write_text("outside\n")
        self.agents.symlink_to(outside)
        with mock.patch.object(mpa, "target", return_value=self.agents):
            with self.assertRaises(OSError):
                mpa.read(self.dir, "AGENTS.md")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "the platform has no named pipes")
    def test_read_refuses_a_file_that_is_not_regular_once_opened(self):
        os.mkfifo(self.agents)
        with mock.patch.object(mpa, "target", return_value=self.agents):
            with self.assertRaisesRegex(mpa.Refuse, "AGENTS.md is not a regular file"):
                mpa.read(self.dir, "AGENTS.md")

    def test_each_claude_file_selects_the_claude_runtime_and_an_empty_claude_folder_does_not(self):
        (self.dir / ".claude").mkdir()
        self.assertEqual(mpa.default_runtimes(self.dir), ["agents"])
        for rel in ("CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json"):
            with self.subTest(rel):
                path = self.put(rel, "{}\n")
                self.assertEqual(mpa.default_runtimes(self.dir), ["claude"])
                path.unlink()

    def test_block_of_another_version_is_left_to_update(self):
        self.init()
        self.agents.write_text(self.agents.read_text().replace(mpa.BLOCK_VERSION, "6.9.0"))
        self.assertIn("update", self.assert_refused())

    def test_unusual_directory_name_is_not_used_as_title(self):
        for bad in ("a <b> [c](d)", "   "):
            with self.subTest(bad):
                self.dir = self.tmp / bad
                self.dir.mkdir()
                self.init("--skills=none")
                self.assertEqual((self.dir / "AGENTS.md").read_text().split("\n")[0], "# Project")
                self.assert_clean()
                shutil.rmtree(self.dir)

    def test_bom_before_heading_fence_or_comment_is_parsed(self):
        self.assertEqual(mpa.outline(BOM + "## Approvals\nAsk.\n"), ([(1, "Approvals")], False))
        self.assertEqual(mpa.outline(BOM + "```\n## Fake\n```\n## Real\n"), ([(17, "Real")], False))
        self.assertEqual(mpa.outline(BOM + "<!--\n## Fake\n-->\n## Real\n"), ([(18, "Real")], False))
        self.assertEqual(mpa.section(BOM + "## Commands\n- Test:\n", "Commands"), "## Commands\n- Test:")
        self.put("AGENTS.md", BOM + "## Approvals\n\nAsk.\n")
        self.init("--skills=none")
        self.assertEqual(self.agents.read_text().count("## Approvals"), 1)
        self.assert_clean()

    def test_claude_dir_symlink_is_refused_even_when_file_links_back(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "CLAUDE.md").symlink_to(self.dir / "AGENTS.md")
        (self.dir / ".claude").symlink_to(outside)
        self.assertIn(".claude is a symbolic link", self.assert_refused())

    def test_adoption_puts_block_and_missing_sections_after_title(self):
        original = "# Title\n\nPreamble text.\n\n## Approvals\n\nAsk before deploys.\n\n## Style\n\nTabs."
        self.put("AGENTS.md", original)
        code, text = self.init()
        self.assertEqual(code, 0, text)
        self.assertIn("pass --runtime claude for Claude Code", text)
        self.assertRegex(text, r"note +AGENTS.md keeps its existing ## Approvals")
        self.assertNotIn("existing ## Constraints", text)
        self.assertIn("Commands, Constraints sections after the block", text)
        result = self.agents.read_text()
        start, end, _ = mpa.find_block(result)
        self.assertEqual(result[:start], "# Title\n\n")
        self.assertTrue(result[end:].startswith("\n\n## Commands\n"))
        self.assertLess(result.index("## Constraints"), result.index("Preamble text."))
        self.assertTrue(result.endswith("Preamble text.\n\n## Approvals\n\nAsk before deploys.\n\n## Style\n\nTabs."))
        heads = [title for _, title in mpa.outline(result)[0]]
        self.assertEqual(heads, ["Working agreement", "Commands", "Constraints", "Approvals", "Style"])
        self.assert_clean()

    def test_adoption_notes_existing_constraints_section(self):
        original = "# Title\n\n## Constraints\n\n- Keep changes small.\n"
        self.put("AGENTS.md", original)
        code, text = self.init("--skills=none")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"note +AGENTS.md keeps its existing ## Constraints section; add a scope rule if desired\.")
        self.assertNotIn("existing ## Approvals", text)
        result = self.agents.read_text()
        heads = [title for _, title in mpa.outline(result)[0]]
        self.assertEqual(heads, ["Working agreement", "Approvals", "Commands", "Constraints"])
        self.assertIn("- Keep changes small.\n", result)
        self.assert_clean()

    def test_adoption_recognizes_indented_closed_and_tab_separated_headings(self):
        for text, titles in (
            ("   ## Approvals ##\n", ["Approvals"]),
            ("##\tCommands\n", ["Commands"]),
            ("## Constraints #  \n", ["Constraints"]),
            ("## C#\n", ["C#"]),
            ("    ## Code\n", []),
            ("## ##\n", []),
            ("### Deeper\n", []),
            ("##Tight\n", []),
        ):
            self.assertEqual([title for _, title in mpa.outline(text)[0]], titles, text)
        self.put("AGENTS.md", "# T\n\n  ## Approvals ##\n\nAsk.\n\n##\tCommands\n\n- Test: make\n\n## Constraints #\n\n- Keep.\n")
        code, text = self.init("--skills=none")
        self.assertEqual(code, 0, text)
        self.assertNotIn("sections after the block", text)
        result = self.agents.read_text()
        heads = [title for _, title in mpa.outline(result)[0]]
        self.assertEqual(heads, ["Working agreement", "Approvals", "Commands", "Constraints"])
        self.assertNotIn("<!-- Exact commands", result)
        self.assertNotIn("- Scope:", result)
        self.assert_clean()

    def test_adoption_without_title_puts_block_and_sections_first(self):
        original = "Preamble.\n\n```md\n## Approvals\n```\n"
        self.put("AGENTS.md", original)
        self.init("--runtime", "generic")
        result = self.agents.read_text()
        self.assertEqual(mpa.find_block(result)[0], 0)
        self.assertTrue(result.endswith("\n\n" + original))
        heads = [title for _, title in mpa.outline(result)[0]]
        self.assertEqual(heads, ["Working agreement", "Approvals", "Commands", "Constraints", "Guides"])
        self.assert_clean()

    def test_adoption_keeps_bytes_of_a_file_with_unclosed_fence(self):
        original = "Rules\r\n~~~sh\r\nmake\r\n<!-- open\r\n"
        self.put("AGENTS.md", original)
        self.put("CLAUDE.md", "# Notes\nKeep.\n")
        text = self.init()[1]
        self.assertIn("This script does not review it", text)
        result = self.agents.read_bytes()
        self.assertTrue(result.startswith(b"<!-- mpa:begin "))
        self.assertTrue(result.endswith(b"\r\n\r\n" + original.encode()))
        self.assertLess(result.index(b"\r\n## Approvals\r\n"), result.index(original.encode()))
        self.assertNotIn(b"\n", result.replace(b"\r\n", b""))
        claude = (self.dir / "CLAUDE.md").read_text().split()
        self.assertEqual(claude, ["#", "Notes", "@AGENTS.md", "Keep."])
        self.assert_clean()

    def test_file_with_byte_order_mark_is_adopted_and_updated(self):
        for label, body in (("title", "# Title\n\nText.\n"), ("no title", "Text.\n")):
            with self.subTest(label):
                self.put("AGENTS.md", BOM + body)
                self.assertEqual(self.init("--skills=none")[0], 0)
                self.assertTrue(self.agents.read_text().startswith(BOM))
                self.assert_clean()
                self.assertIn("up to date", run("update", self.dir)[1])
                self.agents.unlink()

    def test_import_goes_into_the_nested_claude_file(self):
        self.put(".claude/CLAUDE.md", "Local rules.\n")
        self.init("--runtime", "claude")
        self.assertTrue((self.dir / ".claude/CLAUDE.md").read_text().startswith("@../AGENTS.md\n"))
        self.assertFalse((self.dir / "CLAUDE.md").exists())
        self.assert_clean()

    def test_dual_claude_files_insert_import_only_when_neither_imports(self):
        self.put("CLAUDE.md", "# Root\n\nRoot text.\n")
        self.put(".claude/CLAUDE.md", "Nested text.\n")
        self.assertEqual(self.init("--runtime", "claude", "--skills=none")[0], 0)
        self.assertTrue(mpa.has_import((self.dir / "CLAUDE.md").read_text(), "@AGENTS.md"))
        self.assertEqual((self.dir / ".claude/CLAUDE.md").read_text(), "Nested text.\n")
        self.assert_clean()

        self.put("CLAUDE.md", "# Root\n\nRoot text.\n")
        self.put(".claude/CLAUDE.md", "@../AGENTS.md\n\nNested text.\n")
        code, text = self.init("--runtime", "claude", "--skills=none")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"keep +\.claude/CLAUDE.md  \(import present\)")
        self.assertEqual((self.dir / "CLAUDE.md").read_text(), "# Root\n\nRoot text.\n")
        self.assert_clean()

    def test_import_counts_only_at_line_start_outside_fences(self):
        self.assertTrue(mpa.has_import("# T\n@AGENTS.md  \n", "@AGENTS.md"))
        for text in ("    @AGENTS.md\n", "```\n@AGENTS.md\n```\n", "<!--\n@AGENTS.md\n-->\n", "see @AGENTS.md\n"):
            self.assertFalse(mpa.has_import(text, "@AGENTS.md"), text)

    def test_import_is_found_after_fences_and_comments(self):
        for text in ("# T <!-- c -->\n\n@AGENTS.md\n", "```\ncode\n```\n@AGENTS.md\n",
                     "Use `<!--` markers\n@AGENTS.md\n", "<!-- a -->\n@AGENTS.md\n"):
            self.assertTrue(mpa.has_import(text, "@AGENTS.md"), text)
        for text in ("````\n```\n@AGENTS.md\n````\n", "```\n  ```py\n@AGENTS.md\n```\n",
                     "```\n    ```\n@AGENTS.md\n```\n"):
            self.assertFalse(mpa.has_import(text, "@AGENTS.md"), text)

    def test_headings_inside_comments_are_not_sections(self):
        heads, unclosed = mpa.outline("<!--\n## Approvals\n-->\n## Commands\n")
        self.assertEqual([title for _, title in heads], ["Commands"])
        self.assertFalse(unclosed)
        self.assertTrue(mpa.outline("## A\n<!-- open\n")[1])

    def test_import_after_a_title_comment_is_added_once(self):
        self.put("CLAUDE.md", "# T <!-- c -->\n\nText.\n")
        self.init("--runtime", "claude")
        self.init("--runtime", "claude")
        self.assertEqual((self.dir / "CLAUDE.md").read_text().count("@AGENTS.md"), 1)

    def test_init_notes_existing_files_that_git_cannot_restore(self):
        self.put("AGENTS.md", "# T\n")
        text = self.init("--skills=none")[1]
        self.assertRegex(text, r"note +AGENTS.md is not committed; git cannot restore the old text")

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_init_does_not_note_committed_files(self):
        self.put("AGENTS.md", "# T\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "setup")
        self.assertNotIn("not committed", self.init("--skills=none")[1])

    def test_excludes_are_checked_against_the_active_claude_file_only(self):
        self.init("--runtime", "agents", "--skills=none")
        self.put(".claude/settings.local.json", json.dumps({"claudeMdExcludes": ["CLAUDE.md"]}))
        self.assertNotIn("claudeMdExcludes", self.check()[1])

    def test_wrong_file_types_are_named(self):
        self.put("AGENTS.md/x", "x\n")
        self.assertIn("AGENTS.md is not a regular file", self.assert_refused())

    def test_claude_file_linked_to_agents_file_is_accepted(self):
        (self.dir / "CLAUDE.md").symlink_to("AGENTS.md")
        for runtime in ("agents", "claude"):
            code, text = self.init("--runtime", runtime, "--skills=none")
            self.assertEqual(code, 0, text)
        self.assertTrue((self.dir / "CLAUDE.md").is_symlink())
        self.assert_clean()

    def test_symbolic_links_are_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "a.md").write_text("outside\n")
        self.agents.symlink_to(outside / "a.md")
        self.assert_refused()
        self.agents.unlink()
        (self.dir / ".claude").symlink_to(outside)
        self.assert_refused()
        self.assertEqual(tree(outside), {"a.md": b"outside\n"})

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "the superuser writes to read-only files")
    def test_read_only_file_is_refused(self):
        self.put("AGENTS.md", "# Mine\n").chmod(0o444)
        self.assertIn("AGENTS.md is not writable", self.assert_refused())

    def test_differing_skill_is_refused(self):
        self.put(".claude/skills/mpa-review/SKILL.md", "local text\n")
        self.assertIn("mpa-review", self.assert_refused())

    def test_later_init_adds_the_guides_section_for_the_generic_runtime(self):
        self.init()
        self.assertNotIn("## Guides", self.agents.read_text())
        self.assertNotIn("Guides", self.check()[1])
        code, text = self.init("--runtime", "generic", "--skills=none")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"append +AGENTS.md  \(Guides section at the end\)")
        self.assertIn("applied: 1 file written", text)
        self.assertTrue(self.agents.read_text().endswith("\n\n" + mpa.GUIDES + "\n"))
        self.assertNotIn("Guides", self.check()[1])
        self.assertIn("nothing to do", self.init("--runtime", "generic")[1])

    def test_guides_section_needs_skills_and_the_generic_runtime(self):
        self.init("--runtime", "generic", "--skills=none")
        self.assertNotIn("## Guides", self.agents.read_text())
        self.assertNotIn("Guides", self.check()[1])
        self.init("--runtime", "generic", "--skills", "review")
        self.assertEqual(self.agents.read_text().count("## Guides"), 1)

    def test_guides_section_goes_after_the_block_in_a_file_with_an_unclosed_fence(self):
        self.init("--skills=none")
        self.agents.write_text(self.agents.read_text() + "\n```sh\nmake\n")
        self.init("--runtime", "generic", "--skills", "review")
        result = self.agents.read_text()
        self.assertIn(mpa.END + "\n\n" + mpa.GUIDES + "\n\n## Approvals", result)
        self.assertTrue(result.endswith("```sh\nmake\n"))

    def test_missing_project_and_bad_options_exit_without_traceback(self):
        self.assertEqual(run("init", self.dir / "absent")[0], 1)
        self.assertEqual(run("init", self.dir, "--runtime", "other")[0], 2)
        self.assertEqual(run("init", self.dir, "--skills", "mpa-missing")[0], 2)


class UpdateTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.init()

    def block(self):
        text = self.agents.read_text()
        start, end, _ = mpa.find_block(text)
        return text, start, end

    def test_update_replaces_only_the_block(self):
        text, _, end = self.block()
        old = "<!-- mpa:begin 6.9.0 (old) -->\nold body\n<!-- mpa:end -->"
        self.agents.write_text("# Mine\n\n" + old + text[end:] + "\nTail")
        skill = self.put(".agents/skills/mpa-review/SKILL.md", "stale\n")
        code, plan = run("update", self.dir)
        self.assertEqual(code, 0)
        self.assertIn("3 lines replaced by", plan)
        self.assertEqual(skill.read_text(), "stale\n")
        self.assertEqual(run("update", self.dir, "--write", "--force")[0], 0)
        self.assertEqual(self.agents.read_text(), "# Mine\n\n" + mpa.block_text() + text[end:] + "\nTail")
        self.assertEqual(skill.read_bytes(), (mpa.SKILLS / "mpa-review/SKILL.md").read_bytes())
        self.assert_clean()

    def test_update_refuses_bad_blocks_and_check_reports_them(self):
        text, start, end = self.block()
        begin = text[start:end].split("\n")[0]
        cases = {
            "no block": "# Mine\n",
            "two begins": text + begin + "\n",
            "no end": text.replace(mpa.END, ""),
            "end before begin": mpa.END + "\n" + text.replace(mpa.END, ""),
            "newer version": text.replace(mpa.BLOCK_VERSION, "99.0.0"),
            "long version": text.replace(mpa.BLOCK_VERSION, "7.0.00000"),
        }
        for label, content in cases.items():
            with self.subTest(label):
                self.agents.write_text(content)
                self.assert_refused("update", "--force")
                self.assertEqual(self.check()[0], 1)

    def test_newer_block_refusal_prints_the_block(self):
        text, start, end = self.block()
        self.agents.write_text(text[:start] + "<!-- mpa:begin 99.0.0 (x) -->\nunknown rule text\n" + mpa.END + text[end:])
        self.assertIn("    unknown rule text\n", self.assert_refused("update"))

    def test_older_block_is_a_check_error(self):
        self.agents.write_text(self.agents.read_text().replace(mpa.BLOCK_VERSION, "6.9.0"))
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("run update", text)

    def test_marker_text_inside_a_line_is_not_a_marker(self):
        self.agents.write_text(self.agents.read_text() + "\nThe mpa:begin and `<!-- mpa:end -->` lines mark the block.\n")
        self.assertIn("up to date", run("update", self.dir)[1])
        self.assert_clean()

    def test_marker_lines_inside_code_fences_are_text(self):
        begin = mpa.BEGIN.format(mpa.BLOCK_VERSION)
        doc = f"\n## Markers\n\n```md\n{begin}\n{mpa.END}\n```\n\n~~~\n{mpa.END}\n~~~\n"
        self.agents.write_text(self.agents.read_text() + doc)
        self.assertIn("up to date", run("update", self.dir)[1])
        self.assertIn("nothing to do", self.init()[1])
        self.assert_clean()

        self.agents.write_text("# Mine\n" + doc)
        self.assertIsNone(mpa.find_block(self.agents.read_text()))
        code, text = self.init("--skills=none")
        self.assertEqual(code, 0, text)
        self.assertTrue(self.agents.read_text().endswith(doc))
        self.assert_clean()

    def test_markers_only_inside_code_fences_are_named_as_a_possibly_hidden_block(self):
        text, start, _ = self.block()
        self.agents.write_text(text[:start] + "```\n" + text[start:] + "\n## Commands\n\n```\nnpm test\n```\n")
        message = "block marker lines appear only inside code fences, and a fence may be hiding the block"
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn(message, report)
        self.assertNotIn("run init", report)
        self.assertIn(message, self.assert_refused("update"))
        self.assertIn(f"note     AGENTS.md: {message}. Review it before adding a block.\n", self.init()[1])
        self.agents.write_text(text)
        self.assertNotIn(message, self.init()[1])

    def test_a_fence_opened_inside_the_block_does_not_hide_the_end_marker(self):
        text, _, end = self.block()
        cut = end - len(mpa.END)
        self.agents.write_text(text[:cut] + "```\n" + text[cut:])
        self.assertIn("managed block differs", self.check()[1])
        self.assertEqual(run("update", self.dir, "--write", "--force")[0], 0)
        self.assert_clean()

    def test_a_marker_inside_an_unclosed_fence_is_refused(self):
        text, start, _ = self.block()
        self.agents.write_text(text[:start] + "```text\nsample\n\n" + text[start:])
        message = "a block marker is inside an unclosed code fence"
        self.assertIn(message, self.assert_refused("update"))
        self.assertIn(message, self.assert_refused("init"))
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn(message, report)
        self.assertEqual(self.agents.read_text().count("mpa:begin"), 1)

    def test_line_feeds_and_carriage_returns_end_lines_when_finding_the_block_and_headings(self):
        block = mpa.block_text()
        text = "# T\n\nSee page 2\x0c```\n" + block + "\n\nEnd\x0c```\n"
        start = text.index(block)
        self.assertEqual(mpa.find_block(text), (start, start + len(block), mpa.VERSION))
        self.agents.write_text(text)
        self.assertIn("up to date", run("update", self.dir)[1])
        self.assertIn("nothing to do", self.init()[1])
        self.assertEqual(self.agents.read_text().count("mpa:begin"), 1)
        self.assertNotIn("no managed block", self.check()[1])
        for sep in ("\x0b", "\x1c", "\x85", "\u2028", "\u2029"):
            sample = f"# T\nNote{sep}```\n## Approvals\n```\n## Deploy\n"
            self.assertEqual(mpa.titles(sample), {"Approvals"}, repr(sep))
        self.agents.write_text("# T\x0cpage\n\n" + block + "\n")
        self.assert_clean()
        for nl in ("\r", "\r\n"):
            text = f"# T{nl}{nl}" + block.replace("\n", nl) + nl
            start = text.index("<!--")
            self.assertEqual(mpa.find_block(text), (start, start + len(block.replace("\n", nl)), mpa.VERSION))
            self.assertEqual(mpa.titles(f"# T{nl}## Approvals{nl}```{nl}## Deploy{nl}```{nl}"), {"Approvals"})
        self.assertEqual(mpa.lines("a\rb\r\nc\nd\x0ce\u2028f"), ["a\r", "b\r\n", "c\n", "d\x0ce\u2028f"])
        self.agents.write_text("# T\rExtra rules before the block\r\n\n" + block + "\n", newline="")
        self.assertIn("error    AGENTS.md: text other than one H1 line precedes the managed block", self.check()[1])


    def test_a_closed_fence_with_a_marker_does_not_mark_a_later_unclosed_fence(self):
        sample = f"\n## Markers\n\n```md\n{mpa.END}\n```\n\n```text\nunclosed sample\n"
        self.agents.write_text(self.agents.read_text() + sample)
        self.assertIsNotNone(mpa.find_block(self.agents.read_text()))
        self.assertIn("up to date", run("update", self.dir)[1])
        self.assert_clean()

    def test_block_that_holds_other_headings_needs_force(self):
        text, _, end = self.block()
        moved = text[:end - len(mpa.END)] + text[end:] + "\n## Deploy\n\nMine.\n" + mpa.END + "\n"
        self.agents.write_text(moved)
        code, text = run("update", self.dir, "--write")
        self.assertEqual(code, 1)
        self.assertIn("Deploy", text)
        self.assertEqual(self.agents.read_text(), moved)
        self.assertEqual(run("update", self.dir, "--write", "--force")[0], 0)
        self.assertNotIn("## Deploy", self.agents.read_text())

    def test_update_adds_and_removes_skills_with_spaces_commas_repeats_and_bundles(self):
        self.init("--runtime", "claude,agents")
        args = (
            "--add-skill", "python", "hugo",
            "--add-skill", "web,security",
            "--remove-skill", "mpa-release", "mpa-absent",
            "--remove-skill", "mpa-research",
            "--write", "--force",
        )
        code, text = run("update", self.dir, *args)
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"note +mpa-absent is not installed")
        files = set(tree(self.dir))
        added = ("mpa-python", "mpa-hugo", *mpa.BUNDLES["web"], *mpa.BUNDLES["security"])
        for folder in (".claude/skills", ".agents/skills"):
            for name in added:
                self.assertIn(f"{folder}/{name}/SKILL.md", files)
            for name in ("mpa-release", "mpa-research"):
                self.assertNotIn(f"{folder}/{name}/SKILL.md", files)
                self.assertFalse((self.dir / folder / name).exists())
        code, text = run("update", self.dir, "--remove-skill", "web,hugo", "--remove-skill", "security", "--write", "--force")
        self.assertEqual(code, 0, text)
        for folder in (".claude/skills", ".agents/skills"):
            for name in ("mpa-hugo", *mpa.BUNDLES["web"], *mpa.BUNDLES["security"]):
                self.assertFalse((self.dir / folder / name).exists())
        self.assertEqual(run("update", self.dir, "--add-skill", "mpa-missing")[0], 2)

    def test_update_rejects_all_none_languages_and_platforms(self):
        for option in ("--add-skill", "--remove-skill"):
            for token in ("all", "none"):
                with self.subTest(option=option, token=token):
                    code, text = run("update", self.dir, option, token)
                    self.assertEqual(code, 2, text)
                    self.assertIn("init --skills", text)
            for category in mpa.INDIVIDUAL_ONLY:
                with self.subTest(option=option, category=category):
                    code, text = run("update", self.dir, option, category)
                    self.assertEqual(code, 2, text)
                    self.assertIn("not an install bundle", text)
                    for skill in mpa.CATALOG[category]:
                        self.assertIn(skill, text)
        code, text = run("update", self.dir, "--add-skill", "missing")
        self.assertEqual(code, 2, text)
        self.assertIn("unknown skill or bundle: mpa-missing", text)

    def test_update_keeps_and_removes_unshipped_mpa_skills(self):
        own = self.put(".agents/skills/mpa-own/SKILL.md", "mine\n")
        code, text = run("update", self.dir, "--write", "--force")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"note +\.agents/skills/mpa-own/ is not a shipped skill and is kept\. check reports it"
                               r" as an error until it is removed \(--remove-skill mpa-own\) or renamed")
        self.assertEqual(own.read_text(), "mine\n")
        self.assertIn("mpa-own/ is not a shipped skill", self.check()[1])
        self.put(".agents/skills/mpa-own/extra.txt", "kept\n")
        self.assertRegex(run("update", self.dir, "--remove-skill", "own")[1], r"keep +\.agents/skills/mpa-own/")
        (own.parent / "extra.txt").unlink()
        code, text = run("update", self.dir, "--remove-skill", "own", "mpa-missing-local", "--write", "--force")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"note +mpa-missing-local is not installed")
        self.assertFalse(own.parent.exists())

    def test_empty_skill_directory_is_refilled_or_removed(self):
        self.init("--runtime", "claude,agents")
        for folder in (".claude/skills", ".agents/skills"):
            (self.dir / folder / "mpa-review/SKILL.md").unlink()
        self.assertRegex(run("update", self.dir)[1], r"create +\.agents/skills/mpa-review/SKILL.md")
        self.assertEqual(run("update", self.dir, "--remove-skill", "review", "--write")[0], 0)
        self.assertFalse((self.dir / ".claude/skills/mpa-review").exists())
        self.assertFalse((self.dir / ".agents/skills/mpa-review").exists())

    def test_add_skill_without_installed_skills_needs_runtime(self):
        shutil.rmtree(self.dir / ".agents")
        self.assertIn("--runtime", self.assert_refused("update", "--add-skill", "review"))
        self.assertEqual(run("update", self.dir, "--add-skill", "review", "--runtime", "agents", "--write")[0], 0)
        self.assertEqual([p for p in tree(self.dir) if "skills" in p], [".agents/skills/mpa-review/SKILL.md"])

    def test_update_adds_the_guides_section_for_the_generic_runtime(self):
        shutil.rmtree(self.dir / ".agents")
        args = ("update", self.dir, "--add-skill", "python", "--runtime", "generic", "--force")
        code, text = run(*args)
        self.assertEqual(code, 0)
        self.assertRegex(text, r"append +AGENTS.md  \(Guides section at the end\)")
        self.assertEqual(run(*args, "--write")[0], 0)
        self.assertTrue(self.agents.read_text().endswith(mpa.GUIDES + "\n"))
        self.assertTrue((self.dir / ".agents/skills/mpa-python/SKILL.md").exists())
        self.assertIn("up to date", run("update", self.dir, "--runtime", "generic")[1])
        self.assert_clean()

    def test_update_joins_the_guides_section_and_the_block_in_one_step(self):
        self.agents.write_text(self.agents.read_text().replace(mpa.BLOCK_VERSION, "6.9.0"))
        code, text = run("update", self.dir, "--runtime", "generic", "--write", "--force")
        self.assertEqual(code, 0)
        self.assertRegex(text, r"replace +AGENTS.md  \(managed block 6.9.0 -> .*; Guides section at the end\)")
        self.assertIn("applied: 1 change\n", text)
        self.assertIn(mpa.GUIDES, self.agents.read_text())
        self.assert_clean()

    def test_update_adds_no_guides_section_without_generic_skills(self):
        run("update", self.dir, "--add-skill", "python", "--write", "--force")
        self.assertNotIn("## Guides", self.agents.read_text())
        shutil.rmtree(self.dir / ".agents")
        self.assertIn("up to date", run("update", self.dir, "--runtime", "generic")[1])

    def test_removal_that_is_not_carried_out_exits_with_an_error(self):
        self.init("--runtime", "claude,agents")
        for folder in (".claude/skills", ".agents/skills"):
            self.put(f"{folder}/mpa-release/notes.txt", "kept\n")
        before = tree(self.dir)
        for extra in ((), ("--write", "--force")):
            with self.subTest(extra):
                code, text = run("update", self.dir, "--remove-skill", "release", *extra)
                self.assertEqual(code, 1)
                self.assertRegex(text, r"keep +\.claude/skills/mpa-release/  \(holds files other than SKILL.md\)")
                self.assertIn("not removed: .agents/skills/mpa-release/, .claude/skills/mpa-release/;", text)
                self.assertNotIn("up to date", text)
                self.assertEqual(tree(self.dir), before)
        (self.dir / ".agents/skills/mpa-release/notes.txt").unlink()
        code, text = run("update", self.dir, "--remove-skill", "release", "--write", "--force")
        self.assertEqual(code, 1)
        self.assertIn("applied: 1 change\n", text)
        self.assertIn("not removed: .claude/skills/mpa-release/;", text)
        self.assertTrue((self.dir / ".claude/skills/mpa-release/SKILL.md").exists())
        self.assertFalse((self.dir / ".agents/skills/mpa-release").exists())

    def test_forced_update_outside_git_names_no_git_command(self):
        self.put(".agents/skills/mpa-review/SKILL.md", "stale\n")
        code, text = run("update", self.dir, "--write", "--force")
        self.assertEqual(code, 0)
        self.assertIn("applied: 1 change\n", text)
        self.assertNotIn("git diff", text)

    def test_update_rejects_overlapping_add_and_remove_skills(self):
        code, text = run("update", self.dir, "--add-skill", "python", "--remove-skill", "mpa-python")
        self.assertEqual(code, 2)
        self.assertIn("same skill", text)
        code, text = run("update", self.dir, "--add-skill", "web", "--remove-skill", "seo")
        self.assertEqual(code, 2)
        self.assertIn("mpa-seo", text)

    def test_update_refuses_oversized_agents_file(self):
        self.agents.write_text(self.agents.read_text().replace(mpa.BLOCK_VERSION, "6.9.0") + "\n" + "x" * mpa.MAX_SIZE)
        self.assertIn("32 KiB", self.assert_refused("update", "--force"))

    def test_update_notes_large_agents_file_and_missing_agents_file(self):
        self.agents.write_text(self.agents.read_text().replace(mpa.BLOCK_VERSION, "6.9.0") + "\n" + "x" * (mpa.NOTE_SIZE + 100))
        code, text = run("update", self.dir)
        self.assertEqual(code, 0, text)
        self.assertIn("exceeds 16 KiB", text)
        self.agents.unlink()
        self.assertIn("AGENTS.md is missing", self.assert_refused("update", "--force"))

    def test_update_notes_an_unchanged_agents_file_above_16_kib_and_32_kib_as_init_does(self):
        base = self.agents.read_text()
        for extra, shown, hidden in ((mpa.NOTE_SIZE, "AGENTS.md exceeds 16 KiB. Antigravity truncates", "exceeds 32 KiB"),
                                     (mpa.MAX_SIZE, "AGENTS.md exceeds 32 KiB. Codex stops reading instruction files"
                                                    " at that size by default, Antigravity truncates a rule file"
                                                    " at 24,000 bytes, and check reports it as an error.",
                                      "exceeds 16 KiB")):
            with self.subTest(extra=extra):
                self.agents.write_text(base + "x" * extra + "\n")
                before = self.agents.read_bytes()
                code, text = run("update", self.dir, "--write")
                self.assertEqual(code, 0, text)
                self.assertIn(shown, text)
                self.assertNotIn(hidden, text)
                self.assertEqual(self.agents.read_bytes(), before)
                self.assertEqual([row for row in run("init", self.dir, "--skills=none")[1].splitlines()
                                  if row.startswith("note") and "KiB" in row],
                                 [row for row in text.splitlines() if row.startswith("note")])

    def test_update_handles_non_directory_mpa_entry_across_modes(self):
        self.put(".agents/skills/mpa-python", "not a dir\n")
        self.assertIn("is not a skill directory", run("update", self.dir)[1])
        self.assertIn("is not a directory", self.assert_refused("update", "--add-skill", "python", "--force"))
        self.assertIn("is not a directory", self.assert_refused("update", "--remove-skill", "python", "--force"))
        shutil.rmtree(self.dir / ".agents")
        self.put(".agents/skills/mpa-bad", "not a dir\n")
        self.assertIn("--runtime", self.assert_refused("update", "--add-skill", "review", "--force"))


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.skill = self.dir / ".agents/skills/mpa-review/SKILL.md"

    def test_update_outside_a_work_tree_needs_force(self):
        self.skill.write_text("edited\n")
        self.assertIn("git work tree", self.assert_refused("update"))

    def test_dry_run_reports_the_refusal_as_a_plan_line(self):
        self.skill.write_text("edited\n")
        code, text = run("update", self.dir)
        self.assertEqual(code, 0)
        rows = text.splitlines()
        self.assertRegex(rows[0], r"^replace +\.agents/skills/mpa-review/SKILL.md$")
        self.assertRegex(rows[1], r"^refuse +the project is not a git work tree; pass --force")
        self.assertEqual(rows[2], "dry run: nothing changed; --write refuses this plan")
        self.assertNotIn("refuse", run("update", self.dir, "--force")[1])
        self.git("init", "-q")
        self.assertRegex(run("update", self.dir)[1], r"refuse +git does not track these files")
        self.git("add", "-f", ".")
        self.git("commit", "-q", "-m", "setup")
        self.assertIn("add --write to apply", run("update", self.dir, "--add-skill", "python")[1])
        self.skill.write_text("again\n")
        self.assertRegex(run("update", self.dir)[1], r"refuse +these files have unstaged changes: \.agents/")

    def test_refused_write_prints_the_plan_before_the_refusal(self):
        self.skill.write_text("edited\n")
        text = self.assert_refused("update")
        self.assertLess(text.index("replace  .agents/skills/mpa-review/SKILL.md"), text.index("refused: the project"))
        self.assertNotIn("applied", text)

    def test_update_needs_committed_files(self):
        self.git("init", "-q")
        self.git("add", "-f", ".")
        self.git("commit", "-q", "-m", "setup")
        self.skill.write_text("again\n")
        self.assertIn("unstaged changes: .agents/skills/mpa-review/SKILL.md", self.assert_refused("update"))
        self.assertIn("applied: 1 change\nreview with: git status and git diff\n",
                      run("update", self.dir, "--write", "--force")[1])
        self.assert_clean()

    def test_conflicted_file_is_refused_as_conflicted(self):
        self.git("init", "-q", "-b", "main")
        self.git("add", "-f", ".")
        self.git("commit", "-q", "-m", "setup")
        self.git("checkout", "-q", "-b", "other")
        self.skill.write_text("other\n")
        self.git("commit", "-q", "-a", "-m", "other")
        self.git("checkout", "-q", "main")
        self.skill.write_text("mine\n")
        self.git("commit", "-q", "-a", "-m", "mine")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("merge", "-q", "other")
        text = self.assert_refused("update")
        self.assertIn("these files are conflicted in the index: .agents/skills/mpa-review/SKILL.md;", text)
        self.assertNotIn("unstaged", text)

    def test_a_single_index_entry_at_a_merge_stage_is_refused_as_conflicted(self):
        self.git("init", "-q")
        self.git("add", "-f", ".")
        self.git("commit", "-q", "-m", "setup")
        self.skill.write_text("edited\n")
        rel = ".agents/skills/mpa-review/SKILL.md"
        blob = mpa.blob_id(self.skill.read_bytes(), 40)
        self.git("hash-object", "-w", rel)
        self.git("update-index", "--force-remove", rel)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        subprocess.run(["git", "-C", str(self.dir), "update-index", "--index-info"], check=True,
                       input=f"100644 {blob} 2\t{rel}\n".encode(), capture_output=True, env=env)
        text = self.assert_refused("update")
        self.assertIn(f"these files are conflicted in the index: {rel};", text)

    def test_staged_file_is_replaced_and_stays_in_the_index(self):
        self.git("init", "-q")
        self.skill.write_text("staged\n")
        self.git("add", "-f", ".")
        code, text = run("update", self.dir, "--write")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.skill.read_bytes(), mpa.shipped("mpa-review"))
        self.git("checkout", "--", ".agents")
        self.assertEqual(self.skill.read_text(), "staged\n")

    def test_blob_id_matches_git(self):
        self.git("init", "-q")
        self.git("add", "-f", "AGENTS.md")
        listed = mpa.git(self.dir, "ls-files", "-s", "--", "AGENTS.md")
        self.assertEqual(mpa.blob_id(self.agents.read_bytes(), 40), listed.split()[1])

    def test_update_refuses_to_replace_ignored_files(self):
        self.put(".gitignore", "/.agents/\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "setup")
        self.skill.write_text("local edit\n")
        self.assertIn("does not track", self.assert_refused("update"))
        self.skill.write_bytes(mpa.shipped("mpa-review"))
        self.assertEqual(run("update", self.dir, "--add-skill", "python", "--write")[0], 0)

    def test_update_reads_no_repository_inside_a_plain_directory(self):
        marker = self.tmp / "ran"
        hook = self.tmp / "hook.sh"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        self.git("init", "-q", "--bare", "bare")
        for item in (self.dir / "bare").iterdir():
            item.rename(self.dir / item.name)
        with open(self.dir / "config", "a") as config:
            config.write(f"[core]\n\tbare = false\n\tworktree = {self.dir}\n\tfsmonitor = {hook}\n")
        self.skill.write_text("edited\n")
        self.assertIn("git work tree", run("update", self.dir, "--write")[1])
        self.check()
        self.assertFalse(marker.exists())

    def test_git_runs_no_monitor_or_hook_of_the_repository(self):
        marker = self.tmp / "ran"
        hook = self.tmp / "hook.sh"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        self.git("init", "-q")
        self.git("add", "-f", ".")
        self.git("commit", "-q", "-m", "setup")
        self.git("config", "core.fsmonitor", str(hook))
        self.assertEqual(mpa.git(self.dir, "ls-files", "-s", "--", "absent"), "")
        self.assertFalse(marker.exists())

    def test_update_and_check_run_no_clean_filter_of_the_repository(self):
        marker = self.tmp / "ran"
        self.git("init", "-q")
        self.git("add", "-f", ".")
        self.git("commit", "-q", "-m", "setup")
        self.put(".gitattributes", "* filter=x diff=x\n")
        with open(self.dir / ".git/config", "a") as config:
            config.write(f'[filter "x"]\n\tclean = "touch {marker}; cat"\n\tsmudge = "touch {marker}; cat"\n'
                         f'[diff "x"]\n\ttextconv = "touch {marker}; cat"\n\tcommand = "touch {marker}"\n'
                         f'[diff]\n\texternal = "touch {marker}"\n[core]\n\tpager = "touch {marker}"\n')
        self.skill.write_text("edited\n")
        self.assertRegex(run("update", self.dir)[1], r"refuse +these files have unstaged changes")
        self.assert_refused("update")
        self.check()
        self.skill.write_bytes(mpa.shipped("mpa-review"))
        self.agents.write_text(self.agents.read_text().replace(mpa.BLOCK_VERSION, "6.9.0"))
        self.git("-c", "filter.x.clean=", "add", "-f", ".")
        code, text = run("update", self.dir, "--write")
        self.assertEqual(code, 0, text)
        self.assertIn("review with: git status and git diff", text)
        self.assertFalse(marker.exists())
        self.git("status", "--porcelain")
        self.assertTrue(marker.exists())


class LineEndingTests(ProjectCase):
    def test_crlf_files_pass_check_and_update(self):
        self.init("--runtime", "claude,agents")
        for rel in ("AGENTS.md", "CLAUDE.md", ".agents/skills/mpa-review/SKILL.md", ".claude/skills/mpa-review/SKILL.md"):
            path = self.dir / rel
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assert_clean()
        self.assertIn("up to date", run("update", self.dir)[1])

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_autocrlf_checkout_passes_the_guard(self):
        self.init("--skills=none")
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "true")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "setup")
        data = self.agents.read_bytes().replace(b"\n", b"\r\n").replace(mpa.BLOCK_VERSION.encode(), b"6.9.0")
        self.agents.write_bytes(data)
        self.git("add", ".")
        code, text = run("update", self.dir, "--write")
        self.assertEqual(code, 0, text)
        self.assertIn(b"\r\n", self.agents.read_bytes())

    def test_insert_top_cuts_after_the_first_line_and_keeps_its_line_ending(self):
        for nl in ("\n", "\r\n", "\r"):
            self.assertEqual(mpa.insert_top(f"# T{nl}Body{nl}", "A\nB"),
                             (f"# T{nl}{nl}A{nl}B{nl}{nl}Body{nl}", "after line 1"))
            self.assertEqual(mpa.insert_top(f"Body{nl}", "A"), (f"A{nl}{nl}Body{nl}", "at the top"))
        self.assertEqual(mpa.insert_top("# T", "A"), ("# T\n\nA\n", "after line 1"))

    def test_text_added_after_a_lone_carriage_return_keeps_the_blank_line_and_line_feed_endings(self):
        top = mpa.insert_top("# T\rBody\n", "A")
        self.assertEqual(top, ("# T\r\rA\n\nBody\n", "after line 1"))
        end = mpa.append_end("a\nb\r", "X")
        self.assertEqual(end, "a\nb\r\rX\n")
        self.assertEqual((mpa.newline(top[0]), mpa.newline(end)), ("\n", "\n"))

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_update_keeps_line_feed_block_lines_after_a_lone_carriage_return_heading(self):
        self.agents.write_bytes(b"# T\rfoo\nbar\n")
        code, text = self.init("--skills=none")
        self.assertEqual(code, 0, text)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "setup")
        self.agents.write_bytes(self.agents.read_bytes().replace(mpa.BLOCK_VERSION.encode(), b"8.0.0"))
        self.git("add", ".")
        code, text = run("update", self.dir, "--write")
        self.assertEqual(code, 0, text)
        data = self.agents.read_bytes()
        self.assertNotIn(b"\r\n", data)
        self.assertIn(f"# T\r\r{mpa.BEGIN.format(mpa.BLOCK_VERSION)}\n".encode(), data)
        self.assert_clean()

    def test_carriage_return_files_keep_their_import_and_sections(self):
        self.init()
        claude = self.put("CLAUDE.md", "# Team notes\r\r@AGENTS.md\r")
        self.assert_clean()
        self.assertIn("import present", run("init", self.dir, "--runtime", "claude", "--skills", "none")[1])
        self.assertEqual(claude.read_bytes(), b"# Team notes\r\r@AGENTS.md\r")
        claude.unlink()
        original = "# Proj\r\rIntro\r\r## Approvals\r\rAsk first: x.\r\r## Commands\r\r- Test: y\r\r## Constraints\r\r- z\r"
        self.agents.write_bytes(original.encode())
        code, text = run("init", self.dir, "--runtime", "agents", "--skills", "none", "--write")
        self.assertEqual(code, 0, text)
        self.assertNotIn("sections after the block", text)
        data = self.agents.read_bytes().decode()
        self.assertNotIn("\n", data)
        self.assertTrue(data.startswith("# Proj\r\r<!-- mpa:begin "))
        self.assertTrue(data.endswith("\r\r" + original[len("# Proj\r\r"):]))
        self.assertEqual([title for _, title in mpa.outline(data)[0]].count("Approvals"), 1)
        self.assert_clean()
        self.assertIn("up to date", run("update", self.dir)[1])


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitDiscoveryTests(ProjectCase):
    def test_git_finds_the_repository_and_respects_its_limits(self):
        quiet = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        patch = mock.patch.dict(os.environ, quiet)
        patch.start()
        self.addCleanup(patch.stop)
        self.git("init", "-q")
        sub = self.dir / "sub"
        sub.mkdir()
        self.assertEqual(mpa.git(sub, "rev-parse", "--is-inside-work-tree"), "true\n")
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.dir)}):
            self.assertIsNone(mpa.git(sub, "rev-parse", "--is-inside-work-tree"))
        with mock.patch.dict(os.environ, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}):
            self.assertIsNone(mpa.git(self.dir, "rev-parse", "--is-inside-work-tree"))
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.tmp / "elsewhere")}):
            self.assertEqual(mpa.git(sub, "rev-parse", "--is-inside-work-tree"), "true\n")


class CheckTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.init()

    def errors(self):
        code, text = self.check()
        rows = [row for row in text.splitlines() if row.startswith("error")]
        self.assertEqual(code, 1 if rows else 0)
        return "\n".join(rows)

    def test_edited_block_is_an_error(self):
        self.agents.write_text(self.agents.read_text().replace(mpa.END, "- Added rule.\n" + mpa.END))
        self.assertIn("managed block differs", self.errors())

    def test_agents_file_size_notes_and_error_name_codex_and_antigravity(self):
        base = self.agents.read_text()
        self.agents.write_text(base + "x" * mpa.NOTE_SIZE + "\n")
        self.assertIn("AGENTS.md is larger than 16 KiB; Antigravity truncates a rule file at 24,000 bytes,"
                      " and Codex stops reading at 32 KiB by default", self.check()[1])
        self.agents.write_text(base + "x" * mpa.MAX_SIZE + "\n")
        self.assertIn("AGENTS.md is larger than 32 KiB; Codex stops reading instruction files at that size by default,"
                      " and Antigravity truncates a rule file at 24,000 bytes", self.errors())

    def test_text_before_the_block_is_an_error(self):
        self.agents.write_text("Intro\n\n" + self.agents.read_text())
        self.assertIn("precedes the managed block", self.errors())

    def test_import_inside_a_fence_is_an_error(self):
        self.put("CLAUDE.md", "~~~\n@AGENTS.md\n~~~\n")
        self.assertIn("CLAUDE.md: no line", self.errors())

    def test_installed_skills_are_compared_with_the_shipped_text(self):
        self.init("--runtime", "claude,agents")
        self.put(".claude/skills/mpa-review/SKILL.md", "changed\n")
        self.put(".agents/skills/mpa-review/run.sh", "echo\n")
        found = self.errors()
        self.assertIn(".claude/skills/mpa-review/SKILL.md differs", found)
        self.assertIn(".agents/skills/mpa-review/ holds files other than SKILL.md: run.sh", found)
        self.assertEqual(len(found.splitlines()), 2)

    def test_override_file_and_instruction_excludes_are_errors(self):
        self.init("--runtime", "claude", "--skills=none")
        self.put("AGENTS.override.md", "Other rules.\n")
        self.put(".claude/settings.json", json.dumps({"claudeMdExcludes": ["**/other.md", "*/CLAUDE.md", "**/AGENTS.md"]}))
        self.put(".claude/settings.local.json", json.dumps({"claudeMdExcludes": [str(self.dir / "CLAUDE.md"), "**/*.md"]}))
        found = self.errors()
        self.assertIn("AGENTS.override.md exists", found)
        self.assertIn("settings.json: claudeMdExcludes entry **/AGENTS.md covers AGENTS.md", found)
        self.assertNotIn("*/CLAUDE.md", found)
        self.assertIn("settings.local.json: claudeMdExcludes entry **/*.md covers AGENTS.md, CLAUDE.md", found)
        self.assertEqual(len(found.splitlines()), 4)

    def test_glob_match_respects_segment_boundaries(self):
        for path, pattern, expected in (
            ("AGENTS.md", "**/AGENTS.md", True),
            ("/work/app/AGENTS.md", "**/app/AGENTS.md", True),
            ("/work/web-app/AGENTS.md", "**/app/AGENTS.md", False),
            ("AGENTS.md", "**/TS.md", False),
            ("a/fooAGENTS.md", "a/**/AGENTS.md", False),
            ("a/b/AGENTS.md", "a/**/AGENTS.md", True),
            ("a/AGENTS.md", "a/**/AGENTS.md", True),
            ("foobar", "foo**/bar", False),
            ("a", "**/", False),
            ("", "**/", False),
            ("a/", "**/", True),
        ):
            self.assertEqual(mpa.glob_match(path, pattern), expected, (path, pattern))

    def test_broken_claude_symlink_does_not_duplicate_error_or_skip_settings(self):
        (self.dir / "CLAUDE.md").symlink_to("other.md")
        self.put(".claude/settings.json", "{")
        found = self.errors()
        self.assertEqual(found.count("symbolic link"), 1)
        self.assertIn("settings.json is not a JSON object", found)

    def test_dual_claude_files_are_inspected_together(self):
        self.put("CLAUDE.md", "# Root\nNo import here.\n")
        self.put(".claude/CLAUDE.md", "@../AGENTS.md\n")
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertIn("both CLAUDE.md and .claude/CLAUDE.md exist; keep one file to avoid ambiguity", text)

        self.put(".claude/CLAUDE.md", "Still no import.\n")
        found = self.errors()
        self.assertIn("CLAUDE.md: no line that is exactly @AGENTS.md", found)
        self.assertIn(".claude/CLAUDE.md: no line that is exactly @../AGENTS.md", found)

        (self.dir / "CLAUDE.md").unlink()
        (self.dir / "CLAUDE.md").symlink_to("AGENTS.md")
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertIn("both CLAUDE.md and .claude/CLAUDE.md exist; keep one file to avoid ambiguity", text)
        self.assertTrue((self.dir / "CLAUDE.md").is_symlink())

        self.put(".claude/settings.json", json.dumps({"claudeMdExcludes": [".claude/CLAUDE.md"]}))
        self.assertIn("claudeMdExcludes entry .claude/CLAUDE.md covers .claude/CLAUDE.md", self.errors())

        shutil.rmtree(self.dir / ".claude")
        outside = self.tmp / "outside-claude"
        outside.mkdir()
        (self.dir / ".claude").symlink_to(outside)
        self.assertIn(".claude is a symbolic link", self.errors())

    def test_deeply_nested_settings_json_is_reported_without_crashing(self):
        payload = "[" * 100000
        self.assertIsNone(mpa.load_settings(payload))
        self.put(".claude/settings.json", payload)
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn(".claude/settings.json is not a JSON object", text)

    def test_non_directory_mpa_entry_and_missing_skill_file_are_reported_cleanly(self):
        self.init("--runtime", "claude,agents")
        self.put(".agents/skills/mpa-notes", "not a dir\n")
        (self.dir / ".agents/skills/mpa-review/SKILL.md").unlink()
        self.put(".claude/skills/mpa-review/SKILL.md", "changed\n")
        found = self.errors()
        self.assertIn(".agents/skills/mpa-notes is not a directory", found)
        self.assertIn(".agents/skills/mpa-review/SKILL.md is missing; run update", found)
        self.assertIn(".claude/skills/mpa-review/SKILL.md differs", found)
        self.assertNotIn("different mpa-* skill sets", self.check()[1])
        self.put(".agents/skills/mpa-python/SKILL.md", mpa.shipped("mpa-python").decode())
        self.assertIn("different mpa-* skill sets", self.check()[1])

    def test_agents_files_in_subdirectories_are_a_note(self):
        for rel in ("pkg/AGENTS.md", "pkg/CLAUDE.md", "node_modules/x/AGENTS.md", ".cache/AGENTS.md"):
            self.put(rel, "x\n")
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"note +AGENTS.md files in subdirectories: pkg/AGENTS.md\. A tool that reads the nearest"
                               r" file may not apply the working agreement there\.\n")
        self.assertIn("check: 0 errors, 1 note", text)

    def test_symlinked_nested_agents_file_is_skipped_safely(self):
        outside = self.tmp / "outside.md"
        outside.write_text("x" * 30000)
        (self.dir / "sub").mkdir()
        (self.dir / "sub/AGENTS.md").symlink_to(outside)
        (self.dir / "sub2").mkdir()
        (self.dir / "sub2/AGENTS.md").symlink_to("missing.md")
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertNotIn("sub/AGENTS.md", text)
        self.assertNotIn("sub2/AGENTS.md", text)
        self.assertEqual(mpa.nested_files(self.dir), ([], False))

    def test_bfs_nested_files_discovers_shallow_files_before_deep_trees(self):
        self.put("a/d1/d2/d3/d4/d5/AGENTS.md", "deep\n")
        self.put("z/AGENTS.md", "shallow\n")
        with mock.patch.object(mpa, "MAX_WALK", 4):
            found, stopped = mpa.nested_files(self.dir)
        self.assertTrue(stopped)
        self.assertEqual(found, ["z/AGENTS.md"])

    def test_missing_claude_file_is_a_note_where_claude_code_is_set_up(self):
        self.init("--runtime", "claude")
        (self.dir / "CLAUDE.md").unlink()
        self.assertRegex(self.check()[1], r"note +no CLAUDE.md imports AGENTS.md; Claude Code before 2.1.277")
        self.put("CLAUDE.local.md", "x\n")
        self.assertRegex(self.check()[1], r"note +CLAUDE.local.md exists and no CLAUDE.md imports AGENTS.md")
        (self.dir / "CLAUDE.local.md").unlink()
        shutil.rmtree(self.dir / ".claude")
        self.assertNotIn("imports AGENTS.md", self.check()[1])

    def test_scan_for_nested_files_reports_its_limit(self):
        for name in ("a", "b", "c"):
            self.put(f"{name}/AGENTS.md", "x\n")
        self.assertNotIn("stopped", self.check()[1])
        with mock.patch.object(mpa, "MAX_WALK", 2):
            text = self.check()[1]
        self.assertIn("AGENTS.md files in subdirectories: a/AGENTS.md. A tool that reads", text)
        self.assertRegex(text, r"note +the scan for instruction files in subdirectories stopped after 2 directories")

    def test_check_runs_no_git_commands(self):
        if shutil.which("git"):
            self.git("init", "-q")
            self.git("add", ".")
            self.git("commit", "-q", "-m", "setup")
        with mock.patch.object(mpa, "git", side_effect=AssertionError("check must not run git")):
            self.assert_clean()


class ShippedContentTests(unittest.TestCase):
    def test_a_tool_release_alone_leaves_the_block_current(self):
        source = (ROOT / "mpa.py").read_text(encoding="utf-8")
        line = f'__version__ = "{mpa.__version__}"\n'
        self.assertEqual(source.count(line), 1)
        release = types.ModuleType("mpa_release")
        release.__file__ = str(ROOT / "mpa.py")
        exec(compile(source.replace(line, '__version__ = "99.0.0"\n'), release.__file__, "exec"), release.__dict__)
        self.assertEqual((release.__version__, release.BLOCK_VERSION), ("99.0.0", mpa.BLOCK_VERSION))
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(run("init", empty, "--write", "--skills", "review")[0], 0)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                checked = release.main(["check", empty])
                updated = release.main(["update", empty])
            self.assertEqual((checked, updated), (0, 0), out.getvalue())
            self.assertIn("check: 0 errors", out.getvalue())
            self.assertIn("up to date", out.getvalue())

    def test_readme_shows_the_block(self):
        self.assertIn(mpa.template("block.md").strip(), (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_repository_passes_its_own_check(self):
        code, text = run("check", ROOT)
        self.assertEqual(code, 0, text)

    def test_skills_match_the_catalogue(self):
        names = sorted(name for items in mpa.CATALOG.values() for name in items)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sorted(p.name for p in mpa.SKILLS.iterdir() if p.is_dir()), names)
        catalogue = (ROOT / "skills/README.md").read_text(encoding="utf-8")
        listed = re.findall(r"^\| `(mpa-[^`]+)` \| (\w+) \| (bundle|individual) \|", catalogue, re.M)
        expected = [
            (name, cat, "individual" if cat in mpa.INDIVIDUAL_ONLY else "bundle")
            for cat, items in mpa.CATALOG.items()
            for name in items
        ]
        self.assertEqual(listed, expected)
        for name in names:
            with self.subTest(name):
                self.assertEqual([p.name for p in (mpa.SKILLS / name).iterdir()], ["SKILL.md"])
                data = mpa.shipped(name)
                match = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", data.decode("utf-8"))
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), name)
                raw_desc = match.group(2)
                self.assertRegex(raw_desc, r'^"(?:[^"\\]|\\.)*"$')
                description = json.loads(raw_desc)
                self.assertNotIn("<", description)
                self.assertNotIn(">", description)

    def test_stack_skills_open_with_a_coverage_line_no_later_than_the_newest_release(self):
        pattern = re.compile(r"^Current to .+, checked (\d{4}-\d{2}-\d{2})\. For a newer .+, read what changed after .+"
                             r" in the release notes \(https:/{2}\S+(, https:/{2}\S+)*\) before relying on this file;"
                             r" up to .+ no lookup is needed\.$")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        newest = max(re.findall(r"^## \d+\.\d+\.\d+ - (\d{4}-\d{2}-\d{2})$", changelog, re.M))
        names = sorted(name for items in mpa.CATALOG.values() for name in items)
        self.assertLessEqual(set(hygiene.SKILL_SOURCES), set(names))
        for name in names:
            with self.subTest(name):
                text = mpa.shipped(name).decode("utf-8")
                body = text.split("\n---\n", 1)[1]
                lines = [row for row in body.splitlines() if row.startswith("Current to")]
                if name not in hygiene.SKILL_SOURCES:
                    self.assertEqual(lines, [])
                    continue
                self.assertEqual(len(lines), 1)
                match = pattern.match(lines[0])
                self.assertIsNotNone(match, lines[0])
                self.assertLessEqual(match[1], newest)
                first = next(row for row in body.splitlines() if row.strip() and not row.startswith("#"))
                self.assertEqual(first, lines[0])
                description = json.loads(re.search(r"^description: (.+)$", text, re.M)[1])
                # A version that the description names is covered by the line, at the same or a finer level.
                claim = re.search(r"(?:through|current to) (.+?)(?: and checks|\. Use)", description)
                covered = lines[0].split(", checked ")[0]
                for version in re.findall(r"\bv?\d+(?:\.\d+)*\b", claim[1] if claim else ""):
                    self.assertRegex(covered, rf"(?<![\w.]){re.escape(version)}(?!\w)")

    def test_skill_cross_references_resolve(self):
        known = {name for items in mpa.CATALOG.values() for name in items}
        pattern = re.compile(rf"\b{mpa.NAME_RE.pattern}\b")
        matched = 0
        for name in sorted(known):
            text = mpa.shipped(name).decode("utf-8")
            for hit in pattern.finditer(text):
                ref = hit.group(0)
                matched += 1
                self.assertIn(ref, known, f"{name} references unknown skill {ref}")
        self.assertGreater(matched, len(known))

    def test_skills_in_both_folders_are_a_note_and_differing_sets_another(self):
        with tempfile.TemporaryDirectory() as holder:
            project = Path(holder).resolve() / "project"
            project.mkdir()
            code, text = run("init", project, "--write", "--runtime", "claude,agents", "--skills", "all")
            self.assertEqual(code, 0, text)
            errors, notes = [], []
            mpa.check_skills(project, errors, notes)
            self.assertEqual(errors, [])
            joined = "\n".join(notes)
            self.assertIn("both .claude/skills and .agents/skills hold mpa-* skills", joined)
            self.assertNotIn("different mpa-* skill sets", joined)

            shutil.rmtree(project / ".claude/skills/mpa-hugo")
            errors, notes = [], []
            mpa.check_skills(project, errors, notes)
            self.assertEqual(errors, [])
            self.assertIn(".claude/skills and .agents/skills hold different mpa-* skill sets", "\n".join(notes))

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_real_skills_end_to_end_lifecycle(self):
        with tempfile.TemporaryDirectory() as holder:
            project = Path(holder).resolve() / "app"
            project.mkdir()
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
            git_base = ["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@example.com"]

            def run_git(*args):
                subprocess.run([*git_base, *args], check=True, capture_output=True, env=env)

            code, text = run("init", project, "--write")
            self.assertEqual(code, 0, text)
            self.assertFalse((project / "CLAUDE.md").exists())
            self.assertEqual(mpa.installed(project, ".agents/skills"), sorted(mpa.CATALOG["core"]))

            code, text = run("check", project)
            self.assertEqual(code, 0, text)
            self.assertIn("check: 0 errors, 0 notes", text)

            run_git("init", "-q")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "initial mpa setup")

            code, text = run("update", project, "--add-skill", "web,hugo,wordpress", "--write")
            self.assertEqual(code, 0, text)
            expected_after_add = sorted({*mpa.CATALOG["core"], *mpa.CATALOG["web"], "mpa-hugo", "mpa-wordpress"})
            self.assertEqual(mpa.installed(project, ".agents/skills"), expected_after_add)
            for name in ("mpa-web-frontend", "mpa-seo", "mpa-hugo", "mpa-wordpress"):
                self.assertEqual((project / ".agents/skills" / name / "SKILL.md").read_bytes(), mpa.shipped(name))

            code, text = run("check", project)
            self.assertEqual(code, 0, text)
            self.assertIn("check: 0 errors, 0 notes", text)

            run_git("add", ".")
            run_git("commit", "-q", "-m", "add web, hugo, wordpress skills")

            code, text = run("update", project, "--remove-skill", "hugo", "--write")
            self.assertEqual(code, 0, text)
            self.assertFalse((project / ".agents/skills/mpa-hugo").exists())
            expected_after_remove = [name for name in expected_after_add if name != "mpa-hugo"]
            self.assertEqual(mpa.installed(project, ".agents/skills"), expected_after_remove)

            code, text = run("check", project)
            self.assertEqual(code, 0, text)
            self.assertIn("check: 0 errors, 0 notes", text)


class ListingBudgetTests(ProjectCase):
    def test_a_listing_of_names_and_descriptions_above_8000_characters_is_a_note(self):
        names = sorted(mpa.CATALOG["core"])

        def fixture(name, length):
            (self.skills / name / "SKILL.md").write_text(
                f'---\nname: {name}\ndescription: "{"d" * length}"\n---\nBody.\n', encoding="utf-8")

        for name in names:
            fixture(name, 100)
        rest = sum(len(name) + 100 for name in names[1:]) + len(names[0])
        fixture(names[0], 8000 - rest)
        self.assertEqual(self.init()[0], 0)
        self.assertNotIn("startup skill listings", self.check()[1])
        fixture(names[0], 8001 - rest)
        self.assertEqual(run("update", self.dir, "--write", "--force")[0], 0)
        self.assertIn(".agents/skills: mpa-* startup skill listings total 8,001 characters, exceeding 8,000",
                      self.check()[1])
