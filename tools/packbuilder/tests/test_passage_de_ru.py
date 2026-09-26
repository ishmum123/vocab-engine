"""Tests for the German and Russian passage-only rules: the generic Linker
hooks (passage_mode, passage_particle_links, passage_lemma_alias,
nouns_capitalised, the article fallback, a verb reading never linking the
interjection, the ellipsis sentence start, passage_retag / passage_adverb_from,
passage_no_link, span_fold for spans and oop lemmas) and the language rules
behind them (German._sense_guards via passage_post_resolve, the passage_mode
gates in German.post_resolve helpers, Russian.passage_retag /
passage_no_link / span_fold). Stdlib only.

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
"""
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder import langs, passages  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import LanguageSpec  # noqa: E402
from packbuilder.passages import Linker, token_offsets  # noqa: E402

TMP = tempfile.mkdtemp()


def T(text, upos="X", lemma=None, morph=""):
    return [text, lemma or text.lower(), upos, morph]


def word(wid, lemma, group, pos, rank, lv="A1"):
    return {"id": wid, "w": lemma, "lemma": lemma, "pos": pos, "lv": lv, "rank": rank, "_key": [lemma, group]}


class FakeLex:
    """resolve_sentence by lowercase surface; the dictionary calls German's
    sense guards make, from tables."""

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


def linker(spec, lex, words):
    c = {"lexicon": lex, "groups": None, "truecase": (Counter(), Counter()), "words": words}
    return Linker(spec, c, {w["id"]: w for w in words})


def ids(cl):
    return {c[0]: c[2] for c in cl}


# ---- German -----------------------------------------------------------------

def de_spec(lex):
    sp = get_spec("de", TMP)
    sp._lex, sp._vscore = lex, {}
    return sp


