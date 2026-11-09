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
python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<two or three words in order>" [--phrase "<another>" ...] [--limit 40]
```

A phrase works when its words are common but the phrase is not ("implementation plan", "task breakdown", "color palette").
Look up several phrases, each from a different angle: what the work is about; what the finished thing is called; how one
goes about it; its shape. Leave proper nouns out.

It looks for the exact phrase in the whole `SKILL.md` of every skill, body included, and lists up to 10, three short lines
each (name, state, path; the start of the description; the line that matched), best first: a phrase in the name, then in
the description, then how often it occurs. Quotes are optional for words that follow `--phrase` after a space:
`--phrase release notes` is one phrase. Several `--phrase` are alternatives, and a skill holding more of them comes first.
It says how many skills match; when more than 10 do, use a longer phrase, or `--limit 40` to list more. Skills that hold the phrase only in their reference
files (`.md`/`.txt` in the skill's folder, `references/` first, no log, test or hidden folders, up to 120 files of up to
2 MB a skill) follow, up to 5, with the file and line: open that skill's `SKILL.md`, then the file. When no `SKILL.md` holds
it, those come first; then it says how many skills hold each word of the phrase in `SKILL.md` or reference files (a word
held by none is not how any skill says it) and lists up to 10 skills nearest by words, not repeating those above, the first
3 with their descriptions: use fewer words or the other form of the word, or open one of them if it fits.

`--task` is the other way in, a keyword ranking for when no phrase fits or the need takes several words to say:

```
python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --task "<search words for one need>" [--top 8]
```

Write the `--task` words yourself, one run per need, not the person's sentence pasted whole. Use the words a skill's
description would use for what it DOES ("loop", "unattended", "until done", "GraphQL mutation", "heap snapshot"), plus
the tool, error or file type. Words found in over a fifth of all skills ("test", "fix", "page") are dropped by the ranker
unless they are all there is, so they only add noise. On this machine "keep fixing the failing tests until they pass"
ranks playwright-iterate first, and "loop until command exits 0 bounded fresh sessions" ranks subgoal first by a wide margin. `--phrase` and `--task` are not combined.

**Tables of contents.** `--toc` prints every skill as `name — first sentence` grouped by folder (roughly 30 tokens a skill, 6 with `--kind names`); `--toc <folder>` one group; `--toc <skill>` that skill's path and header outline with line numbers, `--kind files` its files. `--phrase "<words>" --toc` prints the hits as sections (`SKILL.md` only, no reference files), one sentence each, with no best match, and ends with the `--toc "<name>"` command that prints a hit's path. `--phrase` without `--toc` stays the first lookup: in tests the table and the sections did not find the right skill more often than it.

Both scan user skills, project skills (`.claude/skills` up from the cwd) and every plugin's skills in each
config dir (`~/.claude`, and `$CLAUDE_CONFIG_DIR` when set): enabled plugins, DISABLED plugins, installed-but-unlisted ones,
and marketplace folders of plugins never installed. A `--phrase` hit is three short lines (name, state, path; the start of the description; the line that matched). A `--task` hit shows its state, source, path, the whole
description (cut at 1,500 characters, and it says so), the lines that matched with `file:line`, and its reference files with their first heading. Copies of one skill are shown
once, with "also at" where their labels differ: identical files, versions of one plugin, a user skill in both config folders,
or the same name with the same description. Two different skills that share a name are both shown, unless they sit in one plugin. `--phrase` and `--task` leave out
skill-finder itself, whose README and notes hold the example phrases and would match most lookups: its own folder, a copy of its `SKILL.md`, and a skill of its name with
`scripts/find_skills.py` beside it (another version installed apart); `--list` prints the whole inventory, and `--toc` without `--phrase` shows it too. `--only DIR` (repeatable) scans only the skills
in `DIR/<name>/`, nothing from the config dirs or the project: for tests and fixture folders. A file
`scripts/roots` (one folder per line, `#` comments; copy `scripts/roots.example`; machine-local, not committed) adds more
folders, like `--root`. The `--task` ranking is by keywords, so it finds candidates; it does not decide. A `LOW CONFIDENCE` line
means the top hit is weak: under two task words in its name or description and not clearly ahead of the next hit, or
only very common words: search again with a word for what the finished thing is called (its kind or format) or for the method,
or search an exact phrase with `--phrase` before deciding "none apply". A line "dropped as too common to rank" names the task words that did not count.
`tests/test_ranking.py` holds the golden queries.

What it cannot see: Claude Code's bundled skills (for example dataviz, code-review, loop) and `~/.claude/commands`
are not on disk. Your own session's skill list is the ground truth for what you can invoke right now, so check it
too. The state labels come from the install records and the settings a session started in the current folder reads (a folder
whose own settings enable a plugin gets it; the config dir not in use is labelled by its own `settings.json`), and can disagree
with a live session. A user or project skill that `skillOverrides` there hides or shortens (an entry under its folder name, not
its frontmatter `name`) reads `user skill, off in settings` (hidden from Claude and from the `/` menu), `user skill,
user-invocable only in settings` (only the person can invoke it) or `user skill, name only in settings`,
and `project skill, ...` alike; plugin skills are not affected.

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
project skill. That also puts the copy under `skillOverrides` by its folder name, the skill's bare name: `off` or
`user-invocable-only` for that name in a file a session in DIR reads (your `settings.json`, DIR's `.claude/settings.json` or
`settings.local.json`, or the `settings.local.json` at DIR's repo root, for a linked worktree the main checkout's root, so an
entry the `/skills` menu saved there reaches a worktree DIR) keeps Claude from invoking the copy. The same entry also hides the original wherever
that file is read (always for a user skill, or for an entry in your `settings.json`); for a plugin skill only the copy is hidden, since `skillOverrides` does not apply to plugin skills. One in another project's files (the `/skills` menu saves to that project's
`.claude/settings.local.json`) does not reach DIR. A user skill in a folder of that name runs instead of the copy (personal
beats project). When two skills share a name, `--source` picks one by part of its source label or its path. Nothing global changes: it never edits `settings.json`. Use a run folder or worktree for DIR,
not a repo the person works in. If it prints a `WARNING` line, say so in the report: `refers to CLAUDE_PLUGIN_ROOT` (that
skill's scripts may not work from the copy), `skillOverrides sets ...` (Claude cannot invoke the copy) or `a user skill of that
name is at ...` (a session in DIR runs that one). Turning a plugin on for every session is the person's call
(`enabledPlugins` in settings); never do it unasked.
