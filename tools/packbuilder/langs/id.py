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
# titles and forms of address, capitalised before a name or in direct address
# ("Pak Sasaki", "Terima kasih, Bu Ani", "Tuan Smith"): common nouns, not names
HONORIFICS = {"pak", "bapak", "ibu", "tuan", "nyonya", "nona", "kakak", "adik", "paman", "bibi", "om", "tante",
              "dokter"}
# lowercased for linking when capitalised mid-sentence (Minggu "Sunday" is minggu "week")
LOWER_SURFACES = set(CAPITALISED) | {"minggu"} | HONORIFICS
CAP_GROUP = {"anda": "PRON"}
# passages only (passage_retag): kinship words and short address forms
# capitalised mid-sentence ("Nenek pulang", "Selamat pagi, Bu") -> the pack noun
PASSAGE_UPOS = {"verb": "VERB", "noun": "NOUN", "adj": "ADJ", "adv": "ADV"}
PASSAGE_ADDRESS = {"nenek": "nenek", "kakek": "kakek", "ayah": "ayah", "mama": "mama", "bu": "ibu",
                   "kak": "kakak", "dik": "adik", "dok": "dokter"}
# passages only (passage_retag): titles capitalised before a name or in an
# address ("Yth. Bapak Ketua RT", "Kepala Sekolah") are the pack noun, not a name
PASSAGE_TITLES = {"ketua", "kepala", "manajer", "direktur", "presiden", "menteri", "guru", "dokter"}
# passages only: two-word compounds read as one tap (passage_post_resolve +
# passage_phrase_ranges): (first, second) -> (lemma, pack POS) of the pack word
# the whole compound links. A compound that is a pack word links it (beri tahu
# -> memberitahu); a compound the pack lacks links its first word, whose gloss
# carries the compound sense (orang tua -> orang "(orang tua) parents"). The
# second part never links on its own ("tua" is not "old" in orang tua).
PASSAGE_COMPOUNDS = {tuple(k.split()): v for k, v in {
    "beri tahu": ("memberitahu", "verb"),
    "orang tua": ("orang", "noun"), "rumah sakit": ("rumah", "noun"), "rumah makan": ("rumah", "noun"),
    "kamar mandi": ("kamar", "noun"), "kamar tidur": ("kamar", "noun"), "tempat tidur": ("tempat", "noun"),
    "ruang tamu": ("ruang", "noun"), "ruang tunggu": ("ruang", "noun"), "air minum": ("air", "noun"),
    "kereta api": ("kereta", "noun"), "masa depan": ("masa", "noun"), "salah satu": ("salah", "adj"),
    "salah seorang": ("salah", "adj"), "ulang tahun": ("ulang", "verb"), "tata bahasa": ("tata", "noun"),
    "tentu saja": ("tentu", "adv"), "makan siang": ("makan", "verb"), "makan malam": ("makan", "verb"),
    "makan pagi": ("makan", "verb"), "teman kerja": ("teman", "noun"), "mabuk laut": ("mabuk", "adj"),
    "masuk akal": ("masuk", "verb"), "sepak bola": ("sepak", "noun"), "buku tulis": ("buku", "noun"),
}.items()}
# passages only: a pack verb/noun homograph read as the noun (passage_post_resolve)
NOUN_AFTER = {"cara"}                  # cara bicara "way of speaking", cara hidup
CLAUSE_OPENERS = {"bahwa", "ternyata"}  # "bahwa hidup di sana tidak mudah": life
# ... but not before an object: an imperative or verb with an object stays the
# verb ("Isi botol itu", '"Gambar rumahmu," kata guru')
OBJECT_UPOS = {"NOUN", "PRON", "PROPN", "DET", "NUM"}

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
DERIVED_RE = re.compile(r"^(?:ber|be|ter|ke|pe|per|pen|pem|peng|se)[a-z]{3,}$|^[a-z]{3,}(?<!k)an$")   # not -kan verbs
# ber- spellings that are not the ber- verb of the root (berikut "following" is not ber- + ikut)
BER_EXCEPT = {"berikut"}
REDUP_RE = re.compile(r"^([a-z]+)-\1$")
FOLD_ZIPF_MARGIN = 1.5       # a derived verb (memberikan, mendapatkan) folds into its root unless the root is this much rarer
ROOT_FREE_MARGIN = 0.5       # a plain me- verb folds into its root unless the root is this much rarer (tangis, tonton, ajar)
# di/ke/dari + a place word written as one token (disini, dimana, kemana): the place word
LOCATIVE_RE = re.compile(r"^(?:di|ke|dari)(sini|sana|situ|mana)$")
LOCATIVE_KEY = {"sini": ("sini", "ADV"), "sana": ("sana", "ADV"), "situ": ("situ", "PRON"), "mana": ("mana", "PRON")}
# kaikki senses that are not translations: abbreviations, bare affixes ("sub-")
JUNK_SENSE_RE = re.compile(r"^(?:syllabic |a )?(?:abbreviation|acronym|initialism|clipping|contraction|ellipsis) of\b|"
                           r"^[a-z]+-$", re.I)
# "synonym of datang (“to arrive; to come”)": a word of its own with that meaning, not a form of datang
SYNONYM_RE = re.compile(r"^synonym of ([a-z]+(?:[ -][a-z]+)*)(?: \(“([^”]+)”\))?")
# "shelf: a flat, rigid structure ...": the translation before the colon is the gloss
FORM_LINE_RE = re.compile(r"^(?:[\w'-]+ ){0,5}(?:forms?|plural|spelling|synonym|variant|abbreviation|ellipsis|clipping|"
                          r"contraction|diminutive|superlative|comparative|misspelling|nonstandard) of\b", re.I)
COLON_RE = re.compile(r"^([^:;()]{2,40}?):\s+\S")
# comparatives are compositional ("lebih baik" = better): never an idiom
DEGREE_WORDS = {"lebih", "paling"}
# sentences whose English translation says something else (asap tebal "thick smoke" / "a cloud of dust")
BAD_TEXTS = ("Mobil itu mengeluarkan asap tebal.",
             "Sepuluh lembar piring kertas harganya 10 dolar.",     # English says "one dollar"
             "Aku pikir Tom sudah lelah mengejar Mary.")            # English says "had gotten over Mary"
# compounds whose meaning is not built from their parts, beyond what the
# gloss-overlap test of _idiom_pairs finds. OPAQUE: no part links (orang tua
# "parents", makan siang "lunch", rumah sakit "hospital"). FORCED_IDIOMS
# (Wiktionary two-word headwords with pack-word parts seen 2+ times in the
# corpus, compositional ones such as hari ini, di sini, tiga puluh left out):
# a part whose glosses share a word with the compound's keeps its link
# (sumber in sumber daya "resource", latar in latar belakang "background").
# Compounds that are the only place a part occurs (kaus kaki, sarung tangan,
# kata sandi, harta benda) stay out: the part would lose every sentence.
OPAQUE_IDIOMS = {tuple(p.split()) for p in (
    "orang tua", "salah satu", "salah seorang", "tanda tangan", "luar biasa", "air terjun", "anak panah",
    "rumah makan", "makan siang", "makan malam", "makan pagi", "memberi tahu", "kamar mandi", "mata uang",
    "rumah sakit", "ibu kandung", "kereta api")}
FORCED_IDIOMS = {tuple(p.split()) for p in (
    "ulang tahun", "ibu kota", "luar negeri", "sepak bola", "masuk akal", "jam tangan", "kebun binatang",
    "pekerjaan rumah", "meninggal dunia", "rumah tangga", "kata kerja", "keras kepala", "buta huruf",
    "kasih sayang", "merah muda", "luar angkasa", "gempa bumi", "kepala sekolah", "bahan bakar", "angkatan laut",
    "salah paham", "tanah air", "negara bagian", "sumber daya", "latar belakang", "kata ganti", "bulan madu")}
