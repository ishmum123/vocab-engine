"""Stage tag: the spec's tagger (spaCy, or spec.tag_texts: Stanza for fa/id)
over the corpus, truecasing the sentence-initial token. tag_docs/doc_tokens
are the shared tagging entry point (also used by passages)."""
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
    sp = env.spec
    ver = sp.versions["tag"]
    if sp.tagger != "spacy" or sp.spacy_model is None:
        # non-spaCy tagger (fa: Stanza): the spec names it and tags the texts
        desc = sp.tagger_desc()
        sig = hashlib.sha1(f"{ver}|{desc}|{corpus_file.name}".encode()).hexdigest()[:10]
        return env.derived / f"tagged_{ver}_{sig}.jsonl.gz", desc
    import spacy
    model = spacy.util.get_package_version(sp.spacy_model)
    sig = hashlib.sha1(f"{ver}|{spacy.__version__}|{sp.spacy_model}-{model}|{corpus_file.name}".encode()).hexdigest()[:10]
    return env.derived / f"tagged_{ver}_{sig}.jsonl.gz", f"spaCy {spacy.__version__}, {sp.spacy_model} {model}"


def tag_docs(sp, texts, n_process=None):
    """Run the spec's tagger over tagger-ready texts (truecased, spec.tag_text
    applied). Returns (docs, fields): docs in text order, and fields(doc) ->
    (text, lemma, upos, {feature: value}) per token. spaCy for a spec with
    tagger "spacy" and a spacy_model (n_process defaults to
    spec.spacy_n_process); otherwise spec.tag_texts (fa, id: Stanza), which
    already yields such tuples. spaCy is imported only on the spaCy branch."""
    if sp.tagger != "spacy" or sp.spacy_model is None:
        return sp.tag_texts(texts), lambda doc: doc
    import spacy
    nlp = spacy.load(sp.spacy_model, exclude=["parser", "ner"])
    sp.setup_nlp(nlp)
    docs = nlp.pipe(texts, batch_size=2000, n_process=sp.spacy_n_process if n_process is None else n_process)
    return docs, lambda doc: ((t.text, t.lemma_, t.pos_, t.morph.to_dict()) for t in doc if not t.is_space)


def doc_tokens(sp, doc, fields, row):
    """One tagged doc -> the sentence's [text, lemma, upos, morph] tokens:
    morph string over spec.morph_keep, spec.fix_token per token, then
    spec.fix_sentence(toks, row, doc). row is the corpus row
    [sid, text, user, english, audio, licence] the doc was tagged from."""
    keep = sp.morph_keep or MORPH_KEEP
    toks = []
    for text, lemma, pos, md in fields(doc):
        ms = "|".join(f"{k}={md[k]}" for k in keep if k in md)
        toks.append(sp.fix_token([text, lemma, pos, ms]))
    return sp.fix_sentence(toks, row, doc)


def stage_tag(env, corpus):
    sp = env.spec
    out, desc = tagged_path(env, corpus_path(env))
    stat("tagger", desc)
    meta_path = out.with_suffix(".meta.json")
    if out.exists() and meta_path.exists():
        stat("tag_meta", json.loads(meta_path.read_text()))
        return out
    t0 = time.time()
    rows = corpus["rows"]
    low, cap = truecase_stats(rows, sp.word_re, sp.sentence_openers)
    texts = [truecase(r[1], low, cap, sp.word_re) for r in rows]
    n_lowered = sum(1 for r, t in zip(rows, texts) if r[1] != t)
    texts = [sp.tag_text(t) for t in texts]
    docs, fields = tag_docs(sp, texts)
    tmp = out.with_suffix(".part")
    n_tok = 0
    with gzip.GzipFile(tmp, "wb", mtime=0) as g:
        for r, doc in zip(rows, docs):
            toks = doc_tokens(sp, doc, fields, r)
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
