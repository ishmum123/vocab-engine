"""Indonesian (id): everything Indonesian-specific in the pack pipeline.

Tagger: Stanza (id, UD_Indonesian-GSD model) through the non-spaCy tagging
hooks (tagger_desc / tag_texts). Stanza's multi-word-token splitter separates
enclitics (rumah|ku, pekerjaan|nya, apa|kah, duduk|lah); a token kept whole is
one Wiktionary lists as a word of its own (apakah, akhirnya, hanya, punya).
The split-off clitic is stored as X, so it never links and never counts.

Lemmas (bind_lexicon rewrites the lexicon in memory):
- me-/di- verb forms are inflections of the root Wiktionary headword
  ("active of makan", "passive of makan"; memakai -> pakai by Sastrawi stem
  and a shared gloss), unless the root is far rarer than the affixed word
  (mengerti stays: erti is rare), in which case the affixed word keeps the
  root's senses as its own.
- ber- verbs are the lemma (bekerja, bermain, bertemu); a root verb with the
  same sense folds into them (main -> bermain, kerja VERB -> bekerja).
- -an / ke-an / pe(N)-an nouns (makanan, pekerjaan) stay separate lemmas.
- Reduplication (anak-anak, buku-buku) is a plural: its senses repeating the
  base fold into the base; lexicalised ones (mata-mata "spy", tiba-tiba,
  hati-hati "careful") stay words.
No gender, articles or tense. Colloquial Jakarta forms are mapped to the
formal lemma for frequency (gue -> aku, udah -> sudah); nggak, banget,
gimana and the discourse particles are A2+ words glossed "(colloquial)".

The A1 core list, gloss overrides and generated sentences live in the
indonesian repo (tools/).
"""
import json
import re
from collections import Counter

from .base import LanguageSpec, SENSITIVE_EN, SENSITIVE_GLOSS_EN, TATOEBA_ENG, TATOEBA_AUDIO, DEFAULT_GROUP_KPOS

DAYS = "senin selasa rabu kamis jumat sabtu minggu".split()
MONTHS = "januari februari maret april mei juni juli agustus september oktober november desember".split()
NUMBERS = ("nol satu dua tiga empat lima enam tujuh delapan sembilan sepuluh sebelas belas puluh "
           "seratus ratus seribu ribu juta").split()
COLOURS = "merah biru hijau kuning hitam putih abu-abu cokelat oranye ungu".split()
PRONOUNS = "saya aku kamu anda dia kami kita mereka beliau".split()
QUESTION = [("apa", "PRON"), ("siapa", "PRON"), ("kapan", "PRON"), ("mengapa", "PRON"), ("kenapa", "PRON"),
            ("bagaimana", "ADV"), ("berapa", "DET"), ("mana", "PRON"), ("apakah", "CONJ")]
PREPS = "di ke dari dengan untuk pada dalam kepada oleh tentang sampai tanpa".split()
CONJS = "dan atau tetapi karena kalau jika bahwa".split()
TIME = [("hari", "NOUN"), ("bulan", "NOUN"), ("tahun", "NOUN"), ("jam", "NOUN"),
        ("menit", "NOUN"), ("pagi", "NOUN"), ("siang", "NOUN"), ("sore", "NOUN"), ("malam", "NOUN"),
        ("sekarang", "ADV"), ("besok", "NOUN"), ("kemarin", "ADV"), ("nanti", "ADV"), ("tadi", "NOUN")]
GREETINGS = [("ya", "PART"), ("halo", "INTJ"), ("hai", "INTJ"), ("maaf", "INTJ"), ("permisi", "INTJ"),
             ("tolong", "ADV"), ("silakan", "ADV"), ("selamat", "ADJ")]
PHRASES = {"terima kasih": "thank you", "sama-sama": "you're welcome; (the) same to you",
           "selamat pagi": "good morning", "selamat siang": "good day (around midday)",
           "selamat sore": "good afternoon", "selamat malam": "good evening; good night",
           "selamat tinggal": "goodbye (to someone staying)", "sampai jumpa": "see you, goodbye"}
FUNCTION = [("yang", "PRON"), ("itu", "DET"), ("ini", "DET"), ("sudah", "VERB"), ("belum", "ADV"),
            ("akan", "VERB"), ("sedang", "ADV"), ("bisa", "VERB"), ("harus", "ADV"), ("mau", "VERB"),
            ("ada", "VERB"), ("adalah", "VERB"), ("tidak", "PART"), ("bukan", "PART"), ("jangan", "PART")]
