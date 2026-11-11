#!/usr/bin/env python3
"""Find the skills that fit a task across the skill folders on this machine.

  find_skills.py --task "explain this PR as a page" [--top 8] [--root DIR ...] [--json]
  find_skills.py --phrase "implementation plan" [--phrase "task breakdown" ...] [--limit 10] [--json]   # quotes optional after a space
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
`grep -il`), then listed compactly: the best 10 by a phrase in the name, then in the description, then how often it occurs; when
more skills hold it, the header says how many and that --limit 40 lists more.
Under a listed skill come the looked-up phrases that only its reference files hold, each with file:line (at most 3, then how many
more), and a line that names its reference files (8 at most: those that hold the looked-up phrases first, a phrase few of the
skill's files hold counting most; copies of one file take one place).
Up to 5 skills that are not listed and hold a phrase only in their reference files follow, with file:line and the phrase: skills whose
SKILL.md holds none of the phrases, and hits beyond --limit. When no SKILL.md holds the phrase those come first; then it says how many
skills hold each word and lists the 10 nearest by the --task ranking.
A phrase search that finds skills ends with the best match: why it matched (where the phrase sits), when to use it, its first lines,
its reference files, and where to read.
The finder itself is left out of every search (its README and notes hold every example phrase): its own folder, a copy of its
SKILL.md, and a skill of its name with scripts/find_skills.py beside it (another version installed apart). --list and a bare --toc
show it.
It calls no model, starts no process and opens no connection; only --enable and --remove write, inside the folder you name.
"""
import argparse, hashlib, json, math, os, re, shutil, sys
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "_archived", "synced", "fixtures", "evals", "tests", "test"}
STOP = set("a an and are as at be by do for from how in into is it its of on or that the this to use with you "
           "make want need can should would could about after before then than them they our out all any new one "
           "please let lets get put set add using used what when where which who will not but also just my me we".split())

PHRASE_LIMIT = 10        # a phrase search lists at most this many skills, three short lines each
LIMIT_MORE = 40          # ... and when more hold the phrase, its header says that --limit this lists more
OPEN_LINES = 20          # ... and ends with the first lines of the best match's SKILL.md, so reading it starts in the same result
CLOSEST = 10            # a phrase that matches nothing lists this many skills nearest by words,
CLOSEST_FULL = 3        # the first of them with the start of the description, the rest as a name and a path
GENERIC_SHARE = 0.20     # a task word found in over a fifth of the skills' texts says little about which skill fits
MARGIN = 1.3             # the top hit counts as clear when it scores this much more than the next one
SENTENCE_MAX = 120       # --toc: a skill's row holds the description's first sentence, cut at a word beyond this
ROW_MAX = 160            # ... and a names, sentence or headers row is at most this long
ON = {"user skill", "plugin enabled", "project skill", "folder skill", "extra root",    # statuses whose skill Claude gets; any other row is [off]
      "user skill, name only in settings", "project skill, name only in settings"}
HIDDEN = {"name-only": "name only", "user-invocable-only": "user-invocable only", "off": "off"}     # skillOverrides states as a label says them; "on" adds nothing
TOC_FILES = 60           # --toc <skill> --kind files lists at most this many files, then says how many more
FILES_SKIP = {".git", "node_modules", "__pycache__", ".venv"}       # a skill's own files never come from these or any dot folder
NOT_END = {"e.g", "i.e", "vs", "etc", "cf"}
OWN = Path(__file__).resolve().parents[1]       # the finder's own skill folder, where a symlinked install leads

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
        if line.strip().startswith("#"): continue          # a YAML comment line belongs to no key
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if km: key = km.group(1); out[key] = re.sub(r"^[>|][-+\d]*(\s+#.*)?$", "", km.group(2).strip()).strip(">|").strip().strip("\"'")     # a block's header: >-, |2+ # note
        elif key and line.strip(): out[key] = (out[key] + " " + line.strip()).strip()
    return out

def walk_skills(base):
    """Plugin trees: skills sit at varying depth; a skill folder is never searched for more skills."""
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith("temp_git_") and not d.endswith((".bak", ".cachebak"))]
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

def git_root(folder):
    """The repo root Claude Code finds for a folder, without running git: the nearest folder up that holds .git. A linked worktree's
    .git file leads (gitdir:, then commondir) to the main checkout. None outside git."""
    for d in [folder, *folder.parents]:
        g = d / ".git"
        if g.is_dir(): return d
        if g.is_file():
            try:
                gitdir = d / g.read_text().split("gitdir:", 1)[1].strip()
                common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
                return common.parent if common.name == ".git" else d
            except Exception: return d
    return None

