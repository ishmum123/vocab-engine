"""LanguageSpec: everything the language-agnostic core needs to know about one
language. A new language subclasses LanguageSpec in langs/<code>.py and
overrides what differs; see packbuilder/README.md "Adding a language".

Class attributes are static language facts. `load(repo)` reads the data files
the language repo owns (gloss overrides, A1 core list, frozen id map).
"""
import json
import re
from pathlib import Path

# Tatoeba exports shared by every language (file names are part of the corpus
# cache key, so keep them stable).
TATOEBA_ENG = ("eng_sentences.tsv.bz2", "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2")
TATOEBA_LINKS = ("links.tar.bz2", "https://downloads.tatoeba.org/exports/links.tar.bz2")
TATOEBA_AUDIO = ("audio.tar.bz2", "https://downloads.tatoeba.org/exports/sentences_with_audio.tar.bz2")

# UD (corpus) POS -> Wiktionary POS headers, in preference order. The first is
# the direct match; the rest cover convention differences between UD and
# Wiktionary (UD ADJ altro/stesso = Wiktionary det; UD ADV però = conj; UD NOUN
# milione = num). Override per language if its conventions differ.
DEFAULT_GROUP_KPOS = {
    "NOUN": ["noun", "num"], "PROPN": ["name", "noun"], "VERB": ["verb"], "ADJ": ["adj", "det", "num"],
    "ADV": ["adv", "conj", "prep"], "DET": ["article", "det", "adj", "pron", "num"],
    "ADP": ["prep", "adv", "conj"], "PRON": ["pron", "det"], "CONJ": ["conj", "adv"],
    "NUM": ["num", "adj", "noun"],
    "INTJ": ["intj", "particle"], "PART": ["particle", "adv"],
}


