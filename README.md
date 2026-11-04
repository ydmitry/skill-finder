# skill-finder

**Maybe someone in your org already wrote a skill for this.**

Your company keeps Claude Code skills in a few repos or plugin marketplaces. You haven't read them all, and you won't install
them all. But for the task in front of you, one may already exist. skill-finder searches every skill on your machine
(installed, disabled, or never installed) plus any skill repo you have cloned and listed for it. It lists the skills that
contain the words Claude looks up, each with its path and the line that matched. Claude can then read the one that fits, or
you can copy it into a folder you start a fresh session in. It never edits `settings.json`; the only global change is the
`CLAUDE.md` lines you add.

Claude will not reach for the finder by itself, so it comes with a short instruction for your `CLAUDE.md` (below).

## What a lookup looks like

```
$ python3 scripts/find_skills.py --phrase "release notes" --only tests/fixtures/skills
phrase search: "release notes" in the SKILL.md of 18 skills on disk (a phrase starts a word: 'plan' matches 'planning', not 'airplane')
1 skill(s) contain it. Best first: the phrase in the name, then in the description, then how often it occurs.

1. release-notes  [folder skill]  tests/fixtures/skills/release-notes/SKILL.md
   Draft release notes and changelog entries from merged pull requests.
   :6: # release-notes

Best match: release-notes  tests/fixtures/skills/release-notes/SKILL.md
Why: "release notes" is in its name and its description and 3 times in SKILL.md (line 6: "# release-notes")
Description: Draft release notes and changelog entries from merged pull requests.
First lines of SKILL.md:
  # release-notes

  Group by change type.
Read tests/fixtures/skills/release-notes/SKILL.md, then follow it; search again only if it does not fit.
```

That is the repo's test fixtures. On your machine each hit shows its state, such as `user skill`, `project skill`, `plugin
enabled`, `plugin DISABLED`, `marketplace only, not installed`, or `extra root` (a folder you added, which Claude Code itself
does not load). The states come from `settings.json` and the install records and can disagree with a live
session. A skill Claude Code does not load can be read from its path, or copied with `--enable NAME --into DIR` into
`DIR/.claude/skills`, so a session started in `DIR` can invoke it (a plugin skill whose scripts use `CLAUDE_PLUGIN_ROOT` may
not work from the copy; the finder warns).

## Set up

1. **Install the skill.** `git clone https://github.com/ydmitry/skill-finder ~/.claude/skills/skill-finder` (or copy the
   folder to a project's `.claude/skills/`). Python 3, standard library only; PyYAML is used for the front matter when it is
   installed. The `CLAUDE.md` block below calls the script directly; the skill's own `SKILL.md` is for when you or Claude
   invoke `skill-finder` for a fuller search and a report on which skill to use and how.
2. **Point it at your org's skills.** It already scans user skills, project skills (`.claude/skills` up from the working
   folder) and every plugin's skills in each config dir (`~/.claude`, and `$CLAUDE_CONFIG_DIR` when set): enabled plugins,
   disabled ones, installed-but-unlisted ones, and the marketplace folders of plugins you never installed, under
   `plugins/marketplaces`. So a marketplace that Claude Code cloned when you added it is searched as it is. For a skill repo
   that is not a marketplace, clone it once and add its folder (for a marketplace added from a local folder, that folder) to
   `scripts/roots` (copy `scripts/roots.example`; one folder per line, machine-local, not committed). It cannot see Claude
   Code's bundled skills.
