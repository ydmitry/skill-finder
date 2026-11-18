# Does Claude find the right skill? What my evals showed

Claude Code rarely reads the skill a task needs unless it is told to look. In my tests it opened the needed skill in 2 of 58 tasks on Haiku and 7 of 58 on Sonnet, the small and the mid-size Claude model. One paragraph in `CLAUDE.md` that says to look the skills up first changed that to 47 and 40. A ten-task sample on Opus, the largest model, went the same way.

The lookup can be my search script, skill-finder ("the finder" below), or a plain `grep`. The finder was ahead only for skills that are on disk but not installed. Everything here comes from test tasks, not from real work. [Jump to the instruction.](#the-instruction-to-put-in-claudemd)

![Of 58 tasks on Haiku, the needed skill was opened in 2 with no instruction and in 47 with the instruction in CLAUDE.md, where a lookup ran first in 54 tasks.](figures/flow.svg)

## The instruction to put in `CLAUDE.md`

Put this in `~/.claude/CLAUDE.md` (all projects) or in one project's `CLAUDE.md`. It needs the finder script: `git clone https://github.com/ydmitry/skill-finder ~/.claude/skills/skill-finder`, or change the path in the instruction.

```
## Skills
Before you write code, a plan, a review or any other piece of work, look the skills up. First read the request and every file it names. List what appears in them: the things, activities, materials and technologies, and what the finished thing is called. Look all of them up in one plain command (no loop, no variable), one --phrase for each, two or three words in order. Run it as a command of its own, not joined to other commands:
  python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<a name>" --phrase "<another name>"
It lists the skills and the reference files that hold a phrase. Read every listed skill that fits to the end, and every listed reference file that fits, and the reference files in a skill's folder that fit, before writing anything. Follow what they say. Nothing listed that fits means proceed without a skill. Skip for one-line answers and when the task names its skills.
The lookup is not one step. After you read a skill or a reference file, look up, the same way, every thing, area or kind of data it mentions that your earlier lookups did not cover. Do this before you write, and again after each new file you read. If a lookup lists nothing that fits, try other words.
```

"Reference files" are the other files in a skill's folder. The last paragraph tells Claude to look up again after each file it reads ("look-again" below). It probably helps; the evidence is under the earlier Sonnet tests.

The three-model results below ran this text. One difference: the command was a short wrapper, `skill-find`, around the same script. Some older Sonnet tests ran earlier wordings, and their sections say so.

<details>
<summary>The grep version, without the finder</summary>

The same instruction with three sentences changed. I ran a close version of it on all three models (it searched one folder, and listed reference files too). I did not run this exact text with a model.

```
## Skills
Before you write code, a plan, a review or any other piece of work, look the skills up. First read the request and every file it names. List what appears in them: the things, activities, materials and technologies, and what the finished thing is called. Look all of them up in one plain command (no loop, no variable), one -e for each, two or three words in order. Run it as a command of its own, not joined to other commands:
  grep -Ril --include=SKILL.md -e "<a name>" -e "<another name>" ~/.claude/skills
It lists the skill files that hold a phrase. Read every listed skill that fits to the end, and the reference files in its folder that fit, before writing anything. Follow what they say. Nothing listed that fits means proceed without a skill. Skip for one-line answers and when the task names its skills.
The lookup is not one step. After you read a skill or a reference file, look up, the same way, every thing, area or kind of data it mentions that your earlier lookups did not cover. Do this before you write, and again after each new file you read. If a lookup lists nothing that fits, try other words.
```

Add your other skill folders to the command: a project's `.claude/skills` and your plugin folders. Search `SKILL.md` files only, or a phrase also matches files that are not skills. On macOS, `grep -R` skips symlinked folders: add `-S` if your skill folders are symlinks.

</details>

## What I tested

The question: given hundreds of skills, does Claude open the right one, and is the finder what makes it do so? I used two suites.

### Suite 1: local rules

Twelve skills written for this test (by AI agents, checked by other agents) for an imaginary engineering team: API conventions, database migrations, background jobs and so on. Each skill holds local rules with an ID, rules that exist only in this team. One example, API-14: partner endpoints live under `/px/<partner>/<event>`, and the request stores the raw body and answers 204. Claude cannot know that rule without reading the skill.

The twelve are hidden among 897 public skills taken from open GitHub repositories.

![The local-rules suite: 12 skills holding local rules are hidden among 897 public skills, and each task needs rules from 3 of the 12.](figures/haystack.svg)

There are 24 tasks. In each, Claude writes a plan or reviews a file, and the task touches three rules, one from each of three skills. Each task ran twice: 24 x 3 x 2 = 144 chances to follow a rule. A rule counts as followed when its ID appears in the answer.

### Suite 2: benchmark tasks

A selection of tasks from Skill-Use-Bench (arXiv 2608.04828), lightly changed (asset folder renamed, environment note shortened). Each task has a skill the authors say it needs. I ran them two ways:

- **Installed, 58 tasks.** The skill's name is in the skill list, the names and short descriptions Claude Code hands the model at session start. With hundreds of skills, most descriptions are cut.
- **Not installed, 53 of the same tasks.** The skill's file is only on disk, as with a plugin that is switched off or a folder Claude Code does not load. Claude can reach it only by searching.

![A skill that is installed is in Claude's skill list; a skill that is not installed is only a file on disk. The list reaches only installed skills, a lookup with the finder or grep reaches both.](figures/where.svg)

These are not the benchmark's official scores, and none of its tasks or skills are republished here.

### Models and counting

Haiku and Sonnet ran every task. Opus ran a sample: ten tasks from each of the three sets, drawn at random before the runs, one run each. An Opus run costs two to three times a Sonnet run.

"Opened" means the skill's text reached Claude.

Before each comparison I wrote down a pass rule. In the three-model runs it was a gap of at least 15 percentage points that also passes a sign test: did one setup win in more tasks than chance allows (p of 0.05 or less)? Earlier tests used 10 to 30 points. "Not shown" means the rule was not met. It does not mean the two setups are equal.

## The instruction does the work

Without an instruction Claude almost never found the skill. With it, Claude found most of them, on all three models.

![With the instruction, the needed installed skill was opened in 47 of 58 tasks on Haiku, 40 of 58 on Sonnet and 9 of 10 on Opus, against 2, 7 and 1 without it; skills not installed and local rules went from 0 to most on all three.](figures/opened.svg)

| | Haiku | Sonnet | Opus (10 tasks) |
|---|---|---|---|
| Installed skill opened | 2 → 47 of 58 | 7 → 40 of 58 | 1 → 9 of 10 |
| Not-installed skill opened | 0 → 44 of 53 | 0 → 36 of 53 | 0 → 9 of 10 |
| Local rules followed | 0 → 76 of 144 | 0 → 98 of 144 | 0 → 24 of 30 |

Each cell reads: no instruction → with the instruction. All nine comparisons met their pass rule. Three notes:

- Zero for not-installed skills without the instruction is expected: Claude has no route to them.
- Sonnet opened fewer skills than Haiku with the instruction. I did not look into why.
- Opus's 24 of 30 is ten tasks x 3 rules, one run.

### Earlier Sonnet tests of the wording

These ran before the instruction had its final text, all on the local-rules suite. Each test has its own runs and its own wording, so compare numbers inside a test, not across tests or with the table above.

![On Sonnet with 897 skills, local rules followed went from 0 of 144 with no instruction to 75 when told to check the skills with no command, 78 with a lookup step and 101 with look-again; the gaps among the three instructions were not shown in this test.](figures/sonnet.svg)

- No instruction: 0 of 144.
- Told in five sentences to check its skills and open every one that fits, with no lookup command: 75.
- An earlier, shorter wording of the lookup step, with an earlier finder: 78.
- The same plus look-again: 101.

With 151 public skills in place of 897, the same test gave 32 of 144 with no instruction and 105 when told. So the effect is not only at 897.

Look-again was higher, but not by that test's 30-point rule. A later test of it alone (Sonnet, 897 skills, 24 tasks x 3 rules x 3 runs = 216) found 182 of 216 rules followed with it and 144 without it, ahead in 18 tasks and behind in 3. That met its rule. But I wrote the rule after seeing three earlier gaps on the same 24 tasks, so I count the gain as likely, not settled.

## Skills needed mid-task

Some skills turn out to be needed only after Claude has started reading. The local-rules suite has this built in. One of each task's three rules is "chained": nothing in the task points to its skill. The only pointer is a sentence inside the first skill Claude reads. To follow that rule, Claude has to look up again in the middle of the task.

![With the instruction and the finder at 897 skills, Claude looked up again after reading a skill in 42 of 48 runs on Haiku, 31 of 48 on Sonnet and 9 of 10 on Opus, and followed the chained rule in 21 of 48, 35 of 48 and 8 of 10.](figures/chain.svg)

These counts come from the same three-model runs as the table above (instruction with the finder, 897 skills):

| | Haiku | Sonnet | Opus (10 tasks) |
|---|---|---|---|
| Runs with another lookup after reading a skill | 42 of 48 | 31 of 48 | 9 of 10 |
| Chained rule followed | 21 of 48 | 35 of 48 | 8 of 10 |
| For comparison: the task's main rule followed | 37 of 48 | 37 of 48 | 8 of 10 |

With no instruction no chained rule was followed. With grep in place of the finder, the chained rule was followed in 20, 29 and 7.

Two cautions:

- Looking again is not the same as finding. Haiku looked up again most often and followed the fewest chained rules.
- Every one of these runs had the look-again paragraph. So they show that Claude does look up again and often reaches the second skill, not that the paragraph is the cause. The only with-and-without comparison is the Sonnet test above (182 against 144 of 216 rules). I set no pass rule for the counts in this section.

## The work changes too, a little

The benchmark ships file checks for 21 of the 58 installed-skill tasks: patterns the finished files must match. With the instruction, the average task passed 63% of its checks on Haiku (51% without) and 64% on Sonnet (49% without). An earlier Sonnet run with an earlier wording gave 78% against 48%. I set no pass rule for the current numbers.

This is the thinnest result here: 21 tasks, one run each. And a run can match a pattern without using the skill: with no instruction, about half the checks already pass.

## The finder against a plain grep

I ran the same instruction with `grep -ril` over the test's skill folder in place of the finder, on all three models.

![Finder minus grep in percentage points: local rules Haiku +1, Sonnet +3; installed skills Haiku +3, Sonnet -2; skills not installed Haiku +13, Sonnet +19. Only the Sonnet not-installed gap passes the 15-point threshold.](figures/finder-vs-grep.svg)

- **Installed skills and local rules: level.** Where the skill is installed, or its name says what it holds (the local-rules suite), grep matched the finder on both models.
- **Not-installed skills: the finder ahead.** On Sonnet it opened the needed skill in 36 of 53 tasks and grep in 26: ahead in 12 tasks, behind in 2 (p = 0.013). That met the pass rule. On Haiku it was 44 against 37, ahead in 9 and behind in 2 (p = 0.065), just short of the rule. Two models, same direction.
- **Opus sample: level.** 24 against 22 of 30 local rules, 9 against 9 of 10 installed, 9 against 9 of 10 not installed. Ten tasks cannot show a gap of the size above, or rule it out.

Installing the finder as a skill, without the instruction, did nothing: Haiku never called it in 159 runs across all three sets. I did not try that on Sonnet or Opus.

## What tuning did not do

I changed the instruction's wording and the finder's ranking several times, on Sonnet, on the 53 not-installed tasks. Neither was shown to open more skills.

- **Wording.** Telling Claude to run the lookup as a command of its own removed lookups joined to other commands (such as `cd x && skill-find ...`, which a stricter permission setup can refuse whole). On a 27-task subset, joined lookups fell from 25 tasks to none. The skill was still opened about as often: 18 of 27 with the new wording, 20 with the old.
- **Ranking.** Changes looked better when I re-ran, without a model, the search phrases Claude had typed in earlier runs. With the model, the needed skill was opened in 40 of 53 tasks with the new ranking and 37 with the old: no difference shown. I kept two small parts: a few extra near-match skills under the results, and longer descriptions on each result.

I then read by hand the 23 of those 53 tasks where some run missed the skill (no pass rule here).

![Of 53 not-installed tasks on Sonnet, 23 had a run that missed the skill: in 13 the lookup never listed it, in 7 it was listed and not opened, and 3 had other causes.](figures/misses.svg)

In 13 the lookup never listed the skill. In 7 it was on the list and Claude did not open it. The other 3 were no lookup at all, a cut-off list and a counting error.

## What this does not show

- **Real use.** In 26 of my own sessions in the nine days after I added the instruction, the finder ran in 6, and in 2 of those a listed skill was then used. I did not check whether the other 20 needed a skill or skipped the lookup. Each test task is built around one skill; real tasks often need none.
- **Cost.** I did not compare time or tokens with and without the instruction.
- **Small skill sets.** I tested at 151 and 897 skills, not fewer, where Claude's own skill list may be enough.
- **Tasks kept apart from the tuning.** I read the local-rules tasks and the 53 not-installed tasks while I changed the instruction and the finder.
- **Neutral prompts.** Some benchmark prompts were written with the skill in view. The 8 no-instruction opens in the earlier Sonnet run are skills whose names are nearly the task's own words.
- **A fair grep.** I ran it once on each model, in a first wording, over a folder holding only skills, inside an instruction tuned with the finder. I added it after I had seen the first Haiku results.
- **Opus beyond a sample.** Ten tasks a set, one run each. Each Opus run also had a higher spending limit (\$1.50) than the Haiku and Sonnet runs (\$0.60).
- **Small differences.** Two runs of the same setup differed by 2 to 5 tasks on Sonnet (I did not repeat a setup on Haiku or Opus), so gaps under about 8 tasks cannot be seen.
- **An outside count for every model.** A separate agent recounted the three-model Sonnet run from the raw files and got the same totals. Nobody but me recounted Haiku and Opus.
- **That "followed" is more than "cited".** A local rule counts as followed when its ID appears in the answer. In the three-model Sonnet run, 42 of the 96 runs with an instruction (48 with the finder, 48 with grep) cited 15 or more rule IDs, where a task needs three. So some of "followed" may be a long list of IDs.

## What to do

1. Start with the instruction above.
2. Install the finder if you keep skills that Claude Code does not load (plugins switched off, other folders). That is the one place it was ahead of grep: 36 against 26 of 53 on Sonnet, which met the pass rule, and 44 against 37 on Haiku, which fell just short.
3. If you would rather install nothing, the grep version is a reasonable start.

An instruction with no command at all (check your skills, open every one that fits) scored 75 against 78 for a lookup step on Sonnet, with no difference shown. But that was a test where each skill's name said what it held.
