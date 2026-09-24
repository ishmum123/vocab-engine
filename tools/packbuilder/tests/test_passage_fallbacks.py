"""Tests for the passage-only link fallbacks and truecasing (passages.Linker
classify, core.tag.truecase_after, spec.truecase_after /
surface_reading_fallback) and es's passage-only fue/fui/fuera rule (Spanish.passage_post_resolve).
Stdlib only.

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
"""
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder import langs  # noqa: E402
from packbuilder.core.tag import truecase_after  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import LanguageSpec  # noqa: E402
from packbuilder.passages import Linker  # noqa: E402

TMP = tempfile.mkdtemp()
WORD_RE = re.compile(r"[^\W\d_]+")


class FakeLex:
    """resolve_sentence by surface, readings and zipf from tables."""

    def __init__(self, res, readings=None, zipf=None):
        self.res, self.rd, self.z = res, readings or {}, zipf or {}

    def resolve_sentence(self, toks, groups=None):
        return [self.res.get(t[0].lower()) for t in toks]

    def readings(self, s):
        return sorted(self.rd.get(s, []))

    def zipf(self, w):
        return self.z.get(w, 0.0)


def word(wid, lemma, group, pos, rank):
    return {"id": wid, "w": lemma, "lemma": lemma, "pos": pos, "lv": "A1", "rank": rank, "_key": [lemma, group]}


WORDS = [word("p1", "por favor", "PHRASE", "phrase", 9), word("w_por", "por", "ADP", "prep", 1),
         word("w_leer", "leer", "VERB", "verb", 2), word("w_lucir", "lucir", "VERB", "verb", 3),
         word("w_aaa", "aaa", "NOUN", "noun", 4), word("w_bbb", "bbb", "VERB", "verb", 5),
         word("w_yo", "yo", "PRON", "pron", 6)]


def linker(spec, lex):
    c = {"lexicon": lex, "groups": None, "truecase": (Counter(), Counter()), "words": WORDS}
    return Linker(spec, c, {w["id"]: w for w in WORDS})


def T(text, upos="X", lemma=None, morph=""):
    return [text, lemma or text.lower(), upos, morph]


def ids(cl):
    return {c[0]: c[2] for c in cl}


class PhrasePartFallback(unittest.TestCase):
    def test_token_inside_pack_phrase_links_the_phrase(self):
        sp = get_spec("es", TMP)
        lex = FakeLex({"por": ("por", "ADP"), "favor": ("favor", "NOUN")})
        cl = linker(sp, lex).classify([T("Por", "ADP"), T("favor", "NOUN"), T(".", "PUNCT")])
        self.assertEqual(ids(cl), {"Por": "w_por", "favor": "p1"})

    def test_same_word_outside_the_phrase_stays_unlinked(self):
        sp = get_spec("es", TMP)
        lex = FakeLex({"por": ("por", "ADP"), "favor": ("favor", "NOUN"), "un": ("uno", "DET")})
        cl = linker(sp, lex).classify([T("un", "DET"), T("favor", "NOUN")])
        self.assertIsNone(ids(cl)["favor"])


class PhrasePartCoverage(unittest.TestCase):
    """classify maps a token to the phrase match covering it, and cue-gated
    phrases follow the English as in sentence_links."""
    WORDS2 = [word("p_fav", "por favor", "PHRASE", "phrase", 1), word("p_sup", "por supuesto", "PHRASE", "phrase", 2),
              word("p_nada", "de nada", "PHRASE", "phrase", 3)]

    def lk(self):
        lex = FakeLex({})
        c = {"lexicon": lex, "groups": None, "truecase": (Counter(), Counter()), "words": self.WORDS2}
        return Linker(get_spec("es", TMP), c, {w["id"]: w for w in self.WORDS2})

    def test_token_links_the_phrase_that_covers_it(self):
        t = [T("Por", "ADP"), T("supuesto", "ADJ"), T(",", "PUNCT"), T("por", "ADP"), T("favor", "NOUN")]
        cl = self.lk().classify(t)
        self.assertEqual([c[2] for c in cl], ["p_sup", "p_sup", "p_fav", "p_fav"])

    def test_cue_phrase_needs_the_english(self):
        t = [T("No", "ADV"), T("la", "PRON"), T("conozco", "VERB"), T("de", "ADP"), T("nada", "PRON")]
        cl = self.lk().classify(t, "I don't know her at all.")
        self.assertIsNone(ids(cl)["nada"])
        cl = self.lk().classify([T("De", "ADP"), T("nada", "PRON")], "You're welcome.")
        self.assertEqual(ids(cl)["nada"], "p_nada")


