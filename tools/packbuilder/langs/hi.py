"""Hindi (hi): everything Hindi-specific in the pack pipeline.

Tagger: Stanza (hi default package, UD Hindi-HDTB model); spaCy has no Hindi
pipeline. Stanza gives infinitive verb lemmas (गया -> जाना) but drops the
nukta from lemmas (बाज़ार -> बाजार): fix_token puts it back from the surface.

Spelling: every matching side is NFC (so precomposed nukta letters क़ ख़ ग़ ज़
ड़ ढ़ फ़ become base + nukta), Devanagari digits are folded to ASCII, ZWJ/ZWNJ
are dropped and chandrabindu is folded to anusvara (हँसना = हंसना) for lookup
only; the displayed word keeps the dictionary spelling (finalize_words), and
spellings the corpus writes differently (हां, जिंदगी) are added as alts so the
engine finds the word in its sentences. Nukta-less spellings resolve through
Wiktionary's "nuqtaless form of" pointers.

Lemmas: verbs are infinitives (-ना); nouns singular direct; adjectives
masculine direct. Pronoun case forms (मुझे, उसने, उन्हें) link their pronoun;
possessives (मेरा, उसका, आपका) are words of their own. Copula forms (है, हैं,
था, थे, थी, थीं, हो) link होना.

Compounds (one lemma each, both tokens linked): compound postpositions (के
लिए, के बाद, के बारे में; also after a possessive: मेरे लिए), light verbs
(noun + करना/होना/आना/लगना/देना...: काम करना, मदद करना, याद आना) and a
hand list of vector compounds (चला जाना, भूल जाना, ले आना). A light verb may be
separated from its noun by particles (भी, नहीं, ही, तो) and one adverb. The
conjunctive कर after a verb stem (खा कर) and the passive जाना after a
perfective participle (किया गया) link nothing.

Sentences: Tatoeba has ~13.8k Hindi sentences with an English link; all
16.5k are tagged (frequency and lemma evidence). Words left under 2 sentences
get sentences written for the pack (tools/generated_sentences.tsv, "src":
"gen" in sentences.json).
"""
import gzip
import hashlib
import json
import re
import unicodedata

from .base import (LanguageSpec, TATOEBA_ENG, TATOEBA_AUDIO, DEFAULT_GROUP_KPOS, SENSITIVE_EN,
                   SENSITIVE_GLOSS_EN, drop_all_re, make_word_ceiling_re)

DEV = "\u0900-\u0963\u0971-\u097f"          # Devanagari letters and signs (no danda, no digits)
NUKTA, CANDRA, ANUSVARA, VIRAMA = "\u093c", "\u0901", "\u0902", "\u094d"
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
ZW_RE = re.compile("[\u200c\u200d\u200b\ufeff]")
TOKEN_PUNCT = "।॥|.,!?;:\"'()[]{}…-–—‘’“”"
GEN_SID_BASE = 90_000_000          # corpus sids of sentences written for the pack


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


# a nasal consonant + virama before a stop of its own class is written with
# anusvara as often as not (लम्बा = लंबा, हिन्दी = हिंदी, पन्द्रह = पंद्रह)
NASAL_CONJ_RE = re.compile("ङ\u094d(?=[क-घ])|ञ\u094d(?=[च-झ])|ण\u094d(?=[ट-ढ])|न\u094d(?=[त-ध])|म\u094d(?=[प-भ])")
# perfective/adjective glide spellings: गये = गए, गयी = गई, नयी = नई, लिये = लिए, चाहिये = चाहिए
GLIDE_RE = re.compile("(?<=[" + DEV + "])य(\u0947|\u0940)(\u0902?)(?![" + DEV + "])")
_GLIDE = {"\u0947": "ए", "\u0940": "ई"}


def fold(s):
    """Matching spelling (every side: kaikki headwords, frequency lists, tagged
    tokens): NFC, ZWJ/ZWNJ dropped, Devanagari digits -> ASCII, chandrabindu ->
    anusvara, nukta dropped (Tatoeba and Stanza's lemmas write ज़ as ज as often
    as not), a class nasal + virama -> anusvara, word-final glide ये/यी -> ए/ई.
    The shipped spelling is the dictionary's (finalize_words)."""
    if not s:
        return s
    s = ZW_RE.sub("", nfc(s)).translate(DIGITS).replace(CANDRA, ANUSVARA).replace(NUKTA, "")
    s = NASAL_CONJ_RE.sub(ANUSVARA, s)
    return GLIDE_RE.sub(lambda m: _GLIDE[m.group(1)] + m.group(2), s)


def dev_rx(term):
    """Regex source for a Devanagari term on NFC text: nukta optional, chandrabindu
    = anusvara, bounded by non-Devanagari (Python's \\b fails on vowel signs)."""
    out = []
    for ch in nfc(term):
        if ch == NUKTA:
            continue
        out.append("[\u0901\u0902]" if ch in (CANDRA, ANUSVARA) else re.escape(ch))
        if ch in "कखगजडढफ":
            out.append("\u093c?")
    return "".join(out)


def normalize_pron(p):
    """Wiktionary's Hindi romanisation (IAST-like: ā ī ū ṭ ḍ ṇ ṛ ś ṣ, x ġ q z f
    for nukta letters, a tilde for nasal vowels), with its double tilde over a
    diphthong (ma͠i) written on the first vowel (mãi)."""
    if not p:
        return p
    p = nfc(p.strip())
    p = re.sub("(.)\u0360(.)", "\\1\u0303\\2", p)
    return nfc(p)


# ---- closed sets (NFC spellings; fold() is applied where they are matched) ----
DAYS = "सोमवार मंगलवार बुधवार गुरुवार शुक्रवार शनिवार रविवार".split()
MONTHS = "जनवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर अक्टूबर नवंबर दिसंबर".split()
SEASONS = "गर्मी सर्दी बरसात वसंत पतझड़ मौसम".split()
NUMBERS = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह "
           "उन्नीस बीस तीस चालीस पचास साठ सत्तर अस्सी नब्बे सौ हज़ार").split()
COLOURS = "लाल नीला हरा पीला काला सफ़ेद भूरा गुलाबी नारंगी बैंगनी".split()
GREETINGS = [("नमस्ते", "INTJ"), ("नमस्कार", "INTJ"), ("धन्यवाद", "INTJ"), ("शुक्रिया", "INTJ"),
             ("हाँ", "INTJ"), ("जी", "PART"), ("अलविदा", "INTJ"), ("कृपया", "ADV")]
PRONOUNS = "मैं तू तुम आप वह यह हम वे ये कोई कुछ सब जो ख़ुद".split()
POSSESSIVES = "मेरा तेरा तुम्हारा आपका उसका इसका उनका इनका हमारा अपना किसका".split()
QUESTION = [("क्या", "PRON"), ("कौन", "PRON"), ("कहाँ", "ADV"), ("कब", "ADV"), ("क्यों", "ADV"),
            ("कैसे", "ADV"), ("कैसा", "DET"), ("कितना", "DET")]
POSTPS = "का को से में पर तक ने".split()
CONJS = [("और", "CONJ"), ("या", "CONJ"), ("लेकिन", "CONJ"), ("कि", "CONJ"), ("क्योंकि", "CONJ"),
         ("अगर", "CONJ"), ("जब", "ADV"), ("तब", "ADV"), ("तो", "CONJ"), ("इसलिए", "ADV")]
PARTICLES = [("ही", "PART"), ("भी", "PART"), ("नहीं", "PART"), ("न", "PART"), ("मत", "PART")]
PHRASES = {"माफ़ कीजिए": "excuse me; sorry", "ठीक है": "okay, all right", "कोई बात नहीं": "no problem, never mind",
           "फिर मिलेंगे": "see you (again), see you later"}

# pronoun case forms -> the pronoun (any tag); possessive forms -> the possessive
PRON_FORMS = {
    "मुझे": "मैं", "मुझको": "मैं", "मैंने": "मैं", "मुझ": "मैं",
    "तुझे": "तू", "तुझको": "तू", "तूने": "तू", "तुझ": "तू",
    "तुम्हें": "तुम", "तुमको": "तुम", "तुमने": "तुम", "तुम्हे": "तुम",
    "आपको": "आप", "आपने": "आप",
    "हमें": "हम", "हमको": "हम", "हमने": "हम", "हमे": "हम",
    "उसे": "वह", "उसको": "वह", "उसने": "वह", "उस": "वह", "वो": "वह",
    "इसे": "यह", "इसको": "यह", "इसने": "यह", "इस": "यह",
    "उन्हें": "वे", "उनको": "वे", "उन्होंने": "वे", "उन": "वे", "उन्हे": "वे",
    "इन्हें": "ये", "इनको": "ये", "इन्होंने": "ये", "इन": "ये",
    "किसे": "कौन", "किसको": "कौन", "किसने": "कौन", "किस": "कौन", "किन्हें": "कौन", "किन": "कौन",
    "जिसे": "जो", "जिसको": "जो", "जिसने": "जो", "जिस": "जो", "जिन्हें": "जो", "जिन्होंने": "जो", "जिन": "जो",
    "किसी": "कोई", "सभी": "सब", "सबको": "सब", "सबने": "सब", "खुद": "ख़ुद",
}
POSS_FORMS = {}
for _p in POSSESSIVES:
    _stem = _p[:-1]
    for _e in ("ा", "ी", "े"):
        POSS_FORMS[_stem + _e] = _p
COPULA_FORMS = {"है", "हैं", "हूं", "हूँ", "था", "थे", "थी", "थीं", "हो", "हों"}
# Tatoeba's stock names that Stanza may read as words
NAMES = {"टॉम", "मैरी", "जॉन", "सामी", "लैला", "केन", "जिम", "बॉब", "एलिस", "जेन", "जैक", "बिल", "माइक",
         "टोनी", "लूसी"}
PROFANE = ("चूतिया", "चुतिया", "मादरचोद", "बहनचोद", "भेनचोद", "भोसड़ी", "भोसडी", "रंडी", "हरामी", "हरामज़ादा",
           "हरामजादा", "चूत", "साला", "साली", "गांड", "गाँड", "लौड़ा", "लौडा", "लंड", "चुदाई", "चोदना", "चोद", "कुतिया", "कमीना", "कमीने")

# ---- compound postpositions: "phrase|gloss"; matched on tokens after a
# genitive का/की/के (or से) or a possessive pronoun form (मेरे लिए, उसकी तरफ़) --
POSTP_SRC = """
के लिए|for
के बाद|after
के साथ|with, together with
के बारे में|about
की तरफ़|towards
के पास|near; (X के पास) X has
के बिना|without
से पहले|before
के पहले|before
की तरह|like, in the manner of
के अलावा|apart from, besides
के अंदर|inside
के बाहर|outside
के ऊपर|above, on top of
के नीचे|under, below
के पीछे|behind
के सामने|in front of
के बीच|between, among
के कारण|because of
की वजह से|because of
के बजाय|instead of
के ख़िलाफ़|against
के तौर पर|as, by way of
की ओर|towards
के क़रीब|near, close to
के दौरान|during
के आसपास|around
के ज़रिए|through, by means of
के मुताबिक़|according to
के अनुसार|according to
के बावजूद|despite
"""
POSTP = {}          # folded phrase -> gloss
POSTP_TAIL = {}     # folded tail tokens (tuple) -> [(folded head or "", folded phrase)]
for _line in POSTP_SRC.strip().splitlines():
    _phrase, _gloss = _line.split("|")
    _parts = [fold(p) for p in _phrase.split()]
    POSTP[" ".join(_parts)] = _gloss
    POSTP_TAIL.setdefault(tuple(_parts[1:]), []).append((_parts[0], " ".join(_parts)))

