"""Tests for the French passage-only rules and the generic Linker hooks they
use: declared names (no truecasing of a name-initial sentence, PROPN),
spec.passage_text, passage_retag, passage_post_resolve, passage_fallback_ok,
passage_phrase_ranges (expression parts read as the expression, one span over
it) and passage_form_base (Linker.form_base). Stdlib only.

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
"""
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.passages import Linker  # noqa: E402

TMP = tempfile.mkdtemp()
WORD_RE = re.compile(r"[^\W\d_]+")


def T(text, upos="X", lemma=None, morph=""):
    return [text, lemma or text.lower(), upos, morph]


def word(wid, lemma, group, pos, rank, en=""):
    return {"id": wid, "w": lemma, "lemma": lemma, "pos": pos, "lv": "A1", "rank": rank, "_key": [lemma, group],
            "en": en}


class FakeLex:
    def __init__(self, res=None, cands=None, E=None, zipf=None):
        self.res, self.cands, self.E, self.z = res or {}, cands or {}, E or {}, zipf or {}

    def resolve_sentence(self, toks, groups=None):
        return [self.res.get(t[0].lower()) for t in toks]

    def readings(self, s):
        return []

    def zipf(self, w):
        return self.z.get(w, 0.0)

    def candidates(self, low, poses):
        return [x for p in poses for x in self.cands.get((low, p), [])]

    def verbs_only(self, c):
        return c

    def best_by_freq(self, c):
        return max(c, key=lambda x: (self.zipf(x), x))

    def usable_entries(self, w, poses):
        return [e for e in self.E.get(w, []) if e["p"] in poses]


def fr_spec(lex):
    sp = get_spec("fr", TMP)
    sp._lx = lex
    return sp


def entry(p, *glosses, g=None, form=False, tags=()):
    return {"p": p, "g": g, "s": [[x, None, list(tags), "form" if form else ""] for x in glosses]}


def linker(spec, lex, words):
    c = {"lexicon": lex, "groups": None, "truecase": (Counter(), Counter()), "words": words}
    return Linker(spec, c, {w["id"]: w for w in words})


class StubSpec:
    """Duck-typed spec with a recording Stanza-style tagger."""
    homograph_by_translation = False
    word_re = WORD_RE
    morph_keep = ()
    tagger, spacy_model = "stanza", None
    truecase_after = truecase_after_end = ""
    span_fold, span_joiners = None, ""

    def __init__(self):
        self.seen = []

    def tag_text(self, t):
        return t

    def tag_texts(self, texts):
        self.seen += texts
        return [[(w, w, "NOUN", {}) for w in re.findall(r"\w+", t)] for t in texts]

    def fix_token(self, tok):
        return tok

    def fix_sentence(self, toks, row, doc):
        return toks


class DeclaredNames(unittest.TestCase):
    def setUp(self):
        self.sp = StubSpec()
        low, cap = Counter({"pierre": 50}), Counter({"pierre": 2})
        self.lk = Linker(self.sp, {"lexicon": None, "groups": None, "truecase": (low, cap), "words": []}, {})

    def test_name_initial_sentence_not_truecased_and_propn(self):
        toks = self.lk.tag("Pierre mange", "", {"Pierre"})
        self.assertEqual(self.sp.seen, ["Pierre mange"])
        self.assertEqual(toks[0][2], "PROPN")

    def test_without_names_truecased_and_cached_apart(self):
        self.lk.pretag([("Pierre mange", "", {"Pierre"}), ("Pierre mange", "")])
        self.assertEqual(self.sp.seen, ["Pierre mange", "pierre mange"])
        self.assertEqual(self.lk.tag("Pierre mange")[0][2], "NOUN")
        self.assertEqual(self.lk.tag("Pierre mange", "", frozenset({"Pierre"}))[0][2], "PROPN")
        self.assertEqual(len(self.sp.seen), 2)              # both served from the cache

    def test_passage_text_sees_the_names(self):
        calls = []
        self.sp.passage_text = lambda text, names, lexicon: calls.append((text, names)) or text.upper()
        self.lk.tag("Léa rit", "", {"Léa"})
        self.assertEqual(calls, [("Léa rit", frozenset({"Léa"}))])
        self.assertEqual(self.sp.seen, ["LÉA RIT"])


