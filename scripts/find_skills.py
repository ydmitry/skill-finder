#!/usr/bin/env python3
"""Find the skills that fit a task across the skill folders on this machine.

  find_skills.py --task "explain this PR as a page" [--top 8] [--root DIR ...] [--json]
  find_skills.py --phrase "implementation plan" [--phrase "task breakdown" ...] [--limit 40] [--json]
  find_skills.py --list
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
    return out

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

def phrase_search(entries, phrases, limit, as_json, for_text=""):
    """`grep -il` over the whole SKILL.md of every skill, but ranked (so the shown ones do not depend on directory order) and
    compact: a phrase in the name first, then in the description, then how often it occurs. Several phrases are alternatives; a
    skill that holds more of them comes first."""
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
                 description=" ".join(e["description"].split())[:110], match=f"{line[0]}: {line[1]}" if line else "")
            for _, e, found, line, _ in shown]
    counts, nearest = near_misses(entries, phrases) if not hits else ({}, [])
    best = best_match(hits, for_text) if hits else None
    if as_json:
        out = dict(phrases=phrases, scanned=len(entries), matched=len(hits), shown=len(rows), candidates=rows)
        if not hits: out.update(word_counts=counts, nearest=nearest)
        else: out.update(best=best)
        print(json.dumps(out, indent=1)); return
    quoted = " | ".join(f'"{ph}"' for ph in phrases)
    print(f"phrase search: {quoted} in the SKILL.md of {len(entries)} skills on disk (a phrase starts a word: 'plan' matches 'planning', not 'airplane')")
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
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--enable", nargs="+", default=[]); ap.add_argument("--remove", action="store_true")
    ap.add_argument("--into"); ap.add_argument("--source", default="")
    a = ap.parse_args()
    if a.remove:
        if not a.into: sys.exit("--remove needs --into DIR")
        return remove(a.into)
    entries = collect(a.root + ([] if a.only else default_roots()), a.only)
    if a.enable:
        if not a.into: sys.exit("--enable needs --into DIR")
        return enable(entries, a.enable, a.into, a.source)
    if a.phrase:
        if a.task: sys.exit("use --phrase or --task, not both")
        return phrase_search(entries, a.phrase, a.limit, a.json, a.for_text)
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
