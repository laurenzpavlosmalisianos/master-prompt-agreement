"""Tests for the shipped texts: the block, the templates, and the skills."""

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Largest size in bytes of the always-loaded templates and of a skill file, and in characters of a description.
CAPS = {"templates/block.md": 1170, "templates/AGENTS.template.md": 1700}
DESCRIPTION_CAP = 320
SKILL_CAP = 7000
# The stack skills outside the languages and platforms groups of the catalogue.
STACK = ("mpa-kubernetes", "mpa-infrastructure-as-code", "mpa-agent-inputs")
FRONTMATTER = re.compile(r"---\nname: (.+)\ndescription: (.+)\n---\n")
COVERAGE = re.compile(r"Current to .+, checked (\d{4}-\d{2}-\d{2})\. The entries are the changes that are easy to miss,"
                      r" not the full release notes: for a change they do not mention, and for anything newer than .+,"
                      r" read the release notes \(https:/{2}\S+(?:, https:/{2}\S+)*\) before relying on this file\.")
# A link with a scheme, or a link without one that starts with the usual host prefix.
LINK = re.compile(r"(?:https?|ftp):/{2}\S|(?<![\w.@/:-])www\.[\w-]+\.\S", re.I)
NAME = re.compile(r"\bmpa-[a-z0-9]+(?:-[a-z0-9]+)*\b")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def skills():
    """Return {name: text of its SKILL.md} for every skill directory."""
    names = sorted(path.name for path in (ROOT / "skills").iterdir() if path.is_dir())
    return {name: read(f"skills/{name}/SKILL.md") for name in names}


def catalogue():
    """Return the (name, group) rows of the table in skills/README.md."""
    return re.findall(r"^\| `(mpa-[^`]+)` \| (\w+) \|", read("skills/README.md"), re.M)


def stack_skills():
    return {name for name, group in catalogue() if group in ("languages", "platforms")} | set(STACK)


def repository_files():
    """Return the tracked and unignored files, or every file outside dot directories when git cannot list them."""
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                              capture_output=True, check=True)
        names = done.stdout.decode("utf-8", "replace").split("\0")
    except (OSError, subprocess.CalledProcessError):
        paths = (path.relative_to(ROOT) for path in ROOT.rglob("*"))
        names = [path.as_posix() for path in paths if not any(part.startswith(".") for part in path.parts)]
    return sorted(name for name in names if name and (ROOT / name).is_file())


class TextTests(unittest.TestCase):
    def test_readme_and_agents_file_hold_the_block(self):
        block = read("templates/block.md")
        for rel in ("README.md", "AGENTS.md"):
            with self.subTest(rel):
                self.assertIn(block, read(rel))

    def test_always_loaded_texts_stay_within_their_caps(self):
        for rel, cap in CAPS.items():
            with self.subTest(rel):
                self.assertLessEqual(len(read(rel).encode("utf-8")), cap)
        for name, text in skills().items():
            with self.subTest(name):
                self.assertLessEqual(len(text.encode("utf-8")), SKILL_CAP)
                self.assertLessEqual(len(json.loads(FRONTMATTER.match(text)[2])), DESCRIPTION_CAP)

    def test_each_skill_is_one_file_with_a_name_and_a_description_and_is_in_the_catalogue(self):
        texts = skills()
        self.assertEqual(sorted(name for name, _ in catalogue()), sorted(texts))
        for name, text in texts.items():
            with self.subTest(name):
                self.assertEqual([path.name for path in (ROOT / "skills" / name).iterdir()], ["SKILL.md"])
                match = FRONTMATTER.match(text)
                self.assertIsNotNone(match)
                self.assertEqual(match[1], name)
                self.assertRegex(match[2], r'^"(?:[^"\\]|\\.)*"$')
                self.assertNotRegex(json.loads(match[2]), "[<>]")

    def test_stack_skills_open_with_a_coverage_line_and_links_sit_only_where_allowed(self):
        newest = max(re.findall(r"^## \d+\.\d+\.\d+ - (\d{4}-\d{2}-\d{2})$", read("CHANGELOG.md"), re.M))
        stack = stack_skills()
        for name, text in skills().items():
            with self.subTest(name):
                body = text.split("\n---\n", 1)[1]
                lines = [row for row in body.splitlines() if row.startswith("Current to")]
                if name not in stack:
                    self.assertEqual(lines, [])
                    continue
                self.assertEqual(len(lines), 1)
                match = COVERAGE.fullmatch(lines[0])
                self.assertIsNotNone(match, lines[0])
                self.assertLessEqual(match[1], newest)
                first = next(row for row in body.splitlines() if row.strip() and not row.startswith("#"))
                self.assertEqual(first, lines[0])
                description = json.loads(FRONTMATTER.match(text)[2])
                # A version that the description names is covered by the line, at the same or a finer level.
                claim = re.search(r"(?:through|current to) (.+?)(?: and (?:easy-to-miss )?checks|\. Use)", description)
                self.assertIsNotNone(claim, description)
                covered = lines[0].split(", checked ")[0]
                versions = re.findall(r"\bv?\d+(?:[.-]\d+)*\b", claim[1])
                self.assertTrue(versions, claim[1])
                for version in versions:
                    self.assertRegex(covered, rf"(?<![\w.]){re.escape(version)}(?!\w)")
        anywhere = ("LICENSE", "docs/runtimes.md")
        coverage = {f"skills/{name}/SKILL.md" for name in stack}
        for rel in repository_files():
            for number, row in enumerate(read(rel).splitlines(), 1):
                if LINK.search(row) and rel not in anywhere:
                    self.assertTrue(rel in coverage and COVERAGE.fullmatch(row), f"{rel}:{number} holds a link")

    def test_skill_cross_references_resolve(self):
        texts = skills()
        found = 0
        for name, text in texts.items():
            for ref in NAME.findall(text):
                found += 1
                self.assertIn(ref, texts, f"{name} names the unknown skill {ref}")
        self.assertGreater(found, len(texts))


if __name__ == "__main__":
    unittest.main()