# closed words resolved to one fixed key whatever the tag (the tagger splits
# them over POS: untuk ADP/SCONJ, itu DET/PRON, maaf NOUN/VERB, kemarin ADV/ADJ)
CLOSED = {**{w: (w, g) for w, g in FUNCTION[:3]}, "untuk": ("untuk", "ADP"), "dengan": ("dengan", "ADP"),
          "karena": ("karena", "CONJ"), "halo": ("halo", "INTJ"), "hai": ("hai", "INTJ"),
          "maaf": ("maaf", "INTJ"), "permisi": ("permisi", "INTJ"), "kemarin": ("kemarin", "ADV"),
          "silakan": ("silakan", "ADV"), "sana": ("sana", "ADV"), "sini": ("sini", "ADV"),
          "situ": ("situ", "PRON"), "lelah": ("lelah", "ADJ"), "para": ("para", "PART"),
          "telah": ("telah", "ADV"), "belum": ("belum", "ADV"), "dulu": ("dulu", "ADV")}

# capitalised common words (days, months, formal Anda): lowercased on every
# matching side (fold, fix_token), shown capitalised again in finalize_words
CAPITALISED = {w: w.capitalize() for w in DAYS + MONTHS if w != "minggu"} | {"anda": "Anda"}
# lowercased for linking when capitalised mid-sentence (Minggu "Sunday" is minggu "week")
LOWER_SURFACES = set(CAPITALISED) | {"minggu"}
CAP_GROUP = {"anda": "PRON"}

# enclitics the multi-word-token splitter separates from their host
CLITICS = {"nya", "ku", "mu", "kah", "lah", "tah", "pun"}
# colloquial (Jakarta/subtitle) spellings -> the formal surface, for the
# frequency lists; the pack teaches nggak/banget/gimana/particles on their own
COLLOQUIAL = {"gue": "aku", "gua": "aku", "gw": "aku", "lo": "kamu", "lu": "kamu", "elo": "kamu", "loe": "kamu",
              "elu": "kamu", "udah": "sudah", "dah": "sudah", "aja": "saja", "emang": "memang", "kalo": "kalau",
              "tau": "tahu", "liat": "lihat", "pengen": "ingin", "pingin": "ingin", "gitu": "begitu",
              "gini": "begini", "kayak": "seperti", "kaya": "seperti", "ntar": "nanti", "ngerti": "mengerti",
              "bener": "benar", "sampe": "sampai", "gak": "nggak", "ga": "nggak", "enggak": "nggak",
              "ngga": "nggak", "nggak": "nggak", "kagak": "nggak", "mulu": "melulu", "bokap": "ayah",
              "nyokap": "ibu", "cewek": "cewek", "cowok": "cowok", "duluan": "dulu", "lagian": "lagipula",
              "trus": "terus", "abis": "habis", "ama": "sama", "yg": "yang", "tdk": "tidak", "dgn": "dengan"}
# colloquial words taught as A2+ entries, each surface -> (lemma, group)
COLLOQ_WORDS = {"nggak": ("nggak", "PART"), "gak": ("nggak", "PART"), "enggak": ("nggak", "PART"),
                "ngga": ("nggak", "PART"), "banget": ("banget", "ADV"), "gimana": ("gimana", "ADV"),
                "dong": ("dong", "PART"), "sih": ("sih", "PART"), "kok": ("kok", "PART"), "deh": ("deh", "PART"),
                "nih": ("nih", "PART"), "tuh": ("tuh", "PART")}
COLLOQ_GLOSS = {("nggak", "PART"): "not, no (colloquial tidak)", ("banget", "ADV"): "very, really (colloquial)",
                ("gimana", "ADV"): "how (colloquial bagaimana)",
                ("dong", "PART"): "particle: come on, of course (softens or urges; colloquial)",
                ("sih", "PART"): "particle: softens a question or statement (colloquial)",
                ("kok", "PART"): "particle: how come, why (surprise; colloquial)",
                ("deh", "PART"): "particle: then, OK (persuading or conceding; colloquial)",
                ("nih", "PART"): "particle: here, this (colloquial ini)",
                ("tuh", "PART"): "particle: there, that (colloquial itu)"}
# Jakarta pronouns the pack does not teach: sentences using them are dropped
UNTAUGHT_SLANG_RE = re.compile(r"(?<![A-Za-z])(gue|gua|gw|lo|lu|elo|elu|loe)(?![A-Za-z])", re.I)
# colloquial markers kept out of A1 example choice (sentence_rank penalty)
COLLOQ_MARK = set(COLLOQ_WORDS) | {"udah", "aja", "emang", "kalo", "tau", "liat", "pengen", "gitu", "gini",
                                   "kayak", "ntar", "ngerti", "bener", "sampe", "bikin", "cuma"}