class GermanSenseGuards(unittest.TestCase):
    """German.passage_post_resolve (_sense_guards): each QA rule on a minimal sentence."""

    def guard(self, toks, out, **lex):
        sp = de_spec(FakeLex(**lex))
        return sp.passage_post_resolve(toks, list(out))

    def test_heisse_next_to_subject_pronoun_is_the_verb(self):
        t = [T("Ich", "PRON", morph="Tag=PPER"), T("heiße", "VERB", morph="VerbForm=Fin|Tag=VVFIN"), T("Ana", "PROPN")]
        out = self.guard(t, [None, ("heiß", "ADJ"), None], cands={("heiße", "verb"): ["heißen"]})
        self.assertEqual(out[1], ("heißen", "VERB"))

    def test_liebe_salutation_is_the_adjective(self):
        t = [T("Liebe", "VERB", morph="Tag=ADJA"), T("Kunden", "NOUN", morph="Tag=NN")]
        out = self.guard(t, [("lieben", "VERB"), None], cands={("liebe", "adj"): ["lieb"]})
        self.assertEqual(out[0], ("lieb", "ADJ"))

    def test_meisten_is_viel_never_meister(self):
        t = [T("die", "DET"), T("meisten", "ADJ")]
        self.assertEqual(self.guard(t, [None, ("Meister", "NOUN")])[1], ("viel", "ADJ"))

    def test_am_liebsten_is_gern(self):
        t = [T("am", "ADP"), T("liebsten", "ADV")]
        self.assertEqual(self.guard(t, [None, ("lieb", "ADJ")])[1], ("gern", "ADV"))

    def test_role_als_is_the_conjunction_comparison_stays(self):
        t = [T("Er", "PRON", morph="Tag=PPER"), T("arbeitet", "VERB"), T("als", "ADP"), T("Lehrer", "NOUN")]
        self.assertEqual(self.guard(t, [None, None, ("als", "ADP"), None])[2], ("als", "CONJ"))
        t = [T("Er", "PRON"), T("ist", "AUX"), T("schneller", "ADJ", morph="Degree=Cmp|Tag=ADJD"), T("als", "ADP"),
             T("ich", "PRON")]
        self.assertEqual(self.guard(t, [None, None, None, ("als", "ADP"), None])[3], ("als", "ADP"))

    def test_indirect_wie_is_how(self):
        t = [T("Ich", "PRON"), T("weiß", "VERB"), T(",", "PUNCT"), T("wie", "ADV", morph="Tag=PWAV"),
             T("wir", "PRON"), T("leben", "VERB")]
        self.assertEqual(self.guard(t, [None] * 3 + [("wie", "CONJ")] + [None] * 2)[3], ("wie", "ADV"))
        t = [T("so", "ADV"), T("hoch", "ADJ"), T(",", "PUNCT"), T("wie", "ADV", morph="Tag=PWAV"), T("du", "PRON")]
        self.assertEqual(self.guard(t, [None] * 3 + [("wie", "CONJ"), None])[3], ("wie", "CONJ"))

    def test_allen_is_all_not_alles(self):
        t = [T("mit", "ADP"), T("allen", "PRON")]
        self.assertEqual(self.guard(t, [None, ("alles", "PRON")])[1], ("all", "PRON"))

    def test_bis_zu_a_number_is_the_preposition(self):
        t = [T("bis", "ADP"), T("zu", "ADV", morph="Tag=PTKA"), T("achtzehn", "NUM")]
        self.assertEqual(self.guard(t, [None, ("zu", "ADV"), None])[1], ("zu", "ADP"))
        t = [T("zu", "ADV", morph="Tag=PTKA"), T("viel", "ADV", morph="Tag=PIAT")]
        self.assertEqual(self.guard(t, [("zu", "ADV"), None])[0], ("zu", "ADV"))     # "zu viel": too

    def test_um_without_zu_infinitive_is_the_preposition(self):
        t = [T("kämpften", "VERB"), T("um", "SCONJ"), T("den", "DET", morph="Tag=ART"), T("Platz", "NOUN"),
             T(".", "PUNCT")]
        self.assertEqual(self.guard(t, [None, ("um", "CONJ"), None, None, None])[1], ("um", "ADP"))
        t = [T("um", "SCONJ"), T("Brot", "NOUN"), T("zu", "PART", morph="Tag=PTKZU"), T("kaufen", "VERB")]
        self.assertEqual(self.guard(t, [("um", "CONJ"), None, None, None])[0], ("um", "CONJ"))

    def test_lernt_kennen_joins_kennenlernen(self):
        t = [T("Sie", "PRON"), T("lernt", "VERB", morph="VerbForm=Fin|Tag=VVFIN"), T("Tom", "PROPN"),
             T("kennen", "VERB", morph="VerbForm=Inf|Tag=VVINF"), T(".", "PUNCT")]
        out = self.guard(t, [None, ("lernen", "VERB"), None, ("kennen", "VERB"), None])
        self.assertEqual(out[1], ("kennenlernen", "VERB"))
        self.assertIsNone(out[3])

    def test_pack_noun_that_is_also_a_place_outside_a_name_context(self):
        E = {"essen": [{"p": "noun", "s": [["food", None, [], ""]]}, {"p": "name", "s": [["a city", None, [], ""]]}]}
        cands = {("essen", "noun"): ["Essen"]}
        t = [T("macht", "VERB"), T("Essen", "PROPN", morph="Tag=NE"), T("für", "ADP")]
        self.assertEqual(self.guard(t, [None, ("essen", "PROPN"), None], E=E, cands=cands)[1], ("Essen", "NOUN"))
        t = [T("in", "ADP"), T("Essen", "PROPN", morph="Tag=NE")]
        self.assertEqual(self.guard(t, [None, ("essen", "PROPN")], E=E, cands=cands)[1], ("essen", "PROPN"))

    def test_nn_tagged_inflected_propn_is_the_noun(self):
        t = [T("isst", "VERB"), T("Äpfel", "PROPN", morph="Tag=NN"), T(".", "PUNCT")]
        out = self.guard(t, [None, ("äpfel", "PROPN"), None], cands={("äpfel", "noun"): ["Apfel"]})
        self.assertEqual(out[1], ("Apfel", "NOUN"))


