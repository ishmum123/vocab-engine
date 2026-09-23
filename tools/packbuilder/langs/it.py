"""Italian (it): everything Italian-specific in the pack pipeline.

Rules and tables here were tuned over three QA rounds; each is described in
the italian repo's tools/REPORT.md. The A1 core list, gloss overrides and the
frozen v1 id map live in the italian repo (tools/).
"""
import re

from .base import LanguageSpec, TATOEBA_ENG, TATOEBA_LINKS, TATOEBA_AUDIO

VOWELS = "aeiouàèéìíòóùú"

DAYS = "lunedì martedì mercoledì giovedì venerdì sabato domenica".split()
MONTHS = ("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre "
          "novembre dicembre").split()
NUMBERS = ("zero uno due tre quattro cinque sei sette otto nove dieci undici dodici tredici "
           "quattordici quindici sedici diciassette diciotto diciannove venti trenta quaranta "
           "cinquanta sessanta settanta ottanta novanta cento mille").split()
COLOURS = "rosso blu verde giallo nero bianco grigio marrone rosa azzurro arancione viola".split()
NATIONALITIES = "italiano tedesco francese spagnolo inglese americano".split()
SEASONS = "primavera estate autunno inverno".split()

_ART_PREP = {}
for _base, _stem in (("a", "a"), ("da", "da"), ("di", "de"), ("in", "ne"), ("su", "su")):
    for _suf in ("l", "llo", "lla", "ll'", "i", "gli", "lle"):
        _ART_PREP[_stem + _suf] = _base
_ART_PREP.update({"col": "con", "coi": "con", "pel": "per", "pei": "per"})

SINGULAR_ARTICLES = {"il", "lo", "la", "l'", "il/la"}
PLURAL_ARTICLES = {"i", "gli", "le"}


def article_for(gender, lemma, plural=False):
    first = lemma[0]
    vowel = first in VOWELS or first == "h"
    lo_type = (lemma[:2] in ("gn", "ps", "pn") or first in "zxy" or
               (first == "s" and len(lemma) > 1 and lemma[1] not in VOWELS) or
               (first == "i" and len(lemma) > 1 and lemma[1] in VOWELS))
    if gender == "f":
        if plural:
            return "le"
        return "l'" if vowel and not (first == "i" and lemma[1:2] in tuple(VOWELS)) else "la"
    if plural:
        return "gli" if (vowel or lo_type) else "i"
    if lo_type:
        return "lo"
    return "l'" if vowel else "il"


def with_article(art, lemma):
    return f"l'{lemma}" if art == "l'" else f"{art} {lemma}"


