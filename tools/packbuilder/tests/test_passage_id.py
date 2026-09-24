"""Tests for the Indonesian passage-only rules (langs/id.py): passage_post_resolve
(quotative katanya, baru after yang, homograph nouns, PASSAGE_COMPOUNDS and the
opaque idiom memberi tahu), passage_phrase_ranges, passage_retag (address
forms, PASSAGE_TITLES, -kan/-i and me- verb forms), the generic
passage_names_never_link in Linker.links_all, and the build pipeline applying
tools/gloss_display.json after finish_words. The pack, dictionary and
pipeline stages are stubbed. Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_passage_id.py     (from vocab-engine/)
"""
import json
import sys
import tempfile
import types
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.passages import Linker  # noqa: E402

TMP = tempfile.mkdtemp()
# (lemma, pos) of the stub pack
PACK = {("berkata", "verb"), ("kata", "noun"), ("baru", "adj"), ("baru", "adv"), ("cara", "noun"),
        ("bicara", "noun"), ("berbicara", "verb"), ("hidup", "verb"), ("hidup", "noun"), ("isi", "verb"),
        ("isi", "noun"), ("gambar", "verb"), ("gambar", "noun"), ("orang", "noun"), ("tua", "adj"),
        ("memberitahu", "verb"), ("beri", "verb"), ("tahu", "verb"), ("rumah", "noun"), ("sakit", "adj"),
        ("ketua", "noun"), ("bapak", "noun"), ("kembali", "verb"), ("mengembalikan", "verb"),
        ("temu", "verb"), ("menemukan", "verb"), ("mengunjungi", "verb"), ("hubung", "verb"),
        ("parkir", "verb"), ("ibu", "noun"), ("nenek", "noun"), ("tengah", "noun"), ("di", "prep")}


class FakeLex:
    def __init__(self, res=None):
        self.res = res or {}

    def usable_entries(self, w, kpos=None):
        return []

    def resolve_sentence(self, toks, groups=None):
        return [self.res.get(t[0].lower()) for t in toks]

    def readings(self, s):
        return []

    def zipf(self, w):
        return 0.0


def id_spec(lex=None):
    sp = get_spec("id", TMP)
    sp._pl = {}
    for lem, pos in sorted(PACK):
        sp._pl.setdefault(lem, pos)
    sp._pkeys = set(PACK)
    sp._lx = lex or FakeLex()
    sp._kaikki_words = lambda: {}
    return sp


def T(text, upos, lemma=None):
    return [text, lemma or text.lower(), upos, ""]


def post(toks, out):
    return id_spec().passage_post_resolve([list(t) for t in toks], list(out))


class Katanya(unittest.TestCase):
    def test_after_a_closing_quote(self):
        toks = [T("pintu", "NOUN"), T(",", "PUNCT"), T('"', "PUNCT"), T("kata", "NOUN"), T("nya", "PRON")]
        out = post(toks, [("pintu", "NOUN"), None, None, ("kata", "NOUN"), None])
        self.assertEqual(out[3], ("berkata", "VERB"))

    def test_after_punctuation_and_clause_initial(self):
        toks = [T("hutan", "NOUN"), T(".", "PUNCT"), T("Kata", "NOUN", "kata"), T("nya", "PRON"), T("seram", "ADJ")]
        self.assertEqual(post(toks, [None, None, ("kata", "NOUN"), None, None])[2], ("berkata", "VERB"))
        toks = [T("Kata", "NOUN", "kata"), T("nya", "PRON"), T("seram", "ADJ")]
        self.assertEqual(post(toks, [("kata", "NOUN"), None, None])[0], ("berkata", "VERB"))

    def test_beberapa_kata_stays_word(self):
        toks = [T("beberapa", "DET"), T("kata", "NOUN"), T("dalam", "ADP")]
        self.assertEqual(post(toks, [None, ("kata", "NOUN"), None])[1], ("kata", "NOUN"))
        toks = [T("beberapa", "DET"), T("kata", "NOUN"), T("nya", "PRON")]
        self.assertEqual(post(toks, [None, ("kata", "NOUN"), None])[1], ("kata", "NOUN"))


class BaruAfterYang(unittest.TestCase):
    def test_yang_baru_ada_is_new(self):
        for cop in ("ada", "adalah"):
            toks = [T("nomor", "NOUN"), T("saya", "PRON"), T("yang", "PRON"), T("baru", "ADJ"), T(cop, "VERB")]
            out = post(toks, [None, None, None, ("baru", "ADJ"), None])
            self.assertEqual(out[3], ("baru", "ADJ"), cop)

    def test_yang_baru_verb_is_just(self):
        toks = [T("orang", "NOUN"), T("yang", "PRON"), T("baru", "ADJ"), T("tinggal", "VERB"), T("di", "ADP")]
        self.assertEqual(post(toks, [None, None, ("baru", "ADJ"), None, None])[2], ("baru", "ADV"))


