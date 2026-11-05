#!/usr/bin/env python3
"""SkillRet's test skills as a folder skill-finder can scan: DIR/<skill id>/SKILL.md holding the dataset's skill_md, byte for byte.

  python3 -I bench/skillret/prep.py DATA DIR

DATA is a download of huggingface.co/datasets/ThakiCloud/SKILLRET at one revision (data/skills/test.jsonl is read). Each folder is
named for the skill id, so the 154 front-matter names that 359 skills share never collide on disk; the finder reads the name from
the front matter, as it does on any machine. The dataset holds SKILL.md alone, so no skill has reference files here.
"""
import json
import re
import sys
from pathlib import Path

ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")      # the ids are uuids; anything else is refused


def main(data, out):
    out = Path(out)
    out.mkdir(parents=True)
    n = 0
    with open(Path(data) / "data/skills/test.jsonl", encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)
            if not ID.fullmatch(s["id"]): sys.exit(f"unexpected skill id {s['id']!r}")
            d = out / s["id"]
            d.mkdir()
            (d / "SKILL.md").write_text(s["skill_md"], encoding="utf-8")
            n += 1
    print(f"{n} skills written to {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(*sys.argv[1:])