def loads_here(rec, cwd, root):
    """An install record a session started in cwd applies: user (or managed) scope always; local or project scope when cwd is its
    projectPath or in the same git repo, a linked worktree included. Claude Code compares the paths as text: only on Windows does it
    retry another spelling, which this does not copy."""
    if rec.get("scope") not in ("local", "project"): return True
    if not rec.get("projectPath"): return False
    p = Path(rec["projectPath"]).resolve()
    return p == cwd or (root is not None and git_root(p) == root)

def projects(recs):
    """The projects install records are for, each named once by its git repo root (Claude Code records the folder a session started
    in, so a repo gathers one per subfolder and linked worktree): at most two names, then how many more."""
    names = sorted({(git_root(p) or p).name for p in (Path(r["projectPath"]).resolve() for r in recs if r.get("projectPath"))},
                   key=lambda n: (n.lower(), n))
    return ", ".join(names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else "")

def session_config():
    """The config dir a session reads, and the only one: $CLAUDE_CONFIG_DIR, else ~/.claude."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").resolve()

def folder_files(cwd, root):
    """The settings files a session started in cwd reads over the user's settings.json, in order: the launch folder's
    .claude/settings.json (never a parent's), then settings.local.json there and at the repo root, where Claude Code keeps it."""
    return (cwd / ".claude" / "settings.json", cwd / ".claude" / "settings.local.json", (root or cwd) / ".claude" / "settings.local.json")

def folder_settings(cwd, root, key):
    """`key` (enabledPlugins, skillOverrides) as a session started in cwd reads it over the user's settings.json, later files
    winning name by name."""
    out = {}
    for f in folder_files(cwd, root): out |= setting(f, key)
    return out

def setting(f, key):
    """A settings file's object under `key` (enabledPlugins, skillOverrides), or {} when the file, its JSON or its schema is unusable.
    Claude Code skips a file that fails its schema whole, so either key failing takes both keys of that file out: a later file's
    "hidden" leaves an earlier file's "off", and its other entries do not count. What is checked: the file is a JSON object;
    enabledPlugins, when present, is an object whose values are true, false or a list of strings (version constraints); skillOverrides,
    when present, is an object whose values are "on", "name-only", "user-invocable-only" or "off". No other key is checked, so a file
    that another key makes invalid still counts here."""
    try: data = json.loads(f.read_text())
    except Exception: return {}
    if not isinstance(data, dict): return {}
    v = {k: data.get(k, {}) for k in ("enabledPlugins", "skillOverrides")}
    if not all(isinstance(x, dict) for x in v.values()) or any(s not in ("on", *HIDDEN) for s in v["skillOverrides"].values()): return {}
    if not all(isinstance(p, bool) or isinstance(p, list) and all(isinstance(c, str) for c in p) for p in v["enabledPlugins"].values()): return {}
    return v[key]

def own_skill():
    """The bytes of the finder's own SKILL.md and its skill name, which mark a copy of the finder elsewhere; (None, None) without one."""
    try: md = (OWN / "SKILL.md").read_bytes()
    except OSError: return None, None
    return md, frontmatter(md.decode(errors="replace")).get("name") or OWN.name

def collect(extra_roots, only=()):
    """`only`: scan these folders alone (skills/<name>/SKILL.md, one level), nothing from the config dirs or the cwd."""
    entries, cwd = [], Path.cwd().resolve()
    root = git_root(cwd)
    in_use = session_config()
    folder_hides = {} if only else folder_settings(cwd, root, "skillOverrides")     # skill folder name -> state; plugin skills ignore it
    own_md, own_name = own_skill()
    def add(sdir, source, status, rank, plugin=None, away=False, hides=None):
        try: text = (sdir / "SKILL.md").read_text(errors="replace")
        except Exception: return
        fm = frontmatter(text)
        name = fm.get("name") or sdir.name
        said = HIDDEN.get((hides or {}).get(sdir.name))     # skillOverrides goes by the command name: a user or project skill's folder
        # the finder itself: its own folder, a copy of its SKILL.md, or a skill of its name with its script (another version, installed
        # apart from the clone that runs); the merges pass it on to the row they keep
        own = (sdir.resolve() == OWN or (sdir / "SKILL.md").read_bytes() == own_md
               or (name == own_name and (sdir / "scripts" / "find_skills.py").is_file()))
        entries.append(dict(name=name, description=fm.get("description", ""), dir=sdir, source=source,
                            status=f"{status}, {said} in settings" if said else status, rank=rank, plugin=plugin, away=away, own=own))
    for cfg in ([] if only else config_dirs()):
        enabled = setting(cfg / "settings.json", "enabledPlugins")
        here = cfg.resolve() == in_use             # another config dir keeps the labels its own settings.json gives
        folder = folder_settings(cwd, root, "enabledPlugins") if here else {}
        on = enabled | folder
        hides = setting(cfg / "settings.json", "skillOverrides") | (folder_hides if here else {})
        installed, install_paths, elsewhere = {}, set(), {}     # elsewhere: key -> its projects, when no install of it loads here
        try:
            installed = json.loads((cfg / "plugins" / "installed_plugins.json").read_text()).get("plugins", {})
            for k, v in installed.items():
                for rec in v: install_paths.add(str(Path(rec["installPath"]).resolve()))
                if here and v and not any(loads_here(rec, cwd, root) for rec in v):
                    elsewhere[k] = projects(v)
        except Exception: pass
        for sdir in top_level_skills(cfg / "skills"): add(sdir, "user", "user skill", 0, away=not here, hides=hides)
        pl = cfg / "plugins"
        for area in ("cache", "marketplaces"):
            for sdir in walk_skills(pl / area):
                rel = sdir.relative_to(pl / area).parts
                market = rel[0]
                pname = plugin_of(sdir, pl / area) or "?"            # "?": no plugin.json, so group_of() names it by its folder
                key = f"{rel[1] if pname == '?' and area == 'cache' and len(rel) > 2 else pname}@{market}"  # cache/<market>/<plugin>/
                s = str(sdir.resolve())
                at_install = any(s == ip or s.startswith(ip + os.sep) for ip in install_paths)     # == : SKILL.md at the plugin root
                if at_install and elsewhere.get(key) and key not in folder: status = f"plugin installed for {elsewhere[key]} only"
                elif area == "cache" and not at_install and installed.get(key): status = "plugin cached, other version"
                elif key in on and (at_install or area == "cache"):
                    status = "plugin enabled" if on[key] is True or isinstance(on[key], list) else "plugin DISABLED"   # a list of versions, even an empty one, enables it
                elif at_install or key in installed: status = "plugin installed"
                elif area == "cache": status = "plugin cached, not installed"
                else: status = "marketplace only, not installed"
                add(sdir, key, status, 1 if at_install else (2 if area == "cache" else 3), pname, away=not here)
    project_hides = {} if only else setting(in_use / "settings.json", "skillOverrides") | folder_hides
    for p in ([] if only else [cwd, *cwd.parents]):
        for sdir in top_level_skills(p / ".claude" / "skills"): add(sdir, f"project {p.name}", "project skill", 0, hides=project_hides)
    for o in only:
        for sdir in top_level_skills(Path(o).expanduser()): add(sdir, f"only {o}", "folder skill", 0)
    for r in extra_roots:
        for sdir in walk_skills(Path(r).expanduser()): add(sdir, f"root {r}", "extra root", 0)
    by_hash, out = {}, []                      # identical SKILL.md = one skill; the best-ranked copy is shown, the rest as "also at"
    # at one rank, a copy in the config dir a session reads comes before one in a dir it does not, then the newest
    for e in sorted(entries, key=lambda e: (e["rank"], e["away"], -e["dir"].stat().st_mtime, str(e["dir"]))):
        h = hashlib.sha1((e["dir"] / "SKILL.md").read_bytes()).hexdigest()
        if h in by_hash: by_hash[h]["also"].append(f"{e['source']} [{e['status']}]"); by_hash[h]["own"] |= e["own"]; continue
        e["also"] = []; by_hash[h] = e; out.append(e)
    # The same skill again with other text (an older cached version, a copy in the second config folder, a user copy of a plugin
    # skill): same name and either the same plugin, the same user skills folder name, or the same description. The best-ranked copy
    # stays and names the rest. Two different skills that merely share a name stay apart: a "configure" in each of three plugins,
    # and two of one name under one --only folder, roots folder or project, whose label names a folder, not one skill's copies.
    def words(s): return " ".join(s.split()).lower()
    def lineage(e):
        if e["source"] == "user": return f"user {e['dir'].name}"
        if e["plugin"] == "?": return group_of(e)                            # no plugin.json: its folder in the cache or the marketplace
        return e["source"] if e["plugin"] else None
    kept, merged = {}, []
    for e in out:
        twin = next((k for k in kept.get(e["name"], []) if (lineage(e) and lineage(k) == lineage(e))
                     or (words(e["description"]) and words(k["description"]) == words(e["description"]))), None)
        if twin:
            here = f"{twin['source']} [{twin['status']}]"
            for place in [f"{e['source']} [{e['status']}]", *e["also"]]:
                if place != here and place not in twin["also"]: twin["also"].append(place)
            twin["own"] |= e["own"]
            continue
        kept.setdefault(e["name"], []).append(e); merged.append(e)
    for e in merged:                           # name only the other places: not the hit's own label again (a copy in the second config folder)
        e["also"] = [p for p in dict.fromkeys(e["also"]) if p != f"{e['source']} [{e['status']}]"]
    return merged

def searchable(entries):
    """The skills a search looks in: all but the finder itself, whose SKILL.md, README, TODO and bench notes hold the example phrases
    and would match most lookups. That is its own folder, any copy of it (see collect) and the row either merged into, whichever copy
    it shows; a skill that only shares its name stays."""
    return [e for e in entries if not e["own"]]

def terms_of(task):
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9+#._-]+", task.lower()) if w not in STOP]
    return sorted(set(words))

def pattern(t):                                 # a term starts a word: "test" matches "tests", not "latest"
    return re.compile(r"(?<![a-z0-9])" + re.escape(t))

def read_small(path, limit=300_000):
    try:
        if path.stat().st_size > limit: return ""
        return path.read_text(errors="replace")
    except Exception: return ""

REF_SKIP = {"logs", "log"}          # run logs are not references
REF_FILES_MAX = 120                 # reference files read a skill, references/ first
REF_BYTES_MAX = 2_000_000           # a reference file larger than this is not read

def reference_paths(sdir):
    """Every .md/.txt in a skill folder but SKILL.md: no skipped, hidden or log folders, no requirements files; references/ first."""
    out = []
    for root, dirs, files in os.walk(sdir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d not in REF_SKIP and not d.startswith(".")]
        out += [Path(root) / n for n in files if n.endswith((".md", ".txt")) and n != "SKILL.md" and not n.startswith((".", "requirements"))]
    return sorted(out, key=lambda p: (p.relative_to(sdir).parts[0] not in ("references", "reference"), p))

def doc_files(sdir):
    return [sdir / "SKILL.md"] + reference_paths(sdir)[:REF_FILES_MAX]

def prepare(entries):
    for e in entries:
        if "_refs" in e: continue                   # read once: a phrase search and its miss report both need them
        refs = reference_paths(e["dir"])
        e["_main"] = read_small(e["dir"] / "SKILL.md").lower()
        e["_refs"] = [(f, read_small(f, REF_BYTES_MAX).lower()) for f in refs[:REF_FILES_MAX]]
        e["_refs_unread"] = max(0, len(refs) - REF_FILES_MAX) + sum(1 for f, txt in e["_refs"] if not txt and f.stat().st_size > REF_BYTES_MAX)

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
    print("Read a section: Read the path above with offset <line>; the whole file: Read the path above.")

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
    print(f"table of contents: {len(es)} skill{'s' * (len(es) != 1)} in {len(groups)} folder{'s' * (len(groups) != 1)} ({said}; [off] = Claude does not get it here: plugin not enabled, not installed, installed for another project, another version, or off or user-invocable only in settings)")
    for g, v in groups:
        print(f"## {g} ({len(v)})")
        for e in v: print(toc_row(e, kind, headers_of(e["dir"] / "SKILL.md") if kind == "headers" else None))
    print("Narrow: --toc <folder> | one skill: --toc <skill> (headers) or --toc <skill> --kind files | open: Read <path>")

def phrase_pattern(phrase):
    """The words of a phrase in order, joined by space, newline, hyphen or underscore; the first word starts a word."""
    words = re.findall(r"[a-z0-9][a-z0-9+#.]*", phrase.lower())
    return re.compile(r"(?<![a-z0-9])" + r"[\s_-]+".join(re.escape(w) for w in words), re.I) if words else None

def near_misses(entries, phrases, extra=0):
    """For phrases nothing contains: how many skills hold each of their words, and the skills nearest by words (the --task
    ranking), so a miss still points somewhere. `extra` more rows, for a caller that drops some it already shows."""
    terms = terms_of(" ".join(phrases))
    if not terms: return {}, []
    ranked, _, _ = rank(entries, terms)
    said = " ".join(phrases).lower()
    counts = document_frequency(entries, {t: pattern(t) for t in sorted(terms, key=said.index)})      # in the order they were typed
    rows = [dict(score=round(s_, 1), name=e["name"], status=e["status"], source=e["source"], path=str(e["dir"] / "SKILL.md"),
                 description=" ".join(e["description"].split())[:110]) for s_, e in ranked[:CLOSEST + extra]]
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
        bits.append((f'"{ph}" is in {where}' + (f" and {times}" if times else "") if where
                     else f'"{ph}" occurs {times}, not in its name or description')
                    + (f' (line {line[0]}: "{line[1]}")' if line and line[2] == ph else ""))
    return "; ".join(bits)

def best_match(cands):
    """What a phrase search ends with: the first hit, why it matched, and where reading starts."""
    _, e, found, line, detail = cands[0]
    return dict(name=e["name"], path=str(e["dir"] / "SKILL.md"), plain=why_plain(detail, line), use_when=use_when(e),
                lines=body_lines(e, OPEN_LINES), references=[str(f.relative_to(e["dir"])) for f in doc_files(e["dir"])[1:]])

def print_best(b):
    print()
    print(f'Best match: {b["name"]}  {b["path"]}')
    print(f'Why: {b["plain"]}')
    print(f'Description: {b["use_when"]}')
    if b["lines"]:
        print("First lines of SKILL.md:"); [print(("  " + ln) if ln else "") for ln in b["lines"]]
    if b["references"]:
        print("References: " + names_line(b.get("references_distinct", b["references"]), len(b["references"]), ROW_REF_FILES))
    print(f'Read {b["path"]}, then follow it; search again only if it does not fit.')

def phrase_sections(shown):
    """The shown hits by where the phrase sits: in the name, else in the description, else in the body (ranking order kept inside each)."""
    sec = dict(name=[], description=[], body=[])
    for h in shown:
        found = h[4].values()
        sec["name" if any(d[0] for d in found) else "description" if any(d[1] for d in found) else "body"].append(h)
    return sec

def invoked_script(path=None, home=None):
    """The path this script was run by, as a command can use it: absolute, symlinks as given (not resolved), the home folder as ~.
    `__file__`, not sys.argv[0]: run as a script it is the path it was started by, and imported (the tests) it is still the module's own file."""
    p = os.path.abspath(path or __file__)
    home = (home if home is not None else os.path.expanduser("~")).rstrip(os.sep)
    return "~" + p[len(home):] if home and p.startswith(home + os.sep) else p

def how_many(n, limit):
    """The header's count of the skills that hold the phrase and, when it lists fewer, how to see more."""
    if n <= limit: return f"{n} skill(s) contain it"
    return (f"{n} skill(s) contain it; the best {limit} are shown" + (f", --limit {LIMIT_MORE} lists more" if limit < LIMIT_MORE else "")
            + ". A longer phrase narrows it")

def print_phrase_toc(entries, hits, sections, counts, nearest, limit):
    def row(e, tail=""):
        return f"{e['name']} — {first_sentence(e['description'], max(20, min(SENTENCE_MAX, ROW_MAX - len(e['name']) - 3 - len(tail)))) or '(no description)'}{tail}"
    if hits:
        if len(hits) > limit: print(how_many(len(hits), limit) + ".")
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
    print(f'Open the one that fits: python3 {invoked_script()} --toc "<name>" prints its path and sections. None fits: search other words, or --toc for the whole table.'
          if hits or nearest else "Search other words, or --toc for the whole table.")

REF_SHOWN = 5        # skills shown that hold a phrase only in their reference files
ROW_REF_PHRASES = 3  # a listed skill names at most this many phrases that only its reference files hold, then how many more
ROW_REF_FILES = 8    # ... and at most this many of its reference files, as the best match does

def excerpt(path, pats):
    """The line of a file where the first match of a phrase starts, as (line number, text, that phrase); a long line is cut around
    the match. `pats` holds (phrase, pattern) pairs."""
    text = read_small(path, REF_BYTES_MAX)
    ms = [(m, ph) for ph, pt in pats if (m := pt.search(text))]
    if not ms: return 0, "", None
    m, ph = min(ms, key=lambda x: x[0].start())
    start, end = text.rfind("\n", 0, m.start()) + 1, text.find("\n", m.start())
    line = text[start:end if end >= 0 else len(text)]
    cut = max(0, m.start() - start - 40) if len(line) > 140 else 0
    return text.count("\n", 0, m.start()) + 1, ("..." if cut else "") + " ".join(line[cut:cut + 140].split()), ph

def ranked_refs(e, pats):
    """A skill's reference files (see prepare), those that fit the looked-up phrases best first. A file scores, for each phrase its
    text holds, one over the number of the skill's reference files whose text holds that phrase: a phrase two files hold tells
    more than one thirty hold. A phrase in its path inside the skill scores the same way, over the files whose path holds it: a
    file named for the phrase counts, a folder that holds forty files hardly does. Files that score the same keep the order they
    are read in. A skill with fifty reference files can name eight in its row; these are the eight to name."""
    key = tuple(pt.pattern for _, pt in pats)
    if e.get("_ranked_for") != key:
        uniq = list({pt.pattern: pt for _, pt in pats}.values())
        rels = [str(f.relative_to(e["dir"])).lower() for f, _ in e["_refs"]]
        in_text = [{pt.pattern for pt in uniq if pt.search(text)} for _, text in e["_refs"]]
        in_path = [{pt.pattern for pt in uniq if pt.search(rel)} for rel in rels]
        df, pdf = {}, {}
        for held, count in ((in_text, df), (in_path, pdf)):
            for h in held:
                for pat in h: count[pat] = count.get(pat, 0) + 1
        score = [sum(1 / df[pat] for pat in t) + sum(1 / pdf[pat] for pat in p) for t, p in zip(in_text, in_path)]
        order = sorted(range(len(e["_refs"])), key=lambda i: (-score[i], i))
        e["_ranked"], e["_ranked_for"] = [e["_refs"][i] for i in order], key
    return e["_ranked"]

def distinct_refs(e, pats=()):
    """reference_files without the copies: of files with the same name and the same text (a skill that nests another holds its
    files twice), the first one. A list of eight names should name eight texts."""
    seen, out = set(), []
    for f, text in ranked_refs(e, pats):
        k = (f.name, hashlib.sha1(text.encode()).hexdigest()) if text else str(f)
        if k not in seen: seen.add(k); out.append(str(f.relative_to(e["dir"])))
    return out

def names_line(names, total, n):
    """`n` reference file names, then how many more the skill has; `names` are distinct texts, `total` counts the copies too."""
    more = total - min(n, len(names))
    tail = "" if not more else f" (+{more} more, copies of these)" if len(names) <= n else f" (+{more} more)"
    return ", ".join(names[:n]) + tail

def reference_only(e, pats, held):
    """The phrases a skill holds in a reference file (see prepare) but not in SKILL.md or its name (`held`), in the order they were
    typed. Each comes with one reference file that holds it, and the line where the phrase first matches there. Which file: one
    whose path holds the phrase; else one that no earlier phrase of this row points at, so three lines name three files when they
    can; among those the one that fits the whole lookup best (see ranked_refs)."""
    out, held, used = {}, {pt.pattern for ph, pt in pats if ph in held}, set()     # by pattern: "torch" and "Torch" are one phrase
    for ph, pt in pats:
        f = None
        if pt.pattern not in held and pt.pattern not in out:
            have = [(not pt.search(str(g.relative_to(e["dir"])).lower()), g in used, i, g) for i, (g, text) in enumerate(ranked_refs(e, pats)) if pt.search(text)]
            f = min(have)[3] if have else None
            used.add(f)
        if f:
            line, text, _ = excerpt(f, [(ph, pt)])
            out[pt.pattern] = dict(phrase=ph, file=str(f.relative_to(e["dir"])), line=line, text=text)
    return list(out.values())

def reference_files(e, pats=()):
    """A skill's reference files as paths inside its folder: those that fit the looked-up phrases best first (see ranked_refs), the
    rest in the order they are read."""
    return [str(f.relative_to(e["dir"])) for f, _ in ranked_refs(e, pats)]

def reference_hits(entries, pats, shown, held):
    """Skills outside the shown rows (`shown`) that hold a phrase in their reference files (see prepare) and not in SKILL.md or the
    name: skills whose SKILL.md holds no phrase first, then more such phrases, then more files (five count), then the name. `held` gives the phrases a SKILL.md hit holds there,
    which do not count for it. Each comes with its first matching line and the phrase on it."""
    out = []
    for e in entries:
        if id(e) in shown: continue
        mine = [(ph, pt) for ph, pt in pats if ph not in held.get(id(e), ())]
        found, files, first = [], 0, None
        for f, text in e["_refs"]:
            here = [ph for ph, pt in mine if pt.search(text)]
            if not here: continue
            files += 1
            found += [ph for ph in here if ph not in found]
            if first is None: first = (str(f.relative_to(e["dir"])), *excerpt(f, mine))
        if found: out.append(((id(e) in held, -len(found), -min(files, 5), e["name"]), e, found, first))
    out.sort(key=lambda h: h[0])
    return out

def phrase_search(entries, phrases, limit, as_json, toc=False):
    """`grep -il` over the whole SKILL.md of every skill, but ranked (so the shown ones do not depend on directory order) and
    compact: a phrase in the name first, then in the description, then how often it occurs. Several phrases are alternatives; a
    skill that holds more of them comes first. Under each shown skill: the phrases that only its reference files hold, with
    file:line (ROW_REF_PHRASES at most, then how many more), and its reference files (ROW_REF_FILES at most, see ranked_refs). Then up to REF_SHOWN
    skills that are not shown and hold a phrase only in their reference files, with file:line and the phrase: skills whose SKILL.md
    holds none, and hits beyond `limit`. With `toc` the hits print as sections (phrase in the name, the description, the body), one
    sentence each, no best match, and reference files are not read."""
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
                    line = (at + 1, " ".join(text.splitlines()[at].split())[:140], ph)
        if found: hits.append(((-len(found), -in_name, -in_desc, -min(count, 5), e["name"]), e, found, line, detail))
    hits.sort(key=lambda h: h[0])
    shown = hits[:limit]
    rows = [dict(name=e["name"], status=e["status"], source=e["source"], path=str(e["dir"] / "SKILL.md"), phrases=found,
                 description=" ".join(e["description"].split())[:110], match=f"{line[0]}: {line[1]}" if line else "", also=e["also"])
            for _, e, found, line, _ in shown]
    if not toc:
        prepare(entries)
        for r, (_, e, found, _, _) in zip(rows, shown): r.update(reference_only=reference_only(e, pats, found), references=reference_files(e, pats), references_distinct=distinct_refs(e, pats))
    refs = reference_hits(entries, pats, {id(h[1]) for h in shown}, {id(h[1]): h[2] for h in hits}) if not toc else []
    ref_rows = [dict(name=e["name"], status=e["status"], source=e["source"], path=str(e["dir"] / "SKILL.md"), phrases=found,
                     description=" ".join(e["description"].split())[:110], match=f"{first[0]}:{first[1]}: {first[2]}")
                for _, e, found, first in refs[:min(REF_SHOWN, limit)]]
    ref_said = [first[3] for _, _, _, first in refs[:len(ref_rows)]]         # the phrase on each row's line, for the text output
    unread = sum(e.get("_refs_unread", 0) for e in entries)
    counts, near = near_misses(entries, phrases, extra=len(ref_rows)) if not hits else ({}, [])
    if counts and not toc:                          # the word counts cover what the search read: SKILL.md, the name, the references
        counts = {t: sum(1 for e in entries if any(p.search(x) for x in (e["_main"], e["name"].lower(), *(r for _, r in e["_refs"]))))
                  for t, p in ((t, pattern(t)) for t in counts)}
    nearest = near[:CLOSEST]
    shown_near = [r for r in near if r["path"] not in {x["path"] for x in ref_rows}][:CLOSEST]      # a skill shown above is not listed twice
    best = best_match(hits) if hits and not toc else None
    if best: best.update(references=reference_files(hits[0][1], pats), references_distinct=distinct_refs(hits[0][1], pats))    # the first row's files, in its order
    sections = phrase_sections(shown) if toc else None
    if as_json:
        out = dict(phrases=phrases, scanned=len(entries), matched=len(hits), shown=len(rows), candidates=rows)
        if not toc: out.update(reference_matched=len(refs), reference_hits=ref_rows, reference_files_unread=unread)
        if not hits: out.update(word_counts=counts, nearest=nearest)
        elif not toc: out.update(best=best)
        if toc: out.update(sections={k: [h[1]["name"] for h in v] for k, v in sections.items()})
        print(json.dumps(out, indent=1)); return
    quoted = " | ".join(f'"{ph}"' for ph in phrases)
    where = "SKILL.md" if toc else "SKILL.md and reference files"
    print(f"phrase search: {quoted} in the {where} of {len(entries)} skills on disk (a phrase starts a word: 'plan' matches 'planning', not 'airplane')")
    if toc: return print_phrase_toc(entries, hits, sections, counts, nearest, limit)
    more = "" if len(refs) <= len(ref_rows) else f"; the first {len(ref_rows)} are shown"
    if not hits:
        if ref_rows:
            print(f"No SKILL.md contains it, but {len(refs)} skill(s) hold it in their reference files{more}. Open the SKILL.md of one that fits; "
                  "the line shown is in its reference file.\n")
            print_reference_rows(ref_rows, ref_said)
        else:
            print("No skill contains it. Try fewer words, another form of the word, or a word the finished thing is called.")
        if counts:
            print("Skills holding each word: " + ", ".join(f"{t} {n}" for t, n in counts.items()) + ". A word held by none is not how any skill says it.")
        if shown_near:
            print(f"\nNearest by words, not by phrase (--task \"{' '.join(counts)}\"); open one only if its description fits:")
            for i, r in enumerate(shown_near, 1):
                print(f"{i}. {r['name']}  [{r['status']}]  {r['path']}" + (f"\n   {r['description']}" if i <= CLOSEST_FULL else ""))
        elif counts and not ref_rows:
            print("No skill holds any of these words either.")
        if unread: print(f"Not read: {unread} reference file(s) over {REF_BYTES_MAX // 1_000_000} MB or past the first {REF_FILES_MAX} of a skill.")
        return
    print(how_many(len(hits), limit) + ". Best first: the phrase in the name, then in the description, then how often it occurs.\n")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['name']}  [{r['status']}]  {r['path']}")
        print(f"   {r['description']}")
        if r["match"]: print(f"   :{r['match']}")
        for x in r["reference_only"][:ROW_REF_PHRASES]: print(f'   :{x["file"]}:{x["line"]}: {x["text"]}  ("{x["phrase"]}")')
        if len(r["reference_only"]) > ROW_REF_PHRASES: print(f"   (+{len(r['reference_only']) - ROW_REF_PHRASES} more phrases only in its reference files)")
        if r["references"]:
            print("   references: " + names_line(r["references_distinct"], len(r["references"]), ROW_REF_FILES))
        if r["also"]: print(f"   also at: {'; '.join(r['also'][:2])}" + (f" (+{len(r['also']) - 2} more)" if len(r["also"]) > 2 else ""))
    if ref_rows:
        print(f"\nOnly in reference files ({len(refs)} skill(s) not listed above hold there a phrase their SKILL.md does not{more}):")
        print_reference_rows(ref_rows, ref_said)
    print_best(best)

