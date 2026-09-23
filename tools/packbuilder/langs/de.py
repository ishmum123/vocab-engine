"""German (de): everything German-specific in the pack pipeline.

German differs from the Romance packs in three ways the core cannot guess:

- Nouns are capitalised. The frequency list is lowercased and the core
  lowercases every surface, so lemmas are kept lowercase internally (fold)
  and the display case is restored in finalize_words (nouns, Sie,
  Entschuldigung). A capitalised mid-sentence token is not a name here
  (caps_mark_names = False); names come from the PROPN tag and kaikki.
- Separable verbs split in main clauses ("fängt ... an"). At tag time each
  token's STTS fine tag is kept in its morph string (Tag=PTKVZ marks the
  particle); post_resolve rejoins particle + the clause's finite verb into
  one lemma (anfangen) when Wiktionary has that verb, so counting, English
  bags and sentence links all see anfangen and never the preposition an.
- Formal Sie and sie share a lowercased surface. fix_sentence decides at tag
  time (mid-sentence capital = formal; sentence-initial: the English
  translation's you vs she/they), storing lemma "Sie"; post_resolve maps it
  to its own entry.

The A1 core list and gloss overrides live in the german repo's tools/.
"""
import re

from .base import LanguageSpec, TATOEBA_ENG, TATOEBA_AUDIO
from ..core.lexicon import GROUP_OF

DAYS = "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag".split()
MONTHS = "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split()
SEASONS = "Frühling Sommer Herbst Winter".split()
NUMBERS = ("null eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn vierzehn fünfzehn "
           "sechzehn siebzehn achtzehn neunzehn zwanzig dreißig vierzig fünfzig sechzig siebzig achtzig "
           "neunzig hundert tausend").split()
COLOURS = "rot blau grün gelb schwarz weiß grau braun rosa orange lila".split()
PERSONAL = "ich du er sie es wir ihr Sie".split()
POSSESSIVE = "mein dein sein ihr unser euer".split()
QUESTION_ADV = "wie wo wann warum woher wohin".split()
QUESTION_PRON = "wer was".split()
PREPOSITIONS = "in an auf mit von zu für bei nach aus".split()

# (display, parts): phrases linked by substring (keys are the lowercase text)
# sexual/suicide content is kept out of A1/A2 sentences (German text or English)
SENSITIVE_RE = re.compile(
    r"\b(sex\w*|sexuell\w*|selbstmord\w*|suizid\w*|vergewaltig\w*|porno\w*|nackt\w*|kondom\w*|orgasmus|"
    r"prostituiert\w*|nutte\w*|hure\w*|bordell\w*|"
    r"sexually|suicide|suicidal|rape[ds]?|raping|rapist|porn\w*|naked|nude|orgasm|condom|prostitut\w*|whore\w*|"
    r"fuck\w*|shit\w*|bitch\w*|asshole\w*|pussy|"
    r"kill(ed|s)? (himself|herself|myself|yourself|themselves|ourselves)|"
    r"(bringe?n?|brachte|umgebracht) (sich|mich|dich) um|"
    r"(ge)?töte\w*|töten|tötet|umbring\w*|umgebracht|umbrachte\w*|bring\w* \w+ um|brachte\w* \w+ um|"
    r"erschie(ß|ss)\w*|erschoss\w*|ermord\w*|mord\w*|mörder\w*|erstech\w*|erstoch\w*|erwürg\w*|"
    r"tot|tote[mnrs]?|sterben lass\w*|lass\w* \w+ sterben|"
    r"kill\w*|murder\w*|dead|shoot (you|him|her|them|me)|stab(bed)?)\b", re.I)

PHRASES = {"auf Wiedersehen": "goodbye", "guten Morgen": "good morning", "guten Tag": "hello, good day",
           "guten Abend": "good evening", "gute Nacht": "good night"}

# pronoun surface -> lemma. Object/dative forms fold into the nominative
# (mich, mir -> ich), as Italian folds mi -> io; spaCy's lemmas for these are
# unreliable (mich -> "sich"). "ihr" Person=3 (dative of sie) is fixed in
# post_resolve. Relative/demonstrative der-forms: das -> das ("that"),
# the rest -> der ("who, which").
PRON_OF = {"ich": "ich", "mich": "ich", "mir": "ich", "du": "du", "dich": "du", "dir": "du",
           "er": "er", "ihn": "er", "ihm": "er", "sie": "sie", "ihnen": "sie", "es": "es",
           "wir": "wir", "uns": "wir", "ihr": "ihr", "euch": "ihr", "sich": "sich", "man": "man",
           "wer": "wer", "wen": "wer", "wem": "wer", "wessen": "wer", "was": "was",
           "das": "das", "der": "der", "die": "der", "den": "der", "dem": "der", "denen": "der",
           "dessen": "der", "deren": "der", "derer": "der"}

ALLOWED_PAST = {"sein", "haben", "können", "müssen", "wollen", "sollen", "dürfen", "mögen", "möchten"}
ALLOWED_PAST_RE = re.compile(r"^(war|warst|waren|wart|hatte|hattest|hatten|hattet|konnte|musste|wollte|sollte|"
                             r"durfte|mochte)(st|n|t)?$")
SEIN_VERBS = {"gehen", "kommen", "fahren", "fliegen", "laufen", "fallen", "sterben", "werden", "bleiben", "sein",
              "passieren", "geschehen", "reisen", "aufstehen", "einschlafen", "ankommen", "abfahren",
              "verschwinden", "wachsen", "springen", "schwimmen", "wandern", "folgen", "begegnen", "gelingen",
              "umziehen", "aufwachen", "zurückkommen", "zurückkehren", "ausgehen", "losgehen", "weggehen",
              "vergehen", "entstehen", "erscheinen", "steigen", "sinken", "rennen", "ziehen", "treten",
              "gelangen", "erschrecken", "einsteigen", "aussteigen", "umsteigen", "eintreten", "mitkommen"}
IMPERATIVE_NEXT = {"uns", "mich", "dich", "mir", "dir", "ihn", "ihm", "es", "euch", "mal", "doch", "bitte", "bloß",
                   "schon", "endlich", "her", "hin", "weg", "auf", "ab", "an", "aus", "zu", "los", "nicht",
                   "sofort", "jetzt", "nur", "einfach", "ruhig"}
NOMINAL_ADJ_ZIPF = 5.0
# before a nominalised infinitive (das Rauchen, beim Lernen) rather than a plural noun
NOMINALISERS = {"das", "dem", "des", "beim", "zum", "vom", "im", "ins", "am", "ans", "aufs", "fürs", "ums", "durchs",
                "übers", "vorm", "ein", "einem", "eines", "kein", "keinem", "sein", "mein", "dein", "unser", "euer",
                "ihr", "lautes", "ständige", "ständiges"}
PLURAL_NOUN_ZIPF = 3.5
SEP_PARTICLES = {"ab", "an", "auf", "aus", "bei", "ein", "fest", "fort", "her", "hin", "los", "mit", "nach", "vor",
                 "weg", "weiter", "zu", "zurück", "zusammen", "vorbei", "heraus", "herein", "hinaus", "hinein",
                 "herum", "um", "wieder", "statt", "teil", "frei", "kennen", "hoch", "runter", "rüber", "rein", "raus",
                 "herunter", "hinunter", "entgegen", "dazu", "fern", "nieder", "bereit", "kaputt", "vorwärts"}
INSEP_PREFIXES = ("be", "ge", "er", "ver", "zer", "ent", "emp", "miss")
COMPARATIVES = {"mehr", "weniger", "lieber", "eher", "besser", "anders", "schlechter", "größer", "kleiner", "älter",
                "jünger", "früher", "später", "schneller", "länger", "höher", "weiter", "öfter", "schöner"}
