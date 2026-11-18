# Does Claude find the right skill? What my evals showed

Claude Code rarely reads the skill a task needs unless it is told to look. In my tests it opened the needed skill in 2 of 58 tasks on Haiku and 7 of 58 on Sonnet. One paragraph in `CLAUDE.md` changed that to 47 and 40. A ten-task sample on Opus went the same way.

The paragraph tells Claude to search its skills first, with my script skill-finder ("the finder") or with a plain `grep`. Both did about equally well. These are test tasks, not real work. [Jump to the instruction.](#the-instruction-to-put-in-claudemd)

![Of 58 tasks on Haiku, the needed skill was opened in 2 with no instruction and in 47 with the instruction in CLAUDE.md, where a lookup ran first in 54 tasks.](figures/flow.svg)

## When this matters

- With many skills, Claude gets only their names and short descriptions, and rarely opens the right one. I tested with 151 and 897 skills, not with a few dozen.
- When a team keeps its conventions in skills, Claude cannot follow a rule it has not read.
- When a task needs a second skill you could not name at the start: a review opens a file, and the file touches something that has its own rules.

## The instruction to put in `CLAUDE.md`

Put this in `~/.claude/CLAUDE.md` or in a project's `CLAUDE.md`. Get the script first: `git clone https://github.com/ydmitry/skill-finder ~/.claude/skills/skill-finder`.

```
## Skills
Before you write code, a plan, a review or any other piece of work, look the skills up. First read the request and every file it names. List what appears in them: the things, activities, materials and technologies, and what the finished thing is called. Look all of them up in one plain command (no loop, no variable), one --phrase for each, two or three words in order. Run it as a command of its own, not joined to other commands:
  python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<a name>" --phrase "<another name>"
It lists the skills and the reference files that hold a phrase. Read every listed skill that fits to the end, and every listed reference file that fits, and the reference files in a skill's folder that fit, before writing anything. Follow what they say. Nothing listed that fits means proceed without a skill. Skip for one-line answers and when the task names its skills.
The lookup is not one step. After you read a skill or a reference file, look up, the same way, every thing, area or kind of data it mentions that your earlier lookups did not cover. Do this before you write, and again after each new file you read. If a lookup lists nothing that fits, try other words.
```

The last paragraph tells Claude to look up again after each file it reads. I call it look-again below.

<details>
<summary>The grep version, without the finder</summary>

The same instruction with grep. I tested a close version of it, not this exact text.

```
## Skills
Before you write code, a plan, a review or any other piece of work, look the skills up. First read the request and every file it names. List what appears in them: the things, activities, materials and technologies, and what the finished thing is called. Look all of them up in one plain command (no loop, no variable), one -e for each, two or three words in order. Run it as a command of its own, not joined to other commands:
  grep -Ril --include=SKILL.md -e "<a name>" -e "<another name>" ~/.claude/skills
It lists the skill files that hold a phrase. Read every listed skill that fits to the end, and the reference files in its folder that fit, before writing anything. Follow what they say. Nothing listed that fits means proceed without a skill. Skip for one-line answers and when the task names its skills.
The lookup is not one step. After you read a skill or a reference file, look up, the same way, every thing, area or kind of data it mentions that your earlier lookups did not cover. Do this before you write, and again after each new file you read. If a lookup lists nothing that fits, try other words.
```

Add your other skill folders to the command. On macOS add `-S` if they are symlinks.

</details>

## What I tested

Two suites, on Haiku, Sonnet and Opus: the small, the mid-size and the largest Claude model.

The first is local rules: twelve skills written for the test, for an imaginary team, hidden among 897 public skills. Each skill holds made-up rules with an ID, which Claude cannot guess. For example, rule API-14 says the URL of an endpoint for a partner must start with `/px/`. Each of 24 tasks, a plan or a review, needs three rules from three skills. A rule counts as followed when its ID appears in the answer.

![The local-rules suite: 12 skills holding local rules are hidden among 897 public skills, and each task needs rules from 3 of the 12.](figures/haystack.svg)

The second is 58 tasks from Skill-Use-Bench (arXiv 2608.04828), each with a skill its authors say it needs. "Opened" means the skill's text reached Claude. These are not the benchmark's official scores.

Haiku and Sonnet ran everything. Opus ran ten tasks from each suite, because it costs more.

I wrote a pass rule before each comparison: here, a gap of 15 percentage points that also passes a sign test. "Not shown" below means the rule was not met.

## The instruction does the work

Without it Claude almost never found the skill. With it, Claude found most of them, on all three models. All six comparisons met their pass rule.

![With the instruction, the needed skill was opened in 47 of 58 tasks on Haiku, 40 of 58 on Sonnet and 9 of 10 on Opus, against 2, 7 and 1 without it; local rules followed went from 0 to 76 of 144, 98 of 144 and 24 of 30.](figures/opened.svg)

Does the work itself get better? A little, on thin evidence. 21 benchmark tasks ship checks on the finished files. The average task passed 63% of them on Haiku (51% without the instruction) and 64% on Sonnet (49% without).

### Does it need a lookup command?

Earlier Sonnet tests on the local rules, with older wordings. They have their own runs, so do not compare them with the numbers above.

![On Sonnet with 897 skills, local rules followed went from 0 of 144 with no instruction to 75 when told to check the skills with no command, 78 with a lookup step and 101 with look-again; the gaps among the three instructions were not shown in this test.](figures/sonnet.svg)

Just telling Claude to check its skills, with no command, already scored 75 of 144. A lookup step scored 78, and 101 with look-again. None of the gaps among the three met that test's rule.

A later test of look-again alone gave 182 against 144 of 216 rules. I count that as likely, not settled: I wrote its pass rule after I had seen earlier results.

## Skills needed mid-task

One of each local-rules task's three rules is "chained". The only pointer to its skill is a sentence inside the first skill Claude reads, so Claude has to look up again in the middle of the task.

![With the instruction and the finder at 897 skills, Claude looked up again after reading a skill in 42 of 48 runs on Haiku, 31 of 48 on Sonnet and 9 of 10 on Opus, and followed the chained rule in 21 of 48, 35 of 48 and 8 of 10, against 0 with no instruction.](figures/chain.svg)

Without the instruction Claude followed no chained rule: it never opened the first skill. With it, Claude followed the chained rule in 21 of 48 runs on Haiku, 35 of 48 on Sonnet and 8 of 10 on Opus.

Looking again is not the same as finding. Haiku looked up again most often and followed the fewest chained rules. And every run had look-again, so this does not show that the paragraph is the cause.

What does plain Claude Code do once a skill is installed and the need shows up mid-task? In a separate small test with eight skills, it depended on the skill's description:

| Description says | Haiku | Sonnet |
|---|---|---|
| "Use ALWAYS, every time, when ..." | 19 of 47 | 14 of 15 |
| "Rules for X." | 0 of 23 | 3 of 13 |

With 200 skills in the list, Haiku used the skill in 1 of 24 runs.

## Finder or grep

I ran the same instruction with `grep` in place of the finder.

![Finder minus grep in percentage points: local rules Haiku +1, Sonnet +3; needed skill opened Haiku +3, Sonnet -2. No gap comes near the 15-point threshold.](figures/finder-vs-grep.svg)

No gap came near the pass rule, on any model. Both suites suit grep: the folder held only skills, and their names say what they hold.

I use the finder because one command covers every skill folder and lists reference files. These tests do not show it opening more skills than grep.

Installing the finder as a skill, without the instruction, did nothing: Haiku never called it.

## What to do

Add the instruction. If you would rather install nothing, use the grep version.
