"""Arabic (ar, Modern Standard Arabic): everything Arabic-specific in the pack pipeline.

Tagger: CAMeL Tools (MIT) with its contextual BERT unfactored MSA disambiguator
(disambig-bert-unfactored-msa, MIT) over the CALIMA MSA morphology database
(morphology-db-msa-r13, GPL-2.0), build time only. A token stays whole with its
clitics (وبالكتاب, أصدقائي): the lemma is the host's (كتاب, صديق), so the
definite article, the proclitics و ف ب ل ك س and pronoun suffixes never reach a
lemma. Raw analyses are cached per text (.cache/derived/camel_raw_*.jsonl.gz),
so rule changes never re-run the model.

Spelling: two folds. `fold` (lemma keys, Wiktionary headwords) strips harakat,
tatweel and the dagger alef and writes alef wasla as alef; hamza, ta marbuta
and alef maqsura stay (أن / إن, مدرسة, على). `lfold` (surfaces: tagged tokens,
frequency lists) also folds أ إ آ -> ا, ة -> ه, ى -> ي, since unvocalised text
writes them inconsistently. The displayed word is the lemma key (unvocalised,
with hamza); `pron` is the Wiktionary romanisation (DIN 31635 style).

MSA filter: Tatoeba "ara" mixes in dialect sentences. A sentence is dropped as
dialect (tagged as nothing: no frequency evidence, never shipped) when it holds
a dialect marker word, or when CAMeL's dialect ID (DIDModel6) gives it under
5% MSA and one of its tokens has no MSA analysis (analyser backoff).

Compounds: verb + preposition (قام بـ "to carry out", بحث عن "to look for"),
verb + noun light verbs (اتخذ قرارا) and fixed prepositional/adverbial phrases
(على الرغم من, من أجل, بالنسبة لـ) are lemmas of their own, resolved in
post_resolve over the tagged tokens (COMPOUNDS).
"""
import gzip
from collections import Counter
import hashlib
import json
import os
import re

from .base import (LanguageSpec, TATOEBA_ENG, TATOEBA_AUDIO, DEFAULT_GROUP_KPOS, SENSITIVE_EN,
                   SENSITIVE_GLOSS_EN, drop_all_re)

LET = "ء-غف-يٱ"          # hamza .. ghain, feh .. yeh, alef wasla
MARKS = "ً-ٰٟـ"                # harakat, dagger alef, tatweel
MARKS_RE = re.compile(f"[{MARKS}‌‍‎‏]")
_FOLD = str.maketrans({"ٱ": "ا", "ی": "ي", "ک": "ك", "ہ": "ه"})
_LOOK = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه",
                       "ى": "ي"})


def fold(s):
    """Lemma/headword spelling: harakat, tatweel, dagger alef, joiners stripped;
    alef wasla -> alef; Persian yeh/kaf -> Arabic. Hamza, ة and ى kept."""
    if not s:
        return s
    return MARKS_RE.sub("", s.translate(_FOLD))


def lfold(s):
    """Surface lookup spelling: fold + أ إ آ -> ا, ة -> ه, ى -> ي."""
    return fold(s).translate(_LOOK) if s else s


CAMEL_UPOS = {
    "noun": "NOUN", "noun_prop": "PROPN", "noun_num": "NUM", "noun_quant": "DET",
    "adj": "ADJ", "adj_comp": "ADJ", "adj_num": "ADJ",
    "adv": "ADV", "adv_interrog": "ADV", "adv_rel": "ADV",
    "pron": "PRON", "pron_dem": "PRON", "pron_exclam": "PRON", "pron_interrog": "PRON", "pron_rel": "PRON",
    "verb": "VERB", "verb_pseudo": "PART",
    "part": "PART", "part_det": "PART", "part_focus": "PART", "part_fut": "PART", "part_interrog": "PART",
    "part_neg": "PART", "part_restrict": "PART", "part_verb": "PART", "part_voc": "PART",
    "prep": "ADP", "conj": "CCONJ", "conj_sub": "SCONJ", "interj": "INTJ",
    "abbrev": "X", "punc": "PUNCT", "digit": "NUM", "latin": "X", "foreign": "X",
}
# dialect phrases whose words are MSA homographs one by one: بعت "send" (MSA
# بعث; تبعت alone is MSA "she followed") after a modal or as imperative/with
# لـ; المطافي "fire brigade" (Egyptian). Matched on lfold()ed tokens.
DIALECT_RE = re.compile(r"(?:^| )(?:(?:ان|لازم|ممكن|عشان|راح) [تينا]بعت|[تينا]?بعتل\S*|ابعت\S*|\S*مطافي)(?= |$)")
ENC_SUFFIX = ("كما", "هما", "كم", "كن", "هم", "هن", "ها", "نا", "ني", "ه", "ك")
RAW_FIELDS = ("lex", "pos", "prc3", "prc2", "prc1", "prc0", "enc0", "asp", "per", "gen", "num", "mod", "vox",
              "stt", "source")
DIALECT_MARKERS = set(lfold(w) for w in (
    # words of Levantine, Egyptian, Gulf/Iraqi and Maghrebi Arabic with no MSA
    # use. An MSA homograph after lookup folding is left out: هما, دول, بدو,
    # شي, هاي, أوي (أوى), إيه (آية), بكرة, (ماشٍ), (دية), كمان, هادي,
    # ياسر, هون
    "شو ايش إيش شلون هيك كتير منيح منيحة بدي بدك بدها بدنا مش مو ليش وين هلق هلأ كده كدة دلوقتي إزاي ازاي "
    "عايز عاوز عايزة فين امتى إمتى بتاع بتاعي لسه كويس كويسة علشان عشان مافي ماكو شنو يلا برشا بزاف "
    "واش كيفاش دابا راني هادا هاذا نحنا إحنا احنا انتو إنتو بتعرف بعرف بحب مشان هيدا هيدي هاد "
    "اللي إللي معلش مفيش ماعندي ماعنديش مابعرف بشوف بيعرف رح هونيك مبارح بكرا دي ده هذول "
    "هاذي ويش وش شكون فماش بالزاف تبغى ابغى أبغى يبغى وايد جدام").split())


# ---- closed sets (lemma keys: fold() spelling, hamza kept) ------------------------------
DAYS = [("الأحد", "sunday", "Sunday"), ("الاثنين", "monday", "Monday"), ("الثلاثاء", "tuesday", "Tuesday"),
        ("الأربعاء", "wednesday", "Wednesday"), ("الخميس", "thursday", "Thursday"), ("الجمعة", "friday", "Friday"),
        ("السبت", "saturday", "Saturday")]
DAY_BY_SURFACE = {lfold(d): (d, en) for d, en, _ in DAYS}
DAY_BY_SURFACE.update({lfold("الإثنين"): ("الاثنين", "monday")})
# Gregorian month names used in MSA media (Egypt / Gulf / Maghreb press); the
# Levantine Syriac set (كانون الثاني, شباط ...) is a TODO
MONTHS = [("يناير", "January"), ("فبراير", "February"), ("مارس", "March"), ("أبريل", "April"), ("مايو", "May"),
          ("يونيو", "June"), ("يوليو", "July"), ("أغسطس", "August"), ("سبتمبر", "September"),
          ("أكتوبر", "October"), ("نوفمبر", "November"), ("ديسمبر", "December")]
MONTHS_SET = {m for m, _ in MONTHS}
SEASONS = [("ربيع", "spring"), ("صيف", "summer"), ("خريف", "autumn, fall"), ("شتاء", "winter")]
NUMBERS = [("صفر", "zero"), ("واحد", "one"), ("اثنان", "two"), ("ثلاثة", "three"), ("أربعة", "four"),
           ("خمسة", "five"), ("ستة", "six"), ("سبعة", "seven"), ("ثمانية", "eight"), ("تسعة", "nine"),
           ("عشرة", "ten"), ("أحد عشر", "eleven"), ("اثنا عشر", "twelve"), ("ثلاثة عشر", "thirteen"),
           ("أربعة عشر", "fourteen"), ("خمسة عشر", "fifteen"), ("ستة عشر", "sixteen"), ("سبعة عشر", "seventeen"),
           ("ثمانية عشر", "eighteen"), ("تسعة عشر", "nineteen"), ("عشرون", "twenty"), ("ثلاثون", "thirty"),
           ("أربعون", "forty"), ("خمسون", "fifty"), ("ستون", "sixty"), ("سبعون", "seventy"), ("ثمانون", "eighty"),
           ("تسعون", "ninety"), ("مئة", "hundred"), ("ألف", "thousand")]
NUMBER_SET = {n for n, _ in NUMBERS}
TEEN_SURF = None    # filled below TEEN_UNITS
# CAMeL lemma / variant -> the pack's numeral lemma (feminine-counted forms,
# oblique -ين, the older مائة spelling)
NUMBER_BASE = {"ثلاث": "ثلاثة", "أربع": "أربعة", "خمس": "خمسة", "ست": "ستة", "سبع": "سبعة", "ثمان": "ثمانية",
               "ثماني": "ثمانية", "تسع": "تسعة", "عشر": "عشرة", "اثنتان": "اثنان", "اثنين": "اثنان",
               "اثنتين": "اثنان", "واحدة": "واحد", "مائة": "مئة", "عشرين": "عشرون", "ثلاثين": "ثلاثون",
               "أربعين": "أربعون", "خمسين": "خمسون", "ستين": "ستون", "سبعين": "سبعون", "ثمانين": "ثمانون",
               "تسعين": "تسعون"}
TEEN_UNITS = {"أحد": "أحد", "إحدى": "أحد", "اثنا": "اثنا", "اثني": "اثنا", "اثنتا": "اثنا", "اثنتي": "اثنا",
              "ثلاثة": "ثلاثة", "ثلاث": "ثلاثة", "أربعة": "أربعة", "أربع": "أربعة", "خمسة": "خمسة", "خمس": "خمسة",
              "ستة": "ستة", "ست": "ستة", "سبعة": "سبعة", "سبع": "سبعة", "ثمانية": "ثمانية", "ثماني": "ثمانية",
              "ثمان": "ثمانية", "تسعة": "تسعة", "تسع": "تسعة"}
TEEN_SURF = {lfold(k): v for k, v in TEEN_UNITS.items()}
COLOURS = [("أبيض", "white"), ("أسود", "black"), ("أحمر", "red"), ("أخضر", "green"), ("أزرق", "blue"),
           ("أصفر", "yellow"), ("برتقالي", "orange (colour)"), ("بني", "brown"), ("رمادي", "grey, gray"),
           ("وردي", "pink"), ("بنفسجي", "purple, violet")]
GREETINGS = [("نعم", "INTJ", "yes"), ("لا", "INTJ", "no"), ("مرحبا", "INTJ", "hello; welcome"),
             ("أهلا", "INTJ", "hello, welcome"), ("شكرا", "INTJ", "thank you, thanks"),
             ("عفوا", "INTJ", "you're welcome; excuse me, sorry"), ("آسف", "ADJ", "sorry"),
             ("من فضلك", "INTJ", "please"), ("مع السلامة", "INTJ", "goodbye"),
             ("السلام عليكم", "INTJ", "hello (peace be upon you)"), ("صباح الخير", "INTJ", "good morning"),
             ("مساء الخير", "INTJ", "good evening")]
PRONOUNS = [("أنا", "I"), ("أنت", "you (m./f. sg.)"), ("هو", "he; it"), ("هي", "she; it"), ("نحن", "we"),
            ("أنتم", "you (pl.)"), ("هم", "they"), ("هذا", "this (هذه: f.)"), ("ذلك", "that (تلك: f.)"),
            ("هؤلاء", "these (people)"), ("أولئك", "those (people)"), ("الذي", "who, which, that (التي: f.)")]
QUESTION = [("ما", "PRON", "what; (neg.) not"), ("ماذا", "PRON", "what"), ("من", "PRON", "who"),
            ("متى", "ADV", "when"), ("أين", "ADV", "where"), ("كيف", "ADV", "how"), ("لماذا", "ADV", "why"),
            ("كم", "PRON", "how many, how much"), ("أي", "DET", "which, any"), ("هل", "PART", "(yes/no question)")]
PREPS = [("في", "in, at"), ("من", "from, of"), ("إلى", "to, towards"), ("على", "on; about"), ("عن", "about; from"),
         ("مع", "with"), ("ب", "with, by, in (bound: بـ)"), ("ل", "for, to; belonging to (bound: لـ)"),
         ("بين", "between, among"), ("تحت", "under"), ("فوق", "above, over"),
         ("أمام", "in front of"), ("خلف", "behind"), ("عند", "at, with; (عندي) I have"), ("حتى", "until; even"),
         ("منذ", "since; ago"), ("بعد", "after"), ("قبل", "before"), ("حول", "around; about")]
CONJS = [("و", "CONJ", "and"), ("أو", "CONJ", "or"), ("لكن", "CONJ", "but"), ("ثم", "CONJ", "then, and then"),
         ("أن", "CONJ", "that; to (+ verb)"), ("إن", "CONJ", "if; indeed"),
         ("لأن", "CONJ", "because"), ("إذا", "CONJ", "if, when"), ("عندما", "CONJ", "when")]
PARTS = [("لا", "PART", "not (+ present tense); there is not"), ("لم", "PART", "did not (+ jussive)"), ("لن", "PART", "will not (+ subjunctive)"),
         ("قد", "PART", "(+ past) already, has; (+ present) may"), ("سوف", "PART", "will (future)"),
         ("يا", "PART", "O, hey (calling someone)"), ("ليس", "VERB", "is not, not to be")]
# lexicalised surfaces the analyser splits into preposition + host
SURFACE_FIX = {"لأن": ("لأن", "SCONJ"), "لان": ("لأن", "SCONJ"), "لأنه": None, "كأن": ("كأن", "SCONJ"),
               "لكي": ("لكي", "SCONJ"), "لذلك": ("لذلك", "ADV"), "لذا": ("لذا", "ADV"), "كذلك": ("كذلك", "ADV"),
               "عندما": ("عندما", "SCONJ"), "بينما": ("بينما", "SCONJ"), "كما": ("كما", "SCONJ"),
               "لماذا": ("لماذا", "ADV"), "لكن": ("لكن", "CCONJ"), "لكنه": None, "ولكن": ("لكن", "CCONJ"),
               "إذا": ("إذا", "SCONJ"), "اذا": ("إذا", "SCONJ"), "حيث": ("حيث", "SCONJ"), "إلا": ("إلا", "PART"),
               "الا": ("إلا", "PART"), "ماذا": ("ماذا", "PRON"), "كيف": ("كيف", "ADV"), "متى": ("متى", "ADV"),
               "أين": ("أين", "ADV"), "اين": ("أين", "ADV"), "كم": ("كم", "PRON"), "هل": ("هل", "PART"),
               "هنا": ("هنا", "ADV"), "هناك": ("هناك", "ADV"), "الآن": ("الآن", "ADV"), "الان": ("الآن", "ADV"),
               "أمس": ("أمس", "ADV"), "امس": ("أمس", "ADV"), "غدا": ("غدا", "ADV"), "جدا": ("جدا", "ADV"),
               "أيضا": ("أيضا", "ADV"), "ايضا": ("أيضا", "ADV"), "فقط": ("فقط", "ADV"), "شكرا": ("شكرا", "INTJ"),
               "عفوا": ("عفوا", "INTJ"), "مرحبا": ("مرحبا", "INTJ"), "أهلا": ("أهلا", "INTJ"),
               "اهلا": ("أهلا", "INTJ"), "نعم": ("نعم", "INTJ"), "هكذا": ("هكذا", "ADV"), "كذالك": ("كذلك", "ADV"),
               "هؤلاء": ("هؤلاء", "PRON"), "طوال": ("طوال", "ADP"), "رغم": ("رغم", "ADP"), "هاؤلاء": ("هؤلاء", "PRON"), "أولئك": ("أولئك", "PRON"),
               "اولئك": ("أولئك", "PRON"), "أولائك": ("أولئك", "PRON"), "اولائك": ("أولئك", "PRON"), "أو": ("أو", "CCONJ"), "او": ("أو", "CCONJ")}
SURFACE_FIX.update({"فطور": ("فطور", "NOUN"), "الفطور": ("فطور", "NOUN")})    # calima: فُطْر mushroom
SURFACE_FIX.update({"أثناء": ("أثناء", "ADP"), "اثناء": ("أثناء", "ADP")})    # calima: plural of ثِنْي "fold"
SURFACE_FIX.update({f"{w}لكن{e}": ("لكن", "CCONJ") for w in ("", "و") for e in ("ك", "كم", "ني", "نني", "نا", "ه", "ها", "هم")})
SURFACE_FIX.update({"ديما": ("دائما", "ADV"), "معي": ("مع", "ADP"), "معى": ("مع", "ADP")})  # ديما: common misspelling; معي: مع + ي, not مِعًى "gut"
# the construct forms of the "five nouns" (أبو مريم "Maryam's father"): CAMeL reads أبو as a name
SURFACE_FIX.update({"أبو": ("أب", "NOUN"), "ابو": ("أب", "NOUN"), "أخو": ("أخ", "NOUN"), "اخو": ("أخ", "NOUN")})
SURFACE_FIX.update({f"{p}مع{e}": ("مع", "ADP") for p in ("", "و", "ف") for e in ("ك", "كم", "كما", "كن", "ه", "ها", "هم", "هما", "هن", "نا")})  # BERT backs off on معك/معهم
SURFACE_FIX.update({k: ("ليس", "VERB") for k in ("أليس", "اليس", "وليس", "أليست", "اليست", "أوليس", "اوليس")})  # interrogative أ + ليس (not أَلِيس "Alice")
SURFACE_FIX.update({k: ("زال", "VERB") for k in ("لازلت", "لازالت", "لازال", "لازلنا", "لازالوا", "ولازلت", "ولازال", "مازلت", "مازالت", "مازال", "مازلنا", "مازالوا", "امازلت", "أمازلت", "ألازلت")})  # لا/ما + زال written joined (not أزال "remove")
SURFACE_FIX.update({"اقسم": ("أقسم", "VERB"), "أقسم": ("أقسم", "VERB"), "اقل": ("أقل", "ADJ")})  # اقل: أقلّ "less", not 1sg of قلّ   # "I swear" (not قسم "divide")
SURFACE_FIX.update({k: ("أمس", "ADV") for k in ("أمس", "الأمس", "بالأمس", "امس", "الامس", "بالامس")})  # BERT: أَمَسّ "more urgent"
for _t, _o in (("عشرون", "عشرين"), ("ثلاثون", "ثلاثين"), ("أربعون", "أربعين"), ("خمسون", "خمسين"),
               ("ستون", "ستين"), ("سبعون", "سبعين"), ("ثمانون", "ثمانين"), ("تسعون", "تسعين")):
    # tens: CAMeL's lemma is the unit (أربعون -> أربع)
    SURFACE_FIX[_t] = SURFACE_FIX[_o] = SURFACE_FIX[lfold(_t)] = SURFACE_FIX[lfold(_o)] = (_t, "NUM")
# homograph surfaces no pack word shares: وحده/لوحده "alone" (not حدّ "limit" or وحدة "unit"),
# خالية "empty" (not خال "maternal uncle"), ألّا = أن + لا (not إلا "except")
SURFACE_FIX.update({f"{p}وحد{e}": ("وحد", "ADV") for p in ("", "و", "ل", "ول", "ف", "ب")
                    for e in ("ه", "ها", "هم", "هما", "هن", "ي", "ك", "كم", "كما", "نا")})
SURFACE_FIX.update({k: ("خال", "ADJ") for k in ("خالية", "خاليه", "الخالية", "الخاليه", "خاليا", "خاليين", "خالون")})
SURFACE_FIX.update({k: ("ألا", "PART") for k in ("ألا", "وألا", "فألا")})
SURFACE_FIX = {k: v for k, v in SURFACE_FIX.items() if v}
LEMMA_FIX = {"توفى": "توفي", "أليس": "ليس", "مشعر": "شعور", "أعال": "تعالى", "حبيبة": "حبيب", "أولى": "أول", "هذه": "هذا", "هٰذه": "هذا", "تلك": "ذلك", "التي": "الذي", "الذين": "الذي", "اللذان": "الذي",
             "اللتان": "الذي", "اللواتي": "الذي", "اللاتي": "الذي", "أنتِ": "أنت", "أنتما": "أنتم", "أنتن": "أنتم",
             "هما": "هم", "هن": "هم", "إياه": "هو", "مائة": "مئة",
             # calima-msa-r13 lexemes that are no headword (its lex for رأى is راوند)
             "راوند": "رأى", "لاس": "ليس", "لسن": "ليس", "أرنى": "أرى", "رنى": "أرى", "لدة": "لدى",
             "كلوة": "كلا", "كوان": "كوب", "جاه": "فجأة", "سنى": "سن", "آلم": "ألم", "كامرا": "كاميرا",
             "رأم": "يرام", "حسب_": "فحسب", "جزل": "جزيل"}