class GermanPassageModeGates(unittest.TestCase):
    """Rules inside post_resolve helpers fire only while passages resolves (passage_mode)."""

    def setUp(self):
        self.sp = de_spec(FakeLex(cands={("blumen", "noun"): ["Blume"]}))

    def test_final_participle_before_und(self):
        self.sp._participle_targets = lambda low: ["hören"]
        t = [T("gehört", "VERB"), T("und", "CCONJ")]
        self.assertFalse(self.sp._final_participle(t, 0, "gehört"))
        self.sp.passage_mode = True
        self.assertTrue(self.sp._final_participle(t, 0, "gehört"))

    def test_name_context_after_determiner_and_plural_neighbour(self):
        t = [T("Meine", "DET"), T("Mutter", "NOUN", morph="Tag=NN"), T("Maria", "PROPN")]
        self.assertTrue(self.sp._name_context(t, 1))
        self.sp.passage_mode = True
        self.assertFalse(self.sp._name_context(t, 1))
        t = [T("schöne", "ADJ"), T("Rosen", "PROPN"), T("Blumen", "NOUN")]
        self.assertFalse(self.sp._name_context(t, 1))
        self.sp.passage_mode = False
        self.assertTrue(self.sp._name_context(t, 1))

    def test_attributive_salutation(self):
        t = [T("Liebe", "ADJ", morph="Tag=ADJA"), T("Kunden", "NOUN")]
        self.assertTrue(self.sp._attributive(t, 0))
        self.assertFalse(self.sp._attributive([T("Liebe", "ADJ", morph="Tag=ADJA"), T("!", "PUNCT")], 0))

    def test_build_post_resolve_never_calls_the_sense_guards(self):
        class Lex(FakeLex):
            F = {}

            def plural_pointer(self, w):
                return None
        sp = de_spec(Lex())
        calls = []
        sp._sense_guards = lambda toks, out: calls.append(1) or out
        t = [T("die", "DET"), T("meisten", "ADJ", morph="Tag=PIAT")]
        self.assertFalse(sp.passage_mode)
        sp.post_resolve(t, [("der", "DET"), ("Meister", "NOUN")])     # the corpus build's call
        self.assertEqual(calls, [])
        sp.passage_post_resolve(t, [("der", "DET"), ("Meister", "NOUN")])
        self.assertEqual(calls, [1])
        self.assertEqual(LanguageSpec.passage_mode, False)


class PassageModeScope(unittest.TestCase):
    def test_true_only_inside_the_wrapped_resolve(self):
        seen = []

        class Spec(LanguageSpec):
            def post_resolve(self, toks, out):
                seen.append(("post", self.passage_mode))
                return out

            def passage_post_resolve(self, toks, out):
                seen.append(("passage", self.passage_mode))
                return out

        sp = Spec(TMP)

        class Lex(FakeLex):
            def resolve_sentence(self, toks, groups=None):
                return sp.post_resolve(toks, [None] * len(toks))

        lex = Lex()
        lex.resolve_sentence([T("a")])                       # the corpus build: unwrapped
        linker(sp, lex, [])
        lex.resolve_sentence([T("a")])
        self.assertEqual(seen, [("post", False), ("post", True), ("passage", True)])
        self.assertFalse(sp.passage_mode)

    def test_reset_when_resolve_raises_and_prior_value_kept(self):
        sp = LanguageSpec(TMP)

        class Lex(FakeLex):
            def resolve_sentence(self, toks, groups=None):
                raise ValueError("tagger mismatch")

        lex = Lex()
        linker(sp, lex, [])
        with self.assertRaises(ValueError):
            lex.resolve_sentence([T("a")])
        self.assertFalse(sp.passage_mode)
        sp.passage_mode = True
        with self.assertRaises(ValueError):
            lex.resolve_sentence([T("a")])
        self.assertTrue(sp.passage_mode)

    def test_uses_the_lexicons_current_spec(self):
        first, second = LanguageSpec(TMP), LanguageSpec(TMP)
        seen = []
        second.passage_post_resolve = lambda toks, out: seen.append(second.passage_mode) or out
        lex = FakeLex()
        linker(first, lex, [])
        lex.spec = second                                   # load_context rebinds the lexicon's spec
        lex.resolve_sentence([T("a")])
        self.assertEqual(seen, [True])
        self.assertFalse(first.passage_mode)