# ---- light verbs: "noun verb|gloss" (noun + करना/होना/आना/लगना/देना/रखना...) ----
LIGHT_VERBS_SRC = """
काम करना|to work
बात करना|to talk, to speak
मदद करना|to help
प्यार करना|to love
कोशिश करना|to try
इंतज़ार करना|to wait
शुरू करना|to start, to begin
शुरू होना|to start, to begin (intr.)
ख़त्म करना|to finish, to end
ख़त्म होना|to end, to be over
याद करना|to remember; to miss
याद आना|to be remembered, to come to mind; to miss
याद रखना|to keep in mind, to remember
याद होना|to remember, to know by heart
पसंद करना|to like
पसंद आना|to be liked (मुझे पसंद आया: I liked it)
पसंद होना|to be liked (मुझे पसंद है: I like)
शादी करना|to marry, to get married
शादी होना|to get married
तैयार करना|to prepare, to get ready
तैयार होना|to get ready
बंद करना|to close, to shut; to turn off
बंद होना|to close, to be shut
साफ़ करना|to clean
फ़ोन करना|to phone, to call
इस्तेमाल करना|to use
मना करना|to refuse; to forbid
माफ़ करना|to forgive, to excuse
ख़्याल रखना|to take care of, to look after
ध्यान रखना|to take care, to be careful
ध्यान देना|to pay attention
जवाब देना|to answer, to reply
ठीक करना|to fix, to repair
ठीक होना|to get better, to be fixed
ग़लती करना|to make a mistake
पूरा करना|to complete, to finish
पूरा होना|to be completed
पता होना|to know (मुझे पता है: I know)
पता चलना|to find out, to come to know
पता करना|to find out
मज़ा आना|to enjoy, to have fun
मज़ाक करना|to joke
गुस्सा आना|to get angry
गुस्सा होना|to be angry
डर लगना|to be afraid
भूख लगना|to be hungry
प्यास लगना|to be thirsty
अच्छा लगना|to like, to feel good
बुरा लगना|to feel bad, to mind
ज़रूरत होना|to need
यात्रा करना|to travel
सफ़र करना|to travel
आराम करना|to rest
पढ़ाई करना|to study
बहस करना|to argue
वादा करना|to promise
भरोसा करना|to trust
विश्वास करना|to believe, to trust
दर्द होना|to hurt, to ache
बीमार होना|to fall ill
परेशान करना|to bother, to trouble
परेशान होना|to be worried, to be troubled
शर्म आना|to feel ashamed, to feel shy
नींद आना|to feel sleepy
समझ आना|to understand, to make sense
तारीफ़ करना|to praise
शिकायत करना|to complain
स्वागत करना|to welcome
फ़ैसला करना|to decide
तय करना|to decide, to settle
ख़र्च करना|to spend
जमा करना|to collect; to deposit
दिखाई देना|to be seen, to appear
सुनाई देना|to be heard
महसूस करना|to feel
महसूस होना|to be felt, to feel
चोरी करना|to steal
नौकरी करना|to work (in a job)
मुलाक़ात करना|to meet
मुलाक़ात होना|to meet (by chance)
कम करना|to reduce
हासिल करना|to obtain, to achieve
पैदा होना|to be born
इलाज करना|to treat (medically)
सवाल करना|to ask a question
खाना बनाना|to cook
प्राप्त करना|to obtain, to receive
प्राप्त होना|to be received, to be obtained
गाड़ी चलाना|to drive
हाथ मिलाना|to shake hands
हार मानना|to give up, to admit defeat
रोक लगाना|to ban, to put a stop to
"""
# ---- vector compounds: "V1-form V2|gloss" (first token: the V1 stem or, for
# चला/ले/दे, the form written) ----------------------------------------------
VECTOR_SRC = """
चला जाना|to go away, to leave
भूल जाना|to forget
हो जाना|to become; to happen
ले जाना|to take (away)
ले आना|to bring
आ जाना|to come, to arrive
मिल जाना|to be found; to meet
बैठ जाना|to sit down
सो जाना|to fall asleep
समझ जाना|to understand, to realise
पहुँच जाना|to arrive, to reach
उठ जाना|to get up
रुक जाना|to stop
गिर जाना|to fall down
बच जाना|to survive, to escape
मर जाना|to die
छोड़ देना|to leave, to give up
कर देना|to do (for someone), to get done
दे देना|to hand over, to give away
ले लेना|to take, to accept
रख देना|to put down
बता देना|to tell
रख लेना|to keep
"""
VECTOR_V1 = {"चला": "चलना", "चली": "चलना", "चले": "चलना"}
LIGHT_VERBS = {}          # folded compound -> gloss
LV_INDEX = {}             # folded verb -> {folded noun: folded compound}
VECTORS = {}              # folded compound -> gloss
VEC_INDEX = {}            # folded V2 -> {folded V1 lemma: folded compound}
for _src, _tab in ((LIGHT_VERBS_SRC, LIGHT_VERBS), (VECTOR_SRC, VECTORS)):
    for _line in _src.strip().splitlines():
        _phrase, _gloss = _line.split("|")
        _parts = [fold(p) for p in _phrase.split()]
        _comp = " ".join(_parts)
        _tab[_comp] = _gloss
        if _tab is LIGHT_VERBS:
            LV_INDEX.setdefault(_parts[-1], {})[_parts[0]] = _comp
        else:
            _v1 = VECTOR_V1.get(_parts[0], _parts[0] + "ना")
            VEC_INDEX.setdefault(_parts[-1], {})[fold(_v1)] = _comp
LV_GAP_OK = {fold(x) for x in ("भी", "नहीं", "ही", "तो", "न", "मत", "ना", "बहुत", "ज़्यादा", "थोड़ा", "जल्दी",
                                   "क्यों", "कब", "कैसे", "कहाँ")}
PERF_PART = ("Aspect=Perf", "VerbForm=Part")

# ---- script primer (docs/SCRIPT_PRIMER.md ss3) -------------------------------
# Devanagari: 73 units in 10 sets. Independent vowels, their matras (vowel signs
# on a consonant, `base` = the vowel), consonants with the inherent a, nukta
# letters, the signs ं ँ ः ्, and six conjuncts with shapes of their own. Romans
# follow the pack's pron scheme (Wiktionary IAST-like); a consonant's roman
# carries its inherent a (क ka, alt k). Sets are ordered so that early sets
# already spell A1 words (काम, नाम, पानी, हम).
# (set, group, slug, glyph, name, roman, alt, confuse slugs, note, base slug)
HI_SCRIPT = [
    (1, "vowel", "a", "अ", "a", "a", [], ["aa"], "short a, as in 'about'", None),
    (1, "vowel", "aa", "आ", "ā", "ā", ["aa"], ["a", "o"], "long a, as in 'father'", None),
    (1, "matra", "m-aa", "ा", "ā kī mātrā", "ā", ["aa"], ["m-o", "m-au"], "the ā sign: क + ा = का kā", "aa"),
    (1, "velar", "ka", "क", "ka", "ka", ["k"], ["qa", "pha"], "k, with the inherent a", None),
    (1, "dental", "ta", "त", "ta", "ta", ["t"], ["tta", "tra"], "t with the tongue on the teeth", None),
    (1, "dental", "na", "न", "na", "na", ["n"], ["nna", "ta"], "n", None),
    (1, "labial", "ma", "म", "ma", "ma", ["m"], ["bha", "ya"], "m", None),
    (1, "semivowel", "ra", "र", "ra", "ra", ["r"], ["va", "rr"], "a tapped r", None),
    (1, "sibilant", "sa", "स", "sa", "sa", ["s"], ["sha", "ssa"], "s", None),
    (1, "labial", "pa", "प", "pa", "pa", ["p"], ["ssa", "ya"], "p, without a puff of air", None),
    (1, "semivowel", "la", "ल", "la", "la", ["l"], ["ra"], "l", None),
    (1, "velar", "ga", "ग", "ga", "ga", ["g"], ["gha", "ghha"], "g as in 'go'", None),
    (2, "vowel", "i", "इ", "i", "i", [], ["ii"], "short i, as in 'bit'", None),
    (2, "vowel", "ii", "ई", "ī", "ī", ["ii", "ee"], ["i"], "long i, as in 'machine'", None),
    (2, "matra", "m-i", "ि", "choṭī i kī mātrā", "i", [], ["m-ii"], "the i sign, written before the consonant: कि ki", "i"),
    (2, "matra", "m-ii", "ी", "baṛī ī kī mātrā", "ī", ["ii", "ee"], ["m-i"], "the ī sign: की kī", "ii"),
    (2, "sibilant", "ha", "ह", "ha", "ha", ["h"], ["da"], "h", None),
    (2, "semivowel", "ya", "य", "ya", "ya", ["y"], ["tha", "ma"], "y", None),
    (2, "semivowel", "va", "व", "va", "va", ["v", "w"], ["ba", "ra"], "v/w, between English v and w", None),
    (3, "vowel", "u", "उ", "u", "u", [], ["uu"], "short u, as in 'put'", None),
    (3, "vowel", "uu", "ऊ", "ū", "ū", ["uu", "oo"], ["u"], "long u, as in 'rule'", None),
    (3, "matra", "m-u", "ु", "choṭā u kī mātrā", "u", [], ["m-uu"], "the u sign, below the consonant: कु ku", "u"),
    (3, "matra", "m-uu", "ू", "baṛā ū kī mātrā", "ū", ["uu", "oo"], ["m-u"], "the ū sign: कू kū", "uu"),
    (3, "labial", "ba", "ब", "ba", "ba", ["b"], ["va"], "b", None),
    (3, "palatal", "ja", "ज", "ja", "ja", ["j"], ["za"], "j", None),
    (3, "dental", "da", "द", "da", "da", ["d"], ["dda", "ha"], "d with the tongue on the teeth", None),
    (3, "sign", "virama", "्", "halant", "halant", [], ["anusvara"],
     "removes the inherent a; joins consonants: क्या kyā", None),
    (4, "vowel", "e", "ए", "e", "e", [], ["ai"], "e as in 'café', long", None),
    (4, "vowel", "ai", "ऐ", "ai", "ai", [], ["e"], "ai, like the a in 'cat'", None),
    (4, "vowel", "o", "ओ", "o", "o", [], ["au"], "o as in 'go', no glide", None),
    (4, "vowel", "au", "औ", "au", "au", [], ["o"], "au, like the o in 'office'", None),
    (4, "matra", "m-e", "े", "e kī mātrā", "e", [], ["m-ai"], "the e sign, above: के ke", "e"),
    (4, "matra", "m-ai", "ै", "ai kī mātrā", "ai", [], ["m-e"], "the ai sign: है hai", "ai"),
    (4, "matra", "m-o", "ो", "o kī mātrā", "o", [], ["m-au", "m-aa"], "the o sign: को ko", "o"),
    (4, "matra", "m-au", "ौ", "au kī mātrā", "au", [], ["m-o", "m-aa"], "the au sign: कौन kaun", "au"),
    (4, "palatal", "ca", "च", "ca", "ca", ["c", "ch"], ["cha", "va"], "ch as in 'church', no puff of air", None),
    (4, "palatal", "cha", "छ", "cha", "cha", ["chh"], ["ca"], "ch with a puff of air", None),
    (4, "sign", "anusvara", "ं", "anusvār", "ṁ", ["n", "m", "ṅ"], ["candrabindu"],
     "a nasal: n or m before a consonant (हिंदी hindī), a nasal vowel at the end (में mẽ)", None),
    (4, "sign", "candrabindu", "ँ", "candrabindu", "ã", [], ["anusvara"], "makes the vowel nasal: हाँ hā̃", None),
    (5, "velar", "kha", "ख", "kha", "kha", ["kh"], ["xa", "ka"], "k with a puff of air", None),
    (5, "velar", "gha", "घ", "gha", "gha", ["gh"], ["dha", "ga"], "g with a puff of air", None),
    (5, "dental", "tha", "थ", "tha", "tha", ["th"], ["ya", "ta"], "dental t with a puff of air (not English th)", None),
    (5, "dental", "dha", "ध", "dha", "dha", ["dh"], ["gha", "da"], "dental d with a puff of air", None),
    (5, "labial", "bha", "भ", "bha", "bha", ["bh"], ["ma", "ba"], "b with a puff of air", None),
    (5, "labial", "pha", "फ", "pha", "pha", ["ph"], ["fa", "pa"], "p with a puff of air", None),
    (5, "palatal", "jha", "झ", "jha", "jha", ["jh"], ["ja"], "j with a puff of air", None),
    (6, "retroflex", "tta", "ट", "ṭa", "ṭa", ["ṭ"], ["ta", "ttha"], "t with the tongue curled back", None),
    (6, "retroflex", "ttha", "ठ", "ṭha", "ṭha", ["ṭh"], ["ddha", "tta"], "ṭ with a puff of air", None),
    (6, "retroflex", "dda", "ड", "ḍa", "ḍa", ["ḍ"], ["nga", "rr", "da"], "d with the tongue curled back", None),
    (6, "retroflex", "ddha", "ढ", "ḍha", "ḍha", ["ḍh"], ["ttha", "rrh"], "ḍ with a puff of air", None),
    (6, "retroflex", "nna", "ण", "ṇa", "ṇa", ["ṇ"], ["na"], "n with the tongue curled back", None),
    (7, "sibilant", "sha", "श", "śa", "śa", ["ś", "sh"], ["ssa", "sa"], "sh as in 'ship'", None),
    (7, "sibilant", "ssa", "ष", "ṣa", "ṣa", ["ṣ"], ["sha", "pa"], "sh, said like श in Hindi", None),
    (7, "vowel", "r", "ऋ", "ŕ", "ŕ", ["ri"], ["ra"], "ri (Sanskrit words): ऋषि ŕṣi", None),
    (7, "matra", "m-r", "ृ", "ŕ kī mātrā", "ŕ", ["ri"], ["m-u"], "the ŕ sign, below: कृ kŕ", "r"),
    (8, "nukta", "rr", "ड़", "ṛa", "ṛa", ["ṛ"], ["dda", "ra"], "a flapped r, the tongue flicks forward: बड़ा baṛā", None),
    (8, "nukta", "rrh", "ढ़", "ṛha", "ṛha", ["ṛh"], ["ddha", "rr"], "ṛ with a puff of air: पढ़ना paṛhnā", None),
    (8, "nukta", "za", "ज़", "za", "za", ["z"], ["ja"], "z (Persian, Arabic and English words)", None),
    (8, "nukta", "fa", "फ़", "fa", "fa", ["f"], ["pha"], "f (Persian, Arabic and English words)", None),
    (8, "nukta", "qa", "क़", "qa", "qa", ["q"], ["ka"], "q, a k from the throat; often said k", None),
    (8, "nukta", "xa", "ख़", "xa", "xa", ["x", "kh"], ["kha"], "x, like ch in Scottish 'loch'", None),
    (8, "nukta", "ghha", "ग़", "ġa", "ġa", ["ġ"], ["ga"], "ġ, a throaty g like French r", None),
    (8, "vowel", "ao", "ऑ", "ŏ", "ŏ", ["aw"], ["o", "au"], "o as in British 'hot' (English words): ऑफ़िस ŏfis", None),
    (8, "matra", "m-ao", "ॉ", "ŏ kī mātrā", "ŏ", ["aw"], ["m-o", "m-au"],
     "the ŏ sign, a moon over the o sign: डॉक्टर ḍŏkṭar, कॉलेज kŏlej", "ao"),
    (9, "velar", "nga", "ङ", "ṅa", "ṅa", ["ṅ"], ["dda"], "ng as in 'sing' (rare)", None),
    (9, "palatal", "nya", "ञ", "ña", "ña", ["ñ"], ["ja"], "ny (rare)", None),
    (9, "sign", "visarga", "ः", "visarg", "ḥ", ["h"], ["virama"], "a light h after a vowel: दुःख duḥkh", None),
    (10, "conjunct", "ksa", "क्ष", "kṣa", "kṣa", ["ksh"], ["ka", "tra"], "k + ṣ: क्षमा kṣamā", None),
    (10, "conjunct", "tra", "त्र", "tra", "tra", ["tr"], ["ta", "ksa"], "t + r: मित्र mitra", None),
    (10, "conjunct", "jna", "ज्ञ", "jña", "jña", ["gya"], ["ja", "sra"], "j + ñ, said gy: ज्ञान jñān", None),
    (10, "conjunct", "sra", "श्र", "śra", "śra", ["shr"], ["sha", "jna"], "ś + r: श्री śrī", None),
    (10, "conjunct", "dya", "द्य", "dya", "dya", ["dy"], ["da", "dva"], "d + y: विद्या vidyā", None),
    (10, "conjunct", "dva", "द्व", "dva", "dva", ["dv"], ["da", "dya"], "d + v: द्वार dvār", None),
]
HI_SCRIPT_NOTES = [
    {"st": "deva", "set": 1, "h": "The inherent a",
     "body": "Every consonant letter carries a short a: क is ka. A vowel sign (mātrā) replaces it: का kā. "
             "At the end of a word the a is usually silent: नाम nām, not nāma."},
    {"st": "deva", "set": 2, "h": "ि comes first",
     "body": "The short i sign is written before its consonant but read after it: कि ki, दिन din."},
    {"st": "deva", "set": 3, "h": "Halant and half letters",
     "body": "् removes the inherent a. Usually the first consonant of a cluster is written as a half "
             "letter joined to the next: क्या kyā, बच्चा baccā, प्यार pyār."},
    {"st": "deva", "set": 3, "h": "रु and रू",
     "body": "With र the u signs sit beside the letter, not below it: रु ru (गुरु guru), रू rū (रूप rūp). "
             "Compare कु ku and कू kū."},
    {"st": "deva", "set": 3, "h": "र in clusters",
     "body": "र before a consonant becomes a small hook above the next letter (reph): कर्म karm, दर्द dard. "
             "र after a consonant becomes a slanted stroke at its foot (rakar): प्रेम prem, ग्राम grām; "
             "त + र is written त्र."},
    {"st": "deva", "set": 4, "h": "Nasal vowels",
     "body": "ँ (chandrabindu) and ं (bindu) make the vowel nasal: हाँ hā̃, में mẽ, नहीं nahī̃. Before a "
             "consonant ं is an n or m sound: हिंदी hindī, कंबल kambal. Many writers use ं for both."},
    {"st": "deva", "set": 5, "h": "Aspirated letters",
     "body": "ख घ थ ध फ भ छ झ are single sounds with a puff of air: kh is k + breath, not k + h. "
             "Hold a hand in front of your mouth to feel it."},
    {"st": "deva", "set": 6, "h": "Retroflex and dental",
     "body": "ट ठ ड ढ ण are said with the tongue curled back; त थ द ध न with the tongue on the teeth. "
             "English t and d sit between the two."},
    {"st": "deva", "set": 8, "h": "The nukta dot",
     "body": "A dot below changes the sound: ड़ ṛ and ढ़ ṛh are flapped r sounds (बड़ा, पढ़ना); ज़ z, फ़ f, "
             "क़ q, ख़ x, ग़ ġ are used in Persian, Arabic and English words. Many writers leave the dot out."},
    {"st": "deva", "set": 9, "h": "ङ and ञ",
     "body": "ङ and ञ appear in older and Sanskrit spellings before a consonant of their own group: अङ्ग, "
             "पञ्च. Modern spelling uses ं instead: अंग aṅg, पंच pañc."},
    {"st": "deva", "set": 10, "h": "Conjunct shapes",
     "body": "Most clusters are half letters, but a few have shapes of their own: क्ष kṣ, त्र tr, ज्ञ gy, "
             "श्र śr, द्य dy, द्व dv. Learn them as single letters."},
]
HI_UNIT_OF = {nfc(g): slug for _, _, slug, g, *_ in HI_SCRIPT}
HI_CONJ = sorted((nfc(g) for _, grp, _, g, *_ in HI_SCRIPT if grp == "conjunct"), key=lambda g: -len(g))
HI_CONS = {nfc(g) for _, grp, _, g, *_ in HI_SCRIPT if grp in ("velar", "palatal", "retroflex", "dental", "labial",
                                                              "semivowel", "sibilant", "nukta")}