LEMMA_POS = {"فجأة": "ADV", "هيا": "INTJ", "ليس": "VERB", "لدى": "ADP", "كلا": "DET"}
FORM_OF_RE = re.compile(r"^(?:plural|alternative form|alternative spelling|misspelling|nonstandard spelling|"
                        r"obsolete spelling|feminine singular|feminine|elative degree) of (\S+)")
PLURAL_OF_RE = re.compile(r"(?:^|# |; )(?:masculine |feminine )?plural of (\S+)")
ELATIVE_FEM_RE = re.compile(r"^feminine singular of (أ\S+)")
ANNA_RE = re.compile(r"^(?:[وفبلك]?ان(?:ك|كم|كما|كن|ه|ها|هم|هما|هن|ني|نا|ي)|[وف]?ان)$")
DEFINITE_OF_RE = re.compile(r"(?:nominative|genitive|accusative) definite of (\S+)")
# a participle line that carries its own meaning ("passive participle of أَغْلَقَ (ʔaḡlaqa): closed")
PART_RE = re.compile(r"^(?:active|passive) participle of \S+(?: \([^)]*\))?:\s*(\S.*)$")
DEFINITE_OK = {d for d, _, _ in DAYS} | {"الله", "الذي"}
EXTRA_INTJ = [("هيا", "come on!, let's go!"), ("عذرا", "sorry, excuse me"), ("وداعا", "goodbye, farewell")]
ORDINALS = [("ثاني", "second"), ("ثالث", "third"), ("رابع", "fourth"), ("خامس", "fifth"), ("سادس", "sixth"),
            ("سابع", "seventh"), ("ثامن", "eighth"), ("تاسع", "ninth"), ("عاشر", "tenth"), ("أخير", "last, final")]
ORDINAL_SET = {o for o, _ in ORDINALS}
COLOUR_SET = {c for c, _ in COLOURS}
# SURFACE_FIX words kaikki has no usable entry for
SURFACE_GLOSS = {"لذا": ("ADV", "so, therefore"), "لذلك": ("ADV", "so, therefore, that is why"),
                 "كذلك": ("ADV", "also, likewise"), "لأن": ("SCONJ", "because"), "لكي": ("SCONJ", "so that, in order to"),
                 "كأن": ("SCONJ", "as if, as though"), "عندما": ("SCONJ", "when"), "بينما": ("SCONJ", "while, whereas"),
                 "كما": ("SCONJ", "as, just as; also"), "هكذا": ("ADV", "like this, thus, so"),
                 "طوال": ("ADP", "throughout, all through"), "رغم": ("ADP", "despite, in spite of"),
                 # adverbial accusatives kaikki has only as their noun/adjective
                 # (غالبا is no غالب "victor")
                 "غالبا": ("ADV", "often, usually"), "إطلاقا": ("ADV", "(not) at all; never"),
                 "لاحقا": ("ADV", "later"), "مسبقا": ("ADV", "in advance, beforehand"),
                 "كلما": ("SCONJ", "whenever; the more … the more"),
                 "لما": ("SCONJ", "when (+ past); (لِمَ) why"),
                 "بأكمله": ("ADV", "entire, in its entirety (بأكملها: f.)"),
                 # lexicalised ـما conjunctions: CAMeL splits them (مثلما -> مثل) or reads a name
                 "مثلما": ("SCONJ", "just as, as"), "حينما": ("SCONJ", "when, while"),
                 "طالما": ("SCONJ", "as long as; (+ past) often"), "أينما": ("SCONJ", "wherever"),
                 "كيفما": ("SCONJ", "however, in whatever way"), "حيثما": ("SCONJ", "wherever"),
                 "ريثما": ("SCONJ", "until, while waiting for"), "إنما": ("PART", "only; but rather"),
                 # فَحَسْب "only": CAMeL's حَسْب (kaikki: "measure, extent"); a form-of reading made it حاسب
                 "فحسب": ("ADV", "only, merely"),
                 # lexicalised adverbials CAMeL splits or reads as nouns (حوالي: حِوال
                 # "circle"; مقدما: مُقَدَّم "chief"; بأسره: أَسْر "captivity")
                 "حوالي": ("ADV", "about, approximately"), "مقدما": ("ADV", "in advance, beforehand"),
                 "بأسره": ("ADV", "entire, as a whole (بأسرها: f.)")}
MA_CONJ = ("مثلما", "حينما", "طالما", "أينما", "كيفما", "حيثما", "ريثما", "إنما", "فحسب")
SURFACE_FIX.update({f(k): ("بأكمله", "ADV") for k in ("بأكمله", "بأكملها", "بأكملهم", "بأكملهما") for f in (fold, lfold)})
SURFACE_FIX.update({f(k): ("بأسره", "ADV") for k in ("بأسره", "بأسرها", "بأسرهم", "بأسرهما") for f in (fold, lfold)})
SURFACE_FIX.update({f(k): (v, g) for k, v, g in (("حوالي", "حوالي", "ADV"), ("حوالى", "حوالي", "ADV"),
                                                 ("مقدما", "مقدما", "ADV"), ("مقدماً", "مقدما", "ADV"))
                    for f in (fold, lfold)})
# ألف "thousand": CAMeL reads unhamzated الف as إِلْف "familiar" (kaikki آلف "elf")
SURFACE_FIX.update({f(k): ("ألف", "NUM") for k in ("ألف", "ألفا", "ألفين", "ألفان", "آلاف", "بألف", "بآلاف")
                    for f in (fold, lfold)})
# يتم "is done" (تَمَّ), not يَتِمَ "to be orphaned"
SURFACE_FIX.update({f(k): ("تم", "VERB") for k in ("يتم", "تتم", "ستتم", "سيتم") for f in (fold, lfold)})
SURFACE_FIX.update({f(k): (k, g) for k in ("غالبا", "إطلاقا", "لاحقا", "مسبقا", "كلما", "لما") + MA_CONJ
                    for g in [SURFACE_GLOSS[k][0]] for f in (fold, lfold)})
# nouns in construct the grammar calls ظرف: taught as prepositions
SEMI_PREP = {"عند", "لدى", "بعد", "قبل", "بين", "مع", "حول", "دون", "بدون", "تحت", "فوق", "أمام", "خلف", "وراء",
             "ضد", "عبر", "نحو", "خلال", "منذ", "حتى", "لدن", "قرب", "مثل", "رغم", "طوال", "عقب", "إثر", "ضمن", "خارج", "داخل"}
QUANT = {"كل", "بعض", "جميع", "أي", "كلا", "كلتا"}
# Arabic-only policy (on the English, every shipped sentence has one): Tatoeba
# "ara" carries side-taking political and religious sentences (Israel/Palestine,
# Kabylie nationalism, religious claims and proselytising, terror). They ship at
# no level; a Kabylie sentence only with a political cue (residence and travel stay).
POLITICAL_EN = (r"(?<![A-Za-z])(?:Israel\w*|Palestin\w*|Zionis\w*|Gaza|Hamas|Hezbollah|intifada|Jerusalem|Western Sahara|Polisario|"
                r"separatis\w*|Islam\w*|Quran\w*|Koran\w*|Prophet|Muhammad|Bible|Jesus|Christianity|Judaism|"
                r"religions?|worship\w*|convert(?:ed|s|ing)? to|atheis\w*|infidels?|jihad\w*|terroris\w*|Allah)"
                r"(?![A-Za-z])|^(?=[\s\S]*\bKabyl)(?=[\s\S]*\b(?:Algeri|part of|borders?\b|independen|nation|"
                r"country|flag|colon|autonom))")
# side-taking claims about a religious or ethnic group ("Muslims don't eat pork because it's dangerous")
GROUP_CLAIM_EN = (r"^(?=[\s\S]*\b(?:Muslims?|Christians?|Jews?|Jewish|Arabs?|Berbers?|Kabyles?)\b)"
                  r"(?=[\s\S]*\b(?:dangerous|evil|bad|dirty|infidels?|superior|inferior|haram|forbidden)\b)")
WASL_HAMZA_RE = re.compile(f"(?<![{LET}])([وفبلك]?)إ(?=(?:بن|سم|ثن|مرأ)[{LET}]{{0,3}}(?![{LET}]))")
# misspellings the analyser still reads (wrong harakat حَيْنَ "when"; أصدقاءها as a subject;
# بنسبتي لي "for me"): dropped with the typo class
MISSPELT_RE = re.compile("حَيْنَ|أصدقاءها يحب|بنسبتي لي")
PERSIAN_CHARS_RE = re.compile("[پچژگ\u200c]")
PERSIAN_WORDS = {lfold(w) for w in ("نبايد", "بايد", "هستند", "است", "نيست", "كند", "ميكند", "خيلي", "هست", "چه", "ميخواهم")}
FEMALE_RE = re.compile(r"\bfemale\b|\bwoman\b|daughter|\w{3,}ess\b", re.I)
# folded host + proclitic spellings that are one word (بعضكم is no بـ + عضّ)
CLITIC_CLOSED = {lfold(w): (w, g) for g, ws in (("DET", ("بعض",)), ("ADP", ("بين", "بعد", "بدون", "لدى", "لدن", "قبل")))
                 for w in ws}
# Tatoeba personal names the analyser reads as common words (Mennad, Skura, Rima)
NAMES = {"مصر", "مسيح", "صين", "بن", "مناد", "منادي", "سكوره", "سكورة", "ريمة", "ريمه", "يانني", "ياني", "زيري", "سامي", "ليلى", "توم",
         "ماري", "فاضل", "دانيا", "دانية", "دانيه", "باية", "بايه", "رامي", "مريم", "نورة", "نوره", "ميمون", "مزيان"}
POS_KAIKKI = {"NOUN": ("noun",), "ADJ": ("adj",), "VERB": ("verb",), "ADV": ("adv",)}

# ---- compounds --------------------------------------------------------------------
# "phrase|gloss|GROUP". A verb compound is "verb prep" (free preposition) or
# "verb بـ/لـ/كـ" (bound: the next token's proclitic, or ب/ل with a pronoun),
# or "verb noun" (light verb + object noun), the second part within 4 tokens
# of the verb. Anything else is a fixed phrase matched on contiguous folded
# surfaces (a first word may carry و/ف, a last word a pronoun suffix, a last
# لـ its preposition proclitic).
COMPOUNDS_SRC = """
قام بـ|to carry out, to do, to undertake|VERB
أخذ في|to begin to, to start|VERB
بحث عن|to look for, to search for|VERB
حصل على|to get, to obtain|VERB
لا بد|must, it is inevitable|ADV
كرة القدم|football, soccer|NOUN
على قيد الحياة|alive, still living|ADV
على وشك|about to, on the verge of|ADV
عثر على|to find, to come across|VERB
اعتمد على|to depend on, to rely on|VERB
وافق على|to agree to|VERB
حافظ على|to preserve, to keep|VERB
رد على|to reply to, to answer|VERB
تعرف على|to get to know, to recognise|VERB
قضى على|to put an end to, to eliminate|VERB
ركز على|to focus on|VERB
أصر على|to insist on|VERB
اعتاد على|to get used to|VERB
تغلب على|to overcome|VERB
سيطر على|to control, to take over|VERB
ضحك على|to laugh at; to fool|VERB
أشار إلى|to point to, to refer to|VERB
احتاج إلى|to need|VERB
استمع إلى|to listen to|VERB
نظر إلى|to look at|VERB
انتقل إلى|to move to|VERB
انضم إلى|to join|VERB
تحدث عن|to talk about, to speak about|VERB
عبر عن|to express|VERB
سأل عن|to ask about|VERB
دافع عن|to defend|VERB
توقف عن|to stop (doing)|VERB
ابتعد عن|to move away from, to avoid|VERB
تخلى عن|to give up, to abandon|VERB
اعتذر عن|to apologise for|VERB
رغب في|to wish, to desire|VERB
فكر في|to think about|VERB
شارك في|to take part in|VERB
ساهم في|to contribute to|VERB
نجح في|to succeed in|VERB
فشل في|to fail (in)|VERB
استمر في|to continue (doing)|VERB
بدأ في|to begin (doing)|VERB
اهتم بـ|to care about, to be interested in|VERB
شعر بـ|to feel|VERB
اتصل بـ|to call, to contact|VERB
سمح بـ|to allow, to permit|VERB
سمح لـ|to allow (someone)|VERB
أمر بـ|to order|VERB
آمن بـ|to believe in|VERB
اعترف بـ|to admit, to confess|VERB
احتفل بـ|to celebrate|VERB
استمتع بـ|to enjoy|VERB
التقى بـ|to meet|VERB
رحب بـ|to welcome|VERB
وعد بـ|to promise|VERB
تمكن من|to be able to, to manage to|VERB
خاف من|to be afraid of|VERB
استفاد من|to benefit from|VERB
تخلص من|to get rid of|VERB
تأكد من|to make sure of|VERB
انتهى من|to finish (doing)|VERB
اقترب من|to approach, to get close to|VERB
اتخذ قرار|to make a decision|VERB
لعب دور|to play a role|VERB
ألقى نظرة|to take a look|VERB
طرح سؤال|to ask a question|VERB
بذل جهد|to make an effort|VERB
على الرغم من|despite, in spite of|ADP
بالرغم من|despite, in spite of|ADP
من أجل|for the sake of; in order to|ADP
بالنسبة لـ|as for, regarding|ADP
بالنسبة إلى|as for, regarding|ADP
بدلا من|instead of|ADP
من خلال|through, by means of|ADP
عن طريق|by way of, through|ADP
إلى جانب|beside, alongside; in addition to|ADP
بالإضافة إلى|in addition to|ADP
بسبب|because of|ADP
في أثناء|during|ADP
في الواقع|in fact, actually|ADV
في الحقيقة|in fact, actually|ADV
على الأقل|at least|ADV
في النهاية|in the end, finally|ADV
على سبيل المثال|for example|ADV
من جديد|again, anew|ADV
على الإطلاق|(not) at all|ADV
في البداية|at first, in the beginning|ADV
في الوقت نفسه|at the same time|ADV
من الآن فصاعدا|from now on|ADV
بعد أن|after (+ verb)|CONJ
قبل أن|before (+ verb)|CONJ
في حين|while, whereas|CONJ
حتى لو|even if|CONJ
كما لو|as if|CONJ
على الفور|immediately, at once|ADV
إلى الأبد|forever|ADV
بالطبع|of course|ADV
بالتأكيد|certainly, definitely|ADV
بالضبط|exactly|ADV
بالفعل|indeed, really; already|ADV
بالتالي|consequently, therefore|ADV
بشأن|about, concerning|ADP
للغاية|extremely, very|ADV
بسرعة|quickly, fast|ADV
ببطء|slowly|ADV
بدون|without|ADP
بخير|well, fine (in health)|ADJ
كالعادة|as usual|ADV
أحيانا|sometimes|ADV
بعض|some; (بعضهم بعضا) each other|DET
على ما يرام|fine, all right|ADJ
لا بأس|never mind, it's all right|INTJ
إن شاء الله|God willing, hopefully|INTJ
الحمد لله|thank God|INTJ
من فضلك|please|INTJ
مع السلامة|goodbye|INTJ
السلام عليكم|hello (peace be upon you)|INTJ
صباح الخير|good morning|INTJ
مساء الخير|good evening|INTJ
شكرا جزيلا|thank you very much|INTJ
"""
PREP_FREE = {"في", "على", "عن", "إلى", "من", "مع"}
# verb + preposition compounds (اتصل بـ, نظر إلى, عثر على) are not cards of
# their own: the verb's card is the one card, its gloss naming the preposition
# (finalize_words). A card beside the bare verb was a twin with the same
# sentences. Light-verb + noun phrases (اتخذ قرار) stay compounds.
MERGED_KINDS = ("bound", "free")
COMPOUNDS = {}          # key (bound ـ dropped) -> (gloss, group)
COMPOUND_DISPLAY = {}   # key -> displayed w (bound prepositions with tatweel)
VERB_COMP_INDEX = {}    # verb lemma -> [(key, "bound"|"free"|"noun", part)]
PHRASE_INDEX = {}       # lfold(first surface) -> [(key, group, parts)] longest first
for _line in COMPOUNDS_SRC.strip().splitlines():
    _phrase, _gloss, _grp = _line.split("|")
    _parts = _phrase.split()
    _key = " ".join(p.rstrip("ـ") for p in _parts)
    COMPOUNDS[_key] = (_gloss, _grp)
    COMPOUND_DISPLAY[_key] = _phrase
    if _grp == "VERB":
        _v, _p = _parts
        _kind = "bound" if _p.endswith("ـ") else "free" if _p in PREP_FREE else "noun"
        VERB_COMP_INDEX.setdefault(_v, []).append((_key, _kind, _p.rstrip("ـ")))
    elif len(_parts) > 1:
        PHRASE_INDEX.setdefault(lfold(_parts[0]), []).append((_key, _grp, _parts))
for _v in PHRASE_INDEX.values():
    _v.sort(key=lambda x: -len(x[2]))
# single-token compounds (بسبب, بالطبع): the surface itself, whatever the analyser's host
SURFACE_FIX.update({lfold(k): (k, g if g != "CONJ" else "SCONJ") for k, (gl, g) in COMPOUNDS.items() if " " not in k})
for _n, _ in NUMBERS:
    if " " in _n:
        COMPOUND_DISPLAY[_n] = _n
FIXED_KEYS_BY_LEMMA = {}
FIXED_GROUPS = {}       # fixed lemma -> its fixed groups
FUNC_UPOS = {"PART", "SCONJ", "CCONJ", "ADP", "PRON", "DET"}


def _group(upos):
    return "CONJ" if upos in ("SCONJ", "CCONJ") else upos


FIXED_PRON = {"الأحد": "al-ʾaḥad", "الاثنين": "al-iṯnayn", "الثلاثاء": "aṯ-ṯulāṯāʾ", "الأربعاء": "al-ʾarbiʿāʾ",
              "الخميس": "al-ḫamīs", "الجمعة": "al-jumʿa", "السبت": "as-sabt", "الآن": "al-ʾān", "اليوم": "al-yawm",
              "الذي": "allaḏī", "هؤلاء": "hāʾulāʾi", "أولئك": "ulāʾika", "سوى": "siwā", "ب": "bi-", "ل": "li-", "ك": "ka-", "ف": "fa-", "و": "wa-",
              "أحد عشر": "ʾaḥada ʿašara", "اثنا عشر": "iṯnā ʿašara", "ثلاثة عشر": "ṯalāṯata ʿašara",
              "أربعة عشر": "ʾarbaʿata ʿašara", "خمسة عشر": "ḫamsata ʿašara", "ستة عشر": "sittata ʿašara",
              "سبعة عشر": "sabʿata ʿašara", "ثمانية عشر": "ṯamāniyata ʿašara", "تسعة عشر": "tisʿata ʿašara"}