# reduplications that are words of their own, not a plural/intensive of the
# root (satu-satunya "the only one" is not satu "one"); kaikki entries add more
LEXICAL_REDUP = {"satu-satu"}
# subject pronouns before an object-voice verb ("yang pernah kamu alami")
AGENT_PRONOUNS = {"aku", "saya", "kamu", "kau", "engkau", "dia", "ia", "mereka", "kami", "kita", "anda", "beliau"}
# enclitics written onto a word (makanlah, rumahnya): stripped to find the word
CLITIC_TAIL_RE = re.compile(r"(?:nya|ku|mu|lah|kah|pun)$")
INFLECT_PREFIXES = ("", "di", "ber", "be", "bel", "ter", "per", "memper", "diper", "ku", "kau")
# a verb entry glossed like an adjective (bersalah "guilty", berguna "useful")
ADJ_GLOSS_RE = re.compile(r"^[a-z]+(?:ful|able|ible|ous|ive|less|ant|ent|al|ic|ed|y)$")
# pack POS label -> kaikki POS (gloss_overrides keys are "lemma|label")
LABEL_KPOS = {"noun": "noun", "verb": "verb", "adj": "adj", "adv": "adv", "prep": "prep", "conj": "conj",
              "part": "particle", "pron": "pron", "det": "det", "intj": "intj", "num": "num"}
GLOSS_STOP = {"to", "a", "an", "the", "of", "be", "or", "and", "in", "on", "for", "with", "something",
              "someone", "one", "oneself", "as", "at", "by", "from", "into", "up", "out"}

KPOS_UPOS = [("adv", "ADV"), ("conj", "SCONJ"), ("pron", "PRON"), ("prep", "ADP"), ("particle", "PART"),
             ("det", "DET"), ("adj", "ADJ"), ("verb", "VERB"), ("noun", "NOUN"), ("num", "NUM"),
             ("intj", "INTJ")]

SENSITIVE_ID = (r"bunuh\w*|membunuh\w*|dibunuh|terbunuh|pembunuh\w*|pembunuhan|tembak\w*|menembak\w*|ditembak|"
                r"tikam\w*|menikam|seks\w*|seksual\w*|bugil|telanjang|pelacur\w*|porno\w*|mayat|kondom|"
                r"mati|matilah|kematian|senjata|pistol|pisau|bercinta|payudara|"
                r"bom|bom-bom|pengeboman|meledak\w*|ledakan\w*|racun\w*|beracun|meracuni|darah\w*|berdarah|"
                r"tewas|jenazah|"
                r"die|dies|dying|weapons?|guns?|serial killer|knife|bombs?|bombing\w*|bombed|explod\w*|"
                r"explosion\w*|explosive\w*|poison\w*|blood\w*|bleed\w*|corpses?")
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


