#!/usr/bin/env python3
"""One-off, reproducible converter: hsk repo data -> packs/zh.

Reads (never writes) the hsk repo:
  data/hsk_vocab.json       [{w,py,n,en,lv}]
  data/hsk_sentences.js     const SENTENCE_EXTRA={token:{py,base}}; const SENTENCES=[{zh,py,en,lv,words}]
  data/pinyin_lessons.js    const LESSONS=[...]   (JS literal, evaluated with node)
  src/pinyin_core.js        SENTENCE_FUNCTION_WORDS -> pack.functionWords

Writes packs/zh/{pack,words,sentences,lessons}.json, then regenerates the .js
consts via jsonify_pack.py. Output is deterministic (running twice is a no-op).

Sentence `words` are resolved to word ids here, at build time:
  1. longest match first: adjacent hsk tokens that are contiguous in the sentence text
     and whose concatenation is itself a VOCAB word (为+什么 -> 为什么) resolve to
     that longer word;
  2. a VOCAB word maps to its own id;
  3. a SENTENCE_EXTRA compound (e.g. 这个) maps to its `base` word's id (这).
Any token that resolves none of these ways is listed and the script exits 1.
SENTENCE_EXTRA keys also become pack.compounds, so the engine never blanks 这
out of 这个 in a cloze.

Usage: python3 tools/pack_from_hsk.py [HSK_REPO_DIR]   (default: ../hsk beside this repo)
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

    def resolve(token):
        if token in id_of:
            return id_of[token], None
        e = extra.get(token)
        if e and e.get("base") in id_of:
            return id_of[e["base"]], token
        return None, None

    # ---- sentences
    out_sent, fallback, unresolved, merged = [], {}, [], {}
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

        segs = []
        while j < len(toks):
            for k in (4, 3, 2):
                cat = "".join(toks[j:j + k])
                if j + k <= len(toks) and cat in id_of and contiguous(j, j + k):
                    merged[cat] = merged.get(cat, 0) + 1
                    segs.append(cat)
                    j += k
                    break
            else:
                segs.append(toks[j])
                j += 1
        for tok in segs:
            wid, via = resolve(tok)
            if wid is None:
                unresolved.append((sid, s["zh"], tok))
                continue
            if via:
                fallback[via] = fallback.get(via, 0) + 1
            ids.append(wid)
        out_sent.append({"id": sid, "t": s["zh"], "en": s["en"], "lv": str(s["lv"]), "words": ids, "pron": s["py"]})

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
        # Typing Chinese needs an IME; hsk's typed drill was pinyin, which the engine
        # never drills (pron is display-only). Production for zh is recall-only.
        "typing": None,
        "showPron": True,
        "hasLessons": True,
        "spaced": False,
        "compounds": sorted(extra.keys()),
    }

    os.makedirs(OUT, exist_ok=True)
    dump(os.path.join(OUT, "pack.json"), pack)
    dump(os.path.join(OUT, "words.json"), words)
    dump(os.path.join(OUT, "sentences.json"), out_sent)
    dump(os.path.join(OUT, "lessons.json"), lessons)

    total_tokens = sum(len(s["words"]) for s in sentences)  # hsk tokens, before merging
    print(f"words {len(words)}  sentences {len(out_sent)}  lessons {len(lessons)}  functionWords {len(fw)}")
    print(f"sentence tokens {total_tokens}: {sum(fallback.values())} resolved via SENTENCE_EXTRA base, {len(unresolved)} unresolved")
    print(f"longest-match merges of adjacent hsk tokens: {sum(merged.values())}")
    for tok in sorted(merged, key=lambda t: (-merged[t], t)):
        print(f"  MERGE {tok} x{merged[tok]}")
    for tok in sorted(fallback, key=lambda t: (-fallback[t], t)):
        print(f"  EXTRA {tok} -> {extra[tok]['base']} x{fallback[tok]}")
    for n in fw_notes:
        print("  " + n)
    for sid, zh, tok in unresolved:
        print(f"  UNRESOLVED {sid} {zh} token {tok}")

    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "jsonify_pack.py"), OUT], check=True)
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