class HomographNoun(unittest.TestCase):
    def test_noun_after_cara(self):
        toks = [T("cara", "NOUN"), T("bicara", "VERB"), T("orang", "NOUN")]
        out = post(toks, [("cara", "NOUN"), ("berbicara", "VERB"), ("orang", "NOUN")])
        self.assertEqual(out[1], ("bicara", "NOUN"))

    def test_clause_initial_subject_is_the_noun(self):
        toks = [T("Ternyata", "ADV", "ternyata"), T("hidup", "VERB"), T("tanpa", "ADP"), T("ponsel", "NOUN")]
        self.assertEqual(post(toks, [None, ("hidup", "VERB"), None, None])[1], ("hidup", "NOUN"))
        toks = [T("bahwa", "SCONJ"), T("hidup", "VERB"), T("di", "ADP"), T("sana", "PRON")]
        self.assertEqual(post(toks, [None, ("hidup", "VERB"), None, None])[1], ("hidup", "NOUN"))

    def test_verb_before_an_object_stays_the_verb(self):
        toks = [T("Isi", "VERB", "isi"), T("botol", "NOUN"), T("itu", "DET")]
        self.assertEqual(post(toks, [("isi", "VERB"), None, None])[0], ("isi", "VERB"))
        toks = [T('"', "PUNCT"), T("Gambar", "VERB", "gambar"), T("rumah", "NOUN"), T("mu", "PRON"), T(",", "PUNCT"),
                T('"', "PUNCT"), T("kata", "VERB"), T("guru", "NOUN")]
        out = post(toks, [None, ("gambar", "VERB"), ("rumah", "NOUN"), None, None, None, ("berkata", "VERB"), None])
        self.assertEqual(out[1], ("gambar", "VERB"))

    def test_subject_before_the_verb_keeps_the_verb(self):
        toks = [T("kakek", "NOUN"), T("hidup", "VERB"), T("di", "ADP"), T("desa", "NOUN")]
        self.assertEqual(post(toks, [None, ("hidup", "VERB"), None, None])[1], ("hidup", "VERB"))


class Compounds(unittest.TestCase):
    def test_first_part_links_second_none(self):
        toks = [T("orang", "NOUN"), T("tua", "ADJ"), T("nya", "PRON"), T("datang", "VERB")]
        sp = id_spec()
        out = sp.passage_post_resolve(toks, [None, None, None, None])
        self.assertEqual(out[:2], [("orang", "NOUN"), None])
        self.assertEqual(sp.passage_phrase_ranges(toks), [(0, 1, 0)])

    def test_compound_that_is_a_pack_word(self):
        toks = [T("jangan", "PART"), T("beri", "VERB"), T("tahu", "VERB"), T("dia", "PRON")]
        sp = id_spec()
        out = sp.passage_post_resolve(toks, [None, ("beri", "VERB"), ("tahu", "VERB"), None])
        self.assertEqual(out[1:3], [("memberitahu", "VERB"), None])
        self.assertEqual(sp.passage_phrase_ranges(toks), [(1, 2, 1)])

    def test_target_outside_the_pack_is_left_alone(self):
        sp = id_spec()
        sp._pkeys = set(PACK) - {("rumah", "noun")}
        toks = [T("rumah", "NOUN"), T("sakit", "ADJ")]
        self.assertEqual(sp.passage_post_resolve(toks, [None, ("sakit", "ADJ")]), [None, ("sakit", "ADJ")])
        self.assertEqual(sp.passage_phrase_ranges(toks), [])

    def test_memberi_tahu_opaque_idiom(self):
        toks = [T("memberi", "VERB", "beri"), T("tahu", "VERB")]
        sp = id_spec()
        self.assertEqual(sp.passage_post_resolve(toks, [None, None])[0], ("memberitahu", "VERB"))
        self.assertEqual(sp.passage_phrase_ranges(toks), [(0, 1, 0)])


class Retag(unittest.TestCase):
    def retag(self, toks):
        return id_spec().passage_retag([list(t) for t in toks])

    def test_title_noun_mid_sentence(self):
        out = self.retag([T("Bapak", "NOUN", "bapak"), T("Ketua", "PROPN", "ketua"), T("RT", "PROPN", "rt")])
        self.assertEqual(out[1][:3], ["ketua", "ketua", "NOUN"])
        self.assertEqual(out[2][2], "PROPN")

    def test_address_forms(self):
        out = self.retag([T("pagi", "NOUN"), T(",", "PUNCT"), T("Bu", "PROPN", "bu")])
        self.assertEqual(out[2][:3], ["bu", "ibu", "NOUN"])
        out = self.retag([T("Kemudian", "ADV", "kemudian"), T("Nenek", "PROPN", "nenek"), T("pulang", "VERB")])
        self.assertEqual(out[1][:3], ["nenek", "nenek", "NOUN"])

    def test_kan_i_forms_read_as_the_me_verb(self):
        out = self.retag([T("dikembalikan", "VERB", "kembali"), T("ditemukan", "VERB", "temu"),
                          T("kunjungi", "VERB", "kunjung")])
        self.assertEqual([t[1] for t in out], ["mengembalikan", "menemukan", "mengunjungi"])

    def test_older_verb_rules(self):
        out = self.retag([T("hubungi", "VERB", "bubung"), T("memarkir", "VERB", "memarkir")])
        self.assertEqual([t[1:3] for t in out], [["hubung", "VERB"], ["parkir", "VERB"]])


