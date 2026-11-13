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
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mpa

PRESET = mpa.TEMPLATES / "presets/claude-settings.json"
# Largest size in bytes of the files that load into every session, and of the skills.
CAPS = {"templates/block.md": 1400, "templates/AGENTS.template.md": 1700}
SKILL_CAP, SKILLS_CAP = 5000, 85000
BOM = "﻿"


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
        skills = self.tmp / "skills"
        for name in (*mpa.GROUPS["core"], "mpa-python"):
            (skills / name).mkdir(parents=True)
            (skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Fixture.\n---\nBody.\n")
        patch = mock.patch.object(mpa, "SKILLS", skills)
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, rel, data):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode())
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
        code, text = run("init", self.dir, "--preset")
        self.assertEqual(code, 0)
        self.assertIn("create   AGENTS.md", text)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_init_creates_expected_files(self):
        self.assertEqual(self.init("--preset")[0], 0)
        expected = {"AGENTS.md", "CLAUDE.md", "TODO.md", ".gitignore", ".claude/settings.json",
                    ".codex/config.toml", ".codex/rules/mpa.rules"}
        expected |= {f"{d}/skills/{n}/SKILL.md" for d in (".claude", ".agents") for n in mpa.GROUPS["core"]}
        files = tree(self.dir)
        self.assertEqual(set(files), expected)
        lines = files["AGENTS.md"].decode().split("\n")
        self.assertEqual(lines[0], "# project")
        self.assertTrue(lines[2].startswith(f"<!-- mpa:begin {mpa.__version__} "))
        self.assertEqual(files["CLAUDE.md"], b"@AGENTS.md\n")
        self.assertIn("check: 0 errors", self.check()[1])

    def test_second_init_changes_nothing(self):
        self.init()
        before = tree(self.dir)
        code, text = self.init()
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", text)
        self.assertEqual(tree(self.dir), before)

    def test_init_adds_presets_to_a_project_that_is_set_up(self):
        self.init("--runtime", "claude")
        before = tree(self.dir)
        self.assertEqual(self.init("--runtime", "claude", "--preset")[0], 0)
        after = tree(self.dir)
        self.assertEqual(set(after) - set(before), {".claude/settings.json"})
        self.assertEqual(after["AGENTS.md"], before["AGENTS.md"])

    def test_failed_write_leaves_agents_file_for_the_next_run(self):
        real = mpa.write

        def failing(root, rel, data):
            if rel == "TODO.md":
                raise OSError(28, "No space left on device")
            real(root, rel, data)

        with mock.patch.object(mpa, "write", failing):
            code, text = self.init()
        self.assertEqual(code, 1)
        self.assertIn("completed: CLAUDE.md", text)
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.init()[0], 0)
        self.assert_clean()

    def test_failed_create_leaves_no_partial_file(self):
        with mock.patch.object(mpa.os, "fsync", side_effect=OSError(5, "Input/output error")):
            self.assertEqual(self.init("--skills=none", "--runtime=codex", "--state=none")[0], 1)
        self.assertEqual(tree(self.dir), {})

    def test_6x_setup_is_refused(self):
        self.put("AGENTS.md", "<!-- mpa-entrypoint-contract: x -->\n")
        self.assertIn("migrating-from-v6", self.assert_refused())

    def test_oversized_file_is_refused(self):
        self.put("AGENTS.md", "x" * mpa.MAX_SIZE)
        self.assert_refused()

    def test_block_of_another_version_is_left_to_update(self):
        self.init()
        self.agents.write_text(self.agents.read_text().replace(mpa.__version__, "6.9.0"))
        self.assertIn("update", self.assert_refused())

    def test_unusual_directory_name_is_not_used_as_title(self):
        self.dir = self.tmp / "a <b> [c](d)"
        self.dir.mkdir()
        self.init("--skills=none")
        self.assertEqual((self.dir / "AGENTS.md").read_text().split("\n")[0], "# Project")

    def test_adoption_puts_block_after_title_and_sections_at_end(self):
        original = "# Title\n\nPreamble text.\n\n## Approvals\n\nAsk before deploys.\n\n## Style\n\nTabs."
        self.put("AGENTS.md", original)
        code, text = self.init()
        self.assertRegex(text, r"note +AGENTS.md keeps its existing ## Approvals")
        result = self.agents.read_text()
        start, end, _ = mpa.find_block(result)
        self.assertEqual(result[:start], "# Title\n\n")
        self.assertTrue(result[end:].startswith("\n\nPreamble text.\n\n## Approvals\n\nAsk before deploys.\n\n## Style\n\nTabs.\n\n"))
        heads = [title for _, title in mpa.outline(result)[0]]
        self.assertEqual(heads[-4:], ["Approvals", "Style", "Commands", "Constraints"])
        self.assert_clean()

    def test_adoption_without_title_puts_block_first(self):
        original = "Preamble.\n\n```md\n## Approvals\n```\n"
        self.put("AGENTS.md", original)
        self.init("--runtime", "generic")
        result = self.agents.read_text()
        self.assertEqual(mpa.find_block(result)[0], 0)
        self.assertIn("\n\n" + original + "\n## Commands\n", result)
        heads = [title for _, title in mpa.outline(result)[0]]
        self.assertEqual(heads[-4:], ["Commands", "Approvals", "Constraints", "Guides"])
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

    def test_import_counts_only_at_line_start_outside_fences(self):
        self.assertTrue(mpa.has_import("# T\n@AGENTS.md  \n", "@AGENTS.md"))
        for text in ("    @AGENTS.md\n", "```\n@AGENTS.md\n```\n", "<!--\n@AGENTS.md\n-->\n", "see @AGENTS.md\n"):
            self.assertFalse(mpa.has_import(text, "@AGENTS.md"), text)

    def test_claude_file_linked_to_agents_file_is_accepted(self):
        (self.dir / "CLAUDE.md").symlink_to("AGENTS.md")
        for runtime in ("codex", "claude"):
            code, text = self.init("--runtime", runtime, "--skills=none")
            self.assertEqual(code, 0, text)
        self.assertTrue((self.dir / "CLAUDE.md").is_symlink())
        self.assert_clean()

    def test_settings_merge_adds_missing_rules(self):
        preset = json.loads(PRESET.read_text())["permissions"]
        mine = ["Bash(make *)", preset["ask"][0]]
        existing = {"model": "x", "hooks": {}, "permissions": {"allow": ["Bash(ls *)"], "ask": mine}}
        self.put(".claude/settings.json", json.dumps(existing))
        text = self.init("--preset")[1]
        self.assertIn(f"+{len(preset['ask']) - 1} ask, +{len(preset['deny'])} deny", text)
        self.assertIn("ask  " + preset["ask"][1], text)
        self.assertRegex(text, r"note +\.claude/settings.json sets hooks, permissions.allow\.")
        merged = json.loads((self.dir / ".claude/settings.json").read_text())
        self.assertEqual(merged["model"], "x")
        self.assertEqual(merged["permissions"]["allow"], ["Bash(ls *)"])
        self.assertEqual(merged["permissions"]["ask"], mine + preset["ask"][1:])
        self.assertEqual(merged["permissions"]["deny"], preset["deny"])
        self.assertIn("preset rules present", self.init("--preset")[1])

    def test_settings_merge_withholds_exceptions_from_an_existing_deny_list(self):
        preset = json.loads(PRESET.read_text())["permissions"]
        exceptions = [rule for rule in preset["deny"] if "(!" in rule]
        self.assertTrue(exceptions)
        self.put(".claude/settings.json", json.dumps({"permissions": {"deny": ["Read(secrets/**)"]}}))
        text = self.init("--preset")[1]
        deny = json.loads((self.dir / ".claude/settings.json").read_text())["permissions"]["deny"]
        self.assertEqual(deny, ["Read(secrets/**)"] + [rule for rule in preset["deny"] if rule not in exceptions])
        self.assertIn("not added", text)
        self.assertIn(exceptions[0], text)

    def test_settings_merge_names_allow_rules_that_now_prompt(self):
        self.assertTrue(mpa.overlap("Bash(git push *)", "Bash(git push --force*)"))
        self.assertTrue(mpa.overlap("Bash(npm publish --dry-run)", "Bash(npm publish *)"))
        self.assertFalse(mpa.overlap("Bash(ls *)", "Bash(npm publish *)"))
        self.assertFalse(mpa.overlap("Read(.env)", "Bash(npm publish *)"))
        self.put(".claude/settings.json", json.dumps({"permissions": {"allow": ["Bash(git push *)", "Bash(ls *)"]}}))
        text = self.init("--preset")[1]
        self.assertIn("allow rules cover: Bash(git push *)\n", text)

    def test_unparseable_settings_are_kept(self):
        self.put(".claude/settings.json", "[" * 100000)
        self.put(".codex/config.toml", "model = 'x'\n")
        code, text = self.init("--preset")
        self.assertEqual(code, 0)
        self.assertRegex(text, r"keep +\.claude/settings.json")
        self.assertRegex(text, r"keep +\.codex/config.toml")
        self.assertEqual((self.dir / ".claude/settings.json").read_bytes(), b"[" * 100000)
        self.assertEqual((self.dir / ".codex/config.toml").read_bytes(), b"model = 'x'\n")
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("settings.json is not a JSON object", text)

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

    def test_state_modes(self):
        for mode, files in (("local", {"TODO.md", ".gitignore"}), ("tracked", {"TODO.md"}), ("none", set())):
            with self.subTest(mode):
                self.init("--skills=none", "--runtime=codex", "--state", mode)
                self.assertEqual(set(tree(self.dir)) - {"AGENTS.md"}, files)
                shutil.rmtree(self.dir)
                self.dir.mkdir()

    def test_existing_notes_file_is_kept(self):
        self.put("TODO.md", "- mine\n")
        self.init()
        self.assertEqual((self.dir / "TODO.md").read_bytes(), b"- mine\n")

    def test_ignore_entry_is_added_once(self):
        first = mpa.ignore_lines(b"node_modules/")
        self.assertEqual(first, f"node_modules/\n\n{mpa.IGNORE_HEAD}\n/TODO.md\n".encode())
        self.assertIsNone(mpa.ignore_lines(first))
        self.assertIsNone(mpa.ignore_lines(b"a\r\nTODO.md\r\n"))

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
        self.assertIn(mpa.END + "\n\n" + mpa.GUIDES + "\n\n## Project", result)
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
        skill = self.put(".claude/skills/mpa-review/SKILL.md", "stale\n")
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
            "newer version": text.replace(mpa.__version__, "99.0.0"),
            "long version": text.replace(mpa.__version__, "7.0.00000"),
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
        self.agents.write_text(self.agents.read_text().replace(mpa.__version__, "6.9.0"))
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("run update", text)

    def test_marker_text_inside_a_line_is_not_a_marker(self):
        self.agents.write_text(self.agents.read_text() + "\nThe mpa:begin and `<!-- mpa:end -->` lines mark the block.\n")
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

    def test_update_adds_and_removes_skills(self):
        args = ("--add-skill", "python", "--remove-skill", "mpa-release", "mpa-absent", "--write", "--force")
        code, text = run("update", self.dir, *args)
        self.assertEqual(code, 0)
        self.assertRegex(text, r"note +mpa-absent is not installed")
        files = set(tree(self.dir))
        for folder in (".claude/skills", ".agents/skills"):
            self.assertIn(f"{folder}/mpa-python/SKILL.md", files)
            self.assertNotIn(f"{folder}/mpa-release/SKILL.md", files)
            self.assertFalse((self.dir / folder / "mpa-release").exists())
        self.assertEqual(run("update", self.dir, "--add-skill", "mpa-missing")[0], 2)

    def test_update_keeps_skills_it_does_not_ship(self):
        own = self.put(".claude/skills/mpa-own/SKILL.md", "mine\n")
        code, text = run("update", self.dir, "--write", "--force")
        self.assertRegex(text, r"note +\.claude/skills/mpa-own/ is not a shipped skill and is kept\. check reports it"
                               r" as an error until it is removed \(--remove-skill mpa-own\) or renamed")
        self.assertEqual(own.read_text(), "mine\n")
        self.assertIn("mpa-own/ is not a shipped skill", self.check()[1])
        self.put(".claude/skills/mpa-own/extra.txt", "kept\n")
        self.assertRegex(run("update", self.dir, "--remove-skill", "own")[1], r"keep +\.claude/skills/mpa-own/")
        (own.parent / "extra.txt").unlink()
        run("update", self.dir, "--remove-skill", "own", "--write", "--force")
        self.assertFalse(own.parent.exists())

    def test_empty_skill_directory_is_refilled_or_removed(self):
        for folder in (".claude/skills", ".agents/skills"):
            (self.dir / folder / "mpa-review/SKILL.md").unlink()
        self.assertRegex(run("update", self.dir)[1], r"create +\.agents/skills/mpa-review/SKILL.md")
        self.assertEqual(run("update", self.dir, "--remove-skill", "review", "--write")[0], 0)
        self.assertFalse((self.dir / ".claude/skills/mpa-review").exists())

    def test_add_skill_without_installed_skills_needs_runtime(self):
        shutil.rmtree(self.dir / ".claude")
        shutil.rmtree(self.dir / ".agents")
        self.assertIn("--runtime", self.assert_refused("update", "--add-skill", "review"))
        self.assertEqual(run("update", self.dir, "--add-skill", "review", "--runtime", "codex", "--write")[0], 0)
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
        self.agents.write_text(self.agents.read_text().replace(mpa.__version__, "6.9.0"))
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

    def test_group_name_is_refused_with_a_pointer_to_init(self):
        for option, item in (("--add-skill", "core"), ("--remove-skill", "languages"), ("--add-skill", "all")):
            with self.subTest(option=option, item=item):
                code, text = run("update", self.dir, option, item)
                self.assertEqual(code, 2)
                self.assertIn(f"{option} takes skill names, and {item} is a group", text)
                self.assertIn("init --skills", text)
        code, text = run("update", self.dir, "--add-skill", "missing")
        self.assertEqual(code, 2)
        self.assertIn("unknown skill: mpa-missing", text)
        self.assertNotIn("group", text)

    def test_removal_that_is_not_carried_out_exits_with_an_error(self):
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
        self.put(".claude/skills/mpa-review/SKILL.md", "stale\n")
        code, text = run("update", self.dir, "--write", "--force")
        self.assertEqual(code, 0)
        self.assertIn("applied: 1 change\n", text)
        self.assertNotIn("git diff", text)

    def test_retired_skill_is_removed(self):
        self.put(".agents/skills/mpa-old/SKILL.md", "old\n")
        with mock.patch.object(mpa, "RETIRED", ("mpa-old",)):
            self.assertEqual(run("update", self.dir, "--write", "--force")[0], 0)
        self.assertFalse((self.dir / ".agents/skills/mpa-old").exists())


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
        self.assertIn("TODO.md is tracked", self.check()[1])

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
        self.put(".gitignore", "/TODO.md\n/.agents/\n")
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
        self.assertIn("TODO.md is tracked", self.check()[1])
        self.skill.write_bytes(mpa.shipped("mpa-review"))
        self.agents.write_text(self.agents.read_text().replace(mpa.__version__, "6.9.0"))
        self.git("-c", "filter.x.clean=", "add", "-f", ".")
        code, text = run("update", self.dir, "--write")
        self.assertEqual(code, 0, text)
        self.assertIn("review with: git status and git diff", text)
        self.assertFalse(marker.exists())
        self.git("status", "--porcelain")
        self.assertTrue(marker.exists())


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

    def test_text_before_the_block_is_an_error(self):
        self.agents.write_text("Intro\n\n" + self.agents.read_text())
        self.assertIn("precedes the managed block", self.errors())

    def test_import_inside_a_fence_is_an_error(self):
        self.put("CLAUDE.md", "~~~\n@AGENTS.md\n~~~\n")
        self.assertIn("CLAUDE.md: no line", self.errors())

    def test_installed_skills_are_compared_with_the_shipped_text(self):
        self.put(".claude/skills/mpa-review/SKILL.md", "changed\n")
        self.put(".agents/skills/mpa-review/run.sh", "echo\n")
        found = self.errors()
        self.assertIn(".claude/skills/mpa-review/SKILL.md differs", found)
        self.assertIn(".agents/skills/mpa-review/ holds files other than SKILL.md: run.sh", found)
        self.assertEqual(len(found.splitlines()), 2)

    def test_override_file_and_instruction_excludes_are_errors(self):
        self.put("AGENTS.override.md", "Other rules.\n")
        self.put(".claude/settings.json", json.dumps({"claudeMdExcludes": ["**/other.md", "**/AGENTS.md"]}))
        self.put(".claude/settings.local.json", json.dumps({"claudeMdExcludes": [str(self.dir / "CLAUDE.md")]}))
        found = self.errors()
        self.assertIn("AGENTS.override.md exists", found)
        self.assertIn("settings.json: claudeMdExcludes entry **/AGENTS.md covers AGENTS.md", found)
        self.assertIn("settings.local.json: claudeMdExcludes entry", found)
        self.assertEqual(len(found.splitlines()), 3)

    def test_other_instruction_files_are_notes(self):
        for rel in ("CLAUDE.local.md", ".claude/rules/a.md", "pkg/AGENTS.md", "node_modules/x/AGENTS.md"):
            self.put(rel, "x\n")
        self.put(".codex/config.toml", "model = 'x'\n")
        code, text = self.check()
        self.assertEqual(code, 0, text)
        for part in ("CLAUDE.local.md", ".claude/rules", ".codex/config.toml", "well: pkg/AGENTS.md\n"):
            self.assertIn(part, text)

    def test_guides_note_needs_skills_that_only_the_generic_directory_holds(self):
        self.assertNotIn("Guides", self.check()[1])
        shutil.rmtree(self.dir / ".claude/skills")
        self.assertRegex(self.check()[1], r"note +AGENTS.md has no ## Guides heading")
        self.init("--runtime", "generic")
        self.assertNotIn("Guides", self.check()[1])

    def test_unedited_placeholder_comments_are_counted(self):
        self.assertRegex(self.check()[1], r"note +AGENTS.md: 3 placeholder comments from the template are unedited")
        rows = [row for row in self.agents.read_text().split("\n") if not row.startswith("<!-- ") or "mpa:" in row]
        self.agents.write_text("\n".join(rows))
        self.assertNotIn("placeholder", self.check()[1])
        self.assert_clean()

    def test_scan_for_nested_files_reports_its_limit(self):
        for name in ("a", "b", "c"):
            self.put(f"{name}/AGENTS.md", "x\n")
        self.assertNotIn("stopped", self.check()[1])
        with mock.patch.object(mpa, "MAX_WALK", 2):
            text = self.check()[1]
        self.assertIn("well: a/AGENTS.md\n", text)
        self.assertRegex(text, r"note +the scan for instruction files in subdirectories stopped after 2 directories")

    def test_empty_command_lines_are_counted(self):
        base = self.agents.read_text().split("\n## Commands")[0]
        for tail, count in (("\n## Commands", 0), ("\n## Commands\n- Test:\n- Run: make\n- Build:", 2),
                            ("\n### Commands\n- Test:\n", 0), ("\n```\n## Commands\n- Test:\n```\n", 0)):
            with self.subTest(tail):
                self.agents.write_text(base + tail)
                code, text = self.check()
                self.assertEqual(code, 0, text)
                self.assertEqual(f"{count} command lines" in text, count > 0)
        self.agents.write_text(base + "\n## Commands\n- Test:\n")
        text = self.check()[1]
        self.assertIn("1 command line under ## Commands is empty", text)
        self.assertRegex(text, r"check: 0 errors, \d+ notes?\n")

    def test_summary_counts_agree_in_number(self):
        self.put("AGENTS.override.md", "Other rules.\n")
        self.agents.write_text(self.agents.read_text().split("\n## Project")[0] + "\n## Approvals\n")
        self.assertIn("check: 1 error, 0 notes\n", self.check()[1])
        self.put(".claude/rules/a.md", "x\n")
        self.assertIn("check: 1 error, 1 note\n", self.check()[1])
        self.put("CLAUDE.local.md", "x\n")
        self.assertIn("check: 1 error, 2 notes\n", self.check()[1])


