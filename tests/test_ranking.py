"""Golden queries for find_skills.py against a fixed folder of 18 skills (tests/fixtures/skills), no model and no machine state.

Every query is written the way SKILL.md asks: the words a skill's description would use for what it does. A skill listed
in FIRST must rank first; one in TOP3 must rank in the first three. Common-word and nonsense queries must come back with
LOW CONFIDENCE, and a clear first hit must not."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FINDER = HERE.parent / "scripts" / "find_skills.py"
FIXTURES = HERE / "fixtures" / "skills"

FIRST = {
    "bounded loop until the check command exits 0": "goal-loop",
    "graphql mutation validation error curl payload": "graphql-iterate",
    "graphql api": "graphql-iterate",
    "production errors logs trace id": "log-triage",
    "which repo owns this request across services": "cross-repo-trace",
    "draw a diagram of the system as a page": "diagram-explainer",
    "create a new skill": "skill-author",
    "memory leak heap snapshot node": "heap-analysis",
    "root cause of a bug before fixing": "systematic-debug",
}
TOP3 = {
    "keep going unattended until done loop": "goal-loop",
    "investigate staging error logs": "log-triage",
    "test the pull request live in the browser with playwright": "playwright-live",
    "color contrast ratio of a text color": "accessibility",
}
# Words found in over a fifth of these 18 skills ("test", "write", "first", "request", "page"), then nonsense.
NOT_CONFIDENT = ["test", "write first", "write first request page", "xyzzy plugh", "banana helicopter",
                 "lorem ipsum dolor sit", "qqq zzz", "the and of"]


def find(task, *extra, env=None):
    cmd = [sys.executable, str(FINDER), "--only", str(FIXTURES), "--top", "3", "--json", "--task", task, *extra]
    out = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


class Golden(unittest.TestCase):
    def test_fixture_folder_has_eighteen_skills(self):
        self.assertEqual(find("anything")["scanned"], 18)

    def test_expected_skill_ranks_first(self):
        for task, want in FIRST.items():
            names = [c["name"] for c in find(task)["candidates"]]
            self.assertEqual(names[:1], [want], f"{task!r} -> {names}")

    def test_expected_skill_ranks_in_the_top_three(self):
        for task, want in TOP3.items():
            names = [c["name"] for c in find(task)["candidates"]]
            self.assertIn(want, names, f"{task!r} -> {names}")

    def test_a_clear_first_hit_is_not_low_confidence(self):
        for task in FIRST:
            self.assertFalse(find(task)["low_confidence"], task)

    def test_common_and_nonsense_queries_are_low_confidence(self):
        for task in NOT_CONFIDENT:
            self.assertTrue(find(task)["low_confidence"], task)

    def test_common_words_are_listed(self):
        """The searcher learns which of its words did not count. 'write' and 'page' are in over a fifth of the fixture skills."""
        out = find("graphql write page")
        self.assertEqual(sorted(out["common"]), ["page", "write"], out["common"])
        self.assertEqual(find("test")["common"], ["test"])
        self.assertEqual(find("bounded loop until the check command exits 0")["common"], [])

    def test_the_text_output_names_the_common_words_and_the_rephrase_advice(self):
        def text(task):
            cmd = [sys.executable, str(FINDER), "--only", str(FIXTURES), "--top", "3", "--task", task]
            return subprocess.run(cmd, capture_output=True, text=True).stdout
        low = text("write first request page")
        self.assertIn("LOW CONFIDENCE", low)
        self.assertIn("what the finished thing is called", low)
        self.assertIn("every word is very common", low)
        self.assertIn("dropped as too common to rank: page, write", text("graphql write page"))
        self.assertNotIn("too common", text("bounded loop until the check command exits 0"))

    def test_a_common_word_does_not_outvote_a_rare_one(self):
        """'tests' is in many skill texts; 'graphql' in one. The rare word decides."""
        names = [c["name"] for c in find("graphql tests failing")["candidates"]]
        self.assertEqual(names[0], "graphql-iterate", names)


class PhraseSearch(unittest.TestCase):
    """--phrase: an exact phrase in the whole SKILL.md of every skill, listed compactly and ranked, not scored by words."""

    def run_phrase(self, *phrases, folder=FIXTURES, extra=()):
        cmd = [sys.executable, str(FINDER), "--only", str(folder), "--json", *[x for p in phrases for x in ("--phrase", p)], *extra]
        out = subprocess.run(cmd, capture_output=True, text=True)
        return out.returncode, (json.loads(out.stdout) if out.returncode == 0 else out.stderr)

    def make(self, tmp, skills):
        for name, text in skills.items():
            (Path(tmp) / name).mkdir()
            (Path(tmp) / name / "SKILL.md").write_text(text)
        return tmp

    def test_a_phrase_in_one_body_lists_that_skill_only(self):
        code, out = self.run_phrase("contrast ratio")
        self.assertEqual(code, 0)
        self.assertEqual([c["name"] for c in out["candidates"]], ["accessibility"])
        self.assertEqual(out["matched"], 1)

    def test_the_phrase_is_looked_up_in_the_body_not_only_the_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"alpha": "---\nname: alpha\ndescription: Does a thing.\n---\n\n# Alpha\nFollow the zebra crossing protocol.\n"})
            code, out = self.run_phrase("zebra crossing", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]], ["alpha"])
            self.assertTrue(out["candidates"][0]["match"].startswith("7: Follow the zebra crossing"), out["candidates"][0]["match"])

    def test_a_phrase_may_wrap_a_line_and_be_hyphenated_and_any_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"beta": "---\nname: beta\ndescription: x\n---\nBreak the work into a Task\nBreakdown first.\n",
                            "gamma": "---\nname: gamma\ndescription: x\n---\nUse the task-breakdown template.\n",
                            "delta": "---\nname: delta\ndescription: x\n---\nA breakdown of tasks.\n"})
            _, out = self.run_phrase("task breakdown", folder=tmp)
            self.assertEqual(sorted(c["name"] for c in out["candidates"]), ["beta", "gamma"])

    def test_a_phrase_starts_a_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"a": "---\nname: a\ndescription: x\n---\nWe fly an airplane.\n",
                            "b": "---\nname: b\ndescription: x\n---\nWe are planning.\n"})
            _, out = self.run_phrase("plan", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]], ["b"])

    def test_name_beats_description_beats_body_and_more_phrases_beat_fewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {
                "body-only": "---\nname: body-only\ndescription: x\n---\nMentions the quartz gauge twice: quartz gauge.\n",
                "in-desc": "---\nname: in-desc\ndescription: Reads the quartz gauge.\n---\nbody\n",
                "quartz-gauge": "---\nname: quartz-gauge\ndescription: x\n---\nbody\n",
                "both": "---\nname: both\ndescription: x\n---\nA quartz gauge and a brass valve.\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]], ["quartz-gauge", "in-desc", "body-only", "both"])
            _, out = self.run_phrase("quartz gauge", "brass valve", folder=tmp)
            self.assertEqual(out["candidates"][0]["name"], "both")

    def test_the_limit_cuts_the_list_and_says_how_many_matched(self):
        _, out = self.run_phrase("the", extra=("--limit", "2"))
        self.assertEqual(out["shown"], 2)
        self.assertGreater(out["matched"], 2)
        cmd = [sys.executable, str(FINDER), "--only", str(FIXTURES), "--phrase", "the", "--limit", "2"]
        text = subprocess.run(cmd, capture_output=True, text=True).stdout
        self.assertIn("the best 2 are shown", text)

    def test_equal_skills_come_out_by_name_whatever_order_the_folders_were_made_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("zulu", "mike", "alpha"):
                self.make(tmp, {name: f"---\nname: {name}\ndescription: x\n---\nThe amber lamp.\n"})
            _, out = self.run_phrase("amber lamp", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]], ["alpha", "mike", "zulu"])

    def text_of(self, folder, *phrases):
        cmd = [sys.executable, str(FINDER), "--only", str(folder), *[x for ph in phrases for x in ("--phrase", ph)]]
        return subprocess.run(cmd, capture_output=True, text=True).stdout

    def test_a_miss_counts_the_skills_holding_each_word_and_lists_the_nearest_ten(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = {f"glow-{i}": f"---\nname: glow-{i}\ndescription: Glow number {i}.\n---\nAmber glow number {i}.\n" for i in range(12)}
            skills.update({f"filler-{i}": f"---\nname: filler-{i}\ndescription: x\n---\nNothing here {i}.\n" for i in range(80)})
            skills["lamp-post"] = "---\nname: lamp-post\ndescription: x\n---\nA lamp on a post.\n"
            self.make(tmp, skills)
            code, out = self.run_phrase("amber lamp", folder=tmp)
            self.assertEqual((code, out["matched"], out["candidates"]), (0, 0, []))
            self.assertEqual(out["word_counts"], {"amber": 12, "lamp": 1})
            self.assertEqual(len(out["nearest"]), 10)
            text = self.text_of(tmp, "amber lamp")
            self.assertIn("No skill contains it", text)
            self.assertIn("Skills holding each word: amber 12, lamp 1", text)
            self.assertIn("Nearest by words", text)
            listed = [ln for ln in text.splitlines() if re.match(r"\d+\. ", ln)]
            self.assertEqual(len(listed), 10)
            self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("   ")), 3)        # only the first three carry a description

    def test_the_same_words_in_another_order_still_point_at_the_skill(self):
        _, out = self.run_phrase("ratio contrast")
        self.assertEqual(out["matched"], 0)
        self.assertIn("accessibility", [n["name"] for n in out["nearest"]])
        self.assertEqual(out["nearest"][0]["path"].endswith("SKILL.md"), True)

    def test_words_no_skill_holds_say_so_and_list_nothing(self):
        text = self.text_of(FIXTURES, "zzz qqq")
        self.assertIn("zzz 0, qqq 0", text)
        self.assertIn("No skill holds any of these words either", text)
        self.assertNotIn("Nearest by words", text)

    def test_a_hit_carries_no_miss_report(self):
        _, out = self.run_phrase("contrast ratio")
        self.assertNotIn("word_counts", out)
        self.assertNotIn("nearest", out)
        self.assertNotIn("Skills holding each word", self.text_of(FIXTURES, "contrast ratio"))

    def test_no_match_says_so_and_a_task_is_refused_beside_it(self):
        cmd = [sys.executable, str(FINDER), "--only", str(FIXTURES), "--phrase", "zzz qqq"]
        self.assertIn("No skill contains it", subprocess.run(cmd, capture_output=True, text=True).stdout)
        code, err = self.run_phrase("heap", extra=("--task", "heap"))
        self.assertNotEqual(code, 0)
        self.assertIn("not both", err)


class DefaultRoots(unittest.TestCase):
    def make_root(self, tmp):
        sk = Path(tmp) / "extra" / "moon-skill"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("---\nname: moon-skill\ndescription: Chart the phases of the moon.\n---\n\nbody\n")
        roots = Path(tmp) / "roots"
        roots.write_text(f"# a comment\n\n{Path(tmp) / 'extra'}\n")
        return roots

    def run_list(self, roots, *extra):
        cmd = [sys.executable, str(FINDER), "--list", *extra]
        return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "SKILL_FINDER_ROOTS": str(roots)}).stdout

    def test_roots_file_adds_skills_to_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("moon-skill", self.run_list(self.make_root(tmp)))

    def test_missing_roots_file_is_fine(self):
        self.assertNotIn("moon-skill", self.run_list(Path(tempfile.gettempdir()) / "no-such-roots-file"))

    def test_only_ignores_the_roots_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_list(self.make_root(tmp), "--only", str(FIXTURES))
            self.assertNotIn("moon-skill", out)


STUB = """import json, os, sys
open(os.environ["STUB_COUNT"], "a").write("x")
sys.stdin.read()
mode = os.environ.get("STUB_MODE", "alpha")
if mode == "fail": sys.exit(3)
if mode == "garbage": print(json.dumps({"result": "no json here"})); sys.exit(0)
ans = {"pick": "NONE", "why": "nothing fits"} if mode == "none" else {"pick": mode, "why": "its text says it is for crossing roads"}
print(json.dumps({"result": json.dumps(ans), "total_cost_usd": 0.002}))
"""


class BestMatch(unittest.TestCase):
    """A phrase search ends with the best match (why, first lines, references, where to read); --for adds a model's reason. The model is
    a stub script here: no model is called."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.skills = t / "skills"
        self.skills.mkdir()
        body = "\n".join(f"line {i}" for i in range(1, 31))
        for name, extra in (("alpha", "Follow the zebra crossing protocol."), ("beta", "A zebra crossing is mentioned once.")):
            (self.skills / name).mkdir()
            (self.skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Use when you cross a road. It also helps.\n---\n\n# {name}\n{extra}\n{body}\n")
        (self.skills / "alpha" / "references").mkdir()
        for i in range(10):
            (self.skills / "alpha" / "references" / f"r{i}.md").write_text(f"# r{i}\n")
        (t / "tmpdir").mkdir()
        (t / "stub.py").write_text(STUB)
        self.count, self.cost = t / "count", t / "cost.log"
        self.env = {**os.environ, "SKILL_FINDER_CLAUDE": f"{sys.executable} {t / 'stub.py'}", "STUB_COUNT": str(self.count),
                    "SKILL_FINDER_COST_LOG": str(self.cost), "TMPDIR": str(t / "tmpdir")}
        self.env.pop("SKILL_FINDER_NESTED", None)
        self.env.pop("SKILL_FINDER_EXPLAIN", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_finder(self, *args, mode="alpha", env=None):
        cmd = [sys.executable, str(FINDER), "--only", str(self.skills), "--phrase", "zebra crossing", *args]
        return subprocess.run(cmd, capture_output=True, text=True, env={**self.env, "STUB_MODE": mode, **(env or {})}).stdout

    def calls(self):
        return len(self.count.read_text()) if self.count.is_file() else 0

    def test_a_phrase_search_ends_with_the_best_match_and_calls_no_model(self):
        text = self.run_finder()
        self.assertIn("Best match: alpha", text)
        self.assertIn('Why: "zebra crossing" is in', text)
        self.assertIn("Description: Use when you cross a road.", text)
        self.assertNotIn("It also helps", text.split("Description:")[1].splitlines()[0])
        self.assertIn("First lines of SKILL.md:", text)
        self.assertIn("  # alpha", text)
        self.assertIn("  line 18", text)
        self.assertNotIn("line 19", text)                                   # twenty lines of the body
        self.assertIn("References: references/r0.md", text)
        self.assertIn("(+2 more)", text)
        self.assertTrue(text.rstrip().endswith(f"Read {self.skills / 'alpha' / 'SKILL.md'}, then follow it; search again only if it does not fit."))
        self.assertNotIn("Fit", text)
        self.assertEqual(self.calls(), 0)

    def test_for_adds_a_models_reason_and_the_same_question_is_asked_once(self):
        text = self.run_finder("--for", "cross a road")
        self.assertIn('Fit (a model read the first 2 hits against "cross a road"): its text says it is for crossing roads', text)
        self.assertEqual(self.calls(), 1)
        self.run_finder("--for", "cross a road")
        self.assertEqual(self.calls(), 1)                                   # cached
        self.assertEqual(len(self.cost.read_text().splitlines()), 1)

    def test_the_model_may_pick_the_second_hit(self):
        text = self.run_finder("--for", "cross a road", mode="beta")
        self.assertIn("Best match: beta", text)
        self.assertIn("(hit 2, picked by the model)", text)
        self.assertIn(f"Read {self.skills / 'beta' / 'SKILL.md'}", text)

    def test_none_says_no_skill_clearly_fits_and_sends_no_one_to_read(self):
        text = self.run_finder("--for", "cross a road", mode="none")
        self.assertIn("none clearly fits", text)
        self.assertIn("No skill clearly fits", text)
        self.assertNotIn("First lines", text)
        self.assertNotIn("then follow it", text)

    def test_a_failing_model_or_a_made_up_name_leaves_the_plain_best_match(self):
        for mode in ("fail", "garbage", "ghost"):
            text = self.run_finder("--for", f"cross a road {mode}", mode=mode)
            self.assertIn("Fit: not available", text, mode)
            self.assertIn("Best match: alpha", text, mode)
            self.assertIn("then follow it", text, mode)

    def test_no_model_inside_a_model_call_and_none_when_switched_off(self):
        for env in ({"SKILL_FINDER_NESTED": "1"}, {"SKILL_FINDER_EXPLAIN": "0"}):
            text = self.run_finder("--for", "cross a road", env=env)
            self.assertNotIn("Fit", text)
            self.assertIn("Best match: alpha", text)
        self.assertEqual(self.calls(), 0)

    def test_the_number_of_hits_the_model_reads_can_be_set(self):
        text = self.run_finder("--for", "cross a road", env={"SKILL_FINDER_WHY_HITS": "1"})
        self.assertIn('against "cross a road"', text)
        self.assertIn("first 1 hits", text)
        text = self.run_finder("--for", "cross a road two", mode="beta", env={"SKILL_FINDER_WHY_HITS": "1"})
        self.assertIn("Fit: not available", text)                           # beta was not among the one hit the model was shown

    def test_json_carries_the_best_match(self):
        out = json.loads(self.run_finder("--json", "--for", "cross a road"))
        self.assertEqual(out["best"]["name"], "alpha")
        self.assertEqual(out["best"]["fit"]["pick"], "alpha")
        self.assertEqual(len(out["best"]["lines"]), 20)


if __name__ == "__main__":
    unittest.main()