class FrenchPassageText(unittest.TestCase):
    def test_capitalised_common_words_lowercased(self):
        lex = FakeLex(E={"madame": [entry("noun", "madam")], "les": [entry("article", "the")],
                         "espagnol": [entry("noun", "Spaniard")], "martin": [entry("name", "a surname")],
                         "marie": [entry("name", "Mary"), entry("verb", "form", form=True)]})
        sp = fr_spec(lex)
        out = sp.passage_text("Bonjour Madame Martin, « Les gens » et un Espagnol. J'ai vu Marie.",
                              frozenset({"Marie"}), lex)
        self.assertEqual(out, "Bonjour madame Martin, « les gens » et un espagnol. j'ai vu Marie.")

    def test_elided_non_letter_kept(self):
        lex = FakeLex(E={"aujourd": [entry("adv", "x")]})
        self.assertEqual(fr_spec(lex).passage_text("Aujourd'hui", frozenset(), lex), "Aujourd'hui")


class FrenchRetag(unittest.TestCase):
    def test_x_gets_dictionary_class(self):
        sp = fr_spec(FakeLex(cands={("dansé", "verb"): ["danser"]}))
        out = sp.passage_retag([T("ont", "AUX"), T("dansé", "X")])
        self.assertEqual(out[1][2], "VERB")

    def test_after_subject_pronoun_a_verb_reading_goes_to_post_resolve_as_noun(self):
        sp = fr_spec(FakeLex(cands={("bois", "verb"): ["boire"], ("court", "verb"): ["courir"]}))
        self.assertEqual(sp.passage_retag([T("je", "PRON"), T("bois", "ADJ")])[1][2], "NOUN")
        self.assertEqual(sp.passage_retag([T("il", "PRON"), T("le", "PRON"), T("court", "PROPN")])[2][2], "NOUN")
        self.assertEqual(sp.passage_retag([T("un", "DET"), T("bois", "ADJ")])[1][2], "ADJ")
        self.assertEqual(sp.passage_retag([T("je", "PRON"), T("Bois", "PROPN")])[1][2], "PROPN")


class FrenchPostResolve(unittest.TestCase):
    def pr(self, toks, out, **lex):
        return fr_spec(FakeLex(**lex)).passage_post_resolve(toks, out)

    def test_ete_after_en_is_summer(self):
        t = [T("en", "ADP"), T("été", "AUX")]
        self.assertEqual(self.pr(t, [None, ("être", "VERB")])[1], ("été", "NOUN"))
        t = [T("a", "AUX"), T("été", "AUX")]
        self.assertEqual(self.pr(t, [None, ("être", "VERB")])[1], ("être", "VERB"))

    def test_plus_is_never_plaire(self):
        t = [T("le", "DET"), T("plus", "VERB")]
        self.assertEqual(self.pr(t, [None, ("plaire", "VERB")])[1], ("plus", "ADV"))

    def test_noun_reading_of_a_finite_verb_after_a_subject_np(self):
        t = [T("Le", "DET"), T("train", "NOUN"), T("part", "NOUN"), T("à", "ADP")]
        out = self.pr(t, [("le", "DET"), ("train", "NOUN"), ("part", "NOUN"), ("à", "ADP")],
                      cands={("part", "verb"): ["partir"]})
        self.assertEqual(out[2], ("partir", "VERB"))

    def test_after_et_once_the_sentence_has_a_verb(self):
        t = [T("reste", "VERB"), T("et", "CCONJ"), T("lit", "NOUN"), T("un", "DET")]
        out = self.pr(t, [("rester", "VERB"), ("et", "CONJ"), ("lit", "NOUN"), ("un", "DET")],
                      cands={("lit", "verb"): ["lire"]})
        self.assertEqual(out[2], ("lire", "VERB"))

    def test_after_a_closing_quote(self):
        t = [T("»", "PUNCT"), T("demande", "NOUN"), T("Léa", "PROPN")]
        out = self.pr(t, [None, ("demande", "NOUN"), None], cands={("demande", "verb"): ["demander"]})
        self.assertEqual(out[1], ("demander", "VERB"))

    def test_noun_stays_without_predicate_position(self):
        t = [T("un", "DET"), T("lit", "NOUN"), T("confortable", "ADJ")]
        out = self.pr(t, [("un", "DET"), ("lit", "NOUN"), None], cands={("lit", "verb"): ["lire"]})
        self.assertEqual(out[1], ("lit", "NOUN"))


