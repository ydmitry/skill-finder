#!/usr/bin/env python3
"""Find the skills that fit a task across the skill folders on this machine.

  find_skills.py --task "explain this PR as a page" [--top 8] [--root DIR ...] [--json]
  find_skills.py --phrase "implementation plan" [--phrase "task breakdown" ...] [--limit 40] [--json]
  find_skills.py --list
  find_skills.py --toc [WHAT] [--kind names|sentence|description|headers|files] [--json]   # tables of contents: every skill, one folder, one skill
  find_skills.py --phrase "<words>" --toc       # the hits as sections, one sentence each, no best match
  find_skills.py --only DIR --task "..."        # scan DIR/<name>/SKILL.md alone (tests, fixtures); default scans the machine
  find_skills.py --enable NAME [NAME ...] --into DIR [--source TEXT]   # copy skills into DIR/.claude/skills (this run only)
A file `roots` beside this script (or $SKILL_FINDER_ROOTS) lists more folders to scan, one per line, like --root.
  find_skills.py --remove --into DIR                                  # take back what --enable put there

Scans user skills, project skills (.claude/skills up from the cwd), and every plugin's skills in each Claude config
dir (~/.claude, $CLAUDE_CONFIG_DIR): installed plugins whether enabled or disabled, cached copies,
and marketplace folders of plugins never installed. Claude Code's bundled skills and ~/.claude/commands are NOT on
disk here; the session's own skill list covers them. Ranks by task terms found in each skill's name, description,
SKILL.md and references/. It finds candidates; a model reading them decides.
--phrase is the other way to search: not scored words but an exact phrase, looked up in the whole SKILL.md of every skill (like
`grep -il`), then listed compactly: the best 40 by a phrase in the name, then in the description, then how often it occurs.
When no skill holds the phrase it says how many hold each word and lists the 10 nearest by the --task ranking.
A phrase search that finds skills ends with the best match: why it matched (where the phrase sits), when to use it, its first lines,
its reference files, and where to read. With --for "<one sentence about the task>" one cheap model call (Claude Code, no tools)
reads the first three hits against that sentence and picks one or says none fits (SKILL_FINDER_EXPLAIN=0 turns it off).
"""
import argparse, hashlib, json, math, os, re, shlex, shutil, subprocess, sys, tempfile, time
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "_archived", "synced", "fixtures", "evals", "tests", "test"}
STOP = set("a an and are as at be by do for from how in into is it its of on or that the this to use with you "
           "make want need can should would could about after before then than them they our out all any new one "
           "please let lets get put set add using used what when where which who will not but also just my me we".split())

PHRASE_LIMIT = 40        # a phrase search lists at most this many skills, three short lines each
OPEN_LINES = 20          # ... and ends with the first lines of the best match's SKILL.md, so reading it starts in the same result
WHY_CANDIDATES = int(os.environ.get("SKILL_FINDER_WHY_HITS", 3))     # --for: a model reads this many of the first hits and says which fits the task, or that none does
WHY_BODY_LINES = int(os.environ.get("SKILL_FINDER_WHY_LINES", 25))   # ... with this many body lines of each
WHY_TIMEOUT = 90         # seconds for that call
WHY_MAX_CALLS = 6        # model calls for one --for sentence; after that the plain reason only
WHY_SYSTEM = ("You match a task to an installed skill using only the text you are given. Answer with one JSON object and nothing else: "
              '{"pick": "<the exact skill name, or NONE>", "why": "<one or two sentences>"}. Pick a skill only if its own text says it is '
              "for this kind of work, and quote its words in why. If none clearly fits, pick NONE and say what is missing. A wrong pick "
              "is worse than NONE.")
CLOSEST = 10            # a phrase that matches nothing lists this many skills nearest by words,
CLOSEST_FULL = 3        # the first of them with the start of the description, the rest as a name and a path
GENERIC_SHARE = 0.20     # a task word found in over a fifth of the skills' texts says little about which skill fits
MARGIN = 1.3             # the top hit counts as clear when it scores this much more than the next one
SENTENCE_MAX = 120       # --toc: a skill's row holds the description's first sentence, cut at a word beyond this
ROW_MAX = 160            # ... and a names, sentence or headers row is at most this long
ON = {"user skill", "plugin enabled", "project skill", "folder skill", "extra root"}     # statuses Claude Code loads; any other row is [off]
TOC_FILES = 60           # --toc <skill> --kind files lists at most this many files, then says how many more
FILES_SKIP = {".git", "node_modules", "__pycache__", ".venv"}       # a skill's own files never come from these or any dot folder
NOT_END = {"e.g", "i.e", "vs", "etc", "cf"}

def default_roots():
    f = Path(os.environ.get("SKILL_FINDER_ROOTS") or Path(__file__).with_name("roots"))
    try: lines = f.read_text().splitlines()
    except OSError: return []
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]

def config_dirs():
    dirs = [Path.home() / ".claude"]
    if os.environ.get("CLAUDE_CONFIG_DIR"): dirs.append(Path(os.environ["CLAUDE_CONFIG_DIR"]))
    seen, out = set(), []
    for d in dirs:
        if d.is_dir() and d.resolve() not in seen: seen.add(d.resolve()); out.append(d)
    return out

def frontmatter(text):
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m: return {}
    block = m.group(1)
    try:
        import yaml
        data = yaml.safe_load(block)
        if isinstance(data, dict): return {k: str(v) for k, v in data.items()}
    except Exception: pass
    out, key = {}, None
    for line in block.splitlines():
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if km: key = km.group(1); out[key] = km.group(2).strip().strip(">|").strip().strip("\"'")
        elif key and line.strip(): out[key] = (out[key] + " " + line.strip()).strip()
    return out