class SurfaceReadingFallback(unittest.TestCase):
    def setUp(self):
        self.lex = FakeLex({"yo": ("yo", "PRON"), "leo": ("leo", "PROPN"), "x": ("x", "ADJ"),
                            "lucía": ("lucía", "PROPN")},
                           readings={"leo": [("leer", "VERB"), ("leo", "NOUN")],
                                     "x": [("aaa", "NOUN"), ("bbb", "VERB"), ("zzz", "NOUN")],
                                     "lucía": [("lucir", "VERB")]},
                           zipf={"leer": 5.0, "aaa": 3.0, "bbb": 4.0, "zzz": 7.0})

    def test_lowercase_propn_links_pack_reading(self):
        cl = linker(get_spec("es", TMP), self.lex).classify([T("Yo", "PRON"), T("leo", "PROPN")])
        self.assertEqual(cl[1][:3], ("leo", "leer", "w_leer"))

    def test_most_frequent_pack_reading_wins(self):
        # zzz is more frequent but not a pack word
        cl = linker(get_spec("es", TMP), self.lex).classify([T("yo", "PRON"), T("x", "ADJ")])
        self.assertEqual(cl[1][1:3], ("bbb", "w_bbb"))

    def test_sentence_initial_propn_is_a_lowered_name(self):
        # the truecaser lowered "Lucía": not lucir
        cl = linker(get_spec("es", TMP), self.lex).classify([T("lucía", "PROPN"), T("yo", "PRON")])
        self.assertEqual(cl[0][:3], ("lucía", "lucía", None))
        # after a sentence end it is sentence-initial again
        cl = linker(get_spec("es", TMP), self.lex).classify(
            [T("yo", "PRON"), T(".", "PUNCT"), T("lucía", "PROPN")])
        self.assertIsNone(ids(cl)["lucía"])

    def test_propn_lowered_by_truecase_after_is_a_name(self):
        # «¡Leo, ven!»: truecase_after lowered Leo mid-sentence: not leer
        t = [T("Dice", "VERB"), T("«", "PUNCT"), T("¡", "PUNCT"), T("leo", "PROPN")]
        lk = linker(get_spec("es", TMP), self.lex)
        self.assertIsNone(lk.classify(t, None, {3})[-1][2])
        self.assertEqual(lk.classify(t)[-1][2], "w_leer")

    def test_off_by_default(self):
        self.assertFalse(LanguageSpec.surface_reading_fallback)
        sp = get_spec("es", TMP)
        sp.surface_reading_fallback = False
        cl = linker(sp, self.lex).classify([T("Yo", "PRON"), T("leo", "PROPN")])
        self.assertIsNone(cl[1][2])

    def test_only_spanish_enables_passage_hooks(self):
        codes = sorted(f.stem for f in Path(langs.__file__).parent.glob("*.py")
                       if f.stem not in ("__init__", "base"))
        self.assertIn("it", codes)
        for m in codes:
            sp = langs.spec_class(m)
            on = sp.code == "es"
            self.assertEqual(bool(sp.surface_reading_fallback), on, m)
            self.assertEqual(bool(sp.truecase_after), on, m)
            self.assertEqual(bool(sp.truecase_after_end), on, m)