3. **Add the instruction to your `CLAUDE.md`.** Put this in your global `~/.claude/CLAUDE.md` (or a project's `CLAUDE.md`),
   and change the path if you installed the skill elsewhere:

```
## Skills
Before the first edit of a task, and again when the work turns to a new tool, file type, service or document kind, look the skills up by phrase:
  python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<two or three words, in order>"
It lists the skills whose SKILL.md contains the phrase, best first. Look up several phrases, each from a different angle: what the work is about; what the finished thing is called; how one goes about it; its shape. Leave proper nouns out.
Open the best match's SKILL.md before writing anything, and follow it. Search again only if it does not fit. No match, or a LOW CONFIDENCE one, means proceed without a skill. Skip for one-line answers and when the task names its skills.
```

`LOW CONFIDENCE` is a line the keyword search (`--task`) prints when its best hit is weak; `--phrase` never prints it, and
the line stays because this is the text that was tested. The block costs about 220 tokens in every session. In a Haiku test,
the same text in the goal you hand a background worker did better than in `CLAUDE.md` (below). To see whether it works for
you, count the transcripts in which Claude ran the finder:

```
grep -rl --include='*.jsonl' '"name":"Bash".*find_skills\.py' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" | wc -l
```

and look at whether a skill it listed is invoked afterwards.

## Does it work?

In short: it helps Claude find and open skills it could not otherwise see, and adds little for skills Claude already lists.
The tests measure whether Claude ran the finder and opened the skill, not whether the work came out better. They were run
with Claude Haiku and Sonnet, their harness is not published (it is not part of this repository), and they are small: read
them as directions, not rates.

**Skills you have not installed** are the finder's main job. Ten skills from public repos that were not installed, and
requests written without any word of the skill's name or description (rejected by a check, then confirmed blind by a second
model that picked the right skill first for 8 of 10). Without the instruction, Sonnet ran the finder in none of 30 runs and
opened none of those skills. With it, it ran the finder in all 50 runs, had the target in a list in 78% of them, opened the
exact skill in 68% and some skill it could not otherwise see in 88%. Seven of the ten skills were opened in four or five of
five runs; two of the misses were requests that fit another unseen skill as well, one was a short skill whose words the
request did not share. Ten skills, one model, the first turn only (nothing is written, so whether the skill was followed is
not measured), and requests written by a model that had read each skill: a direction, not a rate.

**Why the instruction is needed.** A `SKILL.md` description that says "use at the start of EVERY task" got the skill called
in 0 of 232 runs. The models call the skill whose topic matches the task (a chart skill for a chart) and never a skill whose
job is to look for skills. On a machine with many skills Claude Code also drops the description of the ones you never
invoke, so the skill is often listed by name alone. What works better is a standing instruction in the system
instructions, next to the work.

**What the instruction does.** With it in the global `CLAUDE.md`, Sonnet ran the finder before its first edit in 8 of 8 test
tasks and in none of 4 one-line questions. With the lookup allowed it then opened a skill from the list in 6 of 8; in 4 of
those it was a skill it opens without the finder, and for the task whose best skill is not in its own skill list (a colour
theme) it opened the finder's pick in 2 of 2. Subagents read the same file and did the same in 8 of 8 delegated tasks, at
about three lookups each before their first edit; a coordinator that only handed the task over looked nothing up (0 of 8),
so those lookups stay out of the main conversation. In placement tests with Haiku the worker searched every time with this
text in `CLAUDE.md`, but opened the skill it found in about 9 of 15 runs; the same text in the goal handed to a background
worker did better (14 of 15). The line "open the best match's SKILL.md before writing anything" has not been measured.

**Skills the session already lists** gain little. Three skills the session lists by name alone, five Sonnet runs each, with
and without the instruction: the model opened the right skill in all fifteen runs either way, because the names say what
the skill does and it calls the skill by its name. So that test shows no gain from the finder for readable names, and no
harm. Name-only skills whose names say nothing are untested. For skills that keep their description, the two arms opened
the right one in 23 and 25 of 25 runs, a difference of one task (3 of 5 to 5 of 5). So it pays off most when your org's
skills are on disk (a marketplace or a cloned repo) but not installed.

## Commands

```
python3 scripts/find_skills.py --phrase "implementation plan"           # exact phrase in the whole SKILL.md of every skill
python3 scripts/find_skills.py --task "heap snapshot memory leak"        # keyword ranking
python3 scripts/find_skills.py --list                                   # the whole inventory
python3 scripts/find_skills.py --toc [FOLDER|SKILL] [--kind names|sentence|description|headers|files]   # tables of contents
python3 scripts/find_skills.py --phrase "..." --toc   # the hits as sections
python3 scripts/find_skills.py --enable NAME --into DIR                 # copy a skill into DIR/.claude/skills for one run
```

`--phrase` is the recommended lookup and the one the `CLAUDE.md` block uses; `--toc` is an optional way to browse.
`SKILL.md` is the skill: it tells Claude how to search, read the best matches and their reference files, and report which
skill to use and how. `scripts/find_skills.py` is the finder.

## Tests

```
python3 -m unittest discover -s tests
```

`tests/test_ranking.py` holds the golden queries; `tests/fixtures/skills` is the small skill set they run against.

## Status

Experimental. The finder lists candidates by keywords or by an exact phrase; it does not decide. Experiments on whether a worker
opens the right skill (not part of this repository) found that where the instruction to search sits matters, and that the
best-match block a phrase search prints (shown above) did not beat a plain instruction. `TODO.md` lists what is open.

## License

MIT