def walk_skills(base):
    """Plugin trees: skills sit at varying depth; a skill folder is never searched for more skills."""
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith("temp_git_") and not d.endswith(".bak")]
        if "SKILL.md" in fn:
            dn[:] = []
            yield Path(dp)

def top_level_skills(base):
    """User and project roots: Claude Code reads skills/<name>/SKILL.md, one level."""
    try: names = sorted(os.listdir(base))
    except OSError: return
    for n in names:
        d = Path(base) / n
        if d.is_dir() and (d / "SKILL.md").is_file(): yield d

def plugin_of(skill_dir, stop):
    p = skill_dir
    while p != stop and p.parent != p:
        pj = p / ".claude-plugin" / "plugin.json"
        if pj.is_file():
            try: return json.loads(pj.read_text()).get("name") or p.name
            except Exception: return p.name
        p = p.parent
    return None

def collect(extra_roots, only=()):
    """`only`: scan these folders alone (skills/<name>/SKILL.md, one level), nothing from the config dirs or the cwd."""
    entries = []
    def add(sdir, source, status, rank, plugin=None):
        try: text = (sdir / "SKILL.md").read_text(errors="replace")
        except Exception: return
        fm = frontmatter(text)
        entries.append(dict(name=fm.get("name") or sdir.name, description=fm.get("description", ""), dir=sdir,
                            source=source, status=status, rank=rank, plugin=plugin))
    for cfg in ([] if only else config_dirs()):
        enabled = {}
        try: enabled = json.loads((cfg / "settings.json").read_text()).get("enabledPlugins", {})
        except Exception: pass
        installed, install_paths = {}, set()
        try:
            installed = json.loads((cfg / "plugins" / "installed_plugins.json").read_text()).get("plugins", {})
            for k, v in installed.items():
                for rec in v: install_paths.add(str(Path(rec["installPath"]).resolve()))
        except Exception: pass
        for sdir in top_level_skills(cfg / "skills"): add(sdir, "user", "user skill", 0)
        pl = cfg / "plugins"
        for area in ("cache", "marketplaces"):
            for sdir in walk_skills(pl / area):
                rel = sdir.relative_to(pl / area).parts
                market = rel[0]
                pname = plugin_of(sdir, pl / area) or "?"
                key = f"{pname}@{market}"
                at_install = any(str(sdir.resolve()).startswith(ip + os.sep) for ip in install_paths)
                if key in enabled and (at_install or area == "cache"):
                    status = "plugin enabled" if enabled[key] else "plugin DISABLED"
                elif at_install or key in installed: status = "plugin installed"
                elif area == "cache": status = "plugin cached, not installed"
                else: status = "marketplace only, not installed"
                add(sdir, key, status, 1 if at_install else (2 if area == "cache" else 3), pname)
    cwd = Path.cwd().resolve()
    for p in ([] if only else [cwd, *cwd.parents]):
        for sdir in top_level_skills(p / ".claude" / "skills"): add(sdir, f"project {p.name}", "project skill", 0)
    for o in only:
        for sdir in top_level_skills(Path(o).expanduser()): add(sdir, f"only {o}", "folder skill", 0)
    for r in extra_roots:
        for sdir in walk_skills(Path(r).expanduser()): add(sdir, f"root {r}", "extra root", 0)
    by_hash, out = {}, []                      # identical SKILL.md = one skill; the best-ranked copy is shown, the rest as "also at"
    for e in sorted(entries, key=lambda e: (e["rank"], -e["dir"].stat().st_mtime, str(e["dir"]))):
        h = hashlib.sha1((e["dir"] / "SKILL.md").read_bytes()).hexdigest()
        if h in by_hash: by_hash[h]["also"].append(f"{e['source']} [{e['status']}]"); continue
        e["also"] = []; by_hash[h] = e; out.append(e)
    # The same skill again with other text (an older cached version, a copy in the second config folder, a user copy of a plugin
    # skill): same name and either the same plugin or the same description. The best-ranked copy stays and names the rest.
    # Two different skills that merely share a name (a "configure" in each of three plugins) stay apart.
    def words(s): return " ".join(s.split()).lower()
    kept, merged = {}, []
    for e in out:
        twin = next((k for k in kept.get(e["name"], []) if k["source"] == e["source"] or (words(e["description"]) and words(k["description"]) == words(e["description"]))), None)
        if twin:
            here = f"{twin['source']} [{twin['status']}]"
            for place in [f"{e['source']} [{e['status']}]", *e["also"]]:
                if place != here and place not in twin["also"]: twin["also"].append(place)
            continue
        kept.setdefault(e["name"], []).append(e); merged.append(e)
    for e in merged:                           # name only the other places: not the hit's own label again (a copy in the second config folder)
        e["also"] = [p for p in dict.fromkeys(e["also"]) if p != f"{e['source']} [{e['status']}]"]
    return merged

def terms_of(task):
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9+#._-]+", task.lower()) if w not in STOP]
    return sorted(set(words))

def pattern(t):                                 # a term starts a word: "test" matches "tests", not "latest"
    return re.compile(r"(?<![a-z0-9])" + re.escape(t))

def read_small(path):
    try:
        if path.stat().st_size > 300_000: return ""
        return path.read_text(errors="replace")
    except Exception: return ""

def doc_files(sdir):
    refs = sorted(p for p in sdir.rglob("*") if p.is_file() and p.suffix in (".md", ".txt") and p.name != "SKILL.md"
                  and not any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(sdir).parts))
    return [sdir / "SKILL.md"] + refs[:60]

def prepare(entries):
    for e in entries:
        files = doc_files(e["dir"])
        e["_main"] = read_small(files[0]).lower()
        e["_refs"] = [(f, read_small(f).lower()) for f in files[1:]]

def document_frequency(entries, pats):
    return {t: sum(1 for e in entries if p.search(e["_main"]) or p.search(e["name"].lower())) for t, p in pats.items()}

