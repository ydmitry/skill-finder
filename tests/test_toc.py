"""--toc: tables of contents of the skills on disk (all skills, one folder, one skill, one skill's files), and a phrase search printed
as a table. No model and no machine state: the 18 fixture skills plus temporary skill folders the tests write."""
import contextlib
import importlib.util
import io
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


def run(*args, env=None):
    out = subprocess.run([sys.executable, str(FINDER), *args], capture_output=True, text=True, env={**os.environ, **(env or {})})
    return out.returncode, out.stdout, out.stderr


def toc(*args, folder=FIXTURES):
    return run("--only", str(folder), "--toc", *args)


def make(root, name, description="Does a thing.", body="# {name}\n"):
    d = Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n" + body.format(name=name))
    return d


def load_module():
    spec = importlib.util.spec_from_file_location("find_skills_under_test", FINDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def closing_line(script, home=None):
    """The last line of a phrase table that shows rows, for a script run by `script` (the home folder written ~)."""
    p = str(script)
    home = (home if home is not None else os.path.expanduser("~")).rstrip("/")
    if home and p.startswith(home + "/"):
        p = "~" + p[len(home):]
    return (f'Open the one that fits: python3 {p} --toc "<name>" prints its path and sections. '
            "None fits: search other words, or --toc for the whole table.")


class Outline(unittest.TestCase):
    def test_goal_loop_outline_is_its_one_header(self):
        code, out, _ = toc("goal-loop", "--json")
        t = json.loads(out)["toc"]
        self.assertEqual(code, 0)
        self.assertEqual(t["headers"], [{"line": 6, "level": 1, "text": "goal-loop"}])
        self.assertEqual((t["scope"], t["level"], t["kind"], t["name"]), ("goal-loop", "skill", "headers", "goal-loop"))
        self.assertTrue(t["path"].endswith("goal-loop/SKILL.md"), t["path"])

    def test_outline_lines_point_at_header_lines(self):
        body = "# Top\n" + "text\n" * 6 + "## When to use\nx\n### 1. Read\n#### too deep\n## Steps ##\n"
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "outlined", "Does it. More.", body)
            _, out, _ = toc("outlined", "--json", folder=tmp)
            t = json.loads(out)["toc"]
            self.assertEqual([(h["line"], h["level"], h["text"]) for h in t["headers"]],
                             [(6, 1, "Top"), (13, 2, "When to use"), (15, 3, "1. Read"), (17, 2, "Steps")])
            lines = (Path(tmp) / "outlined" / "SKILL.md").read_text().split("\n")
            self.assertTrue(all(lines[h["line"] - 1].lstrip("#").strip().startswith(h["text"]) for h in t["headers"]))
            _, out, _ = toc("outlined", folder=tmp)
            rows = out.splitlines()
            self.assertIn("  13: ## When to use", rows)
            self.assertIn("   6: # Top", rows)
            self.assertTrue(rows[-1].startswith("Read a section: Read "), rows[-1])
            self.assertEqual(rows[-1], "Read a section: Read the path above with offset <line>; the whole file: Read the path above.")

    def test_default_kind_for_a_skill_is_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "plain", "Does a plain thing. Then more.", "# Plain\n## Step\n")
            _, out, _ = toc("plain", folder=tmp)
            rows = out.splitlines()
            self.assertTrue(rows[0].startswith("plain  " + str(Path(tmp) / "plain" / "SKILL.md") + "  ("), rows[0])
            self.assertIn(" bytes)", rows[0])
            self.assertEqual(rows[1], "Does a plain thing.")
            self.assertEqual(rows[2:4], ["   6: # Plain", "   7: ## Step"])

    def test_fenced_and_frontmatter_hashes_are_not_headers(self):
        text = "---\nname: fenced\n# a yaml comment\ndescription: Does it.\n---\n\n```sh\n# not a header\n```\n~~~\n## nor this\n~~~\n## Real\n"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fenced").mkdir()
            (Path(tmp) / "fenced" / "SKILL.md").write_text(text)
            _, out, _ = toc("fenced", "--json", folder=tmp)
            self.assertEqual(json.loads(out)["toc"]["headers"], [{"line": 13, "level": 2, "text": "Real"}])

    def test_longer_fence_is_closed_only_by_an_equal_or_longer_one(self):
        text = "---\nname: nested\ndescription: Does it.\n---\n\n````markdown\n```sh\n## inside\n```\n## still inside\n````\n## Real\n"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "nested").mkdir()
            (Path(tmp) / "nested" / "SKILL.md").write_text(text)
            _, out, _ = toc("nested", "--json", folder=tmp)
            self.assertEqual([h["text"] for h in json.loads(out)["toc"]["headers"]], ["Real"])

    def test_skill_without_headers_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "bare", "Does it.", "Just text.\nMore text.\n")
            _, out, _ = toc("bare", folder=tmp)
            self.assertIn("no headers; 7 lines", out)
            _, out, _ = toc("bare", "--json", folder=tmp)
            self.assertEqual(json.loads(out)["toc"]["headers"], [])

    def test_a_skill_over_300_kb_has_no_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "huge", "Does it.", "# Huge\n" + "x" * 300_100 + "\n")
            _, out, _ = toc("huge", folder=tmp)
            self.assertIn("(file too large for an outline)", out)

    def test_headers_kind_for_every_skill(self):
        _, out, _ = toc("--kind", "headers")
        rows = [ln for ln in out.splitlines() if ": (no H2) " in ln]
        self.assertEqual(len(rows), 18)
        self.assertIn("goal-loop: (no H2) goal-loop", rows)
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "with-h2", "Does it.", "# T\n## A\n### sub\n## B\n")
            _, out, _ = toc("--kind", "headers", folder=tmp)
            self.assertIn("with-h2: A | B", out.splitlines())

    def test_long_header_row_is_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "wide", "Does it.", "# T\n" + "".join(f"## Header number {i:02d} xx\n" for i in range(40)))
            _, out, _ = toc("--kind", "headers", folder=tmp)
            row = next(ln for ln in out.splitlines() if ln.startswith("wide: "))
            self.assertEqual(len(row), 160)
            self.assertTrue(row.endswith("…"))


