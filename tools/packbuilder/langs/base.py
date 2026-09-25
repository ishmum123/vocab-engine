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
# Shared English half of the sensitive-content filter (spec.sensitive_re): the
# English translation is checked with it, each spec adds its own-language terms.
# Cross-pack policy: sexual content, and threats/violence, kept out of A1/A2.
SENSITIVE_EN = (r"sex|sexy|sexual\w*|rape[ds]?|raping|rapist|porn\w*|naked|nude|orgasm|condom|prostitut\w*|"
                r"suicid\w*|fuck\w*|shit\w*|bitch\w*|asshole\w*|pussy|"
                r"kill(s|ed|ing|er|ers)?|murder\w*|dead|shoot(s|ing)?|stab(s|bed|bing)?|strangl\w*|"
                r"want you dead|going to kill")
# Shared English list for the gloss-level sensitive scan (spec.sensitive_gloss_re):
# vulgar or sexual senses never lead a learner gloss (es mamar, perra). Each spec
# may add its own terms to the regex it builds from this.
SENSITIVE_GLOSS_EN = (r"fuck\w*|bullshit\w*|shit\w*|bitch\w*|asshole\w*|arsehole\w*|dick|pussy|cunt|whore\w*|"
                      r"slut\w*|bastard\w*|wank\w*|jerk off|blow ?job|fellat\w*|masturbat\w*|orgasm\w*|"
                      r"have sex|sexual intercourse|copulat\w*|screw around|fornicat\w*|vulgar|slur")
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
    # passages span alignment (passages.token_offsets): tagger surfaces may be a
    # normalised spelling of the text. span_fold(s) -> str folds surfaces and
    # the text (per word / per other character) before matching (fa: Arabic
    # yeh/kaf, hamza carriers, ZWNJ and harakat dropped); span_joiners are characters the tagger's input rewrite
    # may delete inside a token (fa: the space of "می روم"). None / "" = exact.
    # span_fold also folds a passage's declared oop lemmas and the tagger lemma
    # they are matched with (ru: артём = артем).
    span_fold = None
    span_joiners = ""
    tagger = "spacy"            # "spacy" (spacy_model) or "stanza" (stanza_lang; spec.tag_texts does the tagging)
    stanza_lang = None          # Stanza language code when tagger == "stanza" (fa)

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
    gloss_display_file = "tools/gloss_display.json"   # display-only en per "lemma|pos", applied to words.json after linking (core/words.apply_gloss_display)
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
        self.forced = list(dict.fromkeys(self.forced))   # a word listed twice must not become two words
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

    sentence_openers = ""       # characters that open a sentence before its first word (es: ¿¡)
    surface_lemma = {}          # (surface, group) -> lemma or (lemma, group), before the dictionary (es: mis -> mi)
    form_colon_translation = False   # lex: "X of Y: translation" form-of lines also give a sense
    strict_selection = False    # drop dictionary-only POS keys, single letters, rare English homographs
    phrase_bound_share = None   # drop a word when this share of its tokens sits inside a multiword phrase
    phrase_absorbs_parts = False   # links: a content word inside a matched phrase links only the phrase
    object_clitics = set()      # PRON surfaces after which a NOUN-tagged token is read as a verb
    # token-level phrase matching: every token inside a matched phrase links only
    # the phrase, and art_prep contractions are split first (es: "a pesar del" = a pesar de + el)
    phrase_token_spans = False
    prefer_headword_sentence = False   # sentence choice: the headword/alt visible first, then a 3sg present verb
    verb_homograph_ratio = 0    # >0: a form of several verbs goes by person/mood, else to a lemma this many times more used
    fallback_same_class = False  # a NOUN/ADJ-tagged token with no reading of its class falls back to nominal readings first
    fallback_rarity_margin = 0  # >0: keep the tagger lemma over a fallback reading this many zipf rarer
    derived_form_tags = set()   # lex: form-of senses with these tags are words, not inflections (es: diminutive)
    initial_noun_verb_homograph = False   # a clause-initial bare noun with a verb reading is the verb (es)
    function_lemmas = set()     # always function words, whatever the tagger said (es: vosotros tagged NOUN)
    phrase_en_cues = {}         # phrase -> English words one of which the translation must contain (es: de nada -> welcome)
    closed_surfaces = {}        # surface -> (lemma, group) whatever the tag, even PROPN (es: vosotros, conmigo)
    propn_lowercase_rescue = 0  # >0: a lemma seen lowercase mid-sentence this often is not a proper noun
    homograph_by_translation = False   # links: pick between a lemma's entries by the English translation
    homograph_cues = {}         # (lemma, pos) -> extra English cue words for homograph_by_translation
    sensitive_gloss_re = None   # a sense matching it never leads a gloss; check fails on an A1/A2 match
    sensitive_re = None         # sentences matching (text or English) are kept to the top level
    drop_all_levels = None      # sentences matching (text or English) are removed at every level (rape, child abuse)
    lower_level_gloss_re = None # a below-top-level gloss matching it keeps its clean ";"-segments or moves to the top level

    strict_pronominal_links = False  # a verb shown with its reflexive pronoun links only sentences that have it
    revert_dedupe_gloss = False     # a reverted -rsi/-se verb with the same head gloss shows it once
    lemma_tiebreak_corpus = False   # tie-break lemmas by their use in the tagged corpus, not wordfreq

    # passages only (passages.py), not the corpus build:
    truecase_after = ""         # a capitalised word right after one of these characters is truecased like a sentence start (es: «¡¿)
    truecase_after_end = ""     # ... and a capitalised word after one of these plus a space mid-text, if the lexicon reads it lowercase (es: !? in "¡Perfecto! Compro")
    surface_reading_fallback = False   # a counted token whose reading is out of pack links the most frequent other dictionary reading of its surface that is a pack word (es: leo -> leer, negra -> negro)
    passage_mode = False        # True while passages.Linker resolves a sentence (post_resolve, then passage_post_resolve): gates passage-only rules inside post_resolve (de); never set by the corpus build
    passage_particle_links = False     # a token post_resolve set to None whose lowercase surface prefixes the verb it was rejoined to counts and links as that verb (de: "steht ... auf" -> aufstehen)
    passage_lemma_alias = {}    # tagger lemma -> pack lemma for the classify lemma fallback (de: vieler -> viel, chefin -> chef)
    nouns_capitalised = False   # passages: a lowercase token's lemma fallback never lands on a noun (de: meisten is not der Meister)
    passage_form_base = False   # an unresolved counted token links the pack word it is an inflected form of (passages.Linker.form_base; fr: amie -> ami, dansé -> danser, allemande -> allemand)
    passage_feminine_suffixes = (("", "e"),)   # form_base: (masculine ending, feminine ending) pairs that make a "female equivalent" / g "m=X" entry an inflection of X
    passage_adverb_from = ()    # tagger POS whose token is relinked to the pack adverb its surface spells after spec.fold (ru: ADJ, NUM: хорошо, лучше, больше, ещё = еще)
    passage_names_never_link = False   # a capitalised token of a declared name never links and is not counted, whatever sentence_links read it as (id: "Jawa Tengah" is not tengah "middle")

    def copula_inflected(self, surface, adj):
        """After a copula, the surface is an inflected adjective form (it: fiera)."""
        return adj != surface

    def numeral_may_be_verb(self, lexicon, surface):
        """A NUM-tagged token may be re-read as a verb (it: "sei" = you are)."""
        return True

    def after_article_is_noun(self, toks, i):
        """An ADV/VERB-tagged token right after an article is a noun (it: l'ancora)."""
        return True

    def imperative_homograph(self, lexicon, lemma):
        """The noun lemma is really an imperative (it: fallo = fa' + lo)."""
        return lexicon.imperative_clitic(lemma)

    def bind_lexicon(self, lexicon):
        """Called once the Wiktionary lexicon is loaded, for rules that need it."""

    def numeral_group(self, lexicon, surface, lemma):
        """Group for a NUM-tagged token (es: ambos, medio are not cardinals)."""
        return "NUM"

    def sense_tags(self, tags):
        """Normalise a kaikki sense's tags at lex time (es: widespread regional tags dropped)."""
        return tags

    def needs_gender_evidence(self, lexicon, lemma):
        """A noun whose two genders are different words (es: el frente / la frente):
        link it only with gender evidence in the sentence."""
        return False

    def translation_mismatch(self, toks, en):
        """The English translation contradicts the sentence (es: lo vs "her")."""
        return False

    def marks_sentence(self, toks):
        """Whole-sentence marker with the same effect as a marked past: the
        sentence is kept from lower-level words and levelled at the top level
        (es: voseo, regional slang)."""
        return False

    def accent_candidates(self, s):
        """Accented spellings a frequency-list surface may stand for. Default:
        the final letter from accent_variants (it: citta -> città)."""
        av = self.accent_variants
        if s[-1:] not in av:
            return []
        return [s[:-1] + acc for acc in av[s[-1]]]

    def clitic_stem_tries(self, stem):
        """Verb spellings to look up for a stem left after stripping enclitics."""
        return [stem]

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

    # ---- normalisation / finishing hooks (defaults are no-ops) ---------------
    morph_keep = None            # UD features kept in the tagged corpus; None = core.tag.MORPH_KEEP
    rare_zipf = None             # rare-reading override threshold; None = core.lexicon.RARE_ZIPF
    finite_verb_lemma = False     # a finite verb token keeps the tagger lemma over a same-spelling infinitive (ru: есть)
    caps_proper_pool = True       # pool: a lemma capitalised mid-sentence more often than not is a name (ru: off)
    refill_unexampled = False     # a non-forced word with no example sentence is replaced by the next-ranked word
    bare_prefer_shared = False    # example_shows_word: pick the bare-form sentence with audio / already used first
    example_shows_word = False    # sentences: one of a word's examples contains its bare lemma surface when any candidate does
    numeral_verb_rule = True     # a NUM token with no noun after it may be a verb form (it: "sei"); ru: off ("три" = тереть)

    def fold(self, s):
        """Spelling folded on every matching side: kaikki headwords and form
        targets, frequency-list surfaces (summed), wordfreq surfaces. The tagger
        side is folded by tag_text/fix_token. ru: ё -> е."""
        return s

    def fallback_lemma(self, surface, lemma):
        """simplemma's lemma for a frequency-list surface the corpus never
        shows; a spec may reject it (ru: abbreviation expansions мм -> миллиметр)."""
        return lemma

    # ---- corpus / tagger hooks (added for Persian; defaults are no-ops) --------
    min_corpus_tokens = 0        # words: a non-forced (lemma, POS) needs this many tagged-corpus tokens (fa: 3)
    untranslated_rows = False    # corpus: also tag target sentences with no English link (english ""), never shipped
    extra_corpus_files = ()      # repo-relative files read by extra_corpus_rows (part of the corpus cache key)

    def extra_corpus_rows(self, env):
        """Extra corpus rows [sid, text, user, english, audio_id, licence]
        appended after the Tatoeba rows (fa: sentences written for the pack)."""
        return []

    def sentence_fields(self, row):
        """Extra fields for the sentences.json record of a corpus row (fa: src)."""
        return {}

    def pack_json_extra(self):
        """Extra top-level keys for pack.json (script display: rtl, langTag,
        fontFamily, fonts, lineHeight, spaced; see docs/PACK_SCHEMA.md)."""
        return {}

    def extra_attribution(self, env, sentences):
        """Extra top-level keys for attribution.json."""
        return {}

    def subtitle_surface(self, w):
        """A (folded) frequency-list surface -> the surface matched against the
        corpus; None drops it (fa: colloquial میخوام -> میخواهم)."""
        return w

    def tagger_desc(self):
        """Tagger name/version for a spec with spacy_model None (part of the tag cache key)."""
        raise NotImplementedError

    def tag_texts(self, texts):
        """Non-spaCy tagging (spacy_model None): per text, a list of
        (text, lemma, upos, {feature: value}) tuples, in order."""
        raise NotImplementedError

    def extra_wordfreq(self, raw):
        """Add written-frequency surfaces wordfreq's top list lacks, in place
        ({folded surface: 10**zipf}). ru: hyphenated words (кто-то), which
        wordfreq only lists split."""

    def tag_text(self, text):
        """Sentence text as fed to the tagger (after truecasing)."""
        return text

    def setup_nlp(self, nlp):
        """Adjust the loaded spaCy pipeline before tagging, in place (fr:
        tokenizer rules for hyphenated clitics). Anything set here must be
        picklable (spacy_n_process > 1). Bump versions["tag"] when it changes."""

    def fix_token(self, tok):
        """[text, lemma, upos, morph] of one tagged token -> the stored one."""
        return tok

    caps_mark_names = True       # a capitalised non-initial token is a name (links, pool); de: off (nouns are capitalised)
    keep_unseen_keys = True      # pool keeps frequency-list lemmas never seen in the tagged corpus (POS from the dictionary); de: off

    def fix_sentence(self, toks, row, doc):
        """Tag time, whole sentence: the stored tokens (after fix_token) ->
        final stored tokens. row is the corpus row [sid, text, user, english,
        audio_id, licence]; doc the spaCy Doc (its non-space tokens align with
        toks). de: fine-tag marks (separable particles), formal Sie."""
        return toks

    def surface_link_ok(self, tok):
        """May an unresolved token fall back to linking by its surface (a
        sentence-initial pack word, an interjection)? ru: not an interjection
        homograph of a preposition/conjunction ("О нет!" is not о "about")."""
        return True

    def cross_pos_link(self, lexicon, lem, group, key_to_id):
        """Sentence linking: (lem, group) has no pack word and no same-headword
        entry -> another pack word id for this token, or None (default: no
        link). id: the lemma's only pack entry when the tagged reading's
        glosses share a word with it (semua PRON -> semua DET)."""
        return None

    def post_resolve(self, toks, out):
        """Resolve time, whole sentence: [(lemma, group) | None] per token,
        after the core context rules -> the final list (same length).
        de: rejoin separable verbs, formal Sie."""
        return out

    def passage_post_resolve(self, toks, out):
        """Like post_resolve, after it, but only in passages (passages.Linker
        wraps the lexicon's resolve_sentence); the corpus build never calls
        it, so a rule can be tried on passages before it changes sentence
        links. es: fue/fui/fuera."""
        return out

    def passage_retag(self, toks):
        """Passages only: rewrite the tagged [text, lemma, upos, morph] tokens
        (list copies, declared names already PROPN) before linking; the corpus
        build never calls it. ru: correlative Тому, кто; стоит/стоять;
        capitalised Новый год; меньше. fr: X-tagged words get their dictionary
        class; a lowercase PROPN/ADJ/NOUN with a verb reading right after a
        subject pronoun is handed to post_resolve as a noun (je bois)."""
        return toks

    def passage_text(self, text, names, lexicon):
        """Passages only: the truecased text -> the text the tagger sees
        (same length not required; spans align on the original text).
        `names`: the passage's declared name words. fr: capitalised common
        words (Madame, un Espagnol, « Les ») lowercased."""
        return text

    def passage_fallback_ok(self, lexicon, reading, word, en=""):
        """Passages only: may a token whose reading (lemma, group) has no pack
        key link `word` (the pack record of the same lemma under another POS)?
        `en`: the sentence's English, "" for questions and options. fr: la
        ferme "farm" is not ferme "firm"."""
        return True

    def passage_phrase_ranges(self, toks):
        """Passages only: [(first, last, anchor)] token ranges of multiword
        expressions resolved on one anchor token: the other parts read as
        the expression and one span covers the range. fr: MWES (parce qu',
        est-ce qu', au lieu du, d'abord, il y avait)."""
        return []

    def passage_no_link(self, toks):
        """Passages only: token indices that link nothing (they stay counted
        by their reading). ru: друг другу (each other, not friend)."""
        return set()

    def sentence_rank(self, toks, lv):
        """Sort penalty for an example sentence of a word at level lv (lower is
        preferred), applied after the "no higher-level words" key. ru: A1
        prefers sentences whose nouns are Nom/Acc only."""
        return 0

    def shares_gloss(self, lemma, other):
        """Two lemmas may lead with the same English word (the gloss-collision
        rule leaves them alone). ru: aspect partners (читать / прочитать)."""
        return False

    def finalize_words(self, env, ctx, words):
        """Last pass over the built word list (after sentences), in place: display
        spelling, pron, gloss suffixes. May set word["pron"]."""
        return None

    # ---- added for Indonesian (defaults are no-ops) ----------------------------
    audio_rank_bonus = 0         # sentences: a sentence with native audio has its sentence_rank penalty lowered by this
    use_audio = True             # corpus: attach permissive Tatoeba audio (id: off, TTS only)
    corpus_rank_weight = 0       # >0: the tagged corpus's (lemma, POS) counts join the frequency blend
    level_floor = {}             # (lemma, group) -> lowest level it may take (id: colloquial words A2+)
    keep_keys = frozenset()      # (lemma, group) kept in the word list even when ranked past the cut
    level_ceiling = {}           # (lemma, group) -> highest level it may take (ko: NIKL beginner words <= A2)

    # ---- added for Japanese (defaults keep every other language unchanged) ------
    spoken_from_corpus = False   # freq: the tagged corpus's (lemma, POS) counts are the spoken list; subtitles_file is not read (ja: hermitdave list unusable)
    spoken_freq_label = None     # REPORT.md label of the spoken-list row (None: the subtitle list's)
    use_simplemma = True         # freq: simplemma fallback lemma for surfaces unseen in the corpus (ja: unsupported, the surface is kept)
    sentence_end_re = None       # sentences: regex a usable sentence must match at its end (None: core SENT_END_RE; ja adds 。！？)

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
