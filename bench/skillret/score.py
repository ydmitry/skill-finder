#!/usr/bin/env python3
"""NDCG, Recall and Completeness at 5, 10 and 15 for SkillRet run files, as SkillRet's trec_eval() reports them.

  python3 -I bench/skillret/score.py DATA RUN.json [RUN.json ...]
  uv run --no-project --python 3.13 --with pytrec-eval-terrier==0.5.10 python -I bench/skillret/score.py DATA RUN.json ...

Binary gains; NDCG's ideal list holds min(gold, k) hits; Recall@k is the share of a query's gold skills in its first k; Completeness@k
the share of queries with all of them. Every one of the 4,392 queries counts, an empty run as 0. With pytrec_eval installed the same
run is also scored by it the way SkillRet's trec_eval() does (a run's stored scores, else 20 minus the rank, which keeps the run's
order; every query keyed, a query with no hits as an empty dict, which pytrec_eval scores 0), and both rows print.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

KS = (5, 10, 15)


def gold(data):
    g = defaultdict(set)
    for l in open(Path(data) / "data/qrels/test.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["relevance"] > 0: g[r["query_id"]].add(r["skill_id"])
    return g


def ours(g, run):
    m = defaultdict(float)
    for q, rel in g.items():
        r = run.get(q, [])
        for k in KS:
            top = r[:k]
            dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(top) if d in rel)
            idcg = sum(1 / math.log2(i + 2) for i in range(min(len(rel), k)))
            hit = len(rel & set(top))
            m[f"NDCG@{k}"] += dcg / idcg
            m[f"Recall@{k}"] += hit / len(rel)
            m[f"Completeness@{k}"] += hit == len(rel)
    return {k: 100 * v / len(g) for k, v in m.items()}


def trec(g, run, scores):
    import pytrec_eval
    qrels = {q: {d: 1 for d in rel} for q, rel in g.items()}
    res = {q: (scores or {}).get(q) or {d: float(20 - i) for i, d in enumerate(run.get(q, []))} for q in g}
    ev = pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut." + ",".join(map(str, KS)), "recall." + ",".join(map(str, KS))})
    s = ev.evaluate(res)
    m = defaultdict(float)
    for q in s:
        for k in KS:
            m[f"NDCG@{k}"] += s[q][f"ndcg_cut_{k}"]; m[f"Recall@{k}"] += s[q][f"recall_{k}"]
            m[f"Completeness@{k}"] += float(s[q][f"recall_{k}"] == 1.0)
    return {k: 100 * v / max(len(s), 1) for k, v in m.items()}, len(s)


def row(name, m):
    cols = [f"{m[f'{x}@{k}']:.2f}" for x in ("NDCG", "Recall", "Completeness") for k in KS]
    return f"| {name} | " + " | ".join(cols) + " |"


def main(data, *runs):
    g = gold(data)
    print("| run | " + " | ".join(f"{x}@{k}" for x in ("NDCG", "R", "Comp") for k in KS) + " |")
    print("|---" * 10 + "|")
    for p in runs:
        f = json.loads(Path(p).read_text())
        run, meta = f["run"], f["meta"]
        empty = sum(1 for q in g if not run.get(q))
        print(row(f"{meta['system']} — ours, {len(g)} queries, {empty} with no hit", ours(g, run)))
        try:
            m, n = trec(g, run, f.get("scores"))
            print(row(f"{meta['system']} — pytrec_eval, {n} queries", m))
        except ImportError:
            pass


if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(__doc__)
    main(*sys.argv[1:])
