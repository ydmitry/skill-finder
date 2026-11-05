#!/usr/bin/env python3
"""skill-finder's --task ranking of every SkillRet test query, as `find_skills.py --only DIR --task "<query>"` ranks it, as a run file.

  python3 -I bench/skillret/finder_run.py DIR DATA OUT.json [--workers 8]
  python3 -I bench/skillret/finder_run.py DIR DATA --check 12

DIR is the folder prep.py wrote, DATA the SkillRet download. The finder's own collect(), prepare(), terms_of() and pattern() are used
as they are. rank() is recomputed with each word's matches cached across queries: the real one re-reads every file and runs every
word's pattern over all of them for each query, minutes a query at this size. --check N ranks N queries spread over the set with the
real rank() as well and stops at the first difference in the order or the score of the first TOP hits. Positions past --top 8, the
CLI's default, are kept: the order is the CLI's with --top 20. PyYAML is loaded from the user's site-packages when it is there, as a
plain `python3` loads it for the finder (-I would hide it). SKILL_FINDER_SCRIPTS points at another checkout's scripts/ folder.
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import site
import subprocess
import sys
import time
from array import array
from pathlib import Path

FINDER = Path(os.environ.get("SKILL_FINDER_SCRIPTS") or Path(__file__).resolve().parents[2] / "scripts")
sys.path.insert(0, str(FINDER))
sys.path.append(site.getusersitepackages())
import find_skills as fs                                                            # noqa: E402

TOP = 20            # SkillRet's evaluation keeps each query's first 20 (RERANK_TOP_K); the metrics stop at 15
E = []              # the entries, prepared once; forked workers share them


def load(dir_):
    global E
    E = fs.collect([], only=[dir_])
    fs.prepare(E)
    for e in E: e["_name"], e["_desc"] = e["name"].lower(), e["description"].lower()
    return E


def postings(t):
    """For one word: its document frequency as document_frequency() counts it, and score()'s `part` for every entry it reaches."""
    p, idx, part, df = fs.pattern(t), array("i"), array("d"), 0
    for i, e in enumerate(E):                       # `t in text` first: a pattern match is always a substring match
        in_name = t in e["_name"] and p.search(e["_name"]) is not None
        in_desc = t in e["_desc"] and p.search(e["_desc"]) is not None
        cnt = len(p.findall(e["_main"])) if t in e["_main"] else 0
        if cnt or in_name: df += 1
        x = 5 * in_name + 3 * in_desc + 1.5 * min(cnt, 5) / 5
        x += min(sum(1 for f, txt in e["_refs"] if p.search(txt)), 5) / 5 + 1.0 * any(p.search(f.name.lower()) for f, _ in e["_refs"])
        if x: idx.append(i); part.append(x)
    return t, df, idx, part


def ranking(terms, post):
    """rank(entries, terms) with cached postings: [(score, entry index)] best first, ties in entry order, as sorted() leaves them."""
    n = len(E)
    df = {t: post[t][0] for t in terms}
    generic = {t for t in terms if df[t] > fs.GENERIC_SHARE * n}
    eff = [t for t in terms if t not in generic] or terms
    total = {}
    for t in eff:                                   # each entry's sum is built in eff order, as score() builds it
        w = math.log(1 + n / (1 + df[t])) ** 2
        _, idx, part = post[t]
        for i, x in zip(idx, part): total[i] = total.get(i, 0.0) + w * x
    return sorted(((s, i) for i, s in total.items() if s > 0), key=lambda si: (-si[0], si[1]))


def queries(data):
    with open(Path(data) / "data/queries/test.jsonl", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def build(qs, workers):
    words = sorted({t for q in qs for t in fs.terms_of(q["query"])})
    t0, post = time.time(), {}
    with mp.get_context("fork").Pool(workers) as pool:
        for k, (t, df, idx, part) in enumerate(pool.imap_unordered(postings, words, chunksize=64), 1):
            post[t] = (df, idx, part)
            if k % 2000 == 0: print(f"  {k}/{len(words)} words, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    return post, len(words)


def check(qs, n, workers):
    pick = [qs[round(j * (len(qs) - 1) / max(n - 1, 1))] for j in range(n)]
    post, _ = build(pick, workers)
    for q in pick:
        terms = fs.terms_of(q["query"])
        real, _, _ = fs.rank(E, terms)
        fast = ranking(terms, post)
        a = [(s, str(e["dir"])) for s, e in real[:TOP]]
        b = [(s, str(E[i]["dir"])) for s, i in fast[:TOP]]
        if a != b or len(real) != len(fast):
            sys.exit(f"DIFFERENT for {q['id']}: real {len(real)} hits, fast {len(fast)}; first top-{TOP} pairs {a[:3]} vs {b[:3]}")
        print(f"{q['id']}: same top {TOP} (order and score) and same hit count {len(real)}", flush=True)
    print(f"check passed on {n} queries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("data"); ap.add_argument("out", nargs="?")
    ap.add_argument("--check", type=int, default=0); ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    load(a.dir)
    qs = queries(a.data)
    if a.check: return check(qs, a.check, a.workers)
    if not a.out: sys.exit("OUT.json is needed unless --check")
    t0 = time.time()
    post, nwords = build(qs, a.workers)
    run = {q["id"]: [E[i]["dir"].name for _, i in ranking(fs.terms_of(q["query"]), post)[:TOP]] for q in qs}
    on_disk = {p.name for p in Path(a.dir).iterdir() if (p / "SKILL.md").is_file()}
    kept = {e["dir"].name for e in E}
    git = lambda *x: subprocess.run(["git", "-C", str(FINDER), *x], capture_output=True, text=True).stdout.strip()
    meta = dict(system="skill-finder --task (raw query)", finder_commit=git("log", "-1", "--format=%H", "--", "find_skills.py"),
                finder_edited=bool(git("status", "--porcelain", "--", "find_skills.py")), workers=a.workers, yaml="yaml" in sys.modules,
                skills_on_disk=len(on_disk), entries=len(E), merged_away=sorted(on_disk - kept), words=nwords, top=TOP,
                seconds=round(time.time() - t0))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(dict(meta=meta, run=run)) + "\n")
    print(json.dumps(meta | dict(merged_away=len(meta["merged_away"])), indent=1))


if __name__ == "__main__":
    main()