def score(e, pats, idf):
    """Name and description decide; body and references add a little, so a long skill cannot win on volume."""
    name, desc, total = e["name"].lower(), e["description"].lower(), 0.0
    for t, p in pats.items():
        part = 5 * bool(p.search(name)) + 3 * bool(p.search(desc)) + 1.5 * min(len(p.findall(e["_main"])), 5) / 5
        part += min(sum(1 for f, txt in e["_refs"] if p.search(txt)), 5) / 5 + 1.0 * any(p.search(f.name.lower()) for f, _ in e["_refs"])
        total += idf[t] * part
    return total

def rank(entries, terms):
    """The --task ranking: ([(score, entry)] best first, the patterns of the words that count, the words dropped as too common)."""
    prepare(entries)
    df = document_frequency(entries, {t: pattern(t) for t in terms})
    generic = {t for t in terms if df[t] > GENERIC_SHARE * len(entries)}
    eff = [t for t in terms if t not in generic] or terms        # common words are dropped unless they are all there is
    pats = {t: pattern(t) for t in eff}
    idf = {t: math.log(1 + len(entries) / (1 + df[t])) ** 2 for t in eff}      # squared: a rare word outweighs two common ones
    ranked = sorted(((score(e, pats, idf), e) for e in entries), key=lambda x: -x[0])
    return [(s_, e) for s_, e in ranked if s_ > 0], pats, generic

def match_lines(e, pats, limit=4):
    out = []
    for f in [e["dir"] / "SKILL.md"] + [f for f, _ in e["_refs"]]:
        for i, ln in enumerate(read_small(f).splitlines(), 1):
            if any(p.search(ln.lower()) for p in pats.values()):
                out.append(f"{f}:{i}: {ln.strip()[:160]}"); break
        if len(out) >= limit: break
    return out

DESC_MAX = 1500      # the whole description (a third are over 400 characters); a longer one is cut and says so

def whole(text):
    return text if len(text) <= DESC_MAX else f"{text[:DESC_MAX]} ... [{len(text) - DESC_MAX} more characters in SKILL.md]"

def reference_index(sdir):
    out = []
    for p in doc_files(sdir)[1:26]:
        first = next((l.strip().lstrip("# ") for l in read_small(p).splitlines() if l.strip()), "")
        out.append((p, first[:90]))
    return out

def first_sentence(text, n=SENTENCE_MAX):
    """The description's first sentence: up to a . ! or ? followed by an uppercase letter, a quote or the end, never after e.g, vs, etc.
    A longer one, or text without any sentence end, is cut at a word and ends with "…"."""
    text = " ".join(text.split())
    s = text
    for m in re.finditer(r"[.!?](?=\s+[A-Z\"'“‘(]|$)", text):
        if text[:m.start()].split(" ")[-1].lower().lstrip("(\"'“‘") in NOT_END: continue
        s = text[:m.end()]; break
    if len(s) <= n: return s
    cut = s[:n - 1]
    if s[n - 1] != " " and " " in cut: cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"

def group_of(e):
    """The folder an entry sits under in a table: its plugin, `user`, `project <dir>`, or the basename of an --only or roots folder."""
    src = e["source"]
    if e.get("plugin") == "?":                 # a plugin folder without plugin.json: its folder name, so the group is not one bucket of strangers
        market = src.split("@", 1)[-1]
        parts = e["dir"].parts
        i = next((i for i, x in enumerate(parts) if x == "plugins" and parts[i + 1:i + 2] in (("cache",), ("marketplaces",))), None)
        rel = parts[i + 3:] if i is not None else ()
        folder = rel[0] if rel and parts[i + 1] == "cache" else (rel[rel.index("skills") - 1] if "skills" in rel[1:] else None)
        return f"{folder or market}@{market}" if folder != "skills" else f"{market}@{market}"
    if e.get("plugin"): return e["plugin"]
    if src == "user" or src.startswith("project "): return src
    p = Path(src.split(" ", 1)[-1]).expanduser()
    return p.name or p.resolve().name

def off(e):
    return e["status"] not in ON

def toc_scope(entries, what):
    """What --toc names -> ("all" | "folder" | "skill", the entries). In order: a skill name or plugin:name, a folder label, a full
    source key pname@market, a marketplace, a path prefix; a trailing / means folder only. No match, or two skills: exit with the candidates."""
    if what == "all": return "all", entries
    folder_only, w = what.endswith("/") and len(what) > 1, what.rstrip("/") if what.endswith("/") and len(what) > 1 else what
    wl = w.lower()
    def folder():
        for pick in (lambda e: group_of(e).lower() == wl, lambda e: e["source"].lower() == wl, lambda e: e["source"].lower().endswith("@" + wl)):
            hit = [e for e in entries if pick(e)]
            if hit: return hit
        if os.sep in w or w.startswith(("~", ".")):
            pre = os.path.abspath(os.path.expanduser(w))
            return [e for e in entries if any(d == pre or d.startswith(pre.rstrip(os.sep) + os.sep) for d in (os.path.abspath(e["dir"]), os.path.realpath(e["dir"])))]
        return []
    if not folder_only:
        skills = [e for e in entries if e["name"].lower() == wl or (e.get("plugin") and f"{e['plugin']}:{e['name']}".lower() == wl)]
        if not skills and (os.sep in w or w.startswith(("~", "."))):          # a path that is one skill's folder names that skill
            pre = os.path.abspath(os.path.expanduser(w))
            skills = [e for e in entries if pre in (os.path.abspath(e["dir"]), os.path.realpath(e["dir"]))]
        if len(skills) > 1:
            sys.exit(f"{len(skills)} skills are named {what!r}: " + "; ".join(f"{e['dir']} [{e['source']}]" for e in skills) + "; use plugin:name or the path")
        if skills:
            if folder(): print(f"also a folder: --toc {w}/", file=sys.stderr)
            return "skill", skills
    hit = folder()
    if hit: return "folder", hit
    like = sorted({e["name"] for e in entries if wl in e["name"].lower()})[:8]
    sys.exit(f"no skill, folder or path matches {what!r}; folders: " + ", ".join(dict.fromkeys(group_of(e) for e in entries))
             + ("; skills with that in the name: " + ", ".join(like) if like else ""))

