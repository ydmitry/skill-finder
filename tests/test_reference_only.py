"""A phrase search over several phrases: what a listed skill holds only in its reference files, and which reference files it has.

A skill whose SKILL.md holds one looked-up phrase may hold another only in a reference file. Its row names that phrase with the
file and line, and lists the skill's reference files. Temp skill folders, no model and no machine state."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FINDER = Path(__file__).resolve().parent.parent / "scripts" / "find_skills.py"


def skill(name, body="body", description="x"):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n{body}\n"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, skills, refs=None):
        """skills: name -> SKILL.md text; refs: name -> {relative path: text}."""
        for name, text in skills.items():
            (self.tmp / name).mkdir()
            (self.tmp / name / "SKILL.md").write_text(text)
        for name, files in (refs or {}).items():
            for rel, text in files.items():
                (self.tmp / name / rel).parent.mkdir(parents=True, exist_ok=True)
                (self.tmp / name / rel).write_text(text)

    def run_finder(self, *phrases, extra=()):
        cmd = [sys.executable, str(FINDER), "--only", str(self.tmp), *[x for p in phrases for x in ("--phrase", p)], *extra]
        out = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def json_of(self, *phrases, extra=()):
        return json.loads(self.run_finder(*phrases, extra=("--json", *extra)))

    def row(self, text, name):
        """The lines of one numbered row of the text output, from its head line to the next row or the first blank line."""
        lines = text.splitlines()
        at = next(i for i, ln in enumerate(lines) if ln.split("  [")[0].split(". ", 1)[-1] == name and ln[:1].isdigit())
        end = next((i for i in range(at + 1, len(lines)) if not lines[i].startswith("   ")), len(lines))
        return lines[at:end]


class ReferenceOnly(Base):
    def test_a_phrase_only_in_a_reference_file_of_a_listed_skill_is_shown_with_file_line_and_phrase(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"references/torches.md": "# Lights\n\nBring one torch for each pair.\n"}})
        text = self.run_finder("children", "torch")
        self.assertIn('   :references/torches.md:3: Bring one torch for each pair.  ("torch")', self.row(text, "camping"))
        c = self.json_of("children", "torch")["candidates"][0]
        self.assertEqual(c["phrases"], ["children"])
        self.assertEqual(c["reference_only"], [dict(phrase="torch", file="references/torches.md", line=3, text="Bring one torch for each pair.")])

    def test_the_line_is_where_that_phrase_matches_not_where_another_phrase_matches_earlier(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"references/a-other.md": "children only here\n",
                               "references/night.md": "The children sleep early.\n\n\nEach torch needs a battery.\n"}})
        c = self.json_of("children", "torch")["candidates"][0]
        self.assertEqual(c["reference_only"], [dict(phrase="torch", file="references/night.md", line=4, text="Each torch needs a battery.")])
        self.assertIn('   :references/night.md:4: Each torch needs a battery.  ("torch")', self.run_finder("children", "torch"))

    def test_the_file_is_the_first_reference_file_that_holds_the_phrase(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"notes.md": "a torch in the notes\n", "references/z.md": "a torch in the references\n"}})
        c = self.json_of("children", "torch")["candidates"][0]
        self.assertEqual(c["reference_only"][0]["file"], "references/z.md")            # references/ comes first, as in the best match

    def test_a_phrase_in_the_skill_md_or_the_name_gets_no_line_and_nothing_new_gets_none(self):
        self.make({"torch-care": skill("torch-care", "Take the children along."),
                   "plain": skill("plain", "The children carry a torch."),
                   "nothing-new": skill("nothing-new", "The children walk.")},
                  {"torch-care": {"references/r.md": "A torch and the children.\n"},
                   "plain": {"references/r.md": "A torch and the children.\n"},
                   "nothing-new": {"references/r.md": "Only the children are here.\n"}})
        out = self.json_of("children", "torch")
        self.assertEqual({c["name"]: c["reference_only"] for c in out["candidates"]}, {"torch-care": [], "plain": [], "nothing-new": []})
        text = self.run_finder("children", "torch")
        self.assertNotIn(":references/r.md:", text)
        self.assertNotIn('("', text.split("Best match:")[0].split("\n", 1)[1])

    def test_three_lines_a_skill_then_how_many_more_phrases(self):
        refs = {f"references/r{i}.md": f"the word{i} is here\n" for i in range(1, 6)}
        self.make({"camping": skill("camping", "Take the children along.")}, {"camping": refs})
        phrases = ["word3", "children", "word1", "word5", "word2", "word4"]
        row = self.row(self.run_finder(*phrases), "camping")
        marked = [ln for ln in row if ln.endswith('")')]
        self.assertEqual(marked, ['   :references/r3.md:1: the word3 is here  ("word3")',             # in the order they were typed
                                  '   :references/r1.md:1: the word1 is here  ("word1")',
                                  '   :references/r5.md:1: the word5 is here  ("word5")'])
        self.assertEqual(row[row.index(marked[-1]) + 1], "   (+2 more phrases only in its reference files)")
        c = self.json_of(*phrases)["candidates"][0]
        self.assertEqual([r["phrase"] for r in c["reference_only"]], ["word3", "word1", "word5", "word2", "word4"])       # all of them

    def test_three_phrases_get_no_more_line(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"references/r.md": "word1\nword2\nword3\n"}})
        self.assertNotIn("more phrases only in", self.run_finder("children", "word1", "word2", "word3"))

    def test_a_skill_md_hit_beyond_the_limit_is_in_the_reference_block_and_a_shown_one_is_not(self):
        self.make({"children-first": skill("children-first", "children"), "children-second": skill("children-second"),
                   "later": skill("later", "The children walk."),
                   "none": skill("none", "Nothing.")},
                  {"children-first": {"references/r.md": "one torch\n"},
                   "later": {"references/r.md": "\na torch for later\n"},
                   "none": {"references/r.md": "a torch and the children\n"}})
        out = self.json_of("children", "torch", extra=("--limit", "2"))
        self.assertEqual([c["name"] for c in out["candidates"]], ["children-first", "children-second"])
        hits = {r["name"]: r for r in out["reference_hits"]}
        self.assertEqual(sorted(hits), ["later", "none"])                              # children-first is shown above: not repeated
        self.assertEqual(out["reference_matched"], 2)
        self.assertEqual(hits["later"]["phrases"], ["torch"])                          # only what its SKILL.md and name do not hold
        self.assertEqual(hits["later"]["match"], "references/r.md:2: a torch for later")
        self.assertEqual(hits["none"]["phrases"], ["children", "torch"])
        text = self.run_finder("children", "torch", extra=("--limit", "2"))
        block = text.split("Only in reference files")[1].split("Best match:")[0]
        self.assertIn("- later  [folder skill]", block)
        self.assertIn('   :references/r.md:2: a torch for later  ("torch")', block)
        self.assertNotIn("children-first", block)
        head = text.split("Only in reference files")[1].splitlines()[0]
        self.assertNotIn("whose SKILL.md does not contain it", head)                   # 'later' holds a phrase in its SKILL.md
        self.assertIn("2 skill(s) not listed above", head)

    def test_a_shown_hit_stays_out_of_the_reference_block_without_a_limit(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"references/r.md": "a torch\n"}})
        out = self.json_of("children", "torch")
        self.assertEqual((out["reference_matched"], out["reference_hits"]), (0, []))
        self.assertNotIn("Only in reference files", self.run_finder("children", "torch"))

    def test_the_reference_block_line_is_where_a_reference_only_phrase_is(self):
        self.make({"shown": skill("shown", "children children"), "later": skill("later", "The children walk.")},
                  {"later": {"references/r.md": "the children again\nthen a torch\n"}})
        out = self.json_of("children", "torch", extra=("--limit", "1"))
        self.assertEqual(out["reference_hits"][0]["match"], "references/r.md:2: then a torch")

    def test_rows_of_a_search_no_skill_md_holds_name_the_phrase_too(self):
        self.make({"alpha": skill("alpha")}, {"alpha": {"references/r.md": "# R\nthe quartz gauge\n"}})
        text = self.run_finder("brass valve", "quartz gauge")
        self.assertIn("No SKILL.md contains it, but 1 skill(s) hold it in their reference files", text)
        self.assertIn('   :references/r.md:2: the quartz gauge  ("quartz gauge")', text)

    def test_every_shown_row_with_reference_files_lists_them(self):
        self.make({"children-camp": skill("children-camp"), "second": skill("second", "The children walk."),
                   "bare": skill("bare", "The children run.")},
                  {"children-camp": {"notes.md": "n\n", "references/b.md": "b\n", "references/a.md": "a\n"},
                   "second": {"guide.txt": "g\n"}})
        text = self.run_finder("children")
        self.assertIn("   references: references/a.md, references/b.md, notes.md", self.row(text, "children-camp"))
        self.assertIn("   references: guide.txt", self.row(text, "second"))
        self.assertFalse([ln for ln in self.row(text, "bare") if "references:" in ln])
        self.assertIn("References: references/a.md, references/b.md, notes.md", text)           # the best match's own line stays
        refs = {c["name"]: c["references"] for c in self.json_of("children")["candidates"]}
        self.assertEqual(refs, {"children-camp": ["references/a.md", "references/b.md", "notes.md"], "second": ["guide.txt"], "bare": []})

    def test_eight_reference_files_are_listed_then_how_many_more(self):
        self.make({"ten": skill("ten", "The children walk."), "eight": skill("eight", "The children run.")},
                  {"ten": {f"references/r{i}.md": "x\n" for i in range(10)}, "eight": {f"references/r{i}.md": "x\n" for i in range(8)}})
        text = self.run_finder("children")
        self.assertIn("   references: " + ", ".join(f"references/r{i}.md" for i in range(8)) + " (+2 more)", self.row(text, "ten"))
        self.assertIn("   references: " + ", ".join(f"references/r{i}.md" for i in range(8)), self.row(text, "eight"))
        self.assertEqual(len(self.json_of("children")["candidates"][1]["references"]), 10)       # eight, then ten: all of them

    def test_a_row_is_match_line_then_reference_only_lines_then_references_then_also_at(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"references/torches.md": "one torch\n"}})
        other = self.tmp.parent / (self.tmp.name + "-copy")
        try:
            (other / "camping").mkdir(parents=True)
            (other / "camping" / "SKILL.md").write_text((self.tmp / "camping" / "SKILL.md").read_text())
            os.utime(other / "camping", (1, 1))                 # of two equal copies the newer folder is the one shown: the one with references
            text = self.run_finder("children", "torch", extra=("--only", str(other)))
        finally:
            shutil.rmtree(other, ignore_errors=True)
        row = self.row(text, "camping")
        self.assertEqual([ln.strip().split(" ")[0] for ln in row[2:]], [":7:", ":references/torches.md:1:", "references:", "also"], row)

    def test_skills_whose_skill_md_holds_no_phrase_come_before_hits_beyond_the_limit_in_the_block(self):
        self.make({"a-shown": skill("a-shown", "children children"), "b-later": skill("b-later", "The children walk."),
                   "z-none": skill("z-none", "Nothing.")},
                  {"b-later": {"references/r.md": "a torch\n", "references/s.md": "a lamp\n"},
                   "z-none": {"references/r.md": "a torch\n"}})
        out = self.json_of("children", "torch", "lamp", extra=("--limit", "1"))
        self.assertEqual([c["name"] for c in out["candidates"]], ["a-shown"])
        out = self.json_of("children", "torch", "lamp", extra=("--limit", "2"))        # b-later is shown now, z-none is the block
        self.assertEqual([r["name"] for r in out["reference_hits"]], ["z-none"])
        self.make({"c-later": skill("c-later", "children")}, {"c-later": {"references/r.md": "a torch\n", "references/s.md": "a lamp\n"}})
        out = self.json_of("children", "torch", "lamp", extra=("--limit", "2"))
        self.assertEqual([r["name"] for r in out["reference_hits"]], ["z-none", "c-later"])       # c-later holds more phrases there, and is a hit

    def test_two_spellings_of_one_phrase_get_one_line(self):
        self.make({"camping": skill("camping", "Take the children along.")}, {"camping": {"references/t.md": "one torch\n"}})
        row = self.row(self.run_finder("children", "torch", "Torch"), "camping")
        self.assertEqual(len([ln for ln in row if "references/t.md:1:" in ln]), 1)

    def test_toc_mode_prints_none_of_it(self):
        self.make({"camping": skill("camping", "Take the children along.")},
                  {"camping": {"references/torches.md": "one torch\n"}})
        text = self.run_finder("children", "torch", extra=("--toc",))
        self.assertNotIn("torches.md", text)
        self.assertNotIn("references:", text)
        c = self.json_of("children", "torch", extra=("--toc",))["candidates"][0]
        self.assertFalse({"reference_only", "references"} & set(c))


class ReferenceOrder(Base):
    """Which reference files a row names when it cannot name them all, and which file a hit line is taken from: the files that hold
    most of the looked-up phrases, not the first in the folder."""

    def many(self, special):
        refs = {f"references/a{i:02d}.md": "nothing of note here\n" for i in range(1, 13)}
        refs.update(special)
        self.make({"camping": skill("camping", "for children")}, {"camping": refs})

    def listed(self, text, name="camping"):
        line = next(ln for ln in self.row(text, name) if ln.startswith("   references: "))
        return line[len("   references: "):].split(" (+")[0].split(", ")

    def test_a_file_that_holds_a_looked_up_phrase_is_named_first_in_a_cut_list(self):
        self.many({"references/a11.md": "one zebra crossing\n"})
        names = self.listed(self.run_finder("children", "zebra"))
        self.assertEqual(names[0], "references/a11.md")
        self.assertEqual(len(names), 8)
        self.assertEqual(names[1:3], ["references/a01.md", "references/a02.md"])           # the rest keep their order

    def test_a_file_whose_name_holds_a_phrase_counts_too(self):
        self.many({"references/a12-zebra-crossing.md": "nothing here either\n"})
        self.assertEqual(self.listed(self.run_finder("children", "zebra"))[0], "references/a12-zebra-crossing.md")

    def test_more_phrases_held_comes_before_fewer(self):
        self.many({"references/a09.md": "a zebra\n", "references/a10.md": "a zebra and a lantern\n"})
        self.assertEqual(self.listed(self.run_finder("children", "zebra", "lantern"))[:2], ["references/a10.md", "references/a09.md"])

    def test_no_phrase_in_any_reference_file_keeps_the_order(self):
        self.many({})
        self.assertEqual(self.listed(self.run_finder("children"))[:3], ["references/a01.md", "references/a02.md", "references/a03.md"])

    def test_a_phrase_the_skill_md_holds_also_ranks_a_file(self):
        self.many({"references/a12.md": "the children again\n"})
        self.assertEqual(self.listed(self.run_finder("children"))[0], "references/a12.md")

    def test_the_hit_line_comes_from_the_file_that_holds_most_phrases(self):
        self.make({"camping": skill("camping", "for children")},
                  {"camping": {"references/a-first.md": "one torch\n", "references/z-best.md": "tent\nlantern\nthe torch is here\n"}})
        c = self.json_of("children", "torch", "lantern", "tent")["candidates"][0]
        self.assertEqual({x["phrase"]: x["file"] for x in c["reference_only"]},
                         {"torch": "references/z-best.md", "lantern": "references/z-best.md", "tent": "references/z-best.md"})
        self.assertEqual(c["references"], ["references/z-best.md", "references/a-first.md"])

    def test_a_phrase_few_files_hold_outweighs_phrases_many_hold(self):
        refs = {f"references/a{i:02d}.md": "focus and remote\n" for i in range(1, 11)}          # two common phrases in ten files
        refs["references/a11.md"] = "the side menu\n"                                          # one phrase no other file holds
        self.make({"camping": skill("camping", "for children")}, {"camping": refs})
        names = self.listed(self.run_finder("children", "focus", "remote", "side menu"))
        self.assertEqual(names[0], "references/a11.md")

    def test_the_hit_line_of_a_common_phrase_comes_from_the_file_with_the_rare_ones(self):
        refs = {f"references/a{i:02d}.md": "focus and remote and a dialog\n" for i in range(1, 6)}
        refs["references/nav.md"] = "tabs\nthe side menu\na dialog here\n"
        self.make({"camping": skill("camping", "for children")}, {"camping": refs})
        c = self.json_of("children", "dialog", "focus", "remote", "tabs", "side menu")["candidates"][0]
        self.assertEqual({x["phrase"]: x["file"] for x in c["reference_only"]}["dialog"], "references/nav.md")

    def test_identical_copies_of_a_file_take_one_place_in_the_list(self):
        refs = {f"copy{i}/guide.md": "one zebra crossing\n" for i in range(1, 9)}
        refs["other.md"] = "a zebra too, and more\n"
        self.make({"camping": skill("camping", "for children")}, {"camping": refs})
        text = self.run_finder("children", "zebra")
        names = self.listed(text)
        self.assertEqual(sorted(names), ["copy1/guide.md", "other.md"])
        self.assertIn("(+7 more, copies of these)", "\n".join(self.row(text, "camping")))
        self.assertEqual(len(self.json_of("children", "zebra")["candidates"][0]["references"]), 9)        # --json keeps every path

    def test_the_best_match_names_the_same_files(self):
        self.many({"references/a11.md": "one zebra crossing\n"})
        text = self.run_finder("children", "zebra")
        best = next(ln for ln in text.splitlines() if ln.startswith("References: "))
        self.assertTrue(best.startswith("References: references/a11.md, references/a01.md"), best)
        self.assertEqual(self.json_of("children", "zebra")["best"]["references"][0], "references/a11.md")

    def test_a_skill_shown_only_for_its_reference_files_is_not_changed(self):
        self.make({"camping": skill("camping", "tents")}, {"camping": {"references/a.md": "x\n", "references/b.md": "a zebra\n"}})
        self.assertIn(":references/b.md:1: a zebra", self.run_finder("zebra"))


if __name__ == "__main__":
    unittest.main()
