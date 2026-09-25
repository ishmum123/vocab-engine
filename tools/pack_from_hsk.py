#!/usr/bin/env python3
"""One-off, reproducible converter: hsk repo data -> packs/zh.

Reads (never writes) the hsk repo:
  data/hsk_vocab.json       [{w,py,n,en,lv}]
  data/hsk_sentences.js     const SENTENCE_EXTRA={token:{py,base}}; const SENTENCES=[{zh,py,en,lv,words}]
  data/pinyin_lessons.js    const LESSONS=[...]   (JS literal, evaluated with node)
  src/pinyin_core.js        SENTENCE_FUNCTION_WORDS -> pack.functionWords

Writes packs/zh/{pack,words,sentences,lessons,characters,legacy}.json, then
regenerates the .js consts via jsonify_pack.py. Output is deterministic
(running twice is a no-op).

Sentence `words` are resolved to word ids here, at build time:
  1. longest match first: adjacent hsk tokens that are contiguous in the sentence text
     and whose concatenation is itself a VOCAB word (为+什么 -> 为什么) resolve to
     that longer word;
  2. a VOCAB word maps to its own id;
  3. a SENTENCE_EXTRA compound (e.g. 这个) maps to its `base` word's id (这).
Any token that resolves none of these ways is listed and the script exits 1.
SENTENCE_EXTRA keys also become pack.compounds, so the engine never blanks 这
out of 这个 in a cloze.

Each resolved sentence token also gets a `sentences[].ruby` tuple
[start, end, reading, wordId] at its literal UTF-16 offset in the sentence
text (docs/HSK_MERGE.md §2.3): reading is the SENTENCE_EXTRA compound's own
`py` when resolved that way, else the resolved word's own `pron`.

`characters.json` mirrors words.json one-to-one (hsk teaches whole words, not
glyphs: docs/HSK_MERGE.md §2.1), and `legacy.json`/`pack.legacy` carry the
hsk_pinyin -> vocab_zh progress-migration id maps (docs/HSK_MERGE.md §4).

Usage: python3 tools/pack_from_hsk.py [HSK_REPO_DIR]   (default: ../hsk beside this repo)
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# English for hsk sentences whose upstream `en` is unusable (the hsk repo is read-only):
# sentence text -> English. The build fails if any PLACEHOLDER_ string survives.
EN_OVERRIDES = {
    "我们应该看自己的优点，也要改变缺点。": "We should look at our own strengths, and also change our weaknesses.",
}
OUT = os.path.join(ROOT, "packs", "zh")


def js_const_json(path, name):
    """Extract `const NAME=<json>;` (single line, JSON-valid) from a generated hsk data file."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*const\s+" + name + r"\s*=\s*(.*);\s*$", line)
            if m:
                return json.loads(m.group(1))
    raise SystemExit(f"pack_from_hsk: const {name} not found in {path}")


def js_literal_via_node(path, name):
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    code = ("const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');"
            f"process.stdout.write(JSON.stringify(new Function(src+';return {name};')()));")
    out = subprocess.run([node, "-e", code, path], check=True, capture_output=True)
    return json.loads(out.stdout.decode("utf-8"))


def dump(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    cur = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cur = f.read()
    if cur != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(path, ROOT)}")


