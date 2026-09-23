"""Spanish (es): everything Spanish-specific in the pack pipeline.

Ported from langs/it.py where the rule is analogous (articles, clitics,
pronominal verbs, apocopes, accent-split surfaces). The A1 core list, gloss
overrides and (after first publish) the frozen id map live in the spanish
repo's tools/.
"""
import re

from .base import LanguageSpec, SENSITIVE_EN, TATOEBA_ENG, TATOEBA_AUDIO

VOWELS = "aeiouáéíóúü"
STRONG = "aeoáéó"
ACCENTED = "áéíóú"

DAYS = "lunes martes miércoles jueves viernes sábado domingo".split()
MONTHS = ("enero febrero marzo abril mayo junio julio agosto septiembre octubre "
          "noviembre diciembre").split()
SEASONS = "primavera verano otoño invierno".split()
NUMBERS = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
           "dieciséis diecisiete dieciocho diecinueve veinte treinta cuarenta cincuenta sesenta setenta "
           "ochenta noventa cien ciento mil").split()
COLOURS = "rojo azul verde amarillo negro blanco gris marrón rosa naranja morado".split()
NATIONALITIES = "español inglés francés alemán italiano americano mexicano".split()

# object/reflexive clitics and subject pronouns are their own lemmas: spaCy's
# es lemmatiser folds them all into yo/tú/él ("me" -> yo, "ella"/"les" -> él)
OWN_PRONOUNS = ("yo tú él ella ello nosotros nosotras vosotros vosotras ellos ellas usted ustedes "
                "me te se nos os lo la los las le les mí ti sí conmigo contigo consigo").split()

# closed paradigms forced into A1 whatever their corpus rank
PERSONAL = ("yo tú él ella ello nosotros nosotras vosotros vosotras ellos ellas usted ustedes "
            "me te se nos os lo la le les mí ti conmigo contigo").split()
POSSESSIVE = "mi tu su nuestro vuestro".split()
DEMONSTRATIVE = [("este", "DET"), ("ese", "DET"), ("aquel", "DET"), ("esto", "PRON"), ("eso", "PRON"),
                 ("aquello", "PRON")]
# fixed expressions taught as phrases (links: every token inside one links only the phrase)
PHRASES = ("sin embargo", "por supuesto", "de repente", "a través de", "a menudo", "de hecho", "a pesar de",
           "acerca de", "tal vez", "de acuerdo", "sobre todo", "por fin", "a veces", "de nuevo",
           "muchas gracias", "de nada", "por cierto", "a lo mejor", "en serio", "en absoluto")

# sensitive topics kept out of A1/A2 sentences (Spanish text or English translation)
SENSITIVE_RE = re.compile(
    r"\b(sexo|sexual\w*|sexy|suicid\w*|violar|violó|violación|violada|violado|porno\w*|desnud\w*|"
    r"prostitut\w*|orgasmo|condón|preservativo|"
    # threats and violence (cross-pack policy): matar in any form, asesinar,
    # disparar, "estás muerto", "te quiero muerto"
    r"mat(ar|o|as|a|amos|áis|an|é|aste|ó|asteis|aron|e|es|emos|en|ando|ado|ada|ados|adas|aba\w*|ar[éá]\w*|"
    r"aría\w*|ara\w*|ase\w*)(me|te|lo|la|le|nos|os|los|las|les)?|"
    r"asesin\w*|dispar\w*|(estás|eres) muert[oa]s?|te quiero muert[oa]|"
    + SENSITIVE_EN + r")\b", re.I)

# unaccented spellings a frequency list may use for an accented word
ACCENT_PAIRS = {"si": ["sí"], "el": ["él"], "tu": ["tú"], "mi": ["mí"], "se": ["sé"], "mas": ["más"],
                "que": ["qué"], "como": ["cómo"], "cuando": ["cuándo"], "donde": ["dónde"],
                "solo": ["sólo"], "te": ["té"], "de": ["dé"], "aun": ["aún"], "quien": ["quién"],
                "cual": ["cuál"], "cuanto": ["cuánto"], "esta": ["está"], "este": ["esté"]}

