"""A phrase of a several-phrase lookup that no skill holds still points somewhere: its nearest skills by words are listed
after the rows, as a lookup of that phrase alone would list them. Before, they showed only when no phrase matched at all."""
import json, subprocess, sys
from pathlib import Path

FINDER = Path(__file__).resolve().parent.parent / "scripts" / "find_skills.py"

def skill(root, name, desc, body):
    d = root / name; d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")

def world(tmp_path):
    skill(tmp_path, "web-forms", "Build web forms.", "error handling here.\n")
    skill(tmp_path, "moltbook-validator", "Validate a post before it is published on Moltbook.", "Check the draft.\n")
    skill(tmp_path, "ledger", "Our ledger.", "ledger entry rules.\n")
    for n in ("aa", "bb", "cc", "dd"): skill(tmp_path, f"post-{n}", "Notes on blog posts.", "post post.\n")
    for n in range(20): skill(tmp_path, f"filler-{n}", f"Topic number {n}.", "nothing of note.\n")      # so that a word in five skills is not a common word
    return tmp_path

def run(root, phrases, *extra):
    cmd = [sys.executable, str(FINDER), "--only", str(root)] + [x for ph in phrases for x in ("--phrase", ph)] + list(extra)
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

def test_a_phrase_no_skill_holds_gets_its_nearest_skills_listed(tmp_path):
    out = run(world(tmp_path), ["error handling", "Moltbook post"])
    assert "1. web-forms" in out
    block = out[out.index('No skill contains "Moltbook post"'):]
    assert "nearest by words" in block.lower()
    first = [ln for ln in block.splitlines() if ln.startswith("- ")][0]
    assert first.startswith("- moltbook-validator  [") and first.endswith("/moltbook-validator/SKILL.md")
    assert out.index('No skill contains "Moltbook post"') < out.index("Best match:")

def test_every_unmatched_phrase_is_named_and_the_rows_are_capped(tmp_path):
    w = world(tmp_path)
    for n in range(4): skill(w, f"zebra-{n}", "Zebra crossing rules.", "zebra crossing.\n")
    for n in range(4): skill(w, f"quota-{n}", "Quota handling for tenants.", "quota tenants.\n")
    out = run(w, ["error handling", "blog post outline", "zebra crossings quota", "tenants quota report", "of the"])
    block = out[out.index("No skill contains"):out.index("Best match:")]
    for ph in ("blog post outline", "zebra crossings quota", "tenants quota report", "of the"): assert f'No skill contains "{ph}"' in block
    rows = [ln.split()[1] for ln in block.splitlines() if ln.startswith("- ")]
    assert len(rows) == 6 and len(set(rows)) == 6 and "web-forms" not in rows
    d = json.loads(run(w, ["error handling", "blog post outline", "zebra crossings quota", "tenants quota report", "of the"], "--json"))
    assert [u["phrase"] for u in d["unmatched"]] == ["blog post outline", "zebra crossings quota", "tenants quota report", "of the"]
    assert [len(u["nearest"]) for u in d["unmatched"]] == [3, 3, 0, 0] and d["unmatched"][3]["word_counts"] == {}

def test_a_nearest_skill_already_listed_is_named_not_replaced(tmp_path):
    out = run(world(tmp_path), ["error handling", "web forms builder"])
    line = [ln for ln in out.splitlines() if ln.startswith('No skill contains "web forms builder"')][0]
    assert "listed above: web-forms" in line and "builder 0" in line
    assert not [ln for ln in out[out.index("No skill contains"):out.index("Best match:")].splitlines() if ln.startswith("- ")]

def test_a_skill_that_shares_one_common_word_is_not_near(tmp_path):
    w = world(tmp_path)
    out = run(w, ["error handling", "moltbook post outline"])
    block = out[out.index("No skill contains"):out.index("Best match:")]
    rows = [ln.split()[1] for ln in block.splitlines() if ln.startswith("- ")]
    assert rows == ["moltbook-validator"]              # the post-* skills hold only "post"; none has the rarest word, none holds two
    out = run(w, ["error handling", "xyzzy post"])
    assert 'No skill contains "xyzzy post" (skills holding each word: xyzzy 0, post 6).' in out or 'No skill contains "xyzzy post" (skills holding each word: xyzzy 0, post 5).' in out

def test_same_phrase_twice_and_a_reference_file_in_upper_case(tmp_path):
    w = world(tmp_path)
    (w / "ledger" / "references").mkdir()
    (w / "ledger" / "references" / "Close.md").write_text("Month End Close steps\n")
    out = run(w, ["error handling", "Blog Post Outline", "blog-post outline", "MONTH END close"])
    assert out.count("No skill contains") == 1 and 'No skill contains "Blog Post Outline"' in out

def test_toc_and_no_hit_paths_have_no_unmatched_key(tmp_path):
    w = world(tmp_path)
    assert "unmatched" not in json.loads(run(w, ["Moltbook post"], "--json")) and "unmatched" not in json.loads(run(w, ["error handling", "Moltbook post"], "--json", "--toc"))
    assert json.loads(run(w, ["error handling", "ledger entry"], "--json"))["unmatched"] == []

def test_no_block_when_every_phrase_matches_and_one_phrase_alone_is_unchanged(tmp_path):
    w = world(tmp_path)
    assert "No skill contains" not in run(w, ["error handling", "ledger entry"])
    alone = run(w, ["Moltbook post"])
    assert alone.splitlines()[1].startswith("No skill contains it.") and "Nearest by words, not by phrase" in alone

def test_json_names_the_unmatched_phrases_and_their_nearest(tmp_path):
    d = json.loads(run(world(tmp_path), ["error handling", "Moltbook post"], "--json"))
    assert [u["phrase"] for u in d["unmatched"]] == ["Moltbook post"] and d["unmatched"][0]["nearest"][0]["name"] == "moltbook-validator"
    assert d["unmatched"][0]["word_counts"]["moltbook"] == 1 and d["unmatched"][0]["shown_above"] == []

def test_a_phrase_held_only_in_a_reference_file_is_not_unmatched(tmp_path):
    w = world(tmp_path)
    (w / "ledger" / "references").mkdir()
    (w / "ledger" / "references" / "close.md").write_text("month end close steps\n")
    out = run(w, ["error handling", "month end close"])
    assert "No skill contains" not in out