# ---- script primer (docs/SCRIPT_PRIMER.md ss3) -------------------------------------
# 28 letters + the hamza forms ء أ إ آ ؤ ئ + ة ى as units, 7 sets: the dot
# family ب ت ث ن ي with alef first, so set 1 already reads بيت, بنت, ابن.
# Names and romanisation after the Wiktionary "Arabic alphabet" appendix, in
# the pack's DIN 31635 style (ṯ ḥ ḫ ḏ š ṣ ḍ ṭ ẓ ʿ ġ ʾ).
# (set, group, slug, glyph, name, roman, alt, confuse slugs, joins, note)
AR_SCRIPT = [
    (1, "alif", "alif", "ا", "ʾalif", "ā", ["a", "aa"], ["alif-hamza", "lam"], "right", "ā as in 'father'; also carries a word-initial vowel"),
    (1, "ba", "ba", "ب", "bāʾ", "b", [], ["ta", "tha", "nun", "ya"], "dual", "b"),
    (1, "ba", "ta", "ت", "tāʾ", "t", [], ["ba", "tha", "nun"], "dual", "t"),
    (1, "ba", "tha", "ث", "ṯāʾ", "ṯ", ["th"], ["ta", "ba"], "dual", "th as in 'think'"),
    (1, "ba", "nun", "ن", "nūn", "n", [], ["ba", "ta", "ya"], "dual", "n"),
    (1, "ba", "ya", "ي", "yāʾ", "y", ["i", "ii"], ["ba", "nun", "alif-maqsura", "ya-hamza"], "dual", "y; also the long vowel ī"),
    (2, "dal", "dal", "د", "dāl", "d", [], ["dhal", "ra"], "right", "d"),
    (2, "dal", "dhal", "ذ", "ḏāl", "ḏ", ["dh"], ["dal", "zay"], "right", "th as in 'this'"),
    (2, "ra", "ra", "ر", "rāʾ", "r", [], ["zay", "dal"], "right", "a rolled r"),
    (2, "ra", "zay", "ز", "zāy", "z", [], ["ra", "dhal"], "right", "z"),
    (2, "waw", "waw", "و", "wāw", "w", ["u", "uu"], ["waw-hamza", "ra"], "right", "w; also the long vowel ū"),
    (3, "lam", "lam", "ل", "lām", "l", [], ["alif", "kaf"], "dual", "l"),
    (3, "mim", "mim", "م", "mīm", "m", [], ["ha"], "dual", "m"),
    (3, "kaf", "kaf", "ك", "kāf", "k", [], ["lam"], "dual", "k"),
    (4, "jim", "jim", "ج", "jīm", "j", ["g"], ["hha", "kha"], "dual", "j as in 'jam'"),
    (4, "jim", "hha", "ح", "ḥāʾ", "ḥ", [], ["jim", "kha", "ha"], "dual", "a breathy h from deep in the throat"),
    (4, "jim", "kha", "خ", "ḫāʾ", "ḫ", ["kh"], ["jim", "hha"], "dual", "ch as in Scottish 'loch'"),
    (4, "ha", "ha", "ه", "hāʾ", "h", [], ["ta-marbuta", "hha", "mim"], "dual", "h"),
    (4, "ha", "ta-marbuta", "ة", "tāʾ marbūṭa", "a", ["at"], ["ha", "ta"], "right", "-a at the end of a (mostly feminine) word; -at before another word"),
    (5, "sin", "sin", "س", "sīn", "s", [], ["shin", "sad"], "dual", "s"),
    (5, "sin", "shin", "ش", "šīn", "š", ["sh"], ["sin", "sad"], "dual", "sh"),
    (5, "sad", "sad", "ص", "ṣād", "ṣ", [], ["dad", "sin"], "dual", "an emphatic s (tongue low, back of the mouth)"),
    (5, "sad", "dad", "ض", "ḍād", "ḍ", [], ["sad", "dal"], "dual", "an emphatic d"),
    (6, "ta2", "tta", "ط", "ṭāʾ", "ṭ", [], ["zza", "ta"], "dual", "an emphatic t"),
    (6, "ta2", "zza", "ظ", "ẓāʾ", "ẓ", [], ["tta", "dhal", "zay"], "dual", "an emphatic th as in 'this'"),
    (6, "ayn", "ayn", "ع", "ʿayn", "ʿ", ["3"], ["ghayn", "hha"], "dual", "a squeezed sound from the throat"),
    (6, "ayn", "ghayn", "غ", "ġayn", "ġ", ["gh"], ["ayn", "fa"], "dual", "a throaty g, like French r"),
    (6, "fa", "fa", "ف", "fāʾ", "f", [], ["qaf", "ghayn"], "dual", "f"),
    (6, "fa", "qaf", "ق", "qāf", "q", [], ["fa"], "dual", "a k from the back of the throat"),
    (7, "hamza", "hamza", "ء", "hamza", "ʾ", ["'"], ["alif-hamza", "waw-hamza", "ya-hamza"], None, "a glottal stop, the catch in 'uh-oh'"),
    (7, "alif", "alif-hamza", "أ", "ʾalif hamza", "ʾa", ["a", "u"], ["alif", "alif-hamza-below", "alif-madda"], "right", "a glottal stop + a or u"),
    (7, "alif", "alif-hamza-below", "إ", "ʾalif hamza taḥta", "ʾi", ["i"], ["alif", "alif-hamza"], "right", "a glottal stop + i"),
    (7, "alif", "alif-madda", "آ", "ʾalif madda", "ʾā", ["aa"], ["alif", "alif-hamza"], "right", "a glottal stop + long ā"),
    (7, "waw", "waw-hamza", "ؤ", "wāw hamza", "ʾ", [], ["waw", "hamza", "ya-hamza"], "right", "a glottal stop, written on wāw"),
    (7, "ya", "ya-hamza", "ئ", "yāʾ hamza", "ʾ", [], ["ya", "hamza", "waw-hamza"], "dual", "a glottal stop, written on a dotless yāʾ"),
    (7, "ya", "alif-maqsura", "ى", "ʾalif maqṣūra", "ā", ["a"], ["ya", "alif"], "right", "ā at the end of a word, written like a dotless yāʾ"),
]
AR_SCRIPT_NOTES = [
    {"st": "abjad", "set": 1, "h": "Right to left, short vowels unwritten",
     "body": "Arabic is read from right to left. Only long vowels are letters: ā (ا), ū (و), ī (ي). "
             "The short vowels a, i, u are small marks that everyday text leaves out, so بنت is bint."},
    {"st": "abjad", "set": 2, "h": "Joining",
     "body": "Most letters join on both sides and change shape. Six never join the letter after them: "
             "ا د ذ ر ز و."},
    {"st": "abjad", "set": 3, "h": "The article al-",
     "body": "ال is 'the', written on the word: كتاب kitāb 'a book', الكتاب al-kitāb 'the book'. The pack's "
             "words are shown without it."},
    {"st": "abjad", "set": 3, "h": "lām + alif",
     "body": "lām followed by alif is always written as one joined shape, لا (lā), not ل + ا. On its own "
             "لا is the word 'no, not'; inside a word too: سلام salām 'peace', الآن al-ān 'now'."},
    {"st": "abjad", "set": 4, "h": "tāʾ marbūṭa",
     "body": "ة ends many feminine words (مدرسة madrasa). It is read -a, and -at when another word follows."},
    {"st": "abjad", "set": 7, "h": "Hamza",
     "body": "The glottal stop hamza sits alone (ء) or on a seat: أ إ آ ؤ ئ. Everyday writing often drops it "
             "from alif, so انا and أنا are the same word."},
]
AR_LETTERS = {g: slug for _, _, slug, g, *_ in AR_SCRIPT}
AR_IGNORE = set("ًٌٍَُِّْٰـ")


