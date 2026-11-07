# TODO

## Rework the best-match idea

State: after every `--phrase` search that finds something, the finder prints a best-match block (why it matched, description, first
~20 lines of SKILL.md, reference files, "Read <path>, then follow it"). The block has no off switch. A `--for "<one sentence>"` option
that added one Haiku call's fit reason or NONE was removed on 2026-11-07, so that the script calls no model and starts no process.

What the experiments showed (15 runs each, Haiku, tasks with a failing gate; the experiments are not in this repository): the block
with a model reason passed 5 of 15 runs (model reads 3 hits) and 3 of 15 (10 hits), the block without a model 8 of 15, against 9 of 15
for a plain line in the worker's CLAUDE.md that says to search by phrase. The block shows and opens the skill more often (13 and 12 runs
against 11 and 9) but costs tokens: three of five runs on the longest skill hit the 1.5M token cap.

Ideas to rework, each untested and each needs its own bar written before the run:
- Decide whether the block stays on by default; add a switch either way.
- A lighter block (name, one reason, path; no body lines) to cut the tokens per lookup.
- Recall is the limit: the task's skill is often outside the first hits, so neither block nor model can help there. Improve what
  reaches the first hits before improving what is printed about them.
- Pull the changes apart (fit-sentence instruction, printed block); the experiments also changed the model call, now removed.
- If the token cap is raised, that is its own test, not a rescue of this one.

## Real tasks

The experiments used tasks derived from skills, which gives a ceiling only. Harvest about 60 real tasks (from one's own installed
skills and past sessions, each with the skill that should fire, blind-judged), then run a retrieval-only eval (no model) and a small live
Haiku run on them.

## Check the CLAUDE.md instruction in real use

The `SKILL.md` description does not get the skill called: with the old description, with "Use at the start of EVERY task" and without
"EVERY", 0 of 232 runs on Haiku and Sonnet called the finder (the experiments are not in this repository), so the README asks for a
standing instruction in `CLAUDE.md`. On Sonnet the instruction got the finder run before the first edit in 8 of 8 test tasks and in 0 of 4 one-line questions, and the model then
opened a skill from the list in 6 of 8 (n = 2 per task; on 3 of the 4 tasks it opens the same skill without the finder, so the lookup
changed the outcome on one). The line "open the best match's SKILL.md before writing anything" is not tested apart from the rest. After a few weeks of use, count in the session logs how often `find_skills.py` runs and
how often a skill it listed is invoked afterwards. If the finder still hardly runs, the instruction belongs in the goal text of delegated runs.
Delegated workers (intended): subagents read the same `CLAUDE.md`, so each one looks the skills up before its first edit: 8 of 8 delegated
test tasks, about three lookups each, and they open the same skills as the top-level session does. A coordinator that only hands the task
over looks nothing up (0 of 8). That keeps the lookup output (about 20 to 60 lines each) out of the main conversation, at about $0.08 more
per delegated run; the coordinator does not learn which skill the worker opened unless the worker says so.

## Trivial edits start a lookup

The block exempts one-line answers and tasks that name their skills, not small edits. "Rename `x` to `count` in this file" ran the finder
before the first edit in 14 of 15 Sonnet runs (no skill opened, 0.02 to 0.08 USD a run); a one-line question and a thanks ran it in 0 of 15
each. Not changed: an exemption such as "renames and other trivial edits" could also switch the lookup off for small edits where a skill
matters, so it would need the same test as the original instruction (the should-fire tasks must still fire 8 of 8) before it goes in.

## Skills bundled inside Claude Code

The finder cannot see them: `dataviz`, for example, has no `SKILL.md` on disk (Claude Code extracts it to a temp folder when it is invoked),
so `--phrase chart --limit 60` finds nothing for it. A model sees such a skill in its own listing, so the gap hurts only when the listing
shows it as a bare name or not at all. Find out whether there is a way to list the bundled skills (the init event of `claude -p` names
them) and, if so, add them to the inventory as "bundled, not on disk". The script starts no process, so the list has to come from
outside it: a file the user or a caller writes, read like `scripts/roots`.

## What the block says to do when a lookup finds nothing

Tested, nothing to change. The offline recall test (not in this repository) suggested the block's "No match ... proceed without
a skill" discards the finder's "nearest by words" list, which holds the target first for 77% of requests. A live A/B (Sonnet, 9 requests
where the target is the first nearest entry, 12 where nothing fits) showed the block as it is already works: 8 of 9 targets opened
with and without an amendment that allows opening the first nearest entry, no skill opened when nothing fits. The models search again
and judge the nearest list's descriptions themselves. The one target neither arm found (a tracking-parity skill) never reached the
output: that is a vocabulary gap, the thing to look at if recall needs work.
