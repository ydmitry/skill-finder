"""Golden queries for find_skills.py against a fixed folder of 18 skills (tests/fixtures/skills), no model and no machine state.

Every query is written the way SKILL.md asks: the words a skill's description would use for what it does. A skill listed
in FIRST must rank first; one in TOP3 must rank in the first three. Common-word and nonsense queries must come back with
LOW CONFIDENCE, and a clear first hit must not."""
import ast
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
NO_PROCESS_OR_NETWORK = {"subprocess", "socket", "_socket", "ssl", "urllib", "http", "ctypes", "webbrowser", "pty", "socketserver",
                         "ftplib", "smtplib", "asyncio", "multiprocessing", "concurrent"}
# Runs the finder in this interpreter, then names which of the modules in argv[1] it had loaded.
LOADED = """import runpy, sys
watched = set(sys.argv[1].split(","))
sys.argv = sys.argv[2:]
try: runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as e:
    if e.code not in (None, 0): raise
sys.stderr.write("\\nloaded:" + "".join(" " + m for m in sorted({m.split(".")[0] for m in sys.modules} & watched)) + "\\n")
"""

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

    def make_refs(self, tmp, skill, refs):
        for rel, text in refs.items():
            (Path(tmp) / skill / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / skill / rel).write_text(text)

    def test_a_phrase_only_in_a_reference_file_is_listed_with_its_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"alpha": "---\nname: alpha\ndescription: Does a thing.\n---\n\n# Alpha\nSee the references.\n",
                            "beta": "---\nname: beta\ndescription: x\n---\nNothing.\n"})
            self.make_refs(tmp, "alpha", {"references/rollback.md": "# Rollback\n\nUse the Blue-green switch to roll back.\n"})
            code, out = self.run_phrase("blue green switch", folder=tmp)
            self.assertEqual((code, out["matched"], out["candidates"]), (0, 0, []))
            self.assertEqual(out["reference_matched"], 1)
            self.assertEqual([r["name"] for r in out["reference_hits"]], ["alpha"])
            self.assertEqual(out["reference_hits"][0]["match"], "references/rollback.md:3: Use the Blue-green switch to roll back.")
            text = self.text_of(tmp, "blue green switch")
            self.assertIn("No SKILL.md contains it, but 1 skill(s) hold it in their reference files", text)
            self.assertIn(":references/rollback.md:3: Use the Blue-green switch to roll back.", text)
            self.assertNotIn("No skill contains it", text)

    def test_the_nearest_list_stays_beside_reference_hits_without_repeating_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = {"alpha": "---\nname: alpha\ndescription: x\n---\nbody\n",
                      "switch-board": "---\nname: switch-board\ndescription: A switch board.\n---\nbody\n"}
            skills.update({f"filler-{i}": f"---\nname: filler-{i}\ndescription: x\n---\nNothing here {i}.\n" for i in range(10)})
            self.make(tmp, skills)
            self.make_refs(tmp, "alpha", {"references/a.md": "the blue green switch\n"})
            _, out = self.run_phrase("blue green switch", folder=tmp)
            self.assertIn("switch-board", [n["name"] for n in out["nearest"]])
            text = self.text_of(tmp, "blue green switch")
            self.assertIn("Nearest by words", text)
            self.assertIn("switch-board", text.split("Nearest by words")[1])
            self.assertNotIn("alpha", text.split("Nearest by words")[1])

    def test_reference_hits_come_after_the_skill_md_hits_and_leave_their_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"beta": "---\nname: beta\ndescription: x\n---\nThe amber lamp.\n",
                            "amber-lamp": "---\nname: amber-lamp\ndescription: x\n---\nbody\n",
                            "gamma": "---\nname: gamma\ndescription: x\n---\nbody\n",
                            "delta": "---\nname: delta\ndescription: x\n---\nAn amber lamp too.\n"})
            self.make_refs(tmp, "gamma", {"notes.md": "Light the amber lamp.\n"})
            self.make_refs(tmp, "delta", {"notes.md": "amber lamp\n"})
            _, out = self.run_phrase("amber lamp", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]], ["amber-lamp", "beta", "delta"])
            self.assertEqual([r["name"] for r in out["reference_hits"]], ["gamma"])          # delta holds it in SKILL.md: not repeated
            text = self.text_of(tmp, "amber lamp")
            self.assertLess(text.index("3. delta"), text.index("Only in reference files"))
            self.assertLess(text.index("Only in reference files"), text.index("Best match: amber-lamp"))

    def test_reference_hits_rank_by_phrases_then_files_then_name_and_five_are_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ["k1", "k2", "k3", "k4", "k5", "k6", "two-files", "both-phrases"]
            self.make(tmp, {n: f"---\nname: {n}\ndescription: x\n---\nbody\n" for n in names})
            for n in names[:6]: self.make_refs(tmp, n, {"r.md": "a quartz gauge\n"})
            self.make_refs(tmp, "two-files", {"r.md": "quartz gauge\n", "s.md": "quartz gauge\n"})
            self.make_refs(tmp, "both-phrases", {"r.md": "quartz gauge and brass valve\n"})
            _, out = self.run_phrase("quartz gauge", "brass valve", folder=tmp)
            self.assertEqual(out["reference_matched"], 8)
            self.assertEqual([r["name"] for r in out["reference_hits"]], ["both-phrases", "two-files", "k1", "k2", "k3"])

    def test_skipped_and_hidden_folders_are_not_read_as_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"alpha": "---\nname: alpha\ndescription: x\n---\nbody\n"})
            self.make_refs(tmp, "alpha", {"evals/case.md": "quartz gauge\n", ".cache/x.md": "quartz gauge\n", "tests/t.md": "quartz gauge\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp)
            self.assertEqual(out["reference_hits"], [])

    def test_word_counts_beside_a_reference_hit_count_the_reference_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"alpha": "---\nname: alpha\ndescription: x\n---\nbody\n", "beta": "---\nname: beta\ndescription: x\n---\nbody\n"})
            self.make_refs(tmp, "alpha", {"references/r.md": "the blue green switch\n"})
            _, out = self.run_phrase("blue green switch", folder=tmp)
            self.assertEqual(out["word_counts"], {"blue": 1, "green": 1, "switch": 1})
            self.assertIn("blue 1, green 1, switch 1", self.text_of(tmp, "blue green switch"))

    def test_a_large_reference_file_and_one_past_many_other_files_are_still_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"big": "---\nname: big\ndescription: x\n---\nbody\n", "many": "---\nname: many\ndescription: x\n---\nbody\n"})
            self.make_refs(tmp, "big", {"references/huge.md": ("filler line\n" * 40000) + "the quartz gauge\n"})      # about 480 KB
            self.make_refs(tmp, "many", {f"docs/a{i:03}.md": "nothing\n" for i in range(130)})
            self.make_refs(tmp, "many", {"references/z.md": "the quartz gauge\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp)
            self.assertEqual(sorted(r["name"] for r in out["reference_hits"]), ["big", "many"])

    def test_log_folders_are_not_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"alpha": "---\nname: alpha\ndescription: x\n---\nbody\n"})
            self.make_refs(tmp, "alpha", {"logs/run1.md": "quartz gauge\n", "log/x.md": "quartz gauge\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp)
            self.assertEqual(out["reference_hits"], [])

    def test_the_excerpt_is_the_line_with_the_phrase_and_shows_it_in_a_long_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"alpha": "---\nname: alpha\ndescription: x\n---\nbody\n"})
            self.make_refs(tmp, "alpha", {"rfc.txt": "Page one\n\x0cHeader two\n" + "word " * 60 + "the quartz gauge reads high\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp)
            self.assertTrue(out["reference_hits"][0]["match"].startswith("rfc.txt:3: "), out["reference_hits"][0]["match"])
            self.assertIn("quartz gauge", out["reference_hits"][0]["match"])

    def test_limit_also_caps_the_reference_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ["h1", "h2", "k1", "k2", "k3"]
            self.make(tmp, {n: f"---\nname: {n}\ndescription: x\n---\n{'quartz gauge' if n.startswith('h') else 'body'}\n" for n in names})
            for n in names[2:]: self.make_refs(tmp, n, {"r.md": "quartz gauge\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp, extra=("--limit", "1"))
            self.assertEqual(len(out["reference_hits"]), 1)

    def test_toc_json_does_not_claim_references_were_searched(self):
        _, out = self.run_phrase("contrast ratio", extra=("--toc",))
        self.assertNotIn("reference_hits", out)

    def test_json_nearest_keeps_the_reference_hits_and_the_text_does_not_repeat_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = {"alpha": "---\nname: alpha\ndescription: x\n---\nbody\n"}
            skills.update({f"filler-{i}": f"---\nname: filler-{i}\ndescription: x\n---\nNothing here {i}.\n" for i in range(10)})
            self.make(tmp, skills)
            self.make_refs(tmp, "alpha", {"references/a.md": "the blue green switch\n"})
            _, out = self.run_phrase("blue green switch", folder=tmp)
            self.assertIn("alpha", [n["name"] for n in out["nearest"]])
            text = self.text_of(tmp, "blue green switch")
            self.assertEqual(text.count("alpha/SKILL.md"), 1)

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


class SameSkillAgain(unittest.TestCase):
    """The same skill in two places (an older cached version, a user copy of a plugin skill) is one hit that names the other place;
    two different skills that share a name stay two."""

    def make(self, root, name, description, body="Steps."):
        d = Path(root) / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n")

    def run_phrase(self, *roots, phrase="crossing roads"):
        cmd = [sys.executable, str(FINDER), "--phrase", phrase, "--json", "--limit", "40"]
        for r in roots:
            cmd += ["--only", str(r)]
        out = subprocess.run(cmd, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def test_two_copies_with_one_description_are_one_hit_that_names_the_other(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.make(a, "road-skill", "Use for crossing roads safely.", "Look both ways. Version one.")
            self.make(b, "road-skill", "Use for crossing roads safely.", "Look both ways, twice. Version two.")
            res = self.run_phrase(a, b)
            self.assertEqual([c["name"] for c in res["candidates"]], ["road-skill"])
            self.assertEqual(res["matched"], 1)
            self.assertEqual(len(res["candidates"][0]["also"]), 1)

    def test_same_name_but_another_description_stays_a_separate_skill(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.make(a, "configure", "Set up the telegram bot for crossing roads.")
            self.make(b, "configure", "Set up the discord bot for crossing roads.")
            res = self.run_phrase(a, b)
            self.assertEqual([c["name"] for c in res["candidates"]], ["configure", "configure"])

    def test_the_text_output_says_where_else_the_skill_is(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.make(a, "road-skill", "Use for crossing roads safely.", "Version one.")
            self.make(b, "road-skill", "Use for crossing roads safely.", "Version two.")
            cmd = [sys.executable, str(FINDER), "--phrase", "crossing roads", "--only", str(a), "--only", str(b)]
            out = subprocess.run(cmd, capture_output=True, text=True).stdout
            self.assertIn("1 skill(s) contain it", out)
            self.assertIn("also at: only ", out)

    def write(self, folder, name, description):
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nSteps.\n")

    def test_two_different_skills_with_one_name_in_one_folder_both_show(self):
        with tempfile.TemporaryDirectory() as a:
            self.write(Path(a) / "k8s-deploy", "deploy", "Ship containers to kubernetes when crossing roads.")
            self.write(Path(a) / "netlify-deploy", "deploy", "Publish a static site to netlify when crossing roads.")
            res = self.run_phrase(a)
            self.assertEqual(sorted(Path(c["path"]).parent.name for c in res["candidates"]), ["k8s-deploy", "netlify-deploy"])

    def run_isolated(self, home, *args, config_dir=None):
        """The finder with HOME (and config_dir) as its only config dirs and no roots file, so nothing of this machine is in the result.
        It runs in an empty folder outside HOME: run in HOME, HOME/.claude/skills would be read as a project's skills too."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"} | {"HOME": str(home), "SKILL_FINDER_ROOTS": str(Path(home) / "no-roots")}
        if config_dir: env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        with tempfile.TemporaryDirectory() as cwd:
            out = subprocess.run([sys.executable, str(FINDER), *args, "--json", "--limit", "40"], capture_output=True, text=True, env=env, cwd=cwd)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def plugin(self, base, plugin, skill, description):
        (base / ".claude-plugin").mkdir(parents=True)
        (base / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": plugin}))
        self.write(base / "skills" / skill, skill, description)

    def test_two_plugins_of_one_extra_root_keep_their_same_named_skills(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "org-skills"
            self.plugin(repo / "alpha", "alpha", "git-commit", "Write commit messages with a ticket prefix when crossing roads.")
            self.plugin(repo / "beta", "beta", "git-commit", "Sign commits with gpg when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads", "--root", str(repo))
            self.assertEqual(sorted(Path(c["path"]).parts[-4] for c in res["candidates"]), ["alpha", "beta"])

    def test_two_cached_versions_of_one_plugin_are_still_one_skill(self):
        with tempfile.TemporaryDirectory() as home:
            cache = Path(home) / ".claude" / "plugins" / "cache" / "market" / "tools"
            self.plugin(cache / "1.0.0", "tools", "configure", "Set up the bot when crossing roads.")
            self.plugin(cache / "2.0.0", "tools", "configure", "Set up the bot, now with retries, when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads")
            self.assertEqual([c["name"] for c in res["candidates"]], ["configure"])

    def test_copies_of_a_plugin_without_plugin_json_are_still_one_skill(self):
        with tempfile.TemporaryDirectory() as home:
            plugins = Path(home) / ".claude" / "plugins"
            self.write(plugins / "cache" / "market" / "docs" / "1.0" / "skills" / "pdf", "pdf", "Fill pdf forms when crossing roads.")
            self.write(plugins / "cache" / "market" / "docs" / "2.0" / "skills" / "pdf", "pdf", "Fill and sign pdf forms when crossing roads.")
            self.write(plugins / "marketplaces" / "market" / "docs" / "skills" / "pdf", "pdf", "Fill, sign and merge pdf forms when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads")
            self.assertEqual([c["name"] for c in res["candidates"]], ["pdf"])

    def test_two_plugins_without_plugin_json_in_one_marketplace_keep_their_same_named_skills(self):
        with tempfile.TemporaryDirectory() as home:
            market = Path(home) / ".claude" / "plugins" / "marketplaces" / "market"
            self.write(market / "alpha" / "skills" / "configure", "configure", "Set up the telegram bot when crossing roads.")
            self.write(market / "beta" / "skills" / "configure", "configure", "Set up the discord bot when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads")
            self.assertEqual(sorted(Path(c["path"]).parts[-4] for c in res["candidates"]), ["alpha", "beta"])

    def test_one_plugin_name_in_two_marketplaces_is_two_plugins(self):
        with tempfile.TemporaryDirectory() as home:
            cache = Path(home) / ".claude" / "plugins" / "cache"
            self.plugin(cache / "east" / "tools" / "1.0", "tools", "configure", "Set up the telegram bot when crossing roads.")
            self.plugin(cache / "west" / "tools" / "1.0", "tools", "configure", "Set up the discord bot when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads")
            self.assertEqual(sorted(Path(c["path"]).parts[-6] for c in res["candidates"]), ["east", "west"])

    def test_two_different_user_skills_with_one_name_both_show(self):
        with tempfile.TemporaryDirectory() as home:
            skills = Path(home) / ".claude" / "skills"
            self.write(skills / "k8s-deploy", "deploy", "Ship containers to kubernetes when crossing roads.")
            self.write(skills / "netlify-deploy", "deploy", "Publish a static site to netlify when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads")
            self.assertEqual(sorted(Path(c["path"]).parent.name for c in res["candidates"]), ["k8s-deploy", "netlify-deploy"])

    def test_a_user_skill_in_both_config_dirs_is_still_one_skill(self):
        with tempfile.TemporaryDirectory() as home:
            self.write(Path(home) / ".claude" / "skills" / "deploy", "deploy", "Ship containers when crossing roads.")
            self.write(Path(home) / "second" / "skills" / "deploy", "deploy", "Ship containers to kubernetes when crossing roads.")
            res = self.run_isolated(home, "--phrase", "crossing roads", config_dir=Path(home) / "second")
            self.assertEqual([c["name"] for c in res["candidates"]], ["deploy"])

    def test_enable_source_can_name_part_of_the_path(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as into:
            self.write(Path(a) / "k8s-deploy", "deploy", "Ship containers to kubernetes when crossing roads.")
            self.write(Path(a) / "netlify-deploy", "deploy", "Publish a static site to netlify when crossing roads.")
            for pick, word in (("k8s-deploy", "kubernetes"), ("netlify-deploy", "netlify")):             # one of the two is the default pick
                cmd = [sys.executable, str(FINDER), "--only", a, "--enable", "deploy", "--into", into, "--source", pick]
                out = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn(word, (Path(into) / ".claude" / "skills" / "deploy" / "SKILL.md").read_text())

    def test_enable_copies_only_under_the_skills_folder(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as into:
            self.write(Path(a) / "odd", "../escaped", "Crosses roads.")
            out = subprocess.run([sys.executable, str(FINDER), "--only", a, "--enable", "../escaped", "--into", into],
                                 capture_output=True, text=True)
            self.assertFalse((Path(into) / ".claude" / "escaped").exists())
            self.assertIn("../escaped: not a plain folder name; left alone", out.stderr)

    def test_remove_deletes_only_under_the_skills_folder(self):
        with tempfile.TemporaryDirectory() as into:
            skills = Path(into) / ".claude" / "skills"
            skills.mkdir(parents=True)
            (Path(into) / ".claude" / "victim").mkdir()
            (skills / ".skill-finder.json").write_text(json.dumps({"../victim": "x"}))
            out = subprocess.run([sys.executable, str(FINDER), "--remove", "--into", into], capture_output=True, text=True)
            self.assertTrue((Path(into) / ".claude" / "victim").exists())
            self.assertIn("../victim: not a plain folder name; left alone", out.stderr)


class BestMatch(unittest.TestCase):
    """A phrase search ends with the best match: why, first lines, references, where to read. No model is called."""

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

    def tearDown(self):
        self.tmp.cleanup()

    def run_finder(self, *args):
        cmd = [sys.executable, str(FINDER), "--only", str(self.skills), "--phrase", "zebra crossing", *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_a_phrase_search_ends_with_the_best_match(self):
        text = self.run_finder().stdout
        self.assertIn("Best match: alpha", text)
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

    def test_a_body_only_hit_says_where_it_is_not(self):
        text = self.run_finder().stdout
        self.assertIn('Why: "zebra crossing" occurs 1 time in SKILL.md, not in its name or description (line 7:', text)

    def test_for_is_not_an_option(self):
        out = self.run_finder("--for", "cross a road")
        self.assertEqual(out.returncode, 2)
        self.assertIn("unrecognized arguments: --for", out.stderr)

    def test_json_carries_the_best_match(self):
        out = json.loads(self.run_finder("--json").stdout)
        self.assertEqual(out["best"]["name"], "alpha")
        self.assertEqual(len(out["best"]["lines"]), 20)
        self.assertFalse({"fit", "none", "considered", "rank"} & set(out["best"]))

    def test_several_phrases_put_the_line_after_its_own_phrase(self):
        with tempfile.TemporaryDirectory() as a:
            (Path(a) / "mixed-traffic-light").mkdir()
            (Path(a) / "mixed-traffic-light" / "SKILL.md").write_text(
                "---\nname: mixed-traffic-light\ndescription: Covers a zebra crossing too.\n---\n\n# mixed\nred light and pelican crossing\n")
            cmd = [sys.executable, str(FINDER), "--only", a, "--phrase", "pelican crossing", "--phrase", "traffic light", "--phrase", "zebra crossing"]
            why = next(ln for ln in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines() if ln.startswith("Why:"))
            self.assertIn('not in its name or description (line 7: "red light and pelican crossing"); "traffic light"', why)
            self.assertTrue(why.endswith('"zebra crossing" is in its description and 1 time in SKILL.md'), why)

    def test_the_script_imports_nothing_that_starts_a_process_or_opens_a_connection(self):
        tree = ast.parse(FINDER.read_text())
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(imported & (NO_PROCESS_OR_NETWORK | {"importlib", "shlex", "tempfile"}), imported)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertFalse({x for x in names if x in ("system", "popen", "fork", "forkpty", "__import__", "startfile")
                          or x.startswith(("execv", "execl", "spawnv", "spawnl", "posix_spawn"))})

    def test_a_search_loads_no_process_or_network_module(self):
        for args in (["--phrase", "zebra crossing"], ["--phrase", "no such words"], ["--task", "cross a road"], ["--toc"], ["--list"]):
            out = subprocess.run([sys.executable, "-c", LOADED, ",".join(NO_PROCESS_OR_NETWORK), str(FINDER), "--only", str(self.skills), *args],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stderr.splitlines()[-1], "loaded:", args)

    def test_only_enable_and_remove_write_files(self):
        tree = ast.parse(FINDER.read_text())
        writers = {"write_text", "write_bytes", "mkdir", "makedirs", "copytree", "copyfile", "copy2", "rmtree", "unlink", "rename",
                   "touch", "rmdir", "symlink_to", "hardlink_to", "chmod", "truncate"}
        def writes(node):
            for n in ast.walk(node):
                if not isinstance(n, ast.Call): continue
                f = n.func
                if isinstance(f, ast.Attribute) and (f.attr in writers or isinstance(f.value, ast.Name) and f"{f.value.id}.{f.attr}"
                                                     in ("os.remove", "os.replace", "shutil.move", "shutil.copy")): return True
                if (isinstance(f, ast.Name) and f.id == "open" or isinstance(f, ast.Attribute) and f.attr == "open") and any(
                        isinstance(m, ast.Constant) and isinstance(m.value, str) and set(m.value) & set("wax+")
                        for m in n.args[1:2] + [k.value for k in n.keywords if k.arg == "mode"]): return True
            return False
        top = [n.name if isinstance(n, ast.FunctionDef) else type(n).__name__ for n in tree.body if writes(n)]
        self.assertEqual(sorted(top), ["enable", "remove"])


if __name__ == "__main__":
    unittest.main()
