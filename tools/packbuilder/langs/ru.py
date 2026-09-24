"""Russian (ru): everything Russian-specific in the pack pipeline.

Spelling: ё is written inconsistently (subtitles "еще" 232k vs "ещё" 202k,
Tatoeba mixed, spaCy's Nerus training data mostly е), so every matching side
is folded ё -> е and stress marks are stripped (fold). The displayed word
restores kaikki's spelling (ещё, зелёный) in finalize_words, which also adds
the stressed form as pron (соба́ка), the noun gender and the verb aspect.

Nouns show no article; gender goes in the gloss suffix " (m)/(f)/(n)".
Aspect pairs (делать / сделать), motion-verb pairs (идти / ходить) and -ся
verbs are separate lemmas, each gloss marked "(impf.)" / "(pf.)".

The A1 core list and gloss overrides live in the russian repo (tools/).
"""
import gzip
import hashlib
import json
import re

from .base import LanguageSpec, SENSITIVE_EN, SENSITIVE_GLOSS_EN, TATOEBA_ENG, TATOEBA_LINKS, TATOEBA_AUDIO, DEFAULT_GROUP_KPOS

STRESS = "\u0301\u0300"
VOWELS = "аеёиоуыэюя"

DAYS = "понедельник вторник среда четверг пятница суббота воскресенье".split()
MONTHS = "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь".split()
SEASONS = "весна лето осень зима".split()
NUMBERS = ("ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать "
           "тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать "
           "двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто "
           "тысяча").split()
COLOURS = ("красный синий голубой зелёный жёлтый чёрный белый серый коричневый розовый оранжевый "
           "фиолетовый").split()
GREETINGS = "да нет привет здравствуйте спасибо пожалуйста извините простите".split()
ORDINALS = "первый второй третий четвёртый пятый".split()
CONJS = "и а но или".split()
PREPS = "в на с у о к по из за от до".split()
DEATH_LEMMAS = {"умереть", "умирать", "смерть", "помереть", "помирать", "погибнуть", "погибать"}
PROFANE_STEMS = ("хуй", "хуе", "хуё", "хуя", "хуи", "пизд", "ебат", "ебан", "ебал", "ебну", "ёбан", "ебу",
                 "заеб", "уеб", "выеб", "бляд", "блят", "мудак", "мудил", "залуп", "гандон", "пидор",
                 "пидар", "шлюх", "жоп", "говн", "дерьм")
PROFANITY = {"бля", "сука", "сучка", "сучара", "срать", "херня", "хер", "трахать", "трахнуть", "ублюдок"}


ONE_LETTER_WORDS = set("авикосуяж")
PURE_PREPS = {"в", "во", "на", "с", "со", "у", "о", "об", "обо", "к", "ко", "по", "из", "за", "от", "до", "для",
              "над", "под", "при", "без", "про", "через", "между", "перед", "среди", "ради"}
# forms of сам "self" (самом/самого/самой go to самый: "в самом деле", "с самого начала")
SAM_FORMS = {"сам", "сама", "само", "сами", "саму", "самому", "самим", "самих", "самими"}
# emphatic -то on a demonstrative (так-то, тот-то, вот-то) is the demonstrative itself
DEMONSTR = {"так", "тот", "та", "того", "тому", "те", "вот", "это", "там", "тут"}
HYPHEN_ANY_RE = re.compile(r"(?<![А-Яа-яЁё\u2010-])[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)+(?![А-Яа-яЁё\u2010-])")
INDEF_TAILS = ("то", "нибудь", "либо", "ка", "таки")
INDEF_PRON = {"кто", "кого", "кому", "кем", "ком", "что", "чего", "чему", "чем", "чём"}
INDEF_DET = {"какой", "какая", "какое", "какие", "какого", "какую", "каком", "каких", "какому", "какими",
             "какой", "чей", "чья", "чьё", "чьи", "чьего", "чью"}
INDEF_ADV = {"где", "куда", "когда", "как", "откуда", "почему", "зачем", "наконец", "опять", "всё", "все"}
HYPHEN_WORD_RE = re.compile(r"(?<=[А-Яа-яЁё])-(?=(?:то|нибудь|либо|таки)(?![А-Яа-яЁё]))|"
                            r"(?<=\b[Ии]з)-(?=(?:за|под)(?![А-Яа-яЁё]))|(?<=\b[Пп]о)-(?=[а-яё])")
# predicatives the tagger reads as short adjectives (нужно -> нужный)
PREDICATIVES = {"нужно", "можно", "надо", "нельзя", "жаль", "видно", "слышно"}
# irregular plural surfaces whose tagger/dictionary lemma is another word
SURFACE_LEMMA = {"цветы": "цветок", "цветами": "цветок", "цветам": "цветок", "цветах": "цветок",
                 "цветов": "цветок"}