class Groups(unittest.TestCase):
    def home_with_plugins(self, tmp):
        cfg = Path(tmp) / ".claude"
        make(cfg / "plugins" / "cache" / "mk" / "plug-a" / "abc123" / "skills", "alpha-skill")
        make(cfg / "plugins" / "cache" / "mk" / "plug-b" / "abc123" / "skills", "beta-skill")
        make(cfg / "plugins" / "marketplaces" / "mk2" / "plugins" / "plug-c" / "skills", "gamma-skill")
        make(cfg / "skills", "user-skill")
        return dict(HOME=tmp, CLAUDE_CONFIG_DIR="")

    def test_plugin_without_manifest_is_grouped_by_its_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.home_with_plugins(tmp)
            _, out, _ = run("--toc", env=env)
            heads = [ln for ln in out.splitlines() if ln.startswith("## ")]
            for h in ("## plug-a@mk (1)", "## plug-b@mk (1)", "## plug-c@mk2 (1)"):
                self.assertIn(h, heads)
            self.assertFalse([h for h in heads if h.startswith("## ?")], heads)
            code, out, _ = run("--toc", "plug-a@mk", env=env)
            self.assertEqual(code, 0)
            self.assertIn("alpha-skill", out)
            self.assertNotIn("beta-skill", out)

    def test_groups_print_user_first_then_plugins_by_label_and_names_sort_without_case(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            entries = []
            for i, (name, source, plugin, rank) in enumerate((("zed", "p@m", "p", 1), ("Beta", "user", None, 0), ("alpha", "user", None, 0),
                                                              ("a1", "a@m", "a", 1), ("r1", "root /x/rr", None, 0))):
                d = make(tmp, name)
                os.utime(d, (1000 + 100 * i, 1000 + 100 * i))        # newest last: an mtime order would differ from the fixed one
                entries.append(dict(name=name, description="Does it.", dir=d, source=source, status="plugin enabled", rank=rank, plugin=plugin, also=[]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.toc(list(reversed(entries)), "all", "names", False)
            lines = buf.getvalue().splitlines()
            self.assertEqual([ln.split(" (")[0] for ln in lines if ln.startswith("## ")], ["## user", "## rr", "## a", "## p"])
            self.assertEqual(lines[2:4], ["alpha", "Beta"])

    def test_filesystem_root_is_a_path_prefix(self):
        code, out, _ = toc("/")
        self.assertEqual(code, 0)
        self.assertIn("accessibility", out)


class Files(unittest.TestCase):
    def skill_with(self, tmp, name, files):
        d = make(tmp, name, "Has files.")
        for rel, text in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        return d

    def files_json(self, tmp, name):
        code, out, err = toc(name, "--kind", "files", "--json", folder=tmp)
        self.assertEqual(code, 0, err)
        return json.loads(out)["toc"]

    def test_files_kind_lists_skill_md_first_then_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.skill_with(tmp, "filed", {"scripts/x.py": "print(1)\n", "references/b.md": "# Bee\nmore\n", "references/a.md": "\n\n## Ay thing\n"})
            t = self.files_json(tmp, "filed")
            self.assertEqual([f["path"] for f in t["files"]], ["SKILL.md", "references/a.md", "references/b.md", "scripts/x.py"])
            by = {f["path"]: f for f in t["files"]}
            self.assertEqual((by["references/a.md"]["first"], by["references/b.md"]["first"], by["scripts/x.py"]["first"]), ("Ay thing", "Bee", ""))
            self.assertEqual(by["SKILL.md"]["first"], "filed")                  # the first line after the frontmatter, not "---"
            self.assertEqual(by["scripts/x.py"]["bytes"], 9)
            self.assertEqual((t["more_files"], t["kind"], t["level"]), (0, "files", "skill"))
            _, out, _ = toc("filed", "--kind", "files", folder=tmp)
            rows = out.splitlines()
            self.assertEqual(rows[2], "references/a.md  (14)  Ay thing")
            self.assertEqual(rows[4], "scripts/x.py  (9)")
            self.assertTrue(rows[0].startswith("filed  ") and rows[0].endswith("(4 files)"), rows[0])

    def test_files_over_the_cap_say_more(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.skill_with(tmp, "many", {f"data/f{i:02d}.txt": f"line {i}\n" for i in range(69)})            # 69 + SKILL.md = 70
            t = self.files_json(tmp, "many")
            self.assertEqual((len(t["files"]), t["more_files"]), (60, 10))
            self.assertEqual(t["files"][0]["path"], "SKILL.md")
            _, out, _ = toc("many", "--kind", "files", folder=tmp)
            self.assertEqual(len(out.splitlines()), 1 + 60 + 1)
            self.assertTrue(out.rstrip().endswith("+10 more files"), out[-80:])

    def test_symlinked_skill_lists_the_target_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = self.skill_with(Path(tmp) / "elsewhere", "linked", {"references/r.md": "# R\n", "run.sh": "echo\n"})
            (Path(tmp) / "with-link").mkdir()
            (Path(tmp) / "with-link" / "linked").symlink_to(real, target_is_directory=True)
            self.skill_with(Path(tmp) / "with-copy", "linked", {"references/r.md": "# R\n", "run.sh": "echo\n"})
            lists = []
            for root in ("with-link", "with-copy"):
                code, out, err = toc("linked", "--kind", "files", "--json", folder=Path(tmp) / root)
                self.assertEqual(code, 0, err)
                lists.append(json.loads(out)["toc"]["files"])
            self.assertEqual([f["path"] for f in lists[0]], ["SKILL.md", "references/r.md", "run.sh"])
            self.assertEqual(lists[0], lists[1])

    def test_files_skip_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.skill_with(tmp, "skipper", {"node_modules/x.js": "1", ".cache/y": "2", "__pycache__/z.pyc": "3", ".venv/w": "4", ".git/config": "5",
                                             ".hidden": "6", "tests/t.py": "7", "fixtures/f.txt": "8"})
            paths = [f["path"] for f in self.files_json(tmp, "skipper")["files"]]
            self.assertEqual(paths, ["SKILL.md", "fixtures/f.txt", "tests/t.py"])

    def test_files_kind_for_a_table_exits_1(self):
        code, out, err = toc("--kind", "files")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("--kind files needs one skill: --toc <skill>", err)
        code, _, err = toc("skills/", "--kind", "files")
        self.assertEqual(code, 1)
        self.assertIn("--kind files needs one skill", err)

    def test_head_line_counts_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.skill_with(tmp, "three", {"a.md": "# A\n", "b.md": "# B\n"})
            _, out, _ = toc("three", folder=tmp)
            self.assertIn("2 more files: --kind files)", out.splitlines()[0])
            self.skill_with(tmp, "one", {})
            _, out, _ = toc("one", folder=tmp)
            self.assertNotIn("more files", out.splitlines()[0])


class PhraseToc(unittest.TestCase):
    def phrase(self, *args, folder=FIXTURES):
        return run("--only", str(folder), "--phrase", *args)

    def test_phrase_toc_name_section(self):
        code, out, _ = self.phrase("goal loop", "--toc")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith('phrase search: "goal loop" in the SKILL.md of 18 skills on disk'), lines[0])
        self.assertIn("## phrase in the name (1)", lines)
        row = lines[lines.index("## phrase in the name (1)") + 1]
        self.assertTrue(row.startswith("goal-loop — Run a coding agent headless") and row.endswith("  :6"), row)
        self.assertNotIn("Best match", out)
        self.assertNotIn("Why:", out)
        self.assertEqual(lines[-1], closing_line(FINDER))

    def test_phrase_toc_description_rows_have_no_line(self):
        _, out, _ = self.phrase("pull request", "--toc")
        lines = out.splitlines()
        at = lines.index("## phrase in the description (3)")
        rows = lines[at + 1:at + 4]
        self.assertEqual([r.split(" — ")[0] for r in rows], ["playwright-live", "pr-review", "release-notes"])
        self.assertFalse(any(re.search(r":\d+$", r) for r in rows), rows)
        self.assertEqual([ln for ln in lines if ln.startswith("## ")], ["## phrase in the description (3)"])

    def test_phrase_toc_body_section(self):
        _, out, _ = self.phrase("contrast ratio", "--toc")                          # in a description and in the body: the description section
        self.assertIn("## phrase in the description (1)", out)
        self.assertTrue(any(ln.startswith("accessibility — ") and ln.endswith("  :8") for ln in out.splitlines()), out)
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "alpha-skill", "Does a thing.", "# Alpha\nFollow the zebra crossing protocol.\n")
            make(tmp, "beta-skill", "Reads the zebra crossing.", "# Beta\n")
            make(tmp, "zebra-crossing", "Name hit.", "# Z\n")
            _, out, _ = self.phrase("zebra crossing", "--toc", folder=tmp)
            lines = out.splitlines()
            self.assertEqual([ln for ln in lines if ln.startswith("## ")],
                             ["## phrase in the name (1)", "## phrase in the description (1)", "## phrase in the body (1)"])
            self.assertEqual(lines[lines.index("## phrase in the body (1)") + 1], "alpha-skill — Does a thing.  :7")

    def test_phrase_without_toc_is_unchanged(self):
        _, out, _ = self.phrase("goal loop")
        self.assertIn("Best match:", out)
        self.assertNotIn("## phrase in", out)
        self.assertNotIn("Open the one that fits", out)

    def test_phrase_toc_miss_prints_nearest_section_only(self):
        code, out, _ = self.phrase("ratio contrast", "--toc")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertIn("Skills holding each word: ratio 1, contrast 1. A word held by none is not how any skill says it.", lines)
        self.assertEqual([ln for ln in lines if ln.startswith("## ")], ["## nearest by words (1)"])
        self.assertEqual(lines[lines.index("## nearest by words (1)") + 1].split(" — ")[0], "accessibility")
        self.assertNotIn("Nearest by words,", out)
        self.assertEqual(lines[-1], closing_line(FINDER))

    def test_phrase_toc_miss_with_no_near_skill(self):
        _, out, _ = self.phrase("xyzzy plugh", "--toc")
        self.assertIn("No skill holds any of these words either.", out)
        self.assertNotIn("## ", out)
        self.assertEqual(out.splitlines()[-1], "Search other words, or --toc for the whole table.")

    def last_line(self, script, *args, home=None, cwd=None):
        env = {**os.environ, **({"HOME": str(home)} if home is not None else {})}
        out = subprocess.run([sys.executable, str(script), "--only", str(FIXTURES), "--phrase", "goal loop", "--toc", *args],
                             capture_output=True, text=True, env=env, cwd=cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.splitlines()[-1]

    def test_closing_line_names_the_toc_command_with_the_script_as_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / "work").mkdir()
            (home / "work" / "finder").symlink_to(HERE.parent)                     # the repo as the user's home reaches it
            real = home / "work" / "finder" / "scripts" / "find_skills.py"
            self.assertEqual(self.last_line(real, home=home),
                             'Open the one that fits: python3 ~/work/finder/scripts/find_skills.py --toc "<name>" '
                             "prints its path and sections. None fits: search other words, or --toc for the whole table.")

    def test_closing_line_keeps_a_symlinked_path_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / "skills").mkdir()
            (home / "skills" / "skill-finder").symlink_to(HERE.parent)             # like ~/.claude/skills/skill-finder -> the repo
            line = self.last_line(home / "skills" / "skill-finder" / "scripts" / "find_skills.py", home=home)
            self.assertIn(' python3 ~/skills/skill-finder/scripts/find_skills.py --toc "<name>" ', line)
            self.assertNotIn(str(HERE.parent), line)

    def test_closing_line_outside_home_stays_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = self.last_line(FINDER, home=tmp)
            self.assertEqual(line, closing_line(FINDER, home=tmp))
            self.assertIn(f" python3 {FINDER} --toc ", line)
            self.assertNotIn("~", line)

    def test_closing_line_for_a_relative_run_is_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = self.last_line("find_skills.py", home=tmp, cwd=FINDER.parent)
            self.assertIn(f" python3 {FINDER} --toc ", line)

    def test_closing_line_home_prefix_is_a_folder_prefix(self):
        mod = load_module()
        self.assertEqual(mod.invoked_script("/Users/al/work/f.py", home="/Users/al"), "~/work/f.py")
        self.assertEqual(mod.invoked_script("/Users/al/work/f.py", home="/Users/al/"), "~/work/f.py")
        self.assertEqual(mod.invoked_script("/Users/alice/f.py", home="/Users/al"), "/Users/alice/f.py")
        self.assertEqual(mod.invoked_script("/opt/f.py", home="/"), "/opt/f.py")
        self.assertEqual(mod.invoked_script("/opt/f.py", home=""), "/opt/f.py")

    def test_closing_line_when_imported_names_the_loaded_file(self):
        mod = load_module()                                                         # nothing was run by a path: __file__ is the module's own
        self.assertEqual(mod.invoked_script(home="/nowhere"), str(FINDER))
        self.assertEqual(mod.invoked_script(home=str(FINDER.parent.parent)), "~/scripts/find_skills.py")

    def test_phrase_without_rows_has_no_toc_command(self):
        _, out, _ = self.phrase("xyzzy plugh", "--toc")
        self.assertNotIn("python3", out)

    def test_phrase_toc_json_sections(self):
        _, out, _ = self.phrase("pull request", "--toc", "--json")
        o = json.loads(out)
        self.assertNotIn("best", o)
        names = [c["name"] for c in o["candidates"]]
        s = o["sections"]
        self.assertEqual((s["name"], s["body"]), ([], []))
        self.assertEqual(s["description"], names)
        _, out, _ = self.phrase("goal loop", "--toc", "--json")
        self.assertEqual(json.loads(out)["sections"], {"name": ["goal-loop"], "description": [], "body": []})
        _, out, _ = self.phrase("ratio contrast", "--toc", "--json")
        o = json.loads(out)
        self.assertEqual(o["sections"], {"name": [], "description": [], "body": []})
        self.assertIn("nearest", o)

    def test_phrase_toc_is_capped_by_limit(self):
        _, out, _ = self.phrase("the", "--toc", "--limit", "2")
        rows = [ln for ln in out.splitlines() if " — " in ln]
        self.assertEqual(len(rows), 2)
        self.assertIn("the best 2 are shown", out)

    def test_phrase_toc_with_what_exits_1(self):
        code, _, err = self.phrase("goal loop", "--toc", "user")
        self.assertEqual(code, 1)
        self.assertIn("--phrase --toc takes no WHAT", err)

    def test_phrase_with_kind_exits_1(self):
        for extra in (("--toc", "--kind", "names"), ("--kind", "names")):
            code, _, err = self.phrase("goal loop", *extra)
            self.assertEqual(code, 1, extra)
            self.assertIn("--kind goes with --toc alone", err)


class Tables(unittest.TestCase):
    def skill_lines(self, text):
        return [ln for ln in text.splitlines() if " — " in ln and not ln.startswith(("table of contents", "Narrow"))]

    def test_every_skill_one_line_each(self):
        code, out, _ = toc()
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("table of contents: 18 skills in 1 folder"), lines[0])
        self.assertEqual(lines[1], "## skills (18)")
        self.assertEqual(len(lines[2:20]), 18)
        self.assertTrue(all(" — " in ln for ln in lines[2:20]), lines[2:20])
        self.assertTrue(lines[2].startswith("accessibility — Accessibility checks for web pages"), lines[2])
        self.assertTrue(lines[-1].startswith("Narrow: --toc <folder>"), lines[-1])

    def test_sentence_is_first_sentence_at_most_120_chars(self):
        _, out, _ = toc("--json")
        entries = json.loads(out)["toc"]["groups"][0]["entries"]
        self.assertTrue(all(len(e["sentence"]) <= 120 for e in entries))
        by = {e["name"]: e["sentence"] for e in entries}
        self.assertTrue(by["goal-loop"].endswith("or a budget ends."), by["goal-loop"])
        self.assertNotIn("Use for a task", by["goal-loop"])

    def test_sentence_without_punctuation_is_cut_at_a_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "long-one", " ".join(["wordy"] * 60))
            _, out, _ = toc("--json", folder=tmp)
            s = json.loads(out)["toc"]["groups"][0]["entries"][0]["sentence"]
            self.assertTrue(s.endswith("…"), s)
            self.assertLessEqual(len(s), 120)
            self.assertTrue(all(w == "wordy" for w in s[:-1].split()), s)           # no cut mid-word
            make(tmp, "short-one", "Use when X, Y, Z")
            _, out, _ = toc("--json", folder=tmp)
            by = {e["name"]: e["sentence"] for e in json.loads(out)["toc"]["groups"][0]["entries"]}
            self.assertEqual(by["short-one"], "Use when X, Y, Z")

    def test_abbreviations_do_not_end_the_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, "abbr", "Use for a PR, e.g. a hotfix. Then more.")
            make(tmp, "abbr2", "Compare A vs. B and so on. Then more.")
            make(tmp, "abbr3", "Lists files, etc. Capital after it. Then more.")
            _, out, _ = toc("--json", folder=tmp)
            by = {e["name"]: e["sentence"] for e in json.loads(out)["toc"]["groups"][0]["entries"]}
            self.assertEqual(by["abbr"], "Use for a PR, e.g. a hotfix.")
            self.assertEqual(by["abbr2"], "Compare A vs. B and so on.")
            self.assertEqual(by["abbr3"], "Lists files, etc. Capital after it.")

    def test_names_kind_prints_names_only(self):
        code, out, _ = toc("--kind", "names")
        self.assertEqual(code, 0)
        self.assertNotIn(" — ", "\n".join(out.splitlines()[1:-1]))
        self.assertIn("\ngoal-loop\n", out)

    def test_description_kind_prints_whole_description(self):
        _, out, _ = toc("--kind", "description")
        line = next(ln for ln in out.splitlines() if ln.startswith("goal-loop — "))
        self.assertEqual(line, "goal-loop — Run a coding agent headless in a bounded loop of fresh sessions until a check command exits 0 or a budget ends. "
                               "Use for a task in a folder that needs more than a few tool calls.")

    def test_folder_scope_lists_that_group_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first-root", Path(tmp) / "second-root"
            make(first, "alpha-skill")
            make(first, "beta-skill")
            make(second, "gamma-skill")
            code, out, _ = run("--only", str(first), "--only", str(second), "--toc")
            self.assertIn("## first-root (2)", out)
            self.assertIn("## second-root (1)", out)
            code, out, _ = run("--only", str(first), "--only", str(second), "--toc", "second-root")
            self.assertEqual(code, 0)
            self.assertIn("gamma-skill", out)
            self.assertNotIn("alpha-skill", out)
            self.assertNotIn("## first-root", out)
            self.assertTrue(out.splitlines()[0].startswith("table of contents: 1 skill in 1 folder"), out.splitlines()[0])

    def test_two_different_skills_with_one_name(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            make(a, "configure", "Set up the telegram bot.")
            make(b, "configure", "Set up the discord bot.")
            code, out, _ = run("--only", a, "--only", b, "--toc")
            self.assertEqual(len([ln for ln in out.splitlines() if ln.startswith("configure — ")]), 2)
            code, out, err = run("--only", a, "--only", b, "--toc", "configure")
            self.assertEqual(code, 1)
            self.assertIn("2 skills are named 'configure'", err)
            self.assertIn(str(Path(a) / "configure"), err)
            self.assertIn(str(Path(b) / "configure"), err)

    def test_merged_copies_print_one_row_with_also(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            make(a, "twin", "Does the twin thing.")
            make(b, "twin", "Does the twin thing.")
            _, out, _ = run("--only", a, "--only", b, "--toc")
            rows = [ln for ln in out.splitlines() if ln.startswith("twin")]
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0].endswith("(also at 1)"), rows[0])
            _, out, _ = run("--only", a, "--only", b, "--toc", "--json")
            entries = [e for g in json.loads(out)["toc"]["groups"] for e in g["entries"]]
            self.assertEqual(len(entries), 1)
            self.assertEqual(len(entries[0]["also"]), 1)

    def test_off_marker(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            entries = []
            for name, status, source, plugin in (("on-skill", "folder skill", "only x", None), ("off-skill", "plugin installed", "p@m", "p"),
                                                 ("dis-skill", "plugin DISABLED", "q@m", "q")):
                d = make(tmp, name, "Does it.")
                entries.append(dict(name=name, description="Does it.", dir=d, source=source, status=status, rank=0, plugin=plugin, also=[]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.toc(entries, "all", None, False)
            rows = {ln.split(" — ")[0]: ln for ln in buf.getvalue().splitlines() if " — " in ln}
            self.assertTrue(rows["off-skill"].endswith(" [off]"), rows["off-skill"])
            self.assertTrue(rows["dis-skill"].endswith(" [off]"), rows["dis-skill"])
            self.assertNotIn("[off]", rows["on-skill"])
            self.assertIn("## p (1)", buf.getvalue())

    def test_unknown_scope_exits_1(self):
        code, out, err = toc("no-such-thing")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no skill, folder or path matches 'no-such-thing'", err)

    def test_toc_with_task_exits_1(self):
        code, _, err = toc("--task", "graphql")
        self.assertEqual(code, 1)
        self.assertIn("--toc goes alone or with --phrase, not with --task", err)

    def test_toc_with_list_exits_1(self):
        code, _, err = toc("--list")
        self.assertEqual(code, 1)
        self.assertIn("--toc goes alone or with --phrase, not with --list", err)

    def test_toc_with_limit_top_exits_1(self):
        for flag, val in (("--limit", "5"), ("--top", "3")):
            code, _, err = toc(flag, val)
            self.assertEqual(code, 1, flag)
            self.assertIn(f"--toc goes alone or with --phrase, not with {flag}", err)

    def test_kind_without_toc_exits_1(self):
        code, _, err = run("--only", str(FIXTURES), "--kind", "names")
        self.assertEqual(code, 1)
        self.assertIn("--kind needs --toc", err)

    def test_json_shape(self):
        code, out, _ = toc("--json")
        t = json.loads(out)["toc"]
        self.assertEqual((t["scope"], t["level"], t["kind"], t["scanned"]), ("all", "all", "sentence", 18))
        self.assertEqual(t["groups"][0]["group"], "skills")
        e = t["groups"][0]["entries"][0]
        self.assertEqual(sorted(e), ["also", "name", "off", "path", "sentence", "status"])
        self.assertEqual((e["name"], e["status"], e["off"], e["also"]), ("accessibility", "folder skill", False, []))
        self.assertTrue(e["path"].endswith("accessibility/SKILL.md"), e["path"])


if __name__ == "__main__":
    unittest.main()
