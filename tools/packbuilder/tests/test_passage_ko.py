"""Tests for the Korean passage-only rules (langs/ko.py): passage_retag with
declared names (passage_retag_names), numeral compounds (every part links), counters,
날/알리다/번 homographs, X+하고 and unknown X되다 forms of pack verbs, 저, 자기,
noun + particle splits the analyser got wrong, the -님 suffix, and the
passage_lemma_alias fallback for X하다/X되다. The analyser and the pack are
stubbed. Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_passage_ko.py     (from vocab-engine/)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402

PACK = {"학생", "이름", "살", "살다", "사다", "자다", "앞", "교수", "빵", "차", "시", "원", "전", "잠", "자기",
        "저", "운동", "요리", "중독", "날", "알다", "알리다", "번", "벌다", "돈", "시작", "시작하다", "발견되다",
        "사이", "층"}
NOUNS = {"학생", "이름", "살", "앞", "교수", "빵", "차", "시", "원", "전", "잠", "자기", "저", "운동", "요리", "중독",
         "날", "번", "돈", "시작", "사이", "층"}
NOUN = "Ko=noun|G=NOUN|X="
NUMK = "Ko=num|G=NUM|X="


class FakeMorph:
    pos = {}

    def analyse(self, E, hint=None):
        return {"자요": ("verb", [("자요", "자다", "VERB")])}.get(E)

    def candidates(self, E, hint=None):
        return {"사면": [(0, "verb", [("사면", "사다", "VERB")])],
                "앞에서": [(0.5, "exact", [("앞에서", "앞에서", "ADV")])]}.get(E, [])


def spec():
    sp = get_spec("ko", "/nonexistent-ko-repo", load=False)
    sp._morph = FakeMorph()
    sp._ppack = (PACK, NOUNS)
    sp._patch_wordfreq = lambda: None
    return sp


def T(text, lemma=None, upos="NOUN", ms="Ko=unk|X="):
    return [text, lemma if lemma is not None else text, upos, ms]


def P(text, key):
    return [text, key, "X", "Ko=noun|G=PART|X="]


def retag(toks, names=()):
    return [(t[0], t[1], t[2]) for t in spec().passage_retag([list(t) for t in toks], frozenset(names))]


class Names(unittest.TestCase):
    def test_unknown_eojeol_splits(self):
        self.assertEqual(retag([T("민수는"), T("학생"), P("이에요", "-이다")], ["민수"])[:2],
                         [("민수", "민수", "PROPN"), ("는", "-은/는", "X")])

    def test_copula_cut_wrongly(self):
        self.assertEqual(retag([T("김민수예", upos="PROPN"), P("요", "-요")], ["김민수"]),
                         [("김민수", "김민수", "PROPN"), ("예요", "-이다", "X")])

    def test_name_split_by_tagger(self):
        self.assertEqual(retag([T("유"), P("나", "-(이)나")], ["유나"]), [("유나", "유나", "PROPN")])

    def test_familiar_suffix(self):
        self.assertEqual(retag([T("지영이는")], ["지영"]),
                         [("지영", "지영", "PROPN"), ("이", "이", "X"), ("는", "-은/는", "X")])

    def test_word_prefix_is_not_a_name(self):
        self.assertEqual(retag([T("한국어", upos="NOUN"), P("를", "-을/를")], ["한국"])[0], ("한국어", "한국어", "NOUN"))

    def test_no_names_keeps_tokens(self):
        self.assertEqual(retag([T("학생", ms="Ko=noun|G=NOUN|X=")]), [("학생", "학생", "NOUN")])


class Numerals(unittest.TestCase):
    """Every part of a numeral compound links (삼만 -> 삼 + 만), never the first digit alone."""
    def test_sino_compound_before_counter(self):
        self.assertEqual(retag([T("이천"), T("원", ms=NOUN)]),
                         [("이", "이:num", "NUM"), ("천", "천:num", "NUM"), ("원", "원", "NOUN")])

    def test_sino_three_parts(self):
        self.assertEqual([t[1] for t in retag([T("오십만"), T("원", ms=NOUN)])], ["오:num", "십:num", "만:num", "원"])

    def test_sino_digit_plus_particle_man(self):
        # 삼만 원: the tagger cuts 삼 + the particle -만 "only"
        self.assertEqual(retag([T("삼", "삼:num", "NUM", NUMK), P("만", "-만"), T("원", ms=NOUN)])[:2],
                         [("삼", "삼:num", "NUM"), ("만", "만:num", "NUM")])

    def test_sino_digit_particle_man_without_counter_stays(self):
        self.assertEqual(retag([T("삼", "삼:num", "NUM", NUMK), P("만", "-만")])[1], ("만", "-만", "X"))

    def test_sino_compound_without_counter_stays(self):
        self.assertEqual(retag([T("이천"), T("학생")])[0][2], "NOUN")

    def test_known_word_before_particle_do_stays(self):
        # 사이도: 사이 "between" + the particle -도, not 사 + 이 before the counter 도
        self.assertEqual(retag([T("사이", ms=NOUN), P("도", "-도")])[0], ("사이", "사이", "NOUN"))

    def test_native_compound(self):
        out = retag([T("열네"), T("살", "살다", "VERB", "Ko=verb|G=VERB|X=")])
        self.assertEqual(out, [("열", "열:num", "NUM"), ("네", "넷", "NUM"), ("살", "살", "NOUN")])

    def test_native_compound_twenties(self):
        self.assertEqual(retag([T("스물여섯"), T("살", ms=NOUN)])[:2], [("스물", "스물", "NUM"), ("여섯", "여섯", "NUM")])

    def test_tens_plus_unit(self):
        out = retag([T("열", "열:num", "NUM", "Ko=num|G=NUM|X="), T("한", "하다", "VERB", "Ko=verb|G=VERB|X="),
                     T("시", ms="Ko=noun|G=NOUN|X=")])
        self.assertEqual(out[:2], [("열", "열:num", "NUM"), ("한", "하나", "NUM")])


class Context(unittest.TestCase):
    def test_jeo_before_name(self):
        self.assertEqual(retag([T("저", "저:det", "DET"), T("수아예요")], ["수아"])[0], ("저", "저", "PRON"))

    def test_jeo_before_noun(self):
        self.assertEqual(retag([T("저", "저", "PRON"), T("빵", ms="Ko=noun|G=NOUN|X="), P("도", "-도")])[0],
                         ("저", "저:det", "DET"))

    def test_jeo_before_copula_predicate(self):
        self.assertEqual(retag([T("저", "저", "PRON"), T("학생", ms="Ko=noun|G=NOUN|X="), P("이에요", "-이다")])[0],
                         ("저", "저", "PRON"))

    def test_jagi_before_jeon(self):
        self.assertEqual(retag([T("자기"), T("한", "하나", "NUM"), T("시간"), T("전")])[0], ("자기", "자다", "VERB"))

    def test_jagi_after_jam(self):
        self.assertEqual(retag([T("잠"), P("을", "-을/를"), T("자기"), P("가", "-이/가")])[2], ("자기", "자다", "VERB"))

    def test_jagi_noun_stays(self):
        self.assertEqual(retag([T("자기", ms="Ko=noun|G=NOUN|X="), P("에게", "-에게")])[0], ("자기", "자기", "NOUN"))


class Homographs(unittest.TestCase):
    def test_nal_day_not_pronoun(self):
        self.assertEqual(retag([T("다음", ms=NOUN), T("날", "나", "PRON", "Ko=closed|G=PRON|X=")])[1], ("날", "날", "NOUN"))

    def test_nal_nada_stays(self):
        self.assertEqual(retag([T("날", "나다", "VERB", "Ko=verb|G=VERB|X="), T("위험", ms=NOUN)])[0],
                         ("날", "나다", "VERB"))

    def test_allyeo_is_allida(self):
        for s in ("알려", "알렸어요", "알립니다", "알린"):
            self.assertEqual(retag([T(s, "알다", "VERB", "Ko=verb|G=VERB|X=")])[0], (s, "알리다", "VERB"))

    def test_allyeogo_stays_alda(self):
        self.assertEqual(retag([T("알려고", "알다", "VERB", "Ko=verb|G=VERB|X=")])[0], ("알려고", "알다", "VERB"))

    def test_beon_before_noun_is_beolda(self):
        self.assertEqual(retag([T("번", ms=NOUN), T("돈", ms=NOUN), P("으로", "-으로")])[0], ("번", "벌다", "VERB"))

    def test_counter_beon_stays(self):
        self.assertEqual(retag([T("한", "하나", "NUM", NUMK), T("번", ms=NOUN), T("돈", ms=NOUN)])[1], ("번", "번", "NOUN"))


class HadaVerbs(unittest.TestCase):
    def test_noun_hago_is_pack_verb(self):
        self.assertEqual(retag([T("시작", ms=NOUN), P("하고", "-하고"), T("여섯", "여섯", "NUM", NUMK)])[0],
                         ("시작하고", "시작하다", "VERB"))

    def test_hago_and_before_noun_stays(self):
        self.assertEqual(retag([T("시작", ms=NOUN), P("하고", "-하고"), T("돈", ms=NOUN)])[:2],
                         [("시작", "시작", "NOUN"), ("하고", "-하고", "X")])

    def test_hago_without_pack_verb_stays(self):
        self.assertEqual(retag([T("빵", ms=NOUN), P("하고", "-하고"), T("여섯", "여섯", "NUM", NUMK)])[1],
                         ("하고", "-하고", "X"))

    def test_unknown_doeda_form(self):
        self.assertEqual(retag([T("발견되었거나")]), [("발견되었거나", "발견되다", "VERB")])


class AnalyserRepairs(unittest.TestCase):
    def test_noun_particle_that_is_a_verb(self):
        self.assertEqual(retag([T("자", ms="Ko=noun|G=NOUN|X="), P("요", "-요")]), [("자요", "자다", "VERB")])

    def test_pack_noun_particle_stays(self):
        self.assertEqual(retag([T("차", "차:tea", ms="Ko=noun|G=NOUN|X="), P("는", "-은/는")])[0], ("차", "차:tea", "NOUN"))

    def test_whole_eojeol_verb_reading(self):
        self.assertEqual(retag([T("사면")]), [("사면", "사다", "VERB")])

    def test_noun_plus_particles(self):
        self.assertEqual(retag([T("앞에서", upos="ADV")]), [("앞", "앞", "NOUN"), ("에서", "-에서", "X")])

    def test_honorific_nim(self):
        self.assertEqual(retag([T("교수님이")]),
                         [("교수", "교수", "NOUN"), ("님", "님", "X"), ("이", "-이/가", "X")])


class Alias(unittest.TestCase):
    def test_alias(self):
        a = spec().passage_lemma_alias
        self.assertEqual(a.get("운동하다"), "운동")
        self.assertEqual(a.get("중독되다"), "중독")
        self.assertEqual(a.get("주무시다"), "자다")
        self.assertIsNone(a.get("하다"))
        self.assertIsNone(a.get("먹다"))


if __name__ == "__main__":
    unittest.main()