class FrenchFallbackOk(unittest.TestCase):
    def setUp(self):
        self.lex = FakeLex(E={"ferme": [entry("adj", "firm"), entry("noun", "farm")],
                              "long": [entry("adj", "long"), entry("noun", "length")]})
        self.sp = fr_spec(self.lex)

    def test_english_names_the_noun_sense(self):
        w = {"pos": "adj", "en": "firm"}
        self.assertFalse(self.sp.passage_fallback_ok(self.lex, ("ferme", "NOUN"), w, "He lives on the farm."))
        self.assertFalse(self.sp.passage_fallback_ok(self.lex, ("ferme", "NOUN"), w, "an old farmhouse"))
        self.assertTrue(self.sp.passage_fallback_ok(self.lex, ("ferme", "NOUN"), w, "Hold it firm."))
        self.assertTrue(self.sp.passage_fallback_ok(self.lex, ("ferme", "NOUN"), w, ""))      # questions
        self.assertTrue(self.sp.passage_fallback_ok(self.lex, ("ferme", "ADJ"), w, "the farm"))

    def test_other_english_keeps_the_link(self):
        self.assertTrue(self.sp.passage_fallback_ok(self.lex, ("long", "NOUN"), {"pos": "adj", "en": "long"},
                                                    "They walk along the river."))


class FrenchPhraseRanges(unittest.TestCase):
    def setUp(self):
        self.sp = fr_spec(FakeLex())

    def test_ranges(self):
        r = self.sp.passage_phrase_ranges
        self.assertEqual(r([T("parce", "SCONJ"), T("qu'", "SCONJ"), T("il", "PRON")]), [(0, 1, 0)])
        self.assertEqual(r([T("Est", "AUX"), T("-ce", "PRON"), T("que", "SCONJ"), T("tu", "PRON")]), [(0, 2, 0)])
        self.assertEqual(r([T("au", "ADP"), T("lieu", "NOUN"), T("du", "ADP"), T("pain", "NOUN")]), [(0, 2, 1)])
        self.assertEqual(r([T("il", "PRON"), T("n'", "ADV"), T("y", "PRON"), T("a", "VERB")]), [])   # ne keeps its link
        self.assertEqual(r([T("il", "PRON"), T("mange", "VERB")]), [])


FR_WORDS = [word("w_parce", "parce que", "CONJ", "conj", 1), word("w_il", "il", "PRON", "pron", 2),
            word("w_venir", "venir", "VERB", "verb", 3), word("w_ami", "ami", "NOUN", "noun", 4),
            word("w_allemand", "allemand", "ADJ", "adj", 5), word("w_ferme", "ferme", "ADJ", "adj", 6, "firm"),
            word("w_son", "son", "DET", "det", 7, "his, her, its"), word("w_drole", "drôle", "ADJ", "adj", 8, "funny"),
            word("w_mort_n", "mort", "NOUN", "noun", 9, "death"), word("w_mort_a", "mort", "ADJ", "adj", 10, "dead"),
            word("w_pers_p", "personne", "PRON", "pron", 11, "nobody"),
            word("w_pers_n", "personne", "NOUN", "noun", 12, "person"),
            word("w_chanteur", "chanteur", "NOUN", "noun", 13, "singer"),
            word("w_maison", "maison", "NOUN", "noun", 14, "house")]


