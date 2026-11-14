"""Two changes from misses on a public benchmark's tasks: skills near the whole lookup by words are listed when no phrase holds
them, and a row shows more of the description. Tried with them and dropped after model runs: the first row going to the listed
skill the whole lookup's words rank highest (wrong twice as often as right), and a long unmatched phrase retried by its
two-word parts (never listed a needed skill)."""
import json, subprocess, sys
from pathlib import Path

FINDER = Path(__file__).resolve().parent.parent / "scripts" / "find_skills.py"
LONG = ("Guides the migration of Java services from the javax namespace to jakarta when upgrading to Spring Boot 3, with the "
        "import rewrites, the dependency changes and the checks to run after the upgrade is complete and deployed.")

def skill(root, name, desc, body, ref=None):
    d = root / name; d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")
    if ref: (d / "references").mkdir(); (d / "references" / "notes.md").write_text(ref + "\n")

def world(tmp_path):
    skill(tmp_path, "alpha-cloud", "Deploy models to the cloud.", "Use a cmake build for the native part.\n")
    skill(tmp_path, "cpp-testing", "Write and fix C++ tests with GoogleTest.", "Tests are wired into the cmake build.\n")
    skill(tmp_path, "web-forms", "Build web forms.", "error handling here.\n")
    skill(tmp_path, "teams-move", "Move a chat app to Teams.", "The old app used bolt python.\n")
    skill(tmp_path, "slack-bot-builder", "Bolt apps in Python for Slack: errors, retries and their handling.", "Listeners and middleware.\n")
    skill(tmp_path, "docs-writer", "House rules for product documentation.", "Applies to the Gemini CLI pages.\n")
    skill(tmp_path, "jakarta-namespace", LONG, "error handling of imports.\n")
    skill(tmp_path, "ref-holder", "Something else.", "Nothing.\n", ref="error handling in depth")
    for n in range(24): skill(tmp_path, f"filler-{n}", f"Topic number {n}.", "nothing of note.\n")
    return tmp_path

def run(root, phrases, *extra):
    cmd = [sys.executable, str(FINDER), "--only", str(root)] + [x for ph in phrases for x in ("--phrase", ph)] + list(extra)
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

def test_one_phrase_keeps_its_order(tmp_path):
    out = run(world(tmp_path), ["cmake build"])
    assert "1. alpha-cloud  [" in out and "Best match: alpha-cloud" in out

def test_a_skill_near_the_whole_lookup_by_words_is_listed_when_no_phrase_holds_it(tmp_path):
    w = world(tmp_path)
    out = run(w, ["error handling", "bolt python"])
    assert "slack-bot-builder" not in out[:out.index("Nearest by the words of the whole lookup")]
    block = out[out.index("Nearest by the words of the whole lookup"):out.index("Best match:")]
    assert [ln.split()[1] for ln in block.splitlines() if ln.startswith("- ")] == ["slack-bot-builder"]
    data = json.loads(run(w, ["error handling", "bolt python"], "--json"))
    assert [r["name"] for r in data["nearest_whole"]] == ["slack-bot-builder"]

def test_no_whole_lookup_rows_when_the_near_skills_are_listed(tmp_path):
    assert "Nearest by the words of the whole lookup" not in run(world(tmp_path), ["cmake build", "C++ unit tests"])

def test_a_row_shows_more_of_the_description_cut_at_a_word(tmp_path):
    out = run(world(tmp_path), ["error handling"])
    row = out[out.index("jakarta-namespace  ["):].splitlines()[1].strip()
    assert "upgrading to Spring Boot 3" in row and len(row) > 150
    assert row.endswith("...") and LONG.startswith(row[:-3].rstrip()) and LONG[len(row[:-3].rstrip())] == " "

def test_the_reference_only_block_stays_before_the_nearest_rows(tmp_path):
    out = run(world(tmp_path), ["error handling", "Gemini CLI docs"])
    assert out.index("Only in reference files") < out.index('No skill contains "Gemini CLI docs"') < out.index("Best match:")

def test_a_skill_that_holds_no_phrase_is_never_the_best_match(tmp_path):
    w = world(tmp_path)
    data = json.loads(run(w, ["error handling", "bolt slack python"], "--json"))
    assert data["best"]["name"] in [r["name"] for r in data["candidates"]]
    assert "slack-bot-builder" in [r["name"] for r in data["nearest_whole"]] + [r["name"] for u in data["unmatched"] for r in u["nearest"]]


def test_several_phrases_keep_each_phrase_in_turn_for_the_first_row(tmp_path):
    out = run(world(tmp_path), ["cmake build", "C++ unit tests"])
    assert "1. alpha-cloud  [" in out and "Best match: alpha-cloud" in out