class Arabic(LanguageSpec):
    code = "ar"
    name_en = "Arabic"
    pack_name = "Arabic (A1–B1)"
    tts = "ar-SA"
    stt = "ar-SA"
    tatoeba_code = "ara"
    spacy_model = None             # CAMeL Tools: tagger_desc / tag_texts (custom tagger, as ja)
    tagger_attribution = {
        "source": "CAMeL Tools 1.6 (NYU Abu Dhabi CAMeL Lab): BERT unfactored MSA disambiguator over the "
                  "CALIMA MSA morphology database (r13); dialect ID DIDModel6",
        "licence": "MIT (CAMeL Tools code, BERT and dialect-ID models); GPL-2.0 (morphology-db-msa-r13 data)",
        "note": "Used at build time only; the pack ships no model or database files.",
    }
    untranslated_rows = True       # every ara sentence is lemma/frequency evidence; only linked ones ship

    subtitles_file = "ar_full.txt"
    kaikki_file = "kaikki_ar.jsonl.gz"
    sentences_file = "ara_sentences_detailed.tsv.bz2"
    links_file = "ara-eng_links.tsv.bz2"
    kelly_file = "kelly_ar.json"
    sources = {
        "ar_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/ar/ar_full.txt",
        "kaikki_ar.jsonl.gz": "https://kaikki.org/dictionary/Arabic/kaikki.org-dictionary-Arabic.jsonl.gz",
        "ara_sentences_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/ara/ara_sentences_detailed.tsv.bz2",
        "ara-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/ara/ara-eng_links.tsv.bz2",
        "kelly_ar.json": "https://raw.githubusercontent.com/kotoshu/frequency-list-kelly/main/data/ar.json",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t45", "lex": "l1"}
    fix_links_floor = 2     # a homograph-link drop never leaves a word under 2 sentences

    # typed production on: lenient accents fold harakat/tatweel/ZWNJ/ZWJ on
    # both sides (PACK_SCHEMA typing.accents), so an unvocalized typed answer
    # still matches a vocalized pack word. strictFromLevel null: harakat are
    # never written in ordinary Arabic text at any level, so strict is never
    # appropriate. Note: the search-only Arabic folds (hamza/madda carrier
    # drop, ة/ه/ۃ/ۀ->ہ, ى<->ی/ي, optional leading ال) do NOT apply to typed
    # answers (PACK_SCHEMA: "typed-answer checking ... is unaffected by any
    # of the folds below"), so those spelling variants remain unfolded here.
    typing = {"caseSensitive": False, "accents": "lenient", "strictFromLevel": None}
    show_pron = True
    target_len = {"A1": 5, "A2": 6, "B1": 7}
    min_len = {"A1": 3, "A2": 4, "B1": 5}
    max_len = 14

    word_re = re.compile(f"[{LET}{MARKS}]+")
    lex_word_re = re.compile(f"^[{LET}]+(?: [{LET}]+){{0,3}}$")
    sub_token_re = re.compile(f"^[{MARKS}]*[{LET}][{LET}{MARKS}]*$")
    form_target_re = re.compile(f"\\bof ([{LET}{MARKS}]+)")
    fem_of_re = re.compile(r"(?!)")
    morph_keep = ("Dialect", "Voc", "Number", "Person", "Gender", "Aspect", "Mood", "Voice", "Prc3", "Prc2", "Prc1", "Prc0",
                  "Enc0", "State", "Src", "Raw")
    caps_mark_names = False            # no letter case
    caps_proper_pool = False
    numeral_verb_rule = False
    use_simplemma = False              # fallback_lemma runs the CAMeL MLE analyser on the surface

    report_title = "Arabic (MSA) A1-B1 pack (corpus-tagged)"
    forced_description = ("weekdays, Gregorian months, seasons, numbers 0-20 + tens + مئة/ألف, colours, greetings, "
                          "pronouns and demonstratives, question words, core prepositions/conjunctions/particles, "
                          "A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000"
    group_kpos = dict(DEFAULT_GROUP_KPOS, **{
        "NOUN": ["noun", "num"],
        "ADJ": ["adj", "noun", "num"],
        "ADV": ["adv", "noun", "prep", "conj", "particle"],
        "DET": ["noun", "det", "pron", "adj"],
        "ADP": ["prep", "adv", "conj", "noun"],
        "PRON": ["pron", "det", "adv"],
        "CONJ": ["conj", "particle", "adv", "prep"],
        "NUM": ["num", "noun", "adj"],
        "INTJ": ["intj", "particle", "adv", "noun"],
        "PART": ["particle", "adv", "conj", "verb"],
    })
    forced_closed = ([(d, "NOUN") for d, _, _ in DAYS] + [(m, "NOUN") for m, _ in MONTHS] +
                     [(s, "NOUN") for s, _ in SEASONS] + [(n, "NUM") for n, _ in NUMBERS] +
                     [(c, "ADJ") for c, _ in COLOURS] + [(g, grp) for g, grp, _ in GREETINGS] +
                     [(p, "PRON") for p, _ in PRONOUNS] + [(q, grp) for q, grp, _ in QUESTION] +
                     [(p, "ADP") for p, _ in PREPS] + [(c, grp) for c, grp, _ in CONJS] +
                     [(p, grp) for p, grp, _ in PARTS] + [("اليوم", "ADV"), ("الآن", "ADV")] +
                     [(k, "INTJ") for k, (_, g) in COMPOUNDS.items() if g == "INTJ"] +
                     [(k, "INTJ") for k, _ in EXTRA_INTJ])
    forced_closed = list(dict.fromkeys(forced_closed))
    allowed_num = NUMBER_SET | {"مليون", "مليار", "نصف", "ربع", "ثلث"}
    no_article = {d for d, _, _ in DAYS} | MONTHS_SET
    fixed_gloss = {
        **{(k, g if g != "CONJ" else "CONJ"): gl for k, (gl, g) in COMPOUNDS.items()},
        **{(d, "NOUN"): en for d, _, en in DAYS},
        **{(k, "INTJ"): en for k, en in EXTRA_INTJ},
        **{(k, "ADJ"): en for k, en in ORDINALS},
        **{(k, "CONJ" if g == "SCONJ" else g): en for k, (g, en) in SURFACE_GLOSS.items()},
        **{(m, "NOUN"): en for m, en in MONTHS},
        **{(s, "NOUN"): en for s, en in SEASONS},
        **{(n, "NUM"): en for n, en in NUMBERS},
        **{(c, "ADJ"): en for c, en in COLOURS},
        **{(g, grp): en for g, grp, en in GREETINGS},
        **{(p, "PRON"): en for p, en in PRONOUNS},
        **{(q, grp): en for q, grp, en in QUESTION},
        **{(p, "ADP"): en for p, en in PREPS},
        **{(c, grp): en for c, grp, en in CONJS},
        **{(p, grp): en for p, grp, en in PARTS},
        ("اليوم", "ADV"): "today", ("الآن", "ADV"): "now",
    }
    function_lemmas = ({p for p, _ in PREPS} | {c for c, _, _ in CONJS} | {p for p, g, _ in PARTS if g == "PART"} |
                       {p for p, _ in PRONOUNS} | {"كل", "بعض", "غير", "ما", "إلا", "لكي", "كأن", "حيث", "بينما",
                                                    "كما", "أي", "هل", "لو", "أم", "إذ", "لدى", "دون", "عدة"})
    min_corpus_tokens = 3
    profanity = {"كس", "زب", "طيز", "شرموطة", "قحبة", "منيوك", "خول", "عاهرة", "لعنة", "ملعون", "حقير", "زبي"}
    bad_text_re = re.compile(f"(?<![{LET}])(?:[وف]?(?:ال)?)(?:كس|زب|طيز|شرموط\\w*|قحب\\w*|منيوك\\w*|خول)(?![{LET}])")
    drop_all_levels = drop_all_re(re.compile(
        f"(?<![{LET}a-z])(?:[وفبل]?(?:ال)?)(?:اغتصاب\\w*|اغتصب\\w*|يغتصب\\w*|انتحار\\w*|انتحر\\w*|ينتحر\\w*|"
        "تحرش\\s*جنسي\\w*|اعتداء\\s*جنسي\\w*|الاعتداء\\s*الجنسي)"
        f"(?![{LET}a-z])|" + POLITICAL_EN + "|" + GROUP_CLAIM_EN + "|" + MISSPELT_RE.pattern, re.I))
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)
    # A1/A2 tier: sexual content, threats/violence, dying, weapons, drugs
    sensitive_re = re.compile(
        f"(?<![{LET}a-z])(?:[وفبلك]?(?:ال)?)(?:[سوف]?[يتنأ]?قتل\\w*|مقتل\\w*|قاتل\\w*|موت\\w*|ميت\\w*|مات|ماتت|ماتوا|"
        "[سوف]?[يتنأ]موت\\w*|جثة|جثث|دم|دماء|سلاح\\w*|أسلحة|مسدس\\w*|بندقية|سكين\\w*|قنبلة|رصاص\\w*|أطلق\\s*النار|"
        "جنس|جنسي|جنسية\\s*مثلية|عاري\\w*|عارية|مخدرات|كوكايين|هيروين|حشيش|إدمان|"
        "die[ds]?|dying|death|weapons?|guns?|pistols?|rifles?|knife|knives|shot|bomb\\w*|corpse|blood|"
        "(?:illicit|illegal) drugs?|drug (?:dealer|addict|abuse|traffick\\w*)s?|narcotics?|cocaine|heroin|"
        "marijuana|cannabis|overdose|abus(?:e|ed|es|ing|er|ers|ive)|"
        + SENSITIVE_EN + f")(?![{LET}a-z])", re.I)

    # ---- spelling ---------------------------------------------------------------
    def fold(self, s):
        return fold(s)

    def subtitle_surface(self, w):
        return lfold(w)

    def extra_wordfreq(self, raw):
        """wordfreq surfaces were fold()ed; the corpus side is lfold()ed:
        re-key (summing) so أنا and انا are one surface."""
        for w in sorted(raw):
            k = lfold(w)
            if k != w:
                c = raw.pop(w)
                raw[k] = raw.get(k, 0) + c

    # ---- tagging (CAMeL Tools) ----------------------------------------------------
    def _camel_env(self):
        if self.repo is not None:
            os.environ.setdefault("CAMELTOOLS_DATA", str(self.repo / ".cache" / "camel_tools"))

    def tagger_desc(self):
        self._camel_env()
        import camel_tools
        return f"CAMeL Tools {camel_tools.__version__}, BERT unfactored msa + calima-msa-r13, DIDModel6"

    def tag_text(self, text):
        return text.replace("ـ", "").strip()

    def _raw_cache(self):
        import camel_tools
        return self.repo / ".cache" / "derived" / f"camel_raw_{camel_tools.__version__}.jsonl.gz"

    def _camel_raw(self, texts):
        """{text: {"t": [[word, *RAW_FIELDS, diac]], "d": [dialect top, P(MSA)]}}, cached."""
        self._camel_env()
        cache = self._raw_cache()
        raw = getattr(self, "_raw_memo", None)
        if raw is None:
            raw = {}
            if cache.exists():
                with gzip.open(cache, "rt", encoding="utf-8") as f:
                    for line in f:
                        t, rec = json.loads(line)
                        raw[t] = rec
            self._raw_memo = raw
        todo = sorted({t for t in texts if t not in raw})
        if not todo:
            return raw
        import logging
        import warnings
        warnings.filterwarnings("ignore")
        logging.getLogger("transformers").setLevel(logging.ERROR)
        from camel_tools.disambig.bert import BERTUnfactoredDisambiguator
        from camel_tools.tokenizers.word import simple_word_tokenize
        bert = BERTUnfactoredDisambiguator.pretrained("msa", batch_size=64, use_gpu=False)
        toks = {t: simple_word_tokenize(t) for t in todo}
        order = sorted(todo, key=lambda t: (len(toks[t]), t))
        # one call per batch: camel_tools 1.6 fails to concatenate batches of
        # different padded lengths (unfactored.py predict), so a call never spans two
        B = 64
        for i in range(0, len(order), B):
            chunk = order[i:i + B]
            sents = [toks[t] for t in chunk]
            nonempty = [s for s in sents if s]
            res = iter(bert.disambiguate_sentences(nonempty)) if nonempty else iter(())
            for t, s in zip(chunk, sents):
                out = []
                if s:
                    for w, d in zip(s, next(res)):
                        a = d.analyses[0].analysis if d.analyses else {}
                        out.append([w] + [a.get(k) for k in RAW_FIELDS] + [a.get("diac")])
                raw[t] = {"t": out, "d": None}
        if not self.passage_tagging:
            from camel_tools.dialectid import DIDModel6
            did = DIDModel6.pretrained()
            preds = did.predict(todo)
            for t, p in zip(todo, preds):
                raw[t]["d"] = [p.top, round(p.scores.get("MSA", 0.0), 4)]
        from ..core.util import derived_write_ok
        if derived_write_ok(self):
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".part")
            with gzip.GzipFile(tmp, "wb", mtime=0) as g:
                for t in sorted(raw):
                    g.write((json.dumps([t, raw[t]], ensure_ascii=False) + "\n").encode("utf-8"))
            tmp.replace(cache)
        return raw

    def clean_sentence_text(self, t):
        """Display normalisation (length-preserving): alif-wasl nouns without
        hamza, and Persian-keyboard letters:
        ک→ك, ہ/ۀ→ه, ی→ي, a word-final ی→ى when the ى spelling is the more
        frequent one in the corpus (علی, إلی; فی, الذی stay ي)."""
        # hamza written on an alif-wasl noun (إبن, إسم, إثنان, إمرأة): plain alif
        t = WASL_HAMZA_RE.sub(lambda m: m.group(1) + "ا", t)
        if not re.search("[یکہۀ]", t):
            return t
        t = t.replace("ک", "ك").replace("ہ", "ه").replace("ۀ", "ه")
        freq = self._word_freq()

        def fin(m):
            w = m.group(0)
            y, a = w[:-1] + "ي", w[:-1] + "ى"
            return a if freq.get(a, 0) > freq.get(y, 0) else y
        t = re.sub(f"[{LET}ی]*ی(?![{LET}ی])", fin, t)
        return t.replace("ی", "ي")

    def _word_freq(self):
        """Raw (unfolded) token counts over the cached corpus."""
        if getattr(self, "_wfreq", None) is None:
            c = Counter()
            d = self.repo / ".cache" / "derived" if self.repo is not None else None
            cands = sorted(d.glob("corpus_*.json.gz")) if d is not None and d.exists() else []
            if cands:
                with gzip.open(cands[-1], "rt", encoding="utf-8") as f:
                    for r in json.load(f)["rows"]:
                        for w in re.findall(f"[{LET}]+", r[1]):
                            c[w] += 1
            self._wfreq = c
        return self._wfreq

    def translation_mismatch(self, toks, en):
        """Not shippable MSA (the sentence still counts as evidence): Persian or
        Amazigh text (پ چ ژ گ, ZWNJ, >=2 Persian function words), or a token
        the analyser only backs off on that is no name or loanword of the
        English (typos: الاشاء, قررر, نهاره, إبن)."""
        words = re.findall(r"[A-Za-z]+", en)
        pers = 0
        for t in toks:
            if len(t) < 4:
                continue
            if PERSIAN_CHARS_RE.search(t[0]):
                return True
            k = lfold(t[0])
            pers += k in PERSIAN_WORDS
            if "Src=backoff" not in t[3] or t[2] in ("PUNCT", "NUM") or not re.search(f"[{LET}]", k):
                continue
            forms = {k, k[1:] if k[:1] in "وبلفك" and len(k) > 3 else k}
            forms |= {f[2:] for f in forms if f.startswith("ال") and len(f) > 4}
            # (a close match: a typo's 3-consonant skeleton meets some English word at 0.67)
            if not any(_translit_ok(f, w, 0.8) for f in forms for w in words) and \
                    not self._dictionary_word_of(t[0], en):
                return True
        return pers >= 2

    def _dictionary_word_of(self, surface, en):
        """A token the analyser does not know but Wiktionary does, spelt as
        Wiktionary spells it (hamza kept) and in the sense the English carries
        (الأمازيغية "Berber" in "learn Berber"): a real word, not a typo (ببطا
        for ببطء does not match بطء). Nisba endings are tried off (أمازيغية ->
        أمازيغ)."""
        info = self._info()
        k = fold(surface)
        forms = {k}
        for p in ("وال", "فال", "بال", "كال", "لل", "ال", "و", "ف", "ب", "ل", "ك"):
            if k.startswith(p) and len(k) - len(p) >= 3:
                forms.add(k[len(p):])
        forms |= {f[2:] for f in forms if f.startswith("ال") and len(f) > 4}
        # a word-initial alif written without its hamza (امازيغية) is ordinary spelling
        forms |= {h + f[1:] for f in forms if f.startswith("ا") for h in "أإآ"}
        forms |= {f[:-len(e)] for f in forms for e in ("ية", "يه", "ي", "يين", "يون")
                  if f.endswith(e) and len(f) - len(e) >= 3}
        words = set(re.findall(r"[a-z]+", en.lower()))
        return any(r[5] and _en_supports(re.sub(r"\([^)]*\)", "", r[6] or ""), words)
                   for f in sorted(forms) for r in info.get(f, []))

    def is_dialect(self, rec):
        """MSA filter on one cached text: a dialect marker word, or dialect ID
        under 5% MSA with a token the MSA analyser only backs off on."""
        words = [lfold(x[0]) for x in rec["t"]]
        if any(w in DIALECT_MARKERS for w in words) or DIALECT_RE.search(" ".join(words)):
            return True
        d = rec.get("d")
        if d and d[0] != "MSA" and d[1] < 0.05:
            return any(x[RAW_FIELDS.index("source") + 1] == "backoff" and CAMEL_UPOS.get(x[2]) != "PUNCT"
                       for x in rec["t"])
        return False

    def tag_texts(self, texts):
        texts = list(texts)
        raw = self._camel_raw(texts)
        for t in texts:
            rec = raw[t]
            if not self.passage_tagging and self.is_dialect(rec):
                yield [("", "", "X", {"Dialect": "Yes"})]
                continue
            out = []
            for x in rec["t"]:
                w, (lex, pos, prc3, prc2, prc1, prc0, enc0, asp, per, gen, num, mod, vox, stt, src), diac = \
                    x[0], x[1:1 + len(RAW_FIELDS)], x[-1]
                up = CAMEL_UPOS.get(pos or "", "X")
                if not re.search(f"[{LET}]", w):
                    up = "NUM" if w.isdigit() else "PUNCT" if not w.isalnum() else "X"
                feats = {"Raw": pos or "", "Voc": _vnorm(lex) if lex else ""}
                if num in ("s", "d", "p"):
                    feats["Number"] = {"s": "Sing", "d": "Dual", "p": "Plur"}[num]
                if per in ("1", "2", "3"):
                    feats["Person"] = per
                if gen in ("m", "f"):
                    feats["Gender"] = {"m": "Masc", "f": "Fem"}[gen]
                if asp in ("p", "i", "c"):
                    feats["Aspect"] = {"p": "Perf", "i": "Imp", "c": "Cmd"}[asp]
                if mod in ("i", "s", "j"):
                    feats["Mood"] = {"i": "Ind", "s": "Sub", "j": "Jus"}[mod]
                if vox in ("a", "p"):
                    feats["Voice"] = {"a": "Act", "p": "Pass"}[vox]
                for k, v in (("Prc3", prc3), ("Prc2", prc2), ("Prc1", prc1), ("Prc0", prc0), ("Enc0", enc0)):
                    if v and v not in ("0", "na"):
                        feats[k] = v
                if stt in ("d", "i", "c"):
                    feats["State"] = stt
                if src:
                    feats["Src"] = src
                out.append((w, lex or w, up, feats))
            yield out



    # ---- kaikki side info -------------------------------------------------------------
    def _info(self):
        """{fold(headword): [[pos, romanisation, [plurals], non-past, gender, is_lemma, gloss, vocalised,
        [singulatives], [lfold imperatives]]]}. A participle sense with a lexical gloss
        ("passive participle of أَغْلَقَ: closed") makes an adjective lemma."""
        if hasattr(self, "_info_cache"):
            return self._info_cache
        from ..core.util import Env, file_sig
        from ..core.sources import kaikki_plain
        env = Env(self)
        src = kaikki_plain(env)
        sig = hashlib.sha1(f"arinfo4|{file_sig(src)}".encode()).hexdigest()[:10]
        out = env.derived / f"ar_info_{sig}.json.gz"
        if out.exists():
            with gzip.open(out, "rt", encoding="utf-8") as f:
                self._info_cache = json.load(f)
            return self._info_cache
        info = {}
        with open(src, encoding="utf-8") as f:
            for line in f:
                if '"lang_code": "ar"' not in line:
                    continue
                d = json.loads(line)
                if d.get("lang_code") != "ar":
                    continue
                word = d.get("word", "")
                rom, plurals, nonpast, gender, voc, sing, imp = None, [], None, None, word, [], []
                for fm in d.get("forms", []):
                    tags = fm.get("tags") or []
                    form = fm.get("form") or ""
                    if "romanization" in tags and rom is None:
                        rom = form
                    elif "canonical" in tags and re.search(f"[{LET}]", form):
                        voc = form
                        gender = gender or ("f" if "feminine" in tags else "m" if "masculine" in tags else None)
                    elif tags == ["plural"] and re.search(f"[{LET}]", form):
                        plurals.append(form)
                    elif tags == ["non-past"] and nonpast is None:
                        nonpast = form
                    elif "singulative" in tags and "feminine" in tags and re.search(f"[{LET}]", form):
                        sing.append(fold(form))
                    elif "imperative" in tags and "active" in tags and re.search(f"[{LET}]", form):
                        imp.append(lfold(form))
                senses = d.get("senses", [])
                is_lemma = any(s.get("glosses") and not (s.get("form_of") or s.get("alt_of") or
                                                         set(s.get("tags", [])) & {"form-of", "alt-of", "misspelling"})
                               for s in senses) or \
                    any(PART_RE.match((s.get("glosses") or [""])[-1]) for s in senses)
                gloss = "; ".join((s.get("glosses") or [""])[-1] for s in senses[:4])
                info.setdefault(fold(word), []).append([d.get("pos", ""), rom, plurals, nonpast, gender, is_lemma,
                                                        gloss, voc, sorted(set(sing)), sorted(set(imp))])
        env.derived.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(out, "wb", mtime=0) as g:
            g.write(json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        self._info_cache = info
        return info

    def _has(self, w, poses):
        return any(r[0] in poses and r[5] for r in self._info().get(w, []))

    # ---- token fixes (tag time) ------------------------------------------------------
    def fix_token(self, tok):
        text, lemma, upos, ms = tok
        if upos == "X" and "Dialect=Yes" in ms:
            return tok
        raw = fold(text)
        lem = fold(lemma)
        m = dict(kv.split("=", 1) for kv in ms.split("|") if "=" in kv)
        pro = [m.get(k, "") for k in ("Prc3", "Prc2", "Prc1", "Prc0")]
        bare = raw
        if m.get("Prc2", "") in ("wa_conj", "fa_conj", "wa_part", "fa_conn", "fa_rrp", "wa_sub") and \
                bare[:1] in "وف" and len(bare) > 2:
            bare = bare[1:]                 # وأيضا, فقط after و
        key = SURFACE_FIX.get(bare) or SURFACE_FIX.get(lfold(bare))
        if key and m.get("Src") == "backoff":
            # a hand-listed surface is dictionary-validated (مثلما, أبو read as names)
            m["Src"] = "surface"
            ms = "|".join(f"{k}={v}" for k, v in m.items())
        if not key and m.get("Src") == "backoff" and upos in ("PROPN", "X", "NOUN", "ADJ"):
            got = self._backoff_reading(text)
            if got:
                lem, upos, extra = got
                m.update(extra)
                m["Src"] = "rescue"
                ms = "|".join(f"{k}={v}" for k, v in m.items())
        anna = ANNA_RE.match(lfold(raw)) and {"ك": "كأن", "ف": "إن", "ل": "لأن"}.get(lfold(raw)[:1], "أن")
        if not key and anna and not (upos == "SCONJ" and (lem == anna or anna == "أن" and lem == "إن")):
            # an unhamzated أنّ/إنّ + pronoun (انك, بانك, فانه): CAMeL reads آنك
            # "lead", آن "time", بان "builder"; فـ + إنّ, لـ + أنّ, كـ + أنّ, else أنّ
            return [lfold(text), anna, "SCONJ", ms]
        adv_bare = bare[2:] if bare.startswith("ال") else bare
        if key:                             # the whole surface is lexicalised (كذالك is no ك + ذا + ل + ك)
            lem, upos = key
        elif "ً" in text and upos in ("NOUN", "ADJ") and not m.get("Enc0") and not m.get("Prc1") and \
                self._has(adv_bare, ("adv",)):
            # written tanwin fath on a word the dictionary has as an adverb
            # (عادةً usually, not عادة habit; فجأةً)
            lem, upos = adv_bare, "ADV"
        elif upos in ("NOUN", "ADJ", "ADV", "DET") and bare != lem and not m.get("Enc0") and \
                self._has(bare, ("adv", "intj")) and (bare.endswith("ا") or bare.startswith("ال")):
            # an adverbial accusative or a lexicalised definite (دائما, كثيرا,
            # جدا, أيضا, شكرا, الآن): the dictionary's adverb/interjection, not the
            # noun/adjective it is built on
            poses = [r[0] for r in self._info()[bare] if r[5]]
            upos = "INTJ" if "intj" in poses and "adv" not in poses else "ADV"
            lem = bare
        if lem in LEMMA_FIX:
            lem = LEMMA_FIX[lem]
        if not key:
            lem, upos = self._resplit(raw, bare, lem, upos, m)
        if upos == "VERB" and lem == "أمن" and m.get("Aspect") in ("Imp", "Cmd") and "ؤمن" in raw:
            lem = "آمن"                     # يؤمن "believes" (يُؤْمِن), BERT's يُؤَمِّن "insures"
        if lem in LEMMA_POS and upos not in ("PUNCT", "PROPN"):
            upos = LEMMA_POS[lem]
        if upos == "PROPN" and lem in MONTHS_SET:
            upos = "NOUN"                   # يناير, مارس: month names, not names
        elif upos == "PROPN" and self._has(lem, ("noun", "adj", "adv")) and not self._has(lem, ("name",)) and \
                m.get("Src") != "backoff":
            upos = "NOUN"                   # common nouns CAMeL tags as names
        if lem in NAMES or fold(lemma) in NAMES or (upos in ("NOUN", "PROPN") and bare in NAMES):
            return [lfold(text), fold(lemma) if fold(lemma) in NAMES else lem, "PROPN", ms]
        if lem in SEMI_PREP and upos in ("NOUN", "PROPN", "ADJ", "ADV"):
            upos = "ADP"
        elif lem in QUANT and upos in ("NOUN", "PRON", "ADJ"):
            upos = "DET"
        elif lem == "لم" and upos == "ADV":
            upos = "PART"
        elif (lem in ORDINAL_SET or lem in COLOUR_SET) and upos in ("NOUN", "PROPN", "ADJ"):
            upos = "ADJ"
        if upos in ("NOUN", "ADJ", "PROPN") and (lem in NUMBER_SET or lem in NUMBER_BASE):
            upos = "NUM"
        if upos == "NUM" and lem in NUMBER_BASE:
            lem = NUMBER_BASE[lem]
        if upos == "VERB" and not key and (m.get("Src") == "spvar" or m.get("Aspect") == "Cmd"):
            lem = self._imperative(bare, lem, m)
        if upos in POS_KAIKKI and not key and lem not in COLOUR_SET and lem not in ORDINAL_SET:
            lem, upos = self._headword(raw, lem, upos, m)
        # أن / إن / أنّ / إنّ: the hamza the text writes decides (BERT reads إنّ as أنّ)
        if lem in ("أن", "إن"):
            # the written hamza decides (BERT reads إنّ as أنّ, also in فإنه, وإن)
            h = bare[1:] if m.get("Prc1") and bare[:1] in "لب" and len(bare) > 2 else bare
            if h[:2] in ("أن", "إن"):
                lem = h[:2]
        fg = FIXED_GROUPS.get(lem)
        if fg and len(fg) == 1 and upos in FUNC_UPOS and _group(upos) not in fg:
            # one fixed function word, one group (كأنه tagged PART, كأن SCONJ)
            upos = {"CONJ": "SCONJ"}.get(next(iter(fg)), next(iter(fg)))
        return [lfold(text), lem, upos, ms]

    def _imperative(self, bare, lem, m):
        """An imperative written with a bare alif (اذهب, اكتبوا, اعطني): BERT often
        reads it as a form-IV perfect (أذهب, أكتب; analysis source 'spvar'). The
        kaikki verbs whose active imperative paradigm has this spelling compete
        with CAMeL's lemma; the one CAMeL lemmatises most often elsewhere in the
        corpus wins (ذهب over أذهب; أعطى over عطا for اعط)."""
        s = lfold(bare)
        if not s.startswith("ا"):
            return lem
        cores = [s]
        if m.get("Enc0"):
            cores += [s[:-len(x)] for x in ENC_SUFFIX if s.endswith(x) and len(s) - len(x) >= 3]
        idx = self._imp_index()
        cands = sorted({v for c in cores for v in idx.get(c, ())} | {lem})
        if len(cands) == 1:
            return lem
        cnt = self._verb_counts()
        best = max(cands, key=lambda v: (cnt.get(v, 0), v == lem, v))
        # a clear majority only (unhamzated اعلن stays أعلن)
        return best if cnt.get(best, 0) >= max(5, 3 * cnt.get(lem, 0)) else lem

    def _imp_index(self):
        if not hasattr(self, "_imp_cache"):
            idx = {}
            for w, rows in self._info().items():
                for r in rows:
                    if r[0] == "verb" and r[5]:
                        for f in r[9]:
                            idx.setdefault(f, set()).add(w)
            self._imp_cache = idx
        return self._imp_cache

    def _verb_counts(self):
        """fold(CAMeL verb lemma) -> tokens in the Tatoeba corpus (raw cache rows
        with a dialect verdict, i.e. not passages), 'spvar' readings excluded."""
        if not hasattr(self, "_vcount"):
            raw = self._camel_raw([])
            c = {}
            for rec in raw.values():
                if rec.get("d") is None:
                    continue
                for x in rec["t"]:
                    lex, pos, src = x[1], x[2], x[1 + RAW_FIELDS.index("source")]
                    if pos == "verb" and lex and src != "spvar":
                        k = LEMMA_FIX.get(fold(lex), fold(lex))
                        c[k] = c.get(k, 0) + 1
            self._vcount = c
        return self._vcount

    def _resplit(self, raw, bare, lem, upos, m):
        """Readings where CAMeL splits the wrong letters or picks a rare word
        over the host the text means:
        - a quantifier/semi-preposition read as a proclitic + host (بعضكم: بـ +
          عَضّ "bite"; kaikki's بعض is the word);
        - a hollow verb's imperative read as a geminate verb (قم: قَمّ "sweep",
          not قام; نم, كن) when the imperative's verb is far commoner;
        - a feminine noun in ة read as its bare stem (المزرعة: مَزْرَع) when the
          ة noun is a headword and no feminine-of the stem;
        - ورى (CAMeL's root lemma for ترى/أريك): رأى "see", أرى "show";
        - a hollow verb's perfect read as a geminate (قلت: قال, not قَلَّ);
        - a geminate/assimilated imperfect read as a defective verb (أشك: شَكَّ,
          not شكا; تدعه: وَدَعَ "let", not دعا)."""
        s = lfold(bare)
        if m.get("Prc1") in ("bi_prep", "li_prep", "ka_prep"):
            for e in ("",) + ENC_SUFFIX:
                c = s[:-len(e)] if e and s.endswith(e) else (s if not e else None)
                if c and c in CLITIC_CLOSED and lem != CLITIC_CLOSED[c][0]:
                    return CLITIC_CLOSED[c]
        if upos == "VERB" and ((m.get("Src") == "lex" and len(lem) == 2) or
                               (m.get("Src") == "spvar" and s[:1] == "ا" and lem[:1] == "أ")):
            # (a geminate reading of a 2-letter imperative; or an unhamzated
            # alif, i.e. hamzat al-wasl, that CAMeL respelled as a form IV أ)
            cnt = self._verb_counts()
            cands = [v for v in self._imp_index().get(s, ()) if cnt.get(v, 0) >= 20]
            if cands:
                best = max(cands, key=lambda v: (cnt.get(v, 0), v))
                if best != lem and cnt.get(lem, 0) * 5 < cnt.get(best, 0):
                    m["Aspect"] = "Cmd"
                    return best, "VERB"
        if upos == "NOUN" and not lem.endswith("ة") and len(lem) >= 2:
            cand = lem + "ة"
            st = lfold(lem)
            fb = fold(bare)
            core = s[1:] if m.get("Prc2") and s[:1] in "وف" and len(s) > 3 else s
            core = core[1:] if m.get("Prc1") in ("bi_prep", "li_prep", "ka_prep") and core[:1] in "بلك" \
                and not core.startswith("لل") else core
            core = core[2:] if core.startswith(("ال", "لل")) else core[3:] if core.startswith(("بال", "كال")) else core
            # (the ة written, or ه with no pronoun suffix in the analysis: منزله is "his house")
            if ((core == st + "ه" and (fb.endswith("ة") or not m.get("Enc0"))) or
                    (m.get("Enc0") and core.startswith(st + "ت"))) and \
                    self._noun_head(cand) and not self._has(lem, ("adj",)):
                # (not a feminine adjective: صغيرة, باردة stay صغير, بارد)
                # a sense of its own (سباحة "swimming" beside "feminine of سبّاح"),
                # not a female person noun (جارة, مديرة, حفيدة stay on their
                # masculine card)
                own = [r for r in self._info().get(cand, []) if r[0] == "noun" and
                       (r[5] or (r[6] or "").startswith("verbal noun of")) and
                       not re.match(r"feminine (?:singular )?of ", r[6] or "")]
                if own and not all(FEMALE_RE.search(r[6] or "") for r in own):
                    return cand, "NOUN"
        if lem == "ورى":
            return ("أرى" if "ار" in s else "رأى"), "VERB"
        if upos == "VERB" and len(lem) == 2:
            # a form II geminate written in full (تقلل, يقلل: قلّل "reduce") or a
            # sound verb read as prefix + geminate (نقل "transport", not نَقِلّ)
            core = s[1:] if s[:1] in "وف" and len(s) > 3 else s
            cnt = self._verb_counts()
            if lem + lem[1] in core and self._has(lem + lem[1], ("verb",)):
                return lem + lem[1], "VERB"
            if len(core) == 3 and core[1:] == lfold(lem) and self._has(core, ("verb",)) and \
                    cnt.get(core, 0) > 5 * cnt.get(lem, 0):
                return core, "VERB"
        if upos == "VERB" and len(lem) == 2:
            # a hollow verb's 1st/2nd-person perfect (قلت, قلنا: قال) read as a
            # geminate (قَلَّ "to be few"): a geminate writes both letters there (قللت)
            core = s[1:] if s[:1] in "وف" and len(s) > 3 else s
            hollow = lem[0] + "ا" + lem[1]
            if re.match(lem + r"(?:ت|تم|تما|تن|نا)(?:ه|ها|هم|ك|كم|ني)?$", core) and self._has(hollow, ("verb",)):
                return hollow, "VERB"
        if upos == "VERB" and len(lem) == 3 and lem[-1] in "اى":
            # a geminate or assimilated verb's imperfect (أشك, يسعني, تدعه) read
            # as a defective verb (شكا, سعى, دعا): the imperfect with no weak
            # final letter spells only the first two radicals
            core = s[1:] if s[:1] in "وف" and len(s) > 3 else s
            core = core[1:] if core[:1] == "س" and len(core) > 3 else core
            m2 = re.match(r"[يتنا](..)(?:ني|ك|كم|كما|ه|ها|هم|هما|نا)?$", core)
            if m2 and m2.group(1) == lfold(lem[:2]):
                cnt = self._verb_counts()
                cands = [c for c in (lem[:2], "و" + lem[:2]) if self._has(c, ("verb",)) and cnt.get(c, 0) >= 3]
                if cands:
                    return max(cands, key=lambda c: (cnt.get(c, 0), c)), "VERB"
        return lem, upos

    def _noun_head(self, w):
        """A usable noun headword, or a verbal noun kaikki has only as "verbal
        noun of سبح: swimming" (bind_lexicon makes those words)."""
        return any(r[0] == "noun" and (r[5] or (r[6] or "").startswith("verbal noun of"))
                   for r in self._info().get(w, []))

    def _headword(self, raw, lem, upos, m):
        """A content lemma must be a dictionary headword of its POS. Else, in
        order: the other of noun/adjective (CAMeL tags كثير, جميل as nouns); a
        defective noun's kaikki form (ماضي -> ماض); the out-of-context MLE
        analysis of the surface when that is a headword (BERT's رأيت -> راوند,
        لست -> لاس, يمكنك -> مكنك)."""
        kp = POS_KAIKKI[upos]
        core = raw[1:] if raw[:1] in "وف" and len(raw) > 3 else raw
        if m.get("Prc1") and core[:1] in "بلك" and len(core) > 3:
            core = core[1:]
        core = core[2:] if core.startswith("ال") else core
        if core.startswith("آ") and lem.startswith("أ") and not (upos == "VERB" and m.get("Aspect") == "Imp"):
            # (a 1sg imperfect writes أ + أ as آ: آكل "I eat" is أكل, not آكل "eater")
            for u in ([upos] + [x for x in ("ADJ", "NOUN") if x != upos]):
                if u in ("NOUN", "ADJ") and self._has("آ" + lem[1:], POS_KAIKKI[u]):
                    # آمن "safe" not أمن "security", آجلا "later" not أجل: the text's madda decides
                    return "آ" + lem[1:], u
            if m.get("Src") == "spvar":
                return "?" + core, upos      # آجلا "later": kaikki has no آجل; never أجل "deadline"
        if upos in ("NOUN", "ADJ"):
            # a feminine elative (الكبرى, العظمى): kaikki's "feminine singular of
            # أكبر"; CAMeL reads a nisba (كُبْرِيّ) or a rare noun (كُبَر)
            # (only an af'al target of a fu'la form with no entry of its own:
            # دنيا "world", حلوى "sweets", يمني "Yemeni", أبجدية keep theirs)
            cs = [core] if self._info().get(core) else [core[:-1] + "ى"] if core.endswith("ي") else []
            for c in cs:
                if len(c) != 4 or any(r[5] for r in self._info().get(c, [])):
                    continue
                for r in self._info().get(c, []):
                    em = None if r[5] else ELATIVE_FEM_RE.match(r[6] or "")
                    if em:
                        tgt = LEMMA_FIX.get(fold(em.group(1)), fold(em.group(1)))
                        if tgt != lem and len(tgt) == 4 and self._has(tgt, ("adj",)):
                            return tgt, "ADJ"
        if upos == "NOUN" and m.get("Number") == "Plur" and (not m.get("Enc0") or core == lem):
            # the surface (or CAMeL's lemma, when that is the surface) is the
            # dictionary's plural of another singular (شباب: plural of شابّ "young
            # man", not CAMeL's شَبّ "alum"; نساء: plural of امرأة, not "longevity")
            tg = set()
            for r in self._info().get(core, []):
                for part in (r[6] or "").split("; "):
                    fm = FORM_OF_RE.match(part)
                    if fm and fm.group(0).startswith("plural"):
                        tg.add(LEMMA_FIX.get(fold(fm.group(1)), fold(fm.group(1))))
            if tg and lem not in tg:
                for t in sorted(tg):
                    if self._has(t, kp):
                        return t, upos
        if upos in ("NOUN", "ADJ") and lem.endswith("ي") and m.get("Voc", "").endswith("يّ") and self._has(lem[:-1], kp) and \
                any(fold(x) == lem[:-1] for r in self._info().get(lem, []) if not r[5]
                    for x in DEFINITE_OF_RE.findall((r[6] or "") + " # " + (r[7] or ""))):
            # BERT's nisba reading of a defective adjective's definite/feminine
            # form (غالية: غالِيّ "Gallic", kaikki's "definite of غالٍ" expensive)
            return lem[:-1], upos
        if upos in ("NOUN", "ADJ") and m.get("Voc", "").endswith("يّ") and core != lem:
            # BERT's nisba reading of a broken plural (المرضى: مَرْضِيّ
            # "satisfactory", kaikki's "plural of مريض"); a plural kaikki also
            # lists under the reading itself keeps it (جنود: جندي, not جند)
            tgts = [LEMMA_FIX.get(fold(x), fold(x)) for r in self._info().get(core, []) if not r[5]
                    for x in PLURAL_OF_RE.findall((r[6] or "") + " # " + (r[7] or ""))]
            if lem not in tgts:
                for tgt in tgts:
                    if self._has(tgt, kp):
                        return tgt, upos
        if upos in ("NOUN", "ADJ") and self._has(lem, ("noun",)) and self._has(lem, ("adj",)):
            # both: the entry whose vocalisation CAMeL reads (قِطّ cat, not قَطّ;
            # مُعَلِّم teacher); a tie goes to the page's lead POS (جميل, أسود, مريض)
            rows = [r for r in self._info()[lem] if r[5] and r[0] in ("noun", "adj")]
            v = m.get("Voc", "")
            nv = {_vnorm(r[7]) for r in rows if r[0] == "noun"}
            av = {_vnorm(r[7]) for r in rows if r[0] == "adj"}
            if v in nv and v not in av:
                return lem, "NOUN"
            if v in av and v not in nv:
                return lem, "ADJ"
            return lem, "ADJ" if rows[0][0] == "adj" else "NOUN"
        v = m.get("Voc", "")
        rows = self._info().get(lem, [])
        if upos == "NOUN" and m.get("Number") == "Sing" and m.get("Gender") == "Fem" and not lem.endswith("ة"):
            # a singulative (ورقة, وردة, شجرة) CAMeL lemmatises to its collective (ورق, ورد)
            if any(lem + "ة" in r[8] for r in self._info().get(lem, []) if r[0] == "noun") and \
                    self._has(lem + "ة", ("noun",)):
                return lem + "ة", upos
        if v and rows and v not in {_vnorm(r[7]) for r in rows if r[5]}:
            # CAMeL's reading is the dictionary's plural (أُسَر families, not
            # أَسْر captivity): its singular
            for r in rows:
                fm = FORM_OF_RE.match(r[6] or "") if not r[5] and _vnorm(r[7]) == v else None
                if fm and fm.group(0).startswith("plural"):
                    tgt = LEMMA_FIX.get(fold(fm.group(1)), fold(fm.group(1)))
                    if self._has(tgt, kp):
                        return tgt, upos
        if self._has(lem, kp):
            return lem, upos
        tgt = self._form_of(lem, v)          # زهور -> زهرة, أخرى -> آخر, مرأة -> امرأة, سيء -> سيئ
        if tgt and tgt != lem:
            for u in ([upos] + [x for x in ("NOUN", "ADJ", "VERB", "ADV") if x != upos]):
                if self._has(tgt, POS_KAIKKI[u]):
                    return tgt, u
        if upos in ("NOUN", "ADJ"):
            other = "ADJ" if upos == "NOUN" else "NOUN"
            if self._has(lem, POS_KAIKKI[other]):
                return lem, other
            if lem.endswith("ي") and self._has(lem[:-1], kp) and not m.get("Voc", "").endswith("يّ"):
                # (not a nisba adjective kaikki lacks: جامعي is no جامع, منزلي no منزل)
                return lem[:-1], upos
        if m.get("Src") == "backoff":
            return lem, upos
        alt = self.fallback_lemma(raw, lem)
        alt = LEMMA_FIX.get(alt, alt)
        if alt != lem:
            for u in ([upos] + [x for x in ("NOUN", "ADJ", "VERB", "ADV") if x != upos]):
                if self._has(alt, POS_KAIKKI[u]):
                    return alt, u
        return lem, upos

    def _form_of(self, lem, voc=""):
        """The headword a kaikki non-lemma entry points to (plural of, alternative
        form of, misspelling of, feminine singular of), else None. With CAMeL's
        vocalisation, only entries spelled that way count (سَرِقَة "theft" is a
        verbal noun; سَرَقَة is the plural of سارق)."""
        rows = self._info().get(lem, [])
        if voc and fold(voc) == lem:        # (Voc spells the surface: only when that is the lemma)
            vv = _vnorm(voc)
            same = [r for r in rows if _vnorm((r[7] or "").split(" # ")[0]) == vv]
            rows = same or rows
        for r in rows:
            if r[5]:
                continue
            m = FORM_OF_RE.match(r[6] or "")
            if m:
                return LEMMA_FIX.get(fold(m.group(1)), fold(m.group(1)))
        return None

    def fix_sentence(self, toks, row, doc):
        """Readings the English translation decides: اليوم "today" (else the
        day), a clause-initial لا answering "no", weekday names (الأحد is
        Sunday only when the English says so)."""
        en = (row[3] if row else "") or ""
        low = en.lower()
        names = self._name_map() if en else {}
        NAME_SET = set(names.values()) | {"Tom", "Mary", "John"}
        for t in toks:
            # a Tatoeba name the English carries (بول with "Paul", not بول "urine")
            if len(t) < 3 or t[2] in ("X", "PUNCT", "PROPN"):
                continue
            k = lfold(t[0])
            nm = names.get(k) or (names.get(k[1:]) if k[:1] in "وبلف" else None)
            # (or another name: translations rename سامي to Tom)
            if nm and (re.search(r"\b" + nm + r"\b", en) or
                       (any(w in NAME_SET for w in re.findall(r"\b[A-Z][a-z]+\b", en)) and
                        not self._reading_supported(t[1], en))):
                t[1], t[2] = (k if k in names else k[1:]), "PROPN"
        for i, t in enumerate(toks):
            if len(t) < 3 or t[2] == "X":
                continue
            s = t[0]
            core = s[1:] if s[:1] in "وف" and s[1:] in DAY_BY_SURFACE else s
            prev = lfold(toks[i - 1][0]) if i else ""
            day = DAY_BY_SURFACE.get(core) or DAY_BY_SURFACE.get("ال" + core)
            if day and prev in ("يوم", "ويوم", "بيوم", "ليوم", "فيوم"):
                t[1], t[2] = day[0], "NOUN"    # يوم الأربعاء, يوم جمعة: the weekday
            elif core == "اليوم" and re.search(r"\btoday\b", low):
                t[1], t[2] = "اليوم", "ADV"
            elif core in DAY_BY_SURFACE and re.search(r"\b" + DAY_BY_SURFACE[core][1] + r"s?\b", low):
                t[1], t[2] = DAY_BY_SURFACE[core][0], "NOUN"
            elif s == "لا" and t[2] == "PART" and (i + 1 == len(toks) or toks[i + 1][2] == "PUNCT") and \
                    re.match(r"\W*no\b", low):
                t[1], t[2] = "لا", "INTJ"
            elif core == "الم" and t[1] == "ألم" and i + 1 < len(toks) and toks[i + 1][2] == "VERB" and \
                    "Aspect=Imp" in toks[i + 1][3]:
                t[1], t[2] = "لم", "PART"   # أَلَمْ + jussive: "didn't ...?", not ألم "pain"
            elif t[1] == "لم" and t[2] == "PART" and re.search(r"\bwhy\b", low) and \
                    (i + 1 == len(toks) or toks[i + 1][2] != "VERB" or "Aspect=Imp" not in toks[i + 1][3]):
                t[1], t[2] = "لم", "ADV"    # لِمَ "why" (+ past or a noun), not لَمْ + jussive
        # unhamzated ان/انه/اني... opening a clause (sentence start, after
        # punctuation or قال) is إنّ; BERT reads أنّ
        for i, t in enumerate(toks):
            if len(t) < 3 or t[1] != "أن" or not t[0].startswith("ان"):
                continue
            prev = toks[i - 1] if i else None
            if prev is None or prev[2] == "PUNCT" or prev[1] in ("قال", "و") or \
                    (i == 1 and prev[2] in ("CCONJ", "INTJ")):
                t[1] = "إن"
        if row is not None:
            # verb compounds the translation supports (بدأ في only when the
            # English begins something: "School starts in September" is not)
            words = set(re.findall(r"[a-z]+", low))
            for t in toks:
                if len(t) > 3 and t[2] == "VERB" and t[1] in VERB_COMP_INDEX:
                    ok = [c for c, _, _ in VERB_COMP_INDEX[t[1]] if _en_supports(COMPOUNDS[c][0], words)]
                    t[3] = (t[3] + "|" if t[3] else "") + "EnComp=" + ";".join(ok)
        return toks

    def fallback_lemma(self, surface, lemma):
        """A frequency-list surface the tagged corpus never shows: the CAMeL MLE
        analyser's most likely lemma for it out of context (cached)."""
        memo = self._fallback_memo()
        if surface in memo:
            return memo[surface]
        if self._mle is None:
            import warnings
            warnings.filterwarnings("ignore")
            self._camel_env()
            from camel_tools.disambig.mle import MLEDisambiguator
            self._mle = MLEDisambiguator.pretrained("calima-msa-r13")
        d = self._mle.disambiguate([surface])[0]
        a = d.analyses[0].analysis if d.analyses else {}
        lem = fold(a.get("lex") or surface)
        lem = LEMMA_FIX.get(lem, lem)
        if a.get("pos") in ("noun_prop", "foreign", "latin", "abbrev", "digit", "punc") or \
                a.get("source") == "backoff" or (len(lem) <= 2 and len(surface) >= 5) or not a:
            # a transliterated name (فالانتين, سيمون) or an unanalysable dialect
            # form read as some rare lexeme: the surface stays unresolved
            lem = "?" + surface
        memo[surface] = lem
        self._fallback_dirty = True
        self._fb_new = getattr(self, "_fb_new", 0) + 1
        if self._fb_new % 500 == 0:
            self._save_fallback()
        return lem

    _mle = None

    # ---- passages ---------------------------------------------------------------
    passage_retag_names = True
    NAME_PROCLITICS = ("", "و", "ف", "ل", "ب", "ك", "ول", "وب", "فل", "فب", "وك")

    def passage_retag(self, toks, names=()):
        """Passages only. A declared name, also behind a proclitic (لمريم,
        بالإسكندرية, وليلى), is that name (CAMeL: ل + مريم unresolved, الإسكندرية
        the nisba اسكندري, سارة the verb سار). An adverbial accusative right after
        an indefinite accusative noun is the adjective agreeing with it (كتابا
        قديما "an old book", not قديما "in the old days")."""
        nm = {lfold(n): n for n in names if " " not in n}
        for i, t in enumerate(toks):
            s = t[0] or ""
            for pre in self.NAME_PROCLITICS:
                if s.startswith(pre) and len(s) - len(pre) >= 2 and s[len(pre):] in nm:
                    t[1], t[2] = nm[s[len(pre):]], "PROPN"
                    if pre:
                        t[3] = (t[3] + "|" if t[3] else "") + "PassName=Yes"
                    break
            else:
                if t[2] in ("ADV", "INTJ") and i and (t[1] or "").startswith("ال") and toks[i - 1][2] in ("NOUN", "ADJ") and \
                        "ال" in (toks[i - 1][0] or "")[:4] and self._has(t[1][2:], ("adj",)):
                    t[1], t[2] = t[1][2:], "ADJ"     # الشيء المهم "the important thing", not المهم "what matters is"
                elif t[2] == "ADV" and i and s.endswith("ا") and toks[i - 1][2] in ("NOUN", "ADJ") and \
                        (toks[i - 1][0] or "").endswith("ا") and (t[1] or "").endswith("ا") and \
                        self._has(t[1][:-1], ("adj",)):
                    t[1], t[2] = t[1][:-1], "ADJ"
        return toks

    def passage_uncounted(self, toks, resolved):
        """A declared name behind a proclitic (لمريم) is a name: not counted, not
        out of pack (classify reads an unresolved token by its surface)."""
        return {i for i, t in enumerate(toks) if "PassName=Yes" in (t[3] or "")}

    def _mle_reading(self, surface):
        """The out-of-context MLE analysis of a surface (memoised with the fallback
        lemmas: key "\x00" + surface): [lex, pos, source, enc0, prc0, prc1, prc2, asp]."""
        memo = self._fallback_memo()
        k = "\x00" + surface
        if k not in memo:
            if self._mle is None:
                import warnings
                warnings.filterwarnings("ignore")
                self._camel_env()
                from camel_tools.disambig.mle import MLEDisambiguator
                self._mle = MLEDisambiguator.pretrained("calima-msa-r13")
            d = self._mle.disambiguate([surface])[0]
            a = d.analyses[0].analysis if d.analyses else {}
            memo[k] = [a.get(x) for x in ("lex", "pos", "source", "enc0", "prc0", "prc1", "prc2", "asp")]
            self._fallback_dirty = True
        return memo[k]

    def _backoff_reading(self, text):
        """BERT backs off (a noun_prop guess) on words it knows out of context:
        مع/معه/معنا (~1,200 corpus tokens), هكذا, خلال, حيث; imperatives the MSA
        database lacks (اكتبي, ضع); an accusative alif after ي (شايا). In order:
        the MLE analysis when it is a lexical, non-name reading (a content word
        only without proclitics: ليندا is no ل + ندّ); a kaikki active imperative
        form (with an object suffix); a noun/adjective + accusative alif.
        Returns (lemma, upos, extra feats) or None (a name stays a name)."""
        raw = fold(text)
        got = self._backoff_core(raw)
        if got is None and raw[:1] in "وف" and len(raw) > 3:
            got = self._backoff_core(raw[1:])          # واكتب, فضع: a conjunction on the form
        if got is None and raw[:1] in "أا" and len(raw) > 3:
            got = self._question_core(raw[1:])         # أتريد, أيمكنك, أعندك: interrogative أ on the form
        return got

    def _question_core(self, raw):
        """The form after an interrogative أ: its MLE lexical reading, any
        non-name part of speech (a verb in any aspect, عند + suffix)."""
        lex, pos, src, enc0, prc0, prc1, prc2, asp = self._mle_reading(raw)
        if not lex or src != "lex" or pos in ("noun_prop", "foreign", "latin", "abbrev", "digit", "punc"):
            return None
        up = CAMEL_UPOS.get(pos)
        if up is None or self._has(raw, ("name",)):
            return None
        extra = {"Enc0": enc0} if enc0 not in (None, "0", "na") else {}
        return LEMMA_FIX.get(fold(lex), fold(lex)), up, extra

    def _backoff_core(self, raw):
        cnt = self._verb_counts()
        if self._has(raw, ("intj",)) and not self._has(raw, ("name",)):
            return raw, "INTJ", {}         # آه "ah" (also a rare noun "pain"): the interjection
        lex, pos, src, enc0, prc0, prc1, prc2, asp = self._mle_reading(raw)
        if lex and src == "lex" and pos not in ("noun_prop", "foreign", "latin", "abbrev", "digit", "punc"):
            up = CAMEL_UPOS.get(pos)
            lem = LEMMA_FIX.get(fold(lex), fold(lex))
            # function words; an imperative of a verb the corpus uses (a name
            # read as a rare verb, دان, تانينا, stays a name); a content word
            # only when the analysis is the surface itself
            if up in ("ADP", "CCONJ", "SCONJ", "PRON", "PART", "DET", "INTJ", "ADV") or \
                    (up == "VERB" and asp == "c" and cnt.get(lem, 0) >= 20) or \
                    (up in ("NOUN", "ADJ") and (lfold(lem) == lfold(raw) or prc0 == "Al_det") and
                     all(x in (None, "0", "na") for x in (prc1, prc2))):
                extra = {"Enc0": enc0} if enc0 not in (None, "0", "na") else {}
                if up == "VERB":
                    extra["Aspect"] = "Cmd"
                return lem, up, extra
        for u, kp in (("NOUN", ("noun",)), ("ADJ", ("adj",))):
            if self._has(raw, kp) and not self._has(raw, ("name",)):
                return raw, u, {}          # a headword as written (سمين "fat", not سمّين)
        s = lfold(raw)
        idx = self._imp_index()
        cores = [s] + [s[:-len(x)] for x in ENC_SUFFIX if s.endswith(x) and len(s) - len(x) >= 2]
        for c in cores:
            cands = [v for v in idx.get(c, ()) if cnt.get(v, 0) >= 20]
            if cands:
                return max(cands, key=lambda v: (cnt.get(v, 0), v)), "VERB", {"Aspect": "Cmd"}
        if len(raw) >= 4 and raw.endswith("ا"):
            for u, kp in (("NOUN", ("noun",)), ("ADJ", ("adj",))):
                if self._has(raw[:-1], kp) and not self._has(raw[:-1], ("name",)):
                    return raw[:-1], u, {}
        return None

    def span_fold(self, s):
        """passages: token surfaces reach the linker lfolded (hamza carriers,
        ة/ى, harakat); fold the text and declared oop lemmas the same way."""
        return lfold(s)

    def __getstate__(self):
        """Pickling (the passages context cache holds this spec through the
        lexicon): drop the MLE disambiguator (unpickling it would import
        camel_tools before _camel_env sets CAMELTOOLS_DATA) and the raw-analysis
        memo (large; _camel_raw reloads it from its cache file)."""
        d = dict(self.__dict__)
        d.pop("_mle", None)
        d.pop("_raw_memo", None)
        return d

    def _fallback_memo(self):
        if getattr(self, "_fb", None) is None:
            p = self.repo / ".cache" / "derived" / "ar_fallback_mle2.json"
            self._fb = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            self._fallback_dirty = False
        return self._fb

    def _save_fallback(self):
        from ..core.util import derived_write_ok
        if getattr(self, "_fallback_dirty", False) and derived_write_ok(self):
            p = self.repo / ".cache" / "derived" / "ar_fallback_mle2.json"
            p.write_text(json.dumps(self._fb, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            self._fallback_dirty = False

    def is_verb_lemma(self, w):
        return True

    # ---- resolution ------------------------------------------------------------------
    def bind_lexicon(self, lexicon):
        """Letters, roots and affixes are no words; a Classical-spelling alt-of
        (كِتٰب, whose dagger alef fold() strips) points nowhere; verbal nouns
        and participles are words of their own (derived_form_tags)."""
        self._lx = lexicon
        self._save_fallback()
        for s in list(lexicon.E):
            ents = [e for e in lexicon.E[s] if e["p"] not in ("character", "symbol", "suffix", "prefix", "root",
                                                               "interfix", "infix", "circumfix", "diacritical mark")]
            for e in ents:
                e["s"] = [sn for sn in e["s"] if not (sn[3] == "alt" and ("Classical" in sn[2] or "Quranic" in sn[2]))]
            ents = [e for e in ents if e["s"]]
            if ents:
                lexicon.E[s] = ents
            else:
                del lexicon.E[s]
        # homographs of one POS (أَرُزّ rice / أَرْز cedar, فُطُور breakfast /
        # فُطُور cracks): keep the entries whose vocalised headword is the one
        # CAMeL reads in context for >=60% of the lemma's tokens
        voc = self._camel_voc()
        pruned = []
        for s, ents in lexicon.E.items():
            by_pos = {}
            for e in ents:
                by_pos.setdefault(e["p"], []).append(e)
            for p, pe in by_pos.items():
                if len(pe) < 2 or p not in ("noun", "adj", "verb", "adv"):
                    continue
                cnt = voc.get(s, {}).get(p)
                if not cnt:
                    continue
                top, n = max(cnt.items(), key=lambda kv: (kv[1], kv[0]))
                if n < 3 or n < 0.6 * sum(cnt.values()):
                    continue
                keep = [self._entry_voc(s, e) == top for e in pe]
                if any(keep) and not all(keep):
                    drop = [id(e) for e, k in zip(pe, keep) if not k]
                    lexicon.E[s] = [e for e in lexicon.E[s] if id(e) not in drop]
                    pruned.append(s)
        from ..core.util import stat
        stat("ar_homograph_entries_pruned_by_vocalisation", len(pruned))
        # a verbal noun kaikki glosses only as "verbal noun of قام": its verb's
        # first gloss as a gerund (قيام "standing up; carrying out")
        vn = 0
        for s, ents in lexicon.E.items():
            if any(e["p"] == "noun" and lexicon.entry_usable(e) for e in ents):
                continue                    # فطور "breakfast": a real noun entry wins
            for e in ents:
                if e["p"] != "noun" or any(sn[3] == "" for sn in e["s"]):
                    continue
                for sn in e["s"]:
                    m = re.match(r"verbal noun of (\S+)", sn[0])
                    if not m:
                        continue
                    v = fold(m.group(1))
                    target = _vnorm(m.group(1))
                    vents = [ve for ve in lexicon.E.get(v, []) if ve["p"] == "verb"]
                    # the verb form the text names (تنفيذ: نَفَّذَ form II, not نَفَذَ)
                    vents.sort(key=lambda ve: self._entry_voc(v, ve) != target)
                    vg = [x[0] for ve in vents for x in ve["s"] if x[3] == ""]
                    ger = _gerund(vg[0]) if vg else None
                    if ger:
                        e["s"].insert(0, [ger, "", [t for t in sn[2] if t != "form-of"], ""])
                        vn += 1
                    break
        # kaikki's "rare" on a verbal-noun page (حُبّ "love": rare as the verbal
        # noun of حَبَّ) is not the noun's frequency: a noun the corpus reads
        # >=50 times keeps its senses
        from ..core.lexicon import sense_tags
        unrared = 0
        for s, ents in lexicon.E.items():
            n = sum(voc.get(s, {}).get("noun", {}).values())
            if n < 50 or lexicon.usable_entries(s, ["noun"]):
                continue
            for e in ents:
                defs = [sn for sn in e["s"] if sn[3] == ""]
                if e["p"] == "noun" and defs and all("rare" in sense_tags(e, sn) for sn in defs):
                    for sn in e["s"]:
                        sn[2] = [t for t in sn[2] if t != "rare"]
                    e["ht"] = e.get("ht", set()) - {"rare"} if isinstance(e.get("ht"), set) else e.get("ht")
                    unrared += 1
        stat("ar_frequent_nouns_unmarked_rare", unrared)
        # a participle kaikki has only as "passive participle of أَغْلَقَ: closed"
        # (مغلق, نائم, واقف): its lexical part is the adjective's sense
        pp = 0
        for s, ents in lexicon.E.items():
            for e in ents:
                if e["p"] not in ("adj", "noun") or any(sn[3] == "" for sn in e["s"]):
                    continue
                for sn in e["s"]:
                    m = PART_RE.match(sn[0])
                    if m:
                        e["s"].insert(0, [m.group(1).rstrip(" ."), "", [t for t in sn[2] if t != "form-of"], ""])
                        pp += 1
                        break
        stat("ar_participle_senses", pp)
        # a noun/adjective sense glossed as a verb ("to rain" under مَطَر, a
        # verbal-noun line's verb meaning): dropped when the entry has noun
        # senses, else read as a gerund
        tv = 0
        for s, ents in lexicon.E.items():
            for e in ents:
                if e["p"] not in ("noun", "adj"):
                    continue
                verbish = [sn for sn in e["s"] if re.match(r"^to [a-z]", sn[0])]
                if not verbish:
                    continue
                rest = [sn for sn in e["s"] if sn not in verbish]
                if any(sn[3] == "" for sn in rest):
                    e["s"] = rest
                else:
                    for sn in verbish:
                        sn[0] = _gerund(sn[0]) or sn[0]
                tv += 1
        from ..core.util import stat
        stat("ar_verbal_noun_glosses", vn)
        stat("ar_noun_senses_glossed_as_verbs", tv)
        for s in list(lexicon.F):
            keep = [x for x in lexicon.F[s] if not (x[2] == "alt" and s not in lexicon.E)]
            if keep:
                lexicon.F[s] = keep
            else:
                del lexicon.F[s]

    derived_form_tags = {"noun-from-verb", "participle"}
    # analyser artifacts with >= min_corpus_tokens tokens: clitic misparses of
    # names and dialect (فالانتين -> أنة, سيمون -> مون, شي "thing"), أعلم "I know"
    # read as an elative
    refill_unexampled = True      # a word every sentence of which the policy drops (إسرائيلي) gives way
    drop_keys = {**{k: None for k in [("أنة", "NOUN"), ("تب", "VERB"), ("شي", "NOUN"), ("مون", "VERB"),
                                      ("روك", "NOUN"), ("طاب", "VERB"), ("أعلم", "ADJ"), ("سي", "NOUN"),
                                      ("مار", "NOUN"), ("آل", "VERB"), ("ورى", "VERB"), ("خص", "VERB"),
                                      ("كن", "NOUN"), ("ورى", "NOUN"), ("لوى", "VERB"), ("لوى", "NOUN"),
                                      ("إرهاب", "NOUN")]},    # policy: its sentences are the dropped ones
                 ("باي", "NOUN"): ("أي", "DET"),
                 ("سماع", "VERB"): ("سماع", "NOUN"),     # سَمَاعِ "hear!": the verbal noun "hearing"
                 ("جائز", "ADJ"): ("جائزة", "NOUN"),     # its tokens are الجائزة "the prize"
                 ("كن", "VERB"): ("كان", "VERB"),         # لكنت = لـ + كنت
                 ("شخصا", "ADV"): ("شخص", "NOUN")}      # an accusative "a person", not "personally"

    def _entry_voc(self, s, e):
        """The normalised vocalised headword of lexicon entry e under key s (its
        kaikki row: same POS, first gloss contained)."""
        g0 = e["s"][0][0] if e["s"] else ""
        for r in self._info().get(s, []):
            if r[0] == e["p"] and g0 and g0 in (r[6] or ""):
                return _vnorm(r[7])
        return None

    def _camel_voc(self):
        """{lemma: {kaikki pos: {normalised vocalised CAMeL lex: tokens}}} over the
        tagged corpus (final lemma and POS after fix_token), cached."""
        from ..core.util import file_sig
        d = self.repo / ".cache" / "derived"
        cands = sorted(d.glob(f"tagged_{self.versions['tag']}_*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
        if not cands:
            return {}
        src = cands[-1]
        sig = hashlib.sha1(f"arvoc3|{file_sig(src)}".encode()).hexdigest()[:10]
        out = d / f"ar_voc_{sig}.json.gz"
        if out.exists():
            with gzip.open(out, "rt", encoding="utf-8") as f:
                return json.load(f)
        kp = {"NOUN": "noun", "ADJ": "adj", "VERB": "verb", "ADV": "adv"}
        res = {}
        for _, toks in _iter_tagged(src):
            for t in toks:
                pos = kp.get(t[2])
                v = re.search(r"(?:^|\|)Voc=([^|]*)", t[3]) if pos else None
                if not v or not v.group(1):
                    continue
                c = res.setdefault(t[1], {}).setdefault(pos, {})
                c[v.group(1)] = c.get(v.group(1), 0) + 1
        with gzip.GzipFile(out, "wb", mtime=0) as g:
            g.write(json.dumps(res, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return res

    def _name_map(self):
        """{folded Arabic surface: English name} for Tatoeba personal and place
        names the analyser reads as words (بول Paul, not "urine"; جيم Jim;
        هاري Harry): surfaces that occur with that capitalised English name in
        >=60% of their sentences (>=3), the name's spelling matching. Built from
        the cached corpus, cached."""
        if getattr(self, "_names_cache", None) is not None:
            return self._names_cache
        from ..core.util import file_sig
        d = self.repo / ".cache" / "derived" if self.repo is not None else None
        cands = sorted(d.glob("corpus_*.json.gz")) if d is not None and d.exists() else []
        if not cands:
            self._names_cache = {}
            return {}
        src = cands[-1]
        sig = hashlib.sha1(f"arnames5|{file_sig(src)}".encode()).hexdigest()[:10]
        out = d / f"ar_names_{sig}.json.gz"
        if out.exists():
            with gzip.open(out, "rt", encoding="utf-8") as f:
                self._names_cache = json.load(f)
            return self._names_cache
        with gzip.open(src, "rt", encoding="utf-8") as f:
            rows = [r for r in json.load(f)["rows"] if r[3]]
        en_n, tok_n, co = {}, {}, {}
        for r in rows:
            names = set(re.findall(r"\b[A-Z][a-z]{2,}\b", r[3]))
            toks = set()
            for w in re.findall(f"[{LET}]+", r[1]):
                w = lfold(w)
                toks.add(w)
                if w[:1] in "وبلف" and len(w) > 3:
                    toks.add(w[1:])
            for t in toks:
                tok_n[t] = tok_n.get(t, 0) + 1
            for nm in names:
                en_n[nm] = en_n.get(nm, 0) + 1
                for t in toks:
                    co[(t, nm)] = co.get((t, nm), 0) + 1
        res = {}
        info = self._info()
        for (t, nm), c in sorted(co.items()):
            if nm in EN_NOT_NAME or (t[-1:] in "يه" or t.endswith(("يون", "يين"))) and \
                    re.search(r"(?:an|ans|ish|ese|ic|is)$", nm):
                continue            # months, languages, religions, nisba demonyms: words
            if nm.endswith("i") and any(r[0] != "name" and re.search(rf"\b{nm}\b", r[6] or "")
                                        for k in (t, t[2:] if t.startswith("ال") else t) for r in info.get(k, [])):
                continue            # عراقي "Iraqi" (a dictionary word); سامي Sami, يومي Yumi are names
            if c >= 3 and c >= 0.6 * tok_n[t] and c >= 0.3 * en_n[nm] and len(t) >= 2 and _translit_ok(t, nm):
                if t not in res or c > res[t][1]:
                    res[t] = [nm, c]
        res = {t: v[0] for t, v in res.items()}
        from ..core.util import derived_write_ok
        if derived_write_ok(self):
            with gzip.GzipFile(out, "wb", mtime=0) as g:
                g.write(json.dumps(res, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        self._names_cache = res
        return res

    def post_resolve(self, toks, out):
        """The tagger's lemma is authoritative when it is a usable headword of
        its POS (the core prefers a surface reading, but an Arabic surface
        carries clitics). Then COMPOUNDS merge."""
        lx = getattr(self, "_lx", None)
        for i, t in enumerate(toks):
            r = out[i]
            if r is None or len(t) < 3 or t[2] in ("PROPN", "X", "PUNCT"):
                continue
            from ..core.lexicon import group_of
            g = group_of(t[2])
            if t[0] in self.closed_surfaces and not (r[0] != t[1] and t[1] in FIXED_KEYS_BY_LEMMA.get(g, ())):
                # the folded surface is a closed word's (كأن -> كان); a fixed
                # function lemma the tagger asserts wins
                continue
            if g == "NUM" or (r[0] == t[1] and r[1] == g):
                continue
            if lx is not None and lx.usable_entries(t[1], self.group_kpos.get(g)):
                out[i] = (t[1], g)
            elif t[1] in FIXED_KEYS_BY_LEMMA.get(g, ()):
                out[i] = (t[1], g)
        self._compounds(toks, out)
        return out

    def word_pos(self, rec, pos, keys):
        """A noun/adjective whose gloss came from the other POS's dictionary entry
        is labelled that POS (حديث "talk" is a noun, واجب "duty" a noun, كاف
        "enough" an adjective): kaikki splits noun and adjective, CAMeL's tags
        and the group_kpos fallback do not. Kept when that key is in the pack."""
        if rec.get("group") == "NOUN" and pos == "verb":
            return "noun"       # سماع "hearing": its gloss came from the imperative-noun entry سَمَاعِ
        other = {"NOUN": ("adj", "ADJ"), "ADJ": ("noun", "NOUN")}.get(rec.get("group"))
        if other and rec.get("entry_pos") == other[0] and not rec.get("fixed") and \
                (rec["lemma"], other[1]) not in keys:
            return other[0]
        return pos

    def note_words(self, words):
        """Sentence linking: a compound outside the pack stays its parts (بدأ في
        ranked below the pack must not make "بدأ عهد جديد في البلد" unusable)."""
        self._pack_keys = {w["lemma"] for w in words}
        self._wid = {w["id"]: w for w in words}
        self._plp = None                            # per-word caches: ids change between passes
        self.__dict__.pop("_own_voc_cache", None)
        self.__dict__.pop("_own_gloss_cache", None)

    def fix_links(self, row, toks, links, key_to_id):
        """Homograph links: a content word whose gloss the sentence English does
        not carry is unlinked when another reading of its spelling is carried
        (رجل "man" in "my leg hurts": رِجْل; أمام "in front of" for الإمام
        "the imam"; جد "grandfather" for جدتي; أجرى for يجري "runs"). The rival
        readings: the lemma's other kaikki headwords (another vocalisation or
        POS) and the headwords its surfaces spell without clitics."""
        wid = getattr(self, "_wid", None)
        en = row[3] if row is not None and len(row) > 3 else ""
        if not wid or not en or not links:
            return links
        words = set(re.findall(r"[a-z]+", en.lower()))
        # English words another link of the sentence already accounts for
        # (المدرّس "teacher": not a rival reading of المدرسة "school")
        claim = {i: {x for x in words if _en_supports(wid[i]["en"], {x})} for i in dict.fromkeys(links) if i in wid}
        drop = set()
        for i in dict.fromkeys(links):
            w = wid.get(i)
            if w is None or w["pos"] not in ("noun", "verb", "adj", "adv") or " " in w["lemma"]:
                continue
            free = words - set().union(*(v for j, v in claim.items() if j != i))
            # a token spelling a name wins even when the English has the word
            # elsewhere (يومي Yumi, بيتي Betty: the word plus ي in "the day after tomorrow")
            if self._name_in_english(w, toks, en, possessive_only=_en_supports(w["en"], words)):
                pass
            elif _en_supports(w["en"], words) or _en_supports(self._own_gloss(w), words) or \
                    not self._rival_supported(w, toks, free - RIVAL_WEAK_EN):
                continue
            drop.add(i)
        return [i for i in links if i not in drop] if drop else links

    def _reading_supported(self, lem, en):
        """The English carries a sense of one of lem's dictionary headwords
        (صادق "honest" in "Tom is honest": the word, not the name Sadiq)."""
        words = set(re.findall(r"[a-z]+", en.lower()))
        return any(r[5] and r[0] in ("noun", "verb", "adj", "adv") and
                   _en_supports(re.split(r"\s*;\s*", r[6] or "")[0], words)
                   for r in self._info().get(fold(lem), []))

    def _name_in_english(self, w, toks, en, possessive_only=False):
        """A token of the word spells a proper name the English carries, one too
        rare for the corpus name map (يومي Yumi, not يوم "day" + ي; بيتي Betty,
        not بيت "house" + ي; كن Ken, not كان): the English word is capitalised,
        never written lowercase anywhere in the corpus English, and its
        consonants match the token's."""
        lower, dict_caps = self._en_lower_vocab()
        own = set(re.findall(r"[a-z]+", w["en"].lower()))     # أكتوبر October: the word itself
        caps = [c for c in re.findall(r"\b[A-Z][a-z]+\b", en)
                if c.lower() not in lower and c not in dict_caps and c.lower() not in own]
        if not caps:
            return False
        sk = [_skel_ar(lfold(t[0])).replace("g", "j") if len(t) > 2 and t[2] != "PUNCT" else "" for t in toks]
        for c in caps:
            hits = [i for i, x in enumerate(sk) if x and x == _skel_en(c)]
            # the only token spelling the name (زيري is Ziri, so زار is not)
            if len(hits) == 1 and lfold(toks[hits[0]][1]) == lfold(w["lemma"]) and \
                    (not possessive_only or lfold(toks[hits[0]][0]) == lfold(w["lemma"]) + "ي"):
                return True
        return False

    def _en_lower_vocab(self):
        """Every word the corpus English writes in lowercase at least once, and
        the capitalised words of the dictionary's non-name glosses."""
        if getattr(self, "_en_lower", None) is None:
            voc = set()
            d = self.repo / ".cache" / "derived" if self.repo is not None else None
            cands = sorted(d.glob("corpus_*.json.gz")) if d is not None and d.exists() else []
            if cands:
                with gzip.open(cands[-1], "rt", encoding="utf-8") as f:
                    for r in json.load(f)["rows"]:
                        voc.update(re.findall(r"\b[a-z]+\b", r[3] or ""))
            caps = set()                    # Arab, Islam, Algeria: dictionary words, not names
            for rows in self._info().values():
                for r in rows:
                    if r[0] != "name":
                        caps.update(re.findall(r"\b[A-Z][a-z]+\b", r[6] or ""))
            self._en_lower = (voc, caps)
        return self._en_lower

    def _lfold_index(self):
        if getattr(self, "_lfx", None) is None:
            ix = {}
            for k, rows in self._info().items():
                if any(r[5] and r[0] in ("noun", "verb", "adj", "adv") for r in rows):
                    ix.setdefault(lfold(k), []).append(k)
            self._lfx = ix
        return self._lfx

    def _own_vocs(self, w):
        """The vocalisations of the pack word's own reading: its picked row's, and
        every row of the lemma of the same POS whose senses carry the pack gloss
        (قَدَّمَ for قدم "to present, to offer", not only the picked قَدَمَ "to precede")."""
        cache = self.__dict__.setdefault("_own_voc_cache", {})
        if w["id"] not in cache:
            own = self._pick_row(w["lemma"], POS_KPOS.get(w["pos"], ()), w["en"])
            vocs = {_vnorm(own[7])} if own and own[7] else set()
            pack = set(re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", "", w["en"].lower()))) - EN_STOP
            kpos = POS_KPOS.get(w["pos"], ())
            for r in self._info().get(w["lemma"], []):
                # same POS only: the verb فَعَلَ "to act" is no reading of the noun فعل "act"
                if r[5] and r[7] and r[0] in kpos and pack and _en_supports_strict(" ".join(sorted(pack)),
                                                                  set(re.findall(r"[a-z]+", (r[6] or "").lower()))):
                    vocs.add(_vnorm(r[7]))
            cache[w["id"]] = vocs
        return cache[w["id"]]

    def _own_gloss(self, w):
        """Every dictionary sense of the pack word's own reading: all rows with
        its vocalisations, any POS (عَمَل "action, deed; work, business" for the
        pack's "job, employment; deed"; خَطَأ adj "wrong" for the noun "mistake")."""
        cache = self.__dict__.setdefault("_own_gloss_cache", {})
        if w["id"] not in cache:
            vocs = self._own_vocs(w)
            cache[w["id"]] = "; ".join(r[6] or "" for r in self._info().get(w["lemma"], [])
                                       if r[5] and r[7] and _vnorm(r[7]) in vocs)
        return cache[w["id"]]

    def _pack_lemma_pos(self):
        if getattr(self, "_plp", None) is None:
            self._plp = {(w["lemma"], w["pos"]) for w in (getattr(self, "_wid", None) or {}).values()}
        return self._plp

    def _rival_supported(self, w, toks, words):
        info, ix = self._info(), self._lfold_index()
        lem = w["lemma"]
        own = self._pick_row(lem, POS_KPOS.get(w["pos"], ()), w["en"])
        own_voc = _vnorm(own[7]) if own else None
        own_words = set(re.findall(r"[a-z]+", w["en"].lower()))
        own_full = self._own_gloss(w)
        # light words are no evidence ("comes" for جاء against أهل)
        words = {x for x in words if not (_en_stems(x) & RIVAL_WEAK_EN)}
        keys = {lem}
        names = self._name_map()
        for t in toks:
            if len(t) > 2 and lfold(t[1]) == lfold(lem) and names.get(lfold(t[0])) and \
                    names[lfold(t[0])].lower() in words:
                return True                     # سامي "Sami" read as سامّ "poisonous"
            # (a lemma that itself starts with a proclitic is a fixed form: بالفعل is no ب + فعل)
            if len(t) > 2 and lfold(t[1]) == lfold(lem) and not re.match("(?:[وفبلك]ال|لل)", lfold(lem)):
                for st in _clitic_stems(lfold(t[0])):
                    keys.update(ix.get(st, ()))
        for k in sorted(keys):
            for r in info.get(k, []):
                if not r[5] or r[0] not in ("noun", "verb", "adj", "adv"):
                    continue
                if k == lem and r[7] and _vnorm(r[7]) in self._own_vocs(w):
                    continue            # the pack word's own reading (any POS: خَطَأ noun/adj)
                if r[7] and _vnorm(r[7]) in {_vnorm(v) for v in re.findall(f"[{LET}{MARKS}]+", own_full)} and \
                        (k, r[0]) not in self._pack_lemma_pos():
                    continue            # the verb of its own verbal noun (شَدَّ for شدة), unless a card of its own (فعل)
                g = re.split(r"\s*;\s*", re.sub(r"\([^)]*\)", "", r[6] or ""))[0]
                if not g or g.startswith(("verbal noun of", "plural of", "feminine", "inflection of")):
                    continue
                if _en_supports(g, own_words):
                    continue            # a synonym reading, not a rival
                if _en_supports_strict(g, words):
                    return True
        return False

    def _compounds(self, toks, out):
        pk = getattr(self, "_pack_keys", None)
        ok = lambda comp: pk is None or comp in pk
        n = len(toks)
        surf = [t[0] if len(t) > 2 else "" for t in toks]
        lem = [t[1] if len(t) > 2 else "" for t in toks]
        feats = [dict(kv.split("=", 1) for kv in t[3].split("|") if "=" in kv) if len(t) > 3 else {} for t in toks]
        # fixed phrases, longest first, by folded surface
        for i in range(n):
            for comp, grp, parts in PHRASE_INDEX.get(_strip_wa(surf[i]), ()):
                k = len(parts)
                if not ok(comp):
                    continue
                if i + k > n or any(out[j] is not None and " " in out[j][0] for j in range(i, i + k)):
                    continue
                if all(_part_ok(parts[j], surf[i + j], lem[i + j], feats[i + j], j == k - 1) for j in range(1, k)):
                    for j in range(i, i + k):
                        out[j] = (comp, grp)
                    break
        # teens: unit + عشر/عشرة (ثلاثة عشر, إحدى عشرة)
        for i in range(n - 1):
            base = TEEN_SURF.get(_strip_wa(surf[i]))
            if base and surf[i + 1] in ("عشر", "عشره") and out[i] is not None and ok(base + " عشر"):
                out[i] = out[i + 1] = (base + " عشر", "NUM")
        # verb + preposition / light-verb noun
        for i in range(n):
            r = out[i]
            if r is None or r[1] != "VERB" or " " in r[0] or r[0] not in VERB_COMP_INDEX:
                continue
            for j in range(i + 1, min(n, i + 5)):
                if toks[j][2] == "PUNCT" or (toks[j][2] == "VERB" and j > i + 1):
                    break
                hit = None
                allowed = feats[i].get("EnComp")
                for comp, kind, arg in VERB_COMP_INDEX[r[0]]:
                    if kind in MERGED_KINDS:
                        continue        # verb + preposition: one card, the verb's (finalize_words)
                    if (allowed is not None and comp not in allowed.split(";")) or not ok(comp):
                        continue
                    if kind == "bound" and (feats[j].get("Prc1") == BOUND_PRC[arg] or lem[j] == arg):
                        hit = (comp, lem[j] == arg)
                    elif kind == "free" and lem[j] == arg:
                        hit = (comp, True)
                    elif kind == "noun" and lem[j] == arg and toks[j][2] == "NOUN":
                        hit = (comp, True)
                    if hit:
                        break
                if hit:
                    out[i] = (hit[0], "VERB")
                    if hit[1]:
                        out[j] = (hit[0], "VERB")
                    break
                if toks[j][2] == "ADP" or feats[j].get("Prc1"):
                    break           # another preposition first: not this compound
        return out

    # ---- words ------------------------------------------------------------------------
    noun_head_template = "ar-noun"

    def noun_display(self, lemma, gender, plural, en):
        """Indefinite, bare. A feminine noun that does not end in ة says so."""
        if gender == "f" and not lemma.endswith("ة") and "(f)" not in en:
            en = en + " (f)"
        return lemma, en

    def _corpus_lemma_of(self, f, ctx):
        """The lemma the tagged corpus most often gives a bare or article-prefixed
        surface, when it does so at least 3 times (عملة is its own word, not
        عامل's plural)."""
        if getattr(self, "_form_lemma", None) is None:
            by = {}
            for _, toks in _iter_tagged(ctx["tagged"]):
                for t in toks:
                    if len(t) > 2 and t[2] in ("NOUN", "ADJ"):
                        s = lfold(t[0])
                        for p in ("وال", "فال", "بال", "كال", "لل", "ال"):
                            if s.startswith(p) and len(s) - len(p) >= 2:
                                s = s[len(p):]
                                break
                        by.setdefault(s, Counter())[lfold(t[1])] += 1
            self._form_lemma = {s: sorted(c.items(), key=lambda x: (-x[1], x[0]))[0] for s, c in by.items()}
        lem, n = self._form_lemma.get(f, (None, 0))
        return lem if n >= 3 else None      # a stray reading (خطاء twice as خطوة) is no attestation

    def finalize_words(self, env, ctx, words):
        from ..core.gloss import strip_gloss_style
        from ..core.util import stat
        info = self._info()
        no_pron, plural_alts, stems, merged_twins = [], 0, 0, 0
        heads = {w["lemma"] for w in words}
        # one CAMeL pass for the words _voc_pron may diacritise (no vocalised kaikki row)
        need = sorted({p for w in words for p in w["lemma"].split(" ") if p not in FIXED_PRON and
                       not any(r[7] and re.search(f"[{MARKS}]", r[7]) for r in info.get(p, []))})
        if need:
            self._camel_raw(need)
        seen = set()
        for k in self._word_freq():
            k = lfold(k)
            seen.add(k)
            for p in ("وال", "فال", "بال", "كال", "لل", "ال"):
                if k.startswith(p) and len(k) - len(p) >= 2:
                    seen.add(k[len(p):])
                    break
        for w in words:
            w["en"] = strip_gloss_style(w["en"])
            w["en"] = re.sub(r"[,;]\s*(including|such as|e\.g\.|namely|like|especially|of|and|or)\s*$", "", w["en"])
            w["en"] = re.sub(r"^(?:of )?(?:or )?(?:relating|pertaining|characteristic|belonging) (?:to|of) ",
                             "relating to ", w["en"])
            w["en"] = re.sub(r"^relating to ([A-Z]\w*(?:ic|an|ese|ish|i))\b", r"\1", w["en"])
            if w["pos"] in ("noun", "adj", "adv") and re.match(r"^to [a-z]", w["en"]) and \
                    getattr(self, "_lx", None) is not None:
                # the core's cross-POS fallback took a verb sense ("to rain" for
                # مطر): the lemma's own noun/adjective senses, else a gerund
                own = [sn[0] for e in self._lx.usable_entries(w["lemma"], POS_KPOS.get(w["pos"]))
                       for sn in e["s"] if sn[3] == "" and not re.match(r"^to [a-z]", sn[0])]
                w["en"] = strip_gloss_style("; ".join(dict.fromkeys(own[:2]))) if own else \
                    (_gerund(w["en"]) or w["en"])
            key = w["lemma"]
            if w["pos"] == "verb" and " " not in key:
                same, other = [], []
                ew = set(re.findall(r"[a-z]+", w["en"].lower()))
                for comp, kind, arg in VERB_COMP_INDEX.get(key, ()):
                    disp = COMPOUND_DISPLAY[comp]
                    if kind not in MERGED_KINDS or disp in w["en"]:
                        continue
                    (same if _en_supports(COMPOUNDS[comp][0], ew) else other).append(disp)
                if same:
                    w["en"] += " (" + ", ".join(same) + ")"
                for disp in other:
                    w["en"] += f"; ({disp}) {COMPOUNDS[disp.replace('ـ', '')][0]}"
                merged_twins += bool(same or other)
            if key in COMPOUND_DISPLAY:
                w["w"] = COMPOUND_DISPLAY[key]
            kpos = POS_KPOS.get(w["pos"], ())
            row = self._pick_row(key, kpos, w["en"])
            p = FIXED_PRON.get(key)
            if p is None and row and row[1]:
                p = row[1]
            if p is None and " " not in key:
                p = self._voc_pron(key, kpos)
            if p is None and " " in key:
                ps = []
                for part in key.split(" "):
                    rr = self._pick_row(part, (), "")
                    ps.append(FIXED_PRON.get(part) or (rr[1] if rr and rr[1] else None) or self._voc_pron(part, ()))
                p = " ".join(ps) if all(ps) else None
            if p:
                w["pron"] = normalize_pron(p)
            else:
                no_pron.append(key)
            alt = []
            if w["pos"] == "noun" and row:
                for pl in row[2]:
                    f = fold(pl)
                    # a broken plural the corpus attests (not a rare classical
                    # plural, خطاء, مساوف) and no other pack headword (خدمة is
                    # no plural card for خادم)
                    if f != key and not _sound_plural(key, f) and f not in alt and \
                            f not in heads and lfold(f) in seen and self._corpus_lemma_of(lfold(f), ctx) == lfold(key):
                        alt.append(f)
                plural_alts += bool(alt)
            elif w["pos"] == "verb" and row and row[3] and " " not in key:
                f = fold(row[3])
                if f != key:
                    alt.append(f)
                    stems += 1
            if alt:
                w["alt"] = alt
            else:
                w.pop("alt", None)
        stat("ar_display", {"words_without_pron": sorted(no_pron),
                            "pron_coverage": f"{len(words) - len(no_pron)}/{len(words)}",
                            "nouns_with_broken_plural_alt": plural_alts, "verbs_with_present_alt": stems,
                            "verbs_carrying_a_preposition_compound": merged_twins})
        n_dialect = sum(1 for _, toks in _iter_tagged(ctx["tagged"]) if toks and toks[0][2] == "X" and
                        "Dialect=Yes" in toks[0][3])
        n_dialect_en = sum(1 for sid, toks in _iter_tagged(ctx["tagged"]) if toks and toks[0][2] == "X" and
                           "Dialect=Yes" in toks[0][3] and ctx["rows_by_sid"][sid][3])
        stat("ar_msa_filter", {"tatoeba_sentences_dropped_as_dialect": n_dialect,
                               "of_them_with_english": n_dialect_en})

    def _voc_pron(self, key, kpos):
        """A romanisation built from a vocalised spelling when kaikki gives none:
        the headword of any row of the key (a verbal noun's قِيَام; the word's
        POS first), else CAMeL's diacritisation of the word in isolation
        (بِالطَّبْعِ, فَحَسْبُ)."""
        rows = self._info().get(key, [])
        for r in sorted(rows, key=lambda r: (r[0] not in kpos, not r[5])):
            if r[7] and re.search(f"[{MARKS}]", r[7]):
                p = romanise(r[7])
                if p:
                    return p
        rec = self._camel_raw([key]).get(key)
        if rec and rec.get("t"):
            p = romanise(" ".join(x[-1] or "" for x in rec["t"]))
            if p:
                return p
        return None

    def _pick_row(self, key, kpos, en):
        rows = [r for r in self._info().get(key, []) if r[5]]
        # no row of the word's POS: one of the same verb/non-verb kind (the prep
        # مثل takes the noun مِثْل's reading, not the verb مَثَلَ's maṯala)
        cands = [r for r in rows if r[0] in kpos] or \
            [r for r in rows if (r[0] == "verb") == ("verb" in kpos)] or rows
        if not cands:
            return None
        if en and len(cands) > 1:
            ours = set(re.findall(r"[a-z]{3,}", en.lower()))
            cands = sorted(cands, key=lambda r: (-len(ours & set(re.findall(r"[a-z]{3,}", (r[6] or "").lower()))),
                                                 r[1] is None))
        return cands[0]

    def check_word(self, w):
        if re.search(f"[{MARKS}]", w["w"]) and not w["w"].endswith("ـ"):
            return f"word {w['id']} {w['w']!r}: harakat or tatweel in w"
        if w.get("pos") == "noun" and w["w"].startswith("ال") and w["lemma"] not in DEFINITE_OK:
            return f"noun {w['id']} {w['w']!r}: definite article on a lemma"
        if w.get("pos") == "noun" and self._plural_only(w["lemma"]):
            return f"noun {w['id']} {w['w']!r}: a plural form as a lemma"
        if w.get("pos") == "verb" and " " not in w["lemma"] and w["lemma"] not in FIXED_KEYS_BY_LEMMA.get("VERB", ()) \
                and not self._has(w["lemma"], ("verb",)):
            return f"verb {w['id']} {w['w']!r}: not a dictionary verb lemma (3sg masc perfect)"
        return None

    def _plural_only(self, lemma):
        rows = self._info().get(lemma, [])
        nouns = [r for r in rows if r[0] == "noun"]
        # (a verbal noun kaikki also spells as a plural is a word: سَرِقَة "theft", سَرَقَة "thieves")
        return bool(nouns) and not any(r[5] for r in nouns) and any("plural of" in (r[6] or "") for r in nouns) and \
            not any((r[6] or "").startswith("verbal noun of") for r in nouns)

    # ---- sentences --------------------------------------------------------------------
    def pack_json_extra(self):
        return {"spaced": True, "compounds": [], "rtl": True, "langTag": "ar",
                "fontFamily": "\"Noto Naskh Arabic\", serif", "fonts": ["Noto Naskh Arabic:wght@400;700"],
                "lineHeight": 1.8}

    # ---- QA scans ------------------------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(d for d, _, _ in DAYS), "months": " ".join(m for m, _ in MONTHS),
        "seasons": " ".join(x for x, _ in SEASONS), "num": " ".join(n for n, _ in NUMBERS if " " not in n),
        "col": " ".join(c for c, _ in COLOURS),
        "core": " ".join([p for p, _ in PRONOUNS] + [q for q, _, _ in QUESTION] + [p for p, _ in PREPS] +
                         [c for c, _, _ in CONJS] + [p for p, _, _ in PARTS] +
                         [g for g, _, _ in GREETINGS if " " not in g]),
    }
    qa_foreign_letters_re = r"[a-z]"
    qa_proper_re = r"\b(Egypt|Cairo|Arabia|Saudi|Syria|Iraq|Morocco|Islam|Muhammad|Mohammed|God|Allah|Quran)\b"

    # ---- script primer ------------------------------------------------------------------
    # tts true: ar-SA / ar-EG voices ship with Apple, Windows and Google TTS
    # (unverified on the user's phone; see TODO.md). say = letter + fatha.
    script = {"stages": [{"key": "abjad", "label": "الأبجدية"}],
              "setsPerSession": 2, "mastered": 3, "tts": True,
              "learnKinds": ["symSound", "formFind"],
              "reviewKinds": ["symSound", "soundSym", "formMatch", "formFind", "wordRead"],
              "testKinds": {"symSound": 35, "soundSym": 20, "formMatch": 20, "wordRead": 25}}

    def script_units(self):
        out = []
        for st, group, slug, t, name, roman, alt, confuse, joins, note in AR_SCRIPT:
            out.append({"id": "ar-" + slug, "st": "abjad", "set": st, "group": group, "t": t,
                        "name": name, "roman": roman, "alt": alt, "note": note,
                        "confuse": ["ar-" + c for c in confuse], "joins": joins})
        return out

    def script_notes(self):
        return AR_SCRIPT_NOTES

    def script_tokens(self, text):
        toks = []
        for c in text:
            if c in AR_IGNORE:
                continue
            if c in AR_LETTERS:
                toks.append(("ar-" + AR_LETTERS[c], True, len(toks)))
            else:
                return None
        return toks

    def script_ex_roman(self, word, text, toks):
        return word.get("pron")

    def script_say(self, unit):
        """Carrier (docs/SCRIPT_PRIMER.md ss5): the letter with fatha (بَ); the
        long-vowel letters and alef forms bare; إ with kasra (إِ)."""
        g = unit["t"]
        if g == "إ":
            return g + "\u0650"        # hamza below carries i: إِ, not إَ
        return g if g in "اويىآ" else g + "\u064e"


DOUBLE_FINAL = {"stop", "sit", "run", "get", "put", "cut", "swim", "shop", "plan", "hit", "set", "let", "win",
                "begin", "forget", "admit", "occur", "prefer", "refer", "drop", "rob", "hug", "dig", "beg", "chat",
                "skip", "step", "trap", "grab", "nod", "rub", "spin", "split", "permit", "commit", "control", "fit",
                "quit", "ban", "tap", "wrap", "slip", "shut", "bet", "jog", "chop", "pat", "sip", "stir", "strip"}


def _gerund(gloss):
    """"to speak, to talk; ..." -> "speaking, talking" (the first sense's to-verbs)."""
    first = re.split(r"\s*;\s*", gloss)[0]
    out = []
    for part in re.split(r"\s*,\s*", first):
        m = re.match(r"^to (\w+)(.*)$", part.strip())
        if not m:
            continue
        v, rest = m.group(1), m.group(2)
        if v == "be":
            g = "being"
        elif v.endswith("ie"):
            g = v[:-2] + "ying"
        elif v.endswith("e") and not v.endswith(("ee", "ye", "oe")):
            g = v[:-1] + "ing"
        elif v in DOUBLE_FINAL:
            g = v + v[-1] + "ing"
        else:
            g = v + "ing"
        out.append(g + rest)
        if len(out) == 2:
            break
    return ", ".join(out) or None


IRREG = {"feel": "felt", "find": "found", "get": "got gotten", "take": "took taken", "think": "thought",
         "begin": "began begun", "meet": "met", "stand": "stood", "give": "gave given", "make": "made",
         "leave": "left", "run": "ran", "keep": "kept", "fall": "fell fallen", "catch": "caught", "become": "became",
         "hear": "heard", "speak": "spoke spoken", "tell": "told", "say": "said", "see": "saw seen",
         "come": "came", "go": "went gone goes", "lose": "lost", "win": "won", "pay": "paid", "hold": "held",
         "bring": "brought", "buy": "bought", "fight": "fought", "choose": "chose chosen", "know": "knew known",
         "do": "did done does", "put": "put", "rely": "relied", "deal": "dealt",
         "sell": "sold", "send": "sent", "spend": "spent", "build": "built", "lend": "lent", "sleep": "slept",
         "teach": "taught", "seek": "sought", "fly": "flew flown flies", "grow": "grew grown", "throw": "threw thrown",
         "draw": "drew drawn", "blow": "blew blown", "wear": "wore worn", "tear": "tore torn", "swear": "swore sworn",
         "bear": "bore born borne", "steal": "stole stolen", "break": "broke broken", "wake": "woke woken",
         "write": "wrote written", "ride": "rode ridden", "rise": "rose risen", "drive": "drove driven",
         "bite": "bit bitten", "hide": "hid hidden", "eat": "ate eaten", "forget": "forgot forgotten",
         "sit": "sat", "shoot": "shot", "lead": "led", "feed": "fed", "flee": "fled", "hang": "hung",
         "dig": "dug", "stick": "stuck", "strike": "struck", "swim": "swam swum", "sing": "sang sung",
         "drink": "drank drunk", "ring": "rang rung", "sink": "sank sunk", "shake": "shook shaken",
         "forgive": "forgave forgiven", "lie": "lay lain lied", "lay": "laid", "understand": "understood",
         "mean": "meant", "burn": "burnt", "learn": "learnt", "dream": "dreamt", "light": "lit",
         "have": "had has", "be": "was were been is are am", "bind": "bound", "freeze": "froze frozen",
         "show": "shown", "shine": "shone", "forbid": "forbade forbidden", "bleed": "bled", "kneel": "knelt",
         "sweep": "swept", "swing": "swung", "wind": "wound", "overcome": "overcame", "arise": "arose arisen",
         "die": "dying died", "child": "children", "man": "men", "woman": "women", "person": "people",
         "foot": "feet", "tooth": "teeth", "mouse": "mice", "good": "better best", "bad": "worse worst",
         "many": "more most", "much": "more most", "little": "less least"}
# light English words too common to show a rival reading ("go" is no evidence
# for مرّ "to go by" against مرة "time"; "ahead" none for قُدُمًا against تقدم)
RIVAL_WEAK_EN = {"go", "goes", "went", "gone", "get", "got", "come", "came", "ahead", "back", "way", "more",
                 "most", "one", "time", "like", "just", "off", "all", "much", "very", "thing", "things", "well"}
# noun/verb/adjective families a gloss and a translation share (موت "death": "I'd rather die")
EN_FAMILY = {"death": "die dies died dying dead", "birth": "born", "life": "live lives lived living alive",
             "success": "succeed succeeded successful", "choice": "choose chose chosen", "loss": "lose lost",
             "sale": "sell sold", "thought": "think thinks", "knowledge": "know knew known", "belief": "believe",
             "decision": "decide decided", "arrival": "arrive arrived", "departure": "leave left depart",
             "marriage": "marry married", "entry": "enter entered", "exit": "leave left", "sleep": "asleep",
             "health": "healthy", "anger": "angry", "hunger": "hungry", "fear": "afraid scared",
             "happiness": "happy", "sadness": "sad", "beauty": "beautiful", "strength": "strong",
             "height": "tall high", "length": "long", "width": "wide", "fly": "flight", "speech": "speak",
             "journey": "travel trip", "help": "helpful", "use": "useful", "wait": "waiting",
             "remain": "left", "college": "university", "university": "college", "assistance": "help"}
for _b, _fs in EN_FAMILY.items():
    IRREG[_b] = (IRREG.get(_b, "") + " " + _fs).strip()
IRREG_BASE = {}
for _b, _fs in IRREG.items():
    for _f in _fs.split():
        IRREG_BASE.setdefault(_f, set()).add(_b)


def _en_stems(w):
    """Base forms an English word may be an inflection of (sold: sell; tries,
    tried: try; working, worked, works: work; hoping: hope; stopped: stop;
    boxes: box; children: child)."""
    out = {w}
    out |= IRREG_BASE.get(w, set())
    if w.endswith(("ss", "us", "is")) or w == "news":
        return out
    for suf in ("ies", "ied"):
        if w.endswith(suf) and len(w) > 4:
            out.add(w[:-3] + "y")
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            b = w[: len(w) - len(suf)]
            out.update({b, b + "e"})
            if len(b) > 2 and b[-1] == b[-2]:
                out.add(b[:-1])             # stopped, stopping: stop
            break
    return out


EN_STOP = {"to", "the", "for", "about", "with", "from", "into", "doing", "someone", "something", "one", "at",
           "in", "on", "of", "up", "out", "a", "an", "be", "and", "or", "by", "away", "down", "over", "oneself"}


EN_NOT_NAME = set("""January February March April May June July August September October November December
Monday Tuesday Wednesday Thursday Friday Saturday Sunday Ramadan Islam Muslims Muslim Arab Arabs Arabic Quran
Latin Halloween Olympic Christmas Berber Kabyle Kabyles Esperanto Internet French Turkmen Romans Sahara Puffins Barbary""".split())
_AR_SKEL = str.maketrans({"ب": "b", "ت": "t", "ط": "t", "ث": "t", "ج": "j", "ح": "h", "ه": "h", "ة": "h",
                          "خ": "k", "د": "d", "ض": "d", "ذ": "z", "ظ": "z", "ز": "z", "ر": "r", "س": "s",
                          "ص": "s", "ش": "s", "غ": "g", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m",
                          "ن": "n", "و": "", "ي": "", "ى": "", "ا": "", "أ": "", "إ": "", "آ": "", "ع": "",
                          "ء": "", "ئ": "", "ؤ": "", "ـ": ""})
_EN_SKEL = [("ph", "f"), ("th", "t"), ("sh", "s"), ("ch", "s"), ("kh", "k"), ("ck", "k"), ("gh", "g"), ("x", "ks"),
            ("q", "k"), ("c", "k"), ("p", "b"), ("v", "f"), ("g", "j"), ("w", ""), ("y", "")]


def _skel_ar(s):
    return re.sub(r"(.)\1+", r"\1", s.translate(_AR_SKEL))


def _skel_en(s):
    s = s.lower()
    for a, b in _EN_SKEL:
        s = s.replace(a, b)
    s = re.sub("[aeiouh]", "", s[1:]) if s[:1] in "aeiou" else s[:1] + re.sub("[aeiouh]", "", s[1:])
    return re.sub(r"(.)\1+", r"\1", s.replace("j", "j")).replace("g", "j")


def _translit_ok(ar, en, ratio=0.66):
    """A crude consonant-skeleton match of an Arabic spelling and a Latin name
    (هاري Harry, بول Paul, جيم Jim; not العاصمة Algiers)."""
    import difflib
    a, e = _skel_ar(ar).replace("g", "j"), _skel_en(en)
    a = a.lstrip("h") if not e.startswith("h") else a
    return bool(a) and bool(e) and difflib.SequenceMatcher(None, a, e).ratio() >= ratio


def _en_supports_strict(gloss, words):
    """_en_supports for rival readings: whole words and their inflections only
    (no prefix match: "assistant" is not "assistance"), no light verbs or
    fragments ("to have intercourse" is not carried by "has"; "one's" by "'s")."""
    stems = None
    for g in set(re.findall(r"[a-z]+", gloss.lower())) - EN_STOP - RIVAL_WEAK_EN - {"have", "has", "had", "is", "are"}:
        if len(g) < 2:
            continue
        if (set(IRREG.get(g, "").split()) | {g}) & words:
            return True
        if stems is None:
            stems = set().union(*(_en_stems(x) for x in words)) if words else set()
        if g in stems:
            return True
    return False


def _en_supports(gloss, words):
    """Whether an English translation (a word set) carries a content word of a
    compound's gloss, inflected (look: looked/looking; feel: felt)."""
    stems = None
    for g in set(re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", "", gloss.lower()))) - EN_STOP:
        forms = set(IRREG.get(g, "").split()) | {g}
        stem = g[:-1] if len(g) > 4 and g[-1] in "eyt" else g
        if forms & words or (len(stem) >= 3 and any(w.startswith(stem) for w in words)):
            return True
        if stems is None:
            stems = set().union(*(_en_stems(w) for w in words)) if words else set()
        if len(g) >= 3 and g in stems:
            return True                     # sold: sell; tried: try; boxes: box
    return False


def _vnorm(v):
    """A vocalised headword for comparison: no sukun, no final short vowel or
    tanwin, alef wasla and dagger alef plain."""
    import unicodedata
    v = unicodedata.normalize("NFD", v or "")     # shadda/kasra order differs between sources
    v = v.replace("ْ", "").replace("ٱ", "ا").replace("ٰ", "").replace("ـ", "")
    return re.sub("[ًٌٍَُِ]+$", "", v)


def _clitic_stems(s):
    """Headword candidates of an lfolded surface: proclitics (و ف ب ل ك ال),
    an object/possessive suffix, an imperfect prefix; ة is ه after lfold."""
    out = {s}
    for p in ("وال", "فال", "بال", "كال", "لل", "ال", "و", "ف", "ب", "ل", "ك"):
        if s.startswith(p) and len(s) - len(p) >= 2:
            out.add(s[len(p):])
    for x in list(out):
        for e in ENC_SUFFIX + ("ي",):
            if x.endswith(e) and len(x) - len(e) >= 2:
                out.add(x[:-len(e)])
    for x in list(out):
        if x[:1] in "يتنا" and len(x) >= 3:
            out.add(x[1:])
        if x.endswith("ت") and len(x) >= 3:
            out.add(x[:-1] + "ه")
    return out


def _strip_wa(s):
    return s[1:] if s[:1] in "وف" and len(s) > 2 and s[1:] in PHRASE_INDEX else s


BOUND_PRC = {"ب": "bi_prep", "ل": "li_prep", "ك": "ka_prep"}


def _part_ok(part, s, lem, feats, last):
    """One non-initial word of a fixed phrase against a token (folded surface,
    lemma, features). A bound preposition part (لـ) matches its proclitic or
    the preposition with a pronoun (له); a last word may carry a pronoun suffix."""
    if part.endswith("ـ"):
        p = part[:-1]
        return feats.get("Prc1") == BOUND_PRC.get(p) or lem == p
    if s == lfold(part):
        return True
    return last and feats.get("Enc0") and lem == fold(part)


def _sound_plural(sing, pl):
    s = sing[:-1] if sing.endswith("ة") else sing
    return pl in (s + "ات", sing + "ون", sing + "ين", s + "ات")


def _iter_tagged(path):
    from ..core.tag import iter_tagged
    return iter_tagged(path)


ROM_CONS = {"ب": "b", "ت": "t", "ث": "ṯ", "ج": "j", "ح": "ḥ", "خ": "ḫ", "د": "d", "ذ": "ḏ", "ر": "r", "ز": "z",
            "س": "s", "ش": "š", "ص": "ṣ", "ض": "ḍ", "ط": "ṭ", "ظ": "ẓ", "ع": "ʿ", "غ": "ġ", "ف": "f", "ق": "q",
            "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y", "ء": "ʾ", "أ": "ʾ", "إ": "ʾ",
            "ؤ": "ʾ", "ئ": "ʾ", "ة": "t"}
SUN_LETTERS = set("تثدذرزسشصضطظلن")
ROM_VOW = {"\u064e": "a", "\u064f": "u", "\u0650": "i", "\u064b": "an", "\u064c": "un", "\u064d": "in"}


def romanise(voc):
    """A fully vocalised Arabic phrase -> DIN 31635 (the pack's pron style):
    long vowels ā ī ū, shadda doubles, the article al- (sun letters
    assimilated: aš-šams, bi-ṭ-ṭabʿ), final short vowels and -un/-in dropped,
    adverbial -an kept (ġāliban). None when a consonant carries no mark
    before another consonant (an unvocalised input)."""
    import unicodedata
    marks = set(ROM_VOW) | {"\u0651", "\u0652", "\u0670"}

    def take(w, i):
        """The marks after position i-1: (shadda?, vowel, next index)."""
        sh, v = False, None
        while i < len(w) and w[i] in marks:
            if w[i] == "\u0651":
                sh = True
            elif w[i] == "\u0670":
                v = "ā"
            elif w[i] in ROM_VOW:
                v = ROM_VOW[w[i]]
            elif w[i] == "\u0652":
                v = v or ""
            i += 1
        return sh, v, i
    words = []
    for w in unicodedata.normalize("NFC", voc or "").split():
        w = w.replace("ٱ", "ا").replace("ـ", "").replace("ا\u064b", "\u064bا")   # باً = بًا
        pre = ""
        m = re.match("([بلكوف])([\u064e\u0650]?)(?=ال)", w)
        if m and len(w) > len(m.group(0)) + 3:
            pre = {"ب": "bi", "ل": "li", "ك": "ka", "و": "wa", "ف": "fa"}[m.group(1)] + "-"
            w = w[len(m.group(0)):]
        out, i, n = [], 0, len(w)
        if w.startswith("ال") and n > 3:
            sh, _, _ = take(w, 3)
            j = 2 + (w[2:3] == "\u0652")
            sun = w[j:j + 1]
            sh = sun in SUN_LETTERS
            out.append(("" if pre else "a") + (ROM_CONS[sun] if sh else "l") + "-")
            i = j
            single = j if sh else -1            # the sun letter's shadda is the article's l
        else:
            single = -1
        while i < n:
            c = w[i]
            if c == "ا":
                if out and out[-1].endswith("a"):
                    out[-1] = out[-1][:-1] + "ā"
                elif out and out[-1].endswith("an"):
                    pass                                  # ـًا: the tanwin's seat
                elif i == 0:
                    _, v, i2 = take(w, 1)
                    out.append(v or "a")                  # hamzat al-wasl: اِنْتِظَار
                    i = i2 - 1
                i += 1
                continue
            if c == "آ":
                out.append("ʾā")
                i += 1
                continue
            if c == "ى":
                if out and out[-1].endswith("a"):
                    out[-1] = out[-1][:-1] + "ā"
                elif not (out and out[-1].endswith("an")):
                    out.append("ā")
                i += 1
                continue
            if c in "وي" and out and out[-1].endswith("u" if c == "و" else "i") and \
                    not (i + 1 < n and w[i + 1] in marks and w[i + 1] != "\u0652"):
                out[-1] = out[-1][:-1] + ("ū" if c == "و" else "ī")
                _, _, i = take(w, i + 1)
                continue
            if c in marks:
                i += 1
                continue
            if c not in ROM_CONS:
                return None
            i0 = i
            sh, v, i = take(w, i + 1)
            if c == "ة":
                out.append(("t" + v if v == "an" else "") + "\x00")   # -a written by the fatha before it
                continue
            if v is None and i == n - 1 and w[i] == "ا" and len(out) >= 2:
                v = "an"                                  # غالبا: a final unmarked alif seats adverbial -an
            elif v is None and i < n and w[i] in "اى":
                v = "a"                                   # an unmarked consonant before alif: ā
            if v is None and i < n and w[i] not in "اوىيآ":
                return None                               # an unvocalised consonant cluster
            out.append(ROM_CONS[c] * (2 if sh and i0 != single else 1) + (v or ""))
        r = "".join(out)
        if not r.endswith(("an", "\x00")):
            r = re.sub(r"(?<=[^aāiīuū\s-])(?:un|in|[aiu])$", "", r)
        words.append(pre + r.replace("\x00", ""))
    return " ".join(words) if words else None


def normalize_pron(p):
    """Wiktionary romanisation -> the pack's DIN 31635 style: ʾ hamza, ʿ ʿayn,
    ḫ, ġ; a word-initial hamza is not written."""
    if not p:
        return p
    p = p.strip()
    for a, b in (("ʔ", "ʾ"), ("ʕ", "ʿ"), ("ḵ", "ḫ"), ("ḡ", "ġ"), ("’", "ʾ"), ("'", "ʾ")):
        p = p.replace(a, b)
    p = re.sub(r"(^|[\s-])ʾ", r"\1", p)
    return p


POS_KPOS = {"noun": ("noun",), "verb": ("verb",), "adj": ("adj",), "adv": ("adv",), "pron": ("pron",),
            "prep": ("prep",), "conj": ("conj",), "num": ("num", "noun"), "intj": ("intj",), "det": ("noun", "det"),
            "part": ("particle",)}

# fixed-gloss words the dictionary has only as form-of lines (هؤلاء "plural of
# هذا"): the tagger's lemma stands (post_resolve)
for (_k, _g) in Arabic.fixed_gloss:
    FIXED_KEYS_BY_LEMMA.setdefault(_g, set()).add(_k)
    FIXED_GROUPS.setdefault(_k, set()).add(_g)

SPEC = Arabic