class Italian(LanguageSpec):
    code = "it"
    name_en = "Italian"
    pack_name = "Italian (A1–B1)"
    tts = "it-IT"
    stt = "it-IT"
    tatoeba_code = "ita"

    spacy_model = "it_core_news_sm"
    tagger_attribution = {
        "source": "spaCy (MIT) + it_core_news_sm model (CC BY-NC-SA 3.0, trained on UD Italian ISDT)",
        "licence": "CC BY-NC-SA 3.0 (model)",
        "note": "Used at build time only; the pack ships no model files. This project is non-commercial.",
    }

    subtitles_file = "it_full.txt"
    kaikki_file = "kaikki_it.jsonl.gz"
    sentences_file = "ita_detailed.tsv.bz2"
    kelly_file = "kelly_it.json"
    sources = {
        "it_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/it/it_full.txt",
        "kaikki_it.jsonl.gz": "https://kaikki.org/dictionary/Italian/kaikki.org-dictionary-Italian.jsonl.gz",
        "ita_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/ita/ita_sentences_detailed.tsv.bz2",
        "ita_cc0.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/ita/ita_sentences_CC0.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_LINKS[0]: TATOEBA_LINKS[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
        "kelly_it.json": "https://raw.githubusercontent.com/kotoshu/frequency-list-kelly/main/data/it.json",
    }
    versions = {"corpus": "c2", "tag": "t3", "lex": "l6"}

    lex_word_re = re.compile(r"^[a-zàáèéìíòóùúç']+$")
    sub_token_re = re.compile(r"^[a-zàèéìíòóùú]+'?$")
    form_target_re = re.compile(r"\bof ([a-zàèéìòù']+)")
    fem_of_re = re.compile(r"(?:female equivalent|(?:singular )?feminine(?: singular)?) of ([a-zàèéìòù]+)")
    accent_variants = {"a": "à", "e": "èé", "i": "ì", "o": "ò", "u": "ù"}

    noun_head_template = "it-noun"
    regional_tags = {"Tuscany", "Southern-Italy", "Northern-Italy", "Rome", "Naples"}

    clitic_re = re.compile(r"^(.+?)((?:glie|me|te|ce|ve|se)(?:lo|la|li|le|ne)|lo|la|li|le|mi|ti|ci|vi|si|ne|gli)$")
    art_prep = _ART_PREP
    article_forms = {"il": {"il", "lo", "la", "l'", "i", "gli", "le"}, "uno": {"un", "uno", "una", "un'"}}
    definite_article = "il"
    # nouns used (almost) only in the plural: kept as their own lemma
    pluralia_tantum = {"soldi", "occhiali", "pantaloni", "forbici", "nozze", "ferie", "dintorni",
                       "stoviglie", "mutande", "calzoni", "spiccioli"}
    copulas = {"essere", "diventare", "sembrare", "rimanere", "restare", "stare", "diventato"}
    refl_clitics = {"mi": ("1", "Sing"), "ti": ("2", "Sing"), "si": ("3", None), "ci": ("1", "Plur"), "vi": ("2", "Plur")}
    # unstressed object pronouns whose Wiktionary entry is only "clitic form of X"
    clitic_of = {"mi": "io", "ti": "tu"}
    mono_imperative = {"da": "dare", "di": "dire", "fa": "fare", "sta": "stare", "va": "andare"}
    verb_endings = ("are", "ere", "ire", "rre", "arsi", "ersi", "irsi", "rsi")
    function_verbs = {"essere", "avere"}

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS + SEASONS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS + NATIONALITIES] + [("buonanotte", "INTJ")] +
                     [("sì", "INTJ"), ("no", "INTJ"), ("ciao", "INTJ"), ("grazie", "INTJ"), ("prego", "INTJ"),
                      ("scusa", "INTJ"), ("buongiorno", "INTJ"), ("buonasera", "INTJ"), ("arrivederci", "INTJ"),
                      ("per favore", "PHRASE"), ("a", "ADP"), ("e", "CONJ"), ("o", "CONJ"),
                      ("è", "FORM")])
    no_article = set(DAYS + MONTHS)
    allowed_num = set(NUMBERS)
    # closed-class items whose Wiktionary gloss is grammatical description
    fixed_gloss = {
        ("il", "DET"): "the (il, lo, l', la, i, gli, le)", ("uno", "DET"): "a, an (un, uno, una, un')",
        ("è", "FORM"): "is (from essere)", ("per favore", "PHRASE"): "please",
    }
    fixed_word = {("il", "DET"): ("il", ["lo", "la", "l'", "i", "gli", "le"]),
                  ("uno", "DET"): ("un", ["uno", "una", "un'"])}
    multiword = {"per favore": ("per", "favore")}
    # apocopated forms link to their lemma (link forms, not typing alts)
    apocope = {"nessun": "nessuno", "quel": "quello", "bel": "bello", "buon": "buono", "gran": "grande",
               "san": "santo", "ciascun": "ciascuno", "alcun": "alcuno"}
    # final-QA hand drops: entries whose sentences are all another word's use
    # (fine adj: every sentence is "fine settimana") or a duplicate of a forced
    # entry (no adv beside the interjection); their tokens link as mapped
    drop_keys = {("fine", "ADJ"): None, ("no", "ADV"): ("no", "INTJ")}
    profane_stems = ("cazz", "merd", "stronz", "puttan", "coglion", "fott", "incazz", "vaffancul")
    profanity = {"cazzo", "cazzata", "merda", "stronzo", "stronza", "puttana", "vaffanculo",
                 "coglione", "cagare", "scopare", "fica", "figa", "culo", "troia", "bastardo",
                 "bastarda", "porco", "porca", "fottere", "fottuto", "puttanata", "incazzare"}
    # "bel" before a vowel is an error for "bell'" ("Non ho un bel aspetto")
    bad_text_re = re.compile(r"\bbel [aeiouàèéìòù]", re.I)

    report_title = "Italian A1-B1 pack (v2, corpus-tagged)"
    forced_description = ("days, months, numbers 0-20 + tens + cento/mille, colours, greetings, a/e/o/è, "
                          "A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000"
    article_pool_note = "; articles il/uno kept alongside"
    marked_past_name = "Passato remoto"
    uses_historic_past_forms = True

    # ---- morphology hooks ------------------------------------------------
    def pronominal_base(self, lemma):
        return lemma[:-2] + "e" if lemma.endswith("rsi") else None     # farsi -> fare

    def pronominal_form(self, lemma):
        return (lemma[:-2] if lemma.endswith("rre") else lemma[:-1]) + "si"

    def clitic_stem_tries(self, stem):
        return [stem, stem + "e", stem + "'"]        # dir+lo -> dire, di'+mi

    def carries_refl_clitic(self, toks, i):
        """Lenient check for the -rsi gate: a reflexive-form clitic attached to the
        verb surface ("fidarti", "muoviti": spaCy's lemma is often garbled there)
        or before it through auxiliaries/adverbs/non ("mi fidassi", "si fidi"),
        without the person agreement the tagger's morphology often gets wrong."""
        s = toks[i][0].lower()
        if len(s) > 4 and s[-2:] in self.refl_clitics and s[-3] in "aeiouàèéìòùr":   # muoviti, fidarti
            return True
        j = i - 1
        while j >= 0 and toks[j][2] in ("AUX", "ADV"):
            j -= 1
        return j >= 0 and toks[j][2] == "PRON" and toks[j][0].lower() in self.refl_clitics

    def stative_aux(self, toks, i):
        j = i - 1
        while j >= 0 and toks[j][2] == "ADV":
            j -= 1
        return j >= 0 and toks[j][2] in ("AUX", "VERB") and toks[j][1].lower() == "essere"

    def is_reflexive(self, toks, i):
        """The verb token carries a reflexive clitic: attached ("lamentarsi",
        spaCy lemma 'lamentare si') or right before it or its auxiliaries, in the
        same person ("mi sono lamentato", "si fida")."""
        text, sl, upos, ms = toks[i]
        parts = sl.lower().split()
        if len(parts) == 2 and parts[1] in self.refl_clitics and parts[1] != "ci":
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

    def is_marked_past(self, ms):
        return "Tense=Past" in ms and "Mood=Ind" in ms and "VerbForm=Fin" in ms

    # ---- nouns / articles -------------------------------------------------
    def default_gender(self, lemma):
        return "f" if lemma.endswith("a") else "m"

    def noun_display(self, lemma, gender, plural, en):
        if gender == "mf":
            am, af = article_for("m", lemma, plural), article_for("f", lemma, plural)
            if am == af == "l'":
                return with_article("l'", lemma), f"{en} (m/f)"
            return f"{am}/{af} {lemma}", en
        art = article_for(gender, lemma, plural)
        return with_article(art, lemma), (f"{en} ({gender})" if art == "l'" else en)

    def clean_sentence_text(self, t):
        return re.sub(r"\s+([?!])", r"\1", t)

    def check_word(self, w):
        """A noun's displayed article must be singular (il, lo, la, l', il/la) and
        the right form for the lemma's first letters; plural articles only for
        pluralia tantum."""
        if w.get("pos") != "noun":
            return None
        shown, lemma = w["w"], (w.get("alt") or [w["lemma"]])[0]
        if shown == lemma:
            return None                      # no article (days, months)
        if shown == f"l'{lemma}":
            art = "l'"
        elif shown.endswith(" " + lemma):
            art = shown[: -len(lemma) - 1]
        else:
            return f"noun {w['id']} {shown!r}: display does not end in its lemma {lemma!r}"
        if art in PLURAL_ARTICLES:
            if lemma not in self.pluralia_tantum:
                return f"noun {w['id']} {shown!r}: plural article on a lemma outside PLURALIA_TANTUM"
            return None
        if art not in SINGULAR_ARTICLES:
            return f"noun {w['id']} {shown!r}: article {art!r} not in {sorted(SINGULAR_ARTICLES)}"
        if art == "il/la":
            ok = article_for("m", lemma) == "il" and article_for("f", lemma) == "la"
        elif art == "l'":
            ok = "l'" in (article_for("m", lemma), article_for("f", lemma))
        else:
            ok = art in (article_for("m", lemma), article_for("f", lemma))
        return None if ok else f"noun {w['id']} {shown!r}: wrong article form for {lemma!r}"

    # ---- QA scans -----------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "num": " ".join(NUMBERS),
        "col": "rosso blu azzurro verde giallo nero bianco grigio marrone rosa viola arancione",
        "core": "a e o essere sì no ciao grazie prego scusa buongiorno buonasera arrivederci",
    }
    qa_verb_re = r"(are|ere|ire|rre|arsi|ersi|irsi)$"
    qa_article_rules = [
        (r"^il ([aeiouàèìòù]|s[^aeiou]|z|gn|ps|x|y|pn)", "il+"),
        (r"^lo (?!(s[^aeiou]|z|gn|ps|x|y|pn|i[aeiou]))", "lo+"),
        (r"^la \S*o$(?<!mano)(?<!radio)(?<!foto)(?<!moto)(?<!auto)(?<!dinamo)", "la -o"),
        (r"^il \S*a$(?<!ma)(?<!ta)(?<!pa)", "il -a"),
        (r"^l'[^aeiouàèéìòùh]", "l'+cons"),
    ]
    qa_clitic_verb_re = r"(r|re)(mi|ti|si|ci|vi|lo|la|li|le|gli|ne|glielo|gliela|melo|telo)$"
    qa_clitic_cluster_re = r"^(glie|me|te|ce|se)(lo|la|li|le|ne)$"
    qa_adj_inflected_re = r"(a|i|he)$"
    qa_foreign_letters_re = r"[wkyjx]"
    qa_proper_re = r"\b(Rome|Milan|Naples|Italy|Florence|Venice|Marche|Tuscany|Christ|God)\b"
    qa_plural_article_re = r"^(i|gli|le) "


SPEC = Italian