def headers_of(path):
    """(line, level, text) of the # to ### headers of a markdown file, after its frontmatter and outside code fences; line numbers as on
    disk. None when the file is too large to read (read_small gives nothing for it)."""
    text = read_small(path)
    if not text:
        try: return None if path.stat().st_size else []
        except OSError: return None
    fm = re.match(r"---\s*\n.*?\n---", text, re.S)
    start = text.count("\n", 0, fm.end()) + 1 if fm else 0
    out, fence = [], ""                        # fence: the opening run of ` or ~; only a line made of that character, at least as long, closes it
    for i, ln in enumerate(text.split("\n")):
        if i < start: continue
        ln = ln.rstrip("\r")
        fm_ = re.match(r"(`{3,}|~{3,})(.*)$", ln.strip())
        if fm_ and (not fence or (fm_.group(1)[0] == fence[0] and len(fm_.group(1)) >= len(fence) and not fm_.group(2).strip())):
            fence = "" if fence else fm_.group(1); continue
        m = None if fence else re.match(r"(#{1,3})\s+(.+?)(?:\s+#+)?\s*$", ln)
        if m and m.group(2).strip(): out.append((i + 1, len(m.group(1)), m.group(2).strip()))
    return out

def files_of(sdir, limit=TOC_FILES):
    """The files of one skill (its resolved folder): SKILL.md first, then sorted; (rows of (relative path, bytes, first line of a .md or
    .txt), total number of files). Not SKIP_DIRS, which only prunes the search for skills; dot folders and files are left out."""
    real = sdir.resolve()
    rels = []
    for dp, dn, fn in os.walk(real):
        dn[:] = [d for d in dn if d not in FILES_SKIP and not d.startswith(".")]
        rels += [Path(dp, f).relative_to(real) for f in fn if f not in FILES_SKIP and not f.startswith(".") and Path(dp, f).is_file()]
    rels.sort(key=lambda r: (r != Path("SKILL.md"), r.parts))
    rows = []
    for r in rels[:limit]:
        first = ""
        if r.suffix in (".md", ".txt"):
            text = read_small(real / r)
            fm = re.match(r"---\s*\n.*?\n---[ \t]*\n?", text, re.S)
            first = next((l.strip().lstrip("# ") for l in (text[fm.end():] if fm else text).splitlines() if l.strip()), "")[:90]
        rows.append((r, (real / r).stat().st_size, first))
    return rows, len(rels)

def toc_row(e, kind, heads=None):
    tail = (" [off]" if off(e) else "") + (f" (also at {len(e['also'])})" if e["also"] else "")
    name = e["name"]
    if kind == "headers":
        h2 = [t for _, lv, t in heads or [] if lv == 2]
        body = " | ".join(h2) if h2 else ("(file too large for an outline)" if heads is None else
               "(no H2) " + next((t for _, lv, t in heads if lv == 1), "(no headers)"))
        room = ROW_MAX - len(name) - 2 - len(tail)
        return f"{name}: {body if len(body) <= room else body[:room - 1] + '…'}{tail}"
    if kind == "names": line = name + tail
    elif kind == "description": return f"{name} — {whole(' '.join(e['description'].split())) or '(no description)'}{tail}"
    else:
        line = f"{name} — {first_sentence(e['description'], max(20, min(SENTENCE_MAX, ROW_MAX - len(name) - 3 - len(tail)))) or '(no description)'}{tail}"
    return line if len(line) <= ROW_MAX else line[:ROW_MAX - 1] + "…"

def toc_entry(e, kind):
    out = dict(name=e["name"], sentence=first_sentence(e["description"]), status=e["status"], path=str(e["dir"] / "SKILL.md"), off=off(e), also=e["also"])
    if kind == "description": out["description"] = " ".join(e["description"].split())
    if kind == "headers": out["headers"] = [t for _, lv, t in headers_of(e["dir"] / "SKILL.md") or [] if lv == 2]
    return out

def toc_skill(e, entries, kind, as_json):
    """One skill: its header outline with line numbers (kind headers), its files (kind files), or its one row."""
    path = e["dir"] / "SKILL.md"
    size = path.stat().st_size
    rows, total = files_of(e["dir"], TOC_FILES if kind == "files" else 0)
    if as_json:
        t = dict(scope=e["name"], level="skill", kind=kind, scanned=len(entries), **toc_entry(e, kind), bytes=size)
        if kind == "headers":
            heads = headers_of(path)
            t["headers"] = None if heads is None else [dict(line=n, level=lv, text=tx) for n, lv, tx in heads]
        if kind == "files": t.update(files=[dict(path=str(r), bytes=b, first=f) for r, b, f in rows], more_files=total - len(rows))
        print(json.dumps(dict(toc=t), indent=1)); return
    if kind == "files":
        print(f"{e['name']}  {path}  ({total} file{'s' * (total != 1)})")
        for r, b, f in rows: print(f"{r}  ({b})" + (f"  {f}" if f else ""))
        if total > len(rows): print(f"+{total - len(rows)} more files")
        return
    others = total - 1
    print(f"{e['name']}  {path}  ({size:,} bytes" + (f"; {others} more files: --kind files" if others > 0 else "") + ")")
    print(first_sentence(e["description"]) or "(no description)")
    heads = headers_of(path)
    if heads is None: print("(file too large for an outline)")
    elif not heads: print(f"no headers; {len(read_small(path).splitlines())} lines")
    for n, lv, tx in heads or []: print(f"{n:>4}: {'#' * lv} {tx}")
    print("Read a section: Read <path> with offset <line>. Whole file: Read <path>.")