SAY_VERBS = {"sagen", "antworten", "nicken", "stimmen"}
MODAL_INF = {"sollen", "müssen", "können", "dürfen", "wollen", "mögen"}
PLURAL_FIX = {"zeug": "-"}          # Wiktionary lists Zeuge (= witness) as its plural
RARE_PLURAL_ZIPF = 2.4
IHR_PRON_NEXT = {"zwei", "drei", "vier", "beide", "beiden"}   # "ihr zwei": you two
CLAUSE_PUNCT = {",", ";", ".", "!", "?", ":", "—", "–", '"'}
QUESTION_WORDS = {"was", "wann", "wo", "wie", "warum", "wieso", "weshalb", "wer", "wen", "wem", "woher", "wohin",
                  "welche", "welcher", "welches", "welchen"}
RARE_PLURAL_MIN_SG = 50      # corpus singular tokens before a plural share is judged
RARE_PLURAL_SHARE = 100     # ... and the noun's plural is under 1% of its corpus tokens
RARE_PLURAL_HOMOGRAPH_ZIPF = 3.5   # a plural this common is real even when it doubles as a verb form
MOECHTEN = {"möchte", "möchtest", "möchten", "möchtet"}
FINITE_TAGS = ("Tag=VVFIN", "Tag=VVIMP", "Tag=VAFIN", "Tag=VAIMP", "Tag=VMFIN")
QUOTES = set("\"'„“”‚‘’«»‹›()[]")
CLAUSE_END = {".", "!", "?", ":", "…", "-", "–", "—", ";"}

YOU_RE = re.compile(r"\byou(r|rs|rself|rselves)?\b", re.I)
THIRD_RE = re.compile(r"\b(she|her|hers|herself|they|them|their|theirs|themselves)\b", re.I)
EXPANSION_G_RE = re.compile(r"^\S+ (m|f|n|pl)\b")
QUAL_RE = re.compile("\U0010203f([^\U00102040]*)\U00102040")
PARTICIPLE_OF_RE = re.compile(r"\bpast participle of ([^\s:;,.()]+)")
AGENT_RE = re.compile(r"^agent noun of [^\s:;]+[:;] (.+)$")
STANDARD_TAGS = {"Germany", "especially"}
LETTER_RE = re.compile(r"^(the )?(name of the )?(\S+ )?(letter|alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|"
                       r"kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega|[A-Z])\b", re.I)      # a sense also used in Germany is not regional
TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})

REGIONAL = {"Austria", "Austrian", "Switzerland", "Swiss", "Southern-Germany", "Northern-Germany",
            "Bavaria", "Bavarian", "Swabia", "Swabian", "Berlin", "Saxony", "Rhineland", "South-Tyrol",
            "Liechtenstein", "Luxembourg", "Westphalia", "Palatinate", "Franconia", "Hesse",
            "Northwest-German", "Low-German", "Ruhr", "Silesia", "Prussia", "East-Germany", "GDR",
            "Tyrol", "Vienna", "Carinthia", "Styria", "Alemannic", "Upper-German", "Central-German",
            "Southwestern-Germany", "Western-Germany", "Northern-German", "Southern-German"}


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def initial_at(toks, i):
    """Token i opens a sentence/clause that German capitalises (start, or
    after . ! ? : and dashes), skipping quotes and brackets."""
    j = i - 1
    while j >= 0 and toks[j][0] in QUOTES:
        j -= 1
    return j < 0 or toks[j][0] in CLAUSE_END