def print_reference_rows(rows, said):
    """`said`: for each row, the phrase its line holds."""
    for r, ph in zip(rows, said):
        print(f"- {r['name']}  [{r['status']}]  {r['path']}")
        print(f"   {r['description']}")
        print(f'   :{r["match"]}  ("{ph}")')

def plain_name(n):
    """A skill name that is one folder name, so DIR/.claude/skills/<name> stays inside DIR/.claude/skills."""
    return n not in ("", ".", "..") and Path(n).name == n and "\\" not in n

def enable(entries, names, into, source):
    """Copy skills into DIR/.claude/skills so a session started in DIR can invoke them, whatever their plugin's
    state. Nothing global changes: settings.json is never touched. The copy loses its plugin namespace. It warns when a session
    started in DIR would not give Claude the copy: skillOverrides hides that folder name there, or a user skill of that name wins."""
    here = Path(into).expanduser().resolve()
    root, user = here / ".claude" / "skills", session_config()
    files = (user / "settings.json", *folder_files(here, git_root(here)))       # the files a session in DIR reads, later ones winning
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / ".skill-finder.json"
    done = json.loads(manifest.read_text()) if manifest.exists() else {}
    for n in names:
        cands = [e for e in entries if e["name"] == n and (not source or source in e["source"] or source in str(e["dir"]))]
        if not cands: print(f"no skill named {n}", file=sys.stderr); continue
        if len(cands) > 1: print(f"{n}: {len(cands)} different skills share this name; took the first ({cands[0]['dir']}); "
                                 f"others: {', '.join(str(c['dir']) for c in cands[1:])}; use --source with part of its source or path to choose", file=sys.stderr)
        e, dest = cands[0], root / n
        if not plain_name(n): print(f"{n}: not a plain folder name; left alone", file=sys.stderr); continue
        if dest.exists() and n not in done: print(f"{dest} exists and is not ours; left alone", file=sys.stderr); continue
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(e["dir"], dest, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        done[n] = str(e["dir"])
        note = ""
        if any("CLAUDE_PLUGIN_ROOT" in read_small(f) for f in dest.rglob("*") if f.is_file() and f.suffix in (".md", ".sh", ".py", ".json")):
            note = "  WARNING: refers to CLAUDE_PLUGIN_ROOT; its scripts may not find their files from here"
        print(f"enabled {n}  ({e['status']}; {e['source']}) -> {dest}{note}")
        state, at = None, None
        for f in files:
            s = setting(f, "skillOverrides").get(n)
            if s: state, at = s, f
        if state in ("off", "user-invocable-only"):
            print(f'  WARNING: skillOverrides sets {n} to "{state}" in {at}; Claude cannot invoke the copy in a session started in {here}')
        mine = user / "skills" / n                 # personal beats project, by folder name
        if (mine / "SKILL.md").is_file() and mine.resolve() != e["dir"].resolve():
            print(f"  WARNING: a user skill of that name is at {mine}; a session started in {here} runs it, not the copy")
    manifest.write_text(json.dumps(done, indent=1) + "\n")

def remove(into):
    root = Path(into).expanduser().resolve() / ".claude" / "skills"
    manifest = root / ".skill-finder.json"
    if not manifest.exists(): print("nothing to remove", file=sys.stderr); return
    for n in json.loads(manifest.read_text()):
        if not plain_name(n): print(f"{n}: not a plain folder name; left alone", file=sys.stderr); continue
        shutil.rmtree(root / n, ignore_errors=True); print(f"removed {n}")
    manifest.unlink()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=""); ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--phrase", action="append", nargs="+", default=[], metavar="WORD",
                    help="an exact phrase to look for in every SKILL.md, then in reference files; quotes optional after a space (repeatable: alternatives)")
    ap.add_argument("--limit", type=int, default=PHRASE_LIMIT,
                    help=f"--phrase: how many skills to list (default {PHRASE_LIMIT}; the header says when more hold the phrase, and --limit {LIMIT_MORE} lists more)")
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
    for words in a.phrase:                                      # `--phrase "release notes" "changelog"` is two phrases, not one
        if len(words) > 1 and any(len(w.split()) > 1 for w in words):
            sys.exit("--phrase " + " ".join(f'"{w}"' for w in words) + ": each phrase needs its own --phrase")
    a.phrase = [" ".join(words) for words in a.phrase]          # `--phrase release notes` is the phrase "release notes"
    if a.kind and a.phrase: sys.exit("--kind goes with --toc alone")
    if a.kind and a.toc is None: sys.exit("--kind needs --toc")
    if a.toc is not None:
        for flag in (a.enable and "--enable", a.remove and "--remove"):
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
        return phrase_search(searchable(entries), a.phrase, a.limit, a.json, a.toc is not None)
    if a.list or not a.task:
        w = max([32, *(len(e["status"]) for e in entries)])        # "plugin installed for <project> only" can be longer
        for e in entries:
            print(f"{e['status']:<{w}} {e['source']:<40} {e['name']:<36} {e['dir']}")
        print(f"\n{len(entries)} skills", file=sys.stderr); return
    entries = searchable(entries)
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