DE_WORDS = [word("w_bitte", "bitte", "INTJ", "intj", 1), word("w_bitten", "bitten", "VERB", "verb", 2),
            word("w_viel", "viel", "ADJ", "adj", 3), word("w_der", "der", "DET", "art", 4),
            word("w_meister", "meister", "NOUN", "noun", 5), word("w_aufstehen", "aufstehen", "VERB", "verb", 6),
            word("w_er", "er", "PRON", "pron", 7)]


class GermanClassify(unittest.TestCase):
    """passages.Linker.classify with German's hooks (the resolve is a table)."""

    def cl(self, toks, res, **attrs):
        sp = get_spec("de", TMP)
        sp.passage_post_resolve = lambda toks, out: out
        for k, v in attrs.items():
            setattr(sp, k, v)
        return ids(linker(sp, FakeLex(res), DE_WORDS).classify(toks))

    def test_verb_reading_never_links_the_interjection(self):
        t = [T("Ich", "PRON"), T("bitte", "VERB"), T("Sie", "PRON")]
        self.assertEqual(self.cl(t, {"bitte": ("bitten", "VERB")})["bitte"], "w_bitten")
        self.assertEqual(self.cl(t, {"bitte": ("bitte", "INTJ")})["bitte"], "w_bitte")

    def test_lemma_alias(self):
        t = [T("viele", "PRON")]
        self.assertEqual(self.cl(t, {"viele": ("vieler", "PRON")})["viele"], "w_viel")
        self.assertIsNone(self.cl(t, {"viele": ("vieler", "PRON")}, passage_lemma_alias={})["viele"])

    def test_article_lemma_links_the_article(self):
        t = [T("der", "PRON")]
        self.assertEqual(self.cl(t, {"der": ("der", "PRON")})["der"], "w_der")

    def test_lowercase_token_never_falls_back_to_a_noun(self):
        t = [T("am", "ADP"), T("meisten", "ADJ")]
        self.assertIsNone(self.cl(t, {"meisten": ("meister", "ADJ")})["meisten"])
        self.assertEqual(self.cl(t, {"meisten": ("meister", "ADJ")}, nouns_capitalised=False)["meisten"],
                         "w_meister")

    def test_rejoined_separable_particle_is_the_verb(self):
        t = [T("Er", "PRON"), T("steht", "VERB"), T("früh", "ADV"), T("auf", "ADP"), T(".", "PUNCT")]
        res = {"er": ("er", "PRON"), "steht": ("aufstehen", "VERB")}
        self.assertEqual(self.cl(t, res)["auf"], "w_aufstehen")
        self.assertIsNone(self.cl(t, res, passage_particle_links=False)["auf"])


# ---- Russian ----------------------------------------------------------------

class RussianRetag(unittest.TestCase):
    def setUp(self):
        self.sp = get_spec("ru", TMP)

    def rt(self, toks):
        return self.sp.passage_retag([list(t) for t in toks])

    def test_correlative_tomu_is_tot(self):
        out = self.rt([T("Тому", "PROPN", "Том"), T(",", "PUNCT"), T("кто", "PRON")])
        self.assertEqual(out[0][:3], ["тому", "тот", "DET"])
        self.assertEqual(self.rt([T("Тому", "PROPN", "Том"), T("нравится", "VERB")])[0][2], "PROPN")

    def test_stoit_cost_or_stand(self):
        out = self.rt([T("Сколько", "ADV"), T("стоит", "VERB", "стоять"), T("билет", "NOUN")])
        self.assertEqual(out[1][1], "стоить")
        out = self.rt([T("Дом", "NOUN"), T("стоит", "VERB", "стоить"), T("у", "ADP"), T("реки", "NOUN")])
        self.assertEqual(out[1][1], "стоять")
        out = self.rt([T("стоит", "VERB", "стоять"), T("посмотреть", "VERB", morph="VerbForm=Inf")])
        self.assertEqual(out[0][1], "стоить")

    def test_novy_god_mid_sentence(self):
        out = self.rt([T("на", "ADP"), T("Новый", "PROPN", "новый"), T("Год", "PROPN", "Год")])
        self.assertEqual(out[1][:3], ["новый", "новый", "ADJ"])
        self.assertEqual(out[2][:3], ["год", "год", "NOUN"])

    def test_tseluyu_sign_off(self):
        out = self.rt([T("Целую", "ADJ", "целый"), T(",", "PUNCT"), T("мама", "NOUN")])
        self.assertEqual(out[0][1:3], ["целовать", "VERB"])
        out = self.rt([T("целую", "ADJ", "целый"), T("неделю", "NOUN")])
        self.assertEqual(out[0][1:3], ["целый", "ADJ"])

    def test_menshe_is_malo(self):
        self.assertEqual(self.rt([T("меньше", "NUM")])[0][1:3], ["мало", "ADV"])

    def test_drug_druga_links_nothing(self):
        self.assertEqual(self.sp.passage_no_link([T("друг"), T("другу")]), {0, 1})
        self.assertEqual(self.sp.passage_no_link([T("друг"), T("с", "ADP"), T("другом")]), {0, 2})
        self.assertEqual(self.sp.passage_no_link([T("мой"), T("друг")]), set())