class TruecaseAfter(unittest.TestCase):
    def setUp(self):
        self.low = Counter({"me": 50, "feliz": 20, "qué": 30})
        self.cap = Counter({"me": 1, "feliz": 2, "ana": 40})

    def tc(self, text, openers="«¡¿"):
        return truecase_after(text, self.low, self.cap, WORD_RE, openers)

    def test_first_word_of_quoted_or_exclaimed_speech(self):
        self.assertEqual(self.tc("Dice: «Me gusta».", ), "Dice: «me gusta».")
        self.assertEqual(self.tc("Gritaron: «¡Feliz cumpleaños!»"), "Gritaron: «¡feliz cumpleaños!»")
        self.assertEqual(self.tc("Y ¿Qué pasa?"), "Y ¿qué pasa?")

    def test_names_all_caps_and_other_positions_kept(self):
        self.assertEqual(self.tc("Dijo: «Ana viene»."), "Dijo: «Ana viene».")
        self.assertEqual(self.tc("Dijo: «ME GUSTA»."), "Dijo: «ME GUSTA».")
        self.assertEqual(self.tc("Me gusta. Me voy."), "Me gusta. Me voy.")     # plain truecase's job
        self.assertEqual(self.tc("« Me gusta»"), "« Me gusta»")                 # not right after the opener

    def test_after_mid_text_exclamation_or_question(self):
        low, cap = Counter({"compro": 9, "vale": 9}), Counter({"ana": 9})
        known = {"compro", "vale", "ana"}.__contains__
        tc = lambda text, k=known: truecase_after(text, low, cap, WORD_RE, "«¡¿", "!?", k)
        self.assertEqual(tc("—¡Perfecto! Compro dos."), "—¡perfecto! compro dos.")
        self.assertEqual(tc("¿Vienes? Vale."), "¿vienes? vale.")
        self.assertEqual(tc("¡Hola! Ana viene."), "¡hola! Ana viene.")          # a name by the corpus counts
        self.assertEqual(tc("¡Hola! Compro.", lambda w: False), "¡hola! Compro.")   # no lowercase reading
        self.assertEqual(tc("Hola. Compro."), "Hola. Compro.")                  # only ! ?
        self.assertEqual(tc("¡Hola!Compro."), "¡hola!Compro.")                  # needs the space
        # off without enders (every other language)
        self.assertEqual(truecase_after("¡Hola! Compro.", low, cap, WORD_RE, "", "", known), "¡Hola! Compro.")

    def test_no_openers_is_identity(self):
        self.assertEqual(self.tc("Dice: «Me gusta».", ""), "Dice: «Me gusta».")

    def test_pretag_applies_spec_openers(self):
        class Spec:
            homograph_by_translation = False
            word_re = WORD_RE
            morph_keep = ()
            tagger, spacy_model = "stanza", None
            truecase_after = "«"
            truecase_after_end = ""
            span_fold, span_joiners = None, ""

            def __init__(self):
                self.seen = []

            def tag_text(self, t):
                return t

            def tag_texts(self, texts):
                self.seen += texts
                return [[(w, w, "X", {}) for w in re.findall(r"\w+|[^\w\s]", t)] for t in texts]

            def fix_token(self, tok):
                return tok

            def fix_sentence(self, toks, row, doc):
                return toks

        sp = Spec()
        lk = Linker(sp, {"lexicon": None, "groups": None, "truecase": (self.low, self.cap), "words": []}, {})
        lk.pretag([("Me dice «Me gusta»", "")])
        self.assertEqual(sp.seen, ["me dice «me gusta»"])
        self.assertEqual(lk.lowered[("Me dice «Me gusta»", "")], {3})   # "me" of «Me: not the initial Me


class LexSpec(LanguageSpec):
    """post_resolve depends on the lexicon bound by bind_lexicon (as es _lex,
    fr _lx), on an attribute that exists before the build and bind_lexicon
    edits in place (as id voice_alt), and on en_stem over the corpus English
    vocabulary prepare() fills (as id _gloss_stems); bind_lexicon also edits
    the lexicon in place (as de/fr/id)."""
    code = "xx"

    def __init__(self, repo=None):
        super().__init__(repo)
        self.voice_alt = {}

    def bind_lexicon(self, lexicon):
        self._lx = lexicon
        self.voice_alt["dibaca"] = "baca"
        lexicon.edits += 1

    def post_resolve(self, toks, out):
        from packbuilder.core.english import en_stem
        lx = getattr(self, "_lx", None)
        return [("bound" if lx is not None else "unbound", self.voice_alt.get("dibaca"), en_stem("cats"))
                for r in out]


