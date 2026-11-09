"""SKILL.md must carry a frontmatter that a strict YAML reader accepts: with a colon-and-space inside a plain description the reader refuses the
whole block, and the skill is then listed by its name alone, without the text that says when to use it. Without PyYAML the finder
reads a frontmatter leniently, folded and literal blocks included."""
import importlib.util
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:                         # the finder itself reads such a file leniently; only this check needs PyYAML
    yaml = None

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class Frontmatter(unittest.TestCase):
    def test_the_frontmatter_is_valid_yaml_with_a_name_and_a_description(self):
        block = re.match(r"---\n(.*?)\n---\n", SKILL.read_text(), re.S).group(1)
        data = yaml.safe_load(block)
        self.assertEqual(data["name"], "skill-finder")
        self.assertIn("Use when", data["description"])
        self.assertIn("a task might fit an installed skill", data["description"])


class LenientReader(unittest.TestCase):
    """The finder's own reader, used when PyYAML cannot be imported (python3 -I, or no PyYAML)."""

    def frontmatter(self, text):
        spec = importlib.util.spec_from_file_location("find_skills_under_test", SKILL.parent / "scripts" / "find_skills.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with mock.patch.dict(sys.modules, {"yaml": None}):          # import yaml now fails, as without PyYAML
            return mod.frontmatter(text)

    def test_a_block_scalar_keeps_no_indicator(self):
        """`>-`, `|-` and an indentation digit are the block's header, not its text: "description: >-" gave "- Use when ..."."""
        for header in (">-", "|-", "|2+", ">"):
            text = f"---\nname: folded\ndescription: {header}\n  Use when a task\n  fits.\n---\n\n# folded\n"
            self.assertEqual(self.frontmatter(text), {"name": "folded", "description": "Use when a task fits."}, header)

    def test_a_block_header_with_a_comment_keeps_neither(self):
        """A comment after the header is not the text either: "description: >- # folded" gave "- # folded Use when ..."."""
        for header in (">- # folded", "| # literal", "|2+  # kept"):
            text = f"---\nname: folded\ndescription: {header}\n  Use when a task\n  fits.\n---\n"
            self.assertEqual(self.frontmatter(text), {"name": "folded", "description": "Use when a task fits."}, header)

    def test_a_comment_line_belongs_to_no_key(self):
        """A line whose text starts with # is a YAML comment. It was added to the key above it, so `--toc fenced` found no skill:
        its name had become "fenced # a yaml comment"."""
        text = "---\nname: fenced\n# a yaml comment\ndescription: Does it.\n  # another one\n---\n"
        self.assertEqual(self.frontmatter(text), {"name": "fenced", "description": "Does it."})

    def test_a_plain_value_keeps_its_signs_and_digits(self):
        text = "---\nname: steps\ndescription: 2-step plan for -1 + 3\n---\n"
        self.assertEqual(self.frontmatter(text)["description"], "2-step plan for -1 + 3")


if __name__ == "__main__":
    unittest.main()
