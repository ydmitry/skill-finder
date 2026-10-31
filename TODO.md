# TODO

## Rework the best-match idea

State: after every `--phrase` search that finds something, the finder prints a best-match block (why it matched, description, first
~20 lines of SKILL.md, reference files, "Read <path>, then follow it"). With `--for "<one sentence>"` one Haiku call adds a fit reason
or NONE. Both are in `scripts/find_skills.py`; the block has no off switch (`SKILL_FINDER_EXPLAIN=0` turns off only the model call).

What the experiments showed (15 runs each, Haiku, tasks with a failing gate; the experiments are not in this repository): the block
with a model reason passed 5 of 15 runs (model reads 3 hits) and 3 of 15 (10 hits), the block without a model 8 of 15, against 9 of 15
for a plain line in the worker's CLAUDE.md that says to search by phrase. The block shows and opens the skill more often (13 and 12 runs
against 11 and 9) but costs tokens: three of five runs on the longest skill hit the 1.5M token cap.

Ideas to rework, each untested and each needs its own bar written before the run:
- Decide whether the block stays on by default; add a switch either way.
- A lighter block (name, one reason, path; no body lines) to cut the tokens per lookup.
- Recall is the limit: the task's skill is often outside the first hits, so neither block nor model can help there. Improve what
  reaches the first hits before improving what is printed about them.
- Pull the three changes apart (fit-sentence instruction, printed block, model call); the experiments changed all three at once.
- If the token cap is raised, that is its own test, not a rescue of this one.
- Drop `--for` if the model reason is not coming back.

## Real tasks

The experiments used tasks derived from skills, which gives a ceiling only. Harvest about 60 real tasks (from one's own installed
skills and past sessions, each with the skill that should fire, blind-judged), then run a retrieval-only eval (no model) and a small live
Haiku run on them.