# enclitic hosts: infinitive, gerund, or an imperative (accented when a clitic
# shifts the stress: cómpralo, dímelo; monosyllabic otherwise: dime, hazlo)
MONO_IMPERATIVES = {"di", "haz", "pon", "ten", "ven", "sal", "ve", "da", "se", "sé", "oye", "mira"}

# voseo pronoun and regional slang: sentences kept from A1/A2 words (voseo
# verb forms are found from Wiktionary's "voseo" form-of tags)
MARKED_TOKENS = {"vos", "che", "boludo", "boluda", "boludos", "pibe", "piba", "pibes", "laburo", "laburar",
                 "guita", "chamba", "chido", "chida", "güey", "wey", "neta", "cachai", "bacán", "chaval",
                 "chavala", "chavales", "flipar", "mola", "molan", "tronco", "órale", "ándale", "pinche"}

PARTICIPLE_RE = re.compile(r"(ado|ido|ído|to|so|cho)$")
IR_SER_PRETERITE = {"fui", "fuiste", "fue", "fuimos", "fuisteis", "fueron"}

REGIONAL = {"Rioplatense", "Argentina", "Uruguay", "Paraguay", "Chile", "Bolivia", "Peru", "Ecuador",
            "Colombia", "Venezuela", "Mexico", "Central-America", "Guatemala", "Honduras", "El-Salvador",
            "Nicaragua", "Costa-Rica", "Panama", "Caribbean", "Cuba", "Puerto-Rico", "Dominican-Republic",
            "Canary-Islands", "Andalusia", "Philippines", "Equatorial-Guinea", "Aragon", "Murcia",
            "Galicia", "Asturias", "Navarre", "Leon", "Extremadura", "Cantabria", "Basque-Country"}


def _strip_acute(s):
    return s.translate(str.maketrans("áéíóú", "aeiou"))


def syllables(w):
    """Vowel nuclei: diphthongs (a weak unaccented i/u next to a vowel) count
    once; two strong vowels or an accented i/u are a hiatus."""
    n, prev = 0, ""
    for c in w:
        if c in VOWELS:
            if prev in VOWELS and not (prev in STRONG and c in STRONG) and c not in "íú" and prev not in "íú":
                pass                       # diphthong (or silent u in que/gue): same nucleus
            else:
                n += 1
        prev = c
    return n


def stressed_initial_a(lemma):
    """Feminine nouns starting with a stressed a-/ha- take el in the singular
    (el agua, el hambre, el aula; but la abeja, la amiga)."""
    w = lemma[1:] if lemma.startswith("h") else lemma
    if not w or w[0] not in "aá":
        return False
    if w[0] == "á":
        return True
    if any(c in ACCENTED for c in lemma):
        return False                       # written stress elsewhere
    n = syllables(lemma)
    if lemma[-1] in "aeiouns":
        return n <= 2                      # penultimate stress: first syllable when 2 syllables
    return n == 1                          # final stress