class LanguageSpec:
    # ---- identity -------------------------------------------------------
    code = None                 # pack key and wordfreq/simplemma/kaikki language code
    name_en = None              # "Italian"
    pack_name = None            # "Italian (A1–B1)"
    tts = None                  # BCP-47, "it-IT"
    stt = None
    tts_rate = 0.9
    wordfreq_code = None        # defaults to code
    simplemma_code = None       # defaults to code
    kaikki_lang_code = None     # defaults to code
    tatoeba_code = None         # ISO 639-3, "ita"

    # ---- tagger -----------------------------------------------------------
    spacy_model = None          # "it_core_news_sm"
    spacy_n_process = 6
    tagger_attribution = None   # dict written to attribution.json["tagger"]

    # ---- sources (file name in .cache/ -> url). Roles name the files the
    # stages read; file names are part of the cache keys.
    sources = {}
    subtitles_file = None       # hermitdave FrequencyWords <code>_full.txt
    kaikki_file = None          # kaikki.org jsonl.gz (decompressed next to it)
    sentences_file = None       # Tatoeba <iso3>_sentences_detailed.tsv.bz2
    eng_file = TATOEBA_ENG[0]
    links_file = TATOEBA_LINKS[0]
    audio_file = TATOEBA_AUDIO[0]
    kelly_file = None           # optional CEFR cross-check list (never shipped)

    # ---- cache versions: bump when the stage's code or this language's rules
    # for that stage change (the old cache file is then ignored).
    versions = {"corpus": "c1", "tag": "t1", "lex": "l1"}

    # ---- levels / pack.json -------------------------------------------------
    bands = [("A1", 600), ("A2", 700), ("B1", 700)]
    placement = [["A1", 4], ["A2", 4], ["B1", 4]]
    set_size = 10
    typing = {"caseSensitive": False, "accents": "lenient", "strictFromLevel": "B1"}
    show_pron = False
    has_lessons = False
    target_len = {"A1": 5, "A2": 7, "B1": 8}     # preferred sentence length per level
    min_len = {"A1": 4, "A2": 4, "B1": 5}
    max_len = 14

    # ---- orthography (regexes over lowercase text) --------------------------
    word_re = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")                 # a word in raw text
    lex_word_re = re.compile(r"^[a-z']+$")                       # a usable Wiktionary headword
    sub_token_re = re.compile(r"^[a-z]+'?$")                     # a usable frequency-list surface
    form_target_re = re.compile(r"\bof ([a-z']+)")               # "... of <lemma>" in a form-of gloss
    fem_of_re = re.compile(r"(?:female equivalent|(?:singular )?feminine(?: singular)?) of ([a-z]+)")
    accent_variants = {}        # unaccented final letter -> accented letters (subtitles drop accents)

    # ---- Wiktionary --------------------------------------------------------
    noun_head_template = None   # kaikki head template carrying noun gender ("it-noun")
    regional_tags = set()       # kaikki region tags that mark a sense as non-standard
    group_kpos = DEFAULT_GROUP_KPOS

    # ---- morphology / resolution tables (empty = rule off) ------------------
    clitic_re = None            # verb+enclitic surface splitter
    art_prep = {}               # articulated preposition surface -> preposition
    article_forms = {}          # article lemma -> its surface forms
    definite_article = None     # key of article_forms for the definite article
    pluralia_tantum = set()
    copulas = set()
    refl_clitics = {}           # clitic -> (Person, Number|None)
    clitic_of = {}              # clitic pronoun -> its full pronoun lemma
    mono_imperative = {}        # monosyllabic imperative -> verb
    verb_endings = None         # infinitive endings; None = any lemma can be a verb
    function_verbs = set()      # verbs kept in functionWords (essere, avere)

    # ---- forced items / hand tables ------------------------------------------
    forced_closed = []          # [(lemma, group)] closed sets forced into A1
    no_article = set()          # nouns shown bare (days, months)
    allowed_num = set()         # numerals allowed as words
    fixed_gloss = {}            # (lemma, group) -> gloss
    fixed_word = {}             # (lemma, group) -> (w, alt list), pos "art"
    multiword = {}              # phrase -> parts; linked by substring
    apocope = {}                # apocopated surface -> lemma (links only)
    drop_keys = {}              # (lemma, group) -> None | key its tokens link to
    profanity = set()
    profane_stems = ()
    bad_text_re = None          # target-language sentences to skip (known errors)

    # ---- language repo data files (repo-relative) ---------------------------
    gloss_overrides_file = "tools/gloss_overrides.json"
    forced_a1_file = "tools/forced_a1.txt"
    id_map_file = "tools/id_map_v1.json"
    report_file = "tools/REPORT.md"

    # ---- report wording -----------------------------------------------------
    report_title = None
    forced_description = "closed sets, A1 core list"
    numeral_exclusion = "numeral outside the allowed set"
    article_pool_note = ""
    marked_past_name = None     # "Passato remoto": literary past kept to B1

    def __init__(self, repo=None):
        self.repo = Path(repo).resolve() if repo else None
        self.wordfreq_code = self.wordfreq_code or self.code
        self.simplemma_code = self.simplemma_code or self.code
        self.kaikki_lang_code = self.kaikki_lang_code or self.code
        self.all_article_forms = set().union(*self.article_forms.values()) if self.article_forms else set()
        self.gloss_overrides = {}
        self.a1_core = {}
        self.forced = list(self.forced_closed)

    # ------------------------------------------------------------------
    def load(self):
        """Read the language repo's data files. Needs self.repo."""
        p = self.repo / self.gloss_overrides_file
        if p.exists():
            self.gloss_overrides = {k: v for k, v in json.loads(p.read_text()).items()
                                    if not k.startswith("_")}
        p = self.repo / self.forced_a1_file
        if p.exists():
            self.a1_core = parse_forced_file(p.read_text())
        self.forced = list(self.forced_closed) + [(w, g) for g, ws in self.a1_core.items() for w in ws]
        return self

    @property
    def n_words(self):
        return sum(n for _, n in self.bands)

    @property
    def level_ids(self):
        return [b[0] for b in self.bands]

    # ---- hooks: orthography / morphology -------------------------------------
    def is_verb_lemma(self, w):
        return self.verb_endings is None or w.endswith(self.verb_endings)

    def is_profane(self, w):
        return w in self.profanity or (bool(self.profane_stems) and w.startswith(self.profane_stems))

    def pronominal_base(self, lemma):
        """Base verb of a pronominal lemma (farsi -> fare), else None."""
        return None

    def pronominal_form(self, lemma):
        """Pronominal display form of a verb (lamentare -> lamentarsi), else None."""
        return None

    def is_reflexive(self, toks, i):
        """Strict: the verb token i carries a reflexive clitic in its own person."""
        return False

    def carries_refl_clitic(self, toks, i):
        """Lenient reflexive check used by the linked-sentence -rsi gate."""
        return False

    def stative_aux(self, toks, i):
        """Participle i is a stative/passive use (essere + participle)."""
        return False

    def is_marked_past(self, ms):
        """Token morph is a literary past tense kept out of A1/A2 sentences."""
        return False

    uses_historic_past_forms = False   # also flag Wiktionary "historic past" forms

    def gender_from_entry(self, d):
        """Gender spec string from a kaikki entry's head templates."""
        g = None
        for ht in d.get("head_templates", []):
            a = ht.get("args", {})
            if self.noun_head_template and ht.get("name") == self.noun_head_template:
                g = a.get("1")
            elif ht.get("name") == "head":
                g = a.get("g")
            if g:
                break
        return g

    def parse_gender(self, g):
        return parse_gender(g)

    def default_gender(self, lemma):
        return "m"

    def noun_display(self, lemma, gender, plural, en):
        """(w, en) for a noun: the displayed form (with article) and gloss."""
        return lemma, en

    def clean_sentence_text(self, t):
        return t

    def check_word(self, w):
        """Language-specific pack assertion on one word; error string or None."""
        return None

    # ---- QA scan config ---------------------------------------------------
    qa_closed_sets = {}          # name -> space-separated lemmas that must be A1
    qa_verb_re = None            # regex a verb lemma must match
    qa_article_rules = []        # [(regex over a noun's w, message)] flagged when matching
    qa_adj_inflected_re = None   # adjective lemma that looks inflected (it: -a/-i/-he)
    qa_foreign_letters_re = None # letters that mark a loanword (it: w k y j x)
    qa_proper_re = None          # gloss words that betray a proper noun (place names...)
    qa_clitic_verb_re = None     # verb lemma with an enclitic still attached
    qa_clitic_cluster_re = None  # a bare clitic cluster as a word (it: glielo)
    qa_plural_article_re = None  # noun displayed with a plural article


def parse_gender(g):
    """Wiktionary gender spec -> ('m'|'f'|'mf'|None, plural_only). Qualified
    alternatives such as 'f,m<l:archaic>' keep only the unqualified gender."""
    if not g:
        return None, False
    specs = [x for x in str(g).split(",") if x and "<" not in x] or [str(g).split("<")[0]]
    g = ",".join(specs).replace("bysense", "")
    plural = "-p" in g or (g.endswith("p") and g not in ("m", "f"))
    has_m, has_f = "m" in g, "f" in g
    if has_m and has_f:
        return "mf", plural
    return ("m" if has_m else "f" if has_f else None), plural


def parse_forced_file(text):
    """'[NOUN]\\nword word\\n[VERB]\\n...' -> {"NOUN": [...], ...}, order kept.
    '#' starts a comment."""
    out, cur = {}, None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[([A-Z]+)\]", line)
        if m:
            cur = out.setdefault(m.group(1), [])
            continue
        if cur is None:
            raise ValueError(f"forced list: words before a [GROUP] header: {line!r}")
        cur.extend(line.split())
    return out