def toc(entries, what, kind, as_json):
    """--toc: a table of contents. Every skill or one folder: a row each; one skill: its outline or files. No model call."""
    level, es = toc_scope(entries, what)
    kind = kind or ("headers" if level == "skill" else "sentence")
    if kind == "files" and level != "skill": sys.exit("--kind files needs one skill: --toc <skill>")
    if level == "skill" and (as_json or kind in ("headers", "files")): return toc_skill(es[0], entries, kind, as_json)
    groups = {}
    for e in es: groups.setdefault(group_of(e), []).append(e)
    def order(g):                              # fixed: user, project, --only / roots folders, then plugins; by label inside a kind
        src = groups[g][0]["source"]
        return (0 if src == "user" else 1 if src.startswith("project ") else 3 if groups[g][0].get("plugin") else 2, g.lower())
    groups = [(g, sorted(groups[g], key=lambda e: (e["name"].lower(), e["name"]))) for g in sorted(groups, key=order)]
    label = "all" if level == "all" else (groups[0][0] if len(groups) == 1 else what.rstrip("/"))
    if as_json:
        print(json.dumps(dict(toc=dict(scope=label, level=level, kind=kind, scanned=len(entries),
              groups=[dict(group=g, entries=[toc_entry(e, kind) for e in v]) for g, v in groups])), indent=1)); return
    said = {"names": "name", "sentence": "name — first sentence", "description": "name — description", "headers": "name: H2 headers"}[kind]
    print(f"table of contents: {len(es)} skill{'s' * (len(es) != 1)} in {len(groups)} folder{'s' * (len(groups) != 1)} ({said}; [off] = plugin not enabled or not installed)")
    for g, v in groups:
        print(f"## {g} ({len(v)})")
        for e in v: print(toc_row(e, kind, headers_of(e["dir"] / "SKILL.md") if kind == "headers" else None))
    print("Narrow: --toc <folder> | one skill: --toc <skill> (headers) or --toc <skill> --kind files | open: Read <path>")

def phrase_pattern(phrase):
    """The words of a phrase in order, joined by space, newline, hyphen or underscore; the first word starts a word."""
    words = re.findall(r"[a-z0-9][a-z0-9+#.]*", phrase.lower())
    return re.compile(r"(?<![a-z0-9])" + r"[\s_-]+".join(re.escape(w) for w in words), re.I) if words else None

def near_misses(entries, phrases):
    """For phrases nothing contains: how many skills hold each of their words, and the skills nearest by words (the --task
    ranking), so a miss still points somewhere."""
    terms = terms_of(" ".join(phrases))
    if not terms: return {}, []
    ranked, _, _ = rank(entries, terms)
    said = " ".join(phrases).lower()
    counts = document_frequency(entries, {t: pattern(t) for t in sorted(terms, key=said.index)})      # in the order they were typed
    rows = [dict(score=round(s_, 1), name=e["name"], status=e["status"], source=e["source"], path=str(e["dir"] / "SKILL.md"),
                 description=" ".join(e["description"].split())[:110]) for s_, e in ranked[:CLOSEST]]
    return counts, rows

def body_lines(e, n):
    """The first n lines of a SKILL.md after its frontmatter: leading blanks dropped, runs of blanks squeezed, long lines cut."""
    text = read_small(e["dir"] / "SKILL.md")
    fm = re.match(r"---\s*\n.*?\n---[ \t]*\n?", text, re.S)
    out, blank = [], True
    for ln in (text[fm.end():] if fm else text).splitlines():
        ln = ln.rstrip()
        if not ln.strip():
            if not blank: out.append("")
            blank = True
        else:
            out.append(ln[:160]); blank = False
        if len(out) >= n: break
    while out and not out[-1]: out.pop()
    return out

def use_when(e):
    return re.split(r"(?<=[.!?])\s", " ".join(e["description"].split()), maxsplit=1)[0][:240]

def why_plain(detail, line):
    """The search's own reason for the best match, from facts only: where each phrase was found, and the first line it is on."""
    bits = []
    for ph, (in_name, in_desc, n) in detail.items():
        where = " and ".join(w for w, ok in (("its name", in_name), ("its description", in_desc)) if ok)
        times = f"{n} time{'s' if n != 1 else ''} in SKILL.md" if n else ""
        bits.append(f'"{ph}" is in ' + ((where + (f" and {times}" if times else "")) if where else times))
    return "; ".join(bits) + (f' (line {line[0]}: "{line[1]}")' if line else "")

def log_cost(rec):
    path = os.environ.get("SKILL_FINDER_COST_LOG")
    if path:
        try:
            with open(path, "a") as f: f.write(json.dumps(rec) + "\n")
        except OSError: pass