class Spanish(LanguageSpec):
    code = "es"
    name_en = "Spanish"
    pack_name = "Spanish (A1–B1)"
    tts = "es-ES"
    stt = "es-ES"
    tatoeba_code = "spa"

    spacy_model = "es_core_news_sm"
    tagger_attribution = {
        "source": "spaCy (MIT) + es_core_news_sm model (GNU GPL 3.0, trained on UD Spanish AnCora and WikiNER)",
        "licence": "GNU GPL 3.0 (model)",
        "note": "Used at build time only; the pack ships no model files.",
    }

    subtitles_file = "es_full.txt"
    kaikki_file = "kaikki_es.jsonl.gz"
    sentences_file = "spa_detailed.tsv.bz2"
    links_file = "spa-eng_links.tsv.bz2"
    sources = {
        "es_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/es/es_full.txt",
        "kaikki_es.jsonl.gz": "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl.gz",
        "spa_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/spa/spa_sentences_detailed.tsv.bz2",
        "spa-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/spa/spa-eng_links.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    # t2: ¿¡ openers; l2: colon translations; l3: widespread regional senses are standard;
    # l4: diminutives are not inflections
    versions = {"corpus": "c1", "tag": "t2", "lex": "l4"}
    derived_form_tags = {"diminutive", "augmentative", "pejorative", "endearing"}
    form_colon_translation = True

    lex_word_re = re.compile(r"^[a-záéíóúüñ]+$")
    sub_token_re = re.compile(r"^[a-záéíóúüñ]+$")
    form_target_re = re.compile(r"\bof ([a-záéíóúüñ]+)")
    fem_of_re = re.compile(r"(?:female equivalent|(?:singular )?feminine(?: singular)?) of ([a-záéíóúüñ]+)")

    sentence_openers = "¿¡"
    strict_selection = True
    phrase_token_spans = True
    initial_noun_verb_homograph = True
    prefer_headword_sentence = True
    fallback_rarity_margin = 1.5
    propn_lowercase_rescue = 10      # tierra, dios, reino, vía: common nouns as well as names
    homograph_by_translation = True
    homograph_cues = {("solo", "adv"): ("only", "just", "merely", "simply", "solely"),
                      ("solo", "adj"): ("alone", "lonely", "lone", "single", "own", "oneself"),
                      ("bajo", "adj"): ("low", "short"), ("bajo", "prep"): ("under", "below", "beneath")}
    sensitive_re = SENSITIVE_RE
    # pronoun paradigms the small tagger mangles (vosotros NOUN -> "vosotro",
    # contigo PROPN, conmigo NOUN/ADP): the surface is the word
    closed_surfaces = {**{p: (p, "PRON") for p in ("yo tú él ella ello nosotros nosotras vosotros vosotras "
                                                    "ellos ellas usted ustedes mí ti conmigo contigo consigo "
                                                    "aquello").split()},
                       **{f: (base, "DET") for base in ("nuestro", "vuestro")
                          for f in (base, base[:-1] + "a", base + "s", base[:-1] + "as")},
                       "varios": ("varios", "DET"), "varias": ("varios", "DET")}
    function_lemmas = {v[0] for v in closed_surfaces.values()} | {"ambos"}
    # short possessives and muy are their own words (Wiktionary lists them as
    # apocopic forms of mío/tuyo/suyo/mucho); old accented demonstratives fold
    # into the modern spelling
    surface_lemma = {**{(s, "DET"): l for s, l in (("mi", "mi"), ("mis", "mi"), ("tu", "tu"), ("tus", "tu"),
                                                     ("su", "su"), ("sus", "su"))},
                     ("muy", "ADV"): "muy", ("sólo", "ADV"): "solo",
                     # neuter demonstratives are their own words (spaCy: eso -> ese,
                     # Wiktionary: eso = "neuter of ése")
                     ("esto", "PRON"): "esto", ("eso", "PRON"): "eso", ("aquello", "PRON"): "aquello",
                     # interrogative adverbs UD tags PRON: one adverb entry each
                     **{(s, "PRON"): (s, "ADV") for s in ("cómo", "dónde", "cuándo", "adónde")},
                     # a demonstrative used as a pronoun (ése, esa, este...) is the
                     # same learner word as the determiner
                     **{(s, "PRON"): (base, "DET") for base, forms in (
                         ("este", "este esta estos estas éste ésta éstos éstas"),
                         ("ese", "ese esa esos esas ése ésa ésos ésas"),
                         ("aquel", "aquel aquella aquellos aquellas aquél aquélla aquéllos aquéllas"))
                        for s in forms.split()}}
    # UD tags interrogatives (cómo, dónde, cuándo) PRON; Wiktionary files them as adverbs
    group_kpos = {**LanguageSpec.group_kpos, "PRON": ["pron", "det", "adv"]}

    noun_head_template = "es-noun"
    regional_tags = REGIONAL

    clitic_re = re.compile(r"^(.+?)((?:me|te|se|nos|os|le|les)(?:lo|la|los|las)|me|te|se|nos|os|le|les|lo|la|los|las)$")
    art_prep = {"al": "a", "del": "de"}
    article_forms = {"el": {"el", "la", "los", "las"}, "uno": {"un", "una", "unos", "unas"}}
    definite_article = "el"
    pluralia_tantum = {"gafas", "tijeras", "afueras", "víveres", "alrededores", "anteojos", "modales"}
    copulas = {"ser", "estar", "parecer", "quedar", "resultar"}
    refl_clitics = {"me": ("1", "Sing"), "te": ("2", "Sing"), "se": ("3", None), "nos": ("1", "Plur"),
                    "os": ("2", "Plur")}
    clitic_of = {p: p for p in OWN_PRONOUNS}
    verb_endings = ("ar", "er", "ir", "ír", "arse", "erse", "irse", "írse")
    function_verbs = {"ser", "estar", "haber"}

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS + SEASONS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS + NATIONALITIES] +
                     [("sí", "INTJ"), ("no", "ADV"), ("hola", "INTJ"), ("gracias", "INTJ"), ("adiós", "INTJ"),
                      ("perdón", "INTJ"), ("por favor", "PHRASE"), ("buenos días", "PHRASE"),
                      ("buenas tardes", "PHRASE"), ("buenas noches", "PHRASE"), ("lo siento", "PHRASE")] +
                     [(p, "PHRASE") for p in PHRASES] +
                     [(p, "PRON") for p in PERSONAL] + [(p, "DET") for p in POSSESSIVE] + DEMONSTRATIVE +
                     [("a", "ADP"), ("y", "CONJ"), ("o", "CONJ"), ("e", "CONJ"), ("u", "CONJ"),
                      ("hay", "FORM")])
    no_article = set(MONTHS)
    allowed_num = set(NUMBERS)
    fixed_gloss = {
        ("el", "DET"): "the (el, la, los, las)", ("uno", "DET"): "a, an; some (un, una, unos, unas)",
        ("hay", "FORM"): "there is, there are (from haber)",
        ("por favor", "PHRASE"): "please", ("buenos días", "PHRASE"): "good morning",
        ("buenas tardes", "PHRASE"): "good afternoon, good evening",
        ("buenas noches", "PHRASE"): "good night, good evening", ("lo siento", "PHRASE"): "I'm sorry",
        # clitics whose Wiktionary entry is only "accusative/dative of X"
        ("me", "PRON"): "me, to me; myself", ("te", "PRON"): "you, to you; yourself",
        ("nos", "PRON"): "us, to us; ourselves", ("os", "PRON"): "you all, to you all; yourselves",
        ("lo", "PRON"): "him, it", ("la", "PRON"): "her, it", ("los", "PRON"): "them (m)",
        ("las", "PRON"): "them (f)", ("les", "PRON"): "to them", ("ti", "PRON"): "you (after a preposition)",
        ("se", "PRON"): "himself, herself, themselves; oneself",
        ("ellos", "PRON"): "they, them (m)", ("mí", "PRON"): "me (after a preposition)",
        ("ustedes", "PRON"): "you (plural)", ("conmigo", "PRON"): "with me", ("contigo", "PRON"): "with you",
        ("vosotros", "PRON"): "you all (Spain)", ("vosotras", "PRON"): "you all (f, Spain)",
        ("nosotras", "PRON"): "we, us (f)", ("ellas", "PRON"): "they, them (f)",
        ("vuestro", "DET"): "your (plural, Spain)",
        # short possessives / muy: Wiktionary has only "apocopic form of X"
        ("mi", "DET"): "my", ("tu", "DET"): "your", ("su", "DET"): "his, her, its, their; your (formal)",
        ("muy", "ADV"): "very",
        ("eso", "PRON"): "that (thing)", ("aquello", "PRON"): "that (thing, over there)",
        # fixed expressions: their bound nouns (el embargo, el través...) are dropped
        ("sin embargo", "PHRASE"): "however, nevertheless", ("por supuesto", "PHRASE"): "of course",
        ("de repente", "PHRASE"): "suddenly", ("a través de", "PHRASE"): "through, across",
        ("a menudo", "PHRASE"): "often", ("de hecho", "PHRASE"): "in fact, actually",
        ("a pesar de", "PHRASE"): "despite, in spite of", ("acerca de", "PHRASE"): "about, concerning",
        ("tal vez", "PHRASE"): "maybe, perhaps", ("de acuerdo", "PHRASE"): "agreed, OK; in agreement",
        ("sobre todo", "PHRASE"): "above all, especially", ("por fin", "PHRASE"): "finally, at last",
        ("a veces", "PHRASE"): "sometimes", ("de nuevo", "PHRASE"): "again",
        ("muchas gracias", "PHRASE"): "thank you very much", ("de nada", "PHRASE"): "you're welcome",
        ("por cierto", "PHRASE"): "by the way", ("a lo mejor", "PHRASE"): "maybe, perhaps",
        ("en serio", "PHRASE"): "seriously, really", ("en absoluto", "PHRASE"): "(not) at all",
    }
    # share of a word's corpus tokens inside one of these phrases above which the
    # word is not a pack entry of its own (the phrase is)
    phrase_bound_share = 0.6
    phrase_absorbs_parts = True
    object_clitics = {"me", "te", "se", "nos", "os", "lo", "le", "les"}   # not la/los/las (articles)
    fixed_word = {("el", "DET"): ("el", ["la", "los", "las"]),
                  ("uno", "DET"): ("un", ["una", "unos", "unas"])}
    multiword = {"por favor": ("por", "favor"), "buenos días": ("buenos", "días"),
                 "buenas tardes": ("buenas", "tardes"), "buenas noches": ("buenas", "noches"),
                 "lo siento": ("lo", "siento"),
                 **{p: tuple(p.split()) for p in PHRASES}}
    apocope = {"buen": "bueno", "gran": "grande", "primer": "primero", "tercer": "tercero", "algún": "alguno",
               "ningún": "ninguno", "san": "santo", "cualquier": "cualquiera"}
    drop_keys = {}
    profane_stems = ("jod", "gilipoll", "pendej", "cojon", "cabron", "cabrón", "ching", "hijoputa")
    profanity = {"mierda", "puta", "puto", "putas", "putos", "coño", "carajo", "verga", "polla", "follar",
                 "culo", "maricón", "marica", "zorra", "pinche", "culero", "cagar", "mamada", "hostia",
                 "joder", "cabrón", "cabrona", "concha", "pija", "pito", "huevón", "huevon", "mamón"}

    report_title = "Spanish A1-B1 pack (corpus-tagged)"
    forced_description = ("days, months, seasons, numbers 0-20 + tens + cien/mil, colours, nationalities, "
                          "greetings, a/y/o/e/u, hay, A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000"
    article_pool_note = "; articles el/un kept alongside"
    marked_past_name = "Voseo / regional slang"

    def __init__(self, repo=None):
        super().__init__(repo)
        self._voseo = {}
        self._gender_homonym = {}

    # ---- orthography -------------------------------------------------------
    def accent_candidates(self, s):
        return ACCENT_PAIRS.get(s, [])

    def clitic_stem_tries(self, stem):
        plain = _strip_acute(stem)
        host = plain.endswith(("ar", "er", "ir", "ndo")) or plain != stem or plain in MONO_IMPERATIVES
        if not host:
            return []
        return [stem] if plain == stem else [stem, plain]

    # ---- morphology hooks --------------------------------------------------
    def pronominal_base(self, lemma):
        return lemma[:-2] if lemma.endswith(("arse", "erse", "irse", "írse")) else None   # levantarse -> levantar

    def pronominal_form(self, lemma):
        return lemma + "se" if lemma.endswith(("ar", "er", "ir", "ír")) else None

    def _attached_refl(self, s, clitics):
        return any(s.endswith(c) and len(s) > len(c) + 2 and s[-len(c) - 1] in "aeiouáéíóúr" for c in clitics)

    def carries_refl_clitic(self, toks, i):
        """Lenient: an attached se/te/os/me/nos (levantarse, levántate) or a
        reflexive clitic before the verb through auxiliaries/adverbs."""
        s = toks[i][0].lower()
        if self._attached_refl(s, self.refl_clitics):
            return True
        j = i - 1
        while j >= 0 and toks[j][2] in ("AUX", "ADV"):
            j -= 1
        return j >= 0 and toks[j][2] == "PRON" and toks[j][0].lower() in self.refl_clitics

    def stative_aux(self, toks, i):
        j = i - 1
        while j >= 0 and toks[j][2] == "ADV":
            j -= 1
        return j >= 0 and toks[j][2] in ("AUX", "VERB") and toks[j][1].lower() == "estar"

    def is_reflexive(self, toks, i):
        """Strict: an attached se (levantarse, dándose; me/te/nos attached are
        often objects: ayudarme, dime), or a reflexive clitic right before the
        verb or its auxiliaries in the verb's person (me levanto, se ha ido)."""
        text, sl, upos, ms = toks[i]
        if len(sl.split()) == 2 and self._attached_refl(text.lower(), ("se",)):
            return True
        j = i - 1
        finite = ms
        while j >= 0 and toks[j][2] in ("AUX", "ADV"):
            if toks[j][2] == "AUX":
                finite = toks[j][3] or finite
            j -= 1
        if j < 0 or toks[j][2] != "PRON":
            return False
        cl = toks[j][0].lower()
        if cl not in self.refl_clitics:
            return False
        person, number = self.refl_clitics[cl]
        m = dict(kv.split("=") for kv in finite.split("|") if "=" in kv)
        if m.get("Person") != person:
            return False
        return number is None or m.get("Number") in (None, number)

    def bind_lexicon(self, lexicon):
        self._lex = lexicon
        self._voseo = {}
        self._gender_homonym = {}

    def is_voseo(self, s):
        """Every verb-form sense of the surface is a voseo form (tenés, sos, vení)."""
        if s not in self._voseo:
            lex = getattr(self, "_lex", None)
            senses = [sn for e in (lex.E.get(s, []) if lex else []) if e["p"] == "verb"
                      for sn in e["s"] if sn[3] == "form"]
            self._voseo[s] = bool(senses) and all("voseo" in sn[2] or "voseo" in sn[0] for sn in senses)
        return self._voseo[s]

    def marks_sentence(self, toks):
        return any(t[0].lower() in MARKED_TOKENS or (t[2] in ("VERB", "AUX", "ADJ", "PROPN") and self.is_voseo(t[0].lower()))
                   for t in toks)

    # ---- nouns / articles ----------------------------------------------------
    lemma_tiebreak_corpus = True
    revert_dedupe_gloss = True

    def copula_inflected(self, surface, adj):
        # a plural ending is no evidence (son animales); a gender change is (enferma)
        return adj != surface and surface not in (adj + "s", adj + "es")

    def numeral_group(self, lexicon, surface, lemma):
        # only cardinals are numerals: ambos "both", medio "half" are read under
        # their own dictionary POS
        lem = lemma if lemma in lexicon.E else surface
        if not lexicon.E.get(lem) or lexicon.usable_entries(lem, ["num"]):
            return "NUM"
        for kp, g in (("det", "DET"), ("pron", "PRON"), ("adj", "ADJ")):
            if lexicon.usable_entries(lem, [kp]):
                return g
        return "NUM"

    def sense_tags(self, tags):
        # a sense tagged with Spain or Latin America as a whole, or with three
        # or more countries, is standard in that variety (ordenador, computadora)
        reg = [t for t in tags if t in REGIONAL or t in ("Spain", "Latin-America")]
        if reg and (len(reg) >= 3 or "Spain" in reg or "Latin-America" in reg):
            return [t for t in tags if t not in REGIONAL]
        return tags

    def needs_gender_evidence(self, lexicon, lemma):
        c = self._gender_homonym.get(lemma)
        if c is None:
            gs = {self.parse_gender(e.get("g"))[0] for e in lexicon.usable_entries(lemma, ["noun"])}
            c = self._gender_homonym[lemma] = {"m", "f"} <= gs
        return c

    def translation_mismatch(self, toks, en):
        # "Lo vi" translated "I saw her": a 3rd-person pronoun whose gender the
        # English contradicts, with nothing of the other gender in the sentence
        prons = {t[0].lower() for t in toks if t[2] == "PRON"}
        e = set(re.findall(r"[a-z]+", en.lower()))
        masc, fem = prons & {"lo", "él"}, prons & {"la", "ella"}
        he = e & {"he", "him", "his", "himself"}
        she = e & {"she", "her", "hers", "herself"}
        neutral = e & {"it", "its", "itself", "you", "your", "they", "them", "their"}
        if masc and not fem and she and not he and not neutral:
            return True
        return bool(fem and not masc and he and not she and not neutral)

    def post_resolve(self, toks, out):
        """ser and ir share the preterite (fue, fueron): followed by a/al/hacia
        it is ir ("Fueron a Chicago"). sí after a preposition is the
        pronoun ("entre sí", "por sí mismo"), not "yes"."""
        lex = getattr(self, "_lex", None)
        for i, r in enumerate(out):
            if i and toks[i][0].lower() == "sí" and toks[i - 1][2] == "ADP":
                out[i] = ("sí", "PRON")
            low = toks[i][0].lower()
            fin = toks[i][2] in ("VERB", "AUX") and "VerbForm=Fin" in toks[i][3]
            first = all(t[2] == "PUNCT" for t in toks[:i])
            if first and fin and i + 1 < len(toks) and toks[i + 1][2] in ("VERB", "AUX") and \
                    "VerbForm=Fin" in toks[i + 1][3]:
                # two finite verbs in a row: the first is a sentence-initial name
                # ("Dan vio el video" is not dar)
                out[i] = (low, "PROPN")
                continue
            if lex is not None and fin and r and r[1] == "VERB":
                j = i - 1
                while j >= 0 and toks[j][2] == "ADV":
                    j -= 1
                if j >= 0 and out[j] and out[j][0] in ("ser", "estar") and out[j][1] == "VERB":
                    # a finite verb cannot follow a copula: "es linda" is the
                    # adjective lindo, not lindar
                    adj = lex.candidates(low, ["adj"])
                    if adj:
                        out[i] = (lex.best_by_freq(adj), "ADJ")
                        continue
            if lex is not None and i and r and r[1] in ("ADJ", "NOUN") and out[i - 1] == ("haber", "VERB") and \
                    PARTICIPLE_RE.search(low):
                # compound tense: "hayas conocido", "he hecho" are the verb,
                # not the adjective conocido / the noun hecho
                verbs = lex.verbs_only(lex.candidates(low, ["verb"]))
                if verbs:
                    out[i] = (lex.best_by_freq(verbs), "VERB")
            if r == ("ser", "VERB") and toks[i][0].lower() in IR_SER_PRETERITE and i + 1 < len(toks) and \
                    toks[i + 1][0].lower() in ("a", "al", "hacia"):
                out[i] = ("ir", "VERB")
        return out

    def numeral_may_be_verb(self, lexicon, surface):
        # "y media", "medio kilo" are not mediar; vosotros forms tagged NUM are verbs
        return not lexicon.candidates(surface, ["num", "adj", "noun"])

    def after_article_is_noun(self, toks, i):
        # "un poco" is an adverbial quantifier; "la amo" is a clitic + finite verb
        if toks[i][2] == "ADV" and toks[i - 1][0].lower() in self.article_forms["uno"]:
            return False
        return not (toks[i][2] == "VERB" and "VerbForm=Fin" in toks[i][3])

    def imperative_homograph(self, lexicon, lemma):
        """Sentence-initial "Mira, ..." is the imperative, not la mira (target)."""
        return lexicon.imperative_form(lemma) is not None or lexicon.imperative_clitic(lemma)

    def parse_gender(self, g):
        # mfequiv (el/la mar, azúcar, arte): either gender, same meaning -> the
        # corpus majority decides; mfbysense: a person/animal noun
        if g and "mfequiv" in str(g):
            return None, False
        return super().parse_gender(g)

    def has_feminine_noun(self, lemma):
        """médico -> médica, juez -> jueza, lobo -> loba: a separate feminine noun."""
        lex = getattr(self, "_lex", None)
        if not lex:
            return False
        stem = lemma[:-1] if lemma[-1] in "oe" else lemma
        return any(re.match(rf"(?:female equivalent|feminine) of {lemma}\b", sn[0])
                   for e in lex.E.get(stem + "a", []) if e["p"] == "noun" for sn in e["s"])

    def default_gender(self, lemma):
        return "f" if lemma.endswith(("a", "ción", "sión", "dad", "tad", "tud", "umbre")) else "m"

    def noun_display(self, lemma, gender, plural, en):
        if plural:
            return ("las " if gender == "f" else "los ") + lemma, en
        if gender == "mf":
            if self.has_feminine_noun(lemma):
                return f"el {lemma}", en           # el médico (la médica is its own word)
            return f"el/la {lemma}", en
        if gender == "f":
            if stressed_initial_a(lemma):
                return f"el {lemma}", f"{en} (f)"          # el agua, el hambre
            return f"la {lemma}", en
        return f"el {lemma}", en

    def check_word(self, w):
        """A noun's article must be el, la or el/la (los/las only for pluralia
        tantum); la never precedes a stressed a-/ha- noun, and el + "(f)" only
        does."""
        if w.get("pos") != "noun":
            return None
        shown, lemma = w["w"], (w.get("alt") or [w["lemma"]])[0]
        if shown == lemma:
            return None if lemma in MONTHS else f"noun {w['id']} {shown!r}: no article"
        if not shown.endswith(" " + lemma):
            return f"noun {w['id']} {shown!r}: display does not end in its lemma {lemma!r}"
        art = shown[: -len(lemma) - 1]
        if art in ("los", "las"):
            return None if lemma in self.pluralia_tantum else \
                f"noun {w['id']} {shown!r}: plural article on a lemma outside pluralia_tantum"
        if art not in ("el", "la", "el/la"):
            return f"noun {w['id']} {shown!r}: article {art!r} not in el/la/el/la"
        if art == "la" and stressed_initial_a(lemma):
            return f"noun {w['id']} {shown!r}: feminine stressed a- noun takes el"
        if art == "el" and w["en"].endswith("(f)") and not stressed_initial_a(lemma):
            return f"noun {w['id']} {shown!r}: el + (f) only for stressed a- nouns"
        return None

    # ---- QA scans ------------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "seasons": " ".join(SEASONS),
        "num": " ".join(NUMBERS), "col": " ".join(COLOURS),
        "core": "a y o e u no sí hola gracias adiós perdón ser estar haber",
        "pron": " ".join(PERSONAL), "poss": " ".join(POSSESSIVE), "demo": " ".join(w for w, _ in DEMONSTRATIVE),
    }
    qa_verb_re = r"(ar|er|ir|ír|arse|erse|irse|írse)$"
    qa_article_rules = [
        (r"^el \S*(ción|sión|dad|tad|tud|umbre)$", "el + feminine ending"),
        (r"^la \S*aje$", "la + masculine ending"),
    ]
    qa_clitic_verb_re = r"(r|ndo)(me|te|se|nos|os|lo|la|los|las|le|les)$"
    qa_clitic_cluster_re = r"^(me|te|se|nos|os)(lo|la|los|las)$"
    qa_adj_inflected_re = r"(os|as)$"
    qa_foreign_letters_re = r"[kw]"
    qa_proper_re = r"\b(Spain|Madrid|Mexico|Argentina|Barcelona|Christ|God)\b"
    qa_plural_article_re = r"^(los|las) "


SPEC = Spanish
