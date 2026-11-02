# skill-finder

A Claude Code skill that finds which installed skill fits a task when you do not know which one exists. It searches every skill on the
machine (user, project, and all plugin skills, enabled, disabled or not installed), lists the best matches with the lines that matched
and their reference files, and can copy chosen skills into a run folder so a fresh session can invoke them. `SKILL.md` is the skill;
`scripts/find_skills.py` is the finder (Python 3, standard library only; PyYAML is used for the front matter when it is installed).

```
python3 scripts/find_skills.py --task "heap snapshot memory leak"        # keyword ranking
python3 scripts/find_skills.py --phrase "implementation plan"           # exact phrase in the whole SKILL.md of every skill
python3 scripts/find_skills.py --list                                   # the whole inventory
python3 scripts/find_skills.py --enable NAME --into DIR                 # copy a skill into DIR/.claude/skills for one run
```

## Install

Copy this folder to `~/.claude/skills/skill-finder` (or a project's `.claude/skills/`). To add more skill folders to the search, copy
`scripts/roots.example` to `scripts/roots`.

## Needs an instruction in your CLAUDE.md

Installing the skill is not enough: Claude will not reach for it by itself. In tests with Claude Haiku and Sonnet (not part of this
repository), a `SKILL.md` description that says "use at the start of EVERY task" got the skill called in 0 of 232 runs. The models call
the skill whose topic matches the task (a chart skill for a chart) and never a skill whose job is to look for skills. On a machine with
many skills Claude Code also drops the description of the ones you never invoke, so the skill is often listed by name alone.

What works better is a standing instruction in the system instructions, next to the work. Put this in your global `~/.claude/CLAUDE.md`
(or a project's `CLAUDE.md`), and change the path if you installed the skill elsewhere:

```
## Skills
Before the first edit of a task, and again when the work turns to a new tool, file type, service or document kind, look the skills up by phrase:
  python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<two or three words, in order>"
It lists the skills whose SKILL.md contains the phrase, best first. Look up several phrases, each from a different angle: what the work is about; what the finished thing is called; how one goes about it; its shape. Leave proper nouns out.
Open the best match's SKILL.md before writing anything, and follow it. Search again only if it does not fit. No match, or a LOW CONFIDENCE one, means proceed without a skill. Skip for one-line answers and when the task names its skills.
```

It costs about 220 tokens in every session. What to expect: with this text in the global `CLAUDE.md`, Sonnet ran the finder before its
first edit in 8 of 8 test tasks and in none of 4 one-line questions. With the lookup allowed it then opened a skill from the list in 6 of 8;
in 4 of those it was a skill it opens without the finder, and for the task whose best skill is not in its own skill list (a colour theme)
it opened the finder's pick in 2 of 2. Subagents read the same file and did the same in 8 of 8 delegated tasks, at about three lookups each
before their first edit; a coordinator that only handed the task over looked nothing up (0 of 8), so those lookups stay out of the main
conversation. In placement tests with Haiku the worker searched every time with this text in
`CLAUDE.md`, but opened the skill it found in about 9 of 15 runs; the same text in the goal of a delegated run did better (14 of 15). The
line "open the best match's SKILL.md before writing anything" has not been measured. To see whether it works for you, count in your session
logs how often `find_skills.py` runs and whether a skill it listed is invoked afterwards.

Skills the session lists by name alone: three such skills, five Sonnet runs each, with and without this text. The model opened the right
skill in all fifteen runs either way, because the names say what the skill does and it calls the skill by its name. So this test shows no
gain from the finder for readable names, and no harm. Name-only skills with names that say nothing are untested (the one tried needed an
API key that did not work and was dropped). For skills that keep their description, the two arms opened the right one in 23 and 25 of 25
runs, a difference of one task (3 of 5 to 5 of 5). The gain that is measured is for a skill the model's own list lacks entirely (the colour
theme, above). Three skills and one model, with requests written from each skill's own text, and the model often needed several phrases
(about one phrase in three listed the skill) to get there: a direction, not a rate.

## Tests

```
python3 -m unittest discover -s tests
```

`tests/test_ranking.py` holds the golden queries; `tests/fixtures/skills` is the small skill set they run against.

## Status

Experimental. The finder lists candidates by keywords or by an exact phrase; it does not decide. Experiments on whether a worker
opens the right skill (not part of this repository) found that where the instruction to search sits matters, and that a best-match block
after a phrase search did not beat a plain instruction. `TODO.md` lists what is open.

## License

MIT
