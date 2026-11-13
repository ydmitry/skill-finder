"""Golden queries for find_skills.py against a fixed folder of 18 skills (tests/fixtures/skills), no model and no machine state.

Every query is written the way SKILL.md asks: the words a skill's description would use for what it does. A skill listed
in FIRST must rank first; one in TOP3 must rank in the first three. Common-word and nonsense queries must come back with
LOW CONFIDENCE, and a clear first hit must not."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FINDER = HERE.parent / "scripts" / "find_skills.py"
FIXTURES = HERE / "fixtures" / "skills"
NO_PROCESS_OR_NETWORK = {"subprocess", "socket", "_socket", "ssl", "urllib", "http", "ctypes", "webbrowser", "pty", "socketserver",
                         "ftplib", "smtplib", "asyncio", "multiprocessing", "concurrent"}      # packages the script itself never imports
# Modules that start a process or open a connection, by full name, for what a search loads at run time: urllib.parse is not one
# (pathlib loads it on Python 3.9), urllib.request is.
STARTS_A_PROCESS_OR_CONNECTS = {"subprocess", "_posixsubprocess", "socket", "_socket", "ssl", "_ssl", "http", "urllib.request", "ftplib",
                                "smtplib", "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc", "socketserver", "webbrowser", "pty",
                                "ctypes", "asyncio.subprocess", "asyncio.base_subprocess", "multiprocessing", "_multiprocessing",
                                "concurrent.futures.process"}
# Runs the finder in this interpreter, then names the modules it had loaded that are in argv[1] or inside one of them.
LOADED = """import runpy, sys
watched = sys.argv[1].split(",")
sys.argv = sys.argv[2:]
try: runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as e:
    if e.code not in (None, 0): raise
