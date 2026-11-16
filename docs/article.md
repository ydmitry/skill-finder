# Does Claude find the right skill? What my evals showed

Claude Code rarely opens the skill a task needs unless it is told to look: in my tests, 2 of 58 tasks on Haiku and 8 on Sonnet. A short instruction in `CLAUDE.md` to look the skills up first changes that: 47 and 40 of 58. The search tool I built was not shown to add much beyond the instruction: on Haiku, a plain `grep` in the same instruction was not shown to do worse. All of this comes from test tasks, not from real work. [Jump to the instruction.](#the-instruction-to-put-in-claudemd)

![On Haiku with no instruction Claude works from the session's skill list, which is mostly names, and opened the needed skill in 2 of 58 tasks. With the instruction in CLAUDE.md it ran a lookup step in 54 of 58 runs and opened the needed skill in 47 of 58 tasks.](figures/flow.svg)

## The instruction to put in `CLAUDE.md`

This is the whole recipe. It needs the finder script: clone [github.com/ydmitry/skill-finder](https://github.com/ydmitry/skill-finder) to `~/.claude/skills/skill-finder`, or change the path. Which wording each test ran is noted beside its result.

```
## Skills
Before you write code, a plan, a review or any other piece of work, look the skills up. First read the request and every file it names. List what appears in them: the things, activities, materials and technologies, and what the finished thing is called. Look all of them up in one plain command (no loop, no variable), one --phrase for each, two or three words in order. Run it as a command of its own, not joined to other commands:
  python3 ~/.claude/skills/skill-finder/scripts/find_skills.py --phrase "<a name>" --phrase "<another name>"
It lists the skills and the reference files that hold a phrase. Read every listed skill that fits to the end, and every listed reference file that fits, and the reference files in a skill's folder that fit, before writing anything. Follow what they say. Nothing listed that fits means proceed without a skill. Skip for one-line answers and when the task names its skills.
The lookup is not one step. After you read a skill or a reference file, look up, the same way, every thing, area or kind of data it mentions that your earlier lookups did not cover. Do this before you write, and again after each new file you read. If a lookup lists nothing that fits, try other words.
```

Without the finder, use a grep over your skill folders instead of the python command:

```
grep -Ril --include=SKILL.md -e "<a name>" -e "<another name>" ~/.claude/skills
```

Search `SKILL.md` files only: one phrase can match hundreds of other files. I did not run this exact form with a model.

## What I tested

"Skill finder" is my script that searches skill files by phrase. The question: given hundreds of skills, does Claude open the right one, and is the finder what makes it do so?

I used two suites. The first is the local-rules suite. I wrote twelve skills for an imaginary engineering team: API conventions, database migrations, background jobs and so on. Each skill holds local rules with an ID: rules that exist only in this team. One example, API-14: partner endpoints live under `/px/<partner>/<event>`, and the request stores the raw body and answers 204. Claude cannot know that rule without reading the skill.

I hid the twelve among 897 public skills. In 24 tasks Claude writes a plan or reviews a file, and each task touches three rules, one from each of three skills. Each task ran twice, so there are 24 x 3 x 2 = 144 chances to follow a rule. A rule counts as followed when its ID appears in the answer.

The second suite is a selection of tasks from Skill-Use-Bench (arXiv 2608.04828), lightly changed (asset folder renamed, environment note shortened). Each task has a skill the authors say it needs. In 58 tasks the skill is in the session's skill list. In 53 it is only on disk, reachable only by searching. These are not the benchmark's official scores, and none of its tasks or skills are republished here.

"Opened" means the skill's text reached Claude. Each comparison had a pass rule written before its runs: a difference counts only at 10 to 20 percentage points (15 for the Haiku tests) and a sign test, which asks whether one setup beat the other in more tasks than chance allows, with p of 0.05 or less. "Not shown" means the rule was not met, not that two setups are equal.

## The instruction does the work

Without any instruction Claude almost never found the skill. With it, Claude did, on both models.

![On Haiku the instruction raised the needed skill opened from 2 to 47 of 58 tasks when installed, and from no route to 44 of 53 when not installed, and local rules followed from 0 to 76 of 144.](figures/opened.svg)

On Haiku, the needed skill was opened in 2 of 58 tasks without the instruction and 47 with it. For skills that are not installed, no instruction means no route to them, so that case has no measurement.

On Sonnet, the same kind of instruction opened the needed skill in 40 of 58 tasks, against 8 with none (an earlier wording of the block).

On the local-rules suite at 897 skills, Sonnet followed none of the rules with no instruction and 75 of 144 with a plain sentence: "use the team's skills that fit". A lookup step scored 78, and 101 with a look-again paragraph. At 151 skills the same test gave 32 of 144 with no instruction and 105 with the plain sentence, so the gap is not specific to 900 skills.

![On Sonnet with 897 skills, local rules followed went from 0 of 144 with no instruction to 75 with a plain sentence, 78 with a lookup step and 101 with look-again; the gaps among the three instructions were not shown in this test.](figures/sonnet.svg)

Look-again led only in counts there. A later test of it alone, with a rule fitted after seeing the gap, found 182 against 144 of 216 rules, ahead in 18 tasks and behind in 3.

## The work changes too, a little

The benchmark ships file checks for 21 of the tasks: patterns the finished files must match. On Sonnet, 48% of the checks passed with no instruction and 78% with it. On Haiku it went from 51% to 63% (counts only).

This is the thinnest result here: 21 tasks, one run each. A run can match a pattern without using the skill, since no instruction already passes 48%.

## The finder against a plain grep

I ran the same instruction with `grep -ril` over the skill folders in place of the finder, on Haiku.

![On Haiku the same instruction with a plain grep scored within 2 to 3 points of the finder on local rules and installed skills, and 13 points lower on not-installed skills, a gap that did not meet the 15-point rule.](figures/finder-vs-grep.svg)

None of the gaps met the rule. The one place the finder may matter is skills that are not installed: 13 percentage points, finder ahead in 9 tasks and grep in 2 (p = 0.065).

Installing the finder as a skill, without the instruction, did nothing: Haiku never called it in 159 runs. I did not run the grep on Sonnet.

## What tuning did not do

I changed the instruction's wording and the finder's ranking several times. Neither opened more skills.

- Telling Claude to run the lookup as a command of its own removed lookups joined to other commands (25 of 27 tasks to 0). The reworded instruction opened the needed skill in 18 tasks, the old one in 20.
- Ranking changes looked better when I replayed old lookups. With the model, the needed skill was opened in 40 of 53 tasks against 37, not a shown difference. I kept two small parts: skills near the whole lookup are listed after the rows, and a row shows more of its description.

Of 23 tasks where some run missed the skill, in 7 the skill was on the list and Claude did not open it, and in 13 the lookup never listed it.

## What this does not show

- Real use. In my own sessions in the nine days after I added the instruction, the finder ran in 6 of 26 (and in 2 of those a listed skill was then read). Test tasks are each built around one skill; real tasks often need none.
- Tasks I could not keep apart from the tuning. I read the local-rules tasks and the 53 tasks while I changed the instruction and the finder.
- Benchmark prompts written with the skill in view. The 8 no-instruction opens on Sonnet are skills whose names are nearly the task's own words.
- A fair grep. I ran it once, in a first wording, over a clean folder, inside an instruction tuned with the finder, and I added it after I had read the first four Haiku setups.
- Repeatable differences. Two runs of the same setup differ by a few tasks (up to 5 in mine), so gaps under about 8 tasks cannot be seen. A second reader did not recount the Haiku rounds.
- Whether "followed" is more than "cited". On the local-rules suite a rule counts as followed when its ID appears in the answer.

The takeaway: the instruction to look up is the part that works. On Haiku the finder was not shown to beat a grep; on Sonnet I did not run the grep.
