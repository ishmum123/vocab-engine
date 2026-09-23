"""English side: crude stemming for gloss <-> translation overlap. Shared by
every language (glosses and translations are English)."""
import re

EN_WORD_RE = re.compile(r"[a-z]+")
EN_STOP = set("""a an the of to in on at for with by from as and or but not no is are was were be
been being am do does did have has had it its this that these those there here i you he she we they
me him her us them my your his our their what which who whom whose when where why how all any some
one ones something someone somebody thing things very so too just than then also only into out up
down about over after before again if will would shall should can could may might must let s t
don isn didn doesn won aren wasn weren haven hasn ll re ve d m used denote denotes indicate
indicates indicating expressing express expresses especially particularly etc sense senses kind
type form""".split())
EN_IRREG = {
    "is": "be", "are": "be", "was": "be", "were": "be", "am": "be", "been": "be", "being": "be",
    "has": "have", "had": "have", "having": "have", "did": "do", "does": "do", "done": "do",
    "went": "go", "gone": "go", "goes": "go", "said": "say", "says": "say", "made": "make",
    "saw": "see", "seen": "see", "took": "take", "taken": "take", "came": "come", "knew": "know",
    "known": "know", "got": "get", "gotten": "get", "gave": "give", "given": "give",
    "thought": "think", "told": "tell", "found": "find", "left": "leave", "felt": "feel",
    "brought": "bring", "bought": "buy", "ate": "eat", "eaten": "eat", "wrote": "write",
    "written": "write", "spoke": "speak", "spoken": "speak", "ran": "run", "sat": "sit",
    "stood": "stand", "understood": "understand", "met": "meet", "paid": "pay", "sold": "sell",
    "sent": "send", "spent": "spend", "built": "build", "kept": "keep", "slept": "sleep",
    "drank": "drink", "drunk": "drink", "began": "begin", "begun": "begin", "chose": "choose",
    "chosen": "choose", "fell": "fall", "fallen": "fall", "held": "hold", "lost": "lose",
    "meant": "mean", "put": "put", "read": "read", "heard": "hear", "taught": "teach",
    "caught": "catch", "fought": "fight", "won": "win", "wore": "wear", "worn": "wear",
    "broke": "break", "broken": "break", "forgot": "forget", "forgotten": "forget",
    "children": "child", "men": "man", "women": "woman", "people": "person", "feet": "foot",
    "teeth": "tooth", "mice": "mouse", "better": "good", "best": "good", "worse": "bad",
    "worst": "bad", "lives": "life", "wives": "wife", "knives": "knife", "leaves": "leaf",
    "died": "die", "dying": "die", "lying": "lie", "lied": "lie",
}


EN_VOCAB = set()   # raw English word forms seen in the corpus translations
_STEM = {}


def en_stem(w):
    """Map an inflected English word to its base form, choosing only bases
    attested in the corpus vocabulary (making -> make, stopped -> stop,
    boxes -> box), so unrelated words never collide (plane != plan)."""
    if w in _STEM:
        return _STEM[w]
    r = EN_IRREG.get(w)
    if r is None:
        r = w
        tries = []
        if len(w) > 4 and w.endswith("ies"):
            tries = [w[:-3] + "y"]
        elif len(w) > 3 and w.endswith("es"):
            tries = [w[:-2], w[:-1]]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            tries = [w[:-1]]
        elif len(w) > 5 and w.endswith("ing"):
            b = w[:-3]
            tries = [b + "e", b, b[:-1] if len(b) > 2 and b[-1] == b[-2] else None]
        elif len(w) > 4 and w.endswith("ed"):
            b = w[:-2]
            tries = [w[:-1], b, b[:-1] if len(b) > 2 and b[-1] == b[-2] else None,
                     b[:-1] + "y" if b.endswith("i") else None]
        for t in tries:
            if t and t in EN_VOCAB:
                r = t
                break
    _STEM[w] = r
    return r


EN_CONTRACTION_RE = re.compile(r"(n't|'s|'re|'ll|'ve|'m|'d)\b")


def en_stems(text, keep_stop=False):
    out = []
    text = text.lower().replace("’", "'").replace("can't", "can not").replace("won't", "will not")
    text = EN_CONTRACTION_RE.sub(lambda m: " not" if m.group(1) == "n't" else " ", text)
    for w in EN_WORD_RE.findall(text):
        if not keep_stop and w in EN_STOP:
            continue
        out.append(en_stem(w))
    return out