def word(wid, lemma, group, pos):
    return {"id": wid, "w": lemma, "lemma": lemma, "pos": pos, "lv": "A1", "rank": 1, "_key": [lemma, group], "en": ""}


class NamesNeverLink(unittest.TestCase):
    def test_multiword_name_unlinked_and_not_counted(self):
        lex = FakeLex({"di": ("di", "ADP"), "tengah": ("tengah", "NOUN")})
        sp = id_spec(lex)
        sp.passage_post_resolve = lambda toks, out: out
        words = [word("w_di", "di", "ADP", "prep"), word("w_tengah", "tengah", "NOUN", "noun")]
        lk = Linker(sp, {"lexicon": lex, "groups": None, "truecase": (Counter(), Counter()), "words": words},
                    {w["id"]: w for w in words})
        # the tagger lowercased Tengah (PROPN rescue); the name test reads the text
        toks = [T("di", "ADP"), T("Jawa", "PROPN", "jawa"), T("tengah", "NOUN")]
        lk.links = lambda toks, text, en, where: where.extend([("tok", 0, 0, "w_di"), ("tok", 2, 2, "w_tengah")]) \
            or ["w_di", "w_tengah"]
        ids, cl, spans, _claimed = lk.links_all(toks, "di Jawa Tengah", "", frozenset({"Jawa", "Tengah"}))
        self.assertEqual(ids, ["w_di"])
        self.assertEqual(spans, [[0, 2, "w_di"]])
        self.assertNotIn(2, [c[4] for c in cl])
        # lowercase tengah (not the name) still links
        toks = [T("di", "ADP"), T("tengah", "NOUN")]
        lk.links = lambda toks, text, en, where: where.extend([("tok", 0, 0, "w_di"), ("tok", 1, 1, "w_tengah")]) \
            or ["w_di", "w_tengah"]
        ids, _cl, _spans, _c = lk.links_all(toks, "di tengah", "", frozenset({"Jawa", "Tengah"}))
        self.assertEqual(ids, ["w_di", "w_tengah"])


class PipelineGlossDisplay(unittest.TestCase):
    def test_display_applied_after_finish_words(self):
        from packbuilder.core import pipeline
        repo = Path(tempfile.mkdtemp())
        (repo / "tools").mkdir()
        (repo / "tools" / "gloss_display.json").write_text(json.dumps({"orang|noun": "person; (orang tua) parents"}))
        sp = get_spec("id", str(repo))
        env = types.SimpleNamespace(spec=sp, pack=repo / "pack", derived=repo / "derived")
        env.derived.mkdir()
        w = {"id": "w0001", "w": "orang", "lemma": "orang", "pos": "noun", "en": "person", "lv": "A1", "rank": 1}
        seen = []

        def prepare(env, ctx):
            ctx.update(lexicon=mock.MagicMock(), raw_upos={})

        def finish(env, ctx, words, records, top):
            seen.append(("finish", words[0]["en"]))
            return words, records, top, [{"id": "s1", "t": "x", "words": ["w0001"]}], {}, {}

        real = pipeline.apply_gloss_display

        def display(repo_, out_words, path):
            seen.append(("display", out_words[0]["en"]))
            return real(repo_, out_words, path)
        with mock.patch.object(pipeline, "ensure_downloaded", lambda *a: None), \
                mock.patch.object(pipeline, "prepare", prepare), \
                mock.patch.object(pipeline, "build_words", lambda env, ctx: ([dict(w)], {}, [])), \
                mock.patch.object(pipeline, "finish_words", finish), \
                mock.patch.object(pipeline, "apply_gloss_display", display), \
                mock.patch.object(pipeline, "build_pack_json", lambda *a: {}), \
                mock.patch.object(pipeline, "attribution", lambda *a: {}), \
                mock.patch.object(pipeline, "write_report", lambda *a: None), \
                mock.patch.object(pipeline, "dump_json", lambda *a: None):
            pipeline.run(env)
        self.assertEqual(seen, [("finish", "person"), ("display", "person")])
        shipped = json.loads((env.pack / "words.json").read_text())
        self.assertEqual(shipped[0]["en"], "person; (orang tua) parents")
        self.assertEqual(json.loads((env.pack / "sentences.json").read_text())[0]["words"], ["w0001"])


if __name__ == "__main__":
    unittest.main()