def ask_model(for_text, cands):
    """--for: one call through Claude Code (`claude -p`, no tools, no session kept) that reads the first hits and says which fits the task
    in one sentence, or NONE. Returns {pick, why, cost, seconds} or {error}; None when it is switched off or already inside such a call.
    Same sentence and same hits: the answer is cached. At most WHY_MAX_CALLS calls for one sentence. Env: SKILL_FINDER_EXPLAIN=0 (off),
    SKILL_FINDER_MODEL (haiku), SKILL_FINDER_CLAUDE (the command), SKILL_FINDER_COST_LOG (a file that gets one JSON line per call)."""
    if os.environ.get("SKILL_FINDER_EXPLAIN") == "0" or os.environ.get("SKILL_FINDER_NESTED"): return None
    names = [h[1]["name"] for h in cands]
    blocks = [f"### {i}. {h[1]['name']}\ndescription: {whole(' '.join(h[1]['description'].split()))}\nfirst lines:\n" + "\n".join(body_lines(h[1], WHY_BODY_LINES))
              for i, h in enumerate(cands, 1)]
    prompt = f"Task, in one sentence, from the person doing it: {for_text}\n\nCandidate skills (found by a phrase search):\n\n" + "\n\n".join(blocks)
    cache = Path(tempfile.gettempdir()) / f"skill-finder-why-{os.getuid()}"
    cache.mkdir(exist_ok=True)
    done = cache / (hashlib.sha1(prompt.encode()).hexdigest()[:24] + ".json")
    if done.is_file():
        try: return {**json.loads(done.read_text()), "cached": True}
        except ValueError: pass
    count = cache / ("calls-" + hashlib.sha1(for_text.encode()).hexdigest()[:12])
    used = int(count.read_text() or 0) if count.is_file() else 0
    if used >= WHY_MAX_CALLS: return {"error": f"{WHY_MAX_CALLS} model reasons already given for this task sentence"}
    count.write_text(str(used + 1))
    cmd = shlex.split(os.environ.get("SKILL_FINDER_CLAUDE", "claude")) + [
        "-p", "--model", os.environ.get("SKILL_FINDER_MODEL", "haiku"), "--tools", "", "--disable-slash-commands", "--strict-mcp-config",
        "--no-session-persistence", "--max-budget-usd", "0.05", "--output-format", "json", "--system-prompt", WHY_SYSTEM]
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as wd:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=WHY_TIMEOUT, cwd=wd, env={**os.environ, "SKILL_FINDER_NESTED": "1"})
    except (subprocess.TimeoutExpired, OSError) as ex:
        res = {"error": type(ex).__name__, "seconds": round(time.time() - t0, 1), "cands": names}
        log_cost(res); return res
    secs = round(time.time() - t0, 1)
    try:
        env = json.loads(r.stdout); text, cost = str(env.get("result", "")), env.get("total_cost_usd", 0)
    except ValueError:
        text, cost = r.stdout, 0
    m = re.search(r"\{.*\}", text, re.S)
    try: ans = json.loads(m.group(0)) if m and r.returncode == 0 else {}
    except ValueError: ans = {}
    pick = str(ans.get("pick", "")).strip()
    if not pick or (pick != "NONE" and pick not in names):
        res = {"error": f"no usable answer (exit {r.returncode})", "seconds": secs, "cost": cost, "cands": names}
        log_cost(res); return res
    res = {"pick": pick, "why": " ".join(str(ans.get("why", "")).split())[:400], "cost": cost, "seconds": secs, "cands": names}
    log_cost(res)
    try: done.write_text(json.dumps(res))
    except OSError: pass
    return res

def best_match(cands, for_text):
    """What a phrase search ends with: the best match, why, and where reading starts. Without --for it is the first hit; with it a model
    may pick another of the first WHY_CANDIDATES or say that none fits."""
    top = cands[:WHY_CANDIDATES]
    fit = ask_model(for_text, top) if for_text else None
    names = [h[1]["name"] for h in top]
    i = names.index(fit["pick"]) if fit and fit.get("pick") in names else 0
    _, e, found, line, detail = top[i]
    none = bool(fit and fit.get("pick") == "NONE")
    return dict(name=e["name"], path=str(e["dir"] / "SKILL.md"), rank=i + 1, plain=why_plain(detail, line), use_when=use_when(e),
                lines=[] if none else body_lines(e, OPEN_LINES), references=[str(f.relative_to(e["dir"])) for f in doc_files(e["dir"])[1:]],
                fit=fit, none=none, considered=len(top))

def print_best(b, for_text):
    fit = b["fit"]
    print()
    print((f'Best by the search: ' if b["none"] else 'Best match: ') + f'{b["name"]}  {b["path"]}' + (f'  (hit {b["rank"]}, picked by the model)' if b["rank"] > 1 else ""))
    print(f'Why: {b["plain"]}')
    if fit and "pick" in fit:
        print(f'Fit (a model read the first {b["considered"]} hits against "{for_text}"): ' + ("none clearly fits. " if b["none"] else "") + fit["why"])
    elif fit:
        print(f'Fit: not available ({fit["error"]}).')
    if b["none"]:
        print("No skill clearly fits: search again with other words, or open the best match only if it looks right to you.")
        return
    print(f'Description: {b["use_when"]}')
    if b["lines"]:
        print("First lines of SKILL.md:"); [print(("  " + ln) if ln else "") for ln in b["lines"]]
    if b["references"]:
        print("References: " + ", ".join(b["references"][:8]) + (f" (+{len(b['references']) - 8} more)" if len(b["references"]) > 8 else ""))
    print(f'Read {b["path"]}, then follow it; search again only if it does not fit.')

def phrase_sections(shown):
    """The shown hits by where the phrase sits: in the name, else in the description, else in the body (ranking order kept inside each)."""
    sec = dict(name=[], description=[], body=[])
    for h in shown:
        found = h[4].values()
        sec["name" if any(d[0] for d in found) else "description" if any(d[1] for d in found) else "body"].append(h)
    return sec