HI_MATRA = {nfc(g) for _, grp, _, g, *_ in HI_SCRIPT if grp == "matra"}
HI_ROMAN = {slug: roman for _, _, slug, _, _, roman, *_ in HI_SCRIPT}


# ---- folded lookup tables built from the hand lists above ---------------------
MISSPELLED = {"मे": "में", "मै": "मैं", "मेँ": "में"}
def _f(xs):
    return {fold(x) for x in xs}


NAMES_F = _f(NAMES)
COPULA_F = _f(COPULA_FORMS)
NUMBERS_F = _f(NUMBERS)
PRON_FORMS.update({"मुझसे": "मैं", "तुझसे": "तू", "तुमसे": "तुम", "आपसे": "आप", "हमसे": "हम", "उससे": "वह",
                   "इससे": "यह", "उनसे": "वे", "इनसे": "ये", "किससे": "कौन", "जिससे": "जो",
                   "उसमें": "वह", "इसमें": "यह", "उनमें": "वे", "इनमें": "ये", "उसपर": "वह", "इसपर": "यह",
                   "ये": "ये", "वे": "वे", "वह": "वह", "यह": "यह", "कोई": "कोई", "किसीको": "कोई",
                   "जिसमें": "जो", "जिनमें": "जो", "किसमें": "कौन", "किनमें": "कौन", "जिनसे": "जो",
                   "किनसे": "कौन", "जिसपर": "जो", "किसपर": "कौन"})
PRON_SE = _f(k for k in PRON_FORMS if k.endswith("से"))
# possessive forms before a compound postposition's tail: मेरे लिए, उसकी तरफ़
# (and the relative/interrogative genitives: किसके लिए, जिसके बारे में)
_GEN_OBL = POSSESSIVES + ["किसका", "जिसका", "किनका", "जिनका"]
POSS_OBL = {"के": _f(p[:-1] + "े" for p in _GEN_OBL), "की": _f(p[:-1] + "ी" for p in _GEN_OBL)}
PHRASE_SEQ = {tuple(fold(x) for x in p.split()): fold(p) for p in PHRASES}
# a V2 after a bare verb stem is a vector (explicator) verb: the V1 carries the meaning
POSTPS_F = frozenset(_f(POSTPS))
_span_fold = fold      # module fold for passages.token_offsets (the class shadows `fold`)


class _FoldedZipf:
    """lexicon.zipf over the folded wordfreq table (picklable)."""
    def __init__(self, fz):
        self.fz = fz

    def __call__(self, w):
        return self.fz.get(w, 0.0)


class _BestByFreq(_FoldedZipf):
    """lexicon.best_by_freq over the folded wordfreq table (picklable)."""
    def __call__(self, cands):
        return sorted(cands, key=lambda c: (-self.fz.get(c, 0.0), c))[0]
# dictionary genders that contradict standard usage (and the genitive/adjective
# agreement the tagged corpus shows): the gloss mark and the link check use these
SPELLING_ENTRY = {"कॉलेज": "कालिज"}     # college: Wiktionary has only कालिज/कालेज
# spelling variants of one word: the variant's tokens link the main spelling,
# whose alts carry the variant's forms (canonical: the standard spelling)
SPELLING_VARIANTS = {("ख़याल", "NOUN"): "ख़्याल", ("अमेरिकी", "ADJ"): "अमरीकी",
                     ("अंतरराष्ट्रीय", "ADJ"): "अंतर्राष्ट्रीय", ("छिपना", "VERB"): "छुपना",
                     ("छिपाना", "VERB"): "छुपाना", ("वसंत", "NOUN"): "बसंत"}
REDUP_RE = re.compile(f"^([{DEV}]+)-(?:(?:से|न|ना|का|की|के|ही)-)?\\1$")
VARIANT_KEY = {(fold(v), g): (fold(w), g) for (w, g), v in SPELLING_VARIANTS.items()}
# कौन-सा "which": कौन + सा/सी/से (hyphen, space or glued) is one word
KAUNSA = "कौनसा"
KAUNSA_ALTS = ["कौन-सी", "कौन-से", "कौनसा", "कौनसी", "कौनसे", "कौन सा", "कौन सी", "कौन से"]
# surfaces of a perfective करना form that is also the genitive की: the verb
# only with an ergative ने subject or a following verb/auxiliary (की है, की गई)
PERF_KI = "की"
GENDER_FIX = {"चीज़": "f", "ख़याल": "m", "ख़्याल": "m", "गाल": "m", "हालात": "m", "घुटना": "m", "पैंट": "f"}
# feminine nouns that head की-compound postpositions (की वजह से, की ओर, की तरह):
# outside the compound they are nouns (आने की वजह क्या है); pure postpositions
# the tagger also reads as ADP (के तहत, हेतु, के बाद) never are
POSTP_NOUN_HEADS = frozenset(_f(["वजह", "ओर", "तरफ़", "तरह", "जगह", "दिशा"]))
VECTOR_V2 = _f(["जाना", "देना", "लेना", "डालना", "पड़ना", "बैठना", "उठना"])
ASPECT_AUX = frozenset(_f(["रहना", "सकना", "चुकना"]))
STEM_AUX = _f(["रहना", "सकना", "चुकना", "जाना", "देना", "लेना", "पाना", "डालना", "पड़ना", "बैठना", "उठना"])
VECTOR_V1_F = {fold(k): fold(v) for k, v in VECTOR_V1.items()}
# nukta-distinct lemma pairs the fold() nukta-drop merges (सज़ा/सजा): before
# these light verbs the merged surface is the nukta headword's noun sense, not
# the other lemma's verb stem (QA v1.1; audited: the only such pack collision)
NUKTA_NOUN_LV = {"सजा": frozenset(_f(["देना", "होना", "मिलना", "पाना", "सुनाना", "भुगतना"]))}
ADVERB_SURFACES = {"अब": "अब", "अभी": "अभी", "यहाँ": "यहाँ", "वहाँ": "वहाँ", "जहाँ": "जहाँ", "कहाँ": "कहाँ",
                   "यहां": "यहाँ", "वहां": "वहाँ", "जहां": "जहाँ", "कहां": "कहाँ", "तब": "तब", "जब": "जब",
                   "कब": "कब", "क्यों": "क्यों", "कैसे": "कैसे", "यहीं": "यहीं", "वहीं": "वहीं", "कभी": "कभी",
                   "कहीं": "कहीं", "इसलिए": "इसलिए", "इसलिये": "इसलिए"}

# display spelling of every hand-listed key (folded -> NFC as written above)
DISPLAY = {}
for _w in (DAYS + MONTHS + SEASONS + NUMBERS + COLOURS + PRONOUNS + POSSESSIVES + POSTPS +
           [w for w, _ in GREETINGS + QUESTION + CONJS + PARTICLES] + list(PHRASES) +
           [_l.split("|")[0] for _src in (POSTP_SRC, LIGHT_VERBS_SRC, VECTOR_SRC) for _l in _src.strip().splitlines()] +
           list(ADVERB_SURFACES.values()) + ["होना", "चाहिए", "जी"]):
    DISPLAY.setdefault(fold(_w), nfc(_w))
DISPLAY[KAUNSA] = "कौन-सा"

# ---- verb paradigm (folded forms; forms the Wiktionary tables lack) ------------
VOWEL_END = set("ािीुूृेैोौ") | set("अआइईउऊएऐओऔ")
IRREG_PERF = {"जाना": ("गया", "गई", "गए", "गईं"), "करना": ("किया", "की", "किए", "कीं"),
              "लेना": ("लिया", "ली", "लिए", "लीं"), "देना": ("दिया", "दी", "दिए", "दीं"),
              "होना": ("हुआ", "हुई", "हुए", "हुईं"), "पीना": ("पिया", "पी", "पिए", "पीं"),
              "जीना": ("जिया", "जी", "जिए", "जीं")}
IRREG_SUBJ = {"लेना": "ल", "देना": "द"}
IRREG_POLITE = {"करना": "कीजिए", "लेना": "लीजिए", "देना": "दीजिए", "पीना": "पीजिए"}


def verb_forms(inf):
    """Folded forms of a -ना infinitive: stem, infinitive/imperfective/perfective
    participles, subjunctive, future, imperatives, conjunctive -कर."""
    inf = nfc(inf)
    stem = inf[:-2]
    if not stem or not inf.endswith("ना"):
        return set()
    f = {stem, stem + "ने", stem + "नी", stem + "ता", stem + "ती", stem + "ते", stem + "तीं", stem + "कर"}
    v = stem[-1] in VOWEL_END
    if inf in IRREG_PERF:
        f |= set(IRREG_PERF[inf])
    elif v:
        f |= {stem + "या", stem + "ई", stem + "ए", stem + "ईं"}
    else:
        f |= {stem + "ा", stem + "ी", stem + "े", stem + "ीं"}
    if inf in IRREG_SUBJ:
        b = IRREG_SUBJ[inf]
        f |= {b + "ूं", stem + "ं", b + "ो", stem + "गा", stem + "गी", stem + "ंगे", stem + "ंगी", b + "ोगे",
              b + "ोगी", b + "ूंगा", b + "ूंगी"}
    elif inf == "होना":
        f |= {"हूं", "हो", "हों", "होगा", "होगी", "होंगे", "होंगी", "होगे", "होऊं", "होओ"}
    elif v:
        f |= {stem + x for x in ("ऊं", "ए", "एं", "ओ", "ऊंगा", "ऊंगी", "एगा", "एगी", "एंगे", "एंगी", "ओगे", "ओगी",
                                 "इए", "इएगा")}
    else:
        f |= {stem + x for x in ("ूं", "े", "ें", "ो", "ूंगा", "ूंगी", "ेगा", "ेगी", "ेंगे", "ेंगी", "ोगे", "ोगी",
                                 "िए", "िएगा")}
    if inf in IRREG_POLITE:
        f.add(IRREG_POLITE[inf])
    return {fold(x) for x in f}