class German(LanguageSpec):
    code = "de"
    name_en = "German"
    pack_name = "German (A1–B1)"
    tts = "de-DE"
    stt = "de-DE"
    tatoeba_code = "deu"

    spacy_model = "de_core_news_sm"
    tagger_attribution = {
        "source": "spaCy (MIT) + de_core_news_sm 3.8.0 model (MIT; trained on TIGER and WikiNER)",
        "licence": "MIT (model)",
        "note": "Used at build time only; the pack ships no model files.",
    }

    subtitles_file = "de_full.txt"
    kaikki_file = "kaikki_de.jsonl.gz"
    sentences_file = "deu_sentences_detailed.tsv.bz2"
    links_file = "deu-eng_links.tsv.bz2"
    sources = {
        "de_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/de/de_full.txt",
        "kaikki_de.jsonl.gz": "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl.gz",
        "deu_sentences_detailed.tsv.bz2":
            "https://downloads.tatoeba.org/exports/per_language/deu/deu_sentences_detailed.tsv.bz2",
        "deu-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/deu/deu-eng_links.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t2", "lex": "l6"}

    show_pron = True            # the plural line under a noun ("pl. Häuser")

    lex_word_re = re.compile(r"^[a-zäöüß]+$")
    sub_token_re = re.compile(r"^[a-zäöüß]+$")
    form_target_re = re.compile(r"\bof ([A-Za-zÄÖÜäöüß]+)")
    fem_of_re = re.compile(r"(?!)")   # Lehrerin is its own noun (die Lehrerin), never an alt of der Lehrer

    noun_head_template = "de-noun"
    regional_tags = REGIONAL

    caps_mark_names = False
    keep_unseen_keys = False    # a lemma never seen in 496k tagged sentences is junk here (letters, English, Swiss ss)
    numeral_verb_rule = False   # sieben/acht are numerals, not "to sieve"/"to heed"

    art_prep = {"im": "in", "ins": "in", "am": "an", "ans": "an", "zum": "zu", "zur": "zu", "beim": "bei",
                "vom": "von", "aufs": "auf", "fürs": "für", "durchs": "durch", "ums": "um", "übers": "über",
                "unterm": "unter", "hinterm": "hinter", "vorm": "vor", "überm": "über"}
    article_forms = {"der": {"der", "die", "das", "den", "dem", "des"},
                     "ein": {"ein", "eine", "einen", "einem", "einer", "eines"}}
    definite_article = "der"
    pluralia_tantum = {"eltern", "leute", "ferien", "geschwister", "kosten", "lebensmittel", "jeans", "shorts", "daten",
                       "alpen", "trümmer", "zinsen", "masern", "flitterwochen", "personalien", "spirituosen"}
    copulas = {"sein", "werden", "bleiben"}
    clitic_of = PRON_OF
    verb_endings = ("n",)                         # -en, -ern, -eln, sein, tun
    function_verbs = {"sein", "haben", "werden"}  # modals are drilled as content words

    forced_closed = ([(w.lower(), "NOUN") for w in DAYS + MONTHS + SEASONS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS] +
                     [(w, "PRON") for w in PERSONAL] + [(w, "DET") for w in POSSESSIVE] +
                     [(w, "PRON") for w in QUESTION_PRON] + [(w, "ADV") for w in QUESTION_ADV] +
                     [("welcher", "DET")] + [(w, "ADP") for w in PREPOSITIONS] +
                     [("und", "CONJ"), ("oder", "CONJ"), ("aber", "CONJ"), ("nicht", "PART"), ("kein", "DET"),
                      ("der", "DET"), ("ein", "DET"),
                      ("ja", "INTJ"), ("nein", "INTJ"), ("hallo", "INTJ"), ("tschüss", "INTJ"), ("danke", "INTJ"),
                      ("bitte", "INTJ"), ("entschuldigung", "INTJ"), ("möchten", "VERB")] +
                     [(p.lower(), "PHRASE") for p in PHRASES])
    no_article = set()
    allowed_num = set(NUMBERS)
    fixed_gloss = {
        ("der", "DET"): "the (der, die, das)", ("ein", "DET"): "a, an (ein, eine)",
        ("ich", "PRON"): "I; me", ("du", "PRON"): "you (informal)", ("er", "PRON"): "he; him, it",
        ("sie", "PRON"): "she; they; her, them", ("es", "PRON"): "it", ("wir", "PRON"): "we; us",
        ("ihr", "PRON"): "you (plural, informal)", ("Sie", "PRON"): "you (formal)",
        ("sich", "PRON"): "oneself, himself, herself, themselves", ("man", "PRON"): "one, you, people",
        ("wer", "PRON"): "who", ("was", "PRON"): "what", ("das", "PRON"): "that, this; which",
        ("der", "PRON"): "who, which, that (relative)",
        ("mein", "DET"): "my", ("dein", "DET"): "your (informal)", ("sein", "DET"): "his, its",
        ("ihr", "DET"): "her, their; (Ihr) your (formal)", ("unser", "DET"): "our",
        ("euer", "DET"): "your (plural, informal)", ("kein", "DET"): "no, not a, not any",
        ("welcher", "DET"): "which",
        ("möchten", "VERB"): "would like (to)",
        ("bitte", "INTJ"): "please; you're welcome", ("entschuldigung", "INTJ"): "excuse me, sorry",
        ("danke", "INTJ"): "thanks, thank you", ("nein", "INTJ"): "no", ("ja", "INTJ"): "yes",
        ("tschüss", "INTJ"): "bye", ("hallo", "INTJ"): "hello",
    }
    fixed_gloss.update({(p.lower(), "PHRASE"): g for p, g in PHRASES.items()})
    fixed_word = {("der", "DET"): ("der", ["die", "das", "den", "dem", "des"]),
                  ("ein", "DET"): ("ein", ["eine", "einen", "einem", "einer", "eines"])}
    multiword = {p.lower(): tuple(p.lower().split()) for p in PHRASES}
    phrase_token_spans = True     # "Auf Wiedersehen" links the phrase only, never auf + wiedersehen
    sensitive_re = SENSITIVE_RE
    refill_unexampled = True      # a word no sentence can show is replaced by the next-ranked word
    example_shows_word = True     # one example shows Haus itself, not only Häuser
    # residuals no rule reaches: "weißen" (whiten; inflected weiß in the lists),
    # die Aue (from the interjection "Au!")
    drop_keys = {("weißen", "VERB"): None, ("aue", "NOUN"): None}
    profane_stems = ("fick", "scheiß", "scheiss", "arschl", "wichs", "fotz", "hurens")
    profanity = {"scheiße", "scheisse", "arsch", "hure", "huren", "schlampe", "kacke", "pisse", "pissen",
                 "verdammt", "verdammte", "wichser", "fotze", "schwuchtel", "nutte", "titten", "bumsen",
                 "mist", "arschloch"}

    report_title = "German A1-B1 pack (corpus-tagged)"
    forced_description = ("days, months, seasons, numbers 0-20 + tens + hundert/tausend, colours, personal and "
                          "possessive pronouns, question words, articles, core prepositions/conjunctions, "
                          "greetings, A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000"
    article_pool_note = "; articles der/ein kept alongside"
    marked_past_name = "Präteritum (other than sein/haben/modals)"

    def __init__(self, repo=None):
        super().__init__(repo)
        self._lex = None
        self.sep_stats = {"joined": 0, "no_verb": 0, "not_in_dictionary": 0}
        self.plural_debug = []
        self._pr_cache = {}
        self.sep_examples = {}

    def load(self):
        """The A1 core list is written with German capitalisation (Haus);
        internal lemmas are lowercase."""
        super().load()
        self.a1_core = {g: [w if w == "Sie" else w.lower() for w in ws] for g, ws in self.a1_core.items()}
        self.forced = list(self.forced_closed) + [(w, g) for g, ws in self.a1_core.items() for w in ws]
        return self

    # ---- orthography -------------------------------------------------------
    def fold(self, s):
        return s.lower()

    # ---- tag time -----------------------------------------------------------
    def fix_sentence(self, toks, row, doc):
        spt = [t for t in doc if not t.is_space]
        if len(spt) != len(toks):
            return toks
        eng = row[3] if row and len(row) > 3 else ""
        out = []
        for i, (tok, t) in enumerate(zip(toks, spt)):
            text, lem, upos, ms = tok
            tag = t.tag_
            if tag == "ADJD" and upos in ("ADV", "ADJ"):
                upos = "ADJ"               # predicative/adverbial adjective (nett, kalt, schnell)
            if upos in ("DET", "ADP") and "Number=Plur" in ms:
                # plural articles have no gender; spaCy copies a guess that
                # would block the noun link on a gender mismatch
                ms = "|".join(kv for kv in ms.split("|") if not kv.startswith("Gender="))
            ms = (ms + "|" if ms else "") + "Tag=" + tag
            if len(text) > 1 and text[:1].isupper() and not text.isupper() and not initial_at(toks, i) and \
                    re.search(r"(?<![\w-])" + re.escape(text) + r"(?![\w-])", eng):
                # the same capitalised word in the English translation: a name
                # or a foreign word (Mark Zuckerberg, Lee, German), not a noun
                ms += "|Eng=Yes"
            low = text.lower()
            if upos == "PRON" and low in ("sie", "ihnen"):
                if not initial_at(toks, i):
                    if text[:1].isupper():
                        lem = "Sie"
                elif re.match(r"^\W*you\b", eng, re.I) or (YOU_RE.search(eng) and not THIRD_RE.search(eng)):
                    lem = "Sie"
            out.append([text, lem, upos, ms])
        return out

    # ---- resolve time -------------------------------------------------------
    def bind_lexicon(self, lexicon):
        """Wiktionary conventions the core would misread, fixed in the loaded
        lexicon: agent nouns (Lehrer "agent noun of lehren: teacher") are
        lemmas, not form-of lines; a sense tagged with regions that include
        Germany ("especially Germany, Switzerland": klingeln) is standard; and
        plural-only nouns (gender "p") are never singularised, unless the word
        is also another noun's plural (Tage)."""
        self._lex = lexicon
        self._vscore = {}
        self.n_agent = self.n_region = 0
        for w, ents in lexicon.E.items():
            for e in ents:
                for sn in e["s"]:
                    if e["p"] == "noun" and sn[3] == "form":
                        m = AGENT_RE.match(sn[0])
                        if m:
                            sn[0], sn[3] = m.group(1), ""
                            sn[2] = [t for t in sn[2] if t not in ("form-of", "agent")]
                            self.n_agent += 1
                    if set(sn[2]) & STANDARD_TAGS and set(sn[2]) & self.regional_tags:
                        sn[2] = [t for t in sn[2] if t not in self.regional_tags]
                        self.n_region += 1
        # letter names (das S, das My "mu") are not vocabulary
        for w, ents in lexicon.E.items():
            for e in ents:
                defs = [sn for sn in e["s"] if sn[3] == ""]
                if e["p"] == "noun" and defs and len(w) <= 3 and all(LETTER_RE.match(sn[0]) for sn in defs):
                    e["p"] = "letter"
        extra = set()
        for w, ents in lexicon.E.items():
            nouns = [e for e in ents if e["p"] == "noun" and e.get("g")]
            if nouns and all(self.parse_gender(e["g"])[1] for e in nouns) and not lexicon.plural_pointer(w):
                extra.add(w)
        self.pluralia_tantum = set(self.pluralia_tantum) | extra

    def _tagged_entry(self, w, g):
        """w has a definitional Wiktionary entry for group g, usable or not
        (kriegen: colloquial-only, filtered as a word)."""
        kp = self.group_kpos.get(g, [])[:1]
        return any(e["p"] in kp and any(sn[3] == "" for sn in e["s"]) for e in self._lex.E.get(w, []))

    def _has_noun(self, w):
        return bool(self._lex.usable_entries(w, ["noun"]))

    def _has_name(self, w):
        return any(e["p"] == "name" for e in self._lex.E.get(w, []))

    def post_resolve(self, toks, out):
        lx = self._lex
        out = list(out)
        for i, (text, sl, upos, ms) in enumerate(toks):
            r = out[i]
            if r is None:
                continue
            low = text.lower()
            if len(r[0]) == 1:
                out[i] = None                     # a single letter is never a word
                continue
            if r[0] != low and r[1] in ("NOUN", "VERB") and any(e["p"] == "intj" for e in lx.E.get(low, [])) and \
                    not lx.usable_entries(low, ["noun", "verb"]):
                out[i] = (low, "INTJ")            # "danke für ...": the interjection, never der Dank
                continue
            if upos == "NOUN" and r[1] == "ADJ" and text[:1].isupper() and not initial_at(toks, i) and \
                    lx.candidates(low, ["noun"]):
                # the core's copula rule ("è ridicolo") never applies to a
                # capitalised German noun: "Es war Liebe" is die Liebe
                out[i] = r = (lx.best_by_freq(lx.candidates(low, ["noun"])), "NOUN")
            pn = self._plural_noun(toks, i, text, low, r, ms)
            if pn:
                out[i] = pn                       # "Antworten", "in vielen Fällen": the plural noun
                continue
            if sl == "Sie" and r[1] == "PRON":
                out[i] = ("Sie", "PRON")
            elif low == "ihr" and r[1] in ("PRON", "DET"):
                out[i] = self._route_ihr(toks, i)
            elif r[1] == "VERB" and low in MOECHTEN:
                out[i] = ("möchten", "VERB")
            elif r[1] == "PROPN" and text[:1].islower():
                # German names are capitalised: a lowercase "name" is a tagger
                # error ("Tom muss" -> muss PROPN)
                alt = [x for x in lx.readings(low) if x[1] not in ("PROPN", "NOUN")]
                out[i] = max(alt, key=lambda x: (lx.zipf(x[0]), x)) if alt else None
            elif r[1] == "NOUN" and "Eng=Yes" in ms and not self._gloss_is(r[0], text):
                out[i] = (low, "PROPN")           # same word in the English: a name/foreign word
            elif r[1] == "NOUN" and r[0] != low and self._gerund_of(low) and not self._plural_reading(toks, i, low, r[0]):
                out[i] = (low, "VERB")            # "vor Lachen": the nominalised infinitive, never die Lache
            elif r[1] == "NOUN" and self._nominalised_adj(low, r[0]):
                out[i] = self._nominalised_adj(low, r[0])   # "der Beste", "als Erste": the adjective
            elif r[1] == "NOUN" and self._has_name(low) and self._name_context(toks, i):
                out[i] = (low, "PROPN")           # "Mark Zuckerberg": the name, not die Mark
            elif r[1] == "PROPN" and self._has_noun(low) and not self._has_name(low) and text[:1].isupper() \
                    and "Eng=Yes" not in ms and not self._name_context(toks, i):
                nouns = lx.candidates(low, ["noun"])   # the small model tags some nouns NE (Hunger)
                if nouns:
                    out[i] = (lx.best_by_freq(nouns), "NOUN")
            elif r[1] == "NOUN" and text[:1].isupper() and not self._has_noun(r[0]):
                out[i] = (low, "PROPN")           # a name tagged NN (Tom, Maria): never linked
            elif r[1] == "NOUN" and (len(text) == 1 or (text[:1].islower() and not initial_at(toks, i))):
                # German nouns are capitalised: a lowercase mid-sentence "noun"
                # is a tagger error (weh, gross, English "be"); a single letter
                # is an abbreviation fragment
                alt = [x for x in lx.readings(low) if x[1] not in ("NOUN", "PROPN")] if len(text) > 1 else []
                out[i] = max(alt, key=lambda x: (lx.zipf(x[0]), x)) if alt else None
            elif r[1] in ("DET", "PRON") and not lx.usable_entries(r[0], ["det", "pron", "article"]):
                # spaCy lemma with only an unrelated entry (alle "finished"): the
                # inflection target (all)
                c = lx.candidates(low, ["det", "pron"])
                if c:
                    out[i] = (lx.best_by_freq(c), r[1])
            elif r[1] == "DET" and r[0] == self.definite_article and not self._noun_follows(toks, i):
                # an article needs a noun: "Ist das Ihr erster Besuch?" is the
                # demonstrative das
                out[i] = ("das" if low == "das" else "der", "PRON")
            elif r[1] == "VERB" and "Tag=ADJA" in ms and lx.candidates(low, ["adj"]):
                out[i] = (lx.best_by_freq(lx.candidates(low, ["adj"])), "ADJ")   # "weißen Wein": attributive adjective
            elif r[1] in ("VERB", "ADJ") and ("VerbForm=Part" in ms or "Tag=VVPP" in ms or "Tag=VAPP" in ms or
                                              self._final_participle(toks, i, low)) and \
                    self._clause_aux(toks, i):
                # a participle needs an auxiliary; "Mir gefällt" (tagged VVPP
                # with none) is the finite verb
                out[i] = self._participle(toks, i, low, r)
            elif "Tag=ADJD" in ms and r[1] in ("ADJ", "ADV") and r[0] != low and \
                    lx.usable_entries(low, ["adj", "adv"]) and not lx.F.get(low):
                # a predicative/adverbial adjective is uninflected: its surface
                # is the lemma (was ist los -> los, never lose)
                out[i] = (low, "ADV" if lx.usable_entries(low, ["adv"]) and not lx.usable_entries(low, ["adj"]) else "ADJ")
            elif low == "gleich" and "Tag=ADJD" in ms and not self._after_copula(toks, i):
                out[i] = ("gleich", "ADV")        # "gleich anzufangen": right away, not the same
            elif low in ("ja", "nein") and r[1] != "INTJ" and self._say_follows(toks, i):
                out[i] = (low, "INTJ")            # "ja sagen": yes, not the particle
            elif low == "als" and r[1] != "ADP" and self._comparative_before(toks, i):
                out[i] = ("als", "ADP")           # "lieber ... als": than
            elif "Tag=PTKANT" in ms and any(e["p"] == "intj" for e in lx.E.get(low, [])):
                out[i] = (low, "INTJ")            # answer particle ja/nein/danke/bitte
            else:
                g = GROUP_OF.get(upos, upos)
                if g in ("VERB", "ADJ", "ADV") and r[1] != g and not lx.usable_entries(low, self.group_kpos.get(g)):
                    base = sl.lower() if self._tagged_entry(sl.lower(), g) else low if self._tagged_entry(low, g) else None
                    if base:
                        out[i] = (base, g)        # kriegen stays kriegen (filtered), never der Krieg
        for i, (text, sl, upos, ms) in enumerate(toks):
            r = out[i]
            if r is None:
                continue
            low = text.lower()
            imp = self._imperative(low) if r[1] != "VERB" and initial_at(toks, i) and \
                not any(e["p"] == "intj" for e in lx.E.get(low, [])) else None
            if imp and self._imperative_context(toks, i, loose=r[1] in ("ADJ", "ADV", "PROPN")):
                # clause-initial imperative the small model tagged ADJ/NOUN
                # ("Lass uns gehen", "Komm her!")
                out[i] = (imp, "VERB")
            elif r[1] == "VERB" and not (("VerbForm=Part" in ms or self._final_participle(toks, i, low))
                                         and r[0] in self._participle_targets(low)
                                         and self._clause_aux(toks, i)):
                # a rare verb among the surface's verb readings (weißt -> weißen
                # "to whiten" beside wissen, gefällt -> fällen beside gefallen):
                # the verb whose principal parts are far more common
                c = [v for v in lx.verbs_only(lx.candidates(low, ["verb"])) if v != r[0]]
                best = max(c, key=lambda v: (self.verb_score(v), v), default=None)
                if best and self.verb_score(best) >= self.verb_score(r[0]) + 1.0:
                    out[i] = (best, "VERB")
        # separable verbs: particle (PTKVZ) + the nearest finite verb before it
        for i, (text, sl, upos, ms) in enumerate(toks):
            part = text.lower()
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            clause_final = nxt is None or nxt[2] == "PUNCT"
            if "Tag=PTKVZ" not in ms and not (clause_final and part in SEP_PARTICLES and
                                              upos in ("ADP", "ADV", "PART", "ADJ") and out[i] is not None):
                continue
            j = i - 1
            imp = None
            while j >= 0 and toks[j][0] not in (".", "!", "?", ";"):
                if any(f in toks[j][3] for f in FINITE_TAGS) or \
                        (toks[j][2] == "VERB" and "VerbForm=Fin" in toks[j][3]):
                    break
                if out[j] and out[j][1] == "VERB" and toks[j][2] != "VERB" and j and \
                        toks[j - 1][2] in ("CCONJ", "PUNCT") and self._imperative(toks[j][0].lower()):
                    imp = out[j][0]               # "und hör zu": an imperative after a conjunction
                    break
                if initial_at(toks, j) and toks[j][2] != "PUNCT":
                    # clause-initial imperative the small model mis-tags
                    # ("Hör auf!" ADJD, "Geh weg" PROPN)
                    imp = self._imperative(toks[j][0].lower())
                    if imp:
                        break
                j -= 1
            joined = None
            strict = "Tag=PTKVZ" in ms           # else a clause-final particle tagged ADP/ADV
            if j >= 0 and (imp or any(f in toks[j][3] for f in FINITE_TAGS) or "VerbForm=Fin" in toks[j][3]):
                bases = [imp] if imp else []
                if out[j] and out[j][1] == "VERB":
                    bases.append(out[j][0])
                bases.append(toks[j][1].lower())
                bases += sorted(lx.candidates(toks[j][0].lower(), ["verb"]))
                for b in bases:
                    if lx.usable_entries(part + b, ["verb"]):
                        joined = part + b
                        break
                if joined:
                    out[j] = (joined, "VERB")
                    out[i] = None
                    self.sep_stats["joined"] += 1
                    continue
                if not strict:
                    continue
                self.sep_stats["not_in_dictionary"] += 1
                if len(self.sep_examples) < 30:
                    self.sep_examples.setdefault(part + "+" + toks[j][0].lower(), 0)
            elif strict:
                self.sep_stats["no_verb"] += 1
            if upos == "ADP" and "Tag=PTKVZ" in ms:
                out[i] = None                     # a particle is never the preposition
        return out

    def _route_ihr(self, toks, i):
        """ihr: before a noun the possessive (hat ihr Ticket); after a verb in
        -t or opening a question/clause before a verb the you-plural pronoun
        (Wartet ihr, Habt ihr); after a preposition or as Person=3 the dative
        of sie (mit ihr, Ich gebe ihr ...)."""
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if nxt is not None and nxt[0].lower() in IHR_PRON_NEXT:
            return ("ihr", "PRON")        # "ihr zwei", "ihr beide", "ihr alle"
        a = i
        while a > 0 and toks[a - 1][0] not in CLAUSE_PUNCT:
            a -= 1
        b = i
        while b + 1 < len(toks) and toks[b + 1][0] not in CLAUSE_PUNCT:
            b += 1
        v2 = {j: self._person_readings(toks[j][0].lower()) for j in range(a, b + 1)
              if j != i and not any(f in toks[j][3] for f in ("VerbForm=Part", "Tag=VVPP", "Tag=VAPP", "Tag=VMPP"))}
        v2 = {j: r for j, r in v2.items() if ("second", "plural") in r}
        if any(("third", "singular") not in r for r in v2.values()):
            return ("ihr", "PRON")        # seid, habt, könnt ... in the clause: you (plural)
        prev_j = i - 1
        if prev_j in v2 and (prev_j == a or toks[a][0].lower() in QUESTION_WORDS and
                             not self._noun_follows(toks, i, allow_adv=False)):
            return ("ihr", "PRON")        # "Wartet ihr", "Warum kauft ihr ...": verb-first, ihr is the subject
        if any(j > i for j in v2) and not self._noun_follows(toks, i, allow_adv=False):
            return ("ihr", "PRON")        # "Wenn ihr mich braucht", "ob ihr kommen könnt"
        name_next = nxt is not None and ("Eng=Yes" in nxt[3] or nxt[2] == "PROPN" or
                                         (self._has_name(nxt[0].lower()) and not self._has_noun(nxt[0].lower())))
        if self._noun_follows(toks, i, allow_adv=False) and not name_next:
            return ("ihr", "DET")
        prev = toks[i - 1] if i else None
        if initial_at(toks, i) and nxt and nxt[2] in ("VERB", "AUX"):
            return ("ihr", "PRON")
        if (prev and prev[2] == "ADP") or "Person=3" in toks[i][3]:
            return ("sie", "PRON")
        if not v2 and any(t[2] in ("VERB", "AUX") for t in toks[a:b + 1]):
            return ("sie", "PRON")        # no verb here agrees with ihr: "wurde ihr verweigert" = to her
        return ("ihr", "PRON")

    def _person_readings(self, low):
        """(person, number) pairs Wiktionary gives a verb form (braucht:
        third singular and second plural; seid: second plural only)."""
        if low not in self._pr_cache:
            out = set()
            for e in self._lex.E.get(low, []):
                if e["p"] != "verb":
                    continue
                for sn in e["s"]:
                    tags = set(sn[2])
                    for per in ("first", "second", "third"):
                        if f"{per}-person" in tags:
                            for num in ("singular", "plural"):
                                if num in tags:
                                    out.add((per, num))
            self._pr_cache[low] = out
        return self._pr_cache[low]

    def _plural_noun(self, toks, i, text, low, r, ms):
        """A capitalised token read as a verb/conjunction that is the plural
        (or dative plural) of a common noun: Antworten, Tagen, in vielen
        Fällen, mit besten Wünschen. After a neuter singular determiner it is
        a nominalised infinitive (das Rauchen, beim Lernen) and stays the verb.
        A sentence-initial capitalised conjunction the truecaser kept (Ehe) is
        the noun."""
        lx = self._lex
        if r[1] == "CONJ" and initial_at(toks, i) and i + 1 < len(toks) and "VerbForm=Fin" in toks[i + 1][3] and \
                "Tag=KOUS" not in ms and lx.usable_entries(low, ["noun"]):
            # a subordinating conjunction puts the verb last: "Ehe ist ..." is die Ehe
            return (low, "NOUN")
        if not text[:1].isupper() or "Eng=Yes" in ms or r[1] != "VERB":
            return None
        initial = initial_at(toks, i)
        j = i - 1
        while j >= 0 and toks[j][2] == "ADJ":
            j -= 1
        prev = toks[j] if j >= 0 else None
        if initial or (prev and prev[0].lower() in NOMINALISERS):
            return None
        if not (prev is None or prev[2] in ("DET", "ADP", "ADJ", "NUM", "PUNCT", "CCONJ", "PRON", "VERB", "AUX", "ADV")):
            return None
        nouns = [n for n in lx.candidates(low, ["noun"]) if n != low and lx.zipf(n) >= PLURAL_NOUN_ZIPF]
        if not nouns or not lx.plural_pointer(low) and not any(
                sn[3] == "form" and "plural" in sn[2] for e in lx.E.get(low, []) if e["p"] == "noun" for sn in e["s"]):
            return None
        return (max(nouns, key=lambda n: (lx.zipf(n), n)), "NOUN")

    def _gloss_is(self, lem, text):
        """A noun's own gloss is the same capitalised word (November = November)."""
        return any(re.search(r"\b" + re.escape(text) + r"\b", sn[0]) for e in self._lex.usable_entries(lem, ["noun"])
                   for sn in e["s"] if sn[3] == "")

    def _after_copula(self, toks, i):
        return any(t[2] == "AUX" and t[1].lower() == "sein" for t in toks[max(0, i - 3):i])

    def _say_follows(self, toks, i):
        for t in toks[i + 1:i + 4]:
            if t[2] in ("VERB", "AUX"):
                return t[1].lower() in SAY_VERBS or t[0].lower() in ("gesagt", "sagen", "sagt", "sag", "sagte")
        return False

    def _comparative_before(self, toks, i):
        for t in toks[max(0, i - 5):i]:
            lw = t[0].lower()
            if lw in COMPARATIVES or "Degree=Cmp" in t[3] or (t[2] in ("ADJ", "ADV") and any(
                    sn[3] == "form" and "comparative" in sn[2]
                    for e in self._lex.E.get(lw, []) if e["p"] in ("adj", "adv") for sn in e["s"])):
                return True
        return False

    def _final_participle(self, toks, i, low):
        """A clause-final ge- form the tagger read as finite ("... von ihm
        gehört."): a participle when Wiktionary lists it as one."""
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        return low.startswith("ge") and (nxt is None or nxt[2] == "PUNCT") and \
            bool(self._participle_targets(low))

    def _plural_reading(self, toks, i, low, noun):
        """The tagger's plural of a common noun (Tagen -> Tag, Träumen -> Traum)
        outside a nominalising context: keep the noun, never the gerund."""
        lx = self._lex
        j = i - 1
        while j >= 0 and toks[j][2] == "ADJ":
            j -= 1
        if j >= 0 and toks[j][0].lower() in NOMINALISERS:
            return False                  # das Rauchen, beim Lernen
        if toks[i][1].lower() != low and toks[i][1].lower() == noun and lx.zipf(noun) >= PLURAL_NOUN_ZIPF:
            return True                   # tagged as a form of the noun (von ganzem Herzen -> Herz)
        if "Number=Sing" in toks[i][3]:
            return False                  # "dass Rauchen ... ruiniert"
        return lx.plural_pointer(low) and lx.zipf(noun) >= PLURAL_NOUN_ZIPF

    def _gerund_of(self, low):
        """low is a verb infinitive that Wiktionary also lists as its gerund
        noun (das Lachen): the verb, when it is usable."""
        lx = self._lex
        return any(e["p"] == "noun" and any("gerund" in sn[2] for sn in e["s"]) for e in lx.E.get(low, [])) and \
            bool(lx.usable_entries(low, ["verb"]))

    def _nominalised_adj(self, low, lem):
        """An adjectival noun (der/die Beste, das Gute) built on a very common
        adjective links that adjective; lexicalised person nouns on rarer
        adjectives (der/die Erwachsene, der/die Deutsche) stay nouns."""
        lx = self._lex
        ents = lx.usable_entries(lem, ["noun"])
        # every noun reading is adjectival (die Liebe "love" is not)
        adjectival = (bool(ents) and all(len(str(e.get("g", "")).split("|")) > 2 and str(e.get("g", "")).split("|")[2]
                                         for e in ents)) \
            or (not ents and any("nominalization" in sn[0] for e in lx.E.get(lem, []) if e["p"] == "noun"
                                 for sn in e["s"]))
        if not adjectival:
            return None
        adj = lx.candidates(low, ["adj"])
        best = max(adj, key=lambda a: (lx.zipf(a), a), default=None)
        return (best, "ADJ") if best and lx.zipf(best) >= NOMINAL_ADJ_ZIPF else None

    def _name_context(self, toks, i):
        """Token i sits next to a name: a capitalised neighbour with no
        noun entry (Zuckerberg) or one tagged PROPN."""
        for j in (i - 1, i + 1):
            if 0 <= j < len(toks) and toks[j][0][:1].isupper() and toks[j][2] in ("PROPN", "NOUN", "X") and \
                    not initial_at(toks, j) and not self._has_noun(toks[j][0].lower()):
                return True
        return False

    def _imperative(self, s):
        """Verb whose imperative Wiktionary lists as s (German imperative
        senses carry no person tag, so the core's imperative_form misses them)."""
        lx = self._lex
        for e in lx.E.get(s, []):
            if e["p"] == "verb" and any(sn[3] == "form" and "imperative" in sn[2] for sn in e["s"]):
                c = lx.verbs_only(lx.candidates(s, ["verb"]))
                if c:
                    return max(c, key=lambda v: (self.verb_score(v), v))
        return None

    def verb_score(self, v):
        """Commonness of a verb from its principal parts: min(zipf(preterite),
        zipf(past participle)). The infinitive is often an inflected form of
        something else (weißen = weiß adj), and the min discounts one shared
        part (gefällt is also gefallen's present)."""
        if v not in self._vscore:
            lx = self._lex
            parts = next((str(e.get("g", "")).split("|")[1:3] for e in lx.E.get(v, [])
                          if e["p"] == "verb" and str(e.get("g", "")).startswith("v|")), [])
            parts = [x for x in parts if x]
            self._vscore[v] = min((lx.zipf(x.lower()) for x in parts), default=lx.zipf(v) - 1.0)
        return self._vscore[v]

    def _imperative_context(self, toks, i, loose=False):
        """What follows a clause-initial word marks it as an imperative: "!"
        right after it, or an object pronoun/particle (Lass uns, Hör mal).
        loose (the word was tagged ADJ/ADV/PROPN): anything but a finite verb
        or a comma, since a fronted adjective is followed by the verb in V2
        order (Weiß ist ..., Lass das Wasser ...)."""
        nxt = toks[i + 1][0].lower() if i + 1 < len(toks) else ""
        if nxt in IMPERATIVE_NEXT or (nxt == "!" and i + 2 >= len(toks) - 1):
            return True
        if loose and i + 1 < len(toks):
            t = toks[i + 1]
            return t[2] not in ("VERB", "AUX", "PUNCT", "CCONJ", "SCONJ") and "VerbForm=Fin" not in t[3]
        return False

    def _noun_follows(self, toks, i, allow_adv=True):
        """A noun (or a capitalised nominalised word/number) follows token i
        before the next verb, pronoun, determiner or punctuation."""
        adv_pending = False
        for t in toks[i + 1:i + 6]:
            if t[2] in ("NOUN", "PROPN", "NUM") or (t[0][:1].isupper() and t[2] in ("ADJ", "VERB", "X")):
                return not adv_pending      # "das wirklich Zufall": an adverb needs an adjective after it
            if t[2] == "ADJ" and "Tag=ADJD" not in t[3]:
                adv_pending = False           # attributive (inflected, ADJA)
            elif t[2] in ("ADV", "PART") and allow_adv:
                adv_pending = True
            else:
                return False
        return False

    def _participle(self, toks, i, low, r):
        """A past participle: the verb Wiktionary lists it as the participle
        of (gehört -> hören, not gehören); after sein with no other verb in
        the clause a lexicalised participle adjective (ist ausgezeichnet ->
        ausgezeichnet "excellent") is the adjective."""
        lx = self._lex
        targets = self._participle_targets(low)
        after_sein = any(t[2] == "AUX" and t[1].lower() == "sein" for t in toks[max(0, i - 6):i])
        if after_sein and lx.usable_entries(low, ["adj"]) and not any(
                self.sein_perfect(t) for t in targets):
            return (low, "ADJ")
        if len(targets) > 1 or (targets and r[0] not in targets):
            # gehört is the participle of hören (ge- + hört) and of gehören
            # (inseparable ge-, no extra ge-): a ge- participle is the verb
            # without the inseparable prefix
            aux = self._clause_aux_verb(toks, i)
            if len(targets) > 1 and aux:
                # hat gefallen -> gefallen (haben), ist gefallen -> fallen (sein),
                # hat geraten -> raten, ist geraten -> geraten
                match = [t for t in targets if aux in self._verb_aux(t)]
                if match:
                    targets = match
            if len(targets) > 1 and low.startswith("ge"):
                plain = [t for t in targets if not t.startswith(INSEP_PREFIXES)]
                if plain:
                    targets = plain
            return (lx.best_by_freq(targets), "VERB")
        return r

    def _verb_aux(self, v):
        """Perfect auxiliaries Wiktionary lists for a verb: {"haben"}, {"sein"} or both."""
        for e in self._lex.E.get(v, []):
            g = str(e.get("g", ""))
            if e["p"] == "verb" and g.startswith("v|") and len(g.split("|")) > 3 and g.split("|")[3]:
                return set(g.split("|")[3].split("+"))
        return {"sein"} if v in SEIN_VERBS else {"haben"}

    def _clause_aux_verb(self, toks, i):
        """haben or sein when that auxiliary is in token i's clause, else None."""
        a = i
        while a > 0 and toks[a - 1][0] not in (",", ";", ".", "!", "?"):
            a -= 1
        b = i
        while b + 1 < len(toks) and toks[b + 1][0] not in (",", ";", ".", "!", "?"):
            b += 1
        found = {t[1].lower() for t in toks[a:b + 1] if t[2] == "AUX"} & {"haben", "sein"}
        return found.pop() if len(found) == 1 else None

    def _clause_aux(self, toks, i):
        """An auxiliary in token i's comma-bounded clause."""
        a = i
        while a > 0 and toks[a - 1][0] not in (",", ";", ".", "!", "?"):
            a -= 1
        b = i
        while b + 1 < len(toks) and toks[b + 1][0] not in (",", ";", ".", "!", "?"):
            b += 1
        return any(t[2] == "AUX" for t in toks[a:b + 1])

    def _participle_targets(self, low):
        lx = self._lex
        targets = sorted({self.fold(m.group(1)) for e in lx.E.get(low, []) if e["p"] == "verb"
                          for sn in e["s"] if sn[3] == "form" for m in [PARTICIPLE_OF_RE.search(sn[0])] if m})
        out = [t for t in targets if lx.usable_entries(t, ["verb"])]
        # a ge-/be- verb whose participle is its own infinitive (geraten, gefallen, bekommen)
        if low not in out and any(e["p"] == "verb" and str(e.get("g", "")).startswith("v|") and
                                  str(e.get("g", "")).split("|")[2:3] == [low]
                                  for e in lx.usable_entries(low, ["verb"])):
            out = sorted(out + [low])
        return out

    def sein_perfect(self, verb):
        """Verbs whose Perfekt takes sein (motion/change of state): after sein
        their participle is the verb, not an adjective."""
        return verb in SEIN_VERBS or (self._lex is not None and "sein" in self._verb_aux(verb))

    # ---- sentences ------------------------------------------------------------
    def marks_sentence(self, toks):
        """Präteritum other than sein/haben/modals, and the past subjunctive
        (hätte ... gemacht, hätte ... sollen; not the polite hätte gern):
        kept to B1 sentences."""
        subj = any(t[0].lower().startswith(("hätte", "wäre", "wär")) for t in toks)
        if subj and any("VerbForm=Part" in t[3] or (self._lex is not None and self._final_participle(toks, i, t[0].lower()))
                        or (t[1].lower() in MODAL_INF and i and "VerbForm=Inf" in toks[i - 1][3])
                        for i, t in enumerate(toks)):
            return True                   # hätte ... kommen sollen, hätten ... gehört
        for text, sl, upos, ms in toks:
            if upos in ("VERB", "AUX") and "Tense=Past" in ms and "VerbForm=Fin" in ms and "Mood=Sub" not in ms:
                if sl.lower() in ALLOWED_PAST or ALLOWED_PAST_RE.match(text.lower()):
                    continue
                return True
        return False

    # ---- nouns / articles ----------------------------------------------------
    def gender_from_entry(self, d):
        """'<gender>|<plural>' for a de-noun head: gender m/f/n/mf/p from the
        expansion ("Tisch m (strong, ... plural Tische)"), mf for adjectival
        nouns with a masculine form (der/die Angestellte); plural from the
        form tagged exactly ["plural"], "-" when the noun has none."""
        if d.get("pos") == "verb" and any(h.get("name") == "de-verb" for h in d.get("head_templates", [])):
            # principal parts, kept for verb commonness (see verb_score)
            forms = d.get("forms", [])
            pret = next((f["form"] for f in forms if f.get("tags") == ["past"]), "")
            pp = next((f["form"] for f in forms if f.get("tags") == ["participle", "past"]), "")
            aux = "+".join(sorted({f["form"] for f in forms if f.get("tags") == ["auxiliary"]}))
            return f"v|{pret.split(' ')[0]}|{pp}|{aux}"
        for ht in d.get("head_templates", []):
            if ht.get("name") != self.noun_head_template:
                continue
            a = ht.get("args", {})
            a1 = str(a.get("1", ""))
            m = EXPANSION_G_RE.match(ht.get("expansion", ""))
            g = m.group(1) if m else None
            if g is None:
                tags = {t for s in d.get("senses", []) for t in s.get("tags", [])}
                g = "m" if "masculine" in tags else "f" if "feminine" in tags else "n" if "neuter" in tags else None
            bare = ""
            forms = d.get("forms", [])
            if g == "pl" or a1[:1] == "p" or a1[:2] in ("mp", "fp", "np"):
                g = "p"
            elif a1.startswith("+"):
                # adjectival noun (der Beamte / die Angestellte): the headword is
                # the strong form (Beamter); show the weak form after der/die
                dn = next((f.get("form") for f in forms if f.get("tags") == ["definite", "nominative"]), "")
                bare = dn.split(" ", 1)[1] if " " in dn else ""
                if a.get("m") or a.get("f"):
                    g = "mf"
            if g is None:
                return None
            pl = next((f.get("form") for f in forms if f.get("tags") == ["plural"]), None)
            if pl is None:
                # a qualified plural ("plural (rare) Sporte", "(sorts of tea) Tees")
                # or only the declension table: the nominative plural
                cases = {"nominative", "genitive", "dative", "accusative"}
                pl = next((f.get("form") for f in forms if "plural" in f.get("tags", [])
                           and not cases & set(f.get("tags", []))), None) or \
                    next((f.get("form") for f in forms if {"nominative", "plural"} <= set(f.get("tags", []))), None)
                if pl and " " in pl and pl.split(" ", 1)[0] in ("die", "der", "das"):
                    pl = pl.split(" ", 1)[1]
            if bare:
                pl = next((f.get("form") for f in forms if f.get("tags") == ["definite", "plural"]), pl)
            if pl is None and (".sg" in a1 or any("no-plural" in s.get("tags", []) for s in d.get("senses", []))):
                pl = "-"
            # qualifiers of a declension/gender variant ("(less common) Märzes",
            # an obsolete weak declension as a second head) are copied onto
            # every sense by kaikki; as <...> header tags the core ignores them
            quals = set(re.findall(r"[a-z-]+", " ".join(QUAL_RE.findall(" ".join(str(v) for v in a.values())))))
            if sum(1 for h in d.get("head_templates", []) if h.get("name") == self.noun_head_template) > 1:
                quals |= {"obsolete", "archaic", "dated", "rare"}
            head = f"<{' '.join(sorted(quals))}>" if quals else ""
            return f"{g}|{pl or ''}|{bare}|{head}"
        return None

    def parse_gender(self, g):
        if not g:
            return None, False
        gg = str(g).split("|")[0]
        if gg == "p":
            return "p", True
        return (gg if gg in ("m", "f", "n", "mf") else None), False

    def plural_of(self, g):
        parts = str(g or "").split("|")
        return parts[1] if len(parts) > 1 else ""

    def bare_of(self, g, lemma):
        """Displayed noun: the weak form for adjectival nouns, else the lemma."""
        parts = str(g or "").split("|")
        return parts[2] if len(parts) > 2 and parts[2] else cap(lemma)

    def default_gender(self, lemma):
        if lemma.endswith(("ung", "heit", "keit", "schaft", "ion", "tät", "ik", "ei", "in", "ur")):
            return "f"
        if lemma.endswith(("chen", "lein", "ment", "um", "tum")):
            return "n"
        return "m"

    def noun_display(self, lemma, gender, plural, en):
        c = cap(lemma)
        if plural or gender == "p":
            return f"die {c}", en
        art = {"m": "der", "f": "die", "n": "das", "mf": "der/die"}.get(gender, "der")
        return f"{art} {c}", en

    def check_word(self, w):
        """A noun is shown as der/die/das (der/die for common-gender
        adjectival nouns) + the capitalised lemma, with alt[0] the bare noun."""
        wid = w["id"]
        if w.get("pos") != "noun":
            lem = w["lemma"]
            if w.get("pos") not in ("phrase", "intj") and lem != "Sie" and lem != lem.lower():
                return f"word {wid} {w['w']!r}: non-noun lemma {lem!r} is capitalised"
            return None
        m = re.fullmatch(r"(der|die|das|der/die) (\S+)", w["w"])
        if not m:
            return f"noun {wid} {w['w']!r}: not '<der|die|das> Noun'"
        bare = m.group(2)
        if not bare[:1].isupper():
            return f"noun {wid} {w['w']!r}: noun not capitalised"
        if not w.get("alt") or w["alt"][0] != bare:
            return f"noun {wid} {w['w']!r}: alt[0] must be the bare noun {bare!r}"
        if w["lemma"] != bare:
            return f"noun {wid} {w['w']!r}: lemma {w['lemma']!r} != displayed noun"
        return None

    def _rare_plural(self, ctx, key, pl):
        """A plural Wiktionary lists but nobody uses: rare in wordfreq, or (when
        the plural spelling is also a verb form, "ich blute") next to never
        read as the noun in the corpus while the singular is common."""
        lx, surf = ctx["lexicon"], ctx.get("surf", {})
        lem = key[0]
        fp = self.fold(pl)
        zp, zs = lx.zipf(fp), lx.zipf(lem)
        if zp < RARE_PLURAL_ZIPF and zp < zs - 1.5:
            return True
        if zp >= RARE_PLURAL_HOMOGRAPH_ZIPF or not any(e["p"] != "noun" for e in lx.E.get(fp, [])):
            return False
        # the plural spelling is also another word's form (Blute = ich blute),
        # so its wordfreq count is no evidence: the corpus must show the noun
        sg = surf.get(lem, {}).get(key, 0)
        pc = surf.get(fp, {}).get(key, 0) + (surf.get(fp + "n", {}).get(key, 0) if not fp.endswith("n") else 0)
        self.plural_debug.append((lem, pl, round(zs, 2), round(zp, 2), sg, pc))
        return sg >= RARE_PLURAL_MIN_SG and pc * RARE_PLURAL_SHARE < sg

    # ---- finishing -------------------------------------------------------------
    def finalize_words(self, env, ctx, words):
        """Display case (nouns, Sie, Entschuldigung, phrases), noun gender
        with neuter from the corpus when Wiktionary gives none, the plural
        line in pron, and ae/oe/ue/ss spellings as alts at the lenient levels."""
        lx = ctx["lexicon"]
        morph = ctx["morph"]
        strict = self.typing.get("strictFromLevel")
        levels = self.level_ids
        lenient = set(levels[:levels.index(strict)]) if strict in levels else set(levels)
        phrase_disp = {p.lower(): p for p in PHRASES}
        import json as _json
        # the core's id-map key ("haus|noun"), before display case changes the
        # lemma: tools/id_map_v1.json is frozen from this file
        (env.derived / "de_idkeys.json").write_text(_json.dumps(
            {f"{w['lemma']}|{w['pos']}": w["id"] for w in words}, ensure_ascii=False, indent=0, sort_keys=True))
        for w in words:
            lem, g = w["_key"]
            if g == "NOUN":
                ents = [e for e in lx.usable_entries(lem, ["noun"]) if e.get("g")]
                gender = w.get("_gender")
                ent = next((e for e in ents if self.parse_gender(e["g"])[0] == gender), ents[0] if ents else None)
                if ent is None:
                    mc = morph.get(w["_key"], {})
                    counts = {"m": mc.get("Gender=Masc", 0), "f": mc.get("Gender=Fem", 0),
                              "n": mc.get("Gender=Neut", 0)}
                    best = max(counts.values())
                    gender = max(counts, key=lambda k: (counts[k], k)) if best else self.default_gender(lem)
                    pl = ""
                    plural_only = lem in self.pluralia_tantum
                    bare = cap(lem)
                else:
                    gender, plural_only = self.parse_gender(ent["g"])
                    pl = self.plural_of(ent["g"])
                    plural_only = plural_only or lem in self.pluralia_tantum
                    bare = self.bare_of(ent["g"], lem)
                w["_gender"] = gender
                shown, _ = self.noun_display(bare.lower(), gender, plural_only, w["en"])
                shown = shown.rsplit(" ", 1)[0] + " " + bare
                w["w"], w["lemma"] = shown, bare
                w["alt"] = [bare] + [a for a in (w.get("alt") or [])[1:] if a != bare]
                pl = PLURAL_FIX.get(lem, pl)
                if pl and pl != "-" and self._rare_plural(ctx, w["_key"], pl):
                    pl = "~"                      # a technical plural (Milchen, Januare, Blute): not shown
                if plural_only:
                    w["pron"] = "pl. only"
                elif pl == "~":
                    w["pron"] = "rarely pl."
                elif pl == "-":
                    w["pron"] = "no pl."
                elif pl:
                    w["pron"] = f"pl. {pl}"
            elif lem == "entschuldigung":
                w["w"] = w["lemma"] = "Entschuldigung"
            elif g == "PHRASE" and lem in phrase_disp:
                w["w"] = w["lemma"] = phrase_disp[lem]
            if w["lv"] in lenient and w.get("pos") != "art":
                bare = (w.get("alt") or [w["w"]])[0] if g == "NOUN" else w["w"]
                t = bare.translate(TRANSLIT)
                if t != bare:
                    w["alt"] = (w.get("alt") or []) + [t]
        import json as _json
        (env.derived / "de_plural_debug.json").write_text(_json.dumps(sorted(self.plural_debug), ensure_ascii=False))
        from ..core.util import stat
        stat("separable_verbs", {**self.sep_stats, "examples_not_in_dictionary": sorted(self.sep_examples)})

    # ---- QA scans ------------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "seasons": " ".join(SEASONS),
        "num": " ".join(NUMBERS), "col": " ".join(COLOURS), "pron": " ".join(PERSONAL + POSSESSIVE),
        "question": " ".join(QUESTION_PRON + QUESTION_ADV + ["welcher"]),
        "core": "der ein und oder aber in an auf mit von zu für bei nach aus nicht kein ja nein hallo tschüss "
                "danke bitte Entschuldigung sein haben",
    }
    qa_verb_re = r"n$"
    qa_article_rules = [
        (r"^(der|das) \S*(ung|heit|keit|schaft|tät)$", "der/das + feminine suffix"),
        (r"^(der|die) \S*(chen|lein)$", "diminutive must be das"),
    ]
    qa_adj_inflected_re = r"(em|es)$"
    qa_foreign_letters_re = r"y"
    qa_proper_re = r"\b(Germany|Berlin|Austria|Vienna|Switzerland|Munich|Hamburg|Christ|God)\b"


SPEC = German