def print_phrase_toc(entries, hits, sections, counts, nearest, limit):
    def row(e, tail=""):
        return f"{e['name']} — {first_sentence(e['description'], max(20, min(SENTENCE_MAX, ROW_MAX - len(e['name']) - 3 - len(tail)))) or '(no description)'}{tail}"
    if hits:
        if len(hits) > limit: print(f"{len(hits)} skill(s) contain it; the best {limit} are shown. A longer phrase narrows it.")
        for k, v in sections.items():
            if not v: continue
            print(f"## phrase in the {k} ({len(v)})")
            for _, e, _, line, _ in v: print(row(e, f"  :{line[0]}" if line else ""))
    else:
        by_path = {str(e["dir"] / "SKILL.md"): e for e in entries}
        if counts: print("Skills holding each word: " + ", ".join(f"{t} {n}" for t, n in counts.items()) + ". A word held by none is not how any skill says it.")
        if nearest:
            print(f"## nearest by words ({len(nearest)})")
            for r in nearest: print(row(by_path[r["path"]]))
        else: print("No skill holds any of these words either." if counts else "No skill contains it.")
    print("Open the one that fits: Read <path>. None fits: search other words, or --toc for the whole table." if hits or nearest
          else "Search other words, or --toc for the whole table.")

def phrase_search(entries, phrases, limit, as_json, for_text="", toc=False):
    """`grep -il` over the whole SKILL.md of every skill, but ranked (so the shown ones do not depend on directory order) and
    compact: a phrase in the name first, then in the description, then how often it occurs. Several phrases are alternatives; a
    skill that holds more of them comes first. With `toc` the hits print as sections (phrase in the name, the description, the body), one
    sentence each, and no best match."""
    pats = [(ph, phrase_pattern(ph)) for ph in phrases]
    if any(pt is None for _, pt in pats): sys.exit("--phrase needs words or numbers")
    hits = []
    for e in entries:
        text = read_small(e["dir"] / "SKILL.md")
        name, desc = e["name"], e["description"]
        fm = re.match(r"---\s*\n.*?\n---", text, re.S)
        body_from = fm.end() if fm else 0
        found, in_name, in_desc, count, line, detail = [], 0, 0, 0, None, {}
        for ph, pt in pats:
            n = len(pt.findall(text))
            if n or pt.search(name):
                found.append(ph)
                in_name += bool(pt.search(name)); in_desc += bool(pt.search(desc)); count += n
                detail[ph] = (bool(pt.search(name)), bool(pt.search(desc)), n)
                m = pt.search(text, body_from)                  # a match in the frontmatter is the description, shown above it
                if m and line is None:
                    at = text.count("\n", 0, m.start())
                    line = (at + 1, " ".join(text.splitlines()[at].split())[:140])
        if found: hits.append(((-len(found), -in_name, -in_desc, -min(count, 5), e["name"]), e, found, line, detail))
    hits.sort(key=lambda h: h[0])
    shown = hits[:limit]
    rows = [dict(name=e["name"], status=e["status"], source=e["source"], path=str(e["dir"] / "SKILL.md"), phrases=found,
                 description=" ".join(e["description"].split())[:110], match=f"{line[0]}: {line[1]}" if line else "", also=e["also"])
            for _, e, found, line, _ in shown]
    counts, nearest = near_misses(entries, phrases) if not hits else ({}, [])
    best = best_match(hits, for_text) if hits and not toc else None
    sections = phrase_sections(shown) if toc else None
    if as_json:
        out = dict(phrases=phrases, scanned=len(entries), matched=len(hits), shown=len(rows), candidates=rows)
        if not hits: out.update(word_counts=counts, nearest=nearest)
        elif not toc: out.update(best=best)
        if toc: out.update(sections={k: [h[1]["name"] for h in v] for k, v in sections.items()})
        print(json.dumps(out, indent=1)); return
    quoted = " | ".join(f'"{ph}"' for ph in phrases)
    print(f"phrase search: {quoted} in the SKILL.md of {len(entries)} skills on disk (a phrase starts a word: 'plan' matches 'planning', not 'airplane')")
    if toc: return print_phrase_toc(entries, hits, sections, counts, nearest, limit)
    if not hits:
        print("No skill contains it. Try fewer words, another form of the word, or a word the finished thing is called.")
        if counts:
            print("Skills holding each word: " + ", ".join(f"{t} {n}" for t, n in counts.items()) + ". A word held by none is not how any skill says it.")
        if nearest:
            print(f"\nNearest by words, not by phrase (--task \"{' '.join(counts)}\"); open one only if its description fits:")
            for i, r in enumerate(nearest, 1):
                print(f"{i}. {r['name']}  [{r['status']}]  {r['path']}" + (f"\n   {r['description']}" if i <= CLOSEST_FULL else ""))
        elif counts:
            print("No skill holds any of these words either.")
        return
    print(f"{len(hits)} skill(s) contain it" + ("" if len(hits) <= limit else f"; the best {limit} are shown. A longer phrase narrows it")
          + ". Best first: the phrase in the name, then in the description, then how often it occurs.\n")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['name']}  [{r['status']}]  {r['path']}")
        print(f"   {r['description']}")
        if r["match"]: print(f"   :{r['match']}")
        if r["also"]: print(f"   also at: {'; '.join(r['also'][:2])}" + (f" (+{len(r['also']) - 2} more)" if len(r["also"]) > 2 else ""))
    print_best(best, for_text)

