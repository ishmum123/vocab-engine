"""Tests for passage token spans (passages.token_offsets / make_spans and the
`where` records of core.sentences.sentence_links). Stdlib only.

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.core.sentences import phrase_spans, sentence_links  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.passages import make_spans, token_offsets, utf16_index  # noqa: E402


def tok(w, lemma=None, upos="X"):
    return [w, lemma or w.lower(), upos, ""]


class FakeLexicon:
    """resolve_sentence from a {surface: (lemma, group)} table."""

    def __init__(self, spec, table):
        self.spec, self.table = spec, table

    def resolve_sentence(self, toks, groups=None):
        return [self.table.get(t[0].lower()) for t in toks]


class TokenOffsets(unittest.TestCase):
    def test_truecased_elided_and_quoted(self):
        text = "«Buongiorno! L'amico compra le mele.»"
        toks = [tok(x) for x in ["«", "buongiorno", "!", "l'", "amico", "compra", "le", "mele", ".", "»"]]
        offs = token_offsets(text, toks)
        self.assertEqual([text[a:b] for a, b in offs],
                         ["«", "Buongiorno", "!", "L'", "amico", "compra", "le", "mele", ".", "»"])

    def test_rewritten_token_is_none_and_next_resyncs(self):
        # fix_token rewrote "del" as "de": not found in order, the next token still aligns
        text = "Vengo del mercato."
        offs = token_offsets(text, [tok("Vengo"), tok("dello"), tok("mercato"), tok(".")])
        self.assertEqual(offs[1], None)
        self.assertEqual(text[offs[2][0]:offs[2][1]], "mercato")

    def test_no_skipping_over_words(self):
        # tokens align in order (the first "va", not the second); a token may not skip a word
        text = "Lui va a casa e va via."
        offs = token_offsets(text, [tok("Lui"), tok("va"), tok("a"), tok("casa")])
        self.assertEqual(offs[1], (4, 6))
        self.assertEqual(token_offsets("aa bb", [tok("bb")]), [None])   # "aa" would be skipped


    def test_resync_never_matches_inside_a_word(self):
        # "da il" (a rewritten "dal") is unlocated; "e" must not match inside "mercato"
        text = "Vengo dal mercato e torno."
        offs = token_offsets(text, [tok("Vengo"), tok("da il"), tok("e"), tok("torno"), tok(".")])
        self.assertEqual(offs[0], (0, 5))
        self.assertIsNone(offs[1])
        for o in offs[2:]:
            if o is not None:
                a, b = o
                self.assertFalse(text[a - 1:a].isalnum() or text[b:b + 1].isalnum(), text[a:b])
        self.assertNotIn((11, 12), offs)     # the "e" of mercato (old code matched it)

    def test_adjacent_split_tokens_still_align(self):
        # clitic split (comprami -> compra + mi) and elision (l'amico -> l' + amico)
        text = "Comprami l'amico."
        offs = token_offsets(text, [tok("compra"), tok("mi"), tok("l'"), tok("amico"), tok(".")])
        self.assertEqual([text[a:b] for a, b in offs], ["Compra", "mi", "l'", "amico", "."])


class MakeSpans(unittest.TestCase):
    def test_longest_wins_filter_and_sort(self):
        text = "Vorrei due mele, per favore."
        offs = token_offsets(text, [tok(x) for x in ["Vorrei", "due", "mele", ",", "per", "favore", "."]])
        recs = [("tok", 0, 0, "vol"), ("tok", 2, 2, "mela"), ("tok", 4, 4, "per"), ("tok", 5, 5, "fav"),
                ("chars", 17, 27, "perfav"), ("tok", 1, 1, "dropped")]
        spans = make_spans(text, offs, recs, ["vol", "mela", "per", "fav", "perfav"])
        self.assertEqual([(text[a:b], w) for a, b, w in spans],
                         [("Vorrei", "vol"), ("mele", "mela"), ("per favore", "perfav")])

    def test_multi_token_range_and_missing_offset(self):
        text = "Il fine settimana va."
        offs = [(0, 2), (3, 7), (8, 17), None, (20, 21)]
        spans = make_spans(text, offs, [("tok", 1, 2, "fs"), ("tok", 3, 3, "va")], ["fs", "va"])
        self.assertEqual(spans, [[3, 17, "fs"]])

    def test_every_occurrence_gets_a_span(self):
        text = "Sono stati qui."
        offs = token_offsets(text, [tok("Sono"), tok("stati"), tok("qui"), tok(".")])
        spans = make_spans(text, offs, [("tok", 0, 0, "essere"), ("tok", 1, 1, "essere")], ["essere"])
        self.assertEqual(spans, [[0, 4, "essere"], [5, 10, "essere"]])

    def test_utf16_offsets(self):
        text = "\U0001F642 va!"
        self.assertEqual(utf16_index(text, 2), 3)
        spans = make_spans(text, token_offsets(text, [tok("\U0001F642"), tok("va"), tok("!")]),
                           [("tok", 1, 1, "v")], ["v"])
        self.assertEqual(spans, [[3, 5, "v"]])
        self.assertEqual(text.encode("utf-16-le")[6:10].decode("utf-16-le"), "va")


class SentenceLinksWhere(unittest.TestCase):
    def test_token_and_multiword_records(self):
        sp = get_spec("it", tempfile.mkdtemp())
        k2i = {("comprare", "VERB"): "c", ("mela", "NOUN"): "m", ("per favore", "PHRASE"): "pf"}
        lex = FakeLexicon(sp, {"compra": ("comprare", "VERB"), "mele": ("mela", "NOUN")})
        text = "Compra le mele, per favore."
        toks = [tok("compra", "comprare", "VERB"), tok("le", "il", "DET"), tok("mele", "mela", "NOUN"),
                tok(",", ",", "PUNCT"), tok("per", "per", "ADP"), tok("favore", "favore", "NOUN"), tok(".", ".", "PUNCT")]
        where = []
        links = sentence_links(toks, lex, k2i, {"comprare", "mela"}, text, where=where)
        self.assertEqual(links, sentence_links(toks, lex, k2i, {"comprare", "mela"}, text))   # unchanged
        self.assertEqual(sorted(links), ["c", "m", "pf"])
        self.assertIn(("tok", 0, 0, "c"), where)
        self.assertIn(("tok", 2, 2, "m"), where)
        self.assertIn(("chars", 16, 26, "pf"), where)
        spans = make_spans(text, token_offsets(text, toks), where, links)
        self.assertEqual([(text[a:b], w) for a, b, w in spans], [("Compra", "c"), ("mele", "m"), ("per favore", "pf")])

    def test_phrase_ranges(self):
        sp = get_spec("es", tempfile.mkdtemp())
        k2i = {(p, "PHRASE"): f"p_{p}" for p in sp.multiword}
        t = [tok(x) for x in ["A", "pesar", "del", "mal", "tiempo", ","]]
        t[-1][2] = "PUNCT"
        ranges = []
        ids, _, _ = phrase_spans(t, sp, k2i, None, ranges)
        self.assertEqual(ranges, [(0, 2, "p_a pesar de")])
        self.assertEqual(ids, ["p_a pesar de"])



class OneIdPerToken(unittest.TestCase):
    """passages.Linker.links_all: a token carries one word id. A phrase owns
    its tokens, and the lemma fallback never adds a second id to a token the
    primary pass (sentence_links) already linked."""

    def linker(self, where, cl):
        from collections import Counter
        from packbuilder.passages import Linker

        class Spec:
            homograph_by_translation = False
            span_fold, span_joiners = None, ""
        lk = Linker(Spec(), {"lexicon": None, "groups": None, "truecase": (Counter(), Counter()),
                             "words": []}, {})

        def links(toks, text, en, w):
            w.extend(where)
            return list(dict.fromkeys(r[3] for r in where))
        lk.links = links
        lk.classify = lambda toks: cl
        return lk

    def test_fallback_does_not_relink_a_linked_token(self):
        # "Come stai?": come read as "how" (w2012); classify says come "as" (w2017)
        toks = [tok("Come"), tok("stai"), tok("?", upos="PUNCT")]
        lk = self.linker([("tok", 0, 0, "HOW"), ("tok", 1, 1, "STARE")],
                         [("Come", "come", "AS", True, 0), ("stai", "stare", "STARE", True, 1)])
        ids, _cl, spans, linked = lk.links_all(toks, "Come stai?", "")
        self.assertEqual(ids, ["HOW", "STARE"])
        self.assertEqual(spans, [[0, 4, "HOW"], [5, 9, "STARE"]])
        self.assertEqual(linked, {0, 1})

    def test_phrase_owns_its_tokens(self):
        text = "Sei mele, per favore."
        toks = [tok("Sei"), tok("mele"), tok(",", upos="PUNCT"), tok("per"), tok("favore"), tok(".", upos="PUNCT")]
        lk = self.linker([("tok", 1, 1, "MELA"), ("tok", 3, 3, "PER"), ("tok", 4, 4, "FAVORE"),
                          ("chars", 10, 20, "PERFAVORE")],
                         [("mele", "mela", "MELA", True, 1), ("per", "per", "PER", True, 3),
                          ("favore", "favore", "FAVORE", True, 4)])
        ids, _cl, spans, linked = lk.links_all(toks, text, "")
        self.assertEqual(ids, ["MELA", "PERFAVORE"])
        self.assertEqual(spans, [[4, 8, "MELA"], [10, 20, "PERFAVORE"]])
        self.assertEqual(linked, {1, 3, 4})

    def test_part_linked_outside_the_phrase_stays(self):
        text = "Per te, per favore."
        toks = [tok("Per"), tok("te"), tok(",", upos="PUNCT"), tok("per"), tok("favore"), tok(".", upos="PUNCT")]
        lk = self.linker([("tok", 0, 0, "PER"), ("tok", 3, 3, "PER"), ("tok", 4, 4, "FAVORE"),
                          ("chars", 8, 18, "PERFAVORE")],
                         [("Per", "per", "PER", True, 0), ("per", "per", "PER", True, 3),
                          ("favore", "favore", "FAVORE", True, 4)])
        ids, _cl, spans, _ = lk.links_all(toks, text, "")
        self.assertEqual(ids, ["PER", "PERFAVORE"])
        self.assertEqual(spans, [[0, 3, "PER"], [8, 18, "PERFAVORE"]])

    def test_unclaimed_token_still_gets_the_fallback(self):
        # "molto" read as a determiner: no primary link, the fallback links it
        toks = [tok("molto"), tok("bene")]
        lk = self.linker([("tok", 1, 1, "BENE")],
                         [("molto", "molto", "MOLTO", True, 0), ("bene", "bene", "BENE", True, 1)])
        ids, _cl, spans, _ = lk.links_all(toks, "molto bene", "")
        self.assertEqual(ids, ["BENE", "MOLTO"])
        self.assertEqual(spans, [[0, 5, "MOLTO"], [6, 10, "BENE"]])

    def test_compound_head_links_nothing(self):
        toks = [tok("rispetto"), tok("a"), tok("te")]
        lk = self.linker([("tok", 0, 0, "RISPETTO"), ("tok", 1, 1, "A")],
                         [("rispetto", "rispetto", "RISPETTO", False, 0), ("a", "a", "A", True, 1)])
        ids, _cl, spans, _ = lk.links_all(toks, "rispetto a te", "")
        self.assertEqual(ids, ["A"])
        self.assertEqual(spans, [[9, 10, "A"]])


    def test_contraction_leftover_article_stays(self):
        # es phrase_token_spans: "a pesar del" = phrase + el (the article part
        # of del); links_all must keep el (review regression)
        from collections import Counter
        from packbuilder.passages import Linker
        sp = get_spec("es", tempfile.mkdtemp())
        k2i = {("a pesar de", "PHRASE"): "PH", ("el", "DET"): "EL", ("mal", "ADJ"): "M", ("tiempo", "NOUN"): "T"}
        lk = Linker(sp, {"lexicon": None, "groups": None, "truecase": (Counter(), Counter()), "words": []}, {})
        lk.lexicon = FakeLexicon(sp, {"mal": ("mal", "ADJ"), "tiempo": ("tiempo", "NOUN")})
        lk.key_to_id, lk.gender_of, lk.epos_to_id, lk.lemma_ids = k2i, {}, {}, {}
        text = "A pesar del mal tiempo."
        toks = [tok("A", "a", "ADP"), tok("pesar", "pesar", "NOUN"), tok("del", "del", "ADP"),
                tok("mal", "mal", "ADJ"), tok("tiempo", "tiempo", "NOUN"), tok(".", ".", "PUNCT")]
        primary = lk.links(toks, text, "")
        self.assertEqual(sorted(primary), ["EL", "M", "PH", "T"])
        lk.classify = lambda toks: [("pesar", "pesar", "PESAR", True, 1), ("mal", "mal", "M", True, 3),
                                    ("tiempo", "tiempo", "T", True, 4)]
        ids, _cl, spans, linked = lk.links_all(toks, text, "")
        self.assertEqual(sorted(ids), ["EL", "M", "PH", "T"])      # no fallback PESAR inside the phrase
        # el lives inside the phrase span "A pesar del": the longer span wins, el has no span of its own
        self.assertEqual([(text[a:b], w) for a, b, w in spans],
                         [("A pesar del", "PH"), ("mal", "M"), ("tiempo", "T")])
        self.assertEqual(linked, {0, 1, 2, 3, 4})


if __name__ == "__main__":
    unittest.main()
