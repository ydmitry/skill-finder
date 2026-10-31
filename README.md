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