# ---- romanisation fallback (words Wiktionary gives none) -------------------------
_TR_V = {"अ": "a", "आ": "ā", "इ": "i", "ई": "ī", "उ": "u", "ऊ": "ū", "ऋ": "ŕ", "ए": "e", "ऐ": "ai", "ओ": "o",
         "औ": "au", "ऑ": "ŏ"}
_TR_M = {"ा": "ā", "ि": "i", "ी": "ī", "ु": "u", "ू": "ū", "ृ": "ŕ", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
         "ॉ": "ŏ"}
_TR_C = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ṅ", "च": "c", "छ": "ch", "ज": "j", "झ": "jh", "ञ": "ñ",
         "ट": "ṭ", "ठ": "ṭh", "ड": "ḍ", "ढ": "ḍh", "ण": "ṇ", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
         "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "ś",
         "ष": "ṣ", "स": "s", "ह": "h"}
_TR_NUKTA = {"क": "q", "ख": "x", "ग": "ġ", "ज": "z", "ड": "ṛ", "ढ": "ṛh", "फ": "f"}


def translit(word):
    """Devanagari -> the Wiktionary-style roman (inherent a, final schwa dropped,
    anusvara n/m before a consonant and a tilde at the end)."""
    out = []
    s = nfc(word)
    i = 0
    while i < len(s):
        ch = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if ch in _TR_C:
            c = _TR_C[ch]
            if nxt == NUKTA:
                c = _TR_NUKTA.get(ch, c)
                i += 1
                nxt = s[i + 1] if i + 1 < len(s) else ""
            out.append(c)
            if nxt in _TR_M:
                out.append(_TR_M[nxt])
                i += 1
            elif nxt == VIRAMA:
                i += 1
            else:
                end = not nxt or not re.match(f"[{DEV}]", nxt)
                out.append("" if end and len(out) > 1 else "a")
        elif ch in _TR_V:
            out.append(_TR_V[ch])
        elif ch in (ANUSVARA, CANDRA):
            after = s[i + 1] if i + 1 < len(s) else ""
            if after in _TR_C:
                out.append("m" if after in "पफबभम" else "n")
            elif out:
                out[-1] = out[-1] + "̃"
        elif ch == "ः":
            out.append("h")
        elif ch == " ":
            out.append(" ")
        i += 1
    return nfc("".join(out))


# ---- sensitive content (Hindi half; English via the shared lists) ------------------
def _alt(terms):
    return "|".join(dev_rx(t) + f"[{DEV}]*" for t in terms)


_NB, _NA = f"(?<![{DEV}a-z])", f"(?![a-z])"
DROP_HI = ["बलात्कार", "रेप", "यौन शोषण", "यौन उत्पीड़न", "आत्महत्या", "ख़ुदकुशी", "छेड़छाड़", "बाल शोषण", "दुष्कर्म"]
RELIGION = ["हिंदू", "हिन्दू", "मुसलमान", "मुस्लिम", "इस्लाम", "ईसाई", "सिख", "पाकिस्तान", "काफ़िर", "यहूदी"]
POLEMIC = ["दुश्मन", "नफ़रत", "आतंक", "जिहाद", "दंगा", "दंगे", "गद्दार", "मार डाल", "मारो", "हत्या", "युद्ध", "जंग",
           "श्रेष्ठ", "धर्म परिवर्तन", "नष्ट"]
RELIGION_EN = r"hindus?|muslims?|moslems?|islam\w*|christians?|sikhs?|pakistan\w*|infidels?|kafirs?|jews?|jewish"
POLEMIC_EN = (r"enem\w*|hate\w*|hatred|terror\w*|jihad\w*|riot\w*|traitors?|kill\w*|war|wars|destroy\w*|"
              r"superior|inferior|better than|worse than|convert\w*|attack\w*")
# policy drops at every level (QA 2026-09-26): terrorism, party politics and
# religious supremacy claims (side-taking/communal), a named current office
# holder (time-sensitive), explicit sex and nudity (the pack's written
# sentences for such a word are exempt: example_rows)
POLICY_HI = ["आतंकवाद", "आतंकी", "कांग्रेस", "भारतीय जनता पार्टी", "भाजपा", "बीजेपी", "सेक्स", "नंगा", "नंगी"]
POLICY_RX = (_NB + "(?:" + "|".join(dev_rx(t) for t in POLICY_HI) + ")" +
             "|" + _NB + dev_rx("स्तन") + f"(?:ों)?(?![{DEV}])(?! कैंसर)" +
             "|" + _NB + "(?:भगवान|अल्लाह|ईश्वर|ख़ुदा|खुदा|परमेश्वर)[^।!?.]*सबसे (?:महान|बड़ा)" +
             "|" + _NB + "कपड़े उतार[^।!?]*बिस्तर" +
             r"|\bsex\b|\bbreasts?\b(?! cancer)|\bnaked\b|\bnude\b|\bterroris[tm]s?\b|\bcongress\b|"
             r"bharatiya janata|\bbjp\b|\b(?:god|allah) is (?:the )?greatest|"
             r"(?-i:(?:[Cc]hief [Mm]inister|[Pp]rime [Mm]inister|[Pp]resident|[Gg]overnor) of [A-Z][\w ]* is [A-Z])|"
             r"(?-i:[A-Z]\w+ [A-Z]\w+ is the (?:current )?(?:chief minister|prime minister|president|governor))")
SENSITIVE_HI = ["मार डाल", "मार दूंगा", "हत्या", "क़त्ल", "ख़ून", "बंदूक", "गोली", "चाकू", "लाश", "मौत", "मृत्यु", "मरना",
                "मर गया", "मर गई", "मर गए", "मर जा", "मरा हुआ", "सेक्स", "नंगा", "नंगी", "ड्रग्स", "नशा", "गांजा",
                "अफ़ीम", "हेरोइन", "कोकीन", "शराबी", "हथियार", "बम", "आत्महत्या"]