class PickleLex:
    def __init__(self, spec):
        self.spec, self.edits = spec, 0
        spec.bind_lexicon(self)


class CachedContext(unittest.TestCase):
    """load_context: a cached (unpickled) run restores the spec state the
    fresh run's bind_lexicon set, without repeating its lexicon edits."""

    def test_cached_equals_fresh(self):
        import json
        from packbuilder import passages
        from packbuilder.core import pipeline, words as corewords
        repo = Path(tempfile.mkdtemp())
        (repo / "pack").mkdir()
        (repo / "tools").mkdir()
        (repo / ".cache" / "derived").mkdir(parents=True)
        w = {"id": "w1", "w": "a", "lemma": "a", "pos": "noun", "lv": "A1", "en": "a", "rank": 1, "_key": ["a", "NOUN"]}
        (repo / "pack" / "words.json").write_text(json.dumps([{k: w[k] for k in ("id", "w", "lemma", "pos", "lv")}]))

        from packbuilder.core import english

        def prepare(env, ctx):
            english.EN_VOCAB.add("cat")
            ctx.update(lexicon=PickleLex(env.spec), lemma_groups={}, truecase=(Counter(), Counter()))
        saved = pipeline.prepare, pipeline.finish_words, corewords.build_words
        saved_en = set(english.EN_VOCAB), dict(english._STEM)
        pipeline.prepare = prepare
        pipeline.finish_words = lambda env, ctx, words, records, top: (words,)
        corewords.build_words = lambda env, ctx: ([dict(w)], None, None)
        try:
            results = []
            for run in ("fresh", "cached"):
                # a new process: the module-level English vocabulary starts empty
                english.EN_VOCAB.clear()
                english._STEM.clear()
                sp = LexSpec(repo)
                c = passages.load_context(sp)
                results.append((sp.post_resolve([None], [("a", "NOUN")]), c["lexicon"].edits,
                                c["lexicon"] is sp._lx, sorted(c)))
        finally:
            pipeline.prepare, pipeline.finish_words, corewords.build_words = saved
            passages._set_english(*saved_en)
        self.assertEqual(len(list((repo / ".cache" / "derived").glob("passages_ctx_*.pkl"))), 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1][:3], ([("bound", "baca", "cat")], 1, True))