# capitalised, these are Tatoeba's stock names or titles (Tom, Mrs), never the homographs
NAME_HOMOGRAPHS = {"том", "тома", "тому", "томом", "томе", "миссис", "мисс"}
POSSESSIVE_3P = {"его": "он", "ее": "она", "их": "они"}
ABBR_TAGS = {"abbreviation", "initialism", "acronym"}
LETTER_RE = re.compile(r"\bletter\b.*\b(alphabet|script)\b|name of the .*\bletter\b", re.I)


def fold(s):
    """ё -> е, stress marks stripped (both sides of every match)."""
    if not s:
        return s
    for m in STRESS:
        s = s.replace(m, "")
    return s.replace("ё", "е").replace("Ё", "Е")


def strip_stress(s):
    for m in STRESS:
        s = s.replace(m, "")
    return s


def n_vowels(s):
    return sum(1 for ch in s.lower() if ch in VOWELS)


class Russian(LanguageSpec):
    code = "ru"
    name_en = "Russian"
    pack_name = "Russian (A1–B1)"
    tts = "ru-RU"
    stt = "ru-RU"
    tatoeba_code = "rus"

    spacy_model = "ru_core_news_sm"
    tagger_attribution = {
        "source": "spaCy (MIT) + ru_core_news_sm 3.8.0 model (MIT, trained on Nerus) + pymorphy3 lemmatiser (MIT)",
        "licence": "MIT (model and lemmatiser)",
        "note": "Used at build time only; the pack ships no model files.",
    }

    subtitles_file = "ru_full.txt"
    kaikki_file = "kaikki_ru.jsonl.gz"
    sentences_file = "rus_detailed.tsv.bz2"
    kelly_file = "kelly_ru.json"
    sources = {
        "ru_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/ru/ru_full.txt",
        "kaikki_ru.jsonl.gz": "https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl.gz",
        "rus_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/rus/rus_sentences_detailed.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_LINKS[0]: TATOEBA_LINKS[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
        "kelly_ru.json": "https://raw.githubusercontent.com/kotoshu/frequency-list-kelly/main/data/ru.json",
    }
    versions = {"corpus": "c1", "tag": "t14", "lex": "l4"}

    typing = {"caseSensitive": False, "accents": "lenient", "strictFromLevel": None}
    show_pron = True
    audio_rank_bonus = 5.0        # native audio outweighs one A1 difficulty point
    bare_prefer_shared = True
    example_shows_word = True     # one example shows мочь / хотеть itself, not only могу / хочу

    word_re = re.compile(r"[А-Яа-яЁё]+")
    lex_word_re = re.compile(r"^[а-яё]+(?:-[а-яё]+)*$")
    # single letters only when they are words (п, е, ю are letter names/abbreviations)
    sub_token_re = re.compile(r"^(?:[авикосуяж]|[а-яё]{2,}(?:-[а-яё]+)*)$")
    form_colon_translation = True   # "female equivalent of друг: female friend" gives a sense
    refill_unexampled = True        # отряд, прокурор (no usable sentence) give way to the next word
    form_target_re = re.compile(r"\bof ([а-яё\u0301\u0300]+(?:-[а-яё\u0301\u0300]+)*)")
    # feminine nouns (подруга, учительница) stay separate lemmas: never matches
    fem_of_re = re.compile(r"(?!)")

    noun_head_template = None
    group_kpos = dict(DEFAULT_GROUP_KPOS, **{
        # predicatives (надо, можно, нужно, жаль) are Wiktionary "adj" [predicative]
        "ADV": ["adv", "adj", "conj", "prep", "particle"],
        "PART": ["particle", "adv", "conj", "intj"],
        # самый, сам, весь are Wiktionary "pron"
        "ADJ": ["adj", "det", "num", "pron"],
        "INTJ": ["intj", "particle"],
    })

    morph_keep = ("Gender", "Number", "Case", "Aspect", "Tense", "Mood", "VerbForm", "Person")
    numeral_verb_rule = False
    # Земля, Бог, Советский Союз, Интернет: common words capitalised in names; the
    # tagger's PROPN share decides in the pool. Capitalised mid-sentence tokens
    # are still never linked (caps_mark_names stays on).
    caps_proper_pool = False
    finite_verb_lemma = True     # "есть" (is, Fin) -> быть; "есть" (to eat, Inf) stays
    rare_zipf = 1.0              # смочь (2.1) is rarer than its form смог: keep the tagger's verb
    # plural-only nouns; люди is its own lemma (pymorphy gives человек)
    pluralia_tantum = {"деньги", "брюки", "очки", "ножницы", "сутки", "каникулы", "джинсы", "ворота",
                       "люди", "духи", "сливки", "шахматы", "обои", "похороны", "выборы", "перила"}
    verb_endings = ("ть", "ти", "чь", "ться", "тись", "чься")
    function_verbs = {"быть"}

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS + SEASONS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS + ORDINALS] + [(w, "INTJ") for w in GREETINGS] +
                     [("до свидания", "PHRASE")] + [(w, "CONJ") for w in CONJS] +
                     [(w, "ADP") for w in PREPS])
    allowed_num = set(NUMBERS)
    # closed-class items whose Wiktionary entry is form-of only (извините) or
    # misread as form-of ("coffee (in the form of a beverage)")
    fixed_gloss = {("до свидания", "PHRASE"): "goodbye", ("извините", "INTJ"): "excuse me, sorry",
                   ("простите", "INTJ"): "sorry, excuse me, forgive me", ("ничего", "PRON"): "nothing; never mind",
                   ("кофе", "NOUN"): "coffee"}
    multiword = {"до свидания": ("до", "свидания")}
    # ничего links as its own word ("nothing"; "never mind"), not the rare nominative ничто
    # emphatic -то on a demonstrative is the demonstrative (Wiktionary lists так-то separately)
    closed_surfaces = {"ничего": ("ничего", "PRON"), "так-то": ("так", "ADV"), "вот-то": ("вот", "PART"),
                       "то-то": ("то", "PRON"),
                       **{f"{d}-то": ("тот", "DET") for d in ("тот", "та", "того", "тому", "тем", "том", "той",
                                                              "те", "тех", "теми", "ту")}}
    fixed_pron = {"до свидания": "до свида́ния", "водитель": "води́тель"}
    # colloquial spelling of что: its tokens link to что
    # colloquial что; здравствовать only as the greeting здравствуйте (tagged VERB)
    # минуту ("jiffy") is минута's accusative; ага is an interjection tagged NOUN
    drop_keys = {("че", "PRON"): ("что", "PRON"), ("здравствовать", "VERB"): ("здравствуйте", "INTJ"),
                 ("минуту", "NOUN"): ("минута", "NOUN"), ("ага", "NOUN"): None}
    profane_stems = PROFANE_STEMS
    profanity = PROFANITY
    bad_text_re = re.compile(r"(?<![а-яё])(?:(?:" + "|".join(PROFANE_STEMS) + r")[а-яё]*|(?:" +
                             "|".join(sorted(PROFANITY)) + r"))(?![а-яё])", re.I)

    # sensitive topics kept out of A1/A2 sentences (Russian text or English translation)
    sensitive_re = re.compile(
        r"(?<![а-яёa-z])(секс\w*|сексуальн\w*|самоубийств\w*|покончи\w* с собой|изнасил\w*|насилова\w*|"
        r"порн\w*|голы[йехм]\w*|гола[яю]|обнаж\w*|проститут\w*|презерватив\w*|оргазм\w*|"
        # threats/violence, dying/death wishes, weapons (A1/A2 only; the top level keeps them)
        r"уби[тлвй]\w*|убь\w*|убей\w*|убийств\w*|убийц\w*|застрел\w*|пристрел\w*|труп\w*|мёртв\w*|мертв\w*|"
        r"зареж\w*|зарезал\w*|задуш\w*|сдох\w*|сдыха\w*|умри|умрите|"
        r"оружи\w*|пистолет\w*|ружь\w*|винтовк\w*|(?:вы|за|при|под|по|от|пере|на)?стрел(?!к)\w*|насили\w*|"
        r"kill\w*|murder\w*|shot|weapon\w*|guns?|pistol\w*|rifle\w*|"
        + SENSITIVE_EN + r")(?![а-яёa-z])", re.I)
    # removed at every level: rape, sexual abuse, child abuse
    drop_all_levels = re.compile(
        r"(?<![а-яёa-z])(изнасил\w*|насилова\w*|насилуе\w*|растл\w*|педофил\w*|"
        r"rape[ds]?|raping|rapist\w*|molest\w*|child abuse|sexual(?:ly)? abuse\w*|paedophil\w*|pedophil\w*)(?![а-яёa-z])",
        re.I)
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)
    # lex: diminutive / female-equivalent senses are words of their own, not
    # inflections (столик is not a form of стол, принцесса not of принц)
    derived_form_tags = {"diminutive", "augmentative", "pejorative", "endearing",
                         "female equivalent", "male equivalent"}

    report_title = "Russian A1-B1 pack (corpus-tagged)"
    forced_description = ("days, months, seasons, numbers 0-20 + tens + сто/тысяча, colours, greetings, "
                          "и/а/но/или, core prepositions, A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000"

    # ---- spelling ------------------------------------------------------------
    def fold(self, s):
        return fold(s)

    def fallback_lemma(self, surface, lemma):
        # simplemma expands abbreviations (мм -> миллиметр, км -> километр,
        # тыс -> тысяча): a short surface that is not a prefix of its lemma
        if len(surface) <= 4 and len(lemma) > len(surface) + 2 and not lemma.startswith(surface):
            return surface
        return lemma

    def tag_text(self, text):
        # spaCy splits "кто-то", "из-за", "по-русски" at the hyphen and tags
        # the parts (то "that"); U+2010 keeps them one token (fix_token
        # restores the ASCII hyphen of the Wiktionary headword)
        text = HYPHEN_WORD_RE.sub("\u2010", fold(text))
        # any other hyphenated word Wiktionary lists (кое-что, во-первых, чуть-чуть)
        return HYPHEN_ANY_RE.sub(lambda m: m.group(0).replace("-", "\u2010")
                                 if m.group(0).lower() in self._hyphen_heads() else m.group(0), text)

    def _hyphen_heads(self):
        if not hasattr(self, "_hyph"):
            from ..core.util import Env
            from ..core.lex import stage_lex
            self._hyph = {k for k in stage_lex(Env(self))["entries"] if "-" in k}
        return self._hyph

    # spaCy/pymorphy lemmas the pack treats differently
    LEMMA_FIX = {"деньга": "деньги"}

    def fix_token(self, tok):
        text, lemma, upos, ms = tok
        text, lemma = fold(text), fold(lemma.lower())
        if "\u2010" in text:
            text = text.replace("\u2010", "-")
            low = text.lower()
            head, tail = low.split("-", 1)
            if head == "кое":
                upos = "PRON" if tail in INDEF_PRON else "DET" if tail in INDEF_DET else "ADV"
            lemma = low
            if head in ("из", "по") and tail in ("за", "под", "над"):
                upos = "ADP"                       # из-за, из-под
            elif head == "по":
                upos = "ADV"                       # по-русски, по-моему
            elif tail == "то" and head in DEMONSTR:
                lemma = {"та": "тот", "того": "тот", "тому": "тот", "те": "тот"}.get(head, head)
            elif tail in INDEF_TAILS:
                upos = ("PRON" if head in INDEF_PRON else "DET" if head in INDEF_DET else
                        "ADV" if head in INDEF_ADV else upos)
        if lemma in ("бы", "б", "ж") and upos in ("AUX", "VERB", "ADV", "NOUN", "PART"):
            lemma, upos = ("же" if lemma == "ж" else "бы"), "PART"   # spaCy tags бы AUX
        if len(text) == 1 and text.isalpha() and text.lower() not in ONE_LETTER_WORDS:
            upos = "X"                             # "п." / "е" / "Ю": letters, abbreviations
        if lemma in PURE_PREPS and upos in ("ADV", "NOUN", "PROPN", "ADJ"):
            upos = "ADP"                           # "по" tagged ADV 44% of the time
        if lemma == "человек" and text.lower().startswith("люд"):
            lemma = "люди"                         # людей, людям: люди is its own lemma
        low = text.lower()
        if low in POSSESSIVE_3P:
            # spaCy/pymorphy swap these: object "его" (him) gets lemma его and
            # possessive "его" (his) gets он. PRON = the personal pronoun's
            # form, DET = the invariable possessive.
            lemma = POSSESSIVE_3P[low] if upos == "PRON" else low
        if (lemma == "все" or text.lower() in ("всех", "всем", "всеми")) and "Number=Plur" in ms:
            lemma, upos = "весь", "DET"            # все/всех (everyone, all) is весь; всё (everything) stays
        if upos in ("ADJ", "DET") and (lemma == "сам" or low in SAM_FORMS):
            lemma, upos = "сам", "DET"             # сам (self) is a pronoun; spaCy leaves сами/сама unlemmatised
        if upos == "ADV" and low.endswith(("о", "е")) and lemma.endswith(("ий", "ый", "ой")):
            lemma = low                            # далеко/поздно lemmatised to the adjective (далёкий)
        if upos == "ADJ" and lemma.endswith("о") and lemma != low:
            upos = "ADV"                           # comparatives lemmatised to the -о adverb (выше -> высоко)
        if upos in ("ADJ", "DET") and lemma in ("самое", "самая", "самые", "самой", "самого", "самом"):
            lemma = "самый"
        if low in PREDICATIVES and upos in ("ADJ", "ADV", "VERB", "NOUN"):
            lemma, upos = low, "ADV"               # нужно, можно, нельзя: predicatives, not нужный
        if low == "ничего" and upos in ("PRON", "DET", "NOUN"):
            lemma, upos = "ничего", "PRON"         # "nothing"; ничто is its rare nominative
        if low in SURFACE_LEMMA:
            lemma = SURFACE_LEMMA[low]             # цветы -> цветок (not цвет "colour")
        if text[:1].isupper() and low in NAME_HOMOGRAPHS:
            upos = "PROPN"                         # Том/Тома/Тому (Tom), Миссис: never the words том, то, мистер
        lemma = self.LEMMA_FIX.get(lemma, lemma)
        return [text, lemma, upos, ms]

    def marks_sentence(self, toks):
        # death as a death wish, threat or omen about the speaker/addressee
        # ("Я чувствую, что смерть уже на подходе", "Ты умрёшь") goes to the top
        # level; a neutral report ("Его отец умер в 1990") keeps its level
        death = [t for t in toks if t[1] in DEATH_LEMMAS]
        if not death:
            return False
        if any("Mood=Imp" in t[3] or "Person=First" in t[3] or "Person=Second" in t[3] or
               t[0].lower() in ("умереть", "умирать") for t in death):
            return True             # я умру / умри / лучше умереть
        return any(t[2] == "PRON" and ("Person=First" in t[3] or "Person=Second" in t[3]) for t in toks)

    def clean_sentence_text(self, t):
        return t.replace("\u0301", "")          # Tatoeba text with stress marks (pron keeps them)

    def surface_link_ok(self, tok):
        return not (tok[2] == "INTJ" and tok[0].lower() in set(PREPS) | set(CONJS) | set(PURE_PREPS))

    def post_resolve(self, toks, out):
        # an interjection homograph of a function word ("О нет!") links to no
        # word rather than to the preposition/conjunction
        fn = set(PREPS) | set(CONJS) | set(PURE_PREPS)
        return [None if t[2] == "INTJ" and r and (r[1] in ("ADP", "CCONJ", "SCONJ") or r[0] in fn) else r
                for t, r in zip(toks, out)]

    def fix_sentence(self, toks, row, doc):
        """Singular все/всем (DET or PRON) not followed by a noun/adjective is всё
        "everything"; before one it is весь ("всё время" = the whole time)."""
        # the original text keeps ё where the writer used it: всё is "everything"
        orig = re.findall(r"(?<![а-яё])вс[её](?![а-яё])", row[1].lower()) if row else []
        k = 0
        for i, t in enumerate(toks):
            low = t[0].lower()
            if low == "все" and k < len(orig):
                k += 1
                if orig[k - 1] == "всё":
                    nt = toks[i + 1] if i + 1 < len(toks) else ["", "", "PUNCT", ""]
                    nxt = nt[2]
                    if nt[2] == "ADJ" and nt[0].lower().endswith("о") and not nt[0].lower().endswith(("ое", "ее")):
                        nxt = "PRED"                # "Всё хорошо", "Всё возможно": short-form predicate
                    if nxt not in ("NOUN", "ADJ", "PROPN"):
                        t[1], t[2] = "все", "PRON"
                        continue
            if low == "о" and (i + 1 == len(toks) or toks[i + 1][2] in ("PUNCT", "INTJ", "PART") or
                               toks[i + 1][0].lower() in ("нет", "да", "боже", "господи")):
                t[1], t[2] = "о", "INTJ"           # "О нет!", "О, вижу": the interjection, not the preposition
                continue
            if low in ("все", "всем", "всего") and "Number=Sing" in t[3] and t[2] in ("DET", "PRON"):
                nxt = toks[i + 1][2] if i + 1 < len(toks) else "PUNCT"
                if nxt in ("NOUN", "ADJ", "PROPN"):
                    t[1], t[2] = "весь", "DET"
                else:
                    t[1], t[2] = "все", "PRON"
        return toks

    def extra_wordfreq(self, raw):
        """wordfreq splits кто-то/что-нибудь/из-за at the hyphen, so its top list
        never has them: take their (multi-token) zipf for the hyphenated
        frequency-list surfaces that Wiktionary lists as words."""
        from wordfreq import zipf_frequency
        from ..core.util import Env
        from ..core.lex import stage_lex
        heads = {k for k in stage_lex(Env(self))["entries"] if "-" in k}
        with open(self.repo / ".cache" / self.subtitles_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 20000:
                    break
                w = fold(line.split(" ")[0])
                if "-" in w and w in heads and w not in raw:
                    z = zipf_frequency(w, self.wordfreq_code)
                    if z > 0:
                        raw[w] = 10 ** z

    def bind_lexicon(self, lexicon):
        """Abbreviation pointers (п -> параграф, мм -> миллиметр) and letter
        names (е, ю) are not words: drop them from the lexicon."""
        # deverbal nouns (родитель, стоимость, получение) are tagged form-of +
        # noun-from-verb but are lemmas; "archaic" + "standard" (судья) marks
        # an archaic alternative form, not the senses
        from ..core.lexicon import header_tags
        deverbal = set()
        for s, ents in lexicon.E.items():
            for e in ents:
                for sn in e["s"]:
                    t = set(sn[2])
                    if "noun-from-verb" in t and sn[3] == "form" and not re.search(r"\bof\b", sn[0]):
                        sn[3] = ""
                        sn[2] = sorted(t - {"form-of"})
                        deverbal.add(s)
                    if "standard" in t:
                        sn[2] = sorted(set(sn[2]) - {"archaic", "obsolete", "dated"})
                e["ht"] = header_tags(e)
        for s, ents in lexicon.E.items():
            for e in ents:
                for sn in e["s"]:
                    if sn[3] == "form" and not re.search(r"\bof\b", sn[0]) and \
                            not re.search(r"\b(singular|plural|person|tense|form|participle|genitive|dative)\b", sn[0]):
                        sn[3] = ""                 # дедушка "grandfather": a translation tagged form-of (diminutive)
                        sn[2] = sorted(set(sn[2]) - {"form-of"})
                    elif e["p"] == "verb" and "imperative" in sn[2] and sn[3] == "":
                        sn[2] = sorted(set(sn[2]) | {"rare"})   # позволить "excuse me" (imperative use) ranks last
                e["ht"] = header_tags(e)
        for s, ents in lexicon.E.items():
            # "минуту"/"секунду" ("jiffy", Одну минуту!) are accusatives of минута/секунда
            # with an idiom sense: the token is the nominative's form
            if s.endswith(("у", "ю")) and any(x[1] == "noun" and x[2] == "form" for x in lexicon.F.get(s, [])):
                for e in ents:
                    if e["p"] == "noun" and any(sn[3] == "form" for sn in e["s"]):
                        e["s"] = [sn for sn in e["s"] if sn[3] == "form"]
        for s in [x for x in lexicon.E if len(x) >= 2 and not any(ch in VOWELS for ch in x)]:
            del lexicon.E[s]                       # мм, см, кг, тв: abbreviations, not words
            lexicon.F.pop(s, None)
        for s in deverbal:
            lexicon.F[s] = [x for x in lexicon.F.get(s, []) if x[1] != "noun"]
        for s in list(lexicon.F):
            keep = []
            for tgt, pos, kind in lexicon.F[s]:
                if kind == "alt":
                    alts = [set(sn[2]) for e in lexicon.E.get(s, []) if e["p"] == pos
                            for sn in e["s"] if sn[3] == "alt"]
                    if alts and all(t & ABBR_TAGS for t in alts):
                        continue
                keep.append([tgt, pos, kind])
            lexicon.F[s] = keep
        for s in list(lexicon.E):
            ents = [e for e in lexicon.E[s] if e["p"] != "character" and
                    not all(LETTER_RE.search(sn[0]) for sn in e["s"])]
            if ents:
                lexicon.E[s] = ents
            else:
                del lexicon.E[s]

    def load(self):
        super().load()
        self.gloss_overrides = {fold(k): v for k, v in self.gloss_overrides.items()}
        self.a1_core = {g: [fold(w) for w in ws] for g, ws in self.a1_core.items()}
        # closed sets first; an A1-core entry repeating one is dropped (first wins)
        self.forced = list(dict.fromkeys([(fold(w), g) for w, g in self.forced_closed] +
                                         [(w, g) for g, ws in self.a1_core.items() for w in ws]))
        return self

    # ---- nouns ---------------------------------------------------------------
    def gender_from_entry(self, d):
        """'m' / 'f' / 'n' / 'mf', with '-p' for plural-only, from the canonical
        form's tags (ru-noun+) or the head template's g= (head)."""
        tags = set()
        for f in d.get("forms", []):
            if "canonical" in (f.get("tags") or []):
                tags |= set(f["tags"])
        g = ""
        if tags & {"masculine", "feminine", "neuter"}:
            g = "".join(x for x, t in (("m", "masculine"), ("f", "feminine"), ("n", "neuter")) if t in tags)
        else:
            for ht in d.get("head_templates", []):
                spec = str(ht.get("args", {}).get("g", ""))
                if spec:
                    first = spec.split(",")[0].split("-")[0]
                    g = first if first in ("m", "f", "n") else ""
                    if "-p" in spec:
                        tags.add("plural")
                    break
        if not g:
            # monosyllables carry no canonical form: "дверь • (dverʹ) f inan (genitive ...)"
            for ht in d.get("head_templates", []):
                m = re.search(r"•\s*\([^)]*\)\s+([^()]*)", ht.get("expansion", ""))
                if m:
                    toks = m.group(1).split()
                    g = "".join(x for x in ("m", "f", "n") if x in toks)
                    if "pl" in toks:
                        tags.add("plural")
                    break
        if not g:
            return None
        if g in ("mf", "fm"):
            g = "mf"
        if "plural" in tags and d.get("pos") == "noun":
            g += "-p"
        return g

    def parse_gender(self, g):
        if not g:
            return None, False
        plural = g.endswith("-p")
        g = g[:-2] if plural else g
        if g not in ("m", "f", "n", "mf"):
            g = g[:1] or None                # кофе "m or n": the first (standard) gender
        return g, plural

    def default_gender(self, lemma):
        if lemma.endswith(("а", "я")):
            return "f"
        if lemma.endswith(("о", "е")):
            return "n"
        return "m"

    def noun_display(self, lemma, gender, plural, en):
        if plural:
            return lemma, f"{en} (pl.)"
        return lemma, f"{en} ({'m/f' if gender == 'mf' else gender})"

    # ---- sentences -----------------------------------------------------------
    def sentence_rank(self, toks, lv):
        """A1 prefers sentences whose nouns are Nom/Acc only; prepositional case
        after в/на is allowed. Gen/Dat/Ins (and other Prep uses) from A2."""
        if lv != "A1":
            return 0
        for i, (text, sl, upos, ms) in enumerate(toks):
            if upos not in ("NOUN", "PROPN"):
                continue
            m = re.search(r"Case=(\w+)", ms)
            case = m.group(1) if m else None
            if case in (None, "Nom", "Acc"):
                continue
            if case == "Loc":
                j = i - 1
                while j >= 0 and toks[j][2] in ("ADJ", "DET", "NUM"):
                    j -= 1
                if j >= 0 and toks[j][0].lower() in ("в", "во", "на"):
                    continue
            return 1 + self._a1_extra(toks)
        return self._a1_extra(toks) / 10

    def _a1_extra(self, toks):
        """Further A1 difficulty: participles/gerunds, relative который, and
        content lemmas outside the ~1500 most frequent (wordfreq zipf < 4.3)."""
        from wordfreq import zipf_frequency
        n = 0
        for text, sl, upos, ms in toks:
            if "VerbForm=Part" in ms or "VerbForm=Conv" in ms:
                n += 1
            if sl == "который":
                n += 1
            if upos in ("NOUN", "VERB", "ADJ", "ADV") and zipf_frequency(sl, "ru") < 4.3:
                n += 1
        return n

    # ---- finishing: display spelling, pron, aspect ------------------------------
    def _kaikki_info(self, env):
        """{folded headword: [[word, pos, canonical, aspect, gender, is_lemma, gloss]]}
        from the kaikki extract (cached in .cache/derived)."""
        from ..core.sources import kaikki_plain
        from ..core.util import file_sig
        src = kaikki_plain(env)
        sig = hashlib.sha1(f"ruinfo4|{file_sig(src)}".encode()).hexdigest()[:10]
        out = env.derived / f"ru_info_{sig}.json.gz"
        if out.exists():
            with gzip.open(out, "rt", encoding="utf-8") as f:
                return json.load(f)
        info = {}
        needle = '"lang_code": "ru"'
        with open(src, encoding="utf-8") as f:
            for line in f:
                if needle not in line:
                    continue
                d = json.loads(line)
                if d.get("lang_code") != "ru":
                    continue
                word, pos = d.get("word", ""), d.get("pos", "")
                if not word or word[:1].isupper():
                    continue
                canon = None
                ftags = set()
                for fm in d.get("forms", []):
                    if "canonical" in (fm.get("tags") or []):
                        canon = canon or fm.get("form")
                        ftags |= set(fm["tags"])
                aspect = None
                partners = []
                for ht in d.get("head_templates", []):
                    if ht.get("name") == "ru-verb":
                        aspect = str(ht.get("args", {}).get("2", "")) or None
                        for k2, v2 in sorted(ht.get("args", {}).items()):
                            if re.fullmatch(r"(pf|impf)\d*", k2):
                                partners += [fold(x.split("<")[0].strip()) for x in str(v2).split(",") if x.strip()]
                        if not canon:
                            canon = ht.get("args", {}).get("1")
                        break
                if aspect is None and pos == "verb":
                    if {"imperfective", "perfective"} <= ftags:
                        aspect = "both"
                    elif "imperfective" in ftags:
                        aspect = "impf"
                    elif "perfective" in ftags:
                        aspect = "pf"
                senses = d.get("senses", [])
                is_lemma = any(not (s.get("form_of") or s.get("alt_of") or
                                    set(s.get("tags", [])) & {"form-of", "alt-of", "misspelling"})
                               for s in senses)
                gloss = "; ".join((s.get("glosses") or [""])[-1] for s in senses[:4])
                info.setdefault(fold(word), []).append(
                    [word, pos, canon, aspect, self.gender_from_entry(d), is_lemma, gloss, partners])
        with gzip.GzipFile(out, "wb", mtime=0) as g:
            g.write(json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return info

    def shares_gloss(self, lemma, other):
        """Aspect partners (читать / прочитать) keep the same gloss."""
        if not hasattr(self, "_partners"):
            from ..core.util import Env
            self._partners = {}
            for key, rows in self._kaikki_info(Env(self)).items():
                for r in rows:
                    if r[1] == "verb" and r[5]:
                        for p in r[7]:
                            self._partners.setdefault(key, set()).add(p)
                            self._partners.setdefault(p, set()).add(key)
        return other in self._partners.get(lemma, ())

    def _choose(self, rows, epos, en):
        """The kaikki entry a pack word was built from: same POS, a lemma entry;
        several (всё/все, за́мок/замо́к) -> the one whose glosses share the most
        words with the pack gloss, then the ё spelling, then file order."""
        cands = [r for r in rows if r[1] == epos and r[5]] or [r for r in rows if r[5]] or rows
        if len(cands) == 1:
            return cands[0]
        words = set(re.findall(r"[a-z]+", en.lower())) - {"to", "a", "an", "the", "of", "m", "f", "n"}
        return max(cands, key=lambda r: (len(words & set(re.findall(r"[a-z]+", r[6].lower()))),
                                         r[1] == epos, "ё" in r[0], -cands.index(r)))

    def finalize_words(self, env, ctx, words):
        info = self._kaikki_info(env)
        from ..core.gloss import strip_gloss_style
        for w in words:
            w["en"] = strip_gloss_style(w["en"])   # mutually reflexive, thy/hither, "as ... as possible"
        amb, no_aspect, no_pron = [], [], []
        for w in words:
            key = w["lemma"]
            if w["pos"] == "phrase":
                w["pron"] = self.fixed_pron.get(key, key)
                continue
            rows = info.get(key, [])
            r = self._choose(rows, w.get("_epos"), w["en"]) if rows else None
            if rows and len({x[0] for x in rows if x[5] and x[1] == w.get("_epos")}) > 1:
                amb.append(f"{key}->{r[0]}")
            disp = strip_stress(r[0]) if r else key
            if fold(disp) != key:
                disp = key
            w["w"] = w["lemma"] = disp
            if "ё" in disp:
                w["alt"] = [fold(disp)]              # sentences written with е
            else:
                w.pop("alt", None)
            canon = r[2] if r and r[2] and fold(r[2]) == key else None
            if disp in self.fixed_pron:
                w["pron"] = self.fixed_pron[disp]    # kaikki has no stressed headword
            elif canon and ("\u0301" in canon or "ё" in canon):
                w["pron"] = canon
            elif all(n_vowels(part) <= 1 for part in disp.split("-")) or "ё" in disp:
                w["pron"] = disp                     # one vowel or ё: the stress is unambiguous
            else:
                # the stressed form from any entry of this spelling (form-of lines too)
                other = next((x[2] for x in rows if x[2] and "\u0301" in x[2] and strip_stress(x[2]) == disp),
                             None)
                if other:
                    w["pron"] = other
                else:
                    no_pron.append(disp)
            if w["pos"] == "verb":
                asp = r[3] if r else None
                suffix = {"impf": "impf.", "pf": "pf.", "both": "impf./pf.", "impf-pf": "impf./pf.",
                          "pf-impf": "impf./pf."}.get(asp)
                if suffix is None:
                    suffix = self._corpus_aspect(ctx, w)
                if suffix is None:
                    no_aspect.append(disp)
                elif not re.search(r"\((impf\.|pf\.|impf\./pf\.)\)$", w["en"]):
                    w["en"] = f"{w['en']} ({suffix})"
        from ..core.util import stat
        stat("ru_display", {"ambiguous_spelling_choices": sorted(amb), "verbs_without_aspect": sorted(no_aspect),
                            "words_without_pron": sorted(no_pron)})

    def _corpus_aspect(self, ctx, w):
        """Aspect from spaCy's Aspect= majority on the verb's tokens (fallback)."""
        return None

    # ---- checks --------------------------------------------------------------
    def check_word(self, w):
        if any(m in w["w"] for m in STRESS):
            return f"word {w['id']} {w['w']!r}: stress mark in w (pron only)"
        if w.get("pos") == "noun" and not re.search(r"\((m|f|n|m/f|pl\.)\)$", w["en"]):
            return f"noun {w['id']} {w['w']!r}: gloss without gender suffix: {w['en']!r}"
        if w.get("pos") == "verb" and not re.search(r"\((impf\.|pf\.|impf\./pf\.)\)$", w["en"]):
            return f"verb {w['id']} {w['w']!r}: gloss without aspect: {w['en']!r}"
        if not w.get("pron"):
            return f"word {w['id']} {w['w']!r}: no pron (every Russian word carries its stressed form)"
        if strip_stress(w["pron"]) != w["w"]:
            return f"word {w['id']} {w['w']!r}: pron {w['pron']!r} is not the stressed w"
        return None

    # ---- QA scans --------------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "seasons": " ".join(SEASONS),
        "num": " ".join(NUMBERS), "col": " ".join(COLOURS),
        "core": " ".join(GREETINGS + CONJS + PREPS),
    }
    qa_verb_re = r"(ть|ти|чь|ться|тись|чься)$"
    qa_adj_inflected_re = r"(ая|яя|ое|ее|ые|ие|ого|его|ому|ему)$"
    qa_foreign_letters_re = r"[a-z]"
    qa_proper_re = r"\b(Moscow|Russia|Russian|Petersburg|Christ|God|Lenin|Soviet)\b"


SPEC = Russian
