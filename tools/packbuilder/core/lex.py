"""Stage lex: kaikki (Wiktionary) -> compact lexicon + inflection/form map."""
import gzip
import hashlib
import json
import re
import time
from collections import defaultdict

from .sources import kaikki_plain
from .util import log, file_sig

FORM_TAGS = {"form-of"}
ALT_TAGS = {"alt-of"}

NONDEF_RE = re.compile(
    r"^(alternative |obsolete |archaic |dialectal |regional |past |present |future |imperfect |perfect )*"
    r"(form|forms|inflection|participle|gerund|singular|plural|masculine|feminine|imperative|"
    r"subjunctive|indicative|conditional|ellipsis|abbreviation|initialism|acronym|apocopic|elided|"
    r"superlative|diminutive|augmentative|first-person|second-person|third-person|compound of|"
    r"synonym|reflexive)\b.*\bof\b",
    re.IGNORECASE)
FORM_OF_ANY_RE = re.compile(r"^\S+(\s+\S+){0,6}\s+forms? of\b", re.IGNORECASE)


def _borrow_en(d):
    for t in d.get("etymology_templates", []):
        a = t.get("args", {})
        n = t.get("name", "")
        if n in ("bor", "bor+", "lbor", "ubor", "der", "der+") and a.get("2") == "en":
            return True
        if n == "ety" and str(a.get("3", "")).startswith("en:"):
            return True
    return bool(re.search(r"\b(borrowing|borrowed) from English\b", d.get("etymology_text", "") or ""))


def lex_path(env):
    ver = env.spec.versions["lex"]
    sig = hashlib.sha1(f"{ver}|{file_sig(kaikki_plain(env))}".encode()).hexdigest()[:10]
    return env.derived / f"lex_{ver}_{sig}.json.gz"


def stage_lex(env):
    sp = env.spec
    out = lex_path(env)
    if out.exists():
        with gzip.open(out, "rt", encoding="utf-8") as f:
            return json.load(f)
    env.derived.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    entries = defaultdict(list)
    formmap = defaultdict(set)
    names = set()   # lowercase forms of capitalised proper-name headwords
    n = 0
    needle = f'"lang_code": "{sp.kaikki_lang_code}"'
    with open(kaikki_plain(env), encoding="utf-8") as f:
        for line in f:
            if needle not in line:
                continue
            d = json.loads(line)
            if d.get("lang_code") != sp.kaikki_lang_code:
                continue
            word, pos = d.get("word", ""), d.get("pos", "")
            if pos == "name" and word[:1].isupper():
                names.add(word.lower())
            if not sp.lex_word_re.match(word):
                continue
            n += 1
            senses = []
            for s in d.get("senses", []):
                gl = s.get("glosses") or []
                tags = sorted(set(s.get("tags", [])))
                tset = set(tags)
                kind = ""
                target = None
                if s.get("form_of") or tset & FORM_TAGS:
                    kind = "form"
                    target = (s.get("form_of") or [{}])[0].get("word")
                elif "misspelling" in tset:
                    kind = "miss"
                elif s.get("alt_of") or tset & ALT_TAGS:
                    kind = "alt"
                    target = (s.get("alt_of") or [{}])[0].get("word")
                elif "compound-of" in tset:
                    kind = "comp"
                elif gl and (NONDEF_RE.match(gl[0]) or NONDEF_RE.match(gl[-1]) or FORM_OF_ANY_RE.match(gl[-1])):
                    # form-of senses that Wiktionary left untagged
                    # ("first-person plural present indicative of potere")
                    kind = "form"
                    m = sp.form_target_re.search(gl[0] + " " + gl[-1])
                    target = m.group(1) if m else None
                if kind in ("form", "alt") and target and sp.lex_word_re.match(target):
                    formmap[word].add((target, pos, kind))
                if not gl:
                    continue
                senses.append([gl[-1].strip(), gl[0].strip() if len(gl) > 1 else "", tags, kind])
                if kind == "form" and "; " in gl[-1]:
                    # "comparative degree of molto; more": the part after ';' is a translation
                    senses.append([gl[-1].split("; ")[-1].strip(), "",
                                   sorted(set(t for t in tags if t != "form-of") | {"from-form-sense"}), ""])
            if any(s[3] == "comp" for s in senses):
                for t in d.get("etymology_templates", []):
                    if t.get("name") == "af":
                        base = str(t.get("args", {}).get("2", "")).split("<")[0]
                        if sp.lex_word_re.match(base):
                            formmap[word].add((base, pos, "comp"))
                        break
            if not senses:
                continue
            ent = {"p": pos, "s": senses[:30]}
            g = sp.gender_from_entry(d)
            if g:
                ent["g"] = g
            if _borrow_en(d):
                ent["b"] = 1
            entries[word].append(ent)
    result = {
        "entries": dict(entries),
        "formmap": {k: sorted(v) for k, v in formmap.items()},
        "names": sorted(names),
        "n_entries": n,
    }
    with gzip.GzipFile(out, "wb", mtime=0) as g:
        g.write(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    log(f"lex: {n} single-word entries, {len(result['formmap'])} inflected/alt surfaces ({time.time()-t0:.0f}s)")
    return result