class FrenchLinker(unittest.TestCase):
    def lk(self, res=None, E=None):
        lex = FakeLex(res, E=E)
        sp = fr_spec(lex)
        sp.passage_post_resolve = lambda toks, out: out
        return linker(sp, lex, FR_WORDS)

    def test_expression_parts_read_as_the_expression_and_one_span(self):
        lk = self.lk({"parce": ("parce que", "CONJ"), "il": ("il", "PRON"), "vient": ("venir", "VERB")})
        toks = [T("parce", "SCONJ"), T("qu'", "SCONJ"), T("il", "PRON"), T("vient", "VERB")]
        cl = lk.classify(toks)
        self.assertEqual([c[2] for c in cl], ["w_parce", "w_parce", "w_il", "w_venir"])
        lk.links = lambda toks, text, en, where: where.extend(
            [("tok", 0, 0, "w_parce"), ("tok", 2, 2, "w_il"), ("tok", 3, 3, "w_venir")]) or ["w_parce", "w_il", "w_venir"]
        ids, _cl, spans, _claimed = lk.links_all(toks, "parce qu'il vient", "")
        self.assertEqual(ids, ["w_parce", "w_il", "w_venir"])
        self.assertEqual(spans, [[0, 9, "w_parce"], [9, 11, "w_il"], [12, 17, "w_venir"]])

    def test_form_base(self):
        E = {"amie": [entry("noun", "friend", g="f|m=ami")],
             "allemande": [entry("adj", "inflection (feminine singular) allemand", form=True,
                                 tags=["feminine", "form-of", "singular"])],
             "chanteuse": [entry("noun", "female equivalent of chanteur", form=True, tags=["form-of"])]}
        lk = self.lk(E=E)
        cl = lk.classify([T("mon", "DET"), T("amie", "NOUN"), T("allemande", "ADJ"), T("chanteuse", "NOUN")])
        self.assertEqual([(c[1], c[2]) for c in cl][1:],
                         [("ami", "w_ami"), ("allemand", "w_allemand"), ("chanteur", "w_chanteur")])

    def test_vetoed_word_never_comes_back_through_form_base(self):
        # sons: "plural of son"; the pack's son is the determiner (his); the English says sounds
        E = {"son": [entry("det", "his, her, its"), entry("noun", "sound")],
             "sons": [entry("noun", "plural of son", form=True, tags=["form-of", "masculine", "plural"])]}
        lk = self.lk({"sons": ("son", "NOUN")}, E=E)
        toks = [T("les", "DET"), T("sons", "NOUN")]
        self.assertIsNone(lk.classify(toks, "the sounds of the city")[1][2])
        lk = self.lk({}, E=E)                               # unresolved: form_base alone, same guard
        self.assertIsNone(lk.classify(toks, "the sounds of the city")[1][2])

    def test_derivations_never_link(self):
        E = {"drôlesse": [entry("noun", "an unintelligent woman", g="f|m=drôle"),
                          entry("noun", "female equivalent of drôle", form=True, tags=["form-of"])],
             "maisonnette": [entry("noun", "diminutive of maison", form=True, tags=["form-of", "feminine"])]}
        cl = self.lk(E=E).classify([T("une", "DET"), T("drôlesse", "NOUN"), T("maisonnette", "NOUN")])
        self.assertEqual([c[2] for c in cl][1:], [None, None])

    def test_pos_matched_key_wins(self):
        E = {"morte": [entry("adj", "feminine singular of mort", form=True, tags=["feminine", "form-of", "singular"])],
             "personnes": [entry("noun", "plural of personne", form=True, tags=["feminine", "form-of", "plural"])]}
        cl = self.lk(E=E).classify([T("morte", "ADJ"), T("personnes", "NOUN")])
        self.assertEqual([c[2] for c in cl], ["w_mort_a", "w_pers_n"])

    def test_fallback_ok_gates_the_cross_pos_lemma_fallback(self):
        E = {"ferme": [entry("adj", "firm"), entry("noun", "farm")]}
        lk = self.lk({"ferme": ("ferme", "NOUN")}, E=E)
        toks = [T("la", "DET"), T("ferme", "NOUN")]
        self.assertIsNone(lk.classify(toks, "the farm")[1][2])
        self.assertEqual(lk.classify(toks, "")[1][2], "w_ferme")


if __name__ == "__main__":
    unittest.main()
