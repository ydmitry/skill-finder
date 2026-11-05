# The ranker on SkillRet, a public benchmark

SkillRet (Kang et al., [arXiv 2605.05726](https://arxiv.org/abs/2605.05726)) is a retrieval benchmark built from 6,006 real
SKILL.md files from public MIT and Apache-2.0 repos and 4,392 requests written by Claude Opus 4.6. This folder scores the finder's
`--task` ranker on it. No model runs: every result below comes from these scripts, on a laptop, with no API key.

## Result

Finder at 111dabb, dataset at Hugging Face revision `6583d7d`, SkillRet's own metrics over all 4,392 requests:

| run | NDCG@10 | Recall@10 | Completeness@10 |
|---|---|---|---|
| BM25 as SkillRet runs it (this rerun gives the paper's row exactly) | 51.69 | 59.41 | 44.56 |
| BM25 over the SKILL.md alone, which is all the finder reads | 50.70 | 58.49 | 43.62 |
| **skill-finder `--task`** | **58.78** | **67.35** | **53.01** |

Completeness@10 is the share of requests with every needed skill in the first ten. Request by request, the finder is ahead of
BM25 by +7.09 NDCG@10 (paired bootstrap 95% interval +6.19 to +7.98). The lead depends on how many skills a request needs:

| skills needed | requests | BM25 | finder | finder − BM25 |
|---|---|---|---|---|
| one | 2,143 | 57.74 | 58.23 | +0.49 [−0.95, +1.90] |
| two | 1,703 | 47.77 | 59.48 | +11.71 [+10.47, +12.88] |
| three | 546 | 40.13 | 58.74 | +18.61 [+16.55, +20.56] |

On requests that need one skill there is no measurable difference. Among the paper's 19 retrievers on this split, 58.78 would come
12th: above BM25 and small embedding models such as bge-small-en-v1.5 (54.51), within a point of bge-large-en-v1.5 (59.00), and
well below the best off-the-shelf model (70.26) and the benchmark's own fine-tuned one (86.44).

## What it measures, and what it does not

- **The ranker alone, given the whole request** (median 169 words). The `CLAUDE.md` block in the main README has Claude look up
  two or three words with `--phrase`; a whole request as one exact phrase matches nothing, so that mode is not scored here.
- **Not Claude.** Whether Claude runs the finder, opens what it lists, or works better for it is a different question; no skill is
  listed to a model here.
- **The requests were written from each skill's name and description**, and for 5,258 of the 6,006 skills that is the
  description in the SKILL.md front matter (spacing aside). The finder counts a description hit ten times one body occurrence, which suits how these
  requests were made.
- **SKILL.md only.** The dataset has no reference files, so that part of the finder's score is always 0.
- **One skill can never be found.** It shares its name and its description with another, and the finder shows such copies once, so
  one of the 7,187 (request, skill) pairs is out of reach.

## Run it

Python 3 for the finder and these scripts (standard library only); [uv](https://docs.astral.sh/uv/) for the BM25 baseline (bm25s
0.3.3, the version SkillRet's lock file pins) and, optionally, the pytrec_eval cross-check. The numbers above were made with
PyYAML installed, which the finder uses for front matter when it can import it; with its own parser instead, 168 descriptions
read differently (spacing aside) and a few numbers move in the second decimal (Recall@10 67.34, NDCG@10 the same; 5,166
descriptions match the dataset's instead of 5,258). About a quarter of an hour in all, most of it the finder run; the `--check` line is optional and
takes minutes per request. `prep.py` refuses a folder that exists: remove `$D/skills-dir` to start again. From the repository
root:

```
D=~/skillret-data; REV=6583d7d2ed07644d0fb8938ed8178f3a7dc42a12; R=bench/skillret/results
for f in data/skills/test.jsonl data/queries/test.jsonl data/qrels/test.jsonl; do mkdir -p "$D/$(dirname $f)"; \
  curl -sSL -o "$D/$f" "https://huggingface.co/datasets/ThakiCloud/SKILLRET/resolve/$REV/$f"; done
(cd $D && shasum -a 256 -c -) <<'EOF'
edbfae0b8109de460d54e27e6235b1b47316f34956744db0571ad1b4ddb860af  data/qrels/test.jsonl
4d07a35f40e597f8468c6dab480c95a1f9b40ecbde80274081ba2e7c643d0f6d  data/queries/test.jsonl
1960453e422e4ba01977197580934ca3c02b2ac302dfa9c0d074707d961b7c81  data/skills/test.jsonl
EOF
python3 -I bench/skillret/prep.py $D $D/skills-dir                               # DIR/<id>/SKILL.md, byte for byte
uv run --no-project --python 3.13 --with bm25s==0.3.3 python -I bench/skillret/bm25_run.py $D $R/bm25-paper.json
uv run --no-project --python 3.13 --with bm25s==0.3.3 python -I bench/skillret/bm25_run.py $D $R/bm25-skill_md.json --text skill_md
python3 -I bench/skillret/finder_run.py $D/skills-dir $D $R/finder-task.json --workers 6      # about 8 minutes on a 10-core Mac
python3 -I bench/skillret/finder_run.py $D/skills-dir $D --check 3 --workers 4               # optional: the real rank() on 3 requests
python3 -I bench/skillret/score.py $D $R/bm25-paper.json $R/bm25-skill_md.json $R/finder-task.json
uv run --no-project --python 3.13 --with pytrec-eval-terrier==0.5.10 python -I bench/skillret/score.py $D $R/*.json   # cross-check
python3 -I bench/skillret/compare.py $D $R/bm25-paper.json $R/finder-task.json
```

The three test files are the same at revision `a050ad2`, the one SkillRet's own README suggests pinning. Run files go to
`results/`, which is not committed.

## How the scripts stay honest

- `bm25_run.py` is SkillRet's `eval_bm25` (ThakiCloud/SKILLRET commit 0cc508e): the same library version, stopwords, document text
  (`name | description | skill_md`) and first 20 hits. It reproduces all nine BM25 numbers of the paper's Table 3 (NDCG, Recall and
  Completeness at 5, 10 and 15) to two decimals, which checks the data and the metric code together.
- `score.py` computes the metrics itself and, when pytrec_eval is installed, again with pytrec-eval-terrier 0.5.10, as SkillRet's
  `trec_eval()` does; the two agree on every run.
- `finder_run.py` uses the finder's own `collect()`, `prepare()`, `terms_of()` and `pattern()` and recomputes `rank()` with each
  word's matches cached, because the real one takes minutes per long request at this size. `--check N` compares it with the real
  `rank()` on N requests spread over the set: the same first 20 skills, in the same order, with the same scores (3 of 3 for the
  numbers above).
