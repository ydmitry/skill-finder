#!/usr/bin/env python3
"""Two SkillRet runs query by query: NDCG@10 difference with a paired bootstrap 95% interval, wins and losses, and the split by how many
skills a query needs (k = 1, 2, 3), each with its own interval.

  python3 -I bench/skillret/compare.py DATA A.json B.json [--queries FILE]

B minus A. --queries keeps the query ids listed in FILE (one a line). The bootstrap resamples the queries 2,000 times with a fixed
seed, so an interval is the same on every run.
"""
import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

N_BOOT, SEED, K = 2000, 20261105, 10


def ndcg(run, rel):
    top = run[:K]
    dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(top) if d in rel)
    return 100 * dcg / sum(1 / math.log2(i + 2) for i in range(min(len(rel), K)))


def interval(d):
    rnd = random.Random(SEED)
    boot = sorted(sum(rnd.choice(d) for _ in d) / len(d) for _ in range(N_BOOT))
    return f"{sum(d) / len(d):+.2f} [{boot[int(0.025 * N_BOOT)]:+.2f}, {boot[int(0.975 * N_BOOT) - 1]:+.2f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("a"); ap.add_argument("b"); ap.add_argument("--queries")
    x = ap.parse_args()
    g = defaultdict(set)
    for l in open(Path(x.data) / "data/qrels/test.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["relevance"] > 0: g[r["query_id"]].add(r["skill_id"])
    ra, rb = (json.loads(Path(p).read_text())["run"] for p in (x.a, x.b))
    keep = set(Path(x.queries).read_text().split()) if x.queries else None
    qs = sorted(q for q in g if keep is None or q in keep)
    na = {q: ndcg(ra.get(q, []), g[q]) for q in qs}
    nb = {q: ndcg(rb.get(q, []), g[q]) for q in qs}
    d = [nb[q] - na[q] for q in qs]
    print(f"{len(qs)} queries. NDCG@10 B - A: {interval(d)}  (95% paired bootstrap)")
    print(f"queries B better {sum(v > 0 for v in d)}, same {sum(v == 0 for v in d)}, worse {sum(v < 0 for v in d)}")
    for k in (1, 2, 3):
        sub = [q for q in qs if len(g[q]) == k]
        if not sub: continue
        ma, mb = sum(na[q] for q in sub) / len(sub), sum(nb[q] for q in sub) / len(sub)
        print(f"k={k} ({len(sub)} queries): A {ma:.2f}  B {mb:.2f}  B - A {interval([nb[q] - na[q] for q in sub])}")


if __name__ == "__main__":
    main()
