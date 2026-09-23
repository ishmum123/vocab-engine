"""Stage tag: spaCy over the corpus, truecasing the sentence-initial token."""
import gzip
import hashlib
import json
import time
from collections import Counter

from .sources import corpus_path
from .util import log, stat

MORPH_KEEP = ("Gender", "Number", "Tense", "Mood", "VerbForm", "Person", "Clitic")


def truecase_stats(rows, word_re, openers=""):
    """For each lowercase word: (#mid-sentence lowercase, #mid-sentence
    capitalised) occurrences in the corpus. `openers` are extra characters that
    open a sentence (es: ¿ ¡) and are skipped like quotes."""
    low, cap = Counter(), Counter()
    strip = " \"'«»“”‘’-—()" + openers
    for r in rows:
        text = r[1]
        for m in word_re.finditer(text):
            before = text[:m.start()].rstrip(strip)
            if not before or before[-1] in ".!?:;…":
                continue            # sentence-initial (also after an internal full stop)
            t = m.group(0)
            if t[0].isupper():
                if t[1:].islower() or len(t) == 1:
                    cap[t.lower()] += 1
            else:
                low[t] += 1
    return low, cap


def truecase(text, low, cap, word_re):
    """Lowercase the sentence-initial letter unless the word is mostly
    capitalised mid-sentence (a proper noun); small spaCy lemmatisers and
    taggers are case-sensitive and mis-handle 'Chiudi', 'Odio', 'Portami'."""
    m = word_re.search(text)
    if not m or not text[m.start()].isupper():
        return text
    w = m.group(0)
    lw = w.lower()
    if w != w[0] + w[1:].lower():  # all-caps / camel: leave
        return text
    if low[lw] >= cap[lw] and (low[lw] > 0 or cap[lw] == 0):
        return text[:m.start()] + lw[0] + text[m.start() + 1:]
    return text


def tagged_path(env, corpus_file):
    import spacy
    sp = env.spec
    ver = sp.versions["tag"]
    model = spacy.util.get_package_version(sp.spacy_model)
    sig = hashlib.sha1(f"{ver}|{spacy.__version__}|{sp.spacy_model}-{model}|{corpus_file.name}".encode()).hexdigest()[:10]
    return env.derived / f"tagged_{ver}_{sig}.jsonl.gz", f"spaCy {spacy.__version__}, {sp.spacy_model} {model}"


def stage_tag(env, corpus):
    sp = env.spec
    out, desc = tagged_path(env, corpus_path(env))
    stat("tagger", desc)
    meta_path = out.with_suffix(".meta.json")
    if out.exists() and meta_path.exists():
        stat("tag_meta", json.loads(meta_path.read_text()))
        return out
    import spacy
    t0 = time.time()
    rows = corpus["rows"]
    low, cap = truecase_stats(rows, sp.word_re, sp.sentence_openers)
    texts = [truecase(r[1], low, cap, sp.word_re) for r in rows]
    n_lowered = sum(1 for r, t in zip(rows, texts) if r[1] != t)
    texts = [sp.tag_text(t) for t in texts]
    nlp = spacy.load(sp.spacy_model, exclude=["parser", "ner"])
    sp.setup_nlp(nlp)
    keep = sp.morph_keep or MORPH_KEEP
    tmp = out.with_suffix(".part")
    n_tok = 0
    with gzip.GzipFile(tmp, "wb", mtime=0) as g:
        for r, doc in zip(rows, nlp.pipe(texts, batch_size=2000, n_process=sp.spacy_n_process)):
            toks = []
            for t in doc:
                if t.is_space:
                    continue
                md = t.morph.to_dict()
                ms = "|".join(f"{k}={md[k]}" for k in keep if k in md)
                toks.append(sp.fix_token([t.text, t.lemma_, t.pos_, ms]))
            toks = sp.fix_sentence(toks, r, doc)
            n_tok += len(toks)
            g.write((json.dumps([r[0], toks], ensure_ascii=False) + "\n").encode("utf-8"))
    tmp.replace(out)
    meta = {"sentences": len(rows), "tokens": n_tok, "seconds": round(time.time() - t0, 1),
            "truecased_initials": n_lowered}
    meta_path.write_text(json.dumps(meta, sort_keys=True))
    stat("tag_meta", meta)
    log(f"tag: {len(rows)} sentences, {n_tok} tokens in {meta['seconds']}s")
    return out


def iter_tagged(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)