RU_WORDS = [word("w_horosho", "хорошо", "ADV", "adv", 1), word("w_eshche", "еще", "ADV", "adv", 2),
            word("w_my", "мы", "PRON", "pron", 3), word("w_videt", "видеть", "VERB", "verb", 4),
            word("w_drug", "друг", "NOUN", "noun", 5)]


class RussianLinker(unittest.TestCase):
    def setUp(self):
        self.sp = get_spec("ru", TMP)

    def test_adverb_spelled_like_the_surface(self):
        lk = linker(self.sp, FakeLex(), RU_WORDS)
        toks = lk.retag([T("Хорошо", "ADJ", "хороший"), T("ещё", "NUM", "ещё"), T("хорошо", "NOUN")])
        self.assertEqual([t[1:3] for t in toks], [["хорошо", "ADV"], ["еще", "ADV"], ["хорошо", "NOUN"]])

    def test_no_retag_for_a_language_without_hooks(self):
        sp = get_spec("it", TMP)
        toks = [("Bene", "bene", "ADV", "")]
        self.assertIs(linker(sp, FakeLex(), RU_WORDS).retag(toks), toks)

    def test_ellipsis_starts_a_sentence(self):
        lk = linker(self.sp, FakeLex({"вижу": ("видеть", "VERB")}), RU_WORDS)
        for dots in ("...", "…", ".."):
            cl = lk.classify([T("Так", "ADV"), T(dots, "PUNCT"), T("Вижу", "VERB")])
            self.assertEqual(ids(cl).get("Вижу"), "w_videt", dots)
        cl = lk.classify([T("Так", "ADV"), T(",", "PUNCT"), T("Вижу", "VERB")])
        self.assertNotIn("Вижу", ids(cl))                   # a mid-sentence capital: a name

    def test_reciprocal_drug_counted_but_not_linked(self):
        lk = linker(self.sp, FakeLex({"друг": ("друг", "NOUN"), "другу": ("друг", "NOUN")}), RU_WORDS)
        cl = lk.classify([T("друг", "NOUN"), T("другу", "NOUN")])
        self.assertEqual([(c[2], c[3]) for c in cl], [("w_drug", False), ("w_drug", False)])

    def test_yo_folded_span(self):
        text = "Он живёт тут."
        toks = [T("Он"), T("живет"), T("тут"), T(".", "PUNCT")]
        self.assertIsNone(token_offsets(text, toks)[1])
        self.assertEqual(token_offsets(text, toks, self.sp.span_fold)[1], (3, 8))