class Hindi(LanguageSpec):
    code = "hi"
    name_en = "Hindi"
    pack_name = "Hindi (A1–B1)"
    tts = "hi-IN"
    stt = "hi-IN"
    tatoeba_code = "hin"
    spacy_model = None
    tagger = "stanza"
    stanza_lang = "hi"
    tagger_attribution = {
        "source": "Stanza (Apache-2.0) with its Hindi default model, trained on UD Hindi-HDTB",
        "licence": "Apache-2.0 (code); CC BY-NC-SA 4.0 (UD Hindi-HDTB model data)",
        "note": "Used at build time only; the pack ships no model files or treebank text.",
    }
    untranslated_rows = True

    subtitles_file = "hi_full.txt"
    kaikki_file = "kaikki_hi.jsonl.gz"
    sentences_file = "hin_sentences_detailed.tsv.bz2"
    links_file = "hin-eng_links.tsv.bz2"
    sources = {
        "hi_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/hi/hi_full.txt",
        "kaikki_hi.jsonl.gz": "https://kaikki.org/dictionary/Hindi/kaikki.org-dictionary-Hindi.jsonl.gz",
        "hin_sentences_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/hin/hin_sentences_detailed.tsv.bz2",
        "hin-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/hin/hin-eng_links.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t3", "lex": "l1"}

    typing = None
    show_pron = True
    target_len = {"A1": 5, "A2": 6, "B1": 7}
    min_len = {"A1": 3, "A2": 4, "B1": 5}
    max_len = 14

    word_re = re.compile(f"[{DEV}]+")
    lex_word_re = re.compile(f"^[{DEV}]+(?: [{DEV}]+){{0,3}}$")
    sub_token_re = re.compile(f"^[\u0904-\u0939\u0958-\u0961\u0972-\u097f][{DEV}]*$")   # starts with a letter
    form_target_re = re.compile(f"\\bof ([{DEV}]+)")
    fem_of_re = re.compile(r"(?!)")
    noun_head_template = "hi-noun"
    group_kpos = dict(DEFAULT_GROUP_KPOS, **{
        "ADP": ["postp", "prep", "adv"],
        "PART": ["particle", "adv", "intj"],
        "CONJ": ["conj", "adv", "particle"],
        "ADV": ["adv", "adj", "particle", "conj", "postp"],
        "DET": ["det", "pron", "adj", "num", "article"],
        "PRON": ["pron", "det"],
        "NUM": ["num", "adj", "noun", "det"],
        "INTJ": ["intj", "particle", "noun"],
        "ADJ": ["adj", "det", "num", "adv"],
    })
    numeral_verb_rule = False
    morph_keep = ("Gender", "Number", "Person", "Tense", "Aspect", "Mood", "VerbForm", "Case")
    caps_mark_names = False
    caps_proper_pool = False
    function_verbs = {"होना"}
    min_corpus_tokens = 1     # the Hindi corpus is small (116k tokens): one attested use is evidence
    sentence_end_re = re.compile("[.!?…।॥][\"'»”)]*$")

    forced_closed = ([(fold(w), "NOUN") for w in DAYS + MONTHS + SEASONS] + [(fold(w), "NUM") for w in NUMBERS] +
                     [(fold(w), "ADJ") for w in COLOURS] + [(fold(w), g) for w, g in GREETINGS] +
                     [(fold(w), "PRON") for w in PRONOUNS + POSSESSIVES] + [(fold(w), g) for w, g in QUESTION] +
                     [(fold(w), "ADP") for w in POSTPS] + [(fold(w), g) for w, g in CONJS + PARTICLES] +
                     [(p, "PHRASE") for p in PHRASE_SEQ.values()] + [("होना", "VERB")] +
                     [(p, "ADP") for p in (fold(x) for x in ("के लिए", "के बाद", "के साथ", "के बारे में",
                                                               "की तरफ़", "के पास"))] +
                     [(c, "VERB") for c in (fold(x) for x in ("काम करना", "बात करना", "मदद करना", "प्यार करना",
                                                              "शुरू करना", "पसंद होना", "पता होना"))] +
                     [(KAUNSA, "DET")])
    allowed_num = NUMBERS_F | _f(["करोड़", "लाख", "पहला", "दूसरा", "तीसरा", "आधा", "डेढ़", "दोनों"])
    fixed_gloss = {
        **{(c, "VERB"): g for c, g in LIGHT_VERBS.items()},
        **{(c, "VERB"): g for c, g in VECTORS.items()},
        **{(p, "ADP"): g for p, g in POSTP.items()},
        **{(fold(p), "PHRASE"): g for p, g in PHRASES.items()},
        ("मैं", "PRON"): "I", ("तू", "PRON"): "you (intimate)", ("तुम", "PRON"): "you (familiar)",
        ("आप", "PRON"): "you (polite)", ("वह", "PRON"): "he, she, it; that", ("यह", "PRON"): "he, she, it; this",
        ("हम", "PRON"): "we", ("वे", "PRON"): "they; he, she (polite)", ("ये", "PRON"): "these, they; he, she (polite)",
        ("कोई", "PRON"): "someone, anyone; some", ("कुछ", "PRON"): "something; some, a few",
        ("सब", "PRON"): "all, everyone, everything", ("जो", "PRON"): "who, which, what (relative)",
        ("खुद", "PRON"): "oneself, myself, yourself...",
        ("मेरा", "PRON"): "my, mine", ("तेरा", "PRON"): "your, yours (intimate)",
        ("तुम्हारा", "PRON"): "your, yours (familiar)", ("आपका", "PRON"): "your, yours (polite)",
        ("उसका", "PRON"): "his, her, its; that one's", ("इसका", "PRON"): "his, her, its; this one's",
        ("उनका", "PRON"): "their; his, her (polite)", ("इनका", "PRON"): "their; his, her (polite)",
        ("हमारा", "PRON"): "our, ours", ("अपना", "PRON"): "one's own (my own, your own...)",
        ("किसका", "PRON"): "whose", (KAUNSA, "DET"): "which (कौन-सा/कौन-सी/कौन-से)",
        ("का", "ADP"): "of, 's (का/की/के)", ("को", "ADP"): "to; (object marker)", ("से", "ADP"): "from; with, by; than",
        ("में", "ADP"): "in, into", ("पर", "ADP"): "on, at", ("तक", "ADP"): "until, up to, as far as",
        ("ने", "ADP"): "(marks the subject of a past transitive verb)",
        ("क्या", "PRON"): "what", ("क्या", "PART"): "(yes/no question marker)", ("कौन", "PRON"): "who",
        ("कहां", "ADV"): "where", ("कब", "ADV"): "when", ("क्यों", "ADV"): "why", ("कैसे", "ADV"): "how",
        ("कैसा", "DET"): "what kind of; how", ("कितना", "DET"): "how much, how many",
        ("और", "CONJ"): "and; more", ("या", "CONJ"): "or", ("लेकिन", "CONJ"): "but", ("कि", "CONJ"): "that",
        ("क्योंकि", "CONJ"): "because", ("अगर", "CONJ"): "if", ("जब", "ADV"): "when (relative)",
        ("तब", "ADV"): "then, at that time", ("तो", "CONJ"): "then, so", ("इसलिए", "ADV"): "so, therefore",
        ("ही", "PART"): "only, just; (emphasis)", ("भी", "PART"): "also, too, even", ("नहीं", "PART"): "not, no",
        ("न", "PART"): "not; (tag) isn't it?", ("मत", "PART"): "don't (with commands)",
        ("होना", "VERB"): "to be; to happen, to become",
        ("नमस्ते", "INTJ"): "hello; goodbye (greeting)", ("नमस्कार", "INTJ"): "hello (formal greeting)",
        ("धन्यवाद", "INTJ"): "thank you", ("शुक्रिया", "INTJ"): "thanks, thank you",
        ("हां", "INTJ"): "yes", ("जी", "PART"): "(polite particle: जी हाँ yes, sir/madam)",
        ("अलविदा", "INTJ"): "goodbye", ("कृपया", "ADV"): "please",
        ("दोनों", "NUM"): "both", ("चंद", "DET"): "a few, some", ("रोज", "ADV"): "every day, daily",
        ("सदा", "ADV"): "always, forever", ("सबसे", "ADV"): "most (सबसे अच्छा: the best); of all",
        ("वाला", "PART"): "the one (who/which); -er (बेचने वाला: seller); about to (जाने वाला: about to go)",
        ("सा", "PART"): "-ish, rather; like (सा/सी/से after a word)", ("तो", "PART"): "(emphasis) as for, well",
        ("चाहिए", "VERB"): "should, ought to; (मुझे ... चाहिए) I need, I want",
    }
    closed_surfaces = {**{fold(k): (fold(v), "PRON") for k, v in PRON_FORMS.items()},
                       **{fold(k): (fold(v), "PRON") for k, v in POSS_FORMS.items()},
                       **{fold(k): (fold(v), "ADV") for k, v in ADVERB_SURFACES.items()},
                       fold("चाहिए"): (fold("चाहिए"), "VERB"), fold("चाहिये"): (fold("चाहिए"), "VERB"),
                       fold("हाँ"): (fold("हाँ"), "INTJ"), fold("कृपया"): (fold("कृपया"), "ADV"),
                       fold("नमस्ते"): (fold("नमस्ते"), "INTJ"), fold("धन्यवाद"): (fold("धन्यवाद"), "INTJ"),
                       fold("शुक्रिया"): (fold("शुक्रिया"), "INTJ"), fold("और"): (fold("और"), "CONJ"),
                       fold("लेकिन"): (fold("लेकिन"), "CONJ"), fold("क्योंकि"): (fold("क्योंकि"), "CONJ"),
                       fold("अगर"): (fold("अगर"), "CONJ"), "सा": ("सा", "PART"), "सी": ("सा", "PART"),
                       "दोनों": ("दोनों", "NUM"), "दोनो": ("दोनों", "NUM"),
                       "सबसे": ("सबसे", "ADV"), "वाला": ("वाला", "PART"), "वाली": ("वाला", "PART"),
                       "वाले": ("वाला", "PART")}
    function_lemmas = (_f(PRONOUNS + POSSESSIVES + POSTPS) | _f(w for w, _ in QUESTION + CONJS + PARTICLES) |
                       set(POSTP) | {"होना"} | _f(["बिना", "चाहे", "काश"]))
    drop_keys = {("वापस", "ADJ"): ("वापस", "ADV"), ("ऐसा", "PRON"): ("ऐसा", "DET"), ("वैसा", "PRON"): ("वैसा", "DET"),
                 ("जैसा", "PRON"): ("जैसा", "DET"), ("कैसा", "PRON"): ("कैसा", "DET"),
                 ("ओ", "PRON"): None, ("चंद", "NOUN"): ("चंद", "DET"), ("चंद", "ADJ"): ("चंद", "DET"),
                 ("रोज", "NOUN"): ("रोज", "ADV"), ("सदा", "NOUN"): ("सदा", "ADV"),
                 # interjections the tagger reads as nouns (हाय!, आह!)
                 ("हाय", "NOUN"): ("हाय", "INTJ"), ("आह", "NOUN"): ("आह", "INTJ"),
                 # entries reached only through a misread form (सर "head" → सरना, बंधा "bound")
                 ("सरना", "VERB"): None, ("बंधा", "NOUN"): None, ("विचारना", "VERB"): None,
                 # light-verb nominals whose only adjective sense is the light verb's
                 # (ख़त्म = ख़त्म होना/करना): the compound is the entry
                 **{(fold(w), "ADJ"): None for w in ("ख़त्म", "पैदा", "प्राप्त", "महसूस")},
                 # words of the drop-at-every-level class: no sentence may ever show them
                 **{(fold(w), g): None for w in ("बलात्कार", "आत्महत्या", "ख़ुदकुशी", "दुष्कर्म")
                    for g in ("NOUN", "VERB", "ADJ")},
                 # spelling variants: tokens link the main spelling (SPELLING_VARIANTS)
                 **{(fold(v), g): (fold(w), g) for (w, g), v in SPELLING_VARIANTS.items()},
                 # second-entry rule admitted these as a distinct sense by English-gloss
                 # overlap, but the two POS are one Hindi sense split across a learner's
                 # dictionary categories; merge into the more frequent POS's entry, whose
                 # gloss gains the dropped sense (QA v1.1; चीनी sugar/Chinese stays a pair)
                 ("वही", "DET"): ("वही", "PRON"), ("ठीक", "ADJ"): ("ठीक", "ADV"),
                 (fold("बाक़ी"), "NOUN"): (fold("बाक़ी"), "ADJ"),
                 ("मूर्ख", "NOUN"): ("मूर्ख", "ADJ"), ("विरोधी", "NOUN"): ("विरोधी", "ADJ")}
    profanity = _f(PROFANE)
    # profanity, and Tatoeba sentences dropped by text: ungrammatical, or a
    # contested language-politics claim (Hindi/Urdu), against the neutrality rule
    bad_text_re = re.compile(_NB + "(?:" + "|".join(dev_rx(p) for p in PROFANE) + f")(?![{DEV}])"
                             "|वापस आना और मुझे बाद में ले लो|हिंदी और उर्दू एक ही भाषा"
                             # QA 2026-09-26: Latin letters in the Hindi text; ungrammatical
                             # or mistranslated rows; English that misrenders the Hindi
                             "|[A-Za-z]|टॉम के इसकी|टॉम के भीतर औरतों|इस कविता क्या आप|क्या है उनके अधिकार"
                             "|बाल किसने काटें|" + dev_rx("बर्दाश्त की भी हद") + "|रविबार"
                             "|यात्रा करना पसंद करते हो\\?\" \"मैं भी"
                             # QA v1.1: चीज़ "thing" false-friend-glossed as "cheese" (पनीर
                             # is the real word); every corpus row with this gloss, pack or not
                             "|चीज़ दूध से बनता है|मैं चीज़ खाता हूँ|मैं चीज़ खाती हूँ"
                             "|टॉम को चीज़ पसंद है|मैंने बहुत सारा चीज़ दिया")

    def clean_sentence_text(self, t):
        """Tatoeba hygiene: a sentence-final full stop is the danda; no ZWJ/ZWSP."""
        t = re.sub("[\u200d\u200b\ufeff]", "", t)
        return re.sub(r"(?<=[" + DEV + r"])\s*\.(?=[\"'”’)]*\s*$)", "।", t)
    drop_all_levels = drop_all_re(re.compile(
        _NB + "(?:" + _alt(DROP_HI) + ")" +
        "|^(?=[\\s\\S]*" + _NB + "(?:" + _alt(RELIGION) + "|" + RELIGION_EN + ")" + _NA + ")" +
        "(?=[\\s\\S]*" + _NB + "(?:" + _alt(POLEMIC) + "|" + POLEMIC_EN + ")" + _NA + ")" + "|" + POLICY_RX, re.I))
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)
    sensitive_re = re.compile(_NB + "(?:" + _alt(SENSITIVE_HI) + "|" + SENSITIVE_EN +
                              r"|die[ds]?|dying|death|weapons?|guns?|knife|knives|bomb\w*|drugs?|drunk\w*|blood)" +
                              _NA, re.I)

    report_title = "Hindi A1-B1 pack (corpus-tagged)"
    forced_description = ("days, months, seasons, numbers 0-20 + tens + सौ/हज़ार, colours, greetings, pronouns "
                          "(with honorific आप) and possessives, question words, postpositions (with के लिए, के बाद, "
                          "के साथ, के बारे में, की तरफ़, के पास), conjunctions, particles, होना, core light verbs, A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000/lakh/crore/ordinals 1-3"

    def load(self):
        """forced_a1.txt and gloss_overrides.json are written in the dictionary
        spelling (नुक़्ता, चन्द्रबिन्दु): folded here to the builder's keys."""
        super().load()
        self.a1_core = {g: list(dict.fromkeys(fold(w) for w in ws)) for g, ws in self.a1_core.items()}
        self.forced = list(dict.fromkeys(list(self.forced_closed) +
                                         [(w, g) for g, ws in self.a1_core.items() for w in ws]))
        self.gloss_overrides = {fold(k.rsplit("|", 1)[0]) + "|" + k.rsplit("|", 1)[1]: v
                                for k, v in self.gloss_overrides.items()}
        # an override also replaces a hand-written fixed gloss (compounds, pronouns)
        group = {"noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV", "det": "DET", "prep": "ADP",
                 "pron": "PRON", "conj": "CONJ", "num": "NUM", "intj": "INTJ", "part": "PART", "phrase": "PHRASE"}
        self.fixed_gloss = dict(self.fixed_gloss)
        for k, v in self.gloss_overrides.items():
            lem, lab = k.rsplit("|", 1)
            if (lem, group.get(lab)) in self.fixed_gloss:
                self.fixed_gloss[(lem, group[lab])] = v
        return self

    # ---- spelling --------------------------------------------------------------
    def fold(self, s):
        return fold(s)

    def is_verb_lemma(self, w):
        return w.endswith("ना") or w == "चाहिए"

    def is_profane(self, w):
        return w in self.profanity

    def noun_display(self, lemma, gender, plural, en):
        tag = {"m": "m", "f": "f", "mf": "m/f"}.get(gender)
        return lemma, (f"{en} ({tag})" if tag and not en.endswith(f"({tag})") else en)

    def default_gender(self, lemma):
        return None

    # ---- tagging (Stanza) -------------------------------------------------------------
    def tagger_desc(self):
        import stanza
        return f"Stanza {stanza.__version__}, hi default package (UD Hindi-HDTB)"

    def tag_text(self, text):
        """Stanza keeps punctuation glued to a word at times (रह।, बुद्धू!): space it out."""
        t = nfc(text)
        t = re.sub(r"\s*([।॥?!,;:\"“”()])\s*", r" \1 ", t)
        t = re.sub(f"(?<=[{DEV}])\\.(?=\\s|$)", " . ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _stanza_dir(self):
        return str(self.repo / ".cache" / "stanza")

    def tag_texts(self, texts):
        """Stanza tokenize+pos+lemma (Hindi has no multi-word-token expansion), one
        sentence per text; raw output cached per text so rule changes never re-run it."""
        import stanza
        from ..core.util import derived_write_ok
        cache = self.repo / ".cache" / "derived" / f"stanza_raw_hi_{stanza.__version__}.jsonl.gz"
        raw = {}
        if cache.exists():
            with gzip.open(cache, "rt", encoding="utf-8") as f:
                for line in f:
                    t, toks = json.loads(line)
                    raw[t] = toks
        todo = sorted({t for t in texts if t not in raw})
        if todo:
            stanza.download(self.stanza_lang, model_dir=self._stanza_dir(), processors="tokenize,pos,lemma",
                            logging_level="WARN")
            nlp = stanza.Pipeline(self.stanza_lang, dir=self._stanza_dir(), processors="tokenize,pos,lemma",
                                  tokenize_no_ssplit=True, logging_level="WARN", download_method=None,
                                  use_gpu=False)
            for i in range(0, len(todo), 500):
                chunk = todo[i:i + 500]
                docs = nlp.bulk_process([stanza.Document([], text=t) for t in chunk])
                for t, d in zip(chunk, docs):
                    toks = []
                    for s in d.sentences:
                        for w in s.words:
                            feats = dict(kv.split("=", 1) for kv in (w.feats or "").split("|") if "=" in kv)
                            toks.append([w.text, w.lemma or w.text, w.upos, feats])
                    raw[t] = toks
            if derived_write_ok(self):
                cache.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache.with_suffix(".part")
                with gzip.GzipFile(tmp, "wb", mtime=0) as g:
                    for t in sorted(raw):
                        g.write((json.dumps([t, raw[t]], ensure_ascii=False) + "\n").encode("utf-8"))
                tmp.replace(cache)
        for t in texts:
            yield [tuple(x) for x in raw[t]]

    # ---- kaikki side info ---------------------------------------------------------------
    def _info(self):
        """{folded headword: [[headword, pos, romanisation, is_lemma, gloss, gender, [folded table forms]]]}."""
        if hasattr(self, "_info_cache"):
            return self._info_cache
        from ..core.util import Env, file_sig
        env = Env(self)
        src = env.cache / self.kaikki_file
        sig = hashlib.sha1(f"hiinfo2|{file_sig(src)}".encode()).hexdigest()[:10]
        out = env.derived / f"hi_info_{sig}.json.gz"
        if out.exists():
            with gzip.open(out, "rt", encoding="utf-8") as f:
                self._info_cache = json.load(f)
            return self._info_cache
        info = {}
        skip = {"romanization", "Urdu", "table-tags", "inflection-template", "class"}
        with gzip.open(src, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("lang_code") != "hi":
                    continue
                word = nfc(d.get("word", ""))
                rom, forms = None, set()
                for fm in d.get("forms", []):
                    tags = set(fm.get("tags") or [])
                    form = nfc(fm.get("form") or "")
                    if "romanization" in tags and form and rom is None:
                        rom = form
                    elif form and not tags & skip and re.fullmatch(f"[{DEV}]+", form) and \
                            self._table_form(d.get("pos", ""), tags):
                        forms.add(fold(form))
                senses = d.get("senses", [])
                is_lemma = any(not (s.get("form_of") or s.get("alt_of") or
                                    set(s.get("tags", [])) & {"form-of", "alt-of", "misspelling"})
                               for s in senses)
                gloss = "; ".join((s.get("glosses") or [""])[-1] for s in senses[:4])
                info.setdefault(fold(word), []).append(
                    [word, d.get("pos", ""), normalize_pron(rom) if rom else None, is_lemma, gloss,
                     self.gender_from_entry(d), sorted(forms - {fold(word)})])
        env.derived.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(out, "wb", mtime=0) as g:
            g.write(json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        self._info_cache = info
        return info

    CASE_TAGS = {"direct", "oblique", "vocative", "singular", "plural"}

    def _table_form(self, pos, tags):
        """A declension/conjugation cell: nouns by case and number only (a
        "feminine"/"masculine" form is the counterpart noun: बेटा/बेटी, भाई/बहन),
        adjectives also by gender, verbs any conjugation cell; no comparative,
        superlative or diminutive forms."""
        if tags & {"comparative", "superlative", "diminutive", "augmentative", "alternative", "abbreviation"}:
            return False
        if pos == "noun":
            return bool(tags) and tags <= self.CASE_TAGS
        if pos in ("adj", "det", "num"):
            return bool(tags) and tags <= self.CASE_TAGS | {"masculine", "feminine"}
        return pos == "verb"

    def _verbs(self):
        """(folded infinitives, folded verb form -> sorted infinitives)."""
        if hasattr(self, "_verb_cache"):
            return self._verb_cache
        infs, forms = set(), {}
        for key, rows in sorted(self._info().items()):
            for word, pos, rom, is_lemma, gloss, g, tab in rows:
                if pos == "verb" and is_lemma and key.endswith("ना") and " " not in key:
                    infs.add(key)
                    for x in sorted(verb_forms(word) | set(tab)):
                        forms.setdefault(x, set()).add(key)
        self._verb_cache = (infs, {k: sorted(v) for k, v in forms.items()})
        return self._verb_cache

    def _has(self, w, poses):
        return any(r[1] in poses and r[3] for r in self._info().get(w, []))

    def _verb_lemma(self, ft, fl):
        infs, forms = self._verbs()
        if fl in infs:
            return fl
        c = forms.get(ft)
        if c:
            return next((x for x in c if x.startswith(fl[:2])), c[0])
        if fl + "ना" in infs:
            return fl + "ना"
        return fl

    def fix_token(self, tok):
        text, lemma, upos, ms = tok
        core = nfc(text).strip(TOKEN_PUNCT + " ")
        if upos == "PUNCT" or not re.search(f"[{DEV}]", core):
            ft = fold(core) or nfc(text)
            return [ft, ft, "PUNCT" if not re.search(f"[{DEV}A-Za-z0-9]", ft) else upos, ms]
        ft = fold(core)
        fl = fold(nfc(lemma).strip(TOKEN_PUNCT + " ")) or ft
        if upos == "ADP" and ft not in ("का", "की", "के") and "Gender=" in ms:
            # only the genitive agrees with the next noun; पास/लिए carry no gender
            ms = "|".join(f for f in ms.split("|") if not f.startswith("Gender="))
        if ft in MISSPELLED:
            ft = fl = MISSPELLED[ft]        # मे -> में, मै -> मैं (anusvara dropped)
            upos = {"में": "ADP", "मैं": "PRON"}.get(ft, upos)
        if upos in ("NOUN", "PRON", "PROPN", "ADJ") and self._has(ft, ("intj",)) and \
                not self._has(ft, ("noun", "pron", "adj")):
            return [ft, ft, "INTJ", ms]     # हाय, आह: interjections the tagger reads as nouns
        if ft in NAMES_F:
            return [ft, ft, "PROPN", ms]
        if ft in COPULA_F and upos in ("AUX", "VERB"):
            return [ft, "होना", "AUX", ms]
        if upos in ("VERB", "AUX"):
            fl = self._verb_lemma(ft, fl)
        elif upos == "PROPN" and self._has(ft, ("noun", "adj", "adv")) and not self._has(ft, ("name",)):
            upos, fl = "NOUN", ft          # सूरज, आज: common words HDTB tags PROPN
        if ft in NUMBERS_F and upos in ("NOUN", "ADJ", "DET", "PROPN", "PRON"):
            upos, fl = "NUM", ft
        return [ft, fl, upos, ms]

    def fix_sentence(self, toks, row, doc):
        """क्या without "what" in the English is the yes/no question particle."""
        en = row[3] if row else ""
        for t in toks:
            if t[0] == "क्या" and en and not re.search(r"\bwhat", en, re.I):
                t[1], t[2] = "क्या", "PART"
        return toks

    # ---- resolution ------------------------------------------------------------------------
    def post_resolve(self, toks, out):
        """Context rules: fixed phrases, compound postpositions, light verbs,
        vector compounds; vector/passive V2 and conjunctive कर link nothing."""
        # a spelling variant is its main spelling (छुपना -> छिपना, बसंत -> वसंत)
        out = [VARIANT_KEY.get(r, r) if r else r for r in out]
        n = len(toks)
        txt = [t[0] for t in toks]
        edge = lambda j: j < 0 or j >= n or toks[j][2] == "PUNCT"
        done = set()
        # a function-word tag never falls back to a content reading of its form
        # (सी PART is सा "-ish", not सीना "to sew"; the tagger's word, or nothing)
        vforms = self._verbs()[1]
        for i, (t, r) in enumerate(zip(toks, out)):
            if r and t[2] in ("PRON", "DET") and r[1] in ("NOUN", "ADJ") and t[0] not in self.closed_surfaces:
                # चलो "let's" tagged PRON: a verb form is the verb; else a real pronoun or nothing
                # an adjective the tagger calls a pronoun (एक-दूसरे, सारे) keeps its reading
                v = vforms.get(t[0])
                out[i] = (v[0], "VERB") if v else ((t[0], t[2]) if self._has(t[0], ("pron", "det")) else
                                                   (r if r[1] == "ADJ" else None))
                continue
            if r and t[2] in ("PART", "ADP", "CCONJ", "SCONJ") and r[1] in ("NOUN", "VERB", "ADJ"):
                g = {"CCONJ": "CONJ", "SCONJ": "CONJ"}.get(t[2], t[2])
                lx = getattr(self, "_lx", None)
                w = t[0] if lx is None or lx.E.get(t[0]) else t[1]
                out[i] = (w, g) if lx is None or lx.E.get(w) else None
        # a reduplicated hyphen token (कम-से-कम, धीरे-धीरे, बार-बार) is its word
        lxr = getattr(self, "_lx", None)
        for i, t in enumerate(toks):
            m = REDUP_RE.match(t[0])
            if m and lxr is not None:
                w = m.group(1)
                g = next((g for g, k in (("ADV", "adv"), ("ADJ", "adj"), ("NOUN", "noun")) if lxr.usable_entries(w, [k])), None)
                if g:
                    out[i] = (w, g)
                    done.add(i)
        # a bare causative stem outside a verb frame is the intransitive's
        # perfective (बुरा लगा: लगना, not लगाना "to apply"; बना: बनना)
        # and inside a verb frame (हिला रही, बना दो) the causative's stem
        for i, (t, r) in enumerate(zip(toks, out)):
            if not r or r[1] != "VERB" or not txt[i].endswith("ा") or t[2] not in ("VERB", "AUX"):
                continue
            caus, intr = txt[i] + "ना", txt[i][:-1] + "ना"
            if r[0] not in (caus, intr) or not {caus, intr} <= set(vforms.get(txt[i], ())):
                continue
            nx = txt[i + 1] if i + 1 < n else ""
            nr = out[i + 1] if i + 1 < n else None
            framed = nx in ("कर", "के") or (nr and nr[1] == "VERB" and (nr[0] in STEM_AUX or nr[0] in VECTOR_V2))
            out[i] = (caus if framed else intr, "VERB")
        # reflexive अपने आप "oneself, by itself": आप is no "you"
        for i in range(1, n):
            if txt[i] == "आप" and txt[i - 1] in ("अपने", "अपनी"):
                out[i] = None
        # vocative हे before a name or noun (हे भगवान), never a copula
        for i in range(n):
            if txt[i] == "हे" and edge(i - 1) and i + 1 < n and toks[i + 1][2] in ("NOUN", "PROPN"):
                out[i] = ("हे", "PART")
        # fixed phrases, bounded by the clause edge
        for seq, phrase in PHRASE_SEQ.items():
            k = len(seq)
            for i in range(n - k + 1):
                if tuple(txt[i:i + k]) == seq and edge(i - 1) and (edge(i + k) or phrase != fold("ठीक है")):
                    for j in range(i, i + k):
                        out[j] = (phrase, "PHRASE")
                        done.add(j)
        # कौन-सा "which": glued (कौनसी), hyphenated or spaced (कौन सी, कौन - सी)
        for i in range(n):
            if i in done:
                continue
            if txt[i].replace("-", "") in ("कौनसा", "कौनसी", "कौनसे"):
                out[i] = (KAUNSA, "DET")
                done.add(i)
            elif txt[i] == "कौन":
                j = i + 2 if i + 2 < n and txt[i + 1] == "-" else i + 1
                if j < n and txt[j] in ("सा", "सी", "से") and j not in done:
                    for k in range(i, j + 1):
                        out[k] = (KAUNSA, "DET") if k in (i, j) else out[k]
                        done.add(k)
        # की as करना's perfective needs an ergative ने subject or a following
        # verb/auxiliary (मैंने मदद की, की गई, की है); else it is the genitive
        # (यह कहानी है प्यार और दोस्ती की)
        for i in range(n):
            if txt[i] != PERF_KI or not out[i] or out[i][0] != "करना" or i in done:
                continue
            erg = any(txt[k] == "ने" or (txt[k].endswith("ने") and toks[k][2] == "PRON") for k in range(i))
            nxt_v = i + 1 < n and toks[i + 1][2] in ("AUX", "VERB")
            if not erg and not nxt_v:
                out[i] = ("का", "ADP")
                done.add(i)
        # compound postpositions: के + tail, possessive + tail (मेरे लिए), pronoun+से + पहले
        for i in range(1, n):
            if i in done:
                continue
            for tail, heads in POSTP_TAIL.items():
                k = len(tail)
                if tuple(txt[i:i + k]) != tail:
                    continue
                prev = txt[i - 1]
                hit = None
                for h, phrase in heads:
                    if prev == h and i - 1 not in done:
                        hit = (phrase, True)
                    elif (h in POSS_OBL and prev in POSS_OBL[h]) or (h == "से" and prev in PRON_SE):
                        hit = hit or (phrase, False)
                if hit:
                    for j in range(i, i + k):
                        out[j] = (hit[0], "ADP")
                        done.add(j)
                    if hit[1]:
                        out[i - 1] = (hit[0], "ADP")
                        done.add(i - 1)
                    break
        # a noun the tagger reads as a postposition outside any compound
        # postposition (आने की वजह क्या है, उस ओर): the noun
        lx0 = getattr(self, "_lx", None)
        for i, (t, r) in enumerate(zip(toks, out)):
            if i in done or t[2] != "ADP" or txt[i] in self.closed_surfaces or lx0 is None \
                    or (i + 1 < n and txt[i + 1] in POSTPS_F):
                continue
            if txt[i] in POSTP_NOUN_HEADS and lx0.usable_entries(txt[i], ["noun"]):
                out[i] = (txt[i], "NOUN")
        # light verbs: noun/adjective + verb, particles/one adverb between
        for i, r in enumerate(out):
            if i in done or not r or r[1] != "VERB" or r[0] not in LV_INDEX:
                continue
            j, gaps = i - 1, 0
            while j >= 0 and txt[j] in LV_GAP_OK and gaps < 2:
                j, gaps = j - 1, gaps + 1
            if j < 0 or j in done or toks[j][2] in ("PUNCT", "PROPN", "VERB", "AUX"):
                continue
            nouns = LV_INDEX[r[0]]
            comp = nouns.get(out[j][0] if out[j] else "") or nouns.get(txt[j])
            if comp:
                out[i] = out[j] = (comp, "VERB")
                done.update((i, j))
        # vector compounds from the hand list (चला जाना, भूल जाना, ले आना)
        for i in range(1, n):
            r, pr = out[i], out[i - 1]
            if i in done or not r or r[1] != "VERB" or r[0] not in VEC_INDEX or not pr or pr[1] != "VERB":
                continue
            if i - 1 in done:
                continue
            v1 = VECTOR_V1_F.get(txt[i - 1]) or (pr[0] if txt[i - 1] == pr[0][:-2] else None)
            comp = VEC_INDEX[r[0]].get(v1) if v1 else None
            if comp:
                out[i] = out[i - 1] = (comp, "VERB")
                done.update((i, i - 1))
        # a verb stem read as a noun before its auxiliary/vector/conjunctive (तोड़ दिया,
        # हार गया, लड़ रहे, पकड़ कर): the verb; an adjective form read as a noun
        # before a noun or copula (नई गाड़ी: नया, not नई "river"): the adjective
        infs = self._verbs()[0]
        lx = getattr(self, "_lx", None)
        for i in range(n - 1):
            r, nr = out[i], out[i + 1]
            if i in done or not r or r[1] != "NOUN" or r[0] != txt[i]:
                continue
            # कर/के as a conjunctive (पकड़ कर), not the light verb करना (जाँच कर रही)
            # conjunctive के is no genitive: साल के लिए is the noun साल, not सालना
            conj = (txt[i + 1] == "कर" and not (i + 2 < n and toks[i + 2][2] in ("AUX", "VERB"))) or \
                (txt[i + 1] == "के" and toks[i + 1][2] != "ADP")
            # रहना/सकना/चुकना only as the tagger's auxiliary (लड़ रहे), not the main
            # verb "stay" (तीन साल रहा)
            aux_ok = nr and nr[1] == "VERB" and nr[0] in STEM_AUX and i + 1 not in done and \
                (nr[0] not in ASPECT_AUX or toks[i + 1][2] == "AUX")
            # a noun after a genitive or an attributive word is no verb stem
            # (रात की बस ली, सीधी बस जाती: the bus, not बसना)
            modified = i > 0 and (txt[i - 1] in ("का", "की", "के") or toks[i - 1][2] in ("ADJ", "DET", "NUM")) \
                and lx is not None and lx.usable_entries(txt[i], ["noun"])
            # सज़ा "punishment" folds (nukta dropped) to सजा, the stem of सजाना "to
            # decorate"; before a light verb of the punishment sense (सज़ा दी, सज़ा
            # हुई, सज़ा सुनाई) it is always the noun, genitive or not (QA v1.1)
            nukta_lv = r[0] in NUKTA_NOUN_LV and i + 1 < n and toks[i + 1][1] in NUKTA_NOUN_LV[r[0]]
            if (aux_ok or conj) and not modified and not nukta_lv \
                    and txt[i] + "ना" in infs and toks[i + 1][2] in ("VERB", "AUX", "ADP", "SCONJ", "PART", "CCONJ"):
                out[i] = (txt[i] + "ना", "VERB")
                done.add(i)
            elif lx is not None and (toks[i + 1][2] in ("NOUN", "PROPN") or (
                    txt[i + 1] in COPULA_F and not lx.usable_entries(txt[i], ["noun"]))):
                # before a copula only when the form is no noun itself (छुट्टी है)
                adj = sorted(t for t, p, k in lx.F.get(txt[i], []) if p == "adj" and t != txt[i])
                if adj and not lx.usable_entries(txt[i], ["adj"]):
                    out[i] = (adj[0], "ADJ")
        # भरती, an unhaltanted spelling of भर्ती "recruitment, admission", is also
        # भरना's feminine participle "filling"; before a light verb of the
        # recruitment sense (भरती होना/हुई, भरती करना/किया) it is the noun, not
        # the verb (QA v1.1, corpus 2017339/3620571 vs. भर्ती's own 494199/9013203)
        for i, r in enumerate(out):
            if i in done or not r or r[1] != "VERB" or r[0] != "भरना" or txt[i] != "भरती":
                continue
            if i + 1 < n and toks[i + 1][1] in ("होना", "करना", "कराना") and toks[i + 1][2] in ("VERB", "AUX"):
                out[i] = ("भर्ती", "NOUN")
                done.add(i)
        # V2 of an unlisted compound verb and passive जाना link their own verb
        # (लौट जाती: जाना, किया जा सकता: जाना, ख़रीद लें: लेना; QA 2026-09-26);
        # conjunctive कर/के after a stem links nothing
        for i in range(1, n):
            r, pr = out[i], out[i - 1]
            if not r or not pr or pr[1] != "VERB" or i in done:
                continue
            base = pr[0].split(" ")[-1]
            stem = txt[i - 1] == base[:-2] or (txt[i - 1] in VECTOR_V1_F)
            if txt[i] in ("कर", "के") and stem and toks[i - 1][2] in ("VERB", "AUX"):
                out[i] = None
        # an oblique plural in -ों is ambiguous between X and Xा (पौधों: पौध or
        # पौधा; बड़ों: बड़ "banyan" or बड़ा "elders"): the clearly more frequent
        # lemma, a nominalised adjective as that adjective
        for i, (t, r) in enumerate(zip(toks, out)):
            if i in done or not r or r[1] != "NOUN" or t[2] != "NOUN" or not txt[i].endswith("ों") \
                    or lx is None or r[0] != txt[i][:-2]:
                continue
            c2 = txt[i][:-2] + "ा"
            if lx.zipf(c2) < lx.zipf(r[0]) + 0.5:
                continue
            if lx.usable_entries(c2, ["noun"]):
                out[i] = (c2, "NOUN")
            elif lx.usable_entries(c2, ["adj"]):
                out[i] = (c2, "ADJ")
        # open-class tag guard: a noun-tagged bare verb stem outside a verb frame
        # (सर "head" is not सरना) keeps a noun reading or links nothing; a
        # verb-tagged form never links a noun (बंधा "bound" is not बंधा "levee")
        for i, (t, r) in enumerate(zip(toks, out)):
            if i in done or not r:
                continue
            if t[2] in ("NOUN", "PROPN") and r[1] == "VERB" and " " not in r[0] and txt[i] == r[0][:-2]:
                out[i] = (txt[i], "NOUN") if lx is not None and lx.usable_entries(txt[i], ["noun"]) else None
            elif t[2] in ("VERB", "AUX") and r[1] in ("NOUN", "ADJ") and txt[i] in vforms \
                    and not (lx is not None and lx.usable_entries(txt[i], ["adj"]) and r[1] == "ADJ"):
                out[i] = (vforms[txt[i]][0], "VERB")
        return out

    # passages: Devanagari matras are not \w, so the regex word count splits
    # words; the band rule counts the counted tokens instead (as ja). Spans
    # match surfaces after the same fold as the tagger input (nukta, chandrabindu).
    # everyday words the passages need (2026-09-26 lead request): these stay at
    # A2 at most, and these are kept in the list at their own rank
    level_ceiling = {**{(fold(w), "NOUN"): "A2" for w in ("मामा", "मिठाई", "केक", "सिनेमा", "रिश्तेदार", "दफ़्तर")},
                     (_span_fold("पैदल"), "ADJ"): "A2",
                     # core A1 words the forced additions would push to A2
                     **{(fold(w), g): "A1" for w, g in (("खाना बनाना", "VERB"), ("संगीत", "NOUN"),
                                                        ("धीरे", "ADV"), ("बाल", "NOUN"), ("लौटना", "VERB"),
                                                        ("हवा", "NOUN"), ("के नीचे", "ADP"))}}
    # (रेस्टोरेंट, संग्रहालय, पल, रंगीन, कुल are not candidates: no corpus tokens)
    keep_keys = frozenset((fold(w), g) for w, g in (
        ("बगीचा", "NOUN"), ("उगाना", "VERB"), ("पूरा करना", "VERB"), ("प्रदूषण", "NOUN"), ("तोहफ़ा", "NOUN")))

    passage_words_counted = True
    span_fold = staticmethod(_span_fold)
    passage_retag_names = True      # passage_retag gets the declared names (no capitals mark them)

    def passage_retag(self, toks, names=frozenset()):
        """Passages only. Devanagari has no capitals: a declared name is PROPN,
        and a PROPN that is no declared name but a dictionary noun/adjective is
        that word (a one-word option हरे). A hyphenated pair (माता-पिता,
        धीरे-धीरे, खाने-पीने, एक-दूसरे) splits into its words around a "-"."""
        out = []
        for t in toks:
            t = list(t)
            if t[0] in names:
                t[2] = "PROPN"
            elif t[2] == "PROPN":
                lem = t[1] or t[0]
                if self._has(lem, ("noun",)) or self._has(lem, ("adj",)):
                    t[2] = "NOUN" if self._has(lem, ("noun",)) else "ADJ"
            parts = t[0].split("-")
            if len(parts) > 1 and all(re.search(f"[{DEV}]", x) for x in parts):
                for k, x in enumerate(parts):
                    if k:
                        out.append(["-", "-", "PUNCT", ""])
                    up = "NUM" if x in NUMBERS_F else t[2]
                    lem = self._verb_lemma(x, x) if up in ("VERB", "AUX") else x
                    lx = getattr(self, "_lx", None)
                    if up in ("PRON", "DET") and lx is not None and not self._has(x, ("pron", "det")):
                        # दूसरे of एक-दूसरे: an adjective form, not a pronoun
                        adj = sorted(k for k, pos, _kind in lx.F.get(x, []) if pos == "adj")
                        if adj or lx.usable_entries(x, ["adj"]):
                            up, lem = "ADJ", adj[0] if adj else x
                    out.append([x, lem, up, t[3]])
            else:
                out.append(t)
        return out

    def _passage_compounds(self):
        """Folded lemmas of the pack's multiword verbs (pack/words.json)."""
        pc = getattr(self, "_pack_compounds", None)
        if pc is None:
            import json
            from pathlib import Path
            ws = json.loads((Path(self.repo) / "pack" / "words.json").read_text())
            pc = self._pack_compounds = frozenset(fold(w["lemma"]) for w in ws if " " in w["lemma"])
        return pc

    def passage_post_resolve(self, toks, out):
        """Passages only: a light-verb or vector compound the pack lacks
        (नौकरी करना, बस जाना) splits into its parts: the noun/adjective as
        itself, the light verb as its verb, a vector V2 as nothing."""
        pc = self._passage_compounds()
        out = list(out)
        for i, (t, r) in enumerate(zip(toks, out)):
            if not r or r[1] != "VERB" or " " not in r[0] or r[0] in pc:
                continue
            parts = r[0].split(" ")
            idx = [j for j in range(len(toks)) if out[j] == r]
            vector = all(x.endswith("ना") for x in parts)
            for k, j in enumerate(idx):
                tj = toks[j]
                if vector:
                    out[j] = (parts[0], "VERB") if k == 0 else (parts[-1], "VERB")
                elif tj[2] in ("VERB", "AUX"):
                    out[j] = (parts[-1], "VERB")
                else:
                    out[j] = (parts[0], "ADJ" if tj[2] == "ADJ" else "NOUN")
        return out

    def passage_uncounted(self, toks, resolved):
        """Passages only: grammar tokens post_resolve links to nothing are not
        counted: auxiliaries (रहा, सकता, चुका, गया of बन गया), a vector/passive
        V2 after a verb (डाल दीजिए, ख़रीदा जा सकता), conjunctive कर/के, and
        लेकर of से ... लेकर ... तक "from ... to"."""
        gram = STEM_AUX | VECTOR_V2
        out = set()
        for i, t in enumerate(toks):
            if resolved[i] is not None and not (t[0] == "लेकर" and i and toks[i - 1][0] == "से"):
                continue
            prev_verb = i > 0 and (toks[i - 1][2] in ("VERB", "AUX") or
                                   (resolved[i - 1] is not None and resolved[i - 1][1] == "VERB"))
            if t[2] == "AUX" or (t[2] == "VERB" and t[1] in gram and prev_verb) or \
                    (t[0] in ("कर", "के") and prev_verb) or t[0] == "लेकर":
                out.add(i)
        return out

    # the tagger's POS split vs the pack's one entry: कल/आज tagged NOUN are the
    # adverbs, बहुत/ज़्यादा/कम tagged DET the adverb/adjective (QA 2026-09-26)
    CROSS_POS = {"ADJ": ("NOUN", "ADV"), "NOUN": ("ADJ", "ADV"), "PART": ("ADV",), "ADV": ("PART", "ADJ"),
                 "DET": ("ADV", "ADJ")}

    def cross_pos_link(self, lexicon, lem, group, key_to_id):
        """Same lemma, same sense across the tagger's POS split: यहूदी ADJ
        "Jewish" -> the noun entry, सिर्फ़ PART -> the adverb entry."""
        for g in self.CROSS_POS.get(group, ()):
            wid = key_to_id.get((lem, g))
            if wid:
                return wid
        # a noun homograph of a verb stem (दौड़ "race"): the verb (QA 2026-09-26)
        if group == "NOUN":
            return key_to_id.get((lem + "ना", "VERB"))
        return None

    def bind_lexicon(self, lexicon):
        """Declension/conjugation table forms and the regular verb paradigm become
        form pointers; letter/affix entries go."""
        self._lx = lexicon
        for w, g in GENDER_FIX.items():
            for e in lexicon.E.get(fold(w), []):
                if e.get("p") == "noun":
                    e["g"] = g
        self._patch_zipf(lexicon)
        infs, vforms = self._verbs()
        for key, rows in sorted(self._info().items()):
            for word, pos, rom, is_lemma, gloss, g, tab in rows:
                if not is_lemma or pos not in ("noun", "adj", "verb", "pron", "det", "num"):
                    continue
                forms = set(tab)
                if pos == "adj" and key.endswith("ा"):
                    forms |= {key[:-1] + "ी", key[:-1] + "े"}
                for fm in sorted(forms):
                    if fm == key or " " in fm:
                        continue
                    lst = lexicon.F.setdefault(fm, [])
                    if [key, pos, "form"] not in lst:
                        lst.append([key, pos, "form"])
        for fm, lemmas in sorted(vforms.items()):
            lst = lexicon.F.setdefault(fm, [])
            for key in lemmas:
                if fm != key and [key, "verb", "form"] not in lst:
                    lst.append([key, "verb", "form"])
        self._promote_common_spellings(lexicon)
        # everyday loan spellings Wiktionary lacks: the entry of the spelling it has
        import copy
        for w, src in SPELLING_ENTRY.items():
            if fold(w) not in lexicon.E and fold(src) in lexicon.E:
                lexicon.E[fold(w)] = copy.deepcopy(lexicon.E[fold(src)])
        for s in list(lexicon.E):
            ents = [e for e in lexicon.E[s] if e["p"] not in ("character", "suffix", "prefix", "symbol",
                                                              "romanization", "infix")]
            if ents:
                lexicon.E[s] = ents
            else:
                del lexicon.E[s]

    def _folded_zipf(self):
        """wordfreq's Hindi list summed over this spec's fold: wordfreq knows
        तोड़ना (3.7) but not the folded key तोडना (0.0)."""
        if not hasattr(self, "_fz"):
            import math
            from wordfreq import get_frequency_dict
            acc = {}
            for w, f in get_frequency_dict("hi", wordlist="best").items():
                k = fold(w)
                acc[k] = acc.get(k, 0.0) + f
            self._fz = {k: round(math.log10(f) + 9, 2) for k, f in acc.items() if f > 0}
        return self._fz

    def _patch_zipf(self, lexicon):
        """The lexicon's frequency lookups (rare-reading override, best_by_freq)
        read wordfreq by key; Hindi keys are folded (no nukta, anusvara for a class
        nasal), so they get the folded table instead (no shared hook for this)."""
        fz = self._folded_zipf()
        lexicon.zipf = _FoldedZipf(fz)            # module-level callables: the passages
        lexicon.best_by_freq = _BestByFreq(fz)    # link context pickles the lexicon

    def _promote_common_spellings(self, lexicon):
        """Wiktionary files the everyday spelling as an "alternative form" of a
        rarer one (कुर्सी -> कुरसी): when the alternative is clearly more used
        (wordfreq), it becomes the lemma and the rarer spelling points to it."""
        import copy
        info = self._info()
        fz = self._folded_zipf()
        zipf = lambda k: fz.get(k, 0.0)
        n = 0
        for s in sorted(lexicon.E):
            ents = lexicon.E[s]
            if any(sn[3] == "" for e in ents for sn in e["s"]):
                continue
            for tgt, pos, kind in list(lexicon.F.get(s, [])):
                if kind != "alt" or tgt == s or tgt not in lexicon.E or zipf(s) < zipf(tgt) + 0.3:
                    continue
                moved = [copy.deepcopy(e) for e in lexicon.E[tgt] if e["p"] == pos and
                         any(sn[3] == "" for sn in e["s"])]
                if not moved:
                    continue
                ents.extend(moved)
                lexicon.F[s] = [x for x in lexicon.F[s] if x != [tgt, pos, kind]]
                lexicon.F.setdefault(tgt, []).append([s, pos, "alt"])
                n += 1
        self._n_promoted = n

    def pack_json_extra(self):
        return {"spaced": True, "rtl": False, "langTag": "hi", "fontFamily": "\"Noto Sans Devanagari\", sans-serif",
                "fonts": ["Noto Sans Devanagari:wght@400;700"], "lineHeight": 1.8}

    # ---- finishing ----------------------------------------------------------------------
    def finalize_words(self, env, ctx, words):
        from collections import Counter
        from ..core.gloss import strip_gloss_style
        from ..core.util import stat
        info = self._info()
        spell = {}                      # folded surface -> Counter(NFC spellings in the corpus)
        for r in ctx["rows_by_sid"].values():
            for m in self.word_re.finditer(nfc(r[1])):
                spell.setdefault(fold(m.group(0)), Counter())[m.group(0)] += 1
        infs, vforms = self._verbs()
        gpos = {"NOUN": "noun", "ADJ": "adj", "VERB": "verb"}
        variants = {}                   # (folded key, pos) -> folded variant spellings
        for (cw, g), v in SPELLING_VARIANTS.items():
            variants.setdefault((fold(cw), gpos[g]), set()).add(fold(v))

        def rows_for(key, pos):
            rs = info.get(key, [])
            return [r for r in rs if r[1] == pos and r[3]] or [r for r in rs if r[3]] or rs

        def display(key, pos, en):
            if key in DISPLAY:
                return DISPLAY[key]
            if " " in key:
                return " ".join(display(p, None, "") for p in key.split(" "))
            rs = rows_for(key, pos) if pos else [r for r in info.get(key, []) if r[3]] or info.get(key, [])
            if rs:
                ours = set(re.findall(r"[a-z]{3,}", (en or "").lower()))
                rs = sorted(rs, key=lambda r: (-len(ours & set(re.findall(r"[a-z]{3,}", (r[4] or "").lower()))),
                                               NUKTA not in r[0], r[0]))
                return rs[0][0]
            c = spell.get(key)
            return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if c else key

        def rom(key, pos, shown):
            if " " in key:
                return " ".join(rom(p, None, s) for p, s in zip(key.split(" "), shown.split(" ")))
            rs = [r for r in (rows_for(key, pos) if pos else info.get(key, [])) if r[2] and r[0] == shown] or \
                 [r for r in (rows_for(key, pos) if pos else info.get(key, [])) if r[2]]
            return rs[0][2] if rs else translit(shown)

        pack_keys = {w["lemma"] for w in words}      # folded keys, before display spelling
        n_kaikki_pron = 0
        for w in words:
            w["en"] = strip_gloss_style(w["en"])
            w["en"] = re.sub(r"[,;]\s*(including|such as|e\.g\.|namely|like|especially|of|and|or)\s*$", "", w["en"])
            key = w["lemma"]
            kpos = {"prep": "postp", "part": "particle"}.get(w["pos"], w["pos"])
            shown = display(key, kpos, w["en"])
            w["w"] = w["lemma"] = shown
            w["pron"] = rom(key, kpos, shown)
            if all(any(r[2] for r in info.get(p, [])) for p in key.split(" ")):
                n_kaikki_pron += 1
            if w.get("pos") == "intj" and key in PHRASE_SEQ.values():
                w["pos"] = "phrase"
            # alts: the corpus spellings of the word's own forms (the engine finds
            # the word in its sentences by w or an alt, literally)
            if " " in key:
                if key in POSTP:
                    tail = shown.split(" ")[-1]
                    w["alt"] = [tail] + [s for s in sorted(spell.get(fold(tail), {}), key=lambda s: -spell[fold(tail)][s])
                                         if s != tail][:3]
                else:
                    w.pop("alt", None)
                continue
            forms = {key} | variants.get((key, w["pos"]), set())
            if w["pos"] in ("noun", "adj", "verb", "det", "num"):
                for fk in list(forms):
                    for r in info.get(fk, []):
                        if r[3] and r[1] == kpos:
                            forms |= set(r[6])
            if w["pos"] == "verb":
                for fk in [key] + sorted(variants.get((key, "verb"), ())):
                    if fk in infs:
                        forms |= {f for f, ls in vforms.items() if fk in ls}
            if w["pos"] == "adj" and key.endswith("ा"):
                forms |= {key[:-1] + "ी", key[:-1] + "े"}
            if w["pos"] == "pron":
                forms |= {k for k, v in self.closed_surfaces.items() if v[0] == key}
            alts = Counter()
            for f in forms:
                if f != key and f in pack_keys:
                    continue        # पानी is "water", not a form of पाना; कहीं is "somewhere"
                for s, c in spell.get(f, {}).items():
                    if s != shown:
                        alts[s] += c
            for v in variants.get((key, w["pos"]), ()):       # the variant headword itself
                vs = display(v, kpos, "")
                if vs != shown and vs not in alts:
                    alts[vs] = max(alts.values(), default=0) + 1
            # होना: every copula form (थीं, हों) whatever its corpus count
            cap = 30 if key == "होना" else 14
            al = [s for s, _ in sorted(alts.items(), key=lambda kv: (-kv[1], kv[0]))][:cap]
            if key == "होना":
                al += [nfc(c) for c in sorted(COPULA_FORMS) if nfc(c) not in al and nfc(c) != shown and
                       not (c.endswith("ं") and c[:-1] + "ँ" in al)]
            if key == KAUNSA:
                al, w["pron"] = list(KAUNSA_ALTS), "kaun-sā"
            if key == "का":
                al = ["की", "के"]          # the genitive agrees: का/की/के
            if al:
                w["alt"] = al
            else:
                w.pop("alt", None)
        # alts owned by another word: a surface that is another pack word's own
        # spelling, or (for a content word) a function word's form, is never
        # this word's alt (करना's की is the genitive; की वजह से's से is से)
        is_func = lambda w: w["pos"] in ("prep", "pron", "conj", "part", "phrase") or fold(w["w"]) in self.function_lemmas
        own = {}
        for w in words:
            own.setdefault(fold(w["w"]), set()).add(w["id"])
        dropped = {}

        def prune(w, bad):
            keep = [a for a in w.get("alt", []) if not bad(a)]
            gone = [a for a in w.get("alt", []) if bad(a)]
            if gone:
                dropped.setdefault(w["w"], []).extend(gone)
            if keep:
                w["alt"] = keep
            else:
                w.pop("alt", None)
        # pass 1: another pack word's own spelling (के अंदर's अन्दर is अंदर's)
        for w in words:
            prune(w, lambda a, w=w: bool(own.get(fold(a))) and w["id"] not in own[fold(a)])
        # pass 2: a content word never carries a function word's form
        func_surf = {}
        for w in words:
            if is_func(w):
                for a in [w["w"]] + w.get("alt", []):
                    func_surf.setdefault(fold(a), set()).add(w["id"])
        for w in words:
            if not is_func(w):
                prune(w, lambda a, w=w: bool(func_surf.get(fold(a), set()) - {w["id"]}))
        stat("hi_alts_dropped_owned", {k: dropped[k] for k in sorted(dropped)})
        stat("hi_display", {"pron_from_wiktionary": f"{n_kaikki_pron}/{len(words)}",
                            "pron_transliterated": len(words) - n_kaikki_pron})

    def check_word(self, w):
        f = fold(w["w"])
        if w.get("pos") == "verb" and not (f.endswith("ना") or f == "चाहिए"):
            return f"verb {w['id']} {w['w']!r}: not an infinitive"
        if w.get("pos") == "verb" and f != "चाहिए" and not (w.get("en") or "").startswith("to "):
            return f"verb {w['id']} {w['w']!r}: gloss {w.get('en')!r} does not start with 'to '"
        if w.get("pos") == "noun" and f.endswith(("ें", "ों")) and self._info().get(f[:-2] if f.endswith("ें") else f[:-2]):
            return f"noun {w['id']} {w['w']!r}: plural/oblique form as a lemma"
        if w.get("pos") == "adj" and f.endswith(("ी", "े")) and self._has(f[:-1] + "ा", ("adj",)) and \
                not self._has(f, ("adj",)):
            return f"adj {w['id']} {w['w']!r}: inflected adjective as a lemma"
        if re.search("[क़-य़]", w["w"]):
            return f"word {w['id']} {w['w']!r}: precomposed nukta letter (not NFC)"
        return None

    # ---- QA scans ----------------------------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "seasons": " ".join(SEASONS),
        "num": " ".join(NUMBERS), "col": " ".join(COLOURS),
        "core": " ".join(PRONOUNS + POSSESSIVES + POSTPS + [x for x, _ in GREETINGS + QUESTION + CONJS + PARTICLES]),
    }
    qa_verb_re = r"(ना|चाहिए)$"
    qa_foreign_letters_re = r"[a-z]"
    qa_proper_re = r"\b(India|Delhi|Mumbai|Hindu|Muslim|Pakistan|Krishna|Rama?|Shiva|Allah|God)\b"

    # ---- script primer ------------------------------------------------------------------------
    # tts true: hi-IN voices ship with Android/Google TTS, iOS and Windows; not ear-checked
    # on the user's devices (docs/SCRIPT_PRIMER.md ss0 probe pending).
    script = {"stages": [{"key": "deva", "label": "देवनागरी"}],
              "setsPerSession": 2, "mastered": 3, "tts": True,
              "learnKinds": ["symSound", "compose"],
              "reviewKinds": ["symSound", "soundSym", "compose", "wordRead"],
              "testKinds": {"symSound": 30, "soundSym": 20, "compose": 20, "wordRead": 20, "symType": 10}}

    def script_units(self):
        out = []
        for st, group, slug, t, name, roman, alt, confuse, note, base in HI_SCRIPT:
            u = {"id": "hi-" + slug, "st": "deva", "set": st, "group": group, "t": nfc(t), "name": name,
                 "roman": roman, "alt": alt, "note": note, "confuse": ["hi-" + c for c in confuse]}
            if base:
                u["base"] = "hi-" + base
            if slug == "virama":
                u["sound"] = False
            out.append(u)
        return out

    def script_notes(self):
        return HI_SCRIPT_NOTES

    def script_tokens(self, text):
        """Units in reading order: a listed conjunct first, then consonant (+ nukta),
        vowel, matra, sign; an unlisted sign (ॉ, ॅ) is a unit-less symbol."""
        s = nfc(text)
        toks, i = [], 0
        while i < len(s):
            conj = next((c for c in HI_CONJ if s.startswith(c, i)), None)
            if conj:
                toks.append(("hi-" + HI_UNIT_OF[conj], True, len(toks)))
                i += len(conj)
                continue
            ch = s[i]
            if i + 1 < len(s) and s[i + 1] == NUKTA:
                g = ch + NUKTA
                toks.append((("hi-" + HI_UNIT_OF[g]) if g in HI_UNIT_OF else None, True, len(toks)))
                i += 2
                continue
            if ch in HI_UNIT_OF:
                toks.append(("hi-" + HI_UNIT_OF[ch], True, len(toks)))
            elif re.match(f"[{DEV}]", ch):
                toks.append((None, False, len(toks)))
            else:
                return None
            i += 1
        return toks

    def script_ex_roman(self, word, text, toks):
        return word.get("pron")

    def script_syllables(self, text):
        """Consonant (or conjunct) + vowel sign: the compose items (क + ा = का)."""
        out = []
        s = nfc(text)
        i = 0
        while i < len(s):
            conj = next((c for c in HI_CONJ if s.startswith(c, i)), None)
            head = conj or (s[i:i + 2] if i + 1 < len(s) and s[i + 1] == NUKTA else s[i])
            j = i + len(head)
            if head in HI_UNIT_OF and (head in HI_CONS or conj) and j < len(s) and s[j] in HI_MATRA:
                cu, mu = HI_UNIT_OF[head], HI_UNIT_OF[s[j]]
                out.append((head + s[j], ["hi-" + cu, "hi-" + mu], HI_ROMAN[cu][:-1] + HI_ROMAN[mu]))
                i = j + 1
                continue
            i = j
        return out

    def script_say(self, unit):
        """Carrier (docs/SCRIPT_PRIMER.md ss5): vowels and consonants (inherent a) as
        written, a vowel sign on क (का), anusvara/chandrabindu/visarga on अ."""
        if unit.get("sound") is False:
            return None
        g = unit["t"]
        grp = unit["group"]
        if grp == "matra":
            return "क" + g
        if grp == "sign":
            return {"ं": "अं", "ँ": "आँ", "ः": "अः"}.get(g)
        return g


SPEC = Hindi