def me_form(w):
    """The me- verb of an object-voice spelling (nasal rule): kenakan ->
    mengenakan, pakai -> memakai, tulis -> menulis, sapu -> menyapu, lihat
    -> melihat, ambil -> mengambil, beli -> membeli."""
    if not w:
        return w
    c = w[0]
    if c == "k":
        return "meng" + w[1:]
    if c == "p":
        return "mem" + w[1:]
    if c == "t":
        return "men" + w[1:]
    if c == "s":
        return "meny" + w[1:]
    if c in "aeiouhg":
        return "meng" + w
    if c in "bfv":
        return "mem" + w
    if c in "cdjz":
        return "men" + w
    return "me" + w


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
    versions = {"corpus": "c2", "tag": "t6", "lex": "l1"}

    typing = {"caseSensitive": False, "accents": "strict", "strictFromLevel": "A1"}
    show_pron = False
    use_audio = False            # 18 permissive clips only: TTS id-ID throughout
    propn_lowercase_rescue = 5   # seen lowercase mid-sentence 5+ times: a common word (pak, bumi, barat)
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
    passage_names_never_link = True   # passages: a declared name's capitalised token never links (Jawa Tengah)
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
        "DET": ["det", "article", "pron", "adj", "num"],
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
                   ("si", "DET"): "the (before a name or nickname; familiar)",
                   ("anda", "PRON"): "you (formal, polite)",
                   ("kau", "PRON"): "you (informal; short for engkau)",
                   ("apakah", "PART"): "question word (yes/no questions); whether"}
    closed_surfaces = {**COLLOQ_WORDS, **CLOSED, **{w: (w, "NUM") for w in NUMBERS}}
    function_lemmas = {"yang", "itu", "ini", "sudah", "belum", "akan", "sedang", "bisa", "harus", "mau", "ada",
                       "adalah", "telah", "tidak", "bukan", "jangan", "apakah", "nggak", "dong", "sih", "kok",
                       "deh", "nih", "tuh", "untuk", "kenapa", "mengapa", "kapan", "berapa", "situ", "ialah",
                       "apa", "siapa", "mana", "bagaimana"}
    level_floor = {**{v: "A2" for v in COLLOQ_WORDS.values()}, ("bilang", "VERB"): "A2"}   # colloquial words start at A2
    # bound roots that occur only inside derived words or compounds (alih in
    # alih-alih, tuju in tujuan, kejar noun = abbreviation), and vulgar/sexual
    # words the pack leaves out; their tokens link nothing
    drop_keys = {**{(w, g): None for w, g in (
        ("alih", "VERB"), ("tuju", "NOUN"), ("kejar", "NOUN"), ("henti", "NOUN"), ("omong", "NOUN"),
        ("kala", "NOUN"), ("lapis", "NOUN"), ("tebak", "NOUN"), ("budi", "NOUN"), ("halang", "VERB"),
        ("sial", "NOUN"), ("seks", "NOUN"), ("payudara", "NOUN"), ("bajingan", "NOUN"), ("awak", "NOUN"), ("kemas", "ADJ"), ("pelacur", "NOUN"), ("cita", "NOUN"))},
        # one word for one meaning: the second POS reading links the entry that
        # carries both senses (perlu "to need; necessary", pasti "certain; certainly",
        # menarik "interesting; to pull", kasih "love; (colloquial) to give", segala
        # "all, every; everything"). Kept apart: saat "when" / "moment", hidup "to
        # live" / "life", baru "new" / "just", sampai "until" / "to arrive".
        ("perlu", "ADV"): ("perlu", "VERB"), ("pasti", "ADV"): ("pasti", "ADJ"),
        ("kini", "ADJ"): ("kini", "ADV"),      # masa kini "the present": kini "now"
        ("menarik", "VERB"): ("menarik", "ADJ"), ("kasih", "VERB"): ("kasih", "NOUN"),
        ("segala", "DET"): ("segala", "PRON"),
        # kaikki's "hearing (able to hear)" adjective is only the verb's participle
        ("mendengar", "ADJ"): ("dengar", "VERB")}

    bad_text_re = re.compile(UNTAUGHT_SLANG_RE.pattern + "|^(?:" + "|".join(re.escape(t) for t in BAD_TEXTS) + ")$",
                             re.I)
    drop_all_levels = re.compile(r"(?<![A-Za-z])(" + DROP_ALL_ID + r")(?![A-Za-z])", re.I)
    sensitive_re = re.compile(r"(?<![A-Za-z])(" + SENSITIVE_ID + "|" + SENSITIVE_EN + r")(?![A-Za-z])", re.I)
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)    # vulgar senses never lead
    # kill/murder/rape glosses stay out of A1/A2 (clean ";"-segments kept, else the word moves to B1)
    lower_level_gloss_re = re.compile(r"\b(kill\w*|murder\w*|rape[ds]?|raping|rapist|shoot\w*|stab\w*|"
                                      r"porn\w*|prostitut\w*|suicid\w*|bomb\w*|explod\w*|explosi\w*|"
                                      r"poison\w*|blood\w*|corpse\w*|dead body)\b", re.I)

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
        self._mw = None
        self._clf = None
        self._idioms = None
        self._key_index = None
        self.voice_alt = {}
        self.n_derived_unlinked = 0
        self.post_stats = Counter()

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
        senses (not form-of/alt-of lines). Also collects two-word headwords
        (self._mw: (a, b) -> glosses) and classifier glosses (self._clf)."""
        if self._whole is None:
            import gzip
            kw, mw, clf = {}, {}, {}
            with gzip.open(self.repo / ".cache" / self.kaikki_file, "rt", encoding="utf-8") as f:
                for line in f:
                    d = json.loads(line)
                    w = d.get("word", "")
                    if re.fullmatch(r"[a-z]+(?:-[a-z]+)* [a-z]+(?:-[a-z]+)*", w) and d.get("pos") != "name":
                        mw.setdefault(tuple(w.split()), []).extend(
                            (s.get("glosses") or [""])[0] for s in d.get("senses", []))
                        continue
                    if d.get("pos") == "classifier" and self.lex_word_re.match(w):
                        clf.setdefault(w, next(((s.get("glosses") or [""])[-1] for s in d.get("senses", [])), ""))
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
            self._whole, self._mw, self._clf = kw, mw, clf
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
        # words seen lowercase mid-sentence: a capitalised sentence-initial one
        # tagged PROPN is the common word ("Ayo makan!", "Bumi itu bulat"), not a name
        lowc = Counter(w for t in texts for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", t)[1:] if w.islower())
        capc = Counter(w.lower() for t in texts for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", t)[1:]
                       if w[:1].isupper())
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
                for j, tk in enumerate(toks):
                    low = tk[0].lower()
                    if tk[2] == "PROPN" and tk[0][:1].isupper() and low in kw and lowc[low] >= 2 and \
                            (j == 0 or toks[j - 1][0] in (".", "!", "?", "…", '"', "“", ":")):
                        upos = next(u for p, u in KPOS_UPOS + [(None, "X")] if p is None or p in kw[low][0])
                        toks[j] = (tk[0], low, upos, {})
                out.append(toks)
        # the POS each word takes when written lowercase (not as a name)
        lowpos = {}
        for toks in out:
            for tk in toks:
                if tk[0].islower() and tk[2] not in ("PROPN", "X", "PUNCT"):
                    lowpos.setdefault(tk[0], Counter())[(tk[1], tk[2])] += 1
        for toks in out:
            for j, tk in enumerate(toks):
                low = tk[0].lower()
                if tk[2] == "PROPN" and tk[0].islower() and low in lowpos:
                    # "pada bulan Mei": a lowercase word tagged as a name is the common word
                    lem, upos = lowpos[low].most_common(1)[0][0]
                    toks[j] = (tk[0], lem, upos, tk[3])
                elif j and tk[0][:1].isupper() and not tk[0].isupper() and low in lowpos and \
                        low not in LOWER_SURFACES and toks[j - 1][0] not in (".", "!", "?", "…", '"', "“", ":") and \
                        lowc[low] >= self.propn_lowercase_rescue and lowc[low] >= capc[low]:
                    # capitalised mid-sentence but mostly written lowercase: the
                    # common word (cerita Ayah, Bahasa Indonesia, Presiden Reagan),
                    # which the name rule (no capitalised word links) would skip
                    lem, upos = (tk[1], tk[2]) if tk[2] != "PROPN" else lowpos[low].most_common(1)[0][0]
                    toks[j] = (low, lem, upos, tk[3])
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
        import bz2
        p = env.repo / "tools" / "generated_sentences.tsv"
        rows = []
        if not p.exists():
            return rows
        # a generated sentence repeating a Tatoeba one (or an earlier generated
        # one) is dropped: the pack never ships the same text twice
        seen = set()
        data = bz2.decompress((env.cache / self.sentences_file).read_bytes()).decode("utf-8")
        for line in data.split("\n"):
            q = line.split("\t")
            if len(q) >= 3 and q[1] == self.tatoeba_code:
                seen.add(q[2].strip())
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                raise ValueError(f"generated_sentences.tsv line {i+1}: need key<TAB>text<TAB>english")
            if parts[1].strip() in seen:
                continue
            seen.add(parts[1].strip())
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

        def zipf_ok(root, form, margin=FOLD_ZIPF_MARGIN):
            return lx.zipf(root) >= lx.zipf(form) - margin

        def free_margin(w):
            """0.5 for a plain me- verb; 1.5 when w is also a preposition or
            adjective (mengenai "about", menarik "interesting"): its frequency
            is not the verb's, so it never outranks a free root (kena, tarik)."""
            other = any(e["p"] != "verb" and lx.entry_usable(e) for e in E.get(w, []))
            return FOLD_ZIPF_MARGIN if other else ROOT_FREE_MARGIN

        def kan_form(r):
            """lakukan, bayangkan: a -kan spelling built on a word (not makan, ikan)."""
            return r.endswith("kan") and len(r) >= 6 and r[:-3] in E

        # (F) a "form" line whose "of X" sits deep in a definition (perpustakaan:
        # "an institution which holds books and/or other forms of media ...") is
        # a definition, not a form of X; its pointers go
        for w in sorted(E):
            revived = set()
            for e in E[w]:
                for sn in e["s"]:
                    if sn[3] == "form" and not FORM_LINE_RE.match(sn[0]) and not AFFIX_OF_RE.match(sn[0]) and \
                            not SYNONYM_RE.match(sn[0]) and "form-of" not in sn[2] and len(sn[0].split()) > 8:
                        sn[3] = ""
                        revived.add(e["p"])
                        stats["definition read as form-of line: sense again"] += 1
            for pos in revived:
                if not any(sn[3] in ("form", "alt") for e in E[w] if e["p"] == pos for sn in e["s"]) and w in F:
                    F[w] = [f for f in F[w] if f[1] != pos]
                    if not F[w]:
                        del F[w]
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
                    m = COLON_RE.match(sn[0]) if sn[3] == "" else None
                    if m and len(m.group(1).split()) <= 4 and not m.group(1).lower().startswith("used") and \
                            m.group(1).strip().lower() != w:
                        # "shelf: a flat, rigid structure ..." -> shelf
                        sn[0] = m.group(1).strip()
                        stats["definition tail cut (translation: definition)"] += 1
                    if sn[3] == "" and sn[0].lower() in seen:
                        continue
                    seen.add(sn[0].lower())
                    keep.append(sn)
                e["s"] = keep
        # (S) "synonym of datang (“to arrive; to come”)" is a word of its own
        # with that meaning (tiba "to arrive"), never a form of its synonym
        for w in sorted(E):
            for e in E[w]:
                conv = False
                for sn in e["s"]:
                    m = SYNONYM_RE.match(sn[0]) if sn[3] in ("form", "alt") else None
                    if not m:
                        continue
                    tgt, g = m.group(1), m.group(2)
                    if not g:
                        g = next((s2[0] for e2 in E.get(tgt, []) if e2["p"] == e["p"] for s2 in e2["s"]
                                  if s2[3] == ""), None)
                    if not g:
                        # target not a single headword (es teh manis): the line is neither
                        # a sense nor a form, and its pointer (to "es") is dropped
                        sn[3] = "junk"
                        if w in F:
                            F[w] = [f for f in F[w] if not (f[0] == tgt.split()[0] and f[1] == e["p"])]
                            if not F[w]:
                                del F[w]
                        stats["synonym-of line without a headword target skipped"] += 1
                        continue
                    sn[0], sn[1], sn[3] = g, "", ""
                    sn[2] = [t for t in sn[2] if t not in ("form-of", "alt-of", "synonym")]
                    if w in F:
                        F[w] = [f for f in F[w] if not (f[0] == tgt and f[1] == e["p"])]
                        if not F[w]:
                            del F[w]
                    conv = True
                    stats["synonym-of line -> own sense"] += 1
                if conv:
                    e["s"] = [sn for sn in e["s"] if "from-form-sense" not in sn[2]]
        # (J) abbreviation / bare-affix senses are not translations (siap
        # "abbreviation of sisa anggaran ...", bawah "sub-")
        for w in sorted(E):
            for e in E[w]:
                for sn in e["s"]:
                    if sn[3] == "" and JUNK_SENSE_RE.match(sn[0].strip()):
                        sn[3] = "junk"
                        stats["abbreviation/affix sense skipped"] += 1
        # (A) a frequent word whose only lines are "form" lines with no target
        # (merupakan "to take the form of, to be"): the lines are its senses
        for w in sorted(E):
            if w in F or lx.zipf(w) < 4.5 or any(lx.entry_usable(e) for e in E[w]):
                continue
            for e in E[w]:
                for sn in e["s"]:
                    if sn[3] == "form" and not re.search(r"\bof [a-z]+(?:-[a-z]+)*(?: \(“[^”]*”\))?\W*$", sn[0]):
                        sn[3] = ""
                        stats["frequent word: target-less form line read as its sense"] += 1
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
        # (4, before 1: a -kan spelling that is only its base's form never
        # heads a me- verb) -kan / -i verbs that repeat their base verb's sense (berikan =
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
                plain = tgt in me_roots(w)       # memakai / pakai, not memberikan / beri
                if verb_senses(tgt) and w.startswith("me") and plain and kan_form(tgt):
                    # melakukan "active of lakukan": the -kan spelling is the
                    # object-voice form of the me- verb, and the me- verb is the word
                    e["s"] = [list(sn) for _, sn in verb_senses(tgt)] + \
                             [sn for sn in e["s"] if not (sn[3] == "" and AFFIX_OF_RE.match(sn[0]))]
                    mark_form(tgt, "verb", w, "object-voice -kan form = me- verb")
                    self.voice_alt.setdefault(w, set()).add(tgt)
                elif verb_senses(tgt) and not ME_RE.match(w) and ME_RE.match(tgt) and not w.endswith("kan") and \
                        lx.zipf(w) >= lx.zipf(tgt) - 0.5:
                    # the root is the everyday word (mulai "basic form of
                    # memulai"): the root takes the affixed word's senses and
                    # the affixed word becomes its form
                    e["s"] = [list(sn) for _, sn in verb_senses(tgt)] + \
                             [sn for sn in e["s"] if not (sn[3] == "" and AFFIX_OF_RE.match(sn[0]))]
                    mark_form(tgt, "verb", w, "affixed verb = its root (root commoner)")
                elif verb_senses(tgt) and (zipf_ok(tgt, w, free_margin(w) if plain else FOLD_ZIPF_MARGIN) or
                                           not w.startswith("me")):
                    mark_form(w, "verb", tgt, "affix-of gloss")
                elif verb_senses(tgt) and not plain:
                    # the root is far rarer than a derived verb: the derived verb
                    # is the lemma and takes the root's senses
                    e["s"] = [list(sn) for _, sn in verb_senses(tgt)] + \
                             [sn for sn in e["s"] if not (sn[3] == "" and AFFIX_OF_RE.match(sn[0]))]
                    stats["affixed kept, root senses copied"] += 1
                elif verb_senses(tgt):
                    # the root is rare on its own (mengerti / erti, menangis /
                    # tangis): the me- verb is the lemma, takes the root's senses,
                    # and the root (and its di- forms) count toward it
                    e["s"] = [list(sn) for _, sn in verb_senses(tgt)] + \
                             [sn for sn in e["s"] if not (sn[3] == "" and AFFIX_OF_RE.match(sn[0]))]
                    mark_form(tgt, "verb", w, "root = its me- verb (root rarer)")
                    self.voice_alt.setdefault(w, set()).add(tgt)
        # (2) me-/di- verbs with senses of their own that repeat a shorter
        # verb's (memakai = pakai, melakukan = lakukan, menulis = tulis)
        for w in sorted(E):
            if not ME_RE.match(w) or not verb_senses(w):
                continue
            for root in me_roots(w):
                if not (root in E and verb_senses(root) and verb_head(w) & verb_head(root)):
                    continue
                if kan_form(root) and w.startswith("me"):
                    mark_form(root, "verb", w, "object-voice -kan form = me- verb")   # lakukan -> melakukan
                    self.voice_alt.setdefault(w, set()).add(root)
                    break
                if zipf_ok(root, w, free_margin(w)):
                    mark_form(w, "verb", root, "me-/di- verb = root")
                    break
        # (2b) one verb, two headwords: a me- verb and its object-voice spelling
        # (menonton / tonton, membayangkan / bayangkan, menghindari / hindar)
        # sharing a sense become one word: the -kan spelling always counts
        # toward the me- verb; a bare root is the word only when it is about as
        # common as the me- verb (simpan, periksa), else it counts toward it
        for w in sorted(E):
            if not w.startswith("me") or not ME_RE.match(w) or not verb_senses(w):
                continue
            cands = []
            for r in me_roots(w):
                cands.append((r, False))
                if r.endswith("i") and not verb_senses(r):
                    cands.append((r[:-1], True))   # menghindari -> hindari -> hindar
                if kan_form(r) and not verb_senses(r):
                    cands.append((r[:-3], True))   # menerjemahkan -> terjemahkan -> terjemah
            for r, stripped in cands:
                voice = stripped or (kan_form(r) and r in me_roots(w))
                # an object-voice spelling (sampaikan, hindar-i) is the me- verb by
                # its form; a bare root must also share a sense (menarik / tarik)
                if r == w or not verb_senses(r) or not (voice or overlaps(verb_words(w), verb_words(r))):
                    continue
                if stripped and zipf_ok(r, w, free_margin(w)):
                    break       # mengikuti / ikut, menduduki / duduk: the -i verb is a word of its own
                if kan_form(r) and r in me_roots(w):
                    mark_form(r, "verb", w, "object-voice -kan form = me- verb")
                    self.voice_alt.setdefault(w, set()).add(r)
                elif zipf_ok(r, w, free_margin(w)):
                    if not lx.usable_entries(r, ["verb"]):
                        break   # amat "to observe" is literary only: mengamati stays the word
                    mark_form(w, "verb", r, "me-/di- verb = root")
                else:
                    mark_form(r, "verb", w, "root = its me- verb (root rarer)")
                    self.voice_alt.setdefault(w, set()).add(r)
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
                    # an entry that is a plural of the base is plural throughout
                    # (anak-anak "child", "subordinate"); a lexicalised reading is
                    # its own entry (mata-mata "spy", hati-hati "careful")
                    if sn[3] == "" and (plural or (e["p"] == "noun" and gloss_words(sn[0]) and
                                                    gloss_words(sn[0]) <= bw | {"s"})):
                        sn[3] = "form"
                        stats["reduplicated sense = base"] += 1
                if e["p"] == "noun" and plural:
                    fl = F.setdefault(w, [])
                    if [base, "noun", "form"] not in fl:
                        fl.append([base, "noun", "form"])
        # (O) a hand gloss is a sense of its word: it leads the entry of that
        # POS, and a frequent word Wiktionary has no usable entry for (ternyata,
        # suatu, berbagai) gets one from it. A word counted as another word's
        # form keeps no entry of its own.
        ov = self.gloss_overrides or {}
        for key in sorted(ov):
            lem, _, lab = key.rpartition("|")
            kp = LABEL_KPOS.get(lab)
            if not kp or not lem:
                continue
            usable = [e for e in E.get(lem, []) if e["p"] == kp and lx.entry_usable(e)]
            if usable:
                if usable[0]["s"][0][0] != ov[key]:
                    usable[0]["s"].insert(0, [ov[key], "", [], ""])
            elif not any(f[1] == kp for f in F.get(lem, [])):
                E.setdefault(lem, []).append({"p": kp, "s": [[ov[key], "", [], ""]], "ht": set()})
                stats["entry from hand gloss (no usable Wiktionary entry)"] += 1
                self.affix_log.append(f"{lem} {kp}: entry from hand gloss")
        self.affix_stats = dict(stats)

    def _classifiers(self):
        self._kaikki_words()
        return self._clf

    def _idiom_pairs(self):
        """Two-word Wiktionary headwords whose meaning is not built from their
        parts (sama sekali "at all", bulu babi "sea urchin", rumah sakit
        "hospital", masuk akal "reasonable"): (a, b) -> the parts that keep a
        link (a part whose hand gloss teaches the phrase: berterima in
        "berterima kasih"). A pair is compositional when its gloss shares a
        word (or stem) with a part's glosses (hari ini "today", kamar mandi
        "bathroom", jatuh cinta "to fall in love"). Pairs with a closed word,
        a number or a comparative (lebih baik) and the taught phrases are left
        to the normal rules."""
        if self._idioms is None:
            from ..core.english import en_stem
            kw = self._kaikki_words()
            ov_by = {}
            for k, v in (self.gloss_overrides or {}).items():
                ov_by.setdefault(k.rpartition("|")[0], []).append(v)
            closed = set(self.closed_surfaces) | {w for w, _ in self.forced_closed} | self.function_lemmas | \
                set(NUMBERS) | set(PHRASES)
            pointer = re.compile(r"^(?:synonym of|(?:active|passive|imperative|basic)(?: form)? of|alternative "
                                 r"(?:form|spelling) of) ([a-z-]+ [a-z-]+)(?: \(“([^”]+)”\))?")

            def glosses(pair, depth=0):
                out = []
                for g in self._mw.get(pair, []):
                    m = pointer.match(g)
                    if not m:
                        out.append(g)
                    elif m.group(2):
                        out.append(m.group(2))
                    elif depth < 2:
                        out += glosses(tuple(m.group(1).split()), depth + 1)
                return out

            def stems(words):
                words = {w for w in words if w not in GLOSS_STOP}
                return words | {en_stem(w) for w in words}

            res = {}
            for pair in sorted(self._mw):
                a, b = pair
                if a in closed or b in closed or a in DEGREE_WORDS or " ".join(pair) in closed:
                    continue
                cg = stems({w for g in glosses(pair) for w in re.findall(r"[a-z]+", g.lower())})
                if not cg:
                    continue
                parts = []
                for x in pair:
                    pw = set()
                    for y in {x, self._lx.chase(x, None) if self._lx is not None else None} - {None}:
                        pw |= set(kw.get(y, (set(), set()))[1])      # merokok: the glosses of rokok
                        for g in ov_by.get(y, []):
                            pw |= set(re.findall(r"[a-z]+", g.lower()))
                    parts.append(stems(pw))
                if any(overlaps(cg, pw) for pw in parts):
                    continue
                phrase = " ".join(pair)
                res[pair] = {x for x in pair if any(phrase in g for g in ov_by.get(x, []))}
            for pair in sorted((FORCED_IDIOMS | OPAQUE_IDIOMS) - set(res)):
                phrase = " ".join(pair)
                keep = {x for x in pair if any(phrase in g for g in ov_by.get(x, []))}
                if pair in FORCED_IDIOMS:
                    cg = stems({w for g in glosses(pair) for w in re.findall(r"[a-z]+", g.lower())})
                    for x in pair:
                        pw = set(kw.get(x, (set(), set()))[1])
                        for g in ov_by.get(x, []):
                            pw |= set(re.findall(r"[a-z]+", g.lower()))
                        if cg and overlaps(cg, stems(pw)):
                            keep.add(x)
                if keep != set(pair):
                    res[pair] = keep
            self._idioms = res
        return self._idioms

    def surface_link_ok(self, tok):
        """The sentence-initial surface fallback (link the pack word spelled
        like the token) only for a token the tagger took for a name or could
        not tag: "Bagilah" (bagi "to divide", tagged ADP) is not the pack's
        preposition bagi "for". Other POS mismatches go through
        cross_pos_link, which checks the sense."""
        return tok[2] in ("PROPN", "X", "INTJ")

    def _gloss_stems(self, word, kpos=None, extra=()):
        """Gloss words (and their English stems) of word's usable entries, plus
        extra glosses; with kpos=None the word's hand glosses are added too."""
        from ..core.english import en_stem
        ws = set()
        for e in self._lx.usable_entries(word, kpos):
            for sense in e["s"]:
                ws |= gloss_words(str(sense[0]))
        if kpos is None:
            extra = list(extra) + [v for k, v in (self.gloss_overrides or {}).items() if k.rpartition("|")[0] == word]
        for g in extra:
            ws |= gloss_words(g)
        return ws | {en_stem(x) for x in ws}

    def cross_pos_link(self, lexicon, lem, group, key_to_id):
        """A token read with a POS the pack has no entry for links the lemma's
        only pack entry when the reading means the same: its glosses for the
        tagged POS share a word (or English stem) with the pack entry's
        glosses and hand gloss. "Kami semua" (PRON) -> semua "all" (DET),
        "tampak seperti" (CONJ) -> seperti "like", "kurang tidur" (NOUN) ->
        tidur "to sleep"; "bangga akan" (ADP "about") is not akan "will",
        "kena pukul" (VERB "hit") is not pukul "o'clock"."""
        from ..core.english import en_stem
        if group not in self.group_kpos or group in ("PROPN", "PHRASE"):
            return None
        if self._key_index is None or self._key_index[0] is not key_to_id:
            by = {}
            for k in key_to_id:
                if k[1] != "PHRASE":
                    by.setdefault(k[0], []).append(k)
            self._key_index = (key_to_id, by)
        ks = self._key_index[1].get(lem, [])
        if len(ks) != 1 or ks[0][1] not in self.group_kpos:
            return None

        def stems(entries, extra=()):
            ws = set()
            for e in entries:
                for sense in e["s"]:
                    ws |= gloss_words(str(sense[0]))
            for g in extra:
                ws |= gloss_words(g)
            return ws | {en_stem(x) for x in ws}
        tagged = stems(lexicon.usable_entries(lem, self.group_kpos[group]))
        if not tagged:
            return None
        ov = [v for k, v in (self.gloss_overrides or {}).items() if k.rpartition("|")[0] == lem]
        packed = stems(lexicon.usable_entries(lem, self.group_kpos[ks[0][1]]), ov)
        if overlaps(tagged, packed):
            self.post_stats["other-POS reading, same sense: the pack entry"] += 1
            return key_to_id[ks[0]]
        return None

    def post_resolve(self, toks, out):
        """Context rules over the resolved tokens.
        - The tagger's lemma is a form of another word: that word (dikirim ->
          kirim -> mengirim).
        - se- + classifier (seorang, seekor, sebuah) is the classifier word;
          di/ke/dari + a place word written as one token (disini, kemana) is
          the place word; a variant spelling of a closed word (silahkan) is it.
        - A VERB- or NOUN-tagged word with no such reading is a predicate
          adjective ("Saya malu", "Saya tertarik"); a word tagged content but
          read as an interjection (siap) takes its content reading; an
          unlisted base + -kan (biarkan) is the base verb.
        - host + -lah on a verb is its imperative (Bagilah, hiduplah).
        - A surface that is a word of its own keeps it, where the tagger lemma
          or the plural rule sent it to a root: laki-laki, kupu-kupu,
          terlambat "late" (not lambat "slow"); anak-anak -> anak and
          terburuk -> buruk stay (their entries are only form-of lines).
        - A derived surface Wiktionary does not list (persahabatan, terserah)
          links nothing: its tagger root is another word (sahabat, serah).
          me-/di- surfaces are inflections and keep the root.
        - The parts of a non-compositional compound link nothing (sama sekali,
          bulu babi; see _idiom_pairs)."""
        lx = self._lx
        clf = self._classifiers()
        idi = self._idiom_pairs()
        st = self.post_stats
        n = len(toks)
        adj_kp = self.group_kpos["ADJ"]
        for i, t in enumerate(toks):
            r = out[i]
            low = t[0].lower()
            if r is None and low in self.closed_surfaces and t[2] == "X":
                out[i] = tuple(self.closed_surfaces[low])     # banget, dong tagged X
                continue
            m = LOCATIVE_RE.match(low)
            if m and not lx.usable_entries(low, None):
                out[i] = LOCATIVE_KEY[m.group(1)]
                st["di/ke/dari + place word spelled as one"] += 1
                continue
            prev = toks[i - 1][0].lower() if i else ""
            if prev in AGENT_PRONOUNS and (not r or r[1] != "VERB") and t[2] not in ("PUNCT", "X", "NUM") and \
                    low not in self.closed_surfaces and low not in self.function_lemmas and \
                    any(u[0].lower() == "yang" for u in toks[max(0, i - 4):i - 1]):
                # object voice: "(hal) yang pernah kamu alami" is mengalami "to
                # experience", not alami "natural"
                v = lx.chase(me_form(low), ["verb"])
                if v:
                    out[i] = (v, "VERB")
                    st["object voice after yang + pronoun: the me- verb"] += 1
                    continue
            if prev in ("kena", "terkena") and (not r or r[1] != "VERB") and t[2] not in ("PUNCT", "X"):
                # adversative passive: "kena pukul" is pukul "to hit", not "o'clock"
                v = lx.chase(low, ["verb"])
                if v:
                    out[i] = (v, "VERB")
                    st["kena + verb: the verb"] += 1
                    continue
            if r and "-" in low and r[0] != low and (low in LEXICAL_REDUP or lx.usable_entries(low, None) and
                                                      not overlaps(self._gloss_stems(low), self._gloss_stems(r[0]))):
                # a reduplication that is a word of its own, its glosses sharing
                # nothing with the root's (rata-rata "average", mata-mata "spy",
                # satu-satunya "the only"), is not its root; dalam-dalam
                # "deeply" and bunga-bungaan "various flowers" keep it
                out[i] = None
                st["lexicalised reduplication: no root link"] += 1
                continue
            if not r or r[1] == "PROPN" or r[1] not in self.group_kpos or low in self.closed_surfaces:
                continue
            if low.startswith("se") and low[2:] in clf and not lx.usable_entries(low, None):
                out[i] = (low[2:], "NOUN")
                st["se- + classifier"] += 1
                continue
            alt = next((f[0] for f in lx.F.get(low, []) if f[0] in self.closed_surfaces), None)
            if alt and not lx.usable_entries(low, None):
                out[i] = tuple(self.closed_surfaces[alt])
                st["variant spelling of a closed word"] += 1
                continue
            kp = self.group_kpos[r[1]]
            pro = next((low[len(p):] for p in ("kau", "ku") if low.startswith(p) and len(low) > len(p) + 2), None)
            if t[2] == "VERB" and pro and not lx.usable_entries(low, None) and lx.chase(pro, ["verb"]):
                # ku-/kau- + object-voice verb: kulakukan "(that) I do", kaulihat
                out[i] = (lx.chase(pro, ["verb"]), "VERB")
                st["ku-/kau- + verb: the verb"] += 1
                continue
            if not lx.usable_entries(r[0], kp):
                c = lx.chase(r[0], kp)
                if c and c != r[0]:
                    r = out[i] = (c, r[1])
                    st["tagger lemma is a form: its lemma"] += 1
            if not lx.usable_entries(r[0], None) and low.endswith("kan") and \
                    (lx.chase(me_form(low), ["verb"]) or lx.chase(low[:-3], ["verb"])):
                # an object-voice -kan spelling with no entry of its own: its me-
                # verb (kenakan -> mengenakan "to wear"), else the base verb
                # (biarkan -> biar, butuhkan -> butuh)
                r = out[i] = (lx.chase(me_form(low), ["verb"]) or lx.chase(low[:-3], ["verb"]), "VERB")
                st["unlisted -kan spelling: its me- or base verb"] += 1
            obj_clitic = i + 1 < n and toks[i + 1][2] == "X" and toks[i + 1][0].lower() in ("nya", "ku", "mu")
            nxt = next((u[2] for u in toks[i + 1:] if u[2] != "X"), "PUNCT")
            both = re.search(r"\bto [a-z]", (self.gloss_overrides or {}).get(f"{low}|adj", ""))
            if t[2] == "VERB" and low.startswith("me") and r[0] != low and lx.usable_entries(low, adj_kp) and \
                    (both or (not obj_clitic and nxt in ("PUNCT", "ADV", "ADP", "CCONJ", "PART"))):
                # me- adjectives the tagger calls verbs, ending a clause: "Buku
                # itu menarik" "interesting", menyenangkan "pleasant", membosankan
                # "boring"; with an object ("mendengarnya", "mendengar kalau ...")
                # it is the verb. A hand gloss teaching both senses (menarik
                # "interesting; to pull") takes every use.
                out[i] = (low, "ADJ")
                st["me- adjective tagged VERB: the adjective"] += 1
                continue
            if r[0] == low and r[1] in ("VERB", "NOUN") and lx.usable_entries(low, adj_kp) and \
                    not any(f[1] == "verb" for f in lx.F.get(low, [])) and \
                    (t[2] == "VERB" and r[1] != "VERB" or not lx.usable_entries(low, self.group_kpos[r[1]])):
                # "Saya malu", "Saya tertarik": a predicate adjective the tagger
                # called a verb or noun
                r = out[i] = (low, "ADJ")
                st["VERB/NOUN-tagged, no such reading: adjective"] += 1
            elif t[2] in ("VERB", "NOUN", "ADJ") and r[1] in ("INTJ", "PART") and r[0] == low:
                g2 = next((g for g in ("ADJ", "NOUN", "VERB", "ADV")
                           if lx.usable_entries(low, self.group_kpos[g])), None)
                if g2:
                    r = out[i] = (low, g2)
                    st["content-tagged, read as interjection: content reading"] += 1
            if i + 1 < n and toks[i + 1][2] == "X" and toks[i + 1][0].lower() == "lah" and r[1] != "VERB":
                v = lx.chase(low, ["verb"])
                if v:
                    out[i] = (v, "VERB")
                    st["host + -lah: imperative verb"] += 1
                    continue
            if r[0] == low:
                continue
            if lx.usable_entries(low, self.group_kpos[r[1]]):
                out[i] = (low, r[1])
            elif low not in lx.E and low not in lx.F and not ME_RE.match(low) and DERIVED_RE.match(low) and \
                    (r[0] in low or len(r[0]) > 3 and r[0][1:] in low):     # penyerangan: s- -> ny-
                out[i] = None
                self.n_derived_unlinked += 1
        for i in range(n - 1):
            pair = (toks[i][0].lower(), toks[i + 1][0].lower())
            if pair in idi:
                for j, x in ((i, pair[0]), (i + 1, pair[1])):
                    if x not in idi[pair] and out[j] is not None:
                        out[j] = None
                        st["idiom part unlinked"] += 1
        return out

    # ---- sentences ------------------------------------------------------------
    def sentence_rank(self, toks, lv):
        if lv == self.level_ids[0] and any(t[0].lower() in COLLOQ_MARK for t in toks):
            return 1        # A1 examples: formal/neutral register first
        return 0

    def classifier_note(self, lem):
        """(classifier for animals) from kaikki's "Classifier used for animals."."""
        g = self._classifiers().get(lem, "")
        m = re.search(r"\bfor ([a-z ]+?)(?:[,.;(]|$| and | as | or | generally)", g.lower())
        what = m.group(1).strip() if m else ""
        if not what or len(what.split()) > 3 or what.startswith(("anything", "things that", "something")):
            what = "things"
        return f"(classifier for {what})"

    def classifier_uses(self, ctx):
        """Corpus uses of each classifier word in classifier position: a number
        (or se-) + the classifier + the noun it counts (tiga ekor ayam, sebatang
        rokok); "empat kaki" (four legs) is not one."""
        from ..core.tag import iter_tagged
        clf = self._classifiers()
        nums = set(NUMBERS) | {"beberapa", "berapa", "setiap", "tiap"}
        uses = Counter()
        for _, toks in iter_tagged(ctx["tagged"]):
            for j, t in enumerate(toks):
                low = t[0].lower()
                nxt = toks[j + 1][2] if j + 1 < len(toks) else "PUNCT"
                if nxt not in ("NOUN", "PROPN"):
                    continue
                if low.startswith("se") and low[2:] in clf:
                    uses[low[2:]] += 1
                elif low in clf and j and (toks[j - 1][2] == "NUM" or toks[j - 1][0].lower() in nums):
                    uses[low] += 1
        return uses

    def inflection_forms(self, ctx, words):
        """{word key: Counter(written form)}: the bare word and every whole written word of a
        translated corpus sentence whose token resolves to the key and is an
        inflection of it: me-/di-/ber-/ter-/per-/ku-/kau- with -kan/-i, an
        enclitic (-nya -ku -mu -lah -kah -pun), or a reduplication
        (anak-anaknya, berjam-jam, dipikir-pikir)."""
        from ..core.tag import iter_tagged
        lx, rows, groups = ctx["lexicon"], ctx["rows_by_sid"], ctx.get("lemma_groups")
        forms = {}
        for w in words:
            if w["_key"][1] == "PHRASE" or " " in w["lemma"]:
                continue
            lem = w["lemma"]
            roots = {lem} | set(self.voice_alt.get(lem, ()))
            if lem.startswith(("me", "di")):
                roots |= set(me_roots(lem))
            fs = set()
            for r in roots:
                for suf in ("", "kan", "i"):
                    fs.add(me_form(r) + suf)
                    fs.update(pre + r + suf for pre in INFLECT_PREFIXES)
            forms[w["_key"]] = fs

        def related(form, fs):
            f = form
            for _ in range(3):
                if f in fs or ("-" in f and any(x in fs for x in f.split("-"))):
                    return True
                m = CLITIC_TAIL_RE.search(f)
                if not m or m.start() < 2:
                    return False
                f = f[:m.start()]
            return False
        seen = {k: Counter() for k in forms}
        for sid, toks in iter_tagged(ctx["tagged"]):
            row = rows.get(sid)
            if not row or not row[3]:
                continue
            text = row[1].lower()
            res = lx.resolve_sentence(toks, groups)
            cur = 0
            for t, r in zip(toks, res):
                tl = t[0].lower()
                at = text.find(tl, cur) if tl.strip() else -1
                if at < 0:
                    continue
                cur = at + len(tl)
                if r not in seen or t[2] == "PUNCT":
                    continue
                a, b = at, cur
                while a and (text[a - 1].isalpha() or text[a - 1] == "-"):
                    a -= 1
                while b < len(text) and (text[b].isalpha() or text[b] == "-"):
                    b += 1
                form = text[a:b].strip("-")
                if form == r[0] or related(form, forms[r]):
                    seen[r][form] += 1
        return seen

    def finalize_words(self, env, ctx, words):
        clf = self._classifiers()
        uses = self.classifier_uses(ctx)
        infl = self.inflection_forms(ctx, words)
        # an inflected form taken by two words, or spelled like another word,
        # is nobody's alt (it would make the reading ambiguous)
        owner = Counter(f for c in infl.values() for f in c)
        heads = {w["w"].lower() for w in words} | {w["lemma"] for w in words}
        swapped = []
        for w in words:
            if w["lemma"] in clf and w["_key"][1] == "NOUN" and "classifier" not in w["en"] and \
                    uses[w["lemma"]] >= 2:
                w["en"] = w["en"] + "; " + self.classifier_note(w["lemma"])
            va = self.voice_alt.get(w["lemma"])
            if va and w["_key"][1] == "VERB":
                w["alt"] = sorted(set(w.get("alt") or []) | va)
            c = infl.get(w["_key"], Counter())
            extra = [f for f, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))
                     if owner[f] == 1 and f not in heads and f not in (w.get("alt") or [])]
            if extra:
                w["alt"] = (w.get("alt") or []) + extra
            if w["_key"][1] == "VERB" and w["lemma"] == w["w"] and not w["lemma"].startswith(("me", "ber", "ter", "di")):
                # the headword is the form learners meet: a root seen bare in
                # under 20% of its uses is shown as its commonest me- verb
                # (periksa -> memeriksa), the root kept as alt[0]
                bare = sum(n for f, n in c.items() if CLITIC_TAIL_RE.sub("", f) == w["lemma"])
                total = sum(c.values())
                mes = {me_form(w["lemma"]) + suf for suf in ("", "kan", "i")}
                # the plain me- verb when attested (menyanyi, not menyanyikan)
                me = sorted((f != me_form(w["lemma"]), -n, f) for f, n in c.items()
                            if f in mes and f in (w.get("alt") or []))
                if total >= 5 and bare < 0.2 * total and me:
                    head = me[0][2]
                    w["alt"] = [w["lemma"]] + [a for a in w["alt"] if a != head]
                    w["w"] = head
                    swapped.append(f"{w['lemma']}->{head} ({bare}/{total} bare)")
            if w["_key"][1] == "VERB" and w["lemma"] not in self.function_lemmas:
                first = re.split(r"[;,]", w["en"])[0].strip()
                if ADJ_GLOSS_RE.match(first) and not first.endswith("ly") and len(first) >= 5:
                    w["pos"] = "adj"         # bersalah "guilty", berguna "useful": taught as adjectives
            if w["lemma"] in CAPITALISED:
                w["w"] = CAPITALISED[w["lemma"]]
            if w["_key"] == ("nggak", "PART"):
                w["alt"] = ["gak", "enggak", "ngga"]
            if w["_key"] == ("tetapi", "CONJ"):
                w["alt"] = ["tapi"]
        self.post_stats["headword shown as its me- verb"] = len(swapped)
        self.swapped_heads = swapped

    # ---- reading passages (passage-only; the corpus build never calls these) --
    def _pack_lemmas(self):
        """Passages: {lemma: pos} of the shipped pack words (pack/words.json)."""
        if getattr(self, "_pl", None) is None:
            import json
            ws = json.loads((self.repo / "pack" / "words.json").read_text())
            self._pl = {}
            self._pkeys = set()     # (lemma, pos) of every pack word (hidup is a verb and a noun)
            for w in ws:
                self._pl.setdefault(w["lemma"], w["pos"])
                self._pkeys.add((w["lemma"], w["pos"]))
        return self._pl

    def _compounds(self, toks):
        """Passages: [(i, lemma, pos)] for each PASSAGE_COMPOUNDS pair at
        tokens i, i+1 whose target is a pack word, left to right, a token in
        at most one pair."""
        self._pack_lemmas()
        out, used = [], set()
        for i in range(len(toks) - 1):
            pair = ((toks[i][0] or "").lower(), (toks[i + 1][0] or "").lower())
            hit = PASSAGE_COMPOUNDS.get(pair)
            if hit and i not in used and hit in self._pkeys:
                out.append((i, hit[0], hit[1]))
                used |= {i, i + 1}
        return out

    def passage_text(self, text, names, lexicon):
        """Passages only: a capitalised word that opens the text, a sentence
        after . ! ? or quoted speech, and is not a declared name, is lowercased
        when it is a pack word or an address form ("Bu, saya mau...", "Nenek
        tahu", "\"Kamu mau..."). tag_texts' PROPN rescue counts lowercase uses
        across the texts it is given, so passage tagging (a small batch) may
        otherwise keep such a word a name."""
        pl = self._pack_lemmas()

        def low(m):
            w = m.group(2)
            lw = w.lower()
            if w in names or w.isupper() or not (lw in pl or lw in PASSAGE_ADDRESS):
                return m.group(0)
            return m.group(1) + lw
        return re.sub(r'((?:^|[.!?]\s+|["\u201c]))([A-Z][a-z]+)\b', low, text)

    def passage_post_resolve(self, toks, out):
        """Passages only, after post_resolve:
        - a short address form passage_retag read as its pack noun (Bu ->
          ibu, Dok -> dokter) keeps that reading;
        - a verb whose resolved lemma is not a pack word, while its tagger
          lemma (or passage_retag's root) is a pack verb, reads as that pack
          verb when the surface has no entry of its own or its glosses share
          a word with the pack verb's (menunjuk "to point" -> tunjuk, memarkir
          -> parkir); a surface with a sense of its own keeps it;
        - baru before saja/akan or a verb, after a word that is not a noun or
          adjective, is the adverb "just, only then" (not the adjective "new");
          (after "yang" only when the next word is not ada/adalah: "Nomor saya
          yang baru ada di bawah" is new, "orang yang baru tinggal" is just);
        - quotative katanya (kata + -nya after a closing quote or opening a
          clause: '"...," katanya', "Katanya sangat menakutkan") is berkata,
          not kata "word";
        - a pack verb/noun homograph or a verb whose surface is a pack noun
          reads as the noun after cara ("cara bicara": bicara "talk", not
          berbicara) or, for a surface that is both a pack verb and a pack
          noun, opening a clause ("Ternyata hidup tanpa ponsel...", "bahwa
          hidup di sana..."): hidup "life";
        - an opaque idiom whose parts post_resolve unlinked and whose joined
          spelling is a pack word ("memberi tahu" -> memberitahu) reads as
          that word on its first part (passage_phrase_ranges spans both);
        - a PASSAGE_COMPOUNDS pair reads as its target on its first part and
          nothing on its second (passage_phrase_ranges spans both)."""
        pl = self._pack_lemmas()
        pk = self._pkeys
        n = len(toks)
        for i, t in enumerate(toks):
            low = (t[0] or "").lower()
            tgt = PASSAGE_ADDRESS.get(low)
            r = out[i]
            if tgt and tgt != low and t[1] == tgt:
                out[i] = (tgt, "NOUN")
            elif t[2] == "VERB" and pl.get(t[1]) == "verb" and t[1] != low and \
                    (r is None or (r[1] == "VERB" and r[0] not in pl)) and \
                    (i + 1 >= n or (low, toks[i + 1][0].lower()) not in OPAQUE_IDIOMS):
                own = self._gloss_stems(low, "verb") if self._lx.usable_entries(low, "verb") else set()
                if not own or overlaps(own, self._gloss_stems(t[1], "verb")):
                    out[i] = (t[1], "VERB")
            if low == "baru" and r == ("baru", "ADJ") and i + 1 < n and i and \
                    (toks[i + 1][0].lower() in ("saja", "akan") or toks[i + 1][2] in ("VERB", "AUX")) and \
                    toks[i - 1][2] not in ("NOUN", "ADJ") and \
                    not (toks[i - 1][0].lower() == "yang" and toks[i + 1][0].lower() in ("ada", "adalah")):
                out[i] = ("baru", "ADV")       # "itu baru akan berangkat", "Veteran baru saja dibuka": just, only then
            prev = toks[i - 1][0] if i else ""
            if low == "kata" and i + 1 < n and toks[i + 1][0].lower() == "nya" and \
                    (not i or prev in ('"', "\u201d", "\u201c", ".", "!", "?", ",", ";", ":")) and \
                    ("berkata", "verb") in pk:
                out[i] = ("berkata", "VERB")   # quotative katanya: "he/she said"
            elif r is not None and r[1] == "VERB" and (low, "noun") in pk and \
                    (prev.lower() in NOUN_AFTER or ((low, "verb") in pk and r[0] == low and
                                                     (not i or prev.lower() in CLAUSE_OPENERS or
                                                      not any(ch.isalnum() for ch in prev)) and
                                                     (i + 1 >= n or toks[i + 1][2] not in OBJECT_UPOS))):
                out[i] = (low, "NOUN")         # cara bicara, "Ternyata hidup tanpa ponsel": the noun
        for i in range(n - 1):
            pair = (toks[i][0].lower(), toks[i + 1][0].lower())
            joined = "".join(pair)
            if pair in OPAQUE_IDIOMS and out[i] is None and out[i + 1] is None and joined in pl:
                out[i] = (joined, PASSAGE_UPOS.get(pl[joined], "NOUN"))
        for i, lem, pos in self._compounds(toks):
            out[i], out[i + 1] = (lem, PASSAGE_UPOS.get(pos, "NOUN")), None
        return out

    def passage_fallback_ok(self, lexicon, reading, word, en=""):
        """Passages only: a verb reading with no pack key never falls back to a
        function word of the same lemma (membagi is not the preposition bagi
        "for")."""
        return not (reading[1] == "VERB" and word["pos"] in ("prep", "conj", "pron", "det", "part"))

    def passage_phrase_ranges(self, toks):
        """Passages only: an opaque idiom read as one pack word on its first
        part (passage_post_resolve: "memberi tahu" -> memberitahu) and a
        PASSAGE_COMPOUNDS pair (orang tua, rumah sakit) are one span over both
        parts."""
        pl = self._pack_lemmas()
        rs = {(i, i + 1, i) for i in range(len(toks) - 1)
              if (toks[i][0].lower(), toks[i + 1][0].lower()) in OPAQUE_IDIOMS
              and toks[i][0].lower() + toks[i + 1][0].lower() in pl}
        rs |= {(i, i + 1, i) for i, _l, _p in self._compounds(toks)}
        return sorted(rs)

    def passage_retag(self, toks):
        """Passages only:
        - a kinship word or short address form capitalised mid-sentence
          (Nenek, Kakek, Ayah, Mama; Bu, Kak, Dik, Dok) is the common noun
          (ibu, kakak, adik, dokter for the short forms), as fix_token does
          for Pak/Ibu/Paman (HONORIFICS); declared names keep PROPN; so is a
          title noun capitalised mid-sentence (PASSAGE_TITLES: "Bapak Ketua
          RT"), which caps_mark_names would otherwise skip as a name;
        - a di-/bare -kan or -i form whose me- form is a pack verb other than
          the tagger's root is that me- verb (dikembalikan, masukkan ->
          mengembalikan, memasukkan; not kembali "to return", masuk "to enter");
        - a verb form the tagger leaves unresolved or mislemmatises is the pack
          verb it is built on: an object-voice / imperative -i form (hubungi ->
          bubung, sukai, pelajari, kunjungi) -> its me- form (menyukai,
          mengunjungi, mempelajari) or bare root (hubung); a me-/di- form
          (menunjuk, memarkir -> markir, memberi before tahu) -> the root
          me_roots gives (tunjuk, parkir, beri), -kan/-i dropped. Only when
          neither the tagger lemma nor the surface is a pack lemma; a di- form
          whose tagger lemma is a pack non-verb reads as its me- pack verb
          (dikurangi -> mengurangi, not kurang "less");
        - an X-tagged token (not an enclitic) that is a pack word (oke) gets
          its dictionary class."""
        pl = self._pack_lemmas()
        kw = self._kaikki_words()
        for i, t in enumerate(toks):
            text = t[0] or ""
            low = text.lower()
            if low in PASSAGE_ADDRESS and not text.isupper() and t[2] not in ("PUNCT", "NUM") and \
                    (PASSAGE_ADDRESS[low] != low or (i and text[:1].isupper() and t[2] == "PROPN")):
                t[0], t[1], t[2] = low, PASSAGE_ADDRESS[low], "NOUN"
                continue
            if low in PASSAGE_TITLES and pl.get(low) == "noun" and i and text[:1].isupper() and \
                    not text.isupper() and t[2] in ("PROPN", "NOUN"):
                t[0], t[1], t[2] = low, low, "NOUN"     # lowercased: caps_mark_names would skip it
                continue
            stem = low[2:] if low.startswith("di") else low
            mf = me_form(stem) if len(stem) >= 6 and stem.endswith(("kan", "i")) else None
            if mf and low.isalpha() and low not in pl and not low.startswith(("me", "ber", "ter", "pe")) and \
                    t[2] not in ("PROPN", "PUNCT", "NUM") and pl.get(mf) == "verb" and t[1] and \
                    t[1] != mf and stem != t[1] and stem.startswith(t[1]):
                t[1], t[2] = mf, "VERB"     # dikembalikan: mengembalikan, not kembali
                continue
            if t[2] == "X" and low not in CLITICS and low in pl and low in kw:
                t[1] = low
                t[2] = next(u for p, u in KPOS_UPOS + [(None, "X")] if p is None or p in kw[low][0])
                continue
            if len(low) >= 6 and low.isalpha() and low.startswith("di") and low not in pl and \
                    t[2] not in ("PROPN", "PUNCT", "NUM") and pl.get(t[1]) not in (None, "verb") and \
                    pl.get(me_form(low[2:])) == "verb":
                t[1], t[2] = me_form(low[2:]), "VERB"     # dikurangi: mengurangi, not kurang "less"
                continue
            if len(low) >= 5 and low.isalpha() and t[1] not in pl and low not in pl and \
                    t[2] not in ("PROPN", "PUNCT", "NUM"):
                cands = []
                if low.endswith("i"):
                    cands += [me_form(low)] + (["mem" + low] if low.startswith("pe") else []) + [low[:-1]]
                if low.startswith(("me", "di")):
                    for r in me_roots(low):
                        cands += [r] + ([r[:-3]] if r.endswith("kan") else []) + ([r[:-1]] if r.endswith("i") else [])
                hit = next((c for c in cands if pl.get(c) == "verb"), None)
                if hit:
                    t[1], t[2] = hit, "VERB"
        return toks


SPEC = Indonesian