class OopFold(unittest.TestCase):
    """run(): a declared oop lemma matches the tagger's ё-folded lemma; the report keeps the declared spelling."""

    def test_declared_yo_lemma(self):
        repo = Path(tempfile.mkdtemp())
        (repo / "tools").mkdir()
        (repo / "pack").mkdir()
        (repo / "pack" / "words.json").write_text(json.dumps(RU_WORDS))
        src = {"passages": [{"id": "p1", "lv": "A1", "title": "t", "sentences": [["Мы видим ёлку.", "We see a tree."]],
                             "oop": {"ёлка": "not in pack"}, "questions": []}]}
        (repo / "tools" / "passages_src.json").write_text(json.dumps(src, ensure_ascii=False))
        sp = get_spec("ru", str(repo))
        ctx = {"lexicon": FakeLex({"мы": ("мы", "PRON"), "видим": ("видеть", "VERB"), "ёлку": ("елка", "NOUN")}),
               "groups": None, "truecase": (Counter(), Counter()), "words": RU_WORDS}
        toks = [T("Мы", "PRON"), T("видим", "VERB"), T("ёлку", "NOUN", "елка"), T(".", "PUNCT")]
        out = io.StringIO()
        with mock.patch.object(passages, "load_context", lambda spec: ctx), \
                mock.patch.object(Linker, "pretag", lambda self, items: None), \
                mock.patch.object(Linker, "tag", lambda self, text, en="", names=frozenset(): toks), \
                mock.patch.object(Linker, "links", lambda self, toks, text, en, where=None: []):
            passages.run(sp, check_only=True, out=out)
        line = out.getvalue().splitlines()[0]
        self.assertIn("oop={'ёлка': 1}", line)
        self.assertNotIn("without a reason", line)
        self.assertNotIn("used nowhere", line)
        # a stale declaration prints as declared (ёлка), not folded
        src["passages"][0]["oop"]["ёжик"] = "not in pack"
        (repo / "tools" / "passages_src.json").write_text(json.dumps(src, ensure_ascii=False))
        out = io.StringIO()
        with mock.patch.object(passages, "load_context", lambda spec: ctx), \
                mock.patch.object(Linker, "pretag", lambda self, items: None), \
                mock.patch.object(Linker, "tag", lambda self, text, en="", names=frozenset(): toks), \
                mock.patch.object(Linker, "links", lambda self, toks, text, en, where=None: []):
            passages.run(sp, check_only=True, out=out)
        self.assertIn("used nowhere: ['ёжик']", out.getvalue())


class HookOwners(unittest.TestCase):
    def test_hook_owners(self):
        codes = sorted(f.stem for f in Path(langs.__file__).parent.glob("*.py") if f.stem not in ("__init__", "base"))
        own = lambda sp, name: getattr(sp, name) is not getattr(LanguageSpec, name)   # noqa: E731
        for m in codes:
            sp = langs.spec_class(m)
            self.assertEqual(bool(sp.passage_particle_links), m == "de", m)
            self.assertEqual(bool(sp.nouns_capitalised), m == "de", m)
            self.assertEqual(bool(sp.passage_lemma_alias), m in ("de", "fa", "ko", "ur"), m)
            self.assertEqual(bool(sp.passage_adverb_from), m == "ru", m)
            self.assertEqual(own(sp, "passage_retag"), m in ("ru", "fr", "id", "fa", "ko", "ja", "ar", "hi", "ur"), m)
            self.assertEqual(own(sp, "passage_no_link"), m == "ru", m)
            self.assertEqual(own(sp, "passage_post_resolve"), m in ("es", "de", "fr", "id", "fa", "ja", "hi"), m)
            self.assertEqual(bool(sp.passage_form_base), m == "fr", m)
            self.assertEqual(bool(sp.passage_names_never_link), m == "id", m)
            self.assertEqual(own(sp, "passage_text"), m in ("fr", "id", "ja"), m)
            for h in ("passage_fallback_ok", "passage_phrase_ranges"):
                self.assertEqual(own(sp, h), m in ("fr", "id", "ja"), (m, h))
            self.assertEqual(hasattr(sp, "passage_uncounted"), m in ("ja", "ar", "hi", "ur"), m)
            self.assertEqual(bool(getattr(sp, "passage_words_counted", False)), m in ("ja", "hi"), m)
            self.assertFalse(sp.passage_mode, m)
            self.assertFalse(sp.passage_tagging, m)


if __name__ == "__main__":
    unittest.main()
