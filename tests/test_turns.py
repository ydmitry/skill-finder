"""Several phrases in one lookup: each phrase takes a row in turn, so a skill that holds one phrase is not pushed out by
skills that hold many common ones."""
import json, subprocess, sys
from pathlib import Path

FINDER = Path(__file__).resolve().parent.parent / "scripts" / "find_skills.py"

def skill(root, name, desc, body):
    d = root / name; d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")

def rows(root, phrases, limit):
    cmd = [sys.executable, str(FINDER), "--only", str(root), "--limit", str(limit), "--json"] + [x for ph in phrases for x in ("--phrase", ph)]
    return [r["name"] for r in json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)["candidates"]]

def world(tmp_path):
    for n in ("aa-one", "bb-two", "cc-three"): skill(tmp_path, n, "About web apps.", "error handling here.\nrest api there.\n")
    skill(tmp_path, "team-ledger", "Our ledger.", "ledger entry rules.\n")
    skill(tmp_path, "dd-api", "rest api guide.", "rest api rest api.\n")
    return tmp_path

def test_each_phrase_takes_a_row_in_turn(tmp_path):
    assert rows(world(tmp_path), ["error handling", "rest api", "ledger entry"], 3) == ["aa-one", "dd-api", "team-ledger"]

def test_turns_go_round_until_the_limit(tmp_path):
    assert rows(world(tmp_path), ["error handling", "rest api", "ledger entry"], 5) == ["aa-one", "dd-api", "team-ledger", "bb-two", "cc-three"]

def test_one_phrase_keeps_its_order(tmp_path):
    assert rows(world(tmp_path), ["rest api"], 10) == ["dd-api", "aa-one", "bb-two", "cc-three"]

def test_the_same_phrase_twice_has_one_turn(tmp_path):
    assert rows(world(tmp_path), ["rest api", "Rest API", "ledger entry"], 2) == ["dd-api", "team-ledger"]