AFFIX_OF_RE = re.compile(r"^(?:(?:transitive|intransitive|ditransitive|active|passive|imperative|jussive|emphatic|"
                         r"basic|colloquial|informal)[/ ]?)*(?:active|passive|imperative|jussive|emphatic|basic)"
                         r"(?:[/ ](?:[a-z]+))* (?:form )?of ([a-z]+(?:-[a-z]+)*)\b")
ME_RE = re.compile(r"^(?:me|di)[a-z]{3,}$")
BER_RE = re.compile(r"^(?:ber|be)([a-z]{3,})$")
KAN_RE = re.compile(r"^([a-z]{3,}?)(?:kan|i)$")
# homograph parses Wiktionary gets the wrong way round for the corpus
FORM_OF = {"berikan": "beri"}
# host + enclitic spellings that are words by convention
LEXICAL_CLITIC = {"apakah", "adalah", "ialah", "akhirnya", "bagaimanapun", "sebelumnya", "sesungguhnya",
                  "sebenarnya", "sebaiknya", "seharusnya", "setidaknya", "sejujurnya", "biasanya", "sepertinya"}
# a derived surface: ber-/ter-/ke-/pe(r)-/se- prefix or -an suffix
DERIVED_RE = re.compile(r"^(?:ber|be|ter|ke|pe|per|pen|pem|peng|se)[a-z]{3,}$|^[a-z]{3,}an$")
# ber- spellings that are not the ber- verb of the root (berikut "following" is not ber- + ikut)
BER_EXCEPT = {"berikut"}
REDUP_RE = re.compile(r"^([a-z]+)-\1$")
FOLD_ZIPF_MARGIN = 1.5       # me- form folds into its root unless the root is this much rarer
GLOSS_STOP = {"to", "a", "an", "the", "of", "be", "or", "and", "in", "on", "for", "with", "something",
              "someone", "one", "oneself", "as", "at", "by", "from", "into", "up", "out"}

KPOS_UPOS = [("adv", "ADV"), ("conj", "SCONJ"), ("pron", "PRON"), ("prep", "ADP"), ("particle", "PART"),
             ("det", "DET"), ("adj", "ADJ"), ("verb", "VERB"), ("noun", "NOUN"), ("num", "NUM"),
             ("intj", "INTJ")]

SENSITIVE_ID = (r"bunuh\w*|membunuh\w*|dibunuh|terbunuh|pembunuh\w*|pembunuhan|tembak\w*|menembak\w*|ditembak|"
                r"tikam\w*|menikam|seks\w*|seksual\w*|bugil|telanjang|pelacur\w*|porno\w*|mayat|kondom|"
                r"mati|matilah|kematian|senjata|pistol|pisau|bercinta|payudara|"
                r"die|dies|dying|weapons?|guns?|serial killer|knife")
# removed at every level (cross-pack policy): rape, sexual abuse, child abuse
DROP_ALL_ID = (r"perkosa\w*|memperkosa\w*|diperkosa|pemerkosa\w*|pelecehan seksual|cabul\w*|pencabulan|"
               r"rape[ds]?|raping|rapist\w*|molest\w*|sexual(?:ly)? abus\w*|child abuse|pedophil\w*|paedophil\w*")


def me_roots(w):
    """Shorter spellings a me-/di- verb may be built on (nasal assimilation
    undone): memakai -> pakai, menulis -> tulis, melakukan -> lakukan,
    menyapu -> sapu, mengambil -> ambil / kambil."""
    out = []
    if w.startswith("di"):
        out.append(w[2:])
    for pre, adds in (("meny", ("s",)), ("meng", ("", "k")), ("mem", ("", "p")), ("men", ("", "t")),
                      ("me", ("",))):
        if w.startswith(pre):
            out += [a + w[len(pre):] for a in adds]
    seen, res = set(), []
    for r in out:
        if len(r) >= 3 and r not in seen:
            seen.add(r)
            res.append(r)
    return res


def overlaps(a, b):
    """Two gloss-word sets share a word, or one word contains another of 4+
    letters (myself / self, existence / exist, others / other)."""
    if a & b:
        return True
    aff = lambda x, y: len(y) >= 4 and len(x) > len(y) and (x.startswith(y) or x.endswith(y))
    return any(aff(x, y) or aff(y, x) for x in a for y in b)


