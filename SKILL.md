---
name: skill-finder
description: >-
  Use when a task might fit an installed skill and you do not know which, before a long or delegated run (subgoal, a
  subagent, a fresh session), or when asked "which skill can do this", "what skills do I have for X", or to switch some
  skills on for one run. Searches every skill on the machine (user, project, and all plugin skills, enabled, disabled or
  not installed), reads the best matches and their references, and writes a report: which skill, how to use it for this
  task, which reference files to read first. Can copy chosen skills into a run folder so a fresh session can invoke
  them.
---

# skill-finder

Find the skills that fit one task, say how to use them, and (when asked) switch them on for one run only.

## 1. Search

```
python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --task "<search words for one need>" [--top 8]
```

Write the `--task` words yourself, one run per need, not the person's sentence pasted whole. Use the words a skill's
description would use for what it DOES ("loop", "unattended", "until done", "GraphQL mutation", "heap snapshot"), plus
the tool, error or file type. Words found in over a fifth of all skills ("test", "fix", "page") are dropped by the ranker
unless they are all there is, so they only add noise. On this machine "keep fixing the failing tests until they pass"
ranks playwright-iterate first, and "loop until command exits 0 bounded fresh sessions" ranks subgoal first by a wide margin.

A phrase search is the other way in, for when the words are common but the phrase is not ("implementation plan", "task
breakdown", "color palette"):

```
python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<two or three words in order>" [--phrase "<another>" ...] [--limit 40]
```

It looks for the exact phrase in the whole `SKILL.md` of every skill, body included, and lists up to 40, three short lines
each (name, state, path; the start of the description; the line that matched), best first: a phrase in the name, then in
the description, then how often it occurs. Several `--phrase` are alternatives, and a skill holding more of them comes
first. It says how many skills match: over 40, use a longer phrase. When none match, it says how many skills hold each
word of the phrase (a word held by none is not how any skill says it) and lists the 10 skills nearest by words, the first
3 with their descriptions: use fewer words or the other form of the word, or open one of them if it fits. `--phrase` and `--task` are not combined.

Both scan user skills, project skills (`.claude/skills` up from the cwd) and every plugin's skills in each
config dir (`~/.claude`, and `$CLAUDE_CONFIG_DIR` when set): enabled plugins, DISABLED plugins, installed-but-unlisted ones,
and marketplace folders of plugins never installed. Each hit shows its state, source, path, the whole description (cut at 1,500 characters, and it says so), the
lines that matched with `file:line`, and its reference files with their first heading. Identical copies are shown
once, with "also at". `--list` prints the whole inventory. `--only DIR` (repeatable) scans `DIR/<name>/SKILL.md`
alone, nothing from the config dirs or the project: for tests and fixture folders. A file
`scripts/roots` (one folder per line, `#` comments; copy `scripts/roots.example`; machine-local, not committed) adds more
folders, like `--root`. The ranking is by keywords, so it finds candidates; it does not decide. A `LOW CONFIDENCE` line
means the top hit is weak: under two task words in its name or description and not clearly ahead of the next hit, or
only very common words: search again with a word for what the finished thing is called (its kind or format) or for the method,
or search an exact phrase with `--phrase` before deciding "none apply". A line "dropped as too common to rank" names the task words that did not count.
`tests/test_ranking.py` holds the golden queries.

What it cannot see: Claude Code's bundled skills (for example dataviz, code-review, loop) and `~/.claude/commands`
are not on disk. Your own session's skill list is the ground truth for what you can invoke right now, so check it
too. The state labels come from `settings.json` and the install records and can disagree with a live session.

## 2. Read, then decide

Open the `SKILL.md` of the top few that could apply, and the reference files they say to read for this kind of
task. Do not read every candidate. A keyword hit is not a fit: the migration skills that rank for any task
mentioning "library" are noise. If nothing fits, the answer is **none**; say so.

## 3. Write the report

```
# Skills for: <the task>
## Use
1. <skill> [<state>] — why it applies (quote file:line)
   How for this task: <the steps that matter, from the skill>
   Read first: <reference path> (why), then <reference path>
   Check afterwards: <its gates, required steps, commands to run>
   Invoke: Skill tool `<name>`  |  not invokable here (disabled / not installed): read <path>, or --enable it
## Considered, not used
- <skill> — one line why not
## None apply     (write only when that is the answer)
```

Every statement about what a skill says carries a `file:line`; do not paraphrase from the description alone. When
the report goes to a worker (subgoal goal, subagent prompt), give it to the worker only, never to a judge or
reviewer: advice in an acceptance bar becomes extra demands.

## 4. Switch skills on (only when asked, or when the report says "not invokable here")

```
python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --enable NAME [NAME ...] --into DIR [--source TEXT]   # copies to DIR/.claude/skills/NAME
python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --remove --into DIR                               # takes back what --enable put there
```

This works for a disabled or never-installed plugin's skill, because a session started in DIR sees the copy as a
project skill. Nothing global changes: it never edits `settings.json`. Use a run folder or worktree for DIR,
not a repo the person works in. If it prints `WARNING: refers to CLAUDE_PLUGIN_ROOT`, that skill's scripts may
not work from the copy; say so in the report. Turning a plugin on for every session is the person's call
(`enabledPlugins` in settings); never do it unasked.