class ShippedContentTests(unittest.TestCase):
    def test_always_loaded_files_stay_within_caps(self):
        for rel, cap in CAPS.items():
            with self.subTest(rel):
                self.assertLessEqual((ROOT / rel).stat().st_size, cap)

    def test_block_is_a_short_list_without_capitalised_lines(self):
        body = mpa.template("block.md").splitlines()
        self.assertLessEqual(len([row for row in body if row.startswith("- ")]), 4)
        self.assertFalse([row for row in body if row.isupper()])

    def test_readme_shows_the_block(self):
        self.assertIn(mpa.template("block.md").strip(), (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_skeleton_has_the_placeholders_and_adopted_sections(self):
        skeleton = mpa.template("AGENTS.template.md")
        self.assertTrue(skeleton.startswith("# {name}\n\n{block}\n"))
        for title in mpa.ADOPTED:
            self.assertTrue(mpa.section(skeleton, title), title)

    def test_repository_passes_its_own_check(self):
        code, text = run("check", ROOT)
        self.assertEqual(code, 0, text)

    def test_skills_match_the_catalogue(self):
        names = sorted(name for group in mpa.GROUPS.values() for name in group)
        self.assertEqual(sorted(p.name for p in mpa.SKILLS.iterdir() if p.is_dir()), names)
        total = 0
        for name in names:
            with self.subTest(name):
                self.assertEqual([p.name for p in (mpa.SKILLS / name).iterdir()], ["SKILL.md"])
                data = (mpa.SKILLS / name / "SKILL.md").read_bytes()
                total += len(data)
                self.assertLessEqual(len(data), SKILL_CAP)
                match = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", data.decode())
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), name)
                self.assertLessEqual(len(match.group(2).strip("\"'")), 300)
        self.assertLessEqual(total, SKILLS_CAP)

    def test_claude_preset_holds_permission_rules(self):
        rules = json.loads(PRESET.read_text())["permissions"]
        for rule in rules["ask"] + rules["deny"]:
            self.assertRegex(rule, r"^(Bash|Read)\(.+\)$")
        self.assertLess(rules["deny"].index("Read(.env.*)"), rules["deny"].index("Read(!.env.example)"))

    def test_presets_cover_the_same_commands_and_no_install_form(self):
        ask = json.loads(PRESET.read_text())["permissions"]["ask"]
        rules = PRESET.with_name("codex.rules").read_text()
        patterns = "\n".join(re.findall(r"^\s*pattern = (.+),$", rules, re.M))
        self.assertEqual(rules.count("prefix_rule("), len(patterns.splitlines()))
        for rule in ask:
            words = rule[5:-1].split()
            with self.subTest(rule):
                self.assertNotIn(words[1], ("install", "i", "ci", "sync"))
                self.assertIn(f'"{words[0]}"', patterns)
                self.assertIn(f'"{words[1]}"', patterns)
        for command in ("pnpm add", "uv add", "cargo add", "npm uninstall", "pnpm remove", "uv remove",
                        "npm publish", "twine upload", "docker push", "gh pr merge", "gh release create"):
            self.assertIn(f"Bash({command} *)", ask)
        self.assertNotIn('"install"', patterns)

    def test_codex_config_parses(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11")
        config = tomllib.loads(PRESET.with_name("codex-config.toml").read_text())
        self.assertIn("shell_environment_policy", config)

    def test_changelog_names_the_version_and_a_date(self):
        headings = re.findall(r"^## (.+)$", (ROOT / "CHANGELOG.md").read_text(), re.M)
        self.assertRegex(headings[0], rf"^{re.escape(mpa.__version__)} - \d{{4}}-\d{{2}}-\d{{2}}$")

    def test_readme_shows_the_plan_of_the_sample_command(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        options = re.search(r"For `(--runtime [^`]+)` in an empty directory the plan is:\n\n```text\n", readme)
        self.assertIsNotNone(options)
        shown = readme[options.end():].split("```")[0]
        with tempfile.TemporaryDirectory() as empty:
            code, text = run("init", empty, *options.group(1).split())
            self.assertEqual(os.listdir(empty), [])
        self.assertEqual(code, 0)
        self.assertEqual(text, shown)