sys.stderr.write("\\nloaded:" + "".join(" " + m for m in sorted(m for m in sys.modules if any(m == w or m.startswith(w + ".") for w in watched))) + "\\n")
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

    def test_name_beats_description_beats_body_and_phrases_take_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {
                "body-only": "---\nname: body-only\ndescription: x\n---\nMentions the quartz gauge twice: quartz gauge.\n",
                "in-desc": "---\nname: in-desc\ndescription: Reads the quartz gauge.\n---\nbody\n",
                "quartz-gauge": "---\nname: quartz-gauge\ndescription: x\n---\nbody\n",
                "both": "---\nname: both\ndescription: x\n---\nA quartz gauge and a brass valve.\n"})
            _, out = self.run_phrase("quartz gauge", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]], ["quartz-gauge", "in-desc", "body-only", "both"])
            _, out = self.run_phrase("quartz gauge", "brass valve", folder=tmp)
            self.assertEqual([c["name"] for c in out["candidates"]][:2], ["quartz-gauge", "both"])       # each phrase in turn

    def test_the_limit_cuts_the_list_and_says_how_many_matched(self):
        _, out = self.run_phrase("the", extra=("--limit", "2"))
        self.assertEqual(out["shown"], 2)
        self.assertGreater(out["matched"], 2)
        cmd = [sys.executable, str(FINDER), "--only", str(FIXTURES), "--phrase", "the", "--limit", "2"]
        text = subprocess.run(cmd, capture_output=True, text=True).stdout
        self.assertIn("the best 2 are shown", text)

    def test_ten_are_listed_unless_asked_and_the_header_says_how_to_list_more(self):
        """15 of the 18 fixture skills hold "the". A lookup lists 10, and its header says how many hold the phrase and that --limit 40
        lists more, in the plain output and the --toc one; --limit 40 lists 40 of 45, and its header points at no larger --limit."""
        def text(folder, *extra):
            cmd = [sys.executable, str(FINDER), "--only", str(folder), "--phrase", "the", *extra]
            return subprocess.run(cmd, capture_output=True, text=True).stdout
        _, out = self.run_phrase("the")
        self.assertEqual((out["matched"], out["shown"]), (15, 10))
        self.assertEqual(sum(bool(re.match(r"\d+\. ", ln)) for ln in text(FIXTURES).splitlines()), 10)
        for extra in ((), ("--toc",)):
            head = next(ln for ln in text(FIXTURES, *extra).splitlines() if "contain it" in ln)
            self.assertTrue(head.startswith("15 skill(s) contain it; the best 10 are shown"), head)
            self.assertIn("--limit 40 lists more", head)
            self.assertEqual(len([ln for ln in text(FIXTURES, *extra).splitlines() if " — " in ln]), 10 if extra else 0)
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {f"s{i:02}": f"---\nname: s{i:02}\ndescription: x\n---\nRead the quartz gauge.\n" for i in range(45)})
            _, out = self.run_phrase("the", folder=tmp, extra=("--limit", "40"))
            self.assertEqual((out["matched"], out["shown"], len(out["candidates"])), (45, 40, 40))
            for extra in ((), ("--toc",)):
                head = next(ln for ln in text(tmp, "--limit", "40", *extra).splitlines() if "contain it" in ln)
                self.assertTrue(head.startswith("45 skill(s) contain it; the best 40 are shown. A longer phrase narrows it"), head)
                self.assertNotIn("--limit", head)
            self.assertEqual(self.run_phrase("the", folder=tmp)[1]["shown"], 10)

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

    def test_a_phrase_needs_no_quotes(self):
        """`--phrase release notes` is one phrase of two words, as `--phrase "release notes"` is; each --phrase starts another. A
        lookup typed without quotes failed with 'unrecognized arguments'."""
        def run(*args):
            out = subprocess.run([sys.executable, str(FINDER), "--only", str(FIXTURES), *args], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout) if "--json" in args else out.stdout
        self.assertEqual(run("--phrase", "release", "notes"), run("--phrase", "release notes"))
        out = run("--phrase", "release", "notes", "--phrase", "changelog", "--json")
        self.assertEqual((out["phrases"], [c["name"] for c in out["candidates"]]), (["release notes", "changelog"], ["release-notes"]))
        self.assertEqual(run("--phrase", "goal", "loop", "--phrase", "pull request", "--json")["phrases"], ["goal loop", "pull request"])
        self.assertEqual(run("--phrase", "goal", "loop", "--toc", "--json")["sections"]["name"], ["goal-loop"])     # --toc stays a flag
        self.assertEqual(run("--toc", "--phrase", "goal", "loop", "--json")["sections"]["name"], ["goal-loop"])
        self.assertEqual(run("--phrase", "the", "--limit", "2", "--json")["shown"], 2)

    def test_quoted_phrases_after_one_flag_are_refused(self):
        """`--phrase "release notes" "changelog"` is two phrases given to one --phrase: joined, they were the phrase "release notes
        changelog", which no skill holds. Only plain words join; a value with a space among several says each needs its own --phrase."""
        for words in (["release notes", "changelog"], ["changelog", "release notes"], ["release", "notes", "pull request"]):
            out = subprocess.run([sys.executable, str(FINDER), "--only", str(FIXTURES), "--phrase", *words], capture_output=True, text=True)
            self.assertEqual((out.returncode, out.stdout), (1, ""), words)
            self.assertIn("each phrase needs its own --phrase", out.stderr)
        out = subprocess.run([sys.executable, str(FINDER), "--only", str(FIXTURES), "--phrase", "release notes", "--json"], capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout)["phrases"], ["release notes"])

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

    def run_isolated(self, home, *args, config_dir=None, cwd=None):
        """The finder with HOME (and config_dir) as its only config dirs and no roots file, so nothing of this machine is in the result.
        It runs in an empty folder outside HOME (or in cwd): run in HOME, HOME/.claude/skills would be read as a project's skills too."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"} | {"HOME": str(home), "SKILL_FINDER_ROOTS": str(Path(home) / "no-roots")}
        if config_dir: env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        with tempfile.TemporaryDirectory() as empty:
            out = subprocess.run([sys.executable, str(FINDER), *args, "--json", "--limit", "40"], capture_output=True, text=True, env=env,
                                 cwd=cwd or empty)
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

    def installs(self, home, records, enabled=None):
        """installed_plugins.json with these {key: [record]} and, when given, the user settings' enabledPlugins."""
        plugins = Path(home) / ".claude" / "plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        (plugins / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": records}))
        if enabled is not None: (Path(home) / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": enabled}))

    def test_a_cached_plugin_without_plugin_json_is_named_by_its_cache_folder(self):
        """cache/<market>/<plugin>/<version>/: with no plugin.json the folder names the plugin, so its install record and its
        enabledPlugins entry apply (a disabled one read 'plugin installed' under the name ?@market)."""
        with tempfile.TemporaryDirectory() as home:
            install = Path(home) / ".claude" / "plugins" / "cache" / "market" / "docs" / "1.0"
            self.write(install / "skills" / "pdf", "pdf", "Fill pdf forms when crossing roads.")
            for on, state in ((False, "plugin DISABLED"), (True, "plugin enabled")):
                self.installs(home, {"docs@market": [{"scope": "user", "installPath": str(install)}]}, {"docs@market": on})
                (c,) = self.run_isolated(home, "--phrase", "crossing roads")["candidates"]
                self.assertEqual((c["status"], c["source"]), (state, "docs@market"))

    def scoped_tools(self, home, records, user=None):
        """tools@market in the cache with these install records and user settings; returns state(cwd) -> its label there."""
        install = Path(home) / ".claude" / "plugins" / "cache" / "market" / "tools" / "1.0"
        if not install.exists(): self.plugin(install, "tools", "configure", "Set up the bot when crossing roads.")
        self.installs(home, {"tools@market": [dict(r, installPath=str(install)) for r in records]}, user or {})
        def state(cwd=None):
            return next(c["status"] for c in self.run_isolated(home, "--phrase", "crossing roads", cwd=cwd)["candidates"]
                        if c["name"] == "configure")
        return state

    @staticmethod
    def settings(folder, name, on):
        (folder / ".claude").mkdir(parents=True, exist_ok=True)
        (folder / ".claude" / name).write_text(json.dumps({"enabledPlugins": {"tools@market": on}}))

    def test_a_local_install_outside_git_loads_in_its_own_folder_only(self):
        """Claude Code applies a local or project install when the session starts in its projectPath or in the same git repo. Outside
        git that is the folder itself: a subfolder, or a sibling whose name starts the same, does not count."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            if any((d / ".git").exists() for d in (Path(top).resolve(), *Path(top).resolve().parents)):
                self.skipTest("the temp folder is in a git repo, so no folder here is outside git")
            proj = Path(top).resolve() / "app"
            for d in (proj / "sub", proj.parent / "app2"): d.mkdir(parents=True)
            self.settings(proj, "settings.json", False)
            self.settings(proj, "settings.local.json", True)                                   # the local file wins
            only = "plugin installed for app only"
            for scope in ("local", "project"):
                state = self.scoped_tools(home, [{"scope": scope, "projectPath": str(proj)}])
                self.assertEqual([state(c) for c in (None, proj, proj / "sub", proj.parent / "app2")], [only, "plugin enabled", only, only], scope)

    def test_a_local_install_loads_anywhere_in_its_git_repo(self):
        """In git the install counts anywhere under the same repo root, a linked worktree included (its .git file leads through
        commondir to the main checkout), and the local settings file is the one at that root."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            repo, wt = Path(top).resolve() / "repo", Path(top).resolve() / "repo-wt"
            (repo / ".git" / "worktrees" / "wt").mkdir(parents=True)
            (repo / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n")
            (repo / "web").mkdir()
            wt.mkdir()
            (wt / ".git").write_text(f"gitdir: {repo / '.git' / 'worktrees' / 'wt'}\n")
            state = self.scoped_tools(home, [{"scope": "local", "projectPath": str(repo / "web")}])
            self.settings(repo, "settings.local.json", True)
            self.assertEqual([state(c) for c in (None, repo, repo / "web", wt)], ["plugin installed for repo only"] + ["plugin enabled"] * 3)

    def test_the_user_and_project_settings_merge_for_every_plugin(self):
        """user settings < the launch folder's .claude/settings.json < settings.local.json, for every plugin: a project can switch a
        user plugin on or off, and when the project files say nothing a project install keeps the user's value."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as proj:
            proj = Path(proj).resolve()
            state = self.scoped_tools(home, [{"scope": "user"}], {"tools@market": False})
            self.settings(proj, "settings.local.json", True)
            self.assertEqual((state(), state(proj)), ("plugin DISABLED", "plugin enabled"))
            state = self.scoped_tools(home, [{"scope": "project", "projectPath": str(proj)}], {"tools@market": True})
            (proj / ".claude" / "settings.local.json").unlink()
            self.assertEqual(state(proj), "plugin enabled")
            self.settings(proj, "settings.json", False)
            self.assertEqual(state(proj), "plugin DISABLED")                                   # the shared project file counts

    def test_a_project_path_in_another_case_is_another_folder(self):
        """Claude Code 2.1.319 compares the paths as text: only on Windows does it retry another spelling, so on macOS, whose disks
        ignore case, a record for .../app does not load in .../App. Each spelling holds .git, so a repo the temp folder sits in does
        not join them."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            proj = Path(top).resolve() / "App"
            for d in (proj, proj.parent / "app"): (d / ".git").mkdir(parents=True, exist_ok=True)     # one folder on macOS, two on Linux
            state = self.scoped_tools(home, [{"scope": "local", "projectPath": str(proj.parent / "app")}], {"tools@market": True})
            self.assertEqual(state(proj), "plugin installed for app only")

    def test_a_subfolder_reads_its_own_settings_json_and_the_repo_roots_local_file(self):
        """Started in a repo's subfolder, a session reads .claude/settings.json there, not at the root, and settings.local.json
        both there and at the root, the root's winning."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            repo = Path(top).resolve() / "repo"
            (repo / ".git").mkdir(parents=True)
            (repo / "web").mkdir()
            state = self.scoped_tools(home, [{"scope": "user"}], {"tools@market": False})
            self.settings(repo, "settings.json", True)
            self.assertEqual((state(repo), state(repo / "web")), ("plugin enabled", "plugin DISABLED"))
            self.settings(repo / "web", "settings.local.json", True)
            self.assertEqual(state(repo / "web"), "plugin enabled")
            self.settings(repo, "settings.local.json", False)
            self.assertEqual(state(repo / "web"), "plugin DISABLED")

    def test_a_plugin_with_a_user_install_is_not_project_only(self):
        with tempfile.TemporaryDirectory() as home:
            state = self.scoped_tools(home, [{"scope": "user"}, {"scope": "local", "projectPath": "/x/app"}], {"tools@market": True})
            self.assertEqual(state(), "plugin enabled")

    def test_only_the_installed_copy_of_a_project_plugin_says_so(self):
        """A marketplace copy of a project-only plugin never loads, so it does not claim to load in that project."""
        with tempfile.TemporaryDirectory() as home:
            state = self.scoped_tools(home, [{"scope": "local", "projectPath": "/x/app"}])
            self.plugin(Path(home) / ".claude" / "plugins" / "marketplaces" / "market" / "plugins" / "tools", "tools", "extra",
                        "Only in the marketplace when crossing roads.")
            self.assertEqual(state(), "plugin installed for app only")
            extra = [c["status"] for c in self.run_isolated(home, "--phrase", "crossing roads")["candidates"] if c["name"] == "extra"]
            self.assertEqual(len(extra), 1)
            self.assertNotIn(" only", extra[0])

    def test_a_folder_that_sets_a_plugin_decides_over_an_install_for_another_project(self):
        """A session started in a folder whose own settings enable a plugin loads it even when its only install records are for
        another project: Claude Code writes one for the folder at startup. The user's settings.json alone does not."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            a, b = Path(top).resolve() / "a", Path(top).resolve() / "b"
            for d in (a, b): (d / ".git").mkdir(parents=True)
            state = self.scoped_tools(home, [{"scope": "local", "projectPath": str(a)}], {"tools@market": True})
            self.assertEqual(state(b), "plugin installed for a only")
            self.settings(b, "settings.json", True)
            self.assertEqual(state(b), "plugin enabled")
            self.settings(b, "settings.local.json", False)
            self.assertEqual(state(b), "plugin DISABLED")

    def cached(self, cfg, plugin, records):
        """plugin@market cached in config dir cfg with one skill of the same name, and these install records added to cfg's
        installed_plugins.json."""
        install = Path(cfg) / "plugins" / "cache" / "market" / plugin / "1.0"
        self.plugin(install, plugin, plugin, f"The {plugin} skill when crossing roads.")
        f = Path(cfg) / "plugins" / "installed_plugins.json"
        data = json.loads(f.read_text()) if f.exists() else {"version": 2, "plugins": {}}
        data["plugins"][f"{plugin}@market"] = [dict(r, installPath=str(install)) for r in records]
        f.write_text(json.dumps(data))

    def test_the_folder_and_the_install_records_count_only_in_the_config_dir_in_use(self):
        """A session reads one config dir, $CLAUDE_CONFIG_DIR when set, else ~/.claude: the folder's settings and the projects a plugin
        is installed for apply there. Another config dir the finder scans is labelled by its own settings.json alone."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            proj, other = Path(top).resolve() / "proj", Path(top).resolve() / "other"
            for d in (proj, other): (d / ".git").mkdir(parents=True)
            claude, second = Path(home) / ".claude", Path(home) / "second"
            self.cached(claude, "tools", [{"scope": "user"}])
            self.cached(claude, "kit", [{"scope": "local", "projectPath": str(other)}])
            (claude / "settings.json").write_text(json.dumps({"enabledPlugins": {"kit@market": True}}))
            self.cached(second, "gear", [{"scope": "user"}])
            (proj / ".claude").mkdir()
            (proj / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"tools@market": True, "gear@market": True}}))
            def states(**kw): return {c["name"]: c["status"] for c in self.run_isolated(home, "--phrase", "crossing roads", cwd=proj, **kw)["candidates"]}
            self.assertEqual(states(), {"tools": "plugin enabled", "kit": "plugin installed for other only"})
            self.assertEqual(states(config_dir=second), {"tools": "plugin installed", "kit": "plugin enabled", "gear": "plugin enabled"})

    def test_an_install_for_other_projects_names_each_repo_once(self):
        """Claude Code records the folder a session started in, so one repo gathers records for its subfolders and its linked
        worktrees. The label names each project by its repo root, once, and at most two of them."""
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            top = Path(top).resolve()
            repo, wt, here = top / "app", top / "app-fix", top / "here"
            (repo / ".git" / "worktrees" / "fix").mkdir(parents=True)
            (repo / ".git" / "worktrees" / "fix" / "commondir").write_text("../..\n")
            (repo / "src").mkdir()
            wt.mkdir()
            (wt / ".git").write_text(f"gitdir: {repo / '.git' / 'worktrees' / 'fix'}\n")
            for d in (here, top / "zeta", top / "beta", top / "gamma"): (d / ".git").mkdir(parents=True)
            records = [{"scope": "local", "projectPath": str(p)} for p in (repo, wt, repo / "src")]
            self.assertEqual(self.scoped_tools(home, records)(here), "plugin installed for app only")
            records += [{"scope": "project", "projectPath": str(top / n)} for n in ("zeta", "beta", "gamma")]
            self.assertEqual(self.scoped_tools(home, records)(here), "plugin installed for app, beta and 2 more only")

    def test_copies_of_an_installed_plugin_that_claude_code_does_not_load_are_off(self):
        """Claude Code loads an installed plugin from its installPath: another version left in the cache, or a skill folder set aside
        as <skill>.cachebak there, does not load. A cached plugin with no install record keeps its settings' state."""
        with tempfile.TemporaryDirectory() as home:
            cache = Path(home) / ".claude" / "plugins" / "cache" / "market"
            state = self.scoped_tools(home, [{"scope": "user"}], {"tools@market": True, "docs@market": True})
            self.plugin(cache / "tools" / "0.9", "tools", "legacy", "The old bot when crossing roads.")
            self.write(cache / "tools" / "1.0" / "skills" / "retired.cachebak", "retired", "Set aside when crossing roads.")
            self.plugin(cache / "docs" / "1.0", "docs", "pdf", "Fill pdf forms when crossing roads.")
            res = {c["name"]: c["status"] for c in self.run_isolated(home, "--phrase", "crossing roads")["candidates"]}
            self.assertEqual(res, {"configure": "plugin enabled", "legacy": "plugin cached, other version", "pdf": "plugin enabled"})

    def test_a_skill_at_the_root_of_its_install_folder_is_the_installed_copy(self):
        """Some plugins keep SKILL.md in the plugin folder itself, so the install folder is the skill's own folder: that copy loads,
        and a newer version left in the cache does not."""
        with tempfile.TemporaryDirectory() as home:
            cache = Path(home) / ".claude" / "plugins" / "cache" / "market" / "viz"
            for ver, words in (("1.0", "Draw pages when crossing roads."), ("2.0", "Draw pages, with charts, when crossing roads.")):
                (cache / ver / ".claude-plugin").mkdir(parents=True)
                (cache / ver / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "viz"}))
                (cache / ver / "SKILL.md").write_text(f"---\nname: viz\ndescription: {words}\n---\n\n# viz\n")
            self.installs(home, {"viz@market": [{"scope": "user", "installPath": str(cache / "1.0")}]}, {"viz@market": True})
            (c,) = self.run_isolated(home, "--phrase", "crossing roads")["candidates"]
            self.assertEqual((c["status"], Path(c["path"]).parent.name), ("plugin enabled", "1.0"))

    def test_the_copy_in_the_config_dir_in_use_is_the_one_shown(self):
        """Both config dirs can hold the same plugin. A session reads one, so its copy and its label are the hit, however much newer
        the other dir's copy is; that one is named under 'also at'."""
        with tempfile.TemporaryDirectory() as home:
            claude, second = Path(home) / ".claude", Path(home) / "second"
            self.cached(second, "tools", [{"scope": "user"}])
            (second / "settings.json").write_text(json.dumps({"enabledPlugins": {"tools@market": True}}))
            old = second / "plugins" / "cache" / "market" / "tools" / "1.0" / "skills" / "tools"
            os.utime(old, (1_000_000_000, 1_000_000_000))
            self.cached(claude, "tools", [{"scope": "user"}])                 # the same SKILL.md, newer, not enabled there
            (c,) = self.run_isolated(home, "--phrase", "crossing roads", config_dir=second)["candidates"]
            self.assertEqual(c["status"], "plugin enabled")
            self.assertTrue(c["path"].startswith(str(second)), c["path"])

    def test_settings_whose_enabled_plugins_is_not_an_object_are_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            state = self.scoped_tools(home, [{"scope": "user"}])
            for bad in (["tools@market"], None, "yes"):
                (Path(home) / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": bad}))
                self.assertEqual(state(), "plugin installed", bad)

    def test_the_projects_are_named_in_alphabetical_order_whatever_the_case(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as top:
            top = Path(top).resolve()
            for n in ("Zulu", "alpha", "here"): (top / n / ".git").mkdir(parents=True)
            records = [{"scope": "local", "projectPath": str(top / n)} for n in ("Zulu", "alpha")]
            self.assertEqual(self.scoped_tools(home, records)(top / "here"), "plugin installed for alpha, Zulu only")

    def test_list_columns_line_up_past_a_long_state(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd:
            install = Path(home) / ".claude" / "plugins" / "cache" / "market" / "tools" / "1.0"
            self.plugin(install, "tools", "configure", "Set up the bot when crossing roads.")
            project = "/work/" + "p" * 40                                      # a state longer than the 32-character column
            self.installs(home, {"tools@market": [{"scope": "local", "projectPath": project, "installPath": str(install)}]}, {})
            self.write(Path(home) / ".claude" / "skills" / "deploy", "deploy", "Ship containers when crossing roads.")
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"} | {"HOME": home, "SKILL_FINDER_ROOTS": str(Path(home) / "x")}
            rows = subprocess.run([sys.executable, str(FINDER), "--list"], capture_output=True, text=True, env=env, cwd=cwd).stdout.splitlines()
            self.assertEqual(len(rows), 2, rows)
            plugin, user = (next(r for r in rows if r.startswith(state)) for state in ("plugin installed for ", "user skill "))
            self.assertTrue(plugin.startswith(f"plugin installed for {'p' * 40} only tools@market "), plugin)
            self.assertEqual(plugin.index(" configure "), user.index(" deploy "), rows)       # the name column lines up

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
            out = subprocess.run([sys.executable, "-c", LOADED, ",".join(STARTS_A_PROCESS_OR_CONNECTS), str(FINDER), "--only", str(self.skills), *args],
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


class OwnFolder(unittest.TestCase):
    """The finder's own folder holds every example phrase (its SKILL.md, README.md, TODO.md, bench/), so a search leaves it out: the
    phrase hits, the reference hits, the best match, the nearest lists and --task. --list and a bare --toc, the inventories, still name it.
    The fixture is a copy of the finder in a skill folder, scanned as it is and through a symlink, as ~/.claude/skills/skill-finder
    often is, and run by the path it is installed at."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name).resolve()
        own = t / "clone" / "skill-finder"
        (own / "scripts").mkdir(parents=True)
        shutil.copy(FINDER, own / "scripts" / "find_skills.py")
        (own / "SKILL.md").write_text("---\nname: skill-finder\ndescription: Find the skill for a task.\n---\n\n# skill-finder\n"
                                      'Try --phrase "implementation plan", or "implementation plan" with another.\n')
        (own / "README.md").write_text("Look up the quartz gauge, or the amber lamp.\n")
        (t / "linked").mkdir()
        (t / "linked" / "skill-finder").symlink_to(own, target_is_directory=True)
        for root in (t / "clone", t / "linked"):
            for name, body in (("planner", "Write an implementation plan."), ("gauge", "Read the quartz gauge."), ("lamp-post", "A lamp."),
                               ("filler-1", "Nothing."), ("filler-2", "Nothing.")):        # five: a word one of them holds is not too common
                (root / name).mkdir()
                (root / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n\n# {name}\n{body}\n")
        self.roots = (t / "clone", t / "linked")

    def tearDown(self):
        self.tmp.cleanup()

    def run_own(self, root, *args):
        out = subprocess.run([sys.executable, str(root / "skill-finder" / "scripts" / "find_skills.py"), "--only", str(root), *args],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if "--json" in args else out.stdout

    def test_a_phrase_in_its_own_skill_md_finds_the_other_skill(self):
        for root in self.roots:
            out = self.run_own(root, "--phrase", "implementation plan", "--json")
            self.assertEqual(([c["name"] for c in out["candidates"]], out["best"]["name"]), (["planner"], "planner"), root)
            self.assertIn("Best match: planner", self.run_own(root, "--phrase", "implementation plan"))
            out = self.run_own(root, "--phrase", "implementation plan", "--toc", "--json")
            self.assertEqual(out["sections"]["body"], ["planner"], root)

    def test_its_own_reference_files_are_not_reference_hits(self):
        for root in self.roots:
            out = self.run_own(root, "--phrase", "quartz gauge", "--json")
            self.assertEqual(([c["name"] for c in out["candidates"]], out["reference_hits"]), (["gauge"], []), root)

    def test_a_miss_neither_counts_nor_lists_it(self):
        for root in self.roots:
            out = self.run_own(root, "--phrase", "amber lamp", "--json")
            self.assertEqual((out["reference_hits"], out["word_counts"]), ([], {"amber": 0, "lamp": 1}), root)
            self.assertEqual([n["name"] for n in out["nearest"]], ["lamp-post"], root)
            self.assertIn("## nearest by words (1)\nlamp-post — x\n", self.run_own(root, "--phrase", "amber lamp", "--toc"))

    def test_task_leaves_it_out(self):
        for root in self.roots:
            self.assertEqual([c["name"] for c in self.run_own(root, "--task", "quartz gauge", "--json")["candidates"]], ["gauge"], root)

    def test_list_and_toc_still_name_it(self):
        for root in self.roots:
            self.assertIn(" skill-finder ", self.run_own(root, "--list"))
            names = [e["name"] for g in self.run_own(root, "--toc", "--json")["toc"]["groups"] for e in g["entries"]]
            self.assertIn("skill-finder", names, root)
            self.assertEqual(self.run_own(root, "--toc", "skill-finder", "--json")["toc"]["name"], "skill-finder")

    def run_at(self, script, home, *args, config_dir=None, cwd=None):
        """The finder run by `script` in cwd, with `home` (and config_dir) as its only config dirs and no roots file."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"} | {"HOME": str(home), "SKILL_FINDER_ROOTS": str(home / "no-roots")}
        if config_dir: env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        out = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env, cwd=cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if "--json" in args else out.stdout

    def home_with_finder(self):
        """A HOME whose ~/.claude/skills holds the fixture's skills and the finder as a symlink to the clone."""
        home = Path(self.tmp.name).resolve() / "home"
        skills = home / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "skill-finder").symlink_to(self.roots[0] / "skill-finder", target_is_directory=True)
        for d in self.roots[0].iterdir():
            if d.name != "skill-finder": shutil.copytree(d, skills / d.name)
        return home

    def assert_left_out(self, script, home, **kw):
        out = self.run_at(script, home, "--phrase", "implementation plan", "--json", **kw)
        self.assertEqual(([c["name"] for c in out["candidates"]], out["best"]["name"]), (["planner"], "planner"), script)
        out = self.run_at(script, home, "--phrase", "quartz gauge", "--json", **kw)
        self.assertEqual(([c["name"] for c in out["candidates"]], out["reference_hits"]), (["gauge"], []), script)
        self.assertEqual([c["name"] for c in self.run_at(script, home, "--task", "implementation plan", "--json", **kw)["candidates"]],
                         ["planner"], script)
        self.assertEqual(self.run_at(script, home, "--list", **kw).count(" skill-finder "), 1, script)     # one skill, still listed

    def test_another_copy_that_wins_the_merge_is_left_out_too(self):
        """A copy in $CLAUDE_CONFIG_DIR/skills with one more line is the same skill (a user skill in both config dirs) and, in the dir a
        session reads, the copy the merge shows: the finder's own row folds into it, and the search leaves the row out all the same."""
        home = self.home_with_finder()
        work = home / ".claude-work"
        shutil.copytree(self.roots[0] / "skill-finder", work / "skills" / "skill-finder")
        with open(work / "skills" / "skill-finder" / "SKILL.md", "a") as f: f.write("One more line.\n")
        with tempfile.TemporaryDirectory() as empty:
            for script in (home / ".claude" / "skills" / "skill-finder", work / "skills" / "skill-finder"):
                self.assert_left_out(script / "scripts" / "find_skills.py", home, config_dir=work, cwd=empty)

    def home_with_installed(self, write):
        """A HOME whose ~/.claude/skills holds the fixture's skills and, at skill-finder, a separate folder that `write` fills (no
        symlink to the clone): the finder is then run from the clone, which no scan reaches."""
        home = Path(self.tmp.name).resolve() / "home"
        skills = home / ".claude" / "skills"
        skills.mkdir(parents=True)
        for d in self.roots[0].iterdir():
            if d.name != "skill-finder": shutil.copytree(d, skills / d.name)
        write(skills / "skill-finder")
        return home

    def test_a_separate_copy_with_the_same_skill_md_is_left_out(self):
        """The same SKILL.md bytes as the clone's mark a copy of the finder, even with no scripts beside it."""
        def write(d):
            d.mkdir()
            shutil.copy(self.roots[0] / "skill-finder" / "SKILL.md", d / "SKILL.md")
        home = self.home_with_installed(write)
        with tempfile.TemporaryDirectory() as empty:
            self.assert_left_out(self.roots[0] / "skill-finder" / "scripts" / "find_skills.py", home, cwd=empty)

    def test_another_version_installed_apart_from_the_clone_is_left_out(self):
        """Another version of the finder (one more line in SKILL.md) is a skill of the same name with scripts/find_skills.py beside it."""
        def write(d):
            shutil.copytree(self.roots[0] / "skill-finder", d)
            with open(d / "SKILL.md", "a") as f: f.write("One more line.\n")
        home = self.home_with_installed(write)
        with tempfile.TemporaryDirectory() as empty:
            self.assert_left_out(self.roots[0] / "skill-finder" / "scripts" / "find_skills.py", home, cwd=empty)

    def test_another_skill_that_only_shares_the_name_stays(self):
        """A skill named skill-finder with other text and no scripts/find_skills.py is not this tool: a search still finds it."""
        def write(d):
            d.mkdir()
            (d / "SKILL.md").write_text("---\nname: skill-finder\ndescription: x\n---\n\n# Another finder\nWrite an implementation plan.\n")
        home = self.home_with_installed(write)
        with tempfile.TemporaryDirectory() as empty:
            out = self.run_at(self.roots[0] / "skill-finder" / "scripts" / "find_skills.py", home, "--phrase", "implementation plan", "--json", cwd=empty)
        self.assertEqual(sorted(c["name"] for c in out["candidates"]), ["planner", "skill-finder"])

    def test_a_copy_enabled_into_a_run_folder_is_left_out_there(self):
        """--enable skill-finder --into RUN copies it unchanged: one SKILL.md, so one row, shown at the newer copy. Run in RUN, by the
        install or by the copy, the search leaves that row out whichever copy is newer."""
        home = self.home_with_finder()
        installed = home / ".claude" / "skills" / "skill-finder" / "scripts" / "find_skills.py"
        run = Path(self.tmp.name).resolve() / "run"
        run.mkdir()
        self.run_at(installed, home, "--enable", "skill-finder", "--into", str(run), cwd=run)
        copy, m = run / ".claude" / "skills" / "skill-finder", (self.roots[0] / "skill-finder").stat().st_mtime
        for stamp in (m - 1000, m + 1000):              # the copy older, then newer, than the install
            os.utime(copy, (stamp, stamp))
            for script in (installed, copy / "scripts" / "find_skills.py"):
                self.assert_left_out(script, home, cwd=run)


class Overrides(unittest.TestCase):
    """skillOverrides in the settings a session reads maps a skill's command name (for a user or project skill, its folder name) to
    "on", "name-only", "user-invocable-only" or "off" (absent:
    "on"). It hides or shortens a personal or project skill, and the label says so; plugin skills are not affected (Claude Code's docs,
    "Override skill visibility from settings"). The files and their order are the ones enabledPlugins is read from."""
    run_isolated, write, plugin, installs = SameSkillAgain.run_isolated, SameSkillAgain.write, SameSkillAgain.plugin, SameSkillAgain.installs

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name).resolve()
        self.home, self.repo = t / "home", t / "repo"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "web").mkdir()
        for name in ("deploy", "notes", "keep"):
            self.write(self.home / ".claude" / "skills" / name, name, f"The {name} skill when crossing roads.")
        self.write(self.repo / ".claude" / "skills" / "lint", "lint", "The lint skill when crossing roads.")
        install = self.home / ".claude" / "plugins" / "cache" / "market" / "tools" / "1.0"
        self.plugin(install, "tools", "configure", "Set up the bot when crossing roads.")
        self.installs(self.home, {"tools@market": [{"scope": "user", "installPath": str(install)}]})

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def settings(folder, name, overrides, **more):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps({"skillOverrides": overrides, **more}))

    def labels(self, cwd=None, **kw):
        """{name: label} of every skill, for a session started in cwd (the repo root by default)."""
        return {c["name"]: c["status"] for c in self.run_isolated(self.home, "--phrase", "crossing roads", cwd=cwd or self.repo, **kw)["candidates"]}

    def test_each_state_is_in_the_label(self):
        self.settings(self.home / ".claude", "settings.json", {"deploy": "off", "notes": "name-only", "lint": "user-invocable-only", "keep": "on"},
                      enabledPlugins={"tools@market": True})
        self.assertEqual(self.labels(), {"deploy": "user skill, off in settings", "notes": "user skill, name only in settings", "keep": "user skill",
                                         "lint": "project skill, user-invocable only in settings", "configure": "plugin enabled"})

    def test_later_settings_win_name_by_name(self):
        """The user's settings.json < the launch folder's .claude/settings.json < settings.local.json there < the one at the repo root.
        Started in a subfolder, the root's settings.json is not read."""
        user, root, web = self.home / ".claude", self.repo / ".claude", self.repo / "web" / ".claude"
        self.settings(user, "settings.json", {"deploy": "off", "notes": "off", "keep": "off", "lint": "off"})
        self.settings(root, "settings.json", {"deploy": "name-only", "lint": "on"})
        self.settings(root, "settings.local.json", {"notes": "on"})
        self.assertEqual(self.labels(), {"deploy": "user skill, name only in settings", "notes": "user skill", "keep": "user skill, off in settings",
                                         "lint": "project skill", "configure": "plugin installed"})
        self.settings(web, "settings.json", {"keep": "user-invocable-only"})
        self.settings(web, "settings.local.json", {"notes": "off", "lint": "name-only"})
        self.assertEqual(self.labels(self.repo / "web"), {"deploy": "user skill, off in settings", "notes": "user skill",
                                                          "keep": "user skill, user-invocable only in settings",
                                                          "lint": "project skill, name only in settings", "configure": "plugin installed"})

    def test_plugin_skills_are_not_affected(self):
        self.settings(self.home / ".claude", "settings.json", {"configure": "off", "tools:configure": "off"}, enabledPlugins={"tools@market": True})
        self.assertEqual(self.labels()["configure"], "plugin enabled")

    def test_a_user_or_project_skill_is_keyed_by_its_folder_name(self):
        """Claude Code keys skillOverrides on the command name, which for a user or project skill is its folder name (the /skills menu
        saves the entry under it); a frontmatter name that differs is what the menu shows. An entry under the folder name applies, one
        under the frontmatter name does not."""
        skills, project = self.home / ".claude" / "skills", self.repo / ".claude" / "skills"
        self.write(skills / "ship-it", "release-tool", "The release tool when crossing roads.")
        self.write(skills / "jot-down", "notes-tool", "The notes tool when crossing roads.")
        self.write(project / "check-style", "style-guard", "The style guard when crossing roads.")
        self.write(project / "fmt", "formatter", "The formatter when crossing roads.")
        self.settings(self.home / ".claude", "settings.json", {"ship-it": "off", "notes-tool": "off"})
        self.settings(self.repo / ".claude", "settings.json", {"check-style": "user-invocable-only", "formatter": "off", "release-tool": "on"})
        labels = self.labels()
        self.assertEqual({n: labels[n] for n in ("release-tool", "notes-tool", "style-guard", "formatter")},
                         {"release-tool": "user skill, off in settings", "notes-tool": "user skill",
                          "style-guard": "project skill, user-invocable only in settings", "formatter": "project skill"})

    def enable(self, *args):
        """The lines --enable prints, run with HOME as the only config dir from an empty folder outside the repo."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"} | {"HOME": str(self.home), "SKILL_FINDER_ROOTS": str(self.home / "no-roots")}
        with tempfile.TemporaryDirectory() as empty:
            out = subprocess.run([sys.executable, str(FINDER), "--enable", *args], capture_output=True, text=True, env=env, cwd=empty)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.splitlines()

    def test_enable_warns_when_settings_hide_the_copy(self):
        """The copy is a project skill in DIR/.claude/skills/<name>, so skillOverrides "off" or "user-invocable-only" for that folder name,
        in a file a session started in DIR reads, keeps Claude from invoking it. The last file to name it decides; "name-only" leaves
        the copy to Claude, and a file elsewhere does not count."""
        run = self.repo / "web"
        cases = ((self.home / ".claude", "settings.json", "off"), (run / ".claude", "settings.json", "user-invocable-only"),
                 (run / ".claude", "settings.local.json", "off"), (self.repo / ".claude", "settings.local.json", "user-invocable-only"))
        for folder, name, state in cases:
            self.settings(folder, name, {"configure": state})
            lines = self.enable("configure", "--into", str(run))
            self.assertTrue(lines[0].startswith("enabled configure  "), lines)
            self.assertEqual(lines[1:], [f'  WARNING: skillOverrides sets configure to "{state}" in {folder / name}; Claude cannot invoke '
                                         f'the copy in a session started in {run}'], (folder, name))
            (folder / name).unlink()
        self.settings(run / ".claude", "settings.json", {"configure": "off"})
        self.settings(run / ".claude", "settings.local.json", {"configure": "name-only"})         # later, so it decides
        self.settings(self.home / "elsewhere" / ".claude", "settings.json", {"configure": "off"})
        self.assertEqual(len(self.enable("configure", "--into", str(run))), 1)

    def test_enable_warns_when_a_user_skill_of_that_name_runs_instead(self):
        """Personal beats project: with a user skill in a folder of the copy's name, a session started in DIR runs the user skill. The
        folder decides, whatever that skill's frontmatter name; a copy of that same user skill gets no such warning."""
        self.write(self.home / ".claude" / "skills" / "configure", "setup-helper", "Another bot setup when crossing roads.")
        run = self.repo / "web"
        lines = self.enable("configure", "--into", str(run))
        self.assertTrue(lines[0].startswith("enabled configure  (plugin installed; tools@market) -> "), lines)
        self.assertEqual(lines[1:], [f"  WARNING: a user skill of that name is at {self.home / '.claude' / 'skills' / 'configure'}; a session "
                                     f"started in {run} runs it, not the copy"])
        self.assertEqual(len(self.enable("deploy", "--into", str(run))), 1)

    def test_a_value_that_is_not_an_object_or_not_a_state_changes_nothing(self):
        for bad in (["deploy"], "off", None, 3):
            self.settings(self.home / ".claude", "settings.json", bad)
            self.assertEqual(self.labels()["deploy"], "user skill", bad)
        self.settings(self.home / ".claude", "settings.json", {"deploy": "hidden", "notes": ["off"], "keep": None, "lint": {"off": 1}})
        self.assertEqual(self.labels(), {"deploy": "user skill", "notes": "user skill", "keep": "user skill", "lint": "project skill",
                                         "configure": "plugin installed"})
        self.settings(self.home / ".claude", "settings.json", {"deploy": "off"})
        self.settings(self.repo / ".claude", "settings.json", "on")                  # a folder file that is unusable leaves the user's value
        self.assertEqual(self.labels()["deploy"], "user skill, off in settings")

    def test_a_later_file_with_a_value_that_is_not_a_state_leaves_the_earlier_one(self):
        """Claude Code's schema takes on, name-only, user-invocable-only and off, so another value never takes effect: a later file's
        "hidden", null, "OFF" or ["on"] does not replace an earlier file's state, whether the earlier file is the user's or the folder's.
        Such a file fails the schema, so its valid entries ("lint": "off") do not count either."""
        self.settings(self.home / ".claude", "settings.json", {"deploy": "off", "notes": "name-only", "keep": "user-invocable-only"})
        self.settings(self.repo / ".claude", "settings.json", {"deploy": "hidden", "notes": None, "keep": "OFF", "lint": "off"})
        self.settings(self.repo / ".claude", "settings.local.json", {"lint": ["on"]})
        self.assertEqual(self.labels(), {"deploy": "user skill, off in settings", "notes": "user skill, name only in settings",
                                         "keep": "user skill, user-invocable only in settings", "lint": "project skill",
                                         "configure": "plugin installed"})

    def test_a_file_that_fails_the_schema_adds_nothing(self):
        """Claude Code skips a settings file whole when it fails its schema, not just the invalid entry: a skillOverrides value that is
        not one of the four states takes out the file's other overrides and its enabledPlugins, and an enabledPlugins that is not an
        object takes out its skillOverrides."""
        self.settings(self.home / ".claude", "settings.json", {"deploy": "off"})
        self.settings(self.repo / ".claude", "settings.json", {"deploy": "hidden", "lint": "user-invocable-only"},
                      enabledPlugins={"tools@market": True})
        self.assertEqual(self.labels(), {"deploy": "user skill, off in settings", "notes": "user skill", "keep": "user skill",
                                         "lint": "project skill", "configure": "plugin installed"})
        self.settings(self.repo / ".claude", "settings.json", {"lint": "off"}, enabledPlugins=["tools@market"])
        self.assertEqual(self.labels()["lint"], "project skill")
        self.settings(self.repo / ".claude", "settings.json", {"lint": "off"}, enabledPlugins={"tools@market": True})     # the same file, valid
        self.assertEqual((self.labels()["lint"], self.labels()["configure"]), ("project skill, off in settings", "plugin enabled"))

    def test_an_enabled_plugins_value_other_than_true_false_or_versions_fails_the_file(self):
        """Claude Code's schema takes true, false or a list of version constraints for a plugin; any other value fails the file whole,
        as an invalid skillOverrides state does: neither key of that file counts. A list of versions is valid and enables the plugin."""
        self.settings(self.home / ".claude", "settings.json", {"deploy": "off"})
        for bad in ("yes", 1, None, {"version": "1.0"}, [1], "true"):
            self.settings(self.repo / ".claude", "settings.json", {"deploy": "on", "lint": "off"}, enabledPlugins={"tools@market": bad})
            labels = self.labels()
            self.assertEqual((labels["deploy"], labels["lint"], labels["configure"]), ("user skill, off in settings", "project skill",
                                                                                      "plugin installed"), bad)
        for versions in (["^1.0"], []):                  # any list enables the plugin, an empty one too
            self.settings(self.repo / ".claude", "settings.json", {"lint": "off"}, enabledPlugins={"tools@market": versions})
            self.assertEqual((self.labels()["lint"], self.labels()["configure"]), ("project skill, off in settings", "plugin enabled"), versions)

    def test_another_config_dir_labels_its_user_skills_by_its_own_settings(self):
        """A session reads one config dir: its settings.json and the folder's files label its user skills and the project's. Another
        config dir the finder scans labels its own user skills by its own settings.json alone, as it labels its plugins."""
        second = self.home / "second"
        self.write(second / "skills" / "draft", "draft", "The draft skill when crossing roads.")
        self.settings(second, "settings.json", {"lint": "off", "draft": "name-only", "deploy": "on"})
        self.settings(self.home / ".claude", "settings.json", {"lint": "name-only", "deploy": "off", "draft": "off"})
        self.settings(self.repo / ".claude", "settings.json", {"keep": "off", "draft": "user-invocable-only"})
        self.assertEqual(self.labels(config_dir=second), {"draft": "user skill, user-invocable only in settings",
                                                          "lint": "project skill, off in settings", "deploy": "user skill, off in settings",
                                                          "notes": "user skill", "keep": "user skill", "configure": "plugin installed"})


if __name__ == "__main__":
    unittest.main()
