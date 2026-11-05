#!/usr/bin/env python3
"""SkillRet's BM25 baseline as its own code runs it (skillret/eval.py eval_bm25 at ThakiCloud/SKILLRET 0cc508e), as a run file.

  uv run --no-project --python 3.13 --with bm25s==0.3.3 python -I bench/skillret/bm25_run.py DATA OUT.json [--text paper|skill_md]

`paper` is the document text the benchmark scores (name | description | skill_md, load_corpus's fallback to the description when
skill_md is empty); `skill_md` is the file alone, which is all the finder reads. bm25s 0.3.3 is the version in SkillRet's uv.lock:
English stopwords, its default BM25 (Lucene, k1 1.5, b 0.75), the first 20 hits, hits scoring 0 dropped.
"""
import argparse
import json
from pathlib import Path

import bm25s

TOP = 20


def text_of(s, kind):
    body = (s.get("skill_md") or "").strip() or (s.get("description") or "").strip()
    if kind == "skill_md": return body
    return f"{(s.get('name') or '').strip()} | {(s.get('description') or '').strip()} | {body}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("out"); ap.add_argument("--text", choices=("paper", "skill_md"), default="paper")
    a = ap.parse_args()
    d = Path(a.data) / "data"
    skills = [json.loads(l) for l in open(d / "skills/test.jsonl", encoding="utf-8")]
    qs = [json.loads(l) for l in open(d / "queries/test.jsonl", encoding="utf-8")]
    ids = [s["id"] for s in skills]
    retriever = bm25s.BM25()
    retriever.index(bm25s.tokenize([text_of(s, a.text) for s in skills], stopwords="en", show_progress=False), show_progress=False)
    run, scores = {}, {}
    for q in qs:
        qt = bm25s.tokenize(q["query"], stopwords="en", show_progress=False)
        if len(qt.vocab) == 0: qt = bm25s.tokenize("NONE", stopwords=[], show_progress=False)
        hits, sc = retriever.retrieve(qt, corpus=ids, k=min(TOP, len(ids)), show_progress=False)
        keep = [(str(hits[0, i]), float(sc[0, i])) for i in range(len(hits[0])) if sc[0, i] > 0]
        run[q["id"]] = [h for h, _ in keep]
        scores[q["id"]] = {h: s for h, s in keep}
    meta = dict(system=f"BM25 (bm25s {bm25s.__version__}, text {a.text})", top=TOP)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(dict(meta=meta, run=run, scores=scores)) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
