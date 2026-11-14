"""The --task ranking skips the word-start pattern where the word is not in the text at all. The scores must not change."""
import importlib.util, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fs_speed", ROOT / "scripts" / "find_skills.py")
fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)

def slow_score(e, pats, idf):
    name, desc, total = e["name"].lower(), e["description"].lower(), 0.0
    for t, p in pats.items():
        part = 5 * bool(p.search(name)) + 3 * bool(p.search(desc)) + 1.5 * min(len(p.findall(e["_main"])), 5) / 5
        part += min(sum(1 for f, txt in e["_refs"] if p.search(txt)), 5) / 5 + 1.0 * any(p.search(f.name.lower()) for f, _ in e["_refs"])
        total += idf[t] * part
    return total

def test_scores_and_word_counts_equal_the_plain_pattern_reading():
    entries = fs.collect([], only=[str(ROOT / "tests" / "fixtures" / "skills")])
    assert entries, "the fixtures were not read"
    terms = fs.terms_of("draft release notes for the latest test run and a database migration plan with docker images and api tokens")
    fs.prepare(entries)
    pats = {t: fs.pattern(t) for t in terms}
    df_slow = {t: sum(1 for e in entries if p.search(e["_main"]) or p.search(e["name"].lower())) for t, p in pats.items()}
    assert fs.document_frequency(entries, pats) == df_slow
    idf = {t: math.log(1 + len(entries) / (1 + df_slow[t])) ** 2 for t in terms}
    for e in entries: assert fs.score(e, pats, idf) == slow_score(e, pats, idf), e["name"]
    assert any(fs.score(e, pats, idf) > 0 for e in entries)