def gloss_words(g):
    return {w for w in re.findall(r"[a-z]+", re.sub(r"\(.*?\)", " ", g.lower())) if w not in GLOSS_STOP}


class Indonesian(LanguageSpec):
    code = "id"
    name_en = "Indonesian"
    pack_name = "Indonesian (A1–B1)"
    tts = "id-ID"
    stt = "id-ID"
    tatoeba_code = "ind"

    spacy_model = None          # Stanza, see tagger_desc / tag_texts
    tagger = "stanza"
    stanza_lang = "id"
    tagger_attribution = {
        "source": "Stanza (Apache-2.0) with its Indonesian gsd model (trained on UD_Indonesian-GSD, "
                  "CC BY-SA 4.0); Sastrawi stemmer (MIT) for affix roots",
        "licence": "CC BY-SA 4.0 (model training data); Apache-2.0 / MIT (software)",
        "note": "Used at build time only; the pack ships no model files.",
    }

    subtitles_file = "id_full.txt"
    kaikki_file = "kaikki_id.jsonl.gz"
    sentences_file = "ind_sentences_detailed.tsv.bz2"
    links_file = "ind-eng_links.tsv.bz2"
    sources = {
        "id_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/id/id_full.txt",
        "kaikki_id.jsonl.gz": "https://kaikki.org/dictionary/Indonesian/kaikki.org-dictionary-Indonesian.jsonl.gz",
        "ind_sentences_detailed.tsv.bz2":
            "https://downloads.tatoeba.org/exports/per_language/ind/ind_sentences_detailed.tsv.bz2",
        "ind-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/ind/ind-eng_links.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t4", "lex": "l1"}

    typing = {"caseSensitive": False, "accents": "strict", "strictFromLevel": "A1"}
    show_pron = False
    use_audio = False            # 18 permissive clips only: TTS id-ID throughout
    untranslated_rows = True     # all 28k sentences tagged for frequency/lemma evidence
    extra_corpus_files = ("tools/generated_sentences.tsv",)
    corpus_rank_weight = 1.5     # the subtitle list is colloquial: Tatoeba counts weigh more
    refill_unexampled = True
    example_shows_word = True
    prefer_headword_sentence = True
    strict_selection = True
    numeral_verb_rule = False
    phrase_absorbs_parts = True
    phrase_token_spans = True    # phrases match by token; "sama-sama" = you're welcome only with that English
    phrase_en_cues = {"sama-sama": ("welcome", "mention")}
    verb_endings = None

    word_re = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
    lex_word_re = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
    sub_token_re = re.compile(r"^[a-z]{2,}(?:-[a-z]+)*$")
    form_target_re = re.compile(r"\bof ([a-z]+(?:-[a-z]+)*)")
    fem_of_re = re.compile(r"(?!)")

    group_kpos = dict(DEFAULT_GROUP_KPOS, **{
        "ADV": ["adv", "conj", "prep", "particle", "adj"],
        "PART": ["particle", "adv", "conj", "intj"],
        "DET": ["det", "pron", "adj", "num"],
        "PRON": ["pron", "det"],
        "NOUN": ["noun", "num", "classifier"],
        "NUM": ["num", "noun", "adj"],
        "CONJ": ["conj", "adv", "prep"],
        "ADP": ["prep", "conj", "adv"],
    })
    morph_keep = ("Number", "Voice", "Person", "Polarity", "PronType", "Polite")

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS] + [(w, "PRON") for w in PRONOUNS] + QUESTION +
                     [(w, "ADP") for w in PREPS] + [(w, "CONJ") for w in CONJS] + TIME +
                     GREETINGS + [(p, "PHRASE") for p in PHRASES] + FUNCTION)
    allowed_num = set(NUMBERS) | {"setengah", "pertama", "kedua", "ketiga"}
    no_article = set()
    multiword = {p: tuple(p.split()) if " " in p else (p.split("-")[0],) for p in PHRASES}
    fixed_gloss = {**{(p, "PHRASE"): g for p, g in PHRASES.items()}, **COLLOQ_GLOSS,
                   ("anda", "PRON"): "you (formal, polite)",
                   ("kau", "PRON"): "you (informal; short for engkau)",
                   ("apakah", "PART"): "question word (yes/no questions); whether"}
    closed_surfaces = {**COLLOQ_WORDS, **CLOSED, **{w: (w, "NUM") for w in NUMBERS}}
    function_lemmas = {"yang", "itu", "ini", "sudah", "belum", "akan", "sedang", "bisa", "harus", "mau", "ada",
                       "adalah", "telah", "tidak", "bukan", "jangan", "apakah", "nggak", "dong", "sih", "kok",
                       "deh", "nih", "tuh", "untuk", "kenapa", "mengapa", "kapan", "berapa", "situ", "ialah",
                       "apa", "siapa", "mana", "bagaimana"}
    level_floor = {v: "A2" for v in COLLOQ_WORDS.values()}

    bad_text_re = UNTAUGHT_SLANG_RE
    drop_all_levels = re.compile(r"(?<![A-Za-z])(" + DROP_ALL_ID + r")(?![A-Za-z])", re.I)
    sensitive_re = re.compile(r"(?<![A-Za-z])(" + SENSITIVE_ID + "|" + SENSITIVE_EN + r")(?![A-Za-z])", re.I)
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)    # vulgar senses never lead
    # kill/murder/rape glosses stay out of A1/A2 (clean ";"-segments kept, else the word moves to B1)
    lower_level_gloss_re = re.compile(r"\b(kill\w*|murder\w*|rape[ds]?|raping|rapist|shoot\w*|stab\w*|"
                                      r"porn\w*|prostitut\w*|suicid\w*)\b", re.I)

    report_title = "Indonesian A1-B1 pack (corpus-tagged)"
    forced_description = ("days, months, numbers (0-11, belas, puluh, ratus, ribu, juta), colours, pronouns, "
                          "question words, core prepositions/conjunctions, time words, greetings and phrases, "
                          "function words, A1 core list")
    numeral_exclusion = "numeral outside the taught number words"

    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "numbers": " ".join(NUMBERS),
        "colours": " ".join(COLOURS), "pronouns": " ".join(PRONOUNS),
        "question": " ".join(w for w, _ in QUESTION), "prepositions": " ".join(PREPS),
        "conjunctions": " ".join(CONJS), "time": " ".join(w for w, _ in TIME),
        "greetings": " ".join(w for w, _ in GREETINGS),
    }

    GEN_BASE = 1_000_000_000

    def __init__(self, repo=None):
        super().__init__(repo)
        self._lx = None
        self._whole = None
        self._stemmer = None
        self.n_derived_unlinked = 0

    # ---- orthography -------------------------------------------------------
    def fold(self, s):
        return s.lower() if s and s.lower() in LOWER_SURFACES and s[:1].isupper() else s

    def subtitle_surface(self, w):
        w = COLLOQUIAL.get(w, w)
        split = self.clitic_split(w)
        return split[0] if split else w        # bukunya -> buku (the corpus splits clitics too)

    # ---- tagging (Stanza) ---------------------------------------------------
    def tagger_desc(self):
        import stanza
        return f"Stanza {stanza.__version__}, id gsd (tokenize, mwt, pos, lemma); clitic rule 2"

    def _kaikki_words(self):
        """kaikki headword -> (POS set, gloss words) over its definitional
        senses (not form-of/alt-of lines)."""
        if self._whole is None:
            import gzip
            kw = {}
            with gzip.open(self.repo / ".cache" / self.kaikki_file, "rt", encoding="utf-8") as f:
                for line in f:
                    d = json.loads(line)
                    w = d.get("word", "")
                    if not self.lex_word_re.match(w) or d.get("pos") in ("name", "suffix", "prefix", "root",
                                                                          "circumfix", "character"):
                        continue
                    for s in d.get("senses", []):
                        tags = set(s.get("tags", []))
                        gl = s.get("glosses") or [""]
                        if tags & {"form-of", "alt-of", "misspelling"} or AFFIX_OF_RE.match(gl[-1]) or \
                                re.match(r"^\S+(?:\s\S+){0,3} (?:form |spelling )?of ", gl[-1]):
                            continue
                        e = kw.setdefault(w, (set(), set()))
                        e[0].add(d["pos"])
                        for g in gl:
                            e[1].update(gloss_words(g))
            self._whole = kw
        return self._whole

    def clitic_split(self, low):
        """(host, clitic) when a token is host + enclitic, else None. A token
        Wiktionary lists as a word whose senses do not repeat the host's stays
        whole (sebelumnya, biasanya, bangku, sekolah); apakah/adalah/akhirnya
        are words by convention."""
        if low in LEXICAL_CLITIC:
            return None
        kw = self._kaikki_words()
        for cl in ("nya", "lah", "kah", "pun", "ku", "mu"):
            base = low[:-len(cl)]
            if not low.endswith(cl) or len(base) < 3 or base not in kw:
                continue
            content = cl not in ("kah", "lah") or kw.get(low, (set(),))[0] & {"noun", "verb", "adj"}
            if low in kw and content and not overlaps(kw[low][1], kw[base][1]):
                return None             # sekolah, masalah, bangku: words of their own
            return base, cl
        return None

    def tag_texts(self, texts):
        import stanza
        import torch
        torch.manual_seed(0)
        nlp = stanza.Pipeline("id", package="gsd", processors="tokenize,mwt,pos,lemma", tokenize_no_ssplit=True,
                              verbose=False, download_method=stanza.DownloadMethod.REUSE_RESOURCES)
        kw = self._kaikki_words()
        out = []
        for b in range(0, len(texts), 1000):
            docs = nlp.bulk_process([stanza.Document([], text=t) for t in texts[b:b + 1000]])
            for d in docs:
                toks = []
                for s in d.sentences:
                    for tok in s.tokens:
                        ws = tok.words
                        low = tok.text.lower()
                        split = self.clitic_split(low)
                        if len(ws) > 1 and split is None and low in kw:
                            # a word of its own the splitter cut (apakah, akhirnya)
                            upos = next(u for p, u in KPOS_UPOS + [(None, "X")] if p is None or p in kw[low][0])
                            toks.append((tok.text, low, upos, {}))
                            continue
                        if len(ws) == 1 and split is not None:
                            # host + enclitic the splitter left joined (itulah, semuanya)
                            w = ws[0]
                            n = len(tok.text) - len(split[1])
                            feats = dict(kv.split("=", 1) for kv in (w.feats or "").split("|") if "=" in kv)
                            toks.append((tok.text[:n], split[0], w.upos, feats))
                            toks.append((tok.text[n:], split[1], "X", {}))
                            continue
                        for j, w in enumerate(ws):
                            if j and w.text.lower() in CLITICS:
                                toks.append((w.text, w.text.lower(), "X", {}))   # enclitic: never linked
                                continue
                            feats = dict(kv.split("=", 1) for kv in (w.feats or "").split("|") if "=" in kv)
                            toks.append((w.text, w.lemma or w.text.lower(), w.upos, feats))
                out.append(toks)
        return out

    def fix_token(self, tok):
        text, lemma, upos, ms = tok
        low = text.lower()
        if low in LOWER_SURFACES and text[:1].isupper():
            # hari Senin, bulan Januari, Anda: common words, not names
            return [low, low, CAP_GROUP.get(low, "NOUN"), ms]
        return tok

    def sentence_fields(self, row):
        return {"src": "gen"} if row[0] >= self.GEN_BASE else {}

    def extra_corpus_rows(self, env):
        p = env.repo / "tools" / "generated_sentences.tsv"
        rows = []
        if not p.exists():
            return rows
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                raise ValueError(f"generated_sentences.tsv line {i+1}: need key<TAB>text<TAB>english")
            rows.append([self.GEN_BASE + i, parts[1].strip(), "", parts[2].strip(), None, None])
        return rows

    def extra_attribution(self, env, sentences):
        n = sum(1 for s in sentences if s.get("src") == "gen")
        return {"generated_sentences": {
            "source": "written for this pack (tools/generated_sentences.tsv), marked \"src\": \"gen\"",
            "licence": "CC-BY-SA-4.0", "count": n, "audio": "none (TTS)"}}

    # ---- lexicon rewrites -----------------------------------------------------
    def _stem(self, w):
        if self._stemmer is None:
            from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
            self._stemmer = StemmerFactory().create_stemmer()
        return self._stemmer.stem(w)

    def bind_lexicon(self, lx):
        """Affix and reduplication rules over the loaded Wiktionary lexicon
        (in memory; the lex cache keeps kaikki's own view)."""
        self._lx = lx
        E, F = lx.E, lx.F
        stats = Counter()
        self.affix_log = []

        def verb_senses(w):
            return [(e, sn) for e in E.get(w, []) if e["p"] == "verb" for sn in e["s"] if sn[3] == ""
                    and not AFFIX_OF_RE.match(sn[0])]

        def verb_words(w):
            ws = set()
            for e, sn in verb_senses(w):
                if not set(sn[2]) & {"colloquial", "informal", "dialectal", "archaic", "obsolete"}:
                    ws |= gloss_words(sn[0]) | gloss_words(sn[1])
            return ws

        def verb_head(w):
            """Words of the leading segment of w's first standard verb sense."""
            for e, sn in verb_senses(w):
                if not set(sn[2]) & {"colloquial", "informal", "dialectal", "archaic", "obsolete"}:
                    return gloss_words(re.split(r"[;,(]", sn[1] or sn[0])[0])
            return set()

        def colloquial_only(w):
            vs = verb_senses(w)
            return bool(vs) and all(set(sn[2]) & {"colloquial", "informal", "slang"} for _, sn in vs)

        def mark_form(w, pos, target, why):
            for e in E.get(w, []):
                if e["p"] != pos:
                    continue
                for sn in e["s"]:
                    if sn[3] == "":
                        sn[3] = "form"
            fl = F.setdefault(w, [])
            if [target, pos, "form"] not in fl:
                fl.append([target, pos, "form"])
            stats[why] += 1
            self.affix_log.append(f"{w} -> {target} ({why})")

        def zipf_ok(root, form):
            return lx.zipf(root) >= lx.zipf(form) - FOLD_ZIPF_MARGIN

        # (G) kaikki's Indonesian senses are [translation, English definition
        # of it] ("office:", "a room, set of rooms ... used for non-manual
        # work"): the short translation is the gloss; repeats collapse
        for w in sorted(E):
            for e in E[w]:
                seen, keep = set(), []
                for sn in e["s"]:
                    head = sn[1].strip().rstrip(":").strip()
                    if head and sn[3] == "" and (len(head.split()) <= 6 or sn[1].strip().endswith(":")):
                        sn[0], sn[1] = head, ""
                        stats["two-level gloss -> translation"] += 1
                    if sn[3] == "" and sn[0].lower() in seen:
                        continue
                    seen.add(sn[0].lower())
                    keep.append(sn)
                e["s"] = keep
        # (0) kaikki data fixes: a sense tagged both formal and dialectal is
        # standard (beri "to give"); hand-listed homograph parses (berikan =
        # beri + -kan "give", not ber- + ikan "to fish")
        for w in sorted(E):
            for e in E[w]:
                for sn in e["s"]:
                    if "formal" in sn[2] and "dialectal" in sn[2]:
                        sn[2] = [t for t in sn[2] if t != "dialectal"]
        for w, tgt in sorted(FORM_OF.items()):
            for pos in sorted({e["p"] for e in E.get(w, [])}):
                mark_form(w, pos, tgt, "hand-listed form")
        # (1) "active of X" / "passive of X" / "imperative of X": inflections
        for w in sorted(E):
            for e in E[w]:
                if e["p"] != "verb":
                    continue
                tgt = next((m.group(1) for sn in e["s"] if sn[3] == "" for m in [AFFIX_OF_RE.match(sn[0])] if m),
                           None)
                if not tgt or tgt == w:
                    continue
                if not verb_senses(tgt):
                    # the target is itself a form (gunakan "basic form of
                    # menggunakan"): go on to the word it points at
                    nxt = next((t for t, pos, kind in F.get(tgt, []) if pos == "verb" and verb_senses(t)), None)
                    tgt = nxt if nxt and nxt != w else tgt
                if verb_senses(tgt) and not ME_RE.match(w) and ME_RE.match(tgt) and \
                        lx.zipf(w) >= lx.zipf(tgt) - 0.5:
                    # the root is the everyday word (mulai "basic form of
                    # memulai"): the root takes the affixed word's senses and
                    # the affixed word becomes its form
                    e["s"] = [list(sn) for _, sn in verb_senses(tgt)] + \
                             [sn for sn in e["s"] if not (sn[3] == "" and AFFIX_OF_RE.match(sn[0]))]
                    mark_form(tgt, "verb", w, "affixed verb = its root (root commoner)")
                elif verb_senses(tgt) and (zipf_ok(tgt, w) or not ME_RE.match(w)):
                    mark_form(w, "verb", tgt, "affix-of gloss")
                elif verb_senses(tgt):
                    # the root is rare on its own (mengerti / erti): the affixed
                    # word is the lemma and takes the root's senses
                    e["s"] = [list(sn) for _, sn in verb_senses(tgt)] + \
                             [sn for sn in e["s"] if not (sn[3] == "" and AFFIX_OF_RE.match(sn[0]))]
                    stats["affixed kept, root senses copied"] += 1
                    self.affix_log.append(f"{w} kept (root {tgt} rare)")
        # (2) me-/di- verbs with senses of their own that repeat a shorter
        # verb's (memakai = pakai, melakukan = lakukan, menulis = tulis)
        for w in sorted(E):
            if not ME_RE.match(w) or not verb_senses(w):
                continue
            for root in me_roots(w):
                if root in E and verb_senses(root) and verb_head(w) & verb_head(root) and zipf_ok(root, w):
                    mark_form(w, "verb", root, "me-/di- verb = root")
                    break
        # (3) a root verb with the sense of its ber- verb folds into it when the
        # ber- verb is the usual word (main -> bermain) or the root verb is
        # colloquial only (kerja -> bekerja); never berkeinginan <- ingin
        for w in sorted(E):
            m = BER_RE.match(w)
            if not m or not verb_senses(w) or w in BER_EXCEPT:
                continue
            rest = m.group(1)
            for root in (rest, "r" + rest if w.startswith("be") and not w.startswith("ber") else None):
                if not root or root not in E or not verb_senses(root):
                    continue
                shared = verb_head(w) & verb_words(root) or verb_head(root) & verb_words(w)
                if (shared and lx.zipf(w) >= lx.zipf(root) - 0.5) or colloquial_only(root):
                    mark_form(root, "verb", w, "root verb = ber- verb")
                break
        # (4) -kan / -i verbs that repeat their base verb's sense (berikan =
        # beri, inginkan = ingin); dengarkan "listen" stays apart from dengar
        for w in sorted(E):
            m = KAN_RE.match(w)
            if not m or not verb_senses(w) or ME_RE.match(w):
                continue
            base = m.group(1)
            if base.startswith("ke") and w.endswith("i") and base[2:] in E:
                base = base[2:]                 # ketahui -> tahu
            if base in E and verb_senses(base) and verb_head(w) & verb_head(base) and zipf_ok(base, w):
                mark_form(w, "verb", base, "-kan/-i verb = base")
        # (5) reduplicated plurals: senses repeating the base fold into it
        for w in sorted(E):
            m = REDUP_RE.match(w)
            if not m or m.group(1) not in E:
                continue
            base = m.group(1)
            bw = set()
            for e in E[base]:
                for sn in e["s"]:
                    if sn[3] == "":
                        bw |= gloss_words(sn[0])
            for e in E[w]:
                plural = any(sn[3] == "form" and "plural" in sn[2] for sn in e["s"])
                for sn in e["s"]:
                    if sn[3] == "" and (plural or e["p"] == "noun") and gloss_words(sn[0]) and \
                            gloss_words(sn[0]) <= bw | {"s"}:
                        sn[3] = "form"
                        stats["reduplicated sense = base"] += 1
                if e["p"] == "noun" and plural:
                    fl = F.setdefault(w, [])
                    if [base, "noun", "form"] not in fl:
                        fl.append([base, "noun", "form"])
        self.affix_stats = dict(stats)

    def post_resolve(self, toks, out):
        """(1) A surface that is a word of its own keeps it, where the tagger
        lemma or the plural rule sent it to a root: laki-laki, kupu-kupu,
        terlambat "late" (not lambat "slow"); anak-anak -> anak and terburuk
        -> buruk stay (their entries are only form-of lines).
        (2) A derived surface Wiktionary does not list (persahabatan,
        terserah, berduduk) links nothing: its tagger root is another word
        (sahabat, serah). me-/di- surfaces are inflections and keep the root."""
        lx = self._lx
        for i, t in enumerate(toks):
            r = out[i]
            low = t[0].lower()
            if not r or r[0] == low or r[1] not in self.group_kpos or r[1] == "PROPN":
                continue
            if lx.usable_entries(low, self.group_kpos[r[1]]):
                out[i] = (low, r[1])
            elif low not in lx.E and low not in lx.F and not ME_RE.match(low) and \
                    DERIVED_RE.match(low) and r[0] in low:
                out[i] = None
                self.n_derived_unlinked += 1
        return out

    # ---- sentences ------------------------------------------------------------
    def sentence_rank(self, toks, lv):
        if lv == self.level_ids[0] and any(t[0].lower() in COLLOQ_MARK for t in toks):
            return 1        # A1 examples: formal/neutral register first
        return 0

    def finalize_words(self, env, ctx, words):
        for w in words:
            if w["lemma"] in CAPITALISED:
                w["w"] = CAPITALISED[w["lemma"]]
            if w["_key"] == ("nggak", "PART"):
                w["alt"] = ["gak", "enggak", "ngga"]
            if w["_key"] == ("tetapi", "CONJ"):
                w["alt"] = ["tapi"]


SPEC = Indonesian