def main(argv):
    hsk = os.path.abspath(argv[0]) if argv else os.path.join(os.path.dirname(ROOT), "hsk")
    vocab = json.load(open(os.path.join(hsk, "data", "hsk_vocab.json"), encoding="utf-8"))
    sent_path = os.path.join(hsk, "data", "hsk_sentences.js")
    extra = js_const_json(sent_path, "SENTENCE_EXTRA")
    sentences = js_const_json(sent_path, "SENTENCES")
    lessons = js_literal_via_node(os.path.join(hsk, "data", "pinyin_lessons.js"), "LESSONS")
    core_src = open(os.path.join(hsk, "src", "pinyin_core.js"), encoding="utf-8").read()
    m = re.search(r"const SENTENCE_FUNCTION_WORDS\s*=\s*(\[[^\]]*\]);", core_src)
    if not m:
        raise SystemExit("pack_from_hsk: SENTENCE_FUNCTION_WORDS not found in hsk src/pinyin_core.js")
    fw_strings = json.loads(m.group(1))

    # ---- words: ids in hsk file order (which is also set order within a level)
    words, id_of = [], {}
    for i, v in enumerate(vocab):
        wid = f"w{i + 1:04d}"
        if v["w"] in id_of:
            raise SystemExit(f"pack_from_hsk: duplicate hsk word {v['w']}")
        id_of[v["w"]] = wid
        words.append({"id": wid, "w": v["w"], "en": v["en"], "lv": str(v["lv"]), "pron": v["py"]})
    pron_of = {w["id"]: w["pron"] for w in words}

    def resolve(token):
        if token in id_of:
            return id_of[token], None
        e = extra.get(token)
        if e and e.get("base") in id_of:
            return id_of[e["base"]], token
        return None, None

    # ---- sentences
    out_sent, fallback, unresolved, merged, unplaced = [], {}, [], {}, []
    for i, s in enumerate(sentences):
        sid = f"s{i + 1:04d}"
        ids = []
        toks, j = s["words"], 0
        # Each token's start offset in the sentence text (sequential search; None when a
        # token isn't found literally). Tokens merge only when they are contiguous at
        # these positions, so a concatenation that happens to occur elsewhere in the
        # sentence can't trigger a merge.
        pos, cur = [], 0
        for tok in toks:
            at = s["zh"].find(tok, cur)
            pos.append(at if at >= 0 else None)
            if at >= 0:
                cur = at + len(tok)

        def contiguous(a, b):
            return all(pos[x] is not None for x in range(a, b)) and all(
                pos[x] + len(toks[x]) == pos[x + 1] for x in range(a, b - 1))

        segs = []  # (text, start) pairs; start is None if the token wasn't found literally
        while j < len(toks):
            for k in (4, 3, 2):
                cat = "".join(toks[j:j + k])
                if j + k <= len(toks) and cat in id_of and contiguous(j, j + k):
                    merged[cat] = merged.get(cat, 0) + 1
                    segs.append((cat, pos[j]))
                    j += k
                    break
            else:
                segs.append((toks[j], pos[j]))
                j += 1
        ruby = []
        for tok, start in segs:
            wid, via = resolve(tok)
            if wid is None:
                unresolved.append((sid, s["zh"], tok))
                continue
            if via:
                fallback[via] = fallback.get(via, 0) + 1
            ids.append(wid)
            if start is not None:
                reading = extra[via]["py"] if via else pron_of[wid]
                ruby.append([start, start + len(tok), reading, wid])
            else:
                unplaced.append((sid, s["zh"], tok))
        ruby.sort(key=lambda r: r[0])
        rec = {"id": sid, "t": s["zh"], "en": EN_OVERRIDES.get(s["zh"], s["en"]), "lv": str(s["lv"]), "words": ids, "pron": s["py"]}
        if ruby:
            rec["ruby"] = ruby
        out_sent.append(rec)

    # ---- function words (compounds collapse onto their base word)
    fw, fw_notes = [], []
    for tok in fw_strings:
        wid, via = resolve(tok)
        if wid is None:
            fw_notes.append(f"function word {tok} unresolved (dropped)")
            continue
        if via:
            fw_notes.append(f"function word {tok} -> base {extra[tok]['base']} ({wid})")
        if wid not in fw:
            fw.append(wid)

    levels = sorted({w["lv"] for w in words}, key=int)
    pack = {
        "key": "zh",
        "name": "Mandarin (HSK 1–4)",
        "tts": "zh-CN",
        "ttsRate": 0.85,
        "levels": [{"id": lv, "label": f"HSK {lv}"} for lv in levels],
        "setSize": 10,
        "placement": [["1", 3], ["2", 3], ["3", 4], ["4", 6]],
        "functionWords": fw,
        # Typing Chinese needs an IME, so the typed production step types the pinyin
        # instead (hsk's typed drill; docs/PACK_SCHEMA.md "Pronunciation aids"): the same
        # word slot recall uses, never a stand-alone pinyin drill.
        "typing": "pron",
        "showPron": True,
        "hasLessons": True,
        "spaced": False,
        "compounds": sorted(extra.keys()),
        # hsk teaches whole words, not glyphs, so a character unit is one known word
        # (docs/HSK_MERGE.md §2.1): one-to-one with words.json, same order.
        "characters": {
            "label": "字",
            "stages": [{"after": "3", "levels": ["1", "2", "3"]}, {"after": "4", "levels": ["4"]}],
            "setSize": 10,
            "mastered": 3,
            "bare": 6,
            "learnKinds": ["charPick", "charRead"],
            "reviewKinds": ["charRead", "charSound"],
            "testKinds": {"charRead": 40, "charSound": 30, "charPick": 30},
        },
        "legacy": {"key": "hsk_pinyin", "format": "hsk-v2"},
        # Pronunciation first (docs/HSK_MERGE.md §8, 2026-09-25): a word is shown by its
        # pinyin until its character unit reaches the mastered tier, as hsk does.
        "pronFirst": True,
        # Pronunciation aids (docs/PACK_SCHEMA.md, brief BP2): pinyin syllables coloured
        # by tone as hsk did, and a Reference card of every lesson sound in the Sounds tab.
        "tones": "pinyin",
        "soundsReference": True,
    }

    # ---- characters: one unit per word, same order as words.json (docs/HSK_MERGE.md §2.1).
    # Unit id = "c" + the word id's digits (w0416 -> c0416): ids follow word ids and are
    # never renumbered (they are progress keys).
    characters = []
    for w in words:
        if not re.fullmatch(r"w\d+", w["id"]):
            raise SystemExit(f"pack_from_hsk: word id {w['id']!r} is not w<digits>; unit ids derive from it")
        characters.append({
            "id": "c" + w["id"][1:],
            "t": w["w"],
            "words": [w["id"]],
            "lv": w["lv"],
            "reading": w["pron"],
        })
    # ---- legacy map for the hsk_pinyin -> vocab_zh progress migration (docs/HSK_MERGE.md §4)
    legacy = {
        "w": {w["w"]: w["id"] for w in words},
        "s": {s["t"]: s["id"] for s in out_sent},
        "c": {c["t"]: c["id"] for c in characters},
    }

    unused = set(EN_OVERRIDES) - {x["t"] for x in out_sent}
    if unused:
        raise SystemExit(f"pack_from_hsk: EN_OVERRIDES keys match no sentence: {sorted(unused)}")
    ph = sorted({m for part in (words, out_sent, lessons) for m in re.findall(r"PLACEHOLDER_\w+", json.dumps(part, ensure_ascii=False))})
    if ph:
        raise SystemExit(f"pack_from_hsk: placeholder text in the output (add EN_OVERRIDES): {ph}")

    os.makedirs(OUT, exist_ok=True)
    dump(os.path.join(OUT, "pack.json"), pack)
    dump(os.path.join(OUT, "words.json"), words)
    dump(os.path.join(OUT, "sentences.json"), out_sent)
    dump(os.path.join(OUT, "lessons.json"), lessons)
    dump(os.path.join(OUT, "characters.json"), characters)
    dump(os.path.join(OUT, "legacy.json"), legacy)

    total_tokens = sum(len(s["words"]) for s in sentences)  # hsk tokens, before merging
    ruby_tokens = sum(len(s.get("ruby", ())) for s in out_sent)
    print(f"words {len(words)}  sentences {len(out_sent)}  lessons {len(lessons)}  functionWords {len(fw)}")
    print(f"characters {len(characters)}  legacy w={len(legacy['w'])} s={len(legacy['s'])} c={len(legacy['c'])}")
    print(f"sentence tokens {total_tokens}: {sum(fallback.values())} resolved via SENTENCE_EXTRA base, {len(unresolved)} unresolved, ruby tokens {ruby_tokens}, unplaced (no ruby) {len(unplaced)}")
    print(f"longest-match merges of adjacent hsk tokens: {sum(merged.values())}")
    for tok in sorted(merged, key=lambda t: (-merged[t], t)):
        print(f"  MERGE {tok} x{merged[tok]}")
    for tok in sorted(fallback, key=lambda t: (-fallback[t], t)):
        print(f"  EXTRA {tok} -> {extra[tok]['base']} x{fallback[tok]}")
    for n in fw_notes:
        print("  " + n)
    for sid, zh, tok in unresolved:
        print(f"  UNRESOLVED {sid} {zh} token {tok}")
    for sid, zh, tok in unplaced:
        print(f"  UNPLACED (no literal offset, no ruby) {sid} {zh} token {tok}")

    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "jsonify_pack.py"), OUT], check=True)
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
