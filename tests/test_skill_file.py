"""SKILL.md must carry a frontmatter that a strict YAML reader accepts: with a colon-and-space inside a plain description the reader refuses the
whole block, and the skill is then listed by its name alone, without the text that says when to use it."""
import re
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