def enable(entries, names, into, source):
    """Copy skills into DIR/.claude/skills so a session started in DIR can invoke them, whatever their plugin's
    state. Nothing global changes: settings.json is never touched. The copy loses its plugin namespace."""
    root = Path(into).expanduser().resolve() / ".claude" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / ".skill-finder.json"
    done = json.loads(manifest.read_text()) if manifest.exists() else {}
    for n in names:
        cands = [e for e in entries if e["name"] == n and (not source or source in e["source"])]
        if not cands: print(f"no skill named {n}", file=sys.stderr); continue
        if len(cands) > 1: print(f"{n}: {len(cands)} different skills share this name; took the first ({cands[0]['source']}); "
                                 f"others: {', '.join(c['source'] for c in cands[1:])}; use --source to choose", file=sys.stderr)
        e, dest = cands[0], root / n
        if dest.exists() and n not in done: print(f"{dest} exists and is not ours; left alone", file=sys.stderr); continue
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(e["dir"], dest, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        done[n] = str(e["dir"])
        note = ""
        if any("CLAUDE_PLUGIN_ROOT" in read_small(f) for f in dest.rglob("*") if f.is_file() and f.suffix in (".md", ".sh", ".py", ".json")):
            note = "  WARNING: refers to CLAUDE_PLUGIN_ROOT; its scripts may not find their files from here"
        print(f"enabled {n}  ({e['status']}; {e['source']}) -> {dest}{note}")
    manifest.write_text(json.dumps(done, indent=1) + "\n")

def remove(into):
    root = Path(into).expanduser().resolve() / ".claude" / "skills"
    manifest = root / ".skill-finder.json"
    if not manifest.exists(): print("nothing to remove", file=sys.stderr); return
    for n in json.loads(manifest.read_text()):
        shutil.rmtree(root / n, ignore_errors=True); print(f"removed {n}")
    manifest.unlink()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=""); ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--phrase", action="append", default=[], help="an exact phrase to look for in every SKILL.md (repeatable: alternatives)")
    ap.add_argument("--limit", type=int, default=PHRASE_LIMIT, help="--phrase: how many skills to list")
    ap.add_argument("--for", dest="for_text", default="", help="--phrase: one sentence on what you are doing; a model reads the first hits against it and says which fits, or none")
    ap.add_argument("--root", action="append", default=[]); ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", action="append", default=[], metavar="DIR",
                    help="scan only DIR/<name>/SKILL.md (repeatable): no config dirs, no project skills; for tests and fixtures")
    ap.add_argument("--toc", nargs="?", const="all", default=None, metavar="WHAT",
                    help="a table of contents: every skill (name, first sentence), one folder, or one skill (its headers; --kind files for its files)")
    ap.add_argument("--kind", choices=("sentence", "names", "description", "headers", "files"), default=None, help="--toc: what each row holds")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--enable", nargs="+", default=[]); ap.add_argument("--remove", action="store_true")
    ap.add_argument("--into"); ap.add_argument("--source", default="")
    a = ap.parse_args()
    if a.kind and a.phrase: sys.exit("--kind goes with --toc alone")
    if a.kind and a.toc is None: sys.exit("--kind needs --toc")
    if a.toc is not None:
        for flag in (a.for_text and "--for", a.enable and "--enable", a.remove and "--remove"):
            if flag: sys.exit(f"--toc goes alone or with --phrase, not with {flag}")
        if a.phrase and a.toc != "all": sys.exit("--phrase --toc takes no WHAT")
        if not a.phrase:
            for flag in (a.task and "--task", a.list and "--list", a.limit != PHRASE_LIMIT and "--limit", a.top != 8 and "--top"):
                if flag: sys.exit(f"--toc goes alone or with --phrase, not with {flag}")
    if a.remove:
        if not a.into: sys.exit("--remove needs --into DIR")
        return remove(a.into)
    entries = collect(a.root + ([] if a.only else default_roots()), a.only)
    if a.enable:
        if not a.into: sys.exit("--enable needs --into DIR")
        return enable(entries, a.enable, a.into, a.source)
    if a.toc is not None and not a.phrase: return toc(entries, a.toc, a.kind, a.json)
    if a.phrase:
        if a.task: sys.exit("use --phrase or --task, not both")
        return phrase_search(entries, a.phrase, a.limit, a.json, a.for_text, a.toc is not None)
    if a.list or not a.task:
        for e in entries:
            print(f"{e['status']:<32} {e['source']:<40} {e['name']:<36} {e['dir']}")
        print(f"\n{len(entries)} skills", file=sys.stderr); return
    terms = terms_of(a.task)
    ranked, pats, generic = rank(entries, terms)
    top = ranked[0][1] if ranked else None
    named = [t for t in pats if top and (pats[t].search(top["name"].lower()) or pats[t].search(top["description"].lower()))]
    clear = len(ranked) == 1 or (len(ranked) > 1 and ranked[0][0] >= MARGIN * ranked[1][0])
    low = not ranked or len(generic) == len(terms) or not named or (len(named) < 2 and not clear)
    res = []
    for s_, e in ranked[:a.top]:
        res.append(dict(score=round(s_, 1), name=e["name"], source=e["source"], status=e["status"], path=str(e["dir"] / "SKILL.md"),
                        also=e["also"], description=whole(e["description"]), matches=match_lines(e, pats),
                        references=[f"{p}  — {h}" for p, h in reference_index(e["dir"])]))
    common = [t for t in terms if t in generic]       # dropped from the ranking, unless every word is common (then all are kept)
    note = ("LOW CONFIDENCE: the best hit is weak (under two task words in its name or description and not clearly ahead of the "
            "next, or only very common words). Search again with a word for what the finished thing is called (its kind or format) "
            "or for the method, or look up an exact phrase with --phrase, before you decide 'none apply'. Also check the skills already in your own session list.") if low else ""
    if a.json: print(json.dumps(dict(terms=terms, common=common, scanned=len(entries), low_confidence=low, candidates=res), indent=1)); return
    print(f"terms: {', '.join(terms)}\nscanned {len(entries)} skills on disk; top {len(res)}")
    if common:
        print(f"every word is very common among the skills, so none ranks one above another: {', '.join(common)}" if len(common) == len(terms)
              else f"dropped as too common to rank: {', '.join(common)}")
    if note: print(note)
    print()
    for r in res:
        print(f"## {r['name']}  [{r['status']}; {r['source']}]  score {r['score']}\n{r['path']}\n{r['description']}")
        if r["also"]: print(f"  also at: {'; '.join(r['also'][:6])}")
        for m in r["matches"]: print(f"  match {m}")
        if r["references"]:
            print("  references:"); [print(f"    {x}") for x in r["references"]]
        print()

if __name__ == "__main__": main()