class FueFuera(unittest.TestCase):
    """es passage_post_resolve (passages only): fue/fui/fuera between ser, ir and the adverb fuera."""

    def setUp(self):
        self.sp = get_spec("es", TMP)

    def run_rule(self, toks, i, start):
        out = [None] * len(toks)
        out[i] = start
        return self.sp.passage_post_resolve(toks, self.sp.post_resolve(toks, out))[i]

    def test_build_resolve_untouched(self):
        # the corpus build (post_resolve alone) keeps fue a -> ir and fuera as tagged
        t = [T("Lo", "PRON"), T("que", "PRON"), T("aprendí", "VERB", morph="VerbForm=Fin"),
             T("fue", "AUX"), T("a", "ADP"), T("confiar", "VERB")]
        self.assertEqual(self.sp.post_resolve(t, [None, None, None, ("ser", "VERB"), None, None])[3], ("ir", "VERB"))
        t = [T("Vive", "VERB"), T("fuera", "ADV"), T("de", "ADP")]
        self.assertEqual(self.sp.post_resolve(t, [None, ("ser", "VERB"), None])[1], ("ser", "VERB"))

    def test_linker_applies_passage_hook_once(self):
        lex = FakeLex({"fuera": ("ser", "VERB")})
        calls = []
        sp = get_spec("es", TMP)
        sp.passage_post_resolve = lambda toks, out: calls.append(1) or [("fuera", "ADV")] * len(out)
        c = {"lexicon": lex, "groups": None, "truecase": (Counter(), Counter()), "words": WORDS}
        Linker(sp, c, {w["id"]: w for w in WORDS})
        Linker(sp, c, {w["id"]: w for w in WORDS})          # a second Linker does not wrap twice
        self.assertEqual(lex.resolve_sentence([T("fuera")]), [("fuera", "ADV")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(LanguageSpec.passage_post_resolve(None, [], ["x"]), ["x"])

    def test_fuera_adverb(self):
        t = [T("Vive", "VERB"), T("fuera", "ADV"), T("de", "ADP"), T("la", "DET"), T("ciudad", "NOUN")]
        self.assertEqual(self.run_rule(t, 1, ("ser", "VERB")), ("fuera", "ADV"))
        t = [T("Lo", "PRON"), T("pintó", "VERB"), T("por", "ADP"), T("fuera", "VERB")]
        self.assertEqual(self.run_rule(t, 3, ("ser", "VERB")), ("fuera", "ADV"))
        t = [T("Salimos", "VERB"), T("fuera", "VERB"), T(".", "PUNCT")]
        self.assertEqual(self.run_rule(t, 1, ("ir", "VERB")), ("fuera", "ADV"))

    def test_fuera_subjunctive_kept(self):
        t = [T("Si", "SCONJ"), T("yo", "PRON"), T("fuera", "AUX"), T("rico", "ADJ")]
        self.assertEqual(self.run_rule(t, 2, ("ser", "VERB")), ("ser", "VERB"))
        t = [T("Si", "SCONJ"), T("fuera", "AUX"), T(".", "PUNCT")]
        self.assertEqual(self.run_rule(t, 1, ("ser", "VERB")), ("ser", "VERB"))

    def test_fuera_after_subordinator_or_pronoun_kept(self):
        for prv in ("aunque", "cuando", "mientras", "porque", "tú"):
            t = [T(prv, "SCONJ"), T("fuera", "AUX"), T("de", "ADP"), T("noche", "NOUN")]
            self.assertEqual(self.run_rule(t, 1, ("ser", "VERB")), ("ser", "VERB"), prv)
            t = [T(prv, "SCONJ"), T("fuera", "AUX"), T(".", "PUNCT")]
            self.assertEqual(self.run_rule(t, 1, ("ser", "VERB")), ("ser", "VERB"), prv)

    def test_cleft_fue_a_is_ser(self):
        t = [T("Lo", "PRON"), T("que", "PRON"), T("aprendí", "VERB", morph="VerbForm=Fin"),
             T("fue", "AUX"), T("a", "ADP"), T("confiar", "VERB")]
        self.assertEqual(self.run_rule(t, 3, ("ir", "VERB")), ("ser", "VERB"))

    def test_fue_a_place_stays_ir(self):
        t = [T("Ana", "PROPN"), T("fue", "AUX"), T("a", "ADP"), T("Madrid", "PROPN")]
        self.assertEqual(self.run_rule(t, 1, ("ser", "VERB")), ("ir", "VERB"))

    def test_fui_una_de_and_fue_adjective_are_ser(self):
        t = [T("Yo", "PRON"), T("fui", "AUX"), T("una", "PRON"), T("de", "ADP"), T("ellas", "PRON")]
        self.assertEqual(self.run_rule(t, 1, ("ir", "VERB")), ("ser", "VERB"))
        t = [T("La", "DET"), T("fiesta", "NOUN"), T("fue", "AUX"), T("muy", "ADV"), T("agradable", "ADJ")]
        self.assertEqual(self.run_rule(t, 2, ("ir", "VERB")), ("ser", "VERB"))
        t = [T("Fue", "AUX"), T("elegido", "VERB", morph="VerbForm=Part")]
        self.assertEqual(self.run_rule(t, 0, ("ir", "VERB")), ("ser", "VERB"))


if __name__ == "__main__":
    unittest.main()
