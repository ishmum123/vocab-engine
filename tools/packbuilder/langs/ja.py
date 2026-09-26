"""Japanese (ja): everything Japanese-specific in the pack pipeline.

Tagger: SudachiPy (split mode C, SudachiDict-core) through the non-spaCy
tagging hooks (tagger_desc / tag_texts). Each token is stored as
[surface, lemma, UPOS, morph] with the Sudachi analysis in morph (Dict =
dictionary form as written, Norm = normalised form, Read/DRead = katakana
reading of the surface / of the dictionary form, Pos, Conj, Src, Ctr).

Lemmas:
- One word per Sudachi (normalised form, UPOS) group: kana and kanji
  spellings (わかる/分かる, いい/よい/良い, こと/事, する/為る) are one word. The
  headword is the spelling Tatoeba uses most; the other attested spellings
  become alts. Conjugated surfaces (食べ+まし+た) carry the dictionary form
  (食べる), so they link to it; potential forms fold into the verb (話せる ->
  話す), as Sudachi normalises them.
- Tatoeba's curated jpn_indices (JMdict lemma(reading){surface} per word)
  confirm or correct the Sudachi lemma of a token where they align: a
  kana-written homograph (あう: 会う vs 合う) takes the index's word. The
  morph field records Src=idx (confirmed) or Src=idx+ (corrected).
- A noun or suffix right after a numeral is a counter ("〜人", "〜時", "〜円"),
  and a bound suffix anywhere is "〜X" (〜さん, 〜たち): bound morphemes,
  function words. A numeral + 月 is a month name (一月 ... 十二月; 1月 is an
  alt). Fixed greetings Sudachi splits (すみ+ませ+ん, お+願い+し+ます) are merged
  into one token.
- Particles and auxiliaries outside the taught closed set (casual てる,
  ちゃう, passive れる ...) and verbs used as auxiliaries after て (ている,
  てしまう) link nothing and never become words. する right after a noun it
  makes into a verb (勉強する) is absorbed by the noun.
- bind_lexicon points each lemma at the Wiktionary entries of all its
  spellings whose reading the corpus uses (方: ほう and かた), so the sense
  ranking picks the entry, and finalize_words shows that entry's reading.

Display: pron = kana reading (hiragana; katakana words keep katakana).
typing null (no typed drill), spaced false (cloze and highlighting match
substrings), pack.compounds lists the corpus units a shorter pack form must
not be matched inside.

The A1 core list, gloss overrides and generated sentences live in the
japanese repo (tools/).
"""
import bz2
import gzip
import io
import json
import re
import tarfile
from collections import Counter, defaultdict

from .base import LanguageSpec, SENSITIVE_EN, SENSITIVE_GLOSS_EN, TATOEBA_ENG, TATOEBA_AUDIO, drop_all_re

# ---- script ---------------------------------------------------------------
HIRA = "ぁ-ゖゝゞ"
KATA = "ァ-ヺー-ヾ"
KANJI = "㐀-䶿一-鿿豈-﫿々〆ヵヶ"
JA = HIRA + KATA + KANJI
JA_RE = re.compile(f"[{JA}]")
KANJI_RE = re.compile(f"[㐀-䶿一-鿿豈-﫿々]")
KANA_ONLY_RE = re.compile(f"^[{HIRA}{KATA}]+$")
HIRA_ONLY_RE = re.compile(f"^[{HIRA}ー]+$")
KATA_ONLY_RE = re.compile(f"^[{KATA}]+$")
DIGIT_RE = re.compile(r"[0-9０-９]")
# a number before a counter (７時, 二十本, 何ページ, 数分, 14,000人)
NUMERAL_RE = re.compile(r"^[0-9０-９,，.．一二三四五六七八九十百千万億何数幾]+$")


def _u16(text, i):
    """Python str index -> UTF-16 code-unit index (passages.utf16_index)."""
    return i + sum(1 for ch in text[:i] if ord(ch) > 0xFFFF)


def hira(s):
    """Katakana -> hiragana (ー kept); kana iteration marks spelled out
    (Wiktionary writes ほぼ's reading ほゞ)."""
    out = []
    for c in s or "":
        c = chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" or c in "ヽヾ" else c
        if c in "ゝゞ" and out:
            c = out[-1] if c == "ゝ" else chr(ord(out[-1]) + 1)
        out.append(c)
    return "".join(out)


# ---- closed sets -----------------------------------------------------------
NUMBERS = "ゼロ 一 二 三 四 五 六 七 八 九 十 百 千 万".split()
DAYS = "月曜日 火曜日 水曜日 木曜日 金曜日 土曜日 日曜日".split()
MONTHS = [f"{n}月" for n in "一 二 三 四 五 六 七 八 九 十 十一 十二".split()]
MONTH_READ = "いちがつ にがつ さんがつ しがつ ごがつ ろくがつ しちがつ はちがつ くがつ じゅうがつ じゅういちがつ じゅうにがつ".split()
KANJI_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
             "十一": 11, "十二": 12}
PRONOUNS = "私 あなた 彼 彼女 私たち".split()
DEMONSTRATIVES = [("これ", "PRON"), ("それ", "PRON"), ("あれ", "PRON"), ("どれ", "PRON"),
                  ("この", "DET"), ("その", "DET"), ("あの", "DET"), ("どの", "DET"),
                  ("ここ", "PRON"), ("そこ", "PRON"), ("あそこ", "PRON"), ("どこ", "PRON"),
                  ("あちら", "PRON")]
QUESTION = [("何", "PRON"), ("誰", "PRON"), ("いつ", "PRON"), ("どう", "ADV"), ("どうして", "ADV"),
            ("なぜ", "ADV"), ("いくら", "NOUN"), ("いくつ", "NOUN"), ("どんな", "DET"), ("どちら", "PRON"),
            ("何時", "NOUN")]
# particles taught as words (PART); every other particle links nothing
PARTICLES = {"は": "(topic marker) as for",
             "が": "(subject marker); but",
             "を": "(direct object marker)",
             "に": "(particle) to, at, in; (indirect object marker)",
             "で": "(particle) at, in; by, with",
             "と": "(particle) and; with; (quotation marker)",
             "も": "(particle) also, too; even",
             "へ": "(particle) to, towards",
             "の": "(particle) 's, of; (nominaliser)",
             "か": "(question marker); or",
             "ね": "(sentence-final) isn't it?, right?",
             "よ": "(sentence-final, emphasis) you know",
             "て": "(te-form ending) and; (links verbs)",
             "から": "(particle) from; because",
             "まで": "(particle) until, as far as",
             "より": "(particle) than; from",
             "や": "(particle) and (among others)",
             "けど": "but, although",
             "だけ": "only, just",
             "しか": "(with a negative) only, nothing but",
             "など": "and so on, etc.",
             "ば": "(conditional) if",
             "くらい": "about, approximately",
             "ながら": "while (doing)",
             "たり": "(listing actions) do things like"}
FORCED_PARTICLES = "は が を に で と も へ の か ね よ て から まで".split()
# auxiliaries taught as words (UPOS AUX -> core group VERB, shown as pos "aux")
AUXILIARIES = {"だ": "(copula, plain) is, am, are",
               "です": "(copula, polite) is, am, are",
               "ます": "(polite verb ending)",
               "た": "(past tense ending)",
               "ない": "(negative ending) not",
               "たい": "want to (do)"}
FORCED_AUX = "だ です ます た ない".split()
GREETINGS = {"こんにちは": "hello, good afternoon",
             "こんばんは": "good evening",
             "おはよう": "good morning",
             "さようなら": "goodbye",
             "ありがとう": "thank you",
             "すみません": "excuse me; I'm sorry",
             "ごめんなさい": "I'm sorry",
             "お願いします": "please",
             "はい": "yes",
             "いいえ": "no",
             "おやすみなさい": "good night",
             "いただきます": "(said before eating) thank you for the food",
             "ごちそうさま": "(said after eating) thank you for the meal",
             "はじめまして": "nice to meet you",
             "よろしくお願いします": "nice to meet you; please treat me well"}
FORCED_GREETINGS = ("こんにちは こんばんは おはよう さようなら ありがとう すみません ごめんなさい お願いします はい いいえ "
                    "いただきます ごちそうさま はじめまして よろしくお願いします").split()
TIME_WORDS = "今日 明日 昨日 今 朝 昼 夜 毎日 午前 午後 今年 来年 去年 今週 来週 先週 今月 来月 先月 今晩 今朝 週末".split()
COUNTERS = {"〜人": "(counter for people)", "〜時": "o'clock", "〜分": "minute(s)", "〜円": "yen",
            "〜歳": "years old", "〜つ": "(counter for things)", "〜年": "year(s)", "〜時間": "hour(s)",
            "〜日": "day (of the month); days", "〜回": "times", "〜本": "(counter for long objects)",
            "〜枚": "(counter for flat objects)", "〜個": "(counter for small objects)", "〜階": "floor, storey",
            "〜さん": "Mr., Ms. (after a name)", "〜たち": "(plural for people)", "〜か月": "month(s)",
            "〜週間": "week(s)", "〜度": "degree(s); times", "〜番": "number (in order)",
            "〜ら": "(plural suffix)", "〜冊": "(counter for books)", "〜匹": "(counter for small animals)",
            "〜台": "(counter for machines, vehicles)", "〜杯": "(counter for cups, glasses)",
            "〜目": "(ordinal suffix) -th", "〜中": "during; throughout", "〜君": "(after a boy's name)",
            "〜ちゃん": "(affectionate, after a name)", "〜様": "Mr., Ms. (polite)", "〜ヶ月": "month(s)",
            "〜分（ぶん）": "part, portion, share"}
# counter readings: the base form a dictionary gives (〜杯 はい; after a number
# it sounds ぱい/ばい), taught with the counter
COUNTER_READ = {"〜人": "にん", "〜時": "じ", "〜分": "ふん", "〜円": "えん", "〜歳": "さい", "〜つ": "つ",
                "〜年": "ねん", "〜時間": "じかん", "〜日": "にち", "〜回": "かい", "〜本": "ほん", "〜枚": "まい",
                "〜個": "こ", "〜階": "かい", "〜さん": "さん", "〜たち": "たち", "〜か月": "かげつ",
                "〜ヶ月": "かげつ", "〜週間": "しゅうかん", "〜度": "ど", "〜番": "ばん", "〜ら": "ら",
                "〜冊": "さつ", "〜匹": "ひき", "〜台": "だい", "〜杯": "はい", "〜目": "め", "〜中": "ちゅう",
                "〜君": "くん", "〜ちゃん": "ちゃん", "〜様": "さま",
                "〜分（ぶん）": "ぶん"}
# the counters an A1 course teaches for counting things and people (つ 個 枚 本
# 台 杯 冊 匹 人), plus time, money and age
FORCED_COUNTERS = "〜人 〜時 〜分 〜円 〜歳 〜つ 〜さん 〜個 〜匹 〜枚 〜本 〜台 〜杯 〜冊".split()
FIXED = {**{(p, "PART"): g for p, g in PARTICLES.items()},
         **{(a, "VERB"): g for a, g in AUXILIARIES.items()},
         **{(w, "INTJ"): g for w, g in GREETINGS.items()},
         **{(c, "NOUN"): g for c, g in COUNTERS.items()},
         **{(m, "NOUN"): en for m, en in zip(MONTHS, "January February March April May June July August "
                                              "September October November December".split())},
         ("ください", "VERB"): "please (give me / do for me)",
         ("私", "PRON"): "I, me", ("あなた", "PRON"): "you", ("彼", "PRON"): "he, him; boyfriend",
         ("彼女", "PRON"): "she, her; girlfriend", ("私たち", "PRON"): "we, us",
         ("これ", "PRON"): "this (one)", ("それ", "PRON"): "that (one, near you)",
         ("あれ", "PRON"): "that (one, over there)", ("どれ", "PRON"): "which (one)",
         ("この", "DET"): "this ...", ("その", "DET"): "that ... (near you)",
         ("あの", "DET"): "that ... (over there)", ("どの", "DET"): "which ...",
         ("ここ", "PRON"): "here", ("そこ", "PRON"): "there (near you)", ("あそこ", "PRON"): "over there",
         ("どこ", "PRON"): "where", ("何", "PRON"): "what", ("誰", "PRON"): "who", ("いつ", "PRON"): "when",
         ("どう", "ADV"): "how", ("どうして", "ADV"): "why; how", ("なぜ", "ADV"): "why",
         ("いくら", "NOUN"): "how much", ("いくら", "ADV"): "how much",
         ("いくつ", "NOUN"): "how many; how old", ("どんな", "DET"): "what kind of",
         ("どちら", "PRON"): "which (of two); where (polite)", ("何時", "NOUN"): "what time",
         ("あちら", "PRON"): "over there; that way (polite)", ("ゼロ", "NUM"): "zero"}
FIXED_READ = {"何時": "なんじ",
              # Sudachi reads 種 しゅ everywhere, so corpus counts never show the
              # たね the sentences use ("seed", 悩みの種)
              "種": "たね"}
MONTH_PRON = dict(zip(MONTHS, MONTH_READ))

# fixed expressions Sudachi splits: (surface, lemma, standalone, UPOS).
# "standalone": only as a whole utterance (教えていただきます is the humble
# auxiliary, not the greeting)
PHRASES = [("ありがとうございました", "ありがとう", False, "INTJ"), ("ありがとうございます", "ありがとう", False, "INTJ"),
           ("おはようございます", "おはよう", False, "INTJ"), ("すみませんでした", "すみません", False, "INTJ"),
           ("すみません", "すみません", False, "INTJ"), ("すいません", "すみません", False, "INTJ"),
           ("よろしくお願いします", "よろしくお願いします", False, "INTJ"),
           ("よろしくおねがいします", "よろしくお願いします", False, "INTJ"),
           ("お願いいたします", "お願いします", False, "INTJ"), ("お願いします", "お願いします", False, "INTJ"),
           ("おねがいします", "お願いします", False, "INTJ"), ("ごめんなさい", "ごめんなさい", False, "INTJ"),
           ("いただきます", "いただきます", True, "INTJ"), ("ごちそうさまでした", "ごちそうさま", True, "INTJ"),
           ("ごちそうさま", "ごちそうさま", True, "INTJ"), ("ご馳走様でした", "ごちそうさま", True, "INTJ"),
           ("はじめまして", "はじめまして", True, "INTJ"), ("初めまして", "はじめまして", True, "INTJ"),
           ("どうしても", "どうしても", False, "ADV"), ("どうして", "どうして", False, "ADV"),
           ("どうも", "どうも", False, "ADV"),
           # こう/そう/ああ/どう + いう "this/that/what kind of": not 言う "to say"
           ("こういう", "こういう", False, "DET"), ("そういう", "そういう", False, "DET"),
           ("ああいう", "ああいう", False, "DET"), ("どういう", "どういう", False, "DET"),
           # compound particles: one unlinked token (として is not と + する + て)
           ("として", "として", False, "PART"), ("について", "について", False, "PART"),
           ("によって", "によって", False, "PART"), ("にとって", "にとって", False, "PART"),
           ("に対して", "に対して", False, "PART"), ("に関して", "に関して", False, "PART"),
           ("によると", "によると", False, "PART"), ("によれば", "によれば", False, "PART"),
           ("に対する", "に対する", False, "PART"), ("に関する", "に関する", False, "PART")]
# bound suffixes taught as words ("〜さん"); any other suffix is read as its noun
# (同時代人: 人 "person"), and a noun or suffix after a numeral is a counter
SUFFIX_WORDS = {"さん", "様", "さま", "ちゃん", "君", "くん", "たち", "達", "ら", "等", "氏", "中"}
# a taught suffix is bound to the noun or name before it. Sudachi also tags a
# free word as the suffix: after a particle, auxiliary, verb, adjective,
# interjection or punctuation (誰かさん, 。君) it is no suffix; after a numeral
# it is no taught suffix (十中八九, 一等 "first prize"); and 君 is the honorific
# only after a name (トニー君, 鈴木君), else the pronoun (明日君の車 "your car
# tomorrow", 先日君が会った人, みんな君に任せる)
SUFFIX_BAD_PREV = ("助詞", "助動詞", "補助記号", "動詞", "形容詞", "感動詞", "空白", "接頭辞")
HONORIFIC_AFTER_NAME = {"君", "くん"}
# a noun after the honorific prefix 貴 is one word with it (貴職 "you", 貴社
# "your company"): the noun alone (職 "job") is not linked
WORD_PREFIXES = {"貴"}
# fused expressions Sudachi splits into words they do not mean: the listed
# surfaces inside them link nothing (None: every content token inside).
# 何もかも "everything" is not 何 "what"; かどうか "whether" is not どう "how";
# かくして "thus" is not 掻く; いくつめ "which number" is not 行く; うまが合う
# "get along" is not 馬 "horse"
FUSED_UNLINK = {"何もかも": None, "なにもかも": None, "十中八九": None, "かくして": None, "この上なく": None,
                "この上ない": None, "かどうか": None, "いくつめ": None, "いくつ目": None, "幾つ目": None,
                "うまが合": ("うま",), "馬が合": ("馬",)}
# the surfaces of an auxiliary that link it (な/に/で are forms of だ that
# learners meet as grammar: 好きな, 静かに; they link nothing)
AUX_SURFACES = {"だ": {"だ", "だっ", "だろ"}, "です": {"です", "でし", "でしょ"},
                "ます": {"ます", "まし", "ませ", "ましょ"}, "た": {"た", "だ"},
                "ない": {"ない", "なかっ", "なく", "なけれ", "なきゃ"}, "たい": {"たい", "たく", "たかっ", "たけれ"}}
PROFANITY = {"クソ", "くそ", "糞", "畜生", "ちくしょう", "てめえ", "貴様", "野郎", "ブス", "ばか野郎", "馬鹿野郎"}
# surfaces with a fixed lemma, before grouping (ください is the A1 request word;
# other forms of くださる stay くださる)
SURFACE_LEMMA = {"ください": ("ください", "VERB", "クダサイ"), "下さい": ("ください", "VERB", "クダサイ")}
# readings Sudachi gets wrong for a learner (私 is わたし, not the formal わたくし)
# Sudachi reads a few kanji words one fixed way where the everyday reading
# differs (明日 アス for あした, 何 ナン for the headword なに, 私 ワタクシ)
# kana words whose corpus use is dialect or slang for another word (Kansai
# よう分からん = よく; よう! "hey"): no entry of their own
DIALECT_ONLY = {"よう": ("ADV", "INTJ", "NOUN"),   # よう noun: the ように/ような grammar
                "もん": ("NOUN", "PART"),
                "しよう": ("NOUN",)}      # しよう: volitional する (どうしようもない) Sudachi tags 仕様          # もん: casual もの ("because", "thing"), not 門
READING_FIX = {"私": "ワタシ", "明日": "アシタ", "何": "ナニ", "富士山": "フジサン"}
# verbs used as auxiliaries after て/で (ている, てしまう, てみる ...): no link
# unless listed here (てください is the request word)
AUX_VERB_KEEP = {"ください"}
NUMERAL_CHARS = frozenset("0123456789０１２３４５６７８９一二三四五六七八九十百千万〇")
NAME_SUFFIX = frozenset({"城", "寺"})    # after a declared name, when the joined form is
                                          # itself declared: じょう/じ, not the noun 城 しろ, 寺 てら

# ---- register / content filters --------------------------------------------
# kana items are bounded by non-hiragana on the left (やくそく is not くそ)
VULGAR_JA = (r"(?<![ぁ-ゖ])(?:くそ|くたばれ|ちくしょう|てめえ|てめー|きさま|ぶっころ|うるせえ|うるせー|ばかやろ|"
             r"ふざけんな|ざけんな|ちんこ|まんこ|おっぱい|きもい)|"
             r"クソ|糞|畜生|チクショウ|テメエ|貴様|ぶっ殺|馬鹿野郎|バカヤロ|クソッタレ|この野郎|ブス|キモい|"
             # slurs (disability, ethnic); めくら is not めくらない (めくる), かたわ not かたわら
             r"(?<![ぁ-ゖ])めくら(?![なれせずさ])|つんぼ|きちがい|キチガイ|気違い|気狂い|(?<![ぁ-ゖ])かたわ(?!ら)|"
             r"びっこ|支那|ジャップ|(?<![ァ-ヺ])チョン(?![ァ-ヺー])")
CASUAL_JA = (r"俺|(?<![ぁ-ゖ])おれ|オレ|お前|(?<![ぁ-ゖ])おまえ|オマエ|(?<![ぁ-ゖ])あんた|アンタ|じゃん|だぜ|"
             r"ぜ[。！!]|ぞ[。！!]|っす|じゃねえ|"
             r"じゃねー|ねえよ|ねーよ|かよ[。！？!?]|んだよ|だろうが|やがる|やがっ|ちまう|ちまっ|すげえ|すげー|"
             r"やべえ|やべー|でけえ|うめえ|わりい")
SENSITIVE_JA = (r"殺|死ね|死んじまえ|自殺|レイプ|強姦|セックス|性的|性交|エッチ|エロ|裸|ヌード|売春|娼婦|ポルノ|"
                r"射殺|刺し殺|刺され|撃た|撃っ|撃つ|銃|拳銃|爆弾|首を絞|絞め殺|死体|遺体|血まみれ|処刑|拷問|"
                r"コンドーム|妊娠させ")
DROP_ALL = (r"レイプ|強姦|性的虐待|性的暴行|児童虐待|痴漢|わいせつ|猥褻|自殺|自傷|"
            r"rape[ds]?|raping|rapist\w*|molest\w*|sexual(?:ly)? abus\w*|child abuse|pedophil\w*|paedophil\w*")

# "name" is kept: kaikki files some common nouns as names (地球, フランス語,
# クリスマス); Sudachi's proper-noun tag keeps real names out of the pack
JUNK_POS = {"character", "syllable", "soft-redirect", "romanization", "affix", "prefix", "root", "punct",
            "symbol", "combining_form", "infix", "proverb"}
QUOTED_GLOSS_RE = re.compile(r"“([^”]+)”")
FORM_LINE_RE = re.compile(r"^(?:[a-zū-]+ ){0,3}(?:synonym|form|spelling|short for|clipping|abbreviation|"
                          r"contraction|variant|ellipsis)\b[^“]*“", re.I)
SPELLING_PREFIX_RE = re.compile(r"^(?:[^\x00-\x7f]+(?:, ?[^\x00-\x7f]+)*)\s*:\s+")

UPOS_WORD = {"NOUN", "PRON", "ADJ", "DET", "ADV", "CCONJ", "INTJ", "VERB", "NUM", "PART", "AUX"}


def sudachi_upos(p):
    """Sudachi POS tuple -> UD-style UPOS used by the core."""
    a, b = p[0], p[1]
    if a == "名詞":
        return "PROPN" if b == "固有名詞" else "NUM" if b == "数詞" else "NOUN"
    return {"代名詞": "PRON", "連体詞": "DET", "副詞": "ADV", "接続詞": "CCONJ", "動詞": "VERB",
            "形容詞": "ADJ", "助動詞": "AUX", "助詞": "PART", "接頭辞": "X", "補助記号": "PUNCT",
            "空白": "SPACE", "記号": "SYM",
            "形状詞": "AUX" if b == "助動詞語幹" else "ADJ",
            "感動詞": "X" if b == "フィラー" else "INTJ",
            "接尾辞": "NOUN" if b == "名詞的" else "X"}.get(a, "SYM")


def clean_reading(r):
    return hira(re.sub(r"[%^.\-\s・]", "", r or ""))


def ruby_reading(form, ruby):
    """'食べる transitive ichidan' + [["食","た"]] -> 'たべる'."""
    word = form.split(" ")[0]
    out, i = [], 0
    for base, rd in ruby:
        j = word.find(base, i)
        if j < 0:
            return None
        out.append(word[i:j])
        out.append(rd)
        i = j + len(base)
    out.append(word[i:])
    s = "".join(out)
    return hira(s) if KANA_ONLY_RE.match(s.replace("ー", "ー")) else None


GLOSS_STOP = {"the", "a", "an", "of", "to", "or", "and", "in", "on", "for", "with", "one", "used", "as",
              "something", "someone", "that", "is", "be", "by", "from", "which", "who"}


def gloss_words(txt):
    return {re.sub(r"(?<=[a-z]{3})s$", "", x) for x in re.findall(r"[a-z]+", (txt or "").lower())} - GLOSS_STOP


def same_sense_words(pa, pb):
    """Two primary glosses name one sense: half their words shared, or one
    contained in the other when the larger has no qualifier in brackets
    (かける "to hang" in 掛ける "to hang, to raise"; not とる in 撮る "to take (a photo)")."""
    if not pa or not pb:
        return False
    a, b = gloss_words(pa), gloss_words(pb)
    if not a or not b:
        return False
    if len(a & b) / len(a | b) >= 0.5:
        return True
    small, big = (pa, pb) if len(a) <= len(b) else (pb, pa)
    ws = gloss_words(small)
    # the qualifier that matters is on the big gloss's first sense; "(a picture,
    # etc.)" is an example, not a qualifier
    first = re.split(r"[,;]\s*(?![^()]*\))", re.sub(r"\([^)]*(?:etc|,)[^)]*\)", "", big))[0]
    return len(ws & gloss_words(big)) / len(ws) >= 0.5 and "(" not in first


def gloss_words_overlap(fa, fb, kpos):
    """First glosses (by kaikki POS) of a kana and a kanji word share a sense."""
    return any(same_sense_words(fa[p], fb[p]) for p in kpos if p in fa and p in fb)


_ROMA = dict(zip(
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
    "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ",
    ("a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho "
     "ma mi mu me mo ya yu yo ra ri ru re ro wa o n ga gi gu ge go za ji zu ze zo da ji zu de do "
     "ba bi bu be bo pa pi pu pe po").split()))


def romaji(k):
    """Hepburn romanization of a kana word (シロ -> shiro); None when unknown kana."""
    k = hira(k)
    out, i = "", 0
    while i < len(k):
        c = k[i]
        n = k[i + 1] if i + 1 < len(k) else ""
        if c == "っ" and n in _ROMA:
            out += _ROMA[n][0]
            i += 1
            continue
        if c == "ー":
            out += out[-1:]
            i += 1
            continue
        r = _ROMA.get(c)
        if r is None:
            return None
        if n in "ゃゅょ" and n:
            r = (r[:-1] if r in ("shi", "chi", "ji") else r[:-1] + "y") + {"ゃ": "a", "ゅ": "u", "ょ": "o"}[n]
            i += 1
        out += r
        i += 1
    return out


def romaji_forms(k):
    r = romaji(k)
    if not r:
        return set()
    return {r, r.replace("ou", "o").replace("uu", "u").replace("ii", "i"), r.replace("ou", "oh")}


_VOICE = str.maketrans("がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽぁぃぅぇぉゃゅょゎ",
                       "かきくけこさしすせそたちつてとはひふへほはひふへほあいうえおやゆよわ")
_VU = (("ゔぁ", "ば"), ("ゔぃ", "び"), ("ゔぇ", "べ"), ("ゔぉ", "ぼ"), ("ゔ", "ぶ"), ("うぃ", "うい"),
       ("うぇ", "うえ"), ("てぃ", "ち"), ("でぃ", "じ"))


def _long_marks(x):
    x = hira(x)
    for a, b in _VU:
        x = x.replace(a, b)
    x = re.sub("([えけせてねへめれげぜでべぺ])い", r"\1ー", x)
    return re.sub("([おこそとのほもろごぞどぼぽよょ])う", r"\1ー", x)


def kana_sound_variant(a, b, a_has_own):
    """Kana a is a sound variant of reading b: length marks, small っ/ん, voicing,
    ヴ spellings (あんまり/あまり, やっぱり/やはり, ネイティヴ/ネイティブ), or a clipped
    form of it with no word of its own (そっ/そう, カッコ/かっこう). かん is not かれ."""
    def sk(x):
        return re.sub("[ーっん]", "", _long_marks(x)).translate(_VOICE)
    sa, sb = sk(a), sk(b)
    if sa == sb or re.sub(r"(.)\1", r"\1", sa) == re.sub(r"(.)\1", r"\1", sb):
        return True
    ta = re.sub("ー", "", re.sub("[ーっ]+$", "", _long_marks(a)))
    tb = re.sub("ー", "", _long_marks(b))
    return not a_has_own and 0 < len(ta) < len(tb) and tb.startswith(ta)


# idioms whose noun is read and meant otherwise than the word it would link:
# 実を結ぶ "bear fruit" (み, not 実 じつ "truth"), 主として "mainly" (not 主
# ぬし "owner"), ある種 "a kind of" (しゅ, not 種 "seed"), おいとま(する) "take
# one's leave" (not 暇 "free time"). (noun, previous token or None, next
# tokens' prefix or None)
IDIOM_UNLINK = (("実", None, "を結"), ("主", None, "として"), ("種", "ある", None), ("暇", "お", None))


# compound particles Sudachi splits into に + a kana verb: において/における
# (置く), につれて (連れる), にわたって/にわたる (渡る). Grammar, not the verb:
# に置いて "put on" is written in kanji and stays the verb. None = any next token.
COMPOUND_PARTICLE_VERBS = {"おい": ("て",), "おけ": ("る",), "つれ": None, "わたっ": None,
                           "わたり": None, "わたる": None}


def prev_tok(toks, i):
    return next((t for t in reversed(toks[:i]) if t[2] != "SPACE"), None)


# kana potential forms Sudachi keeps as their own verb (なれる: なる "can
# become" after に/と, else 慣れる "to get used to")
POTENTIAL_OF = {"なれる": "なる"}


# passages: pack POS -> build group (passage_retag joins, the conjunction rule)
PASSAGE_POS_GROUP = {"noun": "NOUN", "adv": "ADV", "pron": "PRON", "det": "DET", "adj": "ADJ", "verb": "VERB",
                     "conj": "CONJ", "intj": "INTJ"}
# passages: time units a 前 "ago" or a 位 "about" may follow (3年前, 三日位)
TIME_UNITS = {"年", "ヶ月", "か月", "カ月", "ヵ月", "日", "時間", "週間", "分", "秒", "年間", "日間", "時", "月", "晩", "世紀"}


def feats_of(ms):
    return dict(kv.split("=", 1) for kv in ms.split("|") if "=" in kv) if ms else {}


# ---- script primer (docs/SCRIPT_PRIMER.md ss3) -------------------------------
# Kana: hiragana (108 units, 12 sets) then katakana (the same 108, plus ー and 12
# extended syllables: 121 units, 13 sets). The small ゃ ゅ ょ っ are units of
# their own, taught in the set before the first yōon set; a yōon unit is read
# from its parts (き + ゃ) and carries them as its syll. Romans are Hepburn as romaji() writes
# them (を o, ぢ ji, づ zu); example romans are romaji(pron) exactly.
# rows: (set, group, [(kana, roman, alt)]) -- the hiragana teaching order; the
# katakana stage repeats it (ー joins set 5) and adds the extended set.
_JA_ROWS = [
    (1, "vowel", [("あ", "a", []), ("い", "i", []), ("う", "u", []), ("え", "e", []), ("お", "o", [])]),
    (1, "k", [("か", "ka", []), ("き", "ki", []), ("く", "ku", []), ("け", "ke", []), ("こ", "ko", [])]),
    (2, "s", [("さ", "sa", []), ("し", "shi", ["si"]), ("す", "su", []), ("せ", "se", []), ("そ", "so", [])]),
    (2, "t", [("た", "ta", []), ("ち", "chi", ["ti"]), ("つ", "tsu", ["tu"]), ("て", "te", []), ("と", "to", [])]),
    (3, "n", [("な", "na", []), ("に", "ni", []), ("ぬ", "nu", []), ("ね", "ne", []), ("の", "no", [])]),
    (3, "h", [("は", "ha", ["wa"]), ("ひ", "hi", []), ("ふ", "fu", ["hu"]), ("へ", "he", ["e"]), ("ほ", "ho", [])]),
    (4, "m", [("ま", "ma", []), ("み", "mi", []), ("む", "mu", []), ("め", "me", []), ("も", "mo", [])]),
    (4, "y", [("や", "ya", []), ("ゆ", "yu", []), ("よ", "yo", [])]),
    (4, "r", [("ら", "ra", ["la"]), ("り", "ri", ["li"]), ("る", "ru", ["lu"]), ("れ", "re", ["le"]), ("ろ", "ro", ["lo"])]),
    (5, "w", [("わ", "wa", []), ("を", "o", ["wo"]), ("ん", "n", ["nn"])]),
    (6, "dakuten", [("が", "ga", []), ("ぎ", "gi", []), ("ぐ", "gu", []), ("げ", "ge", []), ("ご", "go", []),
                    ("ざ", "za", []), ("じ", "ji", ["zi"]), ("ず", "zu", []), ("ぜ", "ze", []), ("ぞ", "zo", [])]),
    (7, "dakuten", [("だ", "da", []), ("ぢ", "ji", ["di"]), ("づ", "zu", ["du"]), ("で", "de", []), ("ど", "do", []),
                    ("ば", "ba", []), ("び", "bi", []), ("ぶ", "bu", []), ("べ", "be", []), ("ぼ", "bo", [])]),
    (8, "dakuten", [("ぱ", "pa", []), ("ぴ", "pi", []), ("ぷ", "pu", []), ("ぺ", "pe", []), ("ぽ", "po", [])]),
    (9, "small", [("ゃ", "ya", []), ("ゅ", "yu", []), ("ょ", "yo", []), ("っ", "(double)", [])]),
    (10, "yoon", [("きゃ", "kya", []), ("きゅ", "kyu", []), ("きょ", "kyo", []),
                 ("しゃ", "sha", ["sya"]), ("しゅ", "shu", ["syu"]), ("しょ", "sho", ["syo"]),
                 ("ちゃ", "cha", ["tya"]), ("ちゅ", "chu", ["tyu"]), ("ちょ", "cho", ["tyo"])]),
    (11, "yoon", [("にゃ", "nya", []), ("にゅ", "nyu", []), ("にょ", "nyo", []),
                  ("ひゃ", "hya", []), ("ひゅ", "hyu", []), ("ひょ", "hyo", []),
                  ("みゃ", "mya", []), ("みゅ", "myu", []), ("みょ", "myo", []),
                  ("りゃ", "rya", []), ("りゅ", "ryu", []), ("りょ", "ryo", [])]),
    (12, "yoon", [("ぎゃ", "gya", []), ("ぎゅ", "gyu", []), ("ぎょ", "gyo", []),
                  ("じゃ", "ja", ["zya", "jya"]), ("じゅ", "ju", ["zyu", "jyu"]), ("じょ", "jo", ["zyo", "jyo"]),
                  ("びゃ", "bya", []), ("びゅ", "byu", []), ("びょ", "byo", []),
                  ("ぴゃ", "pya", []), ("ぴゅ", "pyu", []), ("ぴょ", "pyo", [])]),
]
_JA_KATA_EXTRA = [(5, "small", [("ー", "(long)", [])]),
                  (13, "extended", [("ティ", "ti", []), ("ディ", "di", []), ("ファ", "fa", []), ("フィ", "fi", []),
                                    ("フェ", "fe", []), ("フォ", "fo", []), ("ウィ", "wi", []), ("ウェ", "we", []),
                                    ("ウォ", "wo", []), ("シェ", "she", []), ("ジェ", "je", []), ("チェ", "che", [])])]
# id slugs where the roman is taken or is not a slug
_JA_SLUG = {"を": "wo", "ぢ": "di", "づ": "du", "っ": "sokuon", "ー": "choon",
            "ゃ": "small-ya", "ゅ": "small-yu", "ょ": "small-yo"}
# visual confusables (and を/お, same sound); each pair links both ways
_JA_CONFUSE = ("あお あめ ぬめ いり きさ さち ちら るろ ねれ れわ ねわ はほ はけ まも こに くへ しつ おを じぢ ずづ ばぱ ゃや ゅゆ ょよ っつ "
               "シツ ソン ノソ クワ ウワ アマ チテ スヌ コユ フワ セヤ ヨユ オヲ ジヂ ズヅ バパ ャヤ ュユ ョヨ ッツ")
JA_SCRIPT_NOTES = [
    {"st": "hira", "set": 3, "h": "Particles",
     "body": "As particles, は is read wa and へ is read e. を, also a particle, is read o."},
    {"st": "hira", "set": 5, "h": "Long vowels",
     "body": "A vowel written twice is long: おかあさん okāsan; おう and えい are usually a long o "
             "and a long e."},
    {"st": "hira", "set": 6, "h": "Dakuten",
     "body": "Two dots voice the consonant: か → が, さ → ざ, た → だ, は → ば. ぢ and づ are rare "
             "and sound like じ and ず."},
    {"st": "hira", "set": 8, "h": "Handakuten",
     "body": "A small circle turns h into p: は → ぱ."},
    {"st": "hira", "set": 9, "h": "Small kana",
     "body": "Small ゃ ゅ ょ are written half-size after another kana and glide onto it. A small っ "
             "has no sound of its own: it doubles the next consonant, きって kitte."},
    {"st": "hira", "set": 10, "h": "Yōon",
     "body": "A small ゃ ゅ ょ after an i-row kana merges into one syllable: き + ゃ = きゃ kya."},
    {"st": "kata", "set": 1, "h": "Katakana",
     "body": "Katakana writes loanwords, names and emphasis. Every sound is one you know from hiragana."},
    {"st": "kata", "set": 5, "h": "The long mark ー",
     "body": "ー lengthens the vowel before it: コーヒー kōhī."},
    {"st": "kata", "set": 9, "h": "Small kana",
     "body": "Small ャ ュ ョ ッ work as in hiragana: キャ kya, ネット netto."},
    {"st": "kata", "set": 13, "h": "Extended katakana",
     "body": "Small ァ ィ ゥ ェ ォ spell sounds Japanese lacks: ティ ti, ファ fa, ウィ wi, チェ che."},
]


def _ja_kata(k):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in k)


def _ja_script_units():
    pairs = {}
    for ab in _JA_CONFUSE.split():
        pairs.setdefault(ab[0], []).append(ab[1])
        pairs.setdefault(ab[1], []).append(ab[0])
    hira_ids, units = {}, []

    def unit(stage, st, group, kana, roman, alt, slug, base):
        u = {"id": ("ja-" if stage == "hira" else "ja-kata-") + slug, "st": stage, "set": st,
             "group": group, "t": kana, "roman": roman, "alt": alt}
        if kana in "っッー":
            u["sound"] = False
            u["note"] = ("doubles the next consonant" if kana in "っッ" else "lengthens the vowel before it")
        elif group == "small":
            ki = "き" if stage == "hira" else "キ"
            u["note"] = f"written small after an i-row kana: glides onto it ({ki} + {kana} = {ki}{kana})"
        if base:
            u["base"] = base
        return u

    for st, group, row in _JA_ROWS:
        for kana, roman, alt in row:
            slug = _JA_SLUG.get(kana, roman)
            base = None
            if group == "dakuten":
                base = hira_ids[chr(ord(kana) - (2 if kana in "ぱぴぷぺぽ" else 1))]
            elif group == "yoon":
                base = hira_ids[kana[0]]
            u = unit("hira", st, group, kana, roman, alt, slug, base)
            hira_ids[kana] = u["id"]
            units.append(u)
    kata_ids, kata = {}, []
    rows = [(st, g, [(_ja_kata(k), r, a) for k, r, a in row]) for st, g, row in _JA_ROWS] + _JA_KATA_EXTRA
    rows.sort(key=lambda r: r[0])       # stable: ー after the set-5 rows
    for st, group, row in rows:
        for kana, roman, alt in row:
            hk = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in kana)
            slug = _JA_SLUG.get(hk if kana != "ー" else "ー", roman)
            if group == "extended":
                slug = "x-" + roman
                base = kata_ids[kana[0]]
            elif group == "dakuten":
                base = kata_ids[chr(ord(kana) - (2 if kana in "パピプペポ" else 1))]
            else:
                base = hira_ids.get(hk)
            u = unit("kata", st, group, kana, roman, alt, slug, base)
            kata_ids[kana] = u["id"]
            kata.append(u)
    ids = {**hira_ids, **kata_ids}
    for u in units + kata:
        u["confuse"] = [ids[c] for c in pairs.get(u["t"], [])]
    return units + kata


_JA_SMALL = set("ゃゅょぁぃぅぇぉャュョァィゥェォ")
_JA_SMALL_Y = set("ゃゅょャュョ")
_JA_KANA_RE = re.compile(f"^[{HIRA}{KATA}]+$")



class Japanese(LanguageSpec):
    code = "ja"
    name_en = "Japanese"
    pack_name = "Japanese (A1–B1)"
    tts = "ja-JP"
    stt = "ja-JP"
    tatoeba_code = "jpn"

    # custom tagger (spacy_model None + tag_texts): SudachiPy, see tagger_desc
    spacy_model = None
    tagger_attribution = {
        "source": "SudachiPy (Apache-2.0) with SudachiDict-core (Apache-2.0), split mode C; "
                  "Tatoeba jpn_indices (CC-BY 2.0 FR) for curated word links",
        "licence": "Apache-2.0 (software and dictionary); CC-BY 2.0 FR (indices)",
        "note": "Used at build time only; the pack ships no dictionary files.",
    }

    # no usable subtitle list (hermitdave ja_full.txt keeps kanji stems only):
    # the spoken list is the tagged Tatoeba corpus itself (spoken_from_corpus)
    subtitles_file = "jpn_sentences_detailed.tsv.bz2"
    spoken_from_corpus = True
    spoken_freq_label = "Tatoeba corpus (lemma, POS) token counts"
    use_simplemma = False
    kaikki_file = "kaikki_ja.jsonl.gz"
    sentences_file = "jpn_sentences_detailed.tsv.bz2"
    links_file = "jpn-eng_links.tsv.bz2"
    transcriptions_file = "jpn_transcriptions.tsv.bz2"
    indices_file = "jpn_indices.tar.bz2"
    sources = {
        "kaikki_ja.jsonl.gz": "https://kaikki.org/dictionary/Japanese/kaikki.org-dictionary-Japanese.jsonl.gz",
        "jpn_sentences_detailed.tsv.bz2":
            "https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences_detailed.tsv.bz2",
        "jpn-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/jpn/jpn-eng_links.tsv.bz2",
        "jpn_transcriptions.tsv.bz2":
            "https://downloads.tatoeba.org/exports/per_language/jpn/jpn_transcriptions.tsv.bz2",
        "jpn_indices.tar.bz2": "https://downloads.tatoeba.org/exports/jpn_indices.tar.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t22", "lex": "l1"}

    typing = None                # no typed drill (kana/kanji input is out of scope)
    show_pron = True             # kana reading toggle
    use_audio = False            # 27 permissive clips only: TTS ja-JP throughout
    target_len = {"A1": 6, "A2": 8, "B1": 9}
    min_len = {"A1": 3, "A2": 4, "B1": 5}
    max_len = 14
    sentence_end_re = re.compile(r"[。．.！!？?…][」』）)\"”]*$")

    word_re = re.compile(f"[{JA}A-Za-z]+")
    lex_word_re = re.compile(f"^[{JA}]+$")
    sub_token_re = re.compile(f"^[{JA}]+$")
    form_target_re = re.compile(f"\\bof ([{JA}]+)")
    fem_of_re = re.compile(r"(?!)")
    regional_tags = {"Classical", "Kansai", "Kyoto", "Osaka", "Tohoku", "Kyushu", "Hokkaido", "Okinawan",
                     "Ryukyuan", "Kagoshima", "Nagoya", "Hiroshima", "Tosa", "Hakata", "Izumo", "dialectal"}
    group_kpos = {
        "NOUN": ["noun", "counter", "suffix", "num", "pron", "adj", "postp", "name"],
        "PROPN": ["name"],
        "VERB": ["verb", "suffix"],
        "ADJ": ["adj", "adnominal"],
        "ADV": ["adv", "adj"],
        "DET": ["adnominal", "pron", "det"],
        "PRON": ["pron", "noun"],
        "PART": ["particle", "suffix", "conj", "postp"],
        "CONJ": ["conj", "particle"],
        "NUM": ["num", "noun"],
        "INTJ": ["intj", "phrase"],
    }
    morph_keep = ("Dict", "Norm", "Read", "DRead", "Pos", "Conj", "Src", "Ctr")

    caps_mark_names = False
    caps_proper_pool = False
    numeral_verb_rule = False
    keep_unseen_keys = False
    refill_unexampled = True
    example_shows_word = True
    min_corpus_tokens = 3
    extra_corpus_files = ("tools/generated_sentences.tsv",)

    forced_closed = ([(w, "NUM") for w in NUMBERS] + [(w, "NOUN") for w in DAYS + MONTHS] +
                     [(w, "PRON") for w in PRONOUNS] + DEMONSTRATIVES + QUESTION +
                     [(p, "PART") for p in FORCED_PARTICLES] + [(a, "VERB") for a in FORCED_AUX] +
                     [(g, "INTJ") for g in FORCED_GREETINGS] + [(t, "NOUN") for t in TIME_WORDS] +
                     [(c, "NOUN") for c in FORCED_COUNTERS])
    allowed_num = set(NUMBERS)
    fixed_gloss = FIXED
    function_verbs = set(AUXILIARIES)

    bad_text_re = re.compile(VULGAR_JA)
    profanity = PROFANITY
    drop_all_levels = drop_all_re(r"(?<![A-Za-z])(" + DROP_ALL + r")(?![A-Za-z])")
    sensitive_re = re.compile(r"(?:" + SENSITIVE_JA + r")|(?<![A-Za-z])(?:" + SENSITIVE_EN + r")(?![A-Za-z])", re.I)
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)
    lower_level_gloss_re = re.compile(r"\b(kill\w*|murder\w*|rape[ds]?|raping|rapist|shoot\w*|stab\w*|"
                                      r"porn\w*|prostitut\w*|suicid\w*|bomb\w*|explod\w*|explosi\w*|"
                                      r"poison\w*|blood\w*|corpse\w*|dead body)\b", re.I)
    casual_re = re.compile(CASUAL_JA)

    report_title = "Japanese A1-B1 pack (Sudachi-tagged)"
    forced_description = ("numbers, days, months, pronouns, demonstratives, question words, core particles and "
                          "auxiliaries, greetings, time words, common counters, A1 core list")
    numeral_exclusion = "numeral outside the taught number words"

    qa_closed_sets = {
        "numbers": " ".join(NUMBERS), "days": " ".join(DAYS), "months": " ".join(MONTHS),
        "pronouns": " ".join(PRONOUNS), "demonstratives": " ".join(w for w, _ in DEMONSTRATIVES),
        "question words": " ".join(w for w, _ in QUESTION), "particles": " ".join(FORCED_PARTICLES),
        "auxiliaries": " ".join(FORCED_AUX), "greetings": " ".join(FORCED_GREETINGS),
        "time": " ".join(TIME_WORDS),
    }

    GEN_BASE = 1_000_000_000

    # characters stage (docs/HSK_MERGE.md ss2.2): kanji-word units, reading plus
    # meaning, unlocked after A2 (A1+A2 units) and after B1
    characters = {"label": "漢字",
                  "stages": [{"after": "A2", "levels": ["A1", "A2"]}, {"after": "B1", "levels": ["B1"]}],
                  "setSize": 10, "mastered": 3, "bare": 6,
                  "learnKinds": ["charSound", "charRead"], "reviewKinds": ["charRead", "charSound"]}
    emit_ruby = True
    # pronunciation first (docs/HSK_MERGE.md ss8, 2026-09-25): a kanji word is shown by
    # its kana reading until its unit is mastered; written with "characters" only
    pron_first = True

    def __init__(self, repo=None):
        super().__init__(repo)
        self._kana_verb = {}         # hiragana verb surface -> Counter(lemma), tagging pass (_homophone)
        self._noun_read = {}         # noun reading -> Counter(kanji noun lemma), tagging pass
        self._spell_n = {}           # lemma -> Counter(dictionary spelling), tagging pass
        self._tok = None
        self._lx = None
        self._lemma_of = None        # (norm, upos) -> display lemma, from the tagging pass
        self._spellings = None       # display lemma -> set of spellings (tagging pass)
        self._reading = None         # display lemma -> katakana dictionary-form reading
        self._norms = {}             # display lemma -> Sudachi normal forms of its tokens
        self._norm_top = {}          # display lemma -> its most used normal form
        self._sound_splits = {}      # lemma split off by its first sound -> main lemma (よい -> いい)
        self.pron_changes = []
        self.sound_folded = []
        self.spelling_merges = []
        self.alt_sense_drops = []
        self._foreign_spell = {}        # kana headword -> kanji spellings that are another word (note_words)
        self.gloss_flags = []
        self._idx = None
        self._trans = None
        self._info = None
        self._res_cache = {}
        self.redirect = {}           # lemma -> lemma its tokens count as (potential forms Sudachi keeps apart)
        self._noun_pref = {}
        self._shipped = []
        self._last_sid = None
        self._kana_pieces = {}       # sid -> [(written, its kana or None)] of its kana line (sentence_ruby)
        self.compounds = []
        self._pp_ranges = {}         # passages: token key -> Xに ranges (passage_post_resolve)
        self.stats = Counter()
        self.function_lemmas = set(self.function_lemmas)
        self.function_verbs = set(self.function_verbs)

    # ---- reading passages (passages.py only; the corpus build never reads these)
    passage_join = ""               # unspaced: sentences join without a space
    passage_unspaced = True         # report ws_words: the linked word count
    passage_words_counted = True    # length band: the counted tokens (particles the pack has count)

    _passage_grouped = False        # passages: corpus word groups built (tag_texts, while spec.passage_tagging)
    _passage_grouping = False

    def _passage_corpus_texts(self):
        """The cached corpus texts as stage_tag feeds them to the tagger."""
        from ..core.sources import corpus_path
        from ..core.tag import truecase, truecase_stats
        from ..core.util import Env
        rows = json.loads(gzip.decompress(corpus_path(Env(self)).read_bytes()).decode("utf-8"))["rows"]
        low, cap = truecase_stats(rows, self.word_re, self.sentence_openers)
        return [self.tag_text(truecase(r[1], low, cap, self.word_re)) for r in rows]


    passage_retag_names = True      # passage_retag gets the declared names (no capitals mark them)
    passage_span_glosses = True     # passages.run writes tools/gloss_display.json senses on spans

    def passage_text(self, text, names, lexicon):
        """Passages (Linker.pretag, before tagging): text unchanged; loads
        passage_lemma_alias: each pack alt spelling that belongs to one word
        and is no headword -> that word's lemma (kana みんな: 皆, kanji 所:
        ところ), for classify's lemma fallback."""
        if not self.passage_lemma_alias and self.repo is not None:
            words = json.loads((self.repo / "pack" / "words.json").read_text())
            heads = {w["lemma"] for w in words} | {w["w"] for w in words}
            owners = defaultdict(set)
            for w in words:
                for a in w.get("alt") or ():
                    owners[a].add(w["lemma"])
            self.passage_lemma_alias = {a: next(iter(o)) for a, o in owners.items() if len(o) == 1 and a not in heads}
            # headword -> build groups (passage_retag joins, the conjunction rule)
            self._passage_heads = defaultdict(set)
            for w in words:
                g = PASSAGE_POS_GROUP.get(w.get("pos"))
                if g:
                    self._passage_heads[w["w"]].add(g)
            # voiced after a time word (7時ごろ): the pack's 頃 "around (a time)", which the
            # corpus groups keep apart as ごろ
            if "頃" in heads and "ごろ" not in heads:
                self.passage_lemma_alias.setdefault("ごろ", "頃")
            self._passage_lv = {w["lemma"]: w.get("lv") for w in words}    # passage_post_resolve: counter vs plain noun
        for n in names:
            self.passage_lemma_alias.pop(n, None)     # a declared name is never a pack word (あかり: not 明かり)
        return text

    def passage_retag(self, toks, names=frozenset()):
        """Passages: token rules before resolving (the corpus build never runs
        them). Returns `toks` itself when no rule applies.
        - `_passage_join` first: a kanji numeral + the counter つ is one token
          (一つ, 二つ; a digit numeral like 3つ does not join), and a
          determiner/kanji-numeral + noun joined spelling that is a pack
          headword (その後, 一番) is one token.
        - A declared name is one PROPN token, never a pack word (あかり is not
          明かり "light"; あおば町 split by Sudachi is joined), and takes a
          following NAME_SUFFIX only when the joined form is itself a declared
          name (松本城 in `names`: じょう, not 城 しろ "castle"); otherwise the
          suffix stays its own token and links the pack word normally (松本
          alone declared: 城 is still "castle", as shipped).
        - Grammar, not words (upos X: neither counted nor linked): kana いく/くる
          and ほしい after the te-form (なっていく, 聞こえてくる, 来てほしい; kanji
          行く/来る stay the motion verbs: 歩いて行きました); と + いう (減るという
          問題, 「…」という答え); 後 read ご after その or a number/counter (その後,
          3年後), which the pack has no entry for."""
        toks = self._passage_join(toks)
        out = list(toks)
        name_at = set()
        if names:
            joined, i = [], 0
            longest = max(map(len, names))
            while i < len(out):
                j, acc, hit = i, "", None
                while j < len(out) and len(acc) < longest:
                    acc += out[j][0]
                    j += 1
                    if acc in names:
                        hit = j
                if hit is not None:
                    surf = "".join(t[0] for t in out[i:hit])
                    if hit < len(out) and out[hit][0] in NAME_SUFFIX and surf + out[hit][0] in names:
                        surf += out[hit][0]
                        hit += 1
                    name_at.add(len(joined))
                    joined.append([surf, surf, "PROPN", out[i][3]])
                    i = hit
                else:
                    joined.append(out[i])
                    i += 1
            out = joined
        res, i = [], 0
        while i < len(out):
            t = out[i]
            prev = res[-1] if res else None
            if i not in name_at and prev is not None and self._te_form(prev) and (
                    t[1] in ("欲しい", "ほしい") or
                    (t[1] in ("行く", "いく") and t[0][:1] in ("い", "ゆ")) or
                    (t[1] in ("来る", "くる") and t[0][:1] in ("く", "き", "こ"))):
                res.append([t[0], t[1], "X", t[3]])                # ている-type auxiliary
                i += 1
                continue
            if t[0] == "と" and t[2] in ("PART", "ADP") and i + 1 < len(out) and out[i + 1][0] == "いう":
                res += [[t[0], t[1], "X", t[3]], [out[i + 1][0], out[i + 1][1], "X", out[i + 1][3]]]
                i += 2                                              # という: grammar
                continue
            if t[0] == "後" and prev is not None and (prev[0] == "その" or self._numeric(prev)):
                res.append([t[0], t[1], "X", t[3]])                # その後, 3年後: ご
                i += 1
                continue
            res.append(t)
            i += 1
        return toks if res == list(toks) else res

    @staticmethod
    def _te_form(tok):
        """The te-form particle: て, or で as a conjunctive particle (住んで), not で "at, by"."""
        return tok[0] == "て" or (tok[0] == "で" and "接続助詞" in feats_of(tok[3]).get("Pos", ""))

    @staticmethod
    def _numeric(tok):
        """A numeral, or a counter/duration word (〜年, 〜時間, 〜ヶ月; 以上 after one is
        checked by the caller)."""
        return tok[2] == "NUM" or (tok[1] or "").startswith("〜") or \
            bool(tok[0]) and all(c in NUMERAL_CHARS for c in tok[0])

    _passage_heads = {}             # pack headword -> build groups (passage_text)

    def _passage_join(self, toks):
        """Passages: two tokens Sudachi splits that are one pack word become one
        token (one span, counted once):
        - a kanji numeral + the counter つ: 一つ, 三つ, 四つ are 〜つ (ひとつ,
          みっつ), not 一 "one" (いち) + つ;
        - a determiner or kanji numeral + a noun whose joined spelling is a
          pack headword that is no counter: その + 後 (read ご) is その後, 一 +
          番 is 一番 "most". Digits never join (1番 is the counter, 2つ needs
          no join: つ links on its own, unlike ひとつ/みっつ's irregular reading)."""
        out, i, joined = [], 0, False
        while i < len(toks):
            t = toks[i]
            n = toks[i + 1] if i + 1 < len(toks) else None
            if n is not None and not DIGIT_RE.search(t[0]) and t[2] in ("NUM", "DET") and n[2] in ("NOUN", "NUM"):
                cat = t[0] + n[0]
                ft, fn = feats_of(t[3]), feats_of(n[3])
                rd = ft.get("Read", "") + fn.get("Read", "")
                if t[2] == "NUM" and NUMERAL_RE.match(t[0]) and n[0] == "つ" and n[1] == "〜つ":
                    lemma, upos = "〜つ", "NOUN"
                else:
                    gs = self._passage_heads.get(cat, ())
                    upos = next((g for g in ("NOUN", "ADV", "PRON") if g in gs), None)
                    lemma = cat
                if upos:
                    ms = f"Dict={cat}|Norm={cat}|Read={rd}|DRead={rd}|Pos={fn.get('Pos', '')}"
                    self.stats[f"passage join {cat} -> {lemma}"] += 1
                    out.append([cat, lemma, upos, ms])
                    i += 2
                    joined = True
                    continue
            out.append(t)
            i += 1
        return out if joined else toks

    def _time_amount_before(self, toks, i):
        """A time amount ends right before token i (3年, 1時間, 400年以上,
        100年くらい, どのくらい): 前 after it is "ago/before"."""
        j = i - 1
        while j >= 0 and toks[j][0] in ("くらい", "ぐらい", "以上", "ほど"):
            j -= 1
        if j < 0:
            return False
        if toks[j][0] in ("どの", "どれ", "どのくらい", "どれくらい", "どのぐらい", "どれぐらい"):
            return True
        return re.sub(r"（.*）$", "", toks[j][1]).lstrip("〜") in TIME_UNITS and j > 0 and \
            bool(NUMERAL_RE.match(toks[j - 1][0]))

    def passage_post_resolve(self, toks, out):
        """Passage-only resolve rules (the corpus build never runs them).
        ("pattern", "GRAM") marks grammar that links nothing and is not
        counted (passage_uncounted, passage_fallback_ok); (spelling,
        "NOWORD") a counted word the pack does not have.
        - てほしい: ほしい in auxiliary use after て/で is the pattern "want
          (someone) to", not the adjective 欲しい "wanted".
        - という / っていう before a noun (or の, こと) in kana: the quotative
          "called, that", not 言う "to say". Sentence-final だという
          (hearsay) and kanji と言う人 "people who say" keep 言う.
        - 前 after a time amount (3年前に, 1時間前になる, どのくらい前に) is the
          noun 前 "before, ago" and に the particle, not the adverb 前に
          "previously".
        - 後 read ご (1ヶ月後, 一時間後) is the suffix "after": not 後 (あと).
          その後 is joined in passage_retag.
        - 位 read くらい (どれ位), or after a time counter (三日位), is くらい
          "about", not 位 "rank".
        - a conjunction the pack has only as an adverb links the adverb
          (ただ、"but, only": ただ "only, simply", not ただ "ordinary").
        - a kana word Sudachi folds into another kana lemma (たった -> ただ)
          is its own word, out of the pack.
        - an adverb X + に the build reads as the word Xに (一緒に, 急に, 前に,
          先に): one span over both tokens (passage_phrase_ranges)."""
        out = list(out)
        for i, (surf, lemma, upos, ms) in enumerate(toks):
            f = feats_of(ms)
            pos = f.get("Pos", "")
            prev = toks[i - 1] if i else None
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if upos == "ADJ" and lemma == "欲しい" and "非自立可能" in pos and prev is not None and prev[0] in ("て", "で"):
                out[i] = ("てほしい", "GRAM")
            elif lemma == "言う" and HIRA_ONLY_RE.match(surf) and prev is not None and prev[0] in ("と", "って") and \
                    f.get("Conj", "").startswith("連体形") and nxt is not None and \
                    (nxt[2] in ("NOUN", "PRON", "PROPN") or nxt[0] in ("の", "こと")):
                out[i] = ("という", "GRAM")
            elif surf == "前" and self._time_amount_before(toks, i):
                out[i] = ("前", "NOUN")
                if nxt is not None and nxt[0] == "に" and out[i + 1] is None:
                    out[i + 1] = ("に", "PART")
            elif surf == "後" and hira(f.get("Read", "")) == "ご":
                out[i] = ("〜後", "GRAM")
            elif surf == "位" and (hira(f.get("Read", "")) in ("くらい", "ぐらい") or
                                  (prev is not None and (prev[0] in ("どれ", "どの") or
                                   re.sub(r"（.*）$", "", prev[1]).lstrip("〜") in TIME_UNITS))):
                out[i] = ("くらい", "PART")
            elif upos == "CCONJ" and out[i] is not None and out[i][1] == "CONJ" and \
                    "ADV" in self._passage_heads.get(lemma, ()) and "CONJ" not in self._passage_heads.get(lemma, ()):
                out[i] = (lemma, "ADV")
            elif upos in ("ADV", "NOUN", "PRON", "DET") and HIRA_ONLY_RE.match(surf) and HIRA_ONLY_RE.match(lemma) and \
                    HIRA_ONLY_RE.match(f.get("Dict", "")) and f["Dict"] != lemma:
                out[i] = (f["Dict"], "NOWORD")
        ranges = []
        for i, (surf, lemma, upos, ms) in enumerate(toks[:-1]):
            if out[i] == (lemma + "に", "ADV") and toks[i + 1][0] == "に" and out[i + 1] is None:
                ranges.append((i, i + 1, i))
        self._pp_ranges[tuple((t[0], t[1], t[2]) for t in toks)] = ranges
        # a counter read after a numeral whose plain noun is also a pack word at a
        # lower level links the plain noun (3点: 点 A1 "points", not 〜点 B1)
        lv = getattr(self, "_passage_lv", None) or {}
        rank = {x: k for k, x in enumerate(self.level_ids)}
        for i, r in enumerate(out):
            if r is None or i == 0:
                continue
            prev = toks[i - 1]
            if r[0].startswith("〜") and self._numeric(prev) and not (prev[1] or "").startswith("〜"):
                plain = r[0][1:]
                if plain in lv and r[0] in lv and rank.get(lv[plain], 99) < rank.get(lv[r[0]], 99):
                    out[i] = (plain, "NOUN")
        return out

    def passage_phrase_ranges(self, toks):
        """X + に read as the adverb Xに (passage_post_resolve): one span."""
        return self._pp_ranges.get(tuple((t[0], t[1], t[2]) for t in toks), [])

    def passage_fallback_ok(self, lexicon, reading, word, en=""):
        """A GRAM or NOWORD reading (passage_post_resolve) never falls back to a
        pack word by its surface or an alt spelling (後 read ご is not 後 あと,
        たった is not ただ)."""
        return reading[1] not in ("GRAM", "NOWORD")

    def passage_uncounted(self, toks, resolved):
        """Passages: token indices that are grammar, not words, and are not
        counted for coverage or length when they link nothing (passages.Linker
        .classify): a particle or auxiliary outside the pack (ん, れる, たり,
        けど, って, について), a verb or adjective in auxiliary use after て
        (ている, てしまう, てくる, てほしい), する after the noun it makes a
        verb (勉強する), and the other grammar verbs post_resolve leaves
        unlinked (かもしれない, 〜なさい)."""
        out = set()
        for i, (surf, lemma, upos, ms) in enumerate(toks):
            f = feats_of(ms)
            pos = f.get("Pos", "")
            prev = toks[i - 1] if i else None
            if upos in ("AUX", "PART"):     # classify skips it only when it links nothing (たり, けど)
                out.add(i)
            elif upos in ("VERB", "ADJ") and "非自立可能" in pos and prev is not None and prev[0] in ("て", "で"):
                out.add(i)
            elif resolved[i] is not None and resolved[i][1] == "GRAM":
                out.add(i)      # passage_post_resolve: てほしい, という, 〜後
            elif resolved[i] is None and upos == "VERB" and (
                    (lemma == "する" and prev is not None and prev[2] == "NOUN") or "非自立可能" in pos):
                out.add(i)
        return out

    def __getstate__(self):
        """Pickling (the passages context cache holds this spec through the
        lexicon): the Sudachi tokenizer does not pickle; _tokenizer rebuilds it."""
        d = dict(self.__dict__)
        d["_tok"] = None
        return d

    # ---- tagging (SudachiPy) ---------------------------------------------------
    def tagger_desc(self):
        import sudachipy
        from importlib.metadata import version
        return (f"SudachiPy {sudachipy.__version__}, SudachiDict-core {version('SudachiDict-core')}, "
                f"mode C; ja rules 1")

    def _tokenizer(self):
        if self._tok is None:
            from sudachipy import Dictionary, SplitMode
            self._tok = Dictionary(dict="core").tokenizer(mode=SplitMode.C)
        return self._tok

    def _analyse(self, text):
        """Sudachi tokens of one text, with greetings merged, months joined and
        counters marked: [surface, dict, norm, read, dread, pos6, fixed_lemma|None, ctr]."""
        toks = []
        for m in self._tokenizer().tokenize(text):
            dm = m.dictionary_form_morpheme()
            toks.append([m.surface(), m.dictionary_form(), m.normalized_form(), m.reading_form(),
                         dm.reading_form() if dm is not None else m.reading_form(), tuple(m.part_of_speech()),
                         None, False])
        # fixed greetings split by Sudachi -> one INTJ token
        offs, o = [], 0
        for t in toks:
            offs.append(o)
            o += len(t[0])
        i, out = 0, []
        while i < len(toks):
            merged = False
            for phrase, lemma, alone, upos in PHRASES:
                if not text.startswith(phrase, offs[i]):
                    continue
                end = offs[i] + len(phrase)
                j = next((k for k in range(i, len(toks)) if offs[k] + len(toks[k][0]) == end), None)
                if j is None or (j == i and toks[i][1] == lemma):
                    continue
                if alone:
                    prev_ok = i == 0 or sudachi_upos(toks[i - 1][5]) in ("PUNCT", "SPACE")
                    next_ok = j + 1 >= len(toks) or sudachi_upos(toks[j + 1][5]) in ("PUNCT", "SPACE")
                    if not (prev_ok and next_ok):
                        continue
                rd = "".join(t[3] for t in toks[i:j + 1])
                pos6 = ("副詞", "*", "*", "*", "*", "*") if upos == "ADV" else \
                    ("助詞", "格助詞", "*", "*", "*", "*") if upos == "PART" else ("感動詞", "一般", "*", "*", "*", "*")
                out.append([phrase, lemma, lemma, rd, rd, pos6, lemma, False])
                i = j + 1
                merged = True
                break
            if not merged:
                out.append(toks[i])
                i += 1
        toks = out
        # numeral + 月 (ガツ) -> month name; a noun/suffix after a numeral is a counter
        out = []
        for t in toks:
            prev = out[-1] if out else None
            prev_num = prev is not None and prev[5][1] == "数詞"
            if prev_num and t[0] == "月" and t[3] == "ガツ":
                n = prev[0].translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                num = int(n) if n.isdigit() else KANJI_NUM.get(n)
                if num and 1 <= num <= 12:
                    lem = MONTHS[num - 1]
                    rd = MONTH_READ[num - 1]
                    out[-1] = [prev[0] + t[0], lem, lem, rd, rd, ("名詞", "普通名詞", "一般", "*", "*", "*"), lem, False]
                    continue
            if t[0] in MONTHS and t[6] is None:
                i_m = MONTHS.index(t[0])
                out.append([t[0], MONTHS[i_m], MONTHS[i_m], MONTH_READ[i_m], MONTH_READ[i_m],
                            ("名詞", "普通名詞", "一般", "*", "*", "*"), MONTHS[i_m], False])
                continue
            if prev_num and (t[5][0] == "接尾辞" or (t[5][0] == "名詞" and t[5][2] == "助数詞可能")):
                t[7] = t[1] not in SUFFIX_WORDS         # 十中八九, 一等: no taught suffix after a numeral
            elif t[5][0] == "接尾辞" and t[5][1] == "名詞的" and t[1] in SUFFIX_WORDS:
                pp = prev[5] if prev is not None else None
                if t[1] in HONORIFIC_AFTER_NAME and not (
                        pp is not None and pp[0] == "名詞" and (pp[1] == "固有名詞" or pp[1:3] == ("普通名詞", "一般"))):
                    if t[0] == "君":        # 明日君の車: the pronoun きみ
                        t = ["君", "君", "君", "キミ", "キミ", ("代名詞", "*", "*", "*", "*", "*"), None, False]
                        self.stats["suffix: 君 after a non-name read as the pronoun"] += 1
                elif pp is not None and pp[0] not in SUFFIX_BAD_PREV:
                    t[7] = True
            if t[0] in SURFACE_LEMMA:
                lem, _, rd = SURFACE_LEMMA[t[0]]
                t[6], t[4] = lem, rd
            out.append(t)
        return out

    @staticmethod
    def _bound_suffix(t):
        """A noun-forming suffix that is not a counter or a taught suffix (さ in
        高さ, 者 in 学者, 用): no word of its own."""
        return t[5][0] == "接尾辞" and not t[7] and t[6] is None

    def _atom_key(self, toks, i):
        """(normalised form, UPOS, counter, dictionary-form reading) of token i."""
        t = toks[i]
        return (t[2], sudachi_upos(t[5]) if not t[7] else "NOUN", t[7], hira(READING_FIX.get(t[1], t[4])))

    def tag_texts(self, texts):
        """Two passes: the first builds the word groups (headword, spellings,
        reading) over the whole corpus; the second yields the tagged tokens
        (lazily: the corpus is 230k sentences). See _build_groups."""
        if self.passage_tagging and not self._passage_grouping:
            # passages: the word groups (display lemma per Sudachi atom) come
            # from the corpus plus the passages, as in the build, not from the
            # few hundred passage texts alone (いつ is not 何時 なんじ); built
            # once, never saved (_build_groups)
            texts = list(texts)
            if not self._passage_grouped:
                self._passage_grouping = True
                try:
                    self.tag_texts(self._passage_corpus_texts() + texts)
                finally:
                    self._passage_grouping = False
                self._passage_grouped = True
            return (self._tokens(text) for text in texts)
        atoms = defaultdict(lambda: [Counter(), Counter(), 0])
        kana_verb = Counter()           # (hiragana verb surface, atom key) -> tokens
        for text in texts:
            toks = self._analyse(text)
            for i, t in enumerate(toks):
                if t[6] is not None or DIGIT_RE.search(t[0]) or self._bound_suffix(t):
                    continue
                k = self._atom_key(toks, i)
                if k[1] == "VERB" and HIRA_ONLY_RE.match(t[0]):
                    kana_verb[(t[0], k)] += 1
                a = atoms[k]
                a[0][t[1]] += 1
                a[2] += 1
                aux_use = k[1] == "VERB" and t[5][1] == "非自立可能" and i and toks[i - 1][0] in ("て", "で")
                full = k[1] not in ("VERB", "ADJ", "AUX") or t[5][5] in ("終止形-一般", "連体形-一般")
                if full and not aux_use:
                    a[1][t[0]] += 1
        self._build_groups(atoms)
        # the homophones a kana form stands for (_homophone): verb surfaces by
        # the lemmas Sudachi gives them (いっ: 言う / 行く), noun readings by
        # the kanji words read that way (もと: 元, 基)
        self._kana_verb = defaultdict(Counter)
        for (s, k), n in kana_verb.items():
            if self._lemma_of.get(k):
                self._kana_verb[s][self._lemma_of[k]] += n
        self._spell_n = defaultdict(Counter)
        for k, lem in self._lemma_of.items():
            self._spell_n[lem].update(atoms[k][0])
        self._noun_read = defaultdict(Counter)
        for k, lem in self._lemma_of.items():
            if k[1] == "NOUN" and not k[2] and KANJI_RE.search(lem):
                self._noun_read[k[3]][lem] += atoms[k][2]
        return (self._tokens(text) for text in texts)

    def _build_groups(self, atoms):
        """Atoms (normalised form, UPOS, counter, reading) -> words.
        1. Readings of one normalised form are one word unless both are
           written with the same spelling and the smaller reading holds >= 20%
           of the tokens and >= 20 of them (方: ほう / かた): a reading
           homograph. Other reading variants (potential いただける, noise) fold
           into the main reading.
        2. Groups with the same UPOS and reading whose spellings Wiktionary
           lists as alternative forms of each other are one word (どこ / 何処,
           いつ / 何時, こと / 事); a kana group whose spelling is the reading
           of exactly one kanji group joins it (オレ -> 俺).
        3. The headword is the spelling most used as a full dictionary form
           outside auxiliary uses (くる in ～てくる does not count); an
           interjection keeps its kana spelling when Tatoeba uses it at all.
        4. Two words left with one headword and one UPOS: same reading -> one
           word; else the smaller shows its reading in the lemma (方（かた）)."""
        alias = self._kaikki_alias()["alias"]
        own_def = self._kaikki_alias().get("own", {})
        first_gl = self._kaikki_alias().get("first", {})
        parent = {}

        def find(k):
            while parent.get(k, k) != k:
                k = parent[k]
            return k

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                big, small = (ra, rb) if atoms[ra][2] >= atoms[rb][2] else (rb, ra)
                parent[small] = big
        top_spell = {k: a[0].most_common(1)[0][0] for k, a in atoms.items()}
        by_norm = defaultdict(list)
        for k in atoms:
            by_norm[k[:3]].append(k)
        n_homograph = 0
        sound_split = []
        for nk, ks in by_norm.items():
            # the main reading is the one Sudachi's normal form is written with
            # (信じる, not the literary 信ずる; 頂く, not the potential 頂ける)
            # (信じる, not the literary 信ずる; 頂く, not the potential 頂ける) when
            # it is common itself; else the most used reading (まだ, not いまだ 未だ)
            top_n = max(atoms[k][2] for k in ks)
            ks.sort(key=lambda k: (not (k[0] in atoms[k][0] and atoms[k][2] >= 0.2 * top_n), -atoms[k][2], k))
            main = ks[0]
            kanji_sp = sorted(((c, x) for x, c in atoms[main][0].items() if KANJI_RE.search(x)), reverse=True)
            for k in ks[1:]:
                # the smaller reading written with the main reading's kanji spelling
                # (辛い: からい / つらい; 方: ほう / かた), not a spelling of its own (信ずる)
                sp_ = kanji_sp[0][1] if kanji_sp else top_spell[main]
                n = atoms[k][0][sp_]
                same = sum(atoms[x][0][sp_] for x in ks)
                if k[3][:1] != main[3][:1] and atoms[k][2] >= 10:
                    n_homograph += 1
                    sound_split.append((k, main))
                    continue                  # 捲る: まくる "roll up" / めくる "turn over" (sense check later)
                if KANJI_RE.search(sp_) and n >= 20 and n / same >= 0.2 and k[3] != main[3]:
                    n_homograph += 1
                    continue                  # 訳: やく / わけ, 方: ほう / かた (sense check in bind_lexicon)
                union(main, k)
        # 2. alternative-form and kana-reading merges (same UPOS, counter, reading)
        roots = sorted({find(k) for k in atoms})
        spells = defaultdict(set)
        for k in atoms:
            spells[find(k)].update(atoms[k][0])
            spells[find(k)].add(k[0])
        by_read = defaultdict(list)
        for r in roots:
            by_read[(r[1], r[2], r[3])].append(r)
        def direct(sa, sb):
            # a spelling of one group is a Wiktionary alternative form of a
            # spelling of the other (見る / 観る)
            return any(x in sb for y in sa for x in alias.get(y, ())) or \
                any(x in sa for y in sb for x in alias.get(y, ()))
        for rk, rs in by_read.items():
            if len(rs) < 2:
                continue
            kana = [r for r in rs if all(KANA_ONLY_RE.match(x) for x in spells[r])]
            kanji = [r for r in rs if r not in kana]
            size = lambda r: sum(atoms[k][2] for k in atoms if find(k) == find(r))
            # kanji groups never merge here: Sudachi's normal form already joins
            # true variant spellings (観る -> 見る), and Wiktionary aliases join
            # different words (法 / 方, 撮る / 取る)
            for r in kana:
                # Sudachi normalised this kana group to another word (おる -> 居る,
                # not 折る): it never joins a group of a different normal form
                grp = [k for k in atoms if find(k) == find(r)]
                if not all(KANA_ONLY_RE.match(k[0]) for k in grp) or \
                        any(sp_ in DIALECT_ONLY for k in grp for sp_ in atoms[k][0]):
                    continue
                # a kana word Wiktionary defines in its own right (おる "to be",
                # humble; なし "without") is not a spelling of the kanji word (折る, 梨)
                kpos = set(self.group_kpos.get({"AUX": "VERB", "CCONJ": "CONJ"}.get(rk[0], rk[0]), []))
                own_sp = [sp_ for k in grp for sp_ in atoms[k][0] if set(own_def.get(sp_, ())) & kpos]
                if own_sp:
                    kanji_sp = [x for j in kanji for x in spells[j]]
                    if not any(gloss_words_overlap(first_gl.get(a, {}), first_gl.get(b, {}), kpos)
                               for a in own_sp for b in kanji_sp):
                        continue
                # a kana group joins the one kanji group its Wiktionary entry
                # lists (どこ -> 何処, こと -> 事), or the only kanji group of that
                # reading; とる (取る, 撮る, 採る) stays apart
                roots_k = sorted({find(j) for j in kanji})
                listed = sorted({find(j) for j in kanji if direct(spells[r], spells[j])}, key=lambda j: -size(j))
                if own_sp:
                    # and only a kanji group whose sense it shares: humble おる
                    # "to be" joins 居る (おり, おります), never the bigger 折る
                    listed = [j for j in listed if any(gloss_words_overlap(first_gl.get(a, {}), first_gl.get(b, {}), kpos)
                                                       for a in own_sp for b in spells[j])]
                if len(listed) > 1 and size(listed[0]) >= 0.6 * sum(size(j) for j in listed):
                    listed = listed[:1]           # とる -> 取る (撮る, 採る are rarer)
                # only a kanji group Wiktionary links it to: the lone kanji group of a
                # reading is not enough (なれる, potential of なる, is not 慣れる)
                pick = listed if len(listed) == 1 else []
                if pick and find(r) != pick[0]:
                    union(pick[0], r)
        # 3. headwords
        members = defaultdict(list)
        for k in atoms:
            members[find(k)].append(k)
        head, info = {}, {}
        # a spelling the A1 list names is the headword of the group using it most
        # (いい, not よい; 言う, not いう as in という)
        forced_sp = {w for w, g in self.forced if not w.startswith("〜")}
        owner = {}
        for root, ks in members.items():
            for k in ks:
                for sp_, c in atoms[k][0].items():
                    if sp_ in forced_sp:
                        owner.setdefault(sp_, Counter())[root] += c
        forced_head = {}
        for sp_, cs in owner.items():
            r, c = sorted(cs.items(), key=lambda x: (-x[1], x[0]))[0]
            if c >= 3:
                forced_head.setdefault(r, sp_)
        for root, ks in members.items():
            normal = [k for k in ks if k[0] in atoms[k][0]]
            main_read = max(((sum(atoms[k][2] for k in ks if k[3] == r), r)
                             for r in {k[3] for k in (normal or ks)}))[1]
            full, dic = Counter(), Counter()
            for k in ks:
                dic.update(atoms[k][0])
                if k[3] == main_read:
                    full.update(atoms[k][1])
            best = sorted((full or dic).items(), key=lambda x: (-x[1], x[0]))
            if root[1] == "INTJ":
                best = [x for x in best if HIRA_ONLY_RE.match(x[0]) and x[1] >= 3] or best
            head[root] = forced_head.get(root, best[0][0])
            info[root] = (main_read, sum(atoms[k][2] for k in ks))
        # 4. headword collisions
        by_head = defaultdict(list)
        for root in members:
            by_head[(head[root], root[1], root[2])].append(root)
        lemma_of_root = {}
        for hk, rs in by_head.items():
            rs.sort(key=lambda r: (-info[r][1], r))
            for r in rs[1:]:
                if info[r][0] == info[rs[0]][0]:
                    union(rs[0], r)
        members = defaultdict(list)
        for k in atoms:
            members[find(k)].append(k)
        seen_head = {}
        for root in sorted(members, key=lambda r: (-sum(atoms[k][2] for k in members[r]), r)):
            h = head.get(root) or head[next(k for k in members[root] if k in head)]
            key = (h, root[1], root[2])
            lem = ("〜" if root[2] else "") + h
            if key in seen_head:
                lem = f"{lem}（{info.get(root, (root[3],))[0]}）"
            seen_head.setdefault(key, root)
            lemma_of_root[root] = lem
        self._lemma_of = {k: lemma_of_root[find(k)] for k in atoms}
        self._spellings = defaultdict(set)
        self._reading = {}
        self._norm_lemmas = defaultdict(set)
        for k, lem in self._lemma_of.items():
            self._spellings[lem].update(atoms[k][0])
            self._spellings[lem].add(k[0])
            self._norm_lemmas[k[0]].add(lem)
        self._spelling_lemmas = defaultdict(set)
        for lem, sps in self._spellings.items():
            for sp_ in sps:
                self._spelling_lemmas[sp_].add(lem)
        # one reading per lemma over all its groups (上 NOUN うえ and a rarer 上
        # group read じょう share the lemma: the counts decide, not the last group)
        read_n = defaultdict(Counter)
        for root, ks in members.items():
            for k in ks:
                read_n[lemma_of_root[root]][k[3]] += atoms[k][2]
        for lem, rc in read_n.items():
            self._reading[lem] = max((n, r) for r, n in rc.items())[1]
        self.stats["reading homographs split"] = n_homograph
        # an A1 item spelled other than its word's headword counts as that word
        lemmas = set(self._spellings)
        closed = {w for w, g in self.forced_closed}     # fixed lemmas (五月 is the month, not 皐月)
        remap = []
        for w, g in self.forced:
            if w not in lemmas and w not in closed and len(self._spelling_lemmas.get(w, ())) == 1:
                remap.append((next(iter(self._spelling_lemmas[w])), g))
            else:
                remap.append((w, g))
        self.forced = list(dict.fromkeys(remap))
        # what later stages need, saved beside the tag cache: a build that reuses
        # the cached tags never runs this pass
        norms = defaultdict(set)
        norm_n = defaultdict(Counter)
        for k, lem in self._lemma_of.items():
            norms[lem].add(k[0])
            norm_n[lem][k[0]] += atoms[k][2]
        self._norm_top = {lem: c.most_common(1)[0][0] for lem, c in norm_n.items()}
        # いい / よい: split by first sound, one word if their senses agree (bind_lexicon)
        self._sound_splits = {}
        for k, main in sound_split:
            a, b = self._lemma_of.get(k), self._lemma_of.get(main)
            if a and b and a != b:
                self._sound_splits.setdefault(a, b)
        self._norms = {lem: sorted(v) for lem, v in norms.items()}
        state = {"reading": self._reading, "forced": self.forced, "norms": self._norms, "norm_top": self._norm_top,
                 "sound_splits": self._sound_splits,
                 "stats": {"reading homographs split": n_homograph}}
        from ..core.util import derived_write_ok
        if not derived_write_ok(self):
            return          # passage tagging (corpus + passages) never overwrites the corpus groups file
        with gzip.GzipFile(self._groups_path(), "wb", mtime=0) as g:
            g.write(json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def _groups_path(self):
        from ..core.sources import corpus_path
        from ..core.tag import tagged_path
        from ..core.util import Env
        env = Env(self)
        path, _ = tagged_path(env, corpus_path(env))
        return path.with_name(path.name.replace("tagged_", "ja_groups_").replace(".jsonl.gz", ".json.gz"))

    def _ensure_groups(self):
        """Group state from the tagging pass (this run's, or the saved one)."""
        if self._reading is None:
            path = self._groups_path()
            if not path.exists():
                raise RuntimeError(f"{path.name} missing: delete the cached tagged_* file and rebuild")
            state = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            self._reading = state["reading"]
            self._norms = state["norms"]
            self._norm_top = state.get("norm_top", {})
            self._sound_splits = state.get("sound_splits", {})
            self.forced = [tuple(x) for x in state["forced"]]
            self.stats.update(state["stats"])

    def _tokens(self, text):
        out = []
        toks = self._analyse(text)
        for i, t in enumerate(toks):
            surf, dictf, norm, read, dread, pos, fixed, ctr = t
            upos = sudachi_upos(pos)
            if fixed:
                lemma = fixed
                upos = SURFACE_LEMMA[surf][1] if surf in SURFACE_LEMMA else \
                    "NOUN" if fixed in MONTHS else "ADV" if pos[0] == "副詞" else \
                    "PART" if pos[0] == "助詞" else "INTJ"
            elif DIGIT_RE.search(surf) or self._bound_suffix(t):
                lemma = ""           # 高さ, 学者, 子供用: the suffix is part of the word before it
                upos = "NUM" if upos in ("NUM", "NOUN") else upos
            else:
                k = self._atom_key(toks, i)
                lemma = self._lemma_of.get(k) or (("〜" if ctr else "") + dictf)
            if ctr:
                upos = "NOUN"
            dread = READING_FIX.get(dictf, dread)
            feats = {"Dict": dictf, "Norm": norm, "Read": read, "DRead": dread,
                     "Pos": "-".join(x for x in pos[:3] if x != "*"), "Conj": pos[5] if pos[5] != "*" else ""}
            if ctr:
                feats["Ctr"] = "1"
            out.append((surf, lemma, upos, {k: v.replace("|", "").replace("=", "") for k, v in feats.items() if v}))
        return out

    # ---- Tatoeba indices: curated JMdict lemma per word -----------------------
    def _indices(self):
        if self._idx is None:
            item_re = re.compile(r"^([^(\[{~]+)(?:\(([^)]*)\))?(?:\[\d+\])?(?:\{([^}]*)\})?~?$")
            idx = {}
            path = self.repo / ".cache" / self.indices_file
            if path.exists():
                with tarfile.open(path, "r:bz2") as tf:
                    member = next(m for m in tf.getmembers() if m.name.endswith(".csv"))
                    for raw in io.TextIOWrapper(tf.extractfile(member), encoding="utf-8"):
                        p = raw.rstrip("\n").split("\t")
                        if len(p) < 3 or not p[0].isdigit():
                            continue
                        items = []
                        for it in p[2].split(" "):
                            m = item_re.match(re.sub(r"\(#\d+\)", "", it))
                            if m:
                                items.append((m.group(1), hira(m.group(2) or ""), m.group(3) or m.group(1)))
                        idx[int(p[0])] = items
            self._idx = idx
        return self._idx

    def _idx_homographs(self):
        """(lemma, reading) pairs the indices spell out for >= 20% (and >= 20)
        of the lemma's items: a second reading Sudachi cannot see (it reads
        every 風 かぜ; the indices mark 風(ふう) "style")."""
        if getattr(self, "_idx_hg", None) is None:
            n_all, n_read = Counter(), Counter()
            for items in self._indices().values():
                for lem, rd, sf in items:
                    n_all[lem] += 1
                    if rd:
                        n_read[(lem, rd)] += 1
            self._idx_hg = {k for k, n in n_read.items() if n >= 20 and n / n_all[k[0]] >= 0.2}
        return self._idx_hg

    def extra_wordfreq(self, raw):
        """Only a word's own uses count toward its written frequency: wordfreq
        (MeCab) also counts 的 in 経済的 and 者 in 学者. Each surface's count is
        scaled by its free share in the tagged corpus (的 30 free / 213 bound)."""
        self._group_info()
        # MeCab splits 研究者 and 経済的 where Sudachi keeps one word, so the
        # corpus's bound share understates the inflation: a surface used as a
        # bound suffix gets the written count its free corpus uses predict (the
        # median wordfreq/corpus ratio of the other words)
        ratios = sorted(raw[w] / self._surf_free[w] for w in raw
                        if self._surf_free.get(w, 0) >= 20 and not self._surf_bound.get(w))
        med = ratios[len(ratios) // 2] if ratios else 1.0
        n = 0
        for w in list(raw):
            b, f = self._surf_bound.get(w, 0), self._surf_free.get(w, 0)
            if b >= 10 and b >= 0.1 * (b + f):
                raw[w] = min(raw[w], med * max(f, 1))
                n += 1
        self.stats["written frequency: surfaces discounted for suffix uses"] = n
        # a content word spelled like a grammar form the pack never teaches
        # (照る てる / ている's てる) gets only the count its content uses predict
        n = 0
        for w in list(raw):
            g, c = self._surf_gram.get(w, 0), self._surf_content.get(w, 0)
            if g >= 10 and g >= c:
                raw[w] = min(raw[w], med * max(c, 1))
                n += 1
        self.stats["written frequency: surfaces discounted for grammar homographs (てる)"] = n

    def fix_sentence(self, toks, row, doc):
        toks = self._fix_sentence_idx(toks, row, doc)
        return self._fix_sentence_context(toks, row)

    def _fix_sentence_context(self, toks, row):
        """Readings and names only the sentence context decides.
        - 何時 before です/に/から... is 何時 なんじ "what time", else いつ.
        - 金 in a sentence translated "gold" is not 金 "money": no link.
        - A katakana word Wiktionary also lists as an English name (ビル Bill,
          ジム Jim) is that name when the translation shows it: no link.
        - うまくいく: いく written in kana after うまく is 行く, not 言う.
        - A kana form Sudachi normalizes onto a word of another sound (そら -> それ,
          か(も) -> 彼, いとも -> 最も) keeps the link only when Wiktionary confirms
          it (_variant_confirmed).
        - A katakana word read as a name in the translation (シロ "Shiro" -> 白):
          no link. A loanword keeps it when its own gloss has the word (Piano)."""
        en = (row[3] if len(row) > 3 else "") or ""
        names = self._kaikki_alias().get("names", {})
        fused = self._fused_unlink(toks)
        en_words = self._en_words(en)
        out = []
        drop_nai = False
        off_next = 0
        for i, tok in enumerate(toks):
            surf, lemma, upos, ms = tok
            off, off_next = off_next, off_next + len(surf)
            nxt = toks[i + 1][0] if i + 1 < len(toks) else ""
            prev = toks[i - 1][0] if i else ""
            if i in fused and lemma:
                lemma = ""
                self.stats["context: fused expression parts left unlinked (何もかも, かどうか)"] += 1
            if drop_nai:
                # つまら|ない: the ない (also なさ in つまらなさそう, tagged ADJ) is the
                # adjective's ending: an unlinked AUX, so the word's form spans it.
                # The tokens stay apart: wordfreq counts the stem つまら
                lemma, upos = "", "AUX"
            drop_nai = False
            if lemma and upos in ("VERB", "NOUN") and HIRA_ONLY_RE.match(surf) and \
                    not (lemma in ("言う", "行く") and prev in ("うまく", "上手く")):
                lemma = self._homophone(surf, lemma, upos, ms, en_words)
            if lemma and KANJI_RE.search(surf):
                lemma = self._other_spelling(surf, lemma, ms)
            pms = toks[i - 1][3] if i else ""
            if lemma and prev in WORD_PREFIXES and "Pos=接頭辞" in pms:
                lemma = ""              # 貴職ら: 貴職 "you", not 職 "job"
                self.stats["context: noun after the prefix 貴 left unlinked (貴職)"] += 1
            elif lemma == "者" and HIRA_ONLY_RE.match(surf) and \
                    nxt in ("です", "だ", "でし", "でしょ", "だっ", "だろ", "じゃ", "で", "な"):
                lemma = ""              # 寒がるものです: the ものだ pattern, not 者 "person"
                self.stats["context: ものです / ものだ left unlinked (not 者)"] += 1
            elif lemma == "もと" and surf == "下" and self._ruby_at(row[0], off) == "した":
                lemma = "下"            # 太陽の下で read した in the kana line: the word 下
            elif lemma in ("〜分", "〜分（ぶん）") and i and NUMERAL_RE.match(prev):
                # N分のM is a fraction (ぶん "part"); any other N分 is minutes
                # (４５分の電車, ２、３分, 一分の六十分の一: the 六十 before 分)
                after = "".join(t[0] for t in toks[i + 1:i + 4])
                m_ = re.match(r"の([0-9０-９一二三四五六七八九十百千]+)(.?)", after)
                lemma = "〜分（ぶん）" if m_ and m_.group(2) != "分" else "〜分"
            if surf == "何時":
                f = feats_of(ms)
                if "Src=idx" in ms and hira(f.get("DRead", "")) == "なんじ" or \
                        nxt in ("です", "でし", "だ", "に", "から", "まで", "頃", "ごろ", "ころ", "の", "か"):
                    lemma, upos = "何時", "NOUN"
                    ms = re.sub(r"DRead=[^|]*", "DRead=なんじ", ms)
                self.stats["context: 何時 read なんじ"] += lemma == "何時"
            elif surf == "金" and lemma and re.search(r"\bgold", en, re.I):
                lemma = ""
                self.stats["context: 金 'gold' left unlinked"] += 1
            elif KATA_ONLY_RE.match(surf) and upos == "NOUN" and lemma and \
                    any(re.search(rf"\b{n}\b", en) for n in names.get(surf, ())):
                lemma = ""          # the name, not the word: no link, no count
                self.stats["context: katakana names left unlinked (ビル Bill)"] += 1
            elif lemma == "言う" and prev in ("うまく", "上手く") and surf.startswith("い"):
                lemma = "行く"
                self.stats["context: うまくいく"] += 1
            if lemma and upos in ("NOUN", "PRON", "ADV", "DET", "NUM") and "（" not in lemma and \
                    not lemma.startswith("〜") and not self._variant_confirmed(feats_of(ms).get("Dict", ""), lemma):
                lemma = ""
                self.stats["context: kana form of another sound left unlinked (そら, かも)"] += 1
            neg = self._lexical_negative(toks, i, en) if lemma and upos == "VERB" else None
            if neg:
                # つまらない "boring", くだらない: an adjective of its own. The verb
                # token carries the adjective (a word if it ranks), the ない nothing
                adj, spelled, norm = neg
                lemma, upos, drop_nai = adj, "ADJ", True
                ms = "|".join(kv for kv in ms.split("|") if not kv.startswith(("Dict=", "Norm=", "DRead=", "Pos=", "Conj=")))
                ms = f"Dict={spelled}|Norm={norm}|DRead={adj}|Pos=形容詞-一般" + ("|" + ms if ms else "")
            if lemma and KATA_ONLY_RE.match(surf) and upos != "PROPN" and len(romaji(surf) or "") >= 3 and \
                    self._romaji_name(surf, lemma, en):
                lemma = ""
                self.stats["context: katakana name by romanization left unlinked (シロ Shiro)"] += 1
            out.append([surf, lemma, upos, ms])
        return out

    @staticmethod
    def _same_okuri(a, b):
        """One spelling up to okurigana: the shorter is the longer with a kana
        or two left out, kanji in place (詰らない / 詰まらない; not 見えない /
        見っともない)."""
        if a == b:
            return True
        s, l_ = sorted((a, b), key=len)
        if not 0 < len(l_) - len(s) <= 2 or re.sub(f"[{HIRA}]", "", s) != re.sub(f"[{HIRA}]", "", l_):
            return False
        it = iter(l_)
        return all(ch in it for ch in s)

    def _idx_neg_adj(self):
        """Adjectives ending in ない that Tatoeba's index uses as a lemma (>= 3 items)."""
        if getattr(self, "_neg_adj", None) is None:
            n = Counter(lem for items in self._indices().values() for lem, _, _ in items
                        if lem.endswith("ない") and len(lem) > 2)
            self._neg_adj = sorted(k for k, c in n.items() if c >= 3)
        return self._neg_adj

    def _ruby_at(self, sid, off):
        """The Tatoeba furigana of the segment starting at text offset off, or None."""
        t = self._transcriptions().get(sid)
        if not t:
            return None
        at = 0
        for m in re.finditer(r"\[([^|\]]+)\|([^\]]*)\]|[^\[]", t):
            if m.group(1) is None:
                at += 1
                continue
            if at == off:
                return "".join(m.group(2).split("|"))
            at += len(m.group(1))
        return None

    def _other_spelling(self, surf, lemma, ms):
        """A token written as another word's usual spelling whose dictionary
        form is a rare spelling of its own lemma is that other word: Sudachi
        reads 高価すぎる as the ateji 高価い (たかい) + すぎる; it is 高価 こうか."""
        d = feats_of(ms).get("Dict", "")
        own = self._spell_n.get(lemma)
        if not own or not d or d == surf or own.get(d, 0) >= 0.05 * sum(own.values()):
            return lemma
        others = [(self._spell_n[x].get(surf, 0), x) for x in self._spelling_lemmas.get(surf, ()) if x != lemma]
        n, best = max(others, default=(0, None))
        if best and n >= 10 and not own.get(surf):
            self.stats["context: rare spelling of one word written as another's (高価すぎる)"] += 1
            return best
        return lemma

    def _fused_unlink(self, toks):
        """Indices of the tokens inside a FUSED_UNLINK expression that link nothing."""
        text = "".join(t[0] for t in toks)
        spans = []
        for ph, parts in FUSED_UNLINK.items():
            at = text.find(ph)
            while at >= 0:
                spans.append((at, at + len(ph), parts))
                at = text.find(ph, at + 1)
        out, off = set(), 0
        for i, t in enumerate(toks):
            a, off = off, off + len(t[0])
            for s, e, parts in spans:
                if s <= a and off <= e and (t[0] in parts if parts else t[2] not in ("PART", "AUX", "PUNCT")):
                    out.add(i)
        return out

    @staticmethod
    def _en_words(en):
        """English words with their base forms: simplemma (went -> go, told ->
        tell) plus plain suffix stripping (simplemma gives playing -> playe)."""
        import simplemma
        out = set()
        for w in re.findall(r"[a-z]+", (en or "").lower()):
            out |= {w, simplemma.lemmatize(w, lang="en")}
            for suf, adds in (("ing", ("", "e")), ("ed", ("", "e")), ("ies", ("y",)), ("es", ("",)), ("s", ("",))):
                if w.endswith(suf) and len(w) - len(suf) >= 3:
                    st = w[:-len(suf)]
                    out |= {st + a for a in adds}
                    if len(st) >= 2 and st[-1] == st[-2]:
                        out.add(st[:-1])        # stopped -> stop
                    break
        return out

    _CUE_STOP = set("the a an of to or and in on for with one used as be is it that this not something someone "
                    "somebody sb sth oneself up out into from at by etc such so".split())

    def _cues(self, lem, pos):
        """English words of a lemma's gloss (hand gloss, else Wiktionary's first), lemmatized."""
        g = self.gloss_overrides.get(f"{lem}|{pos}") or \
            (self._kaikki_alias().get("first", {}).get(self.fold(lem)) or {}).get(pos) or ""
        g = re.sub(r"^[^\x00-\x7f]+[,:]?\s*", "", g)          # "取る: to take"
        return self._en_words(g) - self._CUE_STOP

    def _homophone(self, surf, lemma, upos, ms, en_words):
        """A kana form that stands for several words keeps its link only when
        the translation confirms it. Verbs: the lemmas Sudachi gives the
        surface (いって: 言う "say" / 行く "go"; とって: とる / 撮る "photo").
        Nouns: a Tatoeba-index correction to one of several kanji nouns read
        that way (もと: 元 / 基; the index's JMdict 基(もと) covers both).
        The translation confirms the candidates with the most gloss words in
        it; the current lemma wins a tie. Unconfirmed, a verb keeps its lemma
        when that is Sudachi's usual reading of the surface (>= 50%) or an
        index choice that is no rare reading (>= 5%: とれる as とる), else takes
        the dominant one (>= 80%: とって is とる, not the index's 撮る), else
        links nothing (いい線いって: 行く or 言う); an unconfirmed index
        correction of a noun links nothing."""
        idx_plus = "Src=idx+" in ms
        if upos == "VERB":
            seen = self._kana_verb.get(surf) or Counter()
        elif idx_plus:
            seen = self._noun_read.get(hira(feats_of(ms).get("DRead", "")) or surf) or Counter()
        else:
            return lemma
        tot = sum(seen.values())
        cands = {c: n for c, n in seen.items() if n >= 3 and n >= 0.05 * tot}
        cands.setdefault(lemma, seen.get(lemma, 0))
        if len(cands) < 2:
            return lemma
        pos = "verb" if upos == "VERB" else "noun"
        score = {c: len(self._cues(c, pos) & en_words) for c in cands}
        best = max(score.values())
        top_c = [c for c in cands if score[c] == best]
        share = seen.get(lemma, 0) / tot if tot else 0.0
        if best and lemma in top_c:
            new = lemma                 # confirmed (a kana group sharing its gloss ties: あう / 会う)
        elif best and len(top_c) == 1:
            new = top_c[0]
        elif upos == "NOUN":
            new = ""
        elif share >= 0.5 or (idx_plus and share >= 0.05):
            new = lemma                 # Sudachi's usual reading, or an index choice that is no rare one
        else:
            top, n = max(seen.items(), key=lambda x: (x[1], x[0])) if seen else (lemma, 0)
            new = top if tot and n / tot >= 0.8 else ""
        if new != lemma:
            self.stats[f"context: kana homophone {pos} {'relinked' if new else 'left unlinked'} "
                       f"(translation check)"] += 1
        return new

    def _variant_confirmed(self, d, lemma):
        """True unless Dict form d is kana of another sound than the lemma's
        reading and Wiktionary does not tie it to the lemma: a "form of" note, a
        shared first gloss, or an alias listing with no definitions of its own."""
        if not d or not KANA_ONLY_RE.match(d):
            return True
        al = self._kaikki_alias()
        own = [p for p in al.get("own", {}).get(d, ()) if p != "name"]
        rd = (self._reading or {}).get(lemma) or lemma
        if not KANA_ONLY_RE.match(rd) or kana_sound_variant(d, rd, bool(own)):
            return True
        forms = {lemma, rd, hira(rd), *self._norms.get(lemma, ())}
        first = al.get("first", {})
        fd = {p: g for p, g in first.get(d, {}).items() if p != "name"}
        for g in fd.values():
            m = re.search(r"form of (\S+)", g)
            if m and (m.group(1) in forms or hira(m.group(1)) in forms):
                return True
        lg = [g for x in forms for p, g in first.get(x, {}).items() if p != "name"]
        if any(same_sense_words(g, h) for g in fd.values() for h in lg):
            return True
        return not own and bool(forms & set(al.get("alias", {}).get(d, ())))

    def _romaji_name(self, surf, lemma, en):
        """The translation spells the katakana word as a capitalized name."""
        rf = romaji_forms(surf)
        if not any(re.search(rf"\b{r.capitalize()}\b", en) for r in rf):
            return False
        if not KATA_ONLY_RE.match(lemma):
            return True                 # a native word in katakana: シロ Shiro (白)
        first = self._kaikki_alias().get("first", {})
        gl = " ".join(g for x in (surf, lemma) for p, g in first.get(x, {}).items() if p != "name").lower()
        return not any(re.search(rf"\b{r}\b", gl) for r in rf)   # Piano: "piano" keeps

    def _fix_sentence_idx(self, toks, row, doc):
        """Align the sentence's jpn_indices items with the Sudachi tokens. An
        item naming the token's word confirms it (Src=idx). An item naming
        another word the token's spelling can stand for corrects it
        (Src=idx+): a kana homograph (あう -> 会う) or a reading homograph
        (この方(かた) -> 方（かた）). Spelling variants are one word already
        (_build_groups), so they are never "corrected" into each other."""
        items = self._indices().get(row[0])
        if not items or self._spellings is None:
            return toks
        text = row[1]
        spans, cur = [], 0
        for lem, rd, sf in items:
            at = text.find(sf, cur)
            if at < 0:
                continue
            spans.append((at, at + len(sf), lem, rd))
            cur = at + len(sf)
        pos = 0
        out = []
        for tok in toks:
            surf, lemma, upos, ms = tok
            at = text.find(surf, pos)
            if at >= 0:
                pos = at + len(surf)
            if at < 0 or upos not in UPOS_WORD or not lemma:
                out.append(tok)
                continue
            item = next((s for s in spans if s[0] <= at < s[1]), None)
            if item is None:
                out.append(tok)
                continue
            f = feats_of(ms)
            ilem, ird = item[2], item[3]
            cands = {c for c in self._norm_lemmas.get(ilem, set()) | self._spelling_lemmas.get(ilem, set())
                     if not c.startswith("〜")}
            if ird:
                cands = {c for c in cands if hira(self._reading.get(c, "")) == ird} or \
                    ({lemma} if hira(self._reading.get(lemma, "")) == ird else set())
            if lemma in cands or f.get("Norm") == ilem or f.get("Dict") == ilem:
                if ird and KANA_ONLY_RE.match(ird) and hira(f.get("DRead", "")) != ird and \
                        hira(f.get("Dict", "")) != hira(f.get("DRead", "")):
                    ms = re.sub(r"DRead=[^|]*", "DRead=" + ird, ms)    # the curated reading (明日: あした)
                if ird and (ilem, ird) in self._idx_homographs() and not lemma.startswith("〜") and \
                        "（" not in lemma and hira(self._reading.get(lemma, "")) != ird:
                    lemma = f"{lemma}（{ird}）"   # 風（ふう）: kept or folded back by the sense check
                ms = ms + "|Src=idx"
            elif len(cands) == 1:
                c = next(iter(cands))
                dictf = f.get("Dict", "")
                reading = hira(self._reading.get(c, ""))
                if dictf in self._spellings.get(c, ()) or (HIRA_ONLY_RE.match(dictf or "") and hira(dictf) == reading):
                    lemma = c
                    ms = re.sub(r"DRead=[^|]*", "DRead=" + reading, ms) + "|Src=idx+"
            out.append([surf, lemma, upos, ms])
        return out

    def fold(self, s):
        """A reading-homograph lemma (方（かた）) is spelled like its headword."""
        return s.split("（", 1)[0] if s and "（" in s else s

    # ---- lexicon ---------------------------------------------------------------
    def gender_from_entry(self, d):
        """The entry's kana reading (hiragana) is kept in the lexicon's "g"
        slot: the reading picks entries (bind_lexicon) and the pron."""
        w = d.get("word", "")
        for ht in d.get("head_templates", []):
            a = ht.get("args", {})
            n = ht.get("name", "")
            cand = a.get("1") if n in ("ja-noun", "ja-verb", "ja-adj", "ja-verb-suru", "ja-phrase") else \
                a.get("2") if n == "ja-pos" else None
            if cand and JA_RE.search(cand):
                r = clean_reading(cand)
                if KANA_ONLY_RE.match(r):
                    return r
        for f in d.get("forms", []):
            if "canonical" in (f.get("tags") or []) and f.get("ruby"):
                r = ruby_reading(f.get("form", ""), f["ruby"])
                if r:
                    return r
        if KANA_ONLY_RE.match(w):
            return hira(w)
        return None

    def parse_gender(self, g):
        return None, False

    def _clean_sense(self, s):
        gl, hdr, tags, kind = s
        gl = SPELLING_PREFIX_RE.sub("", gl)
        # placeholder dots ("why ... ?", "which .. ?") would end the gloss at
        # the core's sentence split
        gl = re.sub(r"\s*(?:\.{2,}|…)\s*", " ", gl)
        gl = re.sub(r"\s+([?!,;])", r"\1", gl).replace("?", "").strip()
        m = re.match(r"^(?:[a-zū-]+ ){0,3}(?:synonym|form|spelling|short for|clipping|abbreviation|variant) of "
                     r"[^\s(]+ \([^)]*\):\s*(.+)$", gl)
        if m:
            # "synonym of 色々な (iroiro na): various", "short for 会社 (kaisha): company"
            abbrev = re.match(r"^(?:[a-zū-]+ ){0,3}(?:short for|clipping|abbreviation)", gl)
            return [m.group(1), SPELLING_PREFIX_RE.sub("", hdr),
                    [t for t in tags if t not in ("form-of", "alt-of", "abbreviation", "synonym")] +
                    (["ja-abbrev"] if abbrev else []), ""]
        if FORM_LINE_RE.match(gl):
            q = QUOTED_GLOSS_RE.findall(gl)
            tail = gl.rsplit(")", 1)[-1].strip(" ,;") if ")" in gl else ""
            if q:
                gl = tail if tail and re.match(r"^[a-z]", tail) else q[0]
                kind = ""
                tags = [t for t in tags if t not in ("form-of", "alt-of", "abbreviation", "clipping",
                                                     "alternative", "synonym")]
        return [gl, SPELLING_PREFIX_RE.sub("", hdr), tags, kind]

    def _group_info(self):
        """(lemma, group) -> spellings / norms / readings over the tagged corpus
        (rebuilt from the cached corpus, so a cached tag stage needs no state)."""
        if self._info is None:
            from ..core.sources import corpus_path
            from ..core.tag import tagged_path, iter_tagged
            from ..core.util import Env
            env = Env(self)
            path, _ = tagged_path(env, corpus_path(env))
            info = defaultdict(lambda: {"spell": Counter(), "norm": Counter(), "read": Counter(), "upos": Counter(),
                                        "gspell": defaultdict(Counter), "n": 0})
            self._surf_bound, self._surf_free = Counter(), Counter()
            self._surf_gram, self._surf_content = Counter(), Counter()
            self._dict_reads = defaultdict(Counter)     # kanji dictionary spelling -> reading stems
            for sid, toks in iter_tagged(path):
                for i, (surf, lemma, upos, ms) in enumerate(toks):
                    if lemma and KANJI_RE.search(surf):
                        f_ = feats_of(ms)
                        st_ = self._reading_stem(hira(f_.get("DRead", "")), f_.get("Dict", ""))
                        if st_:
                            self._dict_reads[f_.get("Dict", "")][st_] += 1
                    if not lemma and "Pos=接尾辞" in ms and not DIGIT_RE.search(surf):
                        self._surf_bound[surf] += 1
                    elif lemma:
                        self._surf_free[surf] += 1
                    if lemma and upos in ("AUX", "PART", "SCONJ") and lemma not in PARTICLES and \
                            lemma not in AUX_SURFACES:
                        self._surf_gram[surf] += 1      # てる (ている), grammar the pack never teaches
                    elif lemma and upos in ("VERB", "NOUN", "ADJ", "ADV", "PRON"):
                        self._surf_content[surf] += 1
                    if not lemma or upos not in UPOS_WORD:
                        continue
                    f = feats_of(ms)
                    d = info[lemma]
                    # tokens Sudachi tags as the adverb / adjective count as those uses
                    # (あまり is mostly 副詞; its noun-tagged minority must not decide)
                    if upos == "ADV":
                        d["advpos_t"] = d.get("advpos_t", 0) + 1
                    elif upos == "ADJ":
                        d["adjpos_t"] = d.get("adjpos_t", 0) + 1
                    if upos == "NOUN" and ("副詞可能" in f.get("Pos", "") or "形状詞可能" in f.get("Pos", "")):
                        nxt = toks[i + 1] if i + 1 < len(toks) else None
                        kind = "adv" if "副詞可能" in f["Pos"] else "adj"
                        d[kind + "pos"] = d.get(kind + "pos", 0) + 1
                        if kind == "adv" and nxt is not None and nxt[2] not in ("PART", "AUX", "PUNCT", "NOUN"):
                            d["advuse"] = d.get("advuse", 0) + 1
                        if kind == "adj" and nxt is not None and nxt[2] == "AUX" and nxt[1] in ("だ", "です"):
                            d["adjuse"] = d.get("adjuse", 0) + 1
                    d["spell"][f.get("Dict", surf)] += 1
                    d["norm"][f.get("Norm", "")] += 1
                    d["read"][hira(f.get("DRead", ""))] += 1
                    d["upos"][upos] += 1
                    d["gspell"][{"AUX": "VERB", "CCONJ": "CONJ"}.get(upos, upos)][f.get("Dict", surf)] += 1
                    d["n"] += 1
            self._info = dict(info)
            # one POS per such noun: the use that dominates (いつも ADV, 元気 ADJ,
            # 仕事 NOUN); a forced key keeps its POS
            forced = {w: g for w, g in self.forced}
            pref = {}
            for lem, d in self._info.items():
                if lem in forced:
                    pref[lem] = forced[lem]
                elif not (d.get("advpos") or d.get("adjpos")):
                    continue
                elif d.get("advpos", 0) + d.get("advpos_t", 0) >= 5 and \
                        (d.get("advuse", 0) + d.get("advpos_t", 0)) / (d.get("advpos", 0) + d.get("advpos_t", 0)) >= 0.5:
                    pref[lem] = "ADV"
                elif d.get("adjpos", 0) + d.get("adjpos_t", 0) >= 5 and \
                        (d.get("adjuse", 0) + d.get("adjpos_t", 0)) / (d.get("adjpos", 0) + d.get("adjpos_t", 0)) >= 0.4:
                    pref[lem] = "ADJ"
                elif d.get("advpos") or d.get("adjpos"):
                    pref[lem] = "NOUN"
            self._noun_pref = pref
        return self._info

    def _kaikki_alias(self):
        """From the kaikki extract (cached in .cache/derived): spelling ->
        headwords that list it as an alternative form or soft-redirect to
        (広い -> ひろい, 何 -> なに), and kana reading -> kanji headwords with
        that reading (やめる -> 止める, 辞める), for kana lemmas Sudachi does
        not normalise to kanji."""
        if getattr(self, "_alias_memo", None) is not None:
            return self._alias_memo
        self._alias_memo = self._kaikki_alias_load()
        return self._alias_memo

    def _kaikki_alias_load(self):
        import gzip
        import hashlib
        from ..core.sources import kaikki_plain
        from ..core.util import Env, file_sig
        env = Env(self)
        plain = kaikki_plain(env)
        sig = hashlib.sha1(f"alias5|{file_sig(plain)}".encode()).hexdigest()[:10]
        path = env.derived / f"ja_alias_{sig}.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        alias, by_read, names, own = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(set)
        first = defaultdict(dict)      # word -> {pos: first gloss}
        generic = {"A", "An", "The", "English", "Japanese", "American", "British", "French", "German",
                   "Chinese", "Korean", "Russian", "Spanish", "Italian", "Dutch", "Latin", "Greek"}
        with open(plain, encoding="utf-8") as f:
            for line in f:
                if '"lang_code": "ja"' not in line:
                    continue
                d = json.loads(line)
                w, pos = d.get("word", ""), d.get("pos", "")
                if not self.lex_word_re.match(w):
                    continue
                if pos == "soft-redirect":
                    for r in d.get("redirects") or []:
                        if self.lex_word_re.match(r) and r != w:
                            alias[w].add(r)
                    continue
                if pos == "name" and KATA_ONLY_RE.match(w):
                    for sn in d.get("senses", []):
                        for g in sn.get("glosses") or []:
                            names[w].update(x for x in re.findall(r"\b[A-Z][a-z]+\b", g) if x not in generic)
                if pos in JUNK_POS or not any(s.get("glosses") for s in d.get("senses", [])):
                    continue
                g0 = next((s["glosses"][0] for s in d["senses"] if s.get("glosses")), "")
                if g0 and pos not in first[w]:
                    first[w][pos] = g0
                if KANA_ONLY_RE.match(w) and any(s.get("glosses") and not re.match(
                        r"(?i)(alternative|hiragana|katakana) (form|spelling)|kana spelling|potential",
                        s["glosses"][0]) for s in d["senses"]):
                    own[w].add(pos)
                for fm in d.get("forms", []):
                    t = set(fm.get("tags") or [])
                    a = fm.get("form", "")
                    if "alternative" in t and self.lex_word_re.match(a) and a != w and \
                            not t & {"obsolete", "historical", "rare", "kyūjitai"}:
                        alias[a].add(w)
                r = self.gender_from_entry(d)
                if r and KANJI_RE.search(w):
                    by_read[r].add(w)
        out = {"alias": {k: sorted(v) for k, v in sorted(alias.items())},
               "reading": {k: sorted(v) for k, v in sorted(by_read.items())},
               "names": {k: sorted(v) for k, v in sorted(names.items())},
               "own": {k: sorted(v) for k, v in sorted(own.items())},
               "first": {k: first[k] for k in sorted(first)}}
        env.derived.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(path, "wb", mtime=0) as g:
            g.write(json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return out

    def bind_lexicon(self, lx):
        self._ensure_groups()
        """Clean the Japanese Wiktionary lexicon and point each corpus lemma at
        the entries of its spellings whose reading the corpus uses."""
        self._lx = lx
        self._orig_E = {}
        E = lx.E
        for word in list(E):
            ents = []
            for e in E[word]:
                if e["p"] in JUNK_POS:
                    continue
                e["s"] = [self._clean_sense(s) for s in e["s"]]
                if e.get("g"):
                    e["g"] = hira(e["g"])       # ほゞ -> ほぼ
                ents.append(e)
            E[word] = ents
        info = self._group_info()
        ka = self._kaikki_alias()
        alias, by_read = ka["alias"], ka["reading"]
        n_alias = n_read = n_unmarked = 0
        new = {}
        for lemma, d in sorted(info.items()):
            ctr = lemma.startswith("〜")
            base = self.fold(lemma[1:] if ctr else lemma)
            if lemma in DIALECT_ONLY:
                self.drop_keys = {**self.drop_keys, **{(lemma, g): None for g in DIALECT_ONLY[lemma]}}
            if ctr and d["n"] < 20 and (lemma, "NOUN") not in self.fixed_gloss:
                self.drop_keys = {**self.drop_keys, (lemma, "NOUN"): None}    # rare suffix readings: parser noise
            spells = [base] + [s for s, _ in d["spell"].most_common() if s != base] + \
                     [s for s, _ in d["norm"].most_common() if s]
            # a kana spelling's aliases are every kanji word read that way (おう: 負う,
            # 追う, 王 ...): a kanji lemma follows only its kanji spellings' aliases
            spells += [a for s in list(spells) for a in alias.get(s, [])
                       if KANJI_RE.search(s) or not KANJI_RE.search(base)]
            tot = sum(d["read"].values()) or 1
            # readings under 20% are not a second entry (brief rule), so their
            # senses do not gloss the word (辛い: つらい, not からい)
            ok_read = {r for r, c in d["read"].items() if c / tot >= 0.2}

            def gather(spellings):
                seen, got = set(), []
                for s in dict.fromkeys(spellings):
                    for e in E.get(s, []):
                        if id(e) in seen:
                            continue
                        if ctr and e["p"] not in ("counter", "suffix", "noun"):
                            continue
                        if e.get("g") and ok_read and e["g"] not in ok_read and not (
                                KATA_ONLY_RE.match(base) and hira(base) == e["g"]):
                            continue
                        seen.add(id(e))
                        got.append(e)
                return got
            top = d["upos"].most_common(1)[0][0] if d["upos"] else "NOUN"
            if self._noun_pref.get(lemma) == "NOUN" and not ctr:
                # an adverbial/adjectival noun (Sudachi 副詞可能) whose own
                # Wiktionary entries have no noun sense is that adverb/adjective:
                # ほぼ "almost" (not the homophone 保母 "childcare worker")
                own = {e["p"] for e in E.get(base, []) if any(sn[3] == "" for sn in e["s"])}
                if own and "noun" not in own:
                    alt_g = "ADV" if "adv" in own else "ADJ" if "adj" in own else None
                    if alt_g and (lemma, "NOUN") not in self.forced:
                        self._noun_pref[lemma] = alt_g
                        top = alt_g
            top = self._noun_pref.get(lemma, top) if top in ("NOUN", "ADJ", "ADV") else top
            kp = self.group_kpos.get({"AUX": "VERB", "CCONJ": "CONJ"}.get(top, top), [])
            covers = lambda es: any(e["p"] in kp and any(sn[3] == "" for sn in e["s"]) for e in es)
            ents = gather(spells)
            if KANA_ONLY_RE.match(base) and not ctr:
                # a kana word's own Wiktionary entries win over kanji homophones
                # (ジム gym, not 事務; さっき "a while ago", not 殺気). A katakana
                # word never takes a kanji word's senses.
                own = gather([base] + ([x for x in spells if KATA_ONLY_RE.match(x)] if KATA_ONLY_RE.match(base) else []))
                if not covers(own) and top in ("NOUN", "ADJ", "ADV"):
                    for g2 in [x for x in ("ADV", "ADJ", "NOUN") if x != top]:
                        kp2 = self.group_kpos.get(g2, [])
                        if any(e["p"] in kp2 and any(sn[3] == "" for sn in e["s"]) for e in own) and \
                                (lemma, top) not in self.forced:
                            top, kp = g2, kp2
                            self._noun_pref[lemma] = g2
                            break
                if covers(own) or (KATA_ONLY_RE.match(base) and own):
                    if [id(e) for e in own] != [id(e) for e in ents]:
                        self.stats["kana words glossed from their own entries only"] += 1
                    ents = own
            if KANJI_RE.search(base):
                # a kanji word's kana spelling also names its homophones (おう: 負う,
                # 追う): its kanji spellings' own entries win when they cover its POS
                own = gather([x for x in spells if KANJI_RE.search(x)])
                if covers(own):
                    ents = own
            if KANA_ONLY_RE.match(base) and not KATA_ONLY_RE.match(base) and \
                    not any(e["p"] in kp and any(sn[3] == "" for sn in e["s"]) for e in ents):
                # a kana lemma Sudachi leaves in kana (やめる, かける) whose own
                # entries do not cover its corpus POS: the kanji headwords read that way
                # only entries of the corpus POS: a kanji homophone of another
                # POS would relabel the word (ほぼ adv is not 保母 noun)
                more = [e for e in gather(by_read.get(hira(base), [])) if e["p"] in kp]
                n_read += bool(more)
                ents += [e for e in more if e not in ents]
            # a pure potential form (話せる) counts as its verb; one with a meaning
            # of its own (入れる "to put in", 売れる "to sell well", 慣れる) is a word
            own_defs = [sn for e in E.get(lemma, []) if e["p"] == "verb" for sn in e["s"] if sn[3] == ""]
            pots = [re.match(r"^potential (?:form )?of ([^\s(;,]+)", sn[0]) for sn in own_defs]
            if own_defs and all(pots):
                tgt = pots[0].group(1)
                if tgt in info and tgt != lemma and all(m.group(1) == tgt for m in pots):
                    self.redirect[lemma] = tgt
            if d["n"] >= 50:
                # a word this common is not literary/archaic-only for a learner
                # (なぜ is tagged formal, literary, poetic)
                fixed = []
                for e in ents:
                    defs = [sn for sn in e["s"] if sn[3] == ""]
                    if defs and all(set(sn[2]) & lx.marked for sn in defs):
                        e = dict(e, s=[[sn[0], sn[1], [t for t in sn[2] if t not in lx.marked], sn[3]]
                                       for sn in e["s"]])
                        n_unmarked += 1
                    fixed.append(e)
                ents = fixed
            # an entry whose every sense is an abbreviation (大: "short for 大学")
            # comes after the others
            ents.sort(key=lambda e: all("ja-abbrev" in sn[2] for sn in e["s"] if sn[3] == "") and
                      any(sn[3] == "" for sn in e["s"]))
            if ctr:
                ents.sort(key=lambda e: e["p"] not in ("counter", "suffix"))
            if ents:
                new[lemma] = ents
                if [id(e) for e in ents] != [id(e) for e in E.get(lemma, [])]:
                    n_alias += 1
        # a reading homograph (訳（やく）) stays a word of its own only when its
        # Wiktionary senses share no word with the headword's (金: きん/かね both
        # "money" -> one word; 方: ほう "direction" / かた "person" -> two)
        stop = {"the", "a", "an", "of", "to", "or", "and", "in", "on", "for", "with", "one", "used", "as",
                "something", "someone", "that", "is", "be", "by", "from", "which", "who"}

        def words_of(lem):
            # the first three senses of the first full entry read the lemma's way
            m_rd = re.search(r"（(.+)）$", lem)
            rd = m_rd.group(1) if m_rd else hira(self._reading.get(lem, ""))
            e = next((e for e in new.get(lem, []) if e.get("g") == rd and
                      e["p"] not in ("name", "character", "affix", "suffix", "prefix", "phrase")), None)
            out = set()
            for sn in [x for x in (e or {"s": []})["s"] if x[3] == ""][:3]:
                out |= {re.sub(r"(?<=[a-z]{3})s$", "", x)          # years ~ year
                        for x in re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", "", sn[0].lower()))} - stop
            return out
        for lemma in sorted(new):
            if "（" in lemma:
                base = self.fold(lemma)
                wl, wb = words_of(lemma), words_of(base)
                if base in new and (not wl or not wb or wl & wb):
                    self.redirect[lemma] = base
        # a word split off by its first sound (よい from いい) is the same word
        # when its senses agree
        # a kana word and a kanji word with one reading and one meaning are one
        # word in two spellings (せい / 所為, かける / 掛ける): the less used one
        # counts toward the other
        closed = {w for w, g in self.forced_closed}

        def top_g(lem):
            up = info.get(lem, {}).get("upos") or Counter()
            g = up.most_common(1)[0][0] if up else "NOUN"
            return self._noun_pref.get(lem, {"AUX": "VERB", "CCONJ": "CONJ", "SCONJ": "CONJ"}.get(g, g))

        def primary(lem, g):
            label = {"NOUN": "noun", "VERB": "verb", "ADJ": "adj", "ADV": "adv"}.get(g, g.lower())
            ov = self.gloss_overrides.get(f"{lem}|{label}")
            txt = ov.split(";")[0] if ov else ""
            if not txt:
                kp_ = self.group_kpos.get(g, [])
                rd = hira(self._reading.get(lem, ""))
                e = next((e for e in new.get(lem, []) if e["p"] in kp_ and (not e.get("g") or e["g"] == rd)
                          and any(sn[3] == "" for sn in e["s"])), None)
                txt = next((sn[0] for sn in e["s"] if sn[3] == ""), "") if e else ""
            return txt
        forced_l = {w for w, g in self.forced}

        def same_sense(a, b):
            # either word's POS: 何時も (noun) and いつも (adv) are both "always"
            gs = {top_g(a), top_g(b)}
            return any(same_sense_words(primary(a, g), primary(b, g)) for g in gs)
        # a word split off by its first sound (よい from いい) is the same word
        # when its primary senses agree (めくる "turn over" is not まくる "roll up")
        for a, b in sorted(self._sound_splits.items()):
            if a in new and b in new and a not in self.redirect and b not in self.redirect and \
                    a not in DIALECT_ONLY and b not in DIALECT_ONLY and same_sense(a, b):
                na, nb = info.get(a, {}).get("n", 0), info.get(b, {}).get("n", 0)
                src, dst = (a, b) if (b in forced_l or nb >= na) and a not in forced_l else (b, a)
                self.redirect[src] = dst
                self.sound_folded.append(f"{src} -> {dst}")
        by_rd = defaultdict(list)
        for lem in new:
            if lem in self.redirect or lem.startswith("〜") or "（" in lem or lem in DIALECT_ONLY:
                continue
            g0 = top_g(lem)
            # adverbial nouns: いつも (adv) and 何時も (noun) are one word
            by_rd[(hira(self._reading.get(lem, "")), "NOM" if g0 in ("NOUN", "ADV", "ADJ") else g0)].append(lem)
        for (rd, g), lems in sorted(by_rd.items()):
            kana = [l for l in lems if KANA_ONLY_RE.match(l)]
            kanji = [l for l in lems if KANJI_RE.search(l)]
            for a in kana:
                for b in kanji:
                    if a in self.redirect or b in self.redirect:
                        continue
                    na, nb = info.get(a, {}).get("n", 0), info.get(b, {}).get("n", 0)
                    if min(na, nb) < 3:
                        continue            # both must be in real use to be two cards
                    # Sudachi normalises the kana to another kanji word (ふり -> 振り, not 不利)
                    top_norm = self._norm_top.get(a, a)
                    if KANJI_RE.search(top_norm) and top_norm != b:
                        continue
                    if not same_sense(a, b):
                        continue
                    src, dst = (a, b) if (b in forced_l or nb >= na) and a not in forced_l else (b, a)
                    if src in closed:
                        continue
                    self.redirect[src] = dst
                    for k2, v2 in list(self.redirect.items()):
                        if v2 == src:
                            self.redirect[k2] = dst       # no chains
                    self.spelling_merges.append(f"{src} -> {dst}")
        self.stats["reading homographs folded back (shared sense)"] = sorted(k for k in self.redirect if "（" in k)
        self.stats["reading homographs kept"] = sorted(k for k in new if "（" in k and k not in self.redirect)
        # closed-set words carry a hand gloss: a synthetic first entry makes
        # sure the word exists whatever its Wiktionary senses clean to
        for (lem, g), gloss in sorted(self.fixed_gloss.items()):
            kp = self.group_kpos.get(g, ["noun"])[0]
            rd = info.get(lem, {}).get("read")
            reading = rd.most_common(1)[0][0] if rd else (MONTH_PRON.get(lem) or None)
            syn = {"p": kp, "s": [[re.sub(r"[()]", "", gloss), "", [], ""]], "ht": set()}
            if reading:
                syn["g"] = reading
            new.setdefault(lem, list(E.get(lem, [])))
            new[lem] = [syn] + [e for e in new[lem] if e.get("p") != kp or e.get("s") != syn["s"]]
        for k in new:
            self._orig_E[k] = [dict(e, g=hira(e["g"])) if e.get("g") else e for e in E.get(k, [])]
        E.update(new)
        self.stats["lemmas pointed at other spellings' entries"] = n_alias
        self.stats["kana lemmas glossed from kanji headwords of the same reading"] = n_read
        self.stats["common lemmas whose only senses were marked literary/archaic"] = n_unmarked

    # ---- resolution --------------------------------------------------------------
    def _usable(self, lemma, group):
        k = (lemma, group)
        if k not in self._res_cache:
            ok = k in self.fixed_gloss or bool(self._lx.usable_entries(lemma, self.group_kpos.get(group)))
            self._res_cache[k] = ok
        return self._res_cache[k]

    def cross_pos_link(self, lexicon, lem, group, key_to_id):
        """A lemma read with a POS the pack has no entry for links the pack
        word of the same lemma (いつも NOUN/ADV, 元気 NOUN/ADJ are one word
        unless the second-entry rule kept both)."""
        for g in ("NOUN", "ADJ", "ADV", "VERB", "PRON", "DET", "NUM", "INTJ", "CONJ", "PART"):
            if g != group and (lem, g) in key_to_id:
                return key_to_id[(lem, g)]
        return None

    def surface_link_ok(self, tok):
        return tok[2] == "INTJ"

    def post_resolve(self, toks, out):
        """The tagged lemma is the word (the core's surface rules are for
        spaced scripts): drop grammar tokens, keep one (lemma, group) per
        content token."""
        res = []
        skip = set()
        for i, (surf, lemma, upos, ms) in enumerate(toks):
            if i in skip:
                res.append(None)
                continue
            if upos in ("PUNCT", "SYM", "X", "SPACE") or not lemma:
                res.append(None)
                continue
            if upos == "PROPN":
                res.append((lemma, "PROPN"))
                continue
            if lemma in POTENTIAL_OF and prev_tok(toks, i) is not None and \
                    (prev_tok(toks, i)[0] in ("に", "と") or
                     (prev_tok(toks, i)[2] == "ADJ" and prev_tok(toks, i)[0].endswith("く"))):
                res.append((POTENTIAL_OF[lemma], "VERB"))   # 先生になれる: なる "can become"
                continue
            lemma = self.redirect.get(lemma, lemma)
            fs = self._foreign_spell.get(lemma)
            if fs and feats_of(ms).get("Dict", surf) in fs:
                # 時間があったら寄ります: 寄る, not よる "to depend on" (note_words;
                # set for the sentence stage only, so frequencies are untouched)
                self.stats["links through a kanji spelling of another word dropped (寄る/よる)"] += 1
                res.append(None)
                continue
            g = {"AUX": "VERB", "CCONJ": "CONJ", "SCONJ": "CONJ"}.get(upos, upos)
            prev = next((t for t in reversed(toks[:i]) if t[2] != "SPACE"), None)
            if upos == "AUX":
                if lemma == "ない" and surf == "ない" and i + 1 < len(toks) and toks[i + 1][0] == "て":
                    # no ない form is ないて: 聞いてないていました is 泣いて misparsed
                    self.stats["impossible ない+て left unlinked (泣いて in kana)"] += 1
                    res.append(None)
                    continue
                res.append((lemma, "VERB") if surf in AUX_SURFACES.get(lemma, ()) else None)
                continue
            if upos == "PART":
                if lemma == "で" and "接続助詞" in feats_of(ms).get("Pos", ""):
                    lemma = "て"            # 住んで, 読んで: the te-form, not で "at, by"
                res.append((lemma, "PART") if lemma in PARTICLES else None)
                continue
            f = feats_of(ms)
            if upos == "VERB" and "非自立可能" in f.get("Pos", "") and prev is not None and \
                    prev[0] in ("て", "で") and lemma not in AUX_VERB_KEEP:
                res.append(None)            # ている, てしまう, てみる: grammar, not the verb
                continue
            if lemma in ("行く", "いけない") and surf.startswith("いけ") and prev is not None and \
                    prev[0] in ("は", "ちゃ", "じゃ", "ば", "と", "ては", "では", "なきゃ", "なくては", "なければ"):
                res.append(None)            # 泳いではいけない "must not", ければいけない "must": grammar, not 行く
                continue
            if any(lemma == n_ and (p_ is None or (prev is not None and prev[0] == p_)) and
                   (x_ is None or "".join(t[0] for t in toks[i + 1:i + 3]).startswith(x_))
                   for n_, p_, x_ in IDIOM_UNLINK):
                self.stats["idiom noun left unlinked (実を結ぶ, 主として)"] += 1
                res.append(None)
                continue
            if lemma == "よる" and upos == "VERB" and HIRA_ONLY_RE.match(surf) and (prev is None or prev[0] != "に"):
                # kana よる is 因る only after に (によって, によると): 来ないよりまし is
                # the particle より, 思いもよらない is 寄る
                self.stats["kana よる outside に... left unlinked"] += 1
                res.append(None)
                continue
            if upos == "VERB" and prev is not None and prev[0] == "に" and surf in COMPOUND_PARTICLE_VERBS and \
                    (COMPOUND_PARTICLE_VERBS[surf] is None or
                     (i + 1 < len(toks) and toks[i + 1][0] in COMPOUND_PARTICLE_VERBS[surf])):
                self.stats["compound particle verb left unlinked (において)"] += 1
                res.append(None)            # 責任において "on (my) responsibility": grammar, not 置く
                continue
            if lemma == "知れる" and i >= 2 and toks[i - 1][0] == "も" and toks[i - 2][0] == "か":
                self.stats["かもしれない left unlinked (grammar, not 知れる)"] += 1
                res.append(None)            # 壊れるかもしれない "might break": grammar, not 知れる "to become known"
                continue
            if upos == "VERB" and lemma == "なさる" and prev is not None and prev[2] == "VERB":
                res.append(None)            # やめなさい: the imperative ending
                continue
            if upos == "VERB" and lemma == "する" and prev is not None and prev[2] == "NOUN":
                res.append(None)            # 勉強する: the noun is the word
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            modified = prev is not None and (prev[2] in ("VERB", "AUX", "ADJ", "DET") or prev[0] == "の")
            if nxt is not None and nxt[0] == "に" and upos in ("NOUN", "ADJ", "ADV") and not modified and \
                    self._usable(lemma + "に", "ADV"):
                # a noun a clause modifies stays the noun: 行くことに (not 殊に "especially"),
                # 来た時に (not 時に "sometimes"), 寝る前に
                res.append((lemma + "に", "ADV"))       # 本当に, 一緒に: the adverb, に absorbed
                skip.add(i + 1)
                continue
            pref = self._noun_pref.get(lemma)
            if upos in ("NOUN", "ADJ", "ADV") and pref and pref != g and self._usable(lemma, pref):
                res.append((lemma, pref))       # one POS per lemma: いつも ADV, 元気 ADJ
                continue
            if self._usable(lemma, g):
                res.append((lemma, g))
                continue
            alt = {"NOUN": ("ADJ", "ADV", "PRON"), "ADJ": ("ADV", "NOUN", "DET"), "ADV": ("ADJ", "NOUN"),
                   "PRON": ("NOUN", "ADV"), "DET": ("ADJ", "PRON"), "NUM": ("NOUN",), "CONJ": ("ADV",),
                   "INTJ": ("ADV", "NOUN")}.get(g, ())
            if g == "INTJ":
                up = (self._info or {}).get(lemma, {}).get("upos")
                if not up or up.most_common(1)[0][0] == "INTJ":
                    res.append((lemma, g))  # a word mostly used as a filler (う, うっ) is not a noun
                    continue
            g2 = next((x for x in alt if self._usable(lemma, x)), None)
            res.append((lemma, g2 or g))    # unresolved content: counts, never a word
        return res

    FORM_NOTE_RE = re.compile(r"(?i)(alternative|obsolete|dated|rare|classical|synonym|kanji|archaic|"
                              r"nonstandard)\b.*\b(form|spelling|of)\b")

    def _foreign_sense(self, w, spelling, en=None):
        """A kanji spelling of a kana headword whose Wiktionary first gloss (for
        the word's POS) shares no word with the word's gloss is another word
        (よる "to depend on" is not 寄る "to drop by"; なし "without" is not 梨)."""
        fg = self._kaikki_alias().get("first", {}).get(spelling, {})
        kp = self.group_kpos.get({"verb": "VERB", "adj": "ADJ", "adv": "ADV", "pron": "PRON"}.get(w["pos"], "NOUN"),
                                 ["noun"])
        gl = [v for k, v in fg.items() if k in kp]
        en = en or w["en"]
        return bool(gl) and not any(self.FORM_NOTE_RE.match(g) or gloss_words(g) & gloss_words(en) for g in gl)

    def note_words(self, words):
        """Kanji spellings that are another word, per kana headword (post_resolve):
        Sudachi gives the spelling its own normal form (寄る), which is not the
        word's main one (よる), and Wiktionary's sense disagrees. A spelling
        Sudachi normalises the kana to (かわいい -> 可愛い) is the word itself."""
        info = self._group_info()
        self._foreign_spell = {}
        for w in words:
            lem = w["_key"][0]
            # katakana is the usual spelling of plant and animal names (バラ 薔薇)
            if not HIRA_ONLY_RE.match(w["w"]) or w["pos"] in ("counter", "aux", "part"):
                continue
            d = info.get(lem, {})
            norms, top = d.get("norm") or {}, self._norm_top.get(lem)
            en = self.gloss_overrides.get(f"{lem}|{w['pos']}") or self.gloss_overrides.get(lem) or w["en"]
            bad = {sp_ for sp_ in (d.get("spell") or {})
                   if KANJI_RE.search(sp_) and sp_ != top and sp_ in norms and self._foreign_sense(w, sp_, en)}
            if bad:
                self._foreign_spell[lem] = bad
        self.foreign_spellings = sorted(f"{k}: {' '.join(sorted(v))}" for k, v in self._foreign_spell.items())

    def _lexical_negative(self, toks, i, en):
        """The verb + ない Wiktionary defines as an adjective whose sense is not
        the verb's (詰まらない "boring" vs 詰まる "to be blocked", 下らない
        "pointless", 済まない): (adjective in kana, spelling, normal form), else
        None. The adjective's sense comes from the spelling of the verb's normal
        form when Wiktionary has it (来ない is only "negative of 来る": the kana
        こない "this kind" is another word); a kana spelling counts only when
        Wiktionary has no such entry (たまらない). ならない stays なる:
        〜なければならない is grammar taught with the verb. 足りない "not
        enough" shares 足りる's sense: kept. The translation decides the rest:
        見えない "can't see", 行けない "can't go" keep the verb when the English
        has its sense. The ない may run on (つまらなかった, つまらなさそう)."""
        nxt = toks[i + 1][0] if i + 1 < len(toks) else ""
        if not re.match("^(?:な[いかくけさ]|ね[えー])", nxt):
            return None
        surf, lemma, _, ms = toks[i]
        f = feats_of(ms)
        if i and toks[i - 1][0].endswith(("て", "で")) and "非自立可能" in f.get("Pos", ""):
            return None                 # 生きていけない, についていけない: ていく "go on, keep up" + ない
        d, norm = f.get("Dict", ""), f.get("Norm", "")
        stems = {surf, surf[:-1] + "ら" if surf.endswith("ん") else surf}
        kana_c = {st + "ない" for st in stems}
        norm_c = set()
        for st in stems:
            if d and norm and len(d) >= 2 and d[:-1] == st[:len(d) - 1]:
                norm_c.add(norm[:-1] + st[len(d) - 1:] + "ない")
        if (kana_c | norm_c) & {"ならない", "成らない"}:
            return None
        first = self._kaikki_alias().get("first", {})
        vg = " ".join(g for x in {lemma, d, norm} for pp, g in first.get(x, {}).items() if pp == "verb")
        if not gloss_words(vg):
            return None
        cands = sorted(c for c in norm_c if c in first) or sorted(kana_c | norm_c)
        # and Tatoeba's curated index names it as a word of its own (詰らない,
        # 行けない, 堪らない); 見えない there is always 見える + ない
        idx_adj = self._idx_neg_adj()
        if not any(self._same_okuri(x, a) for x in kana_c | norm_c for a in idx_adj):
            return None
        for c in cands:
            ag = first.get(c, {}).get("adj", "")
            if not ag or re.match(r"(?i)(?:same as|alternative form|negative of|synonym of)", ag):
                continue
            if not (gloss_words(ag) & gloss_words(vg)):
                ew = re.findall(r"[a-z]+", en.lower())
                if any(t.startswith(w[:4]) or (len(t) >= 3 and w.startswith(t))
                       for w in gloss_words(vg) for t in ew):
                    return None         # "I can't see it": the verb's own sense
                self.stats["verb + ない read as its own adjective (つまらない)"] += 1
                rd = hira(f.get("Read", "")) or hira(surf)
                rd = rd[:-1] + "ら" if rd.endswith("ん") else rd
                spelled = (surf[:-1] + "ら" if surf.endswith("ん") else surf) + "ない"
                return rd + "ない", spelled, c if KANJI_RE.search(c) else spelled
        return None

    # ---- sentences -----------------------------------------------------------------
    def sentence_rank(self, toks, lv):
        """Polite (です/ます) and neutral sentences first; casual speech after."""
        pen = 0
        text = "".join(t[0] for t in toks)
        if self.casual_re.search(text):
            pen += 2
        if not any(t[1] in ("です", "ます", "ください", "お願いします") for t in toks):
            pen += 1
        return pen

    def marks_sentence(self, toks):
        """Rough male speech (俺, お前, じゃねえ, ...) is kept to the top level."""
        return bool(self.casual_re.search("".join(t[0] for t in toks)))

    def sentence_fields(self, row):
        sid = row[0]
        if self._last_sid is not None and sid <= self._last_sid:
            self._shipped = []          # a new build_sentences pass (refill) started
            for k in [k for k in self.stats if k.startswith("ruby: ")]:
                del self.stats[k]       # sentence_ruby counts the shipped pass only
        self._last_sid = sid
        self._shipped.append(sid)
        out = {"pron": self.kana_line(sid, row[1], row[3] or "")}
        if sid >= self.GEN_BASE:
            out["src"] = "gen"
        return out

    def sentence_ruby(self, sid, rec, surfaces, where):
        """Per-token readings covering every kanji of the sentence, from its kana
        line (kana_line pieces), by the passage token rule (ruby_over): each
        linked token holding a kanji is one [start, end, kana, wordId] with the
        edge kana it shares with the text left out (帰った かえった -> 帰 かえ,
        お金 -> 金 かね); every other kanji segment is a token with wordId null
        (a name, a word the sentence does not link; write_characters also nulls
        a linked word that is no unit's words[0]). A kana segment crossing a
        token edge is cut there (一人 ひとり over 一|人: _split_reading), a kanji
        with no reading reads by Sudachi. When the tokens or the kana line do
        not spell the text, the links are left out (every token null) and the
        kana line is Sudachi's (_passage_segments). Nothing is skipped: the
        stats count tokens, null tokens, cuts and Sudachi fallbacks."""
        text = rec["t"]
        segs = self._kana_pieces.get(sid)
        seg_ok = bool(segs) and "".join(b for b, _ in segs) == text
        tok_ok = "".join(surfaces) == text
        if not (seg_ok and tok_ok):
            self.stats["ruby: sentences with tokens or kana segments not spelling the text (read by Sudachi, unlinked)"] += 1
        if seg_ok and tok_ok:
            seg_at, at = [], 0
            for b, r in segs:
                if b:
                    seg_at.append((at, at + len(b), r))
                at += len(b)
        else:
            seg_at = self._passage_segments(text, rec.get("en", ""))
        spans = []
        if tok_ok:
            tok_at = [0]
            for x in surfaces:
                tok_at.append(tok_at[-1] + len(x))
            for kind, a, b, wid in where:
                if wid not in rec["words"]:
                    continue                # a link fix_links dropped
                s0, e0 = (tok_at[a], tok_at[b + 1]) if kind == "tok" else (a, b)
                if KANJI_RE.search(text[s0:e0]):
                    spans.append((s0, e0, wid))
        keep = []
        for sp_ in sorted(spans):
            if keep and sp_[0] < keep[-1][1]:
                self.stats["ruby: links overlapping the previous one (left to the first)"] += 1
                continue
            keep.append(sp_)
        log = defaultdict(list)
        out = self.ruby_over(text, seg_at, keep, lambda w: True, log)
        self.stats["ruby: tokens"] += len(out)
        self.stats["ruby: tokens with no linked word (wordId null)"] += sum(1 for k in out if k[3] is None)
        self.stats["ruby: kana segments cut at a token edge"] += len(log["split"])
        self.stats["ruby: kana segments cut by each side's own Sudachi reading"] += sum(1 for x in log["split"] if x[-1])
        self.stats["ruby: tokens read by Sudachi (no reading in the kana line)"] += len(log["fallback"])
        self.stats["ruby: kanji left outside every token (should be 0)"] += sum(len(x[1]) for x in log["uncovered"])
        self.stats["ruby: readings not kana (should be 0)"] += len(log["bad"])
        return out or None

    def _token_ruby(self, text, seg_at, s0, e0):
        """(start, end, kana) for the token text[s0:e0] from the kana segments
        (start, end, kana or None) tiling the text, or None."""
        ov = [x for x in seg_at if x[0] < e0 and x[1] > s0]
        a, b = ov[0][0], ov[-1][1]
        rd = "".join(r if r is not None else text[x0:x1] for x0, x1, r in ov)
        # the kana (or digits) the reading shares with the text at either edge
        while a < b and rd and not KANJI_RE.match(text[a]) and hira(text[a]) == hira(rd[0]):
            a, rd = a + 1, rd[1:]
        while a < b and rd and not KANJI_RE.match(text[b - 1]) and hira(text[b - 1]) == hira(rd[-1]):
            b, rd = b - 1, rd[:-1]
        if not (s0 <= a < b <= e0):
            self.stats["ruby: tokens skipped (reading crosses a token boundary)"] += 1
            return None
        if any(r is None and KANJI_RE.search(text[max(a, x0):min(b, x1)]) for x0, x1, r in ov):
            self.stats["ruby: tokens skipped (kanji without a reading)"] += 1
            return None
        if not rd or not KANA_ONLY_RE.match(rd):
            self.stats["ruby: tokens skipped (reading not kana)"] += 1
            return None
        return a, b, rd

    # ---- passage readings (ruby, docs/PACK_SCHEMA.md passages.json) -------------------
    # Counters whose sound changes after a number (_counter_sounds): counter ->
    # (reading, class). A class names the numbers that double (いっ, ろっ, はっ,
    # じゅっ): h and k after 1 6 8 10, s and t after 1 8 10. h also turns the
    # counter's h into p after a doubled number (いっぱい) and into b after 3 and 何
    # (さんばい); a class ending in 3 voices the counter after 3 and 何 (さんがい).
    COUNTER_SOUNDS = {"杯": ("はい", "h"), "本": ("ほん", "h"), "匹": ("ひき", "h"), "泊": ("はく", "h"),
                      "回": ("かい", "k"), "個": ("こ", "k"), "課": ("か", "k"), "ヶ月": ("かげつ", "k"),
                      "か月": ("かげつ", "k"), "カ月": ("かげつ", "k"), "ヵ月": ("かげつ", "k"),
                      "箇月": ("かげつ", "k"), "階": ("かい", "k3"), "軒": ("けん", "k3"),
                      "冊": ("さつ", "s"), "週間": ("しゅうかん", "s"), "週": ("しゅう", "s"),
                      "歳": ("さい", "s"), "才": ("さい", "s"), "足": ("そく", "s3"),
                      "点": ("てん", "t"), "頭": ("とう", "t"), "通": ("つう", "t")}
    COUNTER_TAILS = {"日": ("にち", "か"), "人": ("にん", "り")}
    # Sudachi readings of a verb kanji read in the dictionary's other word or
    # colloquially (来る きたる, 言う ゆう): 来 by the kana after it (_passage_kana_rules)
    KURU = (("る", "く"), ("れ", "く"), ("な", "こ"), ("よ", "こ"), ("ら", "こ"), ("さ", "こ"), ("い", "こ"),
            ("ま", "き"), ("て", "き"), ("た", "き"), ("そ", "き"))
    # kanji the linked word's reading never overrides (_agree_word): readings that
    # change with what follows (来 き/こ/く, 何 なに/なん) or with a number (一 いっ);
    # 数: one pack word (w0417 "number", pron すう) links both the noun かず (本の数)
    # and the prefix すう, so Sudachi's reading is kept
    AGREE_SKIP = set("来何一二三四五六七八九十百千万数")
    _ONES = {1: "いち", 2: "に", 3: "さん", 4: "よん", 5: "ご", 6: "ろく", 7: "なな", 8: "はち", 9: "きゅう"}
    _NATIVE_TSU = {1: "ひと", 2: "ふた", 3: "みっ", 4: "よっ", 5: "いつ", 6: "むっ", 7: "なな", 8: "やっ", 9: "ここの"}
    _P = str.maketrans("はひふへほ", "ぱぴぷぺぽ")
    _B = str.maketrans("はひふへほ", "ばびぶべぼ")
    _G = str.maketrans("かきくけこさしすせそ", "がぎぐげござじずぜぞ")

    @staticmethod
    def _small_int(s):
        """1..99 written in digits or kanji (二十三), else None."""
        n = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if n.isdigit():
            return int(n) if 0 < int(n) < 100 else None
        m = re.fullmatch(r"(?:([二三四五六七八九]?)(十))?([一二三四五六七八九]?)", s)
        if not s or not m:
            return None
        return (KANJI_NUM.get(m.group(1), 1) * 10 if m.group(2) else 0) + KANJI_NUM.get(m.group(3), 0)

    def _counter_sounds(self, pieces):
        """Passages (after the shared kana rules): a number + counter reads with
        its sound change, which Sudachi's per-morpheme readings miss (一 いち + 杯
        ばい, 一 いち + 週間): 一杯 いっ|ぱい, 一週間 いっ|しゅうかん, 三階 さん|がい,
        1杯 1|ぱい (a digit stays a digit: only the counter's reading changes),
        何本 なん|ぼん. A kanji numeral + つ is the native count (四つ よっ|つ).
        Numbers 1..99 only."""
        for i in range(len(pieces) - 1):
            b, nb = pieces[i][0], pieces[i + 1][0]
            if nb == "つ" and b in "一二三四五六七八九" and b:
                n = KANJI_NUM[b]
                if "".join(pieces[i][1] or []) != self._NATIVE_TSU[n]:
                    pieces[i][1] = [self._NATIVE_TSU[n]]
                    self.stats["passage kana: native count before つ (四つ よっつ)"] += 1
                continue
            if nb not in self.COUNTER_SOUNDS or pieces[i + 1][1] is None:
                continue
            cr, cls = self.COUNTER_SOUNDS[nb]
            digits = bool(DIGIT_RE.search(b))
            if b == "何":
                n, nr = None, "なん"
            else:
                n = self._small_int(b)
                if n is None:
                    continue
                tens, u = divmod(n, 10)
                nr = ("" if tens < 2 else self._ONES[tens]) + ("じゅう" if tens else "") + (self._ONES[u] if u else "")
            doubled = n is not None and ((n % 10 in (1, 8)) or (n % 10 == 6 and cls[0] in "hk") or n % 10 == 0)
            voiced = n is None or n % 10 == 3
            new_c = cr
            if doubled:
                nr = nr[:-1] + "っ"                  # いち いっ, ろく ろっ, はち はっ, じゅう じゅっ
                if cls == "h":
                    new_c = cr[:1].translate(self._P) + cr[1:]
            elif voiced and cls == "h":
                new_c = cr[:1].translate(self._B) + cr[1:]
            elif voiced and cls.endswith("3"):
                new_c = cr[:1].translate(self._G) + cr[1:]
            changed = False
            if "".join(pieces[i + 1][1]) != new_c:
                pieces[i + 1][1] = [new_c]
                changed = True
            if not digits and "".join(pieces[i][1] or []) != nr:
                pieces[i][1] = [nr]
                changed = True
            if changed:
                self.stats["passage kana: number + counter sound change (一杯 いっぱい)"] += 1

    def _passage_kana_rules(self, pieces):
        """Passages (after the shared kana rules): 来 read by the kana after it
        (来る く, 来ない こ, 来ます き: Sudachi reads 来る as きたる "coming"), 言 as
        い (Sudachi's colloquial ゆう)."""
        for i, (b, r) in enumerate(pieces):
            if r is None or not b.startswith(("来", "言")):
                continue
            rd = "".join(r)
            after = b[1:] or "".join(x for x, _ in pieces[i + 1:i + 2])
            new = None
            if b[0] == "言" and rd.startswith("ゆ"):
                new = "い" + rd[1:]
            elif b[0] == "来" and not KANJI_RE.match(after[:1] or "x"):
                want = next((k for a, k in self.KURU if after.startswith(a)), None)
                tail = hira(b[1:])
                if want and rd.endswith(tail) and rd[:len(rd) - len(tail)] != want:
                    new = want + tail
            if new and new != rd:
                pieces[i][1] = [new]
                self.stats["passage kana: 来 / 言 by the kana after it"] += 1

    def _agree_word(self, text, a, b, x, y, rd, word, after_span=False):
        """A span's token [x, y) read rd, linked to `word`: when the token is
        exactly the kanji run of the word's headword (箱, 間, 外 in 箱いっぱい, その間,
        外で) and the word's own reading of that run differs, the word's reading
        (Sudachi: ばこ, かん, がい). After a kanji or digit only when that
        character ends another linked span (after_span: 毎日|外 そと); after a
        name or other unlinked text the Sudachi reading stays (松本城 じょう, a
        suffix). Not for AGREE_SKIP kanji."""
        if not word or not word.get("pron"):
            return rd
        m = re.match(f"^([^{HIRA}{KATA}]+)([{HIRA}]*)$", word["w"])
        if not m or text[x:y] != m.group(1) or x != a or any(ch in self.AGREE_SKIP for ch in m.group(1)):
            return rd
        if x and (KANJI_RE.match(text[x - 1]) or DIGIT_RE.match(text[x - 1])) and not after_span:
            return rd
        pr, ok = word["pron"].strip("〜"), m.group(2)
        stem = pr if not ok else (pr[:len(pr) - len(ok)] if pr.endswith(ok) else "")
        if stem and KANA_ONLY_RE.match(stem) and stem != rd:
            return stem
        return rd

    def _split_reading(self, text, x0, c, x1, r):
        """The reading r of text[x0:x1] cut at c: (left, right, from Sudachi per side).
        A side with no kanji reads as written; else Sudachi's or the pack's
        reading of one side that begins or ends r (the other side's first sound
        may be voiced by rendaku); else each side's own Sudachi reading."""
        L, R = text[x0:c], text[c:x1]
        plain = lambda x: x[:1].translate(_VOICE) + x[1:]        # noqa: E731
        if not KANJI_RE.search(L) and r.startswith(hira(L)):
            return None, r[len(L):], False
        if not KANJI_RE.search(R) and r.endswith(hira(R)):
            return r[:len(r) - len(R)], None, False
        if (not KANJI_RE.search(L) and DIGIT_RE.search(L)) or (L and all(ch in KANJI_NUM for ch in L)):
            # a number read with its counter (3日 みっか, 一人 ひとり): the counter
            # keeps its own tail of the reading
            for tail in self.COUNTER_TAILS.get(R, ()):
                if r.endswith(tail) and len(tail) < len(r):
                    return r[:len(r) - len(tail)], tail, False
        cands_l = [self._span_reading(L)] + [p for p in self._pack_readings().get(L, ())]
        cands_r = [self._span_reading(R)] + [p for p in self._pack_readings().get(R, ())]
        for x in cands_l:
            if x and r.startswith(x) and len(x) < len(r):
                return x, r[len(x):], False
        for x in cands_r:
            if x and len(x) < len(r) and plain(r[len(r) - len(x):]) == plain(x):
                return r[:len(r) - len(x)], r[len(r) - len(x):], False
        return (cands_l[0] if KANJI_RE.search(L) else None), (cands_r[0] if KANJI_RE.search(R) else None), True

    def _pack_readings(self):
        """spelling -> kana readings from pack/words.json (headword and alts) and
        characters.json units (passages: splitting a reading at a tap edge)."""
        if getattr(self, "_pack_rd", None) is None:
            out = defaultdict(list)
            repo = getattr(self, "repo", None)
            pack = repo / "pack" if repo is not None else None
            if pack is not None and (pack / "words.json").exists():
                for w in json.loads((pack / "words.json").read_text()):
                    rd = (w.get("pron") or "").strip("〜")
                    if rd and KANA_ONLY_RE.match(rd):
                        for f in [w["w"]] + list(w.get("alt") or ()):
                            f = f.strip("〜")
                            if rd not in out[f]:
                                out[f].append(rd)
            if pack is not None and (pack / "characters.json").exists():
                for c in json.loads((pack / "characters.json").read_text()):
                    rd = (c.get("reading") or "").strip("〜")
                    if rd and KANA_ONLY_RE.match(rd) and rd not in out[c["t"].strip("〜")]:
                        out[c["t"].strip("〜")].append(rd)
            self._pack_rd = out
        return self._pack_rd

    def _passage_segments(self, text, en):
        """Kana segments [(start, end, kana or None)] of a passage text: Sudachi
        pieces, the shared kana rules (kana_line), then _counter_sounds."""
        pieces = self._sudachi_pieces(text)
        segs = self._kana_segments(pieces, text, en, extra=(self._counter_sounds, self._passage_kana_rules))
        out, at = [], 0
        for (b, r), (_b, whole) in zip(segs, pieces):
            # a number read natively with its counter (4日 よっか): _kana_digits keeps
            # the digit and leaves っか, no reading of 日; the token reads whole
            m = re.match(r"[0-9０-９]+", r or "")
            if m and r[m.end():m.end() + 1] == "っ" and whole:
                r = "".join(whole)
                self.stats["passage kana: number + counter read whole (4日 よっか)"] += 1
            if b:
                out.append((at, at + len(b), r))
            at += len(b)
        return out

    def text_ruby(self, text, en, spans, wid_ok, log, words=None):
        """[[start, end, kana, wordId or None]] (UTF-16) covering every kanji of
        `text`. spans: [(start, end, wordId)] in code points, the text's tap
        segments (passages.json spans; for titles, questions and options the
        linker's). A reading token never crosses a tap-segment edge (the
        engine renders such a token plain): a kana segment crossing one is cut
        there (_split_reading). A span holding a kanji is one token read over
        its segments with the edge kana it shares with the text left out
        (_token_ruby: 働いて -> 働 はたら, 悪かっ -> 悪 わる), its wordId when wid_ok
        allows it, else null; failing that (a kanji with no reading), each
        segment in it is a token. Outside spans each segment holding a kanji
        is a token with a null wordId (names, unlinked words). A segment
        _token_ruby cannot read gets Sudachi's reading of its text: the
        fallback, logged. A span's reading that is not its linked word's
        (words: id -> words.json entry) is replaced by it (_agree_word).
        log: lists by kind (fallback, split, agree, bad, uncovered)."""
        return self.ruby_over(text, self._passage_segments(text, en), spans, wid_ok, log, words)

    def ruby_over(self, text, segs, spans, wid_ok, log, words=None):
        """text_ruby's token rule over given kana segments [(start, end, kana or
        None)] tiling the text (sentence_ruby: the sentence's kana line;
        passages: _passage_segments). spans: non-overlapping [(start, end,
        wordId)] in code points."""
        words = words or {}
        spans = sorted(s for s in spans if s[1] > s[0])
        cuts = sorted({a for a, _b, _w in spans} | {b for _a, b, _w in spans})
        cut_segs = []
        for x0, x1, r in segs:
            inner = [c for c in cuts if x0 < c < x1]
            if not inner or r is None:
                # no cut, or no reading to cut (a kanji left without one is read below)
                cut_segs += [(p, q, r) for p, q in zip([x0] + inner, inner + [x1])]
                continue
            for c in inner:
                left, right, fb = self._split_reading(text, x0, c, x1, r)
                log["split"].append((text[x0:x1], r, text[x0:c], left, right, fb))
                cut_segs.append((x0, c, left))
                x0, r = c, right
                if r is None:
                    break
            cut_segs.append((x0, x1, r))
        # a kanji piece with no reading (none in the kana line): Sudachi's reading of it
        for i, (p, q, r) in enumerate(cut_segs):
            if r is None and KANJI_RE.search(text[p:q]):
                rd = hira(self._span_reading(text[p:q]))
                log["fallback"].append((text[p:q], text[p:q], rd))
                cut_segs[i] = (p, q, rd or None)
        parts, at = [], 0
        for a, b, wid in spans:
            if a > at:
                parts.append((at, a, None, False))
            parts.append((a, b, wid, True))
            at = b
        if at < len(text):
            parts.append((at, len(text), None, False))
        out = []

        def one(a, b, inside, wid):
            saved = dict(self.stats)
            r = self._token_ruby(text, inside, a, b) if inside else None
            self.stats.clear()
            self.stats.update(saved)
            if r is None:
                rd = hira(self._span_reading(text[a:b]))
                # edge kana shared with the text, as _token_ruby
                x, y = a, b
                while x < y and rd and not KANJI_RE.match(text[x]) and hira(text[x]) == rd[0]:
                    x, rd = x + 1, rd[1:]
                while x < y and rd and not KANJI_RE.match(text[y - 1]) and hira(text[y - 1]) == rd[-1]:
                    y, rd = y - 1, rd[:-1]
                log["fallback"].append((text[a:b], text[x:y], rd))
                r = (x, y, rd)
            out.append([r[0], r[1], r[2], wid])

        for a, b, wid, is_span in parts:
            if not KANJI_RE.search(text[a:b]):
                continue
            inside = [s for s in cut_segs if a <= s[0] and s[1] <= b]
            w = wid if is_span and wid_ok(wid) else None
            if is_span:
                saved = dict(self.stats)
                r = self._token_ruby(text, inside, a, b)
                self.stats.clear()
                self.stats.update(saved)
                if r is not None:
                    rd = self._agree_word(text, a, b, r[0], r[1], r[2], words.get(wid),
                                          after_span=any(q == a for _p, q, _w in spans))
                    if rd != r[2]:
                        log["agree"].append((text[r[0]:r[1]], r[2], rd))
                    out.append([r[0], r[1], rd, w])
                    continue
            for s0, s1, _r in inside:
                if KANJI_RE.search(text[s0:s1]):
                    one(s0, s1, [s for s in inside if s[0] == s0], w)
        for k in out:
            if not (k[2] and KANA_ONLY_RE.match(k[2])):
                log["bad"].append((text, text[k[0]:k[1]], k[2]))
        covered = set()
        for a, b, _r, _w in out:
            covered |= set(range(a, b))
        miss = [i for i, ch in enumerate(text) if KANJI_RE.match(ch) and i not in covered]
        if miss:
            log["uncovered"].append((text, "".join(text[i] for i in miss)))
        return [[_u16(text, a), _u16(text, b), rd, w] for a, b, rd, w in out]

    def passage_ruby(self, lk, passages, names_of):
        """passages.run hook (spec-level; zh's lives on its linker), before
        writing: `ruby` on every passage sentence holding a kanji, `titleRuby`,
        per question `ruby` and (mc) `optionsRuby`, one list per option (lists
        may be empty). Every kanji is inside a token (text_ruby). A sentence's
        tap segments are its spans; a title's, question's and option's are the
        linker's spans for it (lk.tag + lk.links_all). A token's wordId is its
        span's word when that word is some characters.json unit's words[0]
        (and, for a sentence, in its words), else null. Only with a
        characters stage (pack/characters.json). Returns the report lines."""
        chars_p = self.repo / "pack" / "characters.json" if self.repo is not None else None
        if chars_p is None or not chars_p.exists():
            return []
        word0 = {c["words"][0] for c in json.loads(chars_p.read_text()) if c.get("words")}
        wp = self.repo / "pack" / "words.json"
        words = {w["id"]: w for w in json.loads(wp.read_text())} if wp.exists() else {}
        saved_stats = Counter(self.stats)
        self.stats = Counter()
        log = defaultdict(list)
        n = Counter()

        def cp_spans(text, spans):
            # UTF-16 spans -> code points
            idx = {_u16(text, i): i for i in range(len(text) + 1)}
            return [(idx[a], idx[b], w) for a, b, w in (s[:3] for s in spans) if a in idx and b in idx]

        def other(text, en, names):
            toks = lk.tag(text, "", names)
            _ws, _cl, spans, _lt = lk.links_all(toks, text, "", names)
            r = self.text_ruby(text, en, cp_spans(text, spans), lambda w: w in word0, log, words)
            n["other_tok"] += len(r)
            n["other_null"] += sum(1 for k in r if k[3] is None)
            return r

        for p, names in zip(passages, names_of):
            for s in p["sentences"]:
                ws = set(s.get("words") or ())
                r = self.text_ruby(s["t"], s["en"], cp_spans(s["t"], s.get("spans") or []),
                                   lambda w, ws=ws: w in word0 and w in ws, log, words)
                n["sent"] += 1
                n["sent_tok"] += len(r)
                n["sent_null"] += sum(1 for k in r if k[3] is None)
                if r:
                    s["ruby"] = r
                    n["sent_ruby"] += 1
            p["titleRuby"] = other(p["title"], "", names)
            n["titles"] += 1
            for q in p["questions"]:
                q["ruby"] = other(q["q"], q.get("en", ""), names)
                n["questions"] += 1
                if q.get("options"):
                    q["optionsRuby"] = [other(o, "", names) for o in q["options"]]
                    n["options"] += len(q["options"])
        rules = self.stats
        self.stats = saved_stats
        self.ruby_log = log
        fb = Counter((a, b, c) for a, b, c in log["fallback"])
        sp_fb = Counter((a, r, x, l, rr) for a, r, x, l, rr, f in log["split"] if f)
        sp_ok = Counter((a, r, x, l, rr) for a, r, x, l, rr, f in log["split"] if not f)
        fmt = lambda c: ", ".join((f"{k[0]}: {k[1]} {k[2]}" if len(k) == 3 else  # noqa: E731
                                   f"{k[0]} ({k[1]}) cut {k[3] or '-'}|{k[4] or '-'}") + f" x{c[k]}" for k in sorted(c))
        lines = ["## Readings", "",
                 "Reading tokens (`ruby`, langs/ja.py passage_ruby): every kanji of every passage sentence, "
                 "title, question and option is inside a token; readings from Sudachi through the sentences.json "
                 "kana rules (kana_line) plus the passage counter rule.", "",
                 "| | texts | tokens | wordId null |", "|---|---:|---:|---:|",
                 f"| sentences | {n['sent']} ({n['sent_ruby']} with a kanji) | {n['sent_tok']} | {n['sent_null']} |",
                 f"| titles, questions, options | {n['titles']} + {n['questions']} + {n['options']} | "
                 f"{n['other_tok']} | {n['other_null']} |", "",
                 f"Kanji outside every token: {sum(len(x[1]) for x in log['uncovered'])}"
                 + (" (" + "; ".join(f"{t!r}: {m}" for t, m in log["uncovered"][:20]) + ")" if log["uncovered"] else "") + ".",
                 f"Readings not kana: {len(log['bad'])}"
                 + (" (" + "; ".join(f"{t!r}: {b} {r!r}" for t, b, r in log["bad"][:20]) + ")" if log["bad"] else "") + ".",
                 f"Fallback readings (Sudachi's reading of the token's own text, the segment reading failing): "
                 f"{sum(fb.values())}" + (": " + fmt(fb) if fb else "") + ".",
                 f"Kana segments cut at a tap-span edge: {sum(sp_ok.values()) + sum(sp_fb.values())} "
                 f"({sum(sp_fb.values())} by each side's own Sudachi reading, the fallback"
                 + (": " + fmt(sp_fb) if sp_fb else "") + ").",
                 f"Readings replaced by the linked word's own (_agree_word): {len(log['agree'])}"
                 + (": " + ", ".join(f"{k[0]} {k[1]}→{k[2]} x{v}" for k, v in sorted(Counter(log["agree"]).items()))
                    if log["agree"] else "") + ".",
                 "Kana rules applied (count over all texts): "
                 + (", ".join(f"{k} x{v}" for k, v in sorted(rules.items())) or "none") + ".",
                 "Sentences in sentences.json get their ruby by the same token rule (sentence_ruby over the "
                 "sentence's kana line), so both cover every kanji."]
        return lines

    def character_units(self, words):
        """Kanji-word units (docs/HSK_MERGE.md ss2.1): every word whose headword
        has a kanji, read by its kana pron, in words.json order within each
        level. The 〜 of a suffix or counter (〜年 〜ねん) is not part of the
        reading."""
        from ..core.util import stat
        lv = {x: i for i, x in enumerate(self.level_ids)}
        units, left_out = [], []
        for w in sorted((w for w in words if KANJI_RE.search(w["w"])), key=lambda w: lv[w["lv"]]):
            rd = w["pron"].strip("〜")
            if not KANA_ONLY_RE.match(rd):
                left_out.append(f"{w['w']} {w['pron']}")
                continue
            # Unit id = "c" + the word id's digits (w0416 -> c0416): ids follow word ids,
            # so they are never renumbered when units are added or left out.
            if not re.fullmatch(r"w\d+", w["id"]):
                raise ValueError(f"word id {w['id']!r} is not w<digits>; character unit ids derive from it")
            units.append({"id": "c" + w["id"][1:], "t": w["w"], "words": [w["id"]],
                          "lv": w["lv"], "reading": rd})
        stat("ja_characters_left_out_reading_not_kana", left_out)
        return units

    def _transcriptions(self):
        if self._trans is None:
            tr = {}
            p = self.repo / ".cache" / self.transcriptions_file
            if p.exists():
                with bz2.open(p, "rt", encoding="utf-8") as f:
                    for line in f:
                        q = line.rstrip("\n").split("\t")
                        if len(q) >= 5 and q[1] == "jpn" and q[2] == "Hrkt" and q[0].isdigit():
                            tr[int(q[0])] = q[4]
            self._trans = tr
        return self._trans

    def kana_line(self, sid, text, en=""):
        """Whole-sentence kana reading. Segments come from Tatoeba's furigana
        transcription when it matches the sentence, else from Sudachi
        (kanji tokens read, kana kept as written). Context rules then fix
        readings either source gets wrong (see _kana_rules); digits stay
        digits (_kana_digits)."""
        t = self._transcriptions().get(sid)
        pieces = None
        if t and re.sub(r"\[([^|\]]+)\|[^\]]*\]", r"\1", t) == text:
            self.stats["sentence kana from Tatoeba transcriptions"] += 1
            pieces, at = [], 0
            for m in re.finditer(r"\[([^|\]]+)\|([^\]]*)\]", t):
                if m.start() > at:
                    pieces.append([t[at:m.start()], None])
                pieces.append([m.group(1), m.group(2).split("|")])
                at = m.end()
            if at < len(t):
                pieces.append([t[at:], None])
            self._kana_lemma_agree(sid, pieces)
        else:
            self.stats["sentence kana from Sudachi readings"] += 1
            pieces = self._sudachi_pieces(text)
        segs = self._kana_segments(pieces, text, en)
        self._kana_pieces[sid] = segs
        return "".join(r if r is not None else b for b, r in segs)

    def _sudachi_pieces(self, text):
        """Kana pieces [written, [kana] or None] of a text from Sudachi: one per
        morpheme, a kanji morpheme read (READING_FIX first), others kept as written."""
        pieces = []
        for m in self._tokenizer().tokenize(text):
            srf = m.surface()
            if KANJI_RE.search(srf):
                r = READING_FIX.get(srf, m.reading_form())
                pieces.append([srf, [hira(r)] if r and r != "*" else None])
            else:
                pieces.append([srf, None])
        return pieces

    def _kana_segments(self, pieces, text, en, extra=()):
        """The context rules over kana pieces (kana_line), then `extra` rules
        (passages: _counter_sounds), then digits (_kana_digits): [(written,
        kana or None)] tiling the text."""
        self._person_counts(pieces)
        self._kana_rules(pieces, text, en)
        self._day_counts(pieces)
        self._minute_counts(pieces)
        self._naka(pieces, en)
        for f in extra:
            f(pieces)
        return [(b, self._kana_digits(b, r) if r is not None else None) for b, r in pieces]

    def _person_counts(self, pieces):
        """一人/二人 fused into a following compound (一人当たり, 二人組): Sudachi
        reads 一 いち + 人当たり ひとあたり. The number and 人 are ひとり/ふたり,
        the rest keeps its reading (あたり)."""
        for i in range(len(pieces) - 1):
            b, nb, nr = pieces[i][0], pieces[i + 1][0], "".join(pieces[i + 1][1] or [])
            if b in ("一", "二", "１", "1", "２", "2") and nb.startswith("人") and len(nb) > 1 and \
                    re.match("(?:ひと|にん|じん)", nr):
                pieces[i] = [b + "人", ["ひとり" if b in "一１1" else "ふたり"]]
                pieces[i + 1] = [nb[1:], [re.sub("^(?:ひと|にん|じん)", "", nr)]]
                self.stats["sentence kana: 一人/二人 split from a compound (一人当たり)"] += 1

    # (十分 before な/に/だ/で/です or at the end is じゅうぶん "enough")
    MIN_RE = re.compile(r"(?<![0-9０-９一二三四五六七八九十百千万何数])(?!十分(?:[なにだで。、？！]|$))"
                        r"([0-9０-９]{1,2}|[一二三四五六七八九十]{1,3})分"
                        r"(?!の[0-9０-９一二三四五六七八九十百千]+[^分0-9０-９一二三四五六七八九十百千]|の[0-9０-９一二三四五六七八九十百千]+$)")
    _MIN_UNIT = {1: "いっぷん", 2: "にふん", 3: "さんぷん", 4: "よんぷん", 5: "ごふん", 6: "ろっぷん", 7: "ななふん",
                 8: "はっぷん", 9: "きゅうふん"}

    @classmethod
    def _minute_reading(cls, n):
        """N分 as minutes: ふん after 2 5 7 9, ぷん with a doubled sound otherwise."""
        tens, unit = divmod(n, 10)
        head = "" if not tens else "じゅう" if tens == 1 else cls._SINO[tens][0] + "じゅう"
        if unit:
            return head + cls._MIN_UNIT[unit]
        return head[:-1] + "っぷん" if head else ""

    def _minute_counts(self, pieces):
        """N分 is minutes (ふん/ぷん: 一分 いっぷん, ４５分 ４５ふん) unless it is a
        fraction N分のM (六十分の一 ろくじゅうぶんのいち)."""
        text = "".join(b for b, _ in pieces)
        for m in list(self.MIN_RE.finditer(text)):
            n = self._kanji_int(m.group(1))
            if not n or n >= 100:
                continue
            rd = self._minute_reading(n)
            offs, at = [], 0
            for b, _ in pieces:
                offs.append((at, at + len(b)))
                at += len(b)
            idx = [j for j, (s_, e_) in enumerate(offs) if s_ < m.end() and e_ > m.start()]
            if not idx or offs[idx[0]][0] != m.start() or offs[idx[-1]][1] != m.end():
                continue                # segment runs past the count: left as is
            cur = "".join("".join(pieces[j][1]) if pieces[j][1] else pieces[j][0] for j in idx)
            if cur == rd and len(idx) == 1:
                continue
            pieces[idx[0]:idx[-1] + 1] = [[m.group(0), [rd]]]
            self.stats["sentence kana: minutes re-read (ふん / ぷん)"] += 1

    # 中 after a place or a stretch of time is じゅう "throughout" (一日中, 世界中,
    # 部屋中); after an activity it is ちゅう "during, in the middle of" (会議中)
    JUU_HEADS = ("一日", "一晩", "一年", "年", "一生", "晩", "世界", "日本")
    CHUU_HEADS = ("午前", "午後", "来週", "今週", "来月", "今月", "来年")
    THROUGH_EN = re.compile(r"(?i)\b(?:all|whole|entire|throughout|everywhere|over)\b")

    def _naka(self, pieces, en):
        """Re-read 中 after a noun: ちゅう after a time it falls within (午前中,
        来週中), じゅう after a stretch of time or a place it fills (一日中,
        世界中), or when the translation says so ("all over", "all day") and
        the noun is no activity (する-noun: 電話中 stays ちゅう). 間中 is
        あいだじゅう (Sudachi: まなか, the name)."""
        text, at = "".join(b for b, _ in pieces), 0
        for i, (b, r) in enumerate(pieces):
            here, at = at, at + len(b)
            if r is None or not b.endswith("中"):
                continue
            rd = "".join(r)
            if b.endswith("間中") and rd.endswith("まなか") and "manaka" not in (en or "").lower():
                pieces[i][1] = [rd[:-3] + "あいだじゅう"]
                self.stats["sentence kana: 中 re-read (じゅう / ちゅう)"] += 1
                continue
            if not rd.endswith(("ちゅう", "じゅう")):
                continue
            head = (text[:here] + b[:-1]).translate(str.maketrans("１２３４1234", "一二三四一二三四"))
            if not head or not re.search(f"[{KANJI}{KATA}]$", head):
                continue
            want = None
            if head.endswith(self.CHUU_HEADS):
                want = "ちゅう"
            elif head.endswith(self.JUU_HEADS):
                want = "じゅう"
            elif self.THROUGH_EN.search(en or ""):
                last = list(self._tokenizer().tokenize(head))[-1].part_of_speech()
                if last[0] == "名詞" and "サ変" not in last[2]:
                    want = "じゅう"
            if want and not rd.endswith(want):
                pieces[i][1] = [rd[:-3] + want]
                self.stats["sentence kana: 中 re-read (じゅう / ちゅう)"] += 1

    # N日 read natively as a date or a count of days (みっか "the 3rd" and
    # "three days"); 1日 is ついたち as a date, いちにち as a count; other
    # numbers take にち (２２日 ２２にち)
    DAY_NATIVE = {2: "ふつか", 3: "みっか", 4: "よっか", 5: "いつか", 6: "むいか", 7: "なのか", 8: "ようか",
                  9: "ここのか", 10: "とおか", 14: "じゅうよっか", 20: "はつか", 24: "にじゅうよっか"}
    DAY_RE = re.compile(r"(?<![0-9０-９一二三四五六七八九十百千万何数第])([0-9０-９]{1,2}|[一二三四五六七八九十]{1,3})日(?![本曜月])")

    @staticmethod
    def _kanji_int(s):
        n = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if n.isdigit():
            return int(n)
        m = re.fullmatch(r"([二三]?)(十?)([一二三四五六七八九]?)", s)
        if not m or not s or (m.group(1) and not m.group(2)):
            return None             # 二三日 "two or three days"
        return (KANJI_NUM.get(m.group(1), 1) * 10 if m.group(2) else 0) + KANJI_NUM.get(m.group(3), 0)

    def _span_reading(self, s):
        """Sudachi's kana for a short span (a segment's written part beside a day count)."""
        if not KANJI_RE.search(s):
            return s
        return "".join(hira(m.reading_form()) if KANJI_RE.search(m.surface()) else m.surface()
                       for m in self._tokenizer().tokenize(s))

    def _day_counts(self, pieces):
        """Re-read every number + 日 in a kana line (DAY_NATIVE). The segment
        holding it is split so the day count is a segment of its own: ３日後
        みっかご, ６月１０日 ６がつとおか, 3日分 みっかぶん."""
        text = "".join(b for b, _ in pieces)
        for m in list(self.DAY_RE.finditer(text)):
            n = self._kanji_int(m.group(1))
            if not n or n > 31:
                continue
            date = bool(re.search(r"月の?$", text[:m.start()]))
            if n == 1:
                rd = "ついたち" if date else "いちにち"
            elif n in self.DAY_NATIVE:
                rd = self.DAY_NATIVE[n]
            else:
                rd = min(self._num_readings(str(n)), key=lambda r: (r.endswith("っ"), "きゅう" in r, "よん" in r,
                                                                    len(r), r)) + "にち"
            offs, at = [], 0
            for b, _ in pieces:
                offs.append((at, at + len(b)))
                at += len(b)
            idx = [j for j, (s_, e_) in enumerate(offs) if s_ < m.end() and e_ > m.start()]
            if not idx:
                continue
            p, q = idx[0], idx[-1]
            pre, suf = text[offs[p][0]:m.start()], text[m.end():offs[q][1]]
            cur = "".join("".join(pieces[j][1]) if pieces[j][1] else pieces[j][0] for j in range(p, q + 1))
            pre_r, suf_r = self._span_reading(pre), self._span_reading(suf)

            def strip(r, head, tail):
                # the segment's own kana for the written parts beside the day
                # count, matched up to rendaku (分 ふん / ぶん)
                if len(r) < len(head) + len(tail):
                    return None
                h, t = r[:len(head)], r[len(r) - len(tail):]
                plain = lambda x: x[:1].translate(_VOICE) + x[1:]
                return (h, t) if plain(h) == plain(head) and plain(t) == plain(tail) else None
            hs = strip(cur, pre_r, suf_r)
            if hs is None:
                self.stats["sentence kana: day count left (segment does not split)"] += 1
                continue
            if cur[len(hs[0]):len(cur) - len(hs[1])] == rd and p == q:
                continue            # (a digit segment of its own always prints as the digit: [3|みっ][日|か])
            new = ([[pre, [hs[0]] if KANJI_RE.search(pre) or DIGIT_RE.search(pre) else None]] if pre else []) + \
                [[m.group(0), [rd]]] + \
                ([[suf, [hs[1]] if KANJI_RE.search(suf) or DIGIT_RE.search(suf) else None]] if suf else [])
            pieces[p:q + 1] = new
            self.stats["sentence kana: day counts re-read (みっか, とおか)"] += 1

    @staticmethod
    def _reading_stem(reading, word):
        """The reading of a word's kanji part: 行く いく -> い, 車 くるま -> くるま."""
        ok = re.search(f"[{HIRA}]*$", word).group(0) if word else ""
        if not ok:
            return reading
        return reading[:len(reading) - len(ok)] if reading.endswith(ok) else ""

    def _idx_tok_records(self, row, toks):
        """Index-confirmed kanji tokens of a sentence, for its kana line:
        (offset, surface, dictionary spelling, reading, index reading stem)."""
        text = row[1]
        spans, cur = [], 0
        for ilem, rd, sf in self._indices().get(row[0]) or []:
            at = text.find(sf, cur)
            if at >= 0:
                spans.append((at, at + len(sf), ilem, rd))
                cur = at + len(sf)
        out, off = [], 0
        for surf, lemma, upos, ms in toks:
            here, off = off, off + len(surf)
            if not lemma or "Src=idx" not in ms or not KANJI_RE.search(surf) or DIGIT_RE.search(surf) or \
                    upos in ("NUM", "PROPN") or \
                    (here and re.match(f"[0-9０-９一二三四五六七八九十百千万何{KATA}]", text[here - 1])):
                continue                # ２５日, 八時: counters; トニー君: an honorific after a name
            f = feats_of(ms)
            d = f.get("Dict", "")
            ird = ""
            # the index reading is the dictionary form's: it names an uninflected
            # token's reading only (来ます is not く-ます)
            if surf == d:
                item = next((x for x in spans if x[0] <= here < x[1]), None)
                if item and item[3] and KANA_ONLY_RE.match(item[3]) and item[2] == d:
                    ird = self._reading_stem(hira(item[3]), d)
            out.append((here, surf, d, hira(f.get("Read", "")), ird))
        return out

    def _idx_toks_for(self, sid):
        """Index-confirmed kanji tokens per sentence with a transcription (one lazy
        pass over the tagged corpus; kana_line has only the sentence id)."""
        if getattr(self, "_idx_toks", None) is None:
            from ..core.sources import corpus_path
            from ..core.tag import tagged_path, iter_tagged
            from ..core.util import Env
            env = Env(self)
            path, _ = tagged_path(env, corpus_path(env))
            tr = self._transcriptions()
            idx = self._indices()
            self._idx_toks = {}
            for sid_, toks in iter_tagged(path):
                if sid_ in tr and sid_ in idx:
                    rec = self._idx_tok_records([sid_, "".join(t[0] for t in toks)], toks)
                    if rec:
                        self._idx_toks[sid_] = rec
        return self._idx_toks.get(sid)

    def _kana_lemma_agree(self, sid, pieces):
        """A transcription reading that is no reading of an index-confirmed token's
        word is a furigana error (車 しゃ, 行って おこなって, 食べ しょく, 少し
        しょう): the index's reading, else Sudachi's, replaces it. A reading the
        corpus or Wiktionary gives the spelling (値 ね, 描く かく, 開く あく), or
        rendaku (箱 ばこ), is kept."""
        toks = self._idx_toks_for(sid)
        if not toks:
            return
        self._group_info()
        if getattr(self, "_kaikki_reads", None) is None:
            self._kaikki_reads = defaultdict(set)
            for kana, ks in self._kaikki_alias().get("reading", {}).items():
                for k in ks:
                    self._kaikki_reads[k].add(kana)
        starts, at = {}, 0
        for pi, (b, r) in enumerate(pieces):
            starts[at] = pi
            at += len(b)
        for here, surf, d, read, ird in toks:
            m = re.match(f"^([^{HIRA}{KATA}]+)([{HIRA}]*)$", surf)
            pi = starts.get(here)
            if not m or pi is None or pieces[pi][1] is None:
                continue
            # the kanji run is one piece, or per-character pieces ([時|とき][期|き])
            span, base = pi, ""
            while span < len(pieces) and pieces[span][1] is not None and len(base) < len(m.group(1)):
                base += pieces[span][0]
                span += 1
            if base != m.group(1):
                continue
            cur, tail = "".join("".join(pieces[j][1]) for j in range(pi, span)), m.group(2)

            def fits(st):
                return st and (cur == st or (cur[1:] == st[1:] and
                                             cur[:1].translate(_VOICE) == st[:1].translate(_VOICE)))
            if ird:                             # the index names the reading (車 くるま)
                new = ird if not fits(ird) else None
            else:
                seen = {r for r, c in self._dict_reads.get(d, {}).items() if c >= 2}
                seen |= {x for x in (self._reading_stem(r, d) for r in self._kaikki_reads.get(d, ())) if x}
                stem = read[:len(read) - len(tail)] if tail and read.endswith(tail) else (read if not tail else "")
                new = stem if seen and not any(fits(x) for x in seen) and stem in seen else None
            if new:
                pieces[pi] = [m.group(1), [new]]
                for j in range(pi + 1, span):
                    pieces[j] = ["", None]
                self.stats["sentence kana: transcription reading not the word's, index/Sudachi used (車 しゃ)"] += 1

    # readings of a digit string a transcription may give (Sino-Japanese, with
    # the sound changes before a counter: いっ, ろっ, はっ, じゅっ, ひゃっ ...)
    _SINO = {0: ["れい", "ぜろ"], 1: ["いち", "いっ"], 2: ["に"], 3: ["さん"], 4: ["よん", "よ", "し"],
             5: ["ご"], 6: ["ろく", "ろっ"], 7: ["なな", "しち"], 8: ["はち", "はっ"], 9: ["きゅう", "く"]}
    _NATIVE = ("ひと", "ふた", "みっ", "よっ", "いつ", "むっ", "やっ", "ここの", "とお", "つい", "はつ", "ふつ")

    @classmethod
    def _num_readings(cls, digits):
        n = int(digits.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        if n < 10:
            return set(cls._SINO[n])
        if n >= 100000:
            return set()
        out = {""}
        for unit, name, alts in ((10000, "まん", {}), (1000, "せん", {3: "さんぜん", 8: "はっせん"}),
                                 (100, "ひゃく", {3: "さんびゃく", 6: "ろっぴゃく", 8: "はっぴゃく"}),
                                 (10, "じゅう", {})):
            d, n = divmod(n, unit)
            if not d:
                continue
            head = alts.get(d) or (("" if d == 1 and unit < 10000 else cls._SINO[d][0]) + name)
            out = {o + head for o in out}
        if n:
            out = {o + r for o in out for r in cls._SINO[n]}
        # the last sound may double before a counter (じゅっ, ひゃっ, いっ)
        out |= {o[:-1] + "っ" for o in out if o.endswith(("う", "く", "ち"))}
        out |= {o[:-2] + "っ" for o in out if o.endswith(("じゅう",))}
        out |= {o[:-3] + "じっ" for o in out if o.endswith("じゅう")}
        return out

    def _kana_digits(self, base, parts):
        """One segment's kana. Digits stay digits; a reading that fuses number
        and counter natively (１人 ひとり) is kept whole."""
        if parts is None:
            return base
        reading = "".join(parts)
        if not DIGIT_RE.search(base):
            return reading or base
        if not reading or re.fullmatch(r"[0-9０-９,，.]+", base):
            return base
        # align the reading with the segment: each digit run is one of its
        # readings, each other run any reading (３月２２日: さん|がつ|にじゅうに|にち)
        runs = re.findall(r"[0-9０-９]+|[^0-9０-９]+", base)
        pat, ok = "", True
        for run in runs:
            if DIGIT_RE.match(run):
                alts = sorted(self._num_readings(run), key=len, reverse=True)
                if not alts:
                    ok = False
                    break
                pat += "(?:" + "|".join(map(re.escape, alts)) + ")"
            else:
                pat += "(.+?)"
        m = re.fullmatch(pat, reading) if ok else None
        if m:
            out, gi = "", 1
            for run in runs:
                if DIGIT_RE.match(run):
                    out += run
                else:
                    out += m.group(gi)
                    gi += 1
            return out
        self.stats["sentence kana: number read with its counter (１人 ひとり)"] += 1
        return reading

    def _kana_rules(self, pieces, text, en):
        """Readings Tatoeba's furigana and Sudachi get wrong for a learner,
        fixed from context (pieces: [written, [ruby...] or None], in order)."""
        def nxt_text(i):
            return "".join(b for b, _ in pieces[i + 1:])
        gold = bool(re.search(r"\bgold", en or "", re.I))
        sud = None
        for i, (b, r) in enumerate(pieces):
            if r is None:
                continue
            rd = "".join(r)
            after = nxt_text(i)
            new = None
            if b == "何" and rd == "なに" and re.match(r"(?:です|だ|で|の|と|て|時|人|回|歳|才|年|月|日|分|本|枚|個|度|番|階|語|か月|ヶ月|週|曜|杯|匹|台|冊)", after):
                new = "なん"
            elif b == "何時" and rd != "なんじ" and re.match(r"(?:です|でし|だ|に|から|まで|頃|ごろ|ころ|の|か。|か？)", after):
                new = "なんじ"
            elif b == "種" and rd == "たね" and i and pieces[i - 1][0].endswith("ある"):
                new = "しゅ"                     # ある種 "a kind of"
            elif "日本" in b and "にっぽん" in rd:
                new = rd.replace("にっぽん", "にほん")
            elif b in ("一", "二") and rd in ("いち", "に") and after.startswith("人") and \
                    i + 1 < len(pieces) and pieces[i + 1][0] == "人":
                new = {"一": "ひと", "二": "ふた"}[b]
                pieces[i + 1][1] = ["り"]
            elif b in ("１", "1", "２", "2") and i + 1 < len(pieces) and pieces[i + 1][0] == "人" and \
                    "".join(pieces[i + 1][1] or []) == "にん":
                # １人, ２人: ひとり, ふたり (read whole, the one native number reading)
                pieces[i + 1] = [b + "人", ["ひとり" if b in ("１", "1") else "ふたり"]]
                pieces[i] = ["", None]
                self.stats["sentence kana: context fixes"] += 1
                continue
            elif b in ("１人", "1人", "２人", "2人") and rd.endswith("にん"):
                new = "ひとり" if b[0] in "１1" else "ふたり"
            elif b in ("一人", "二人") and rd in ("いちにん", "ににん"):
                new = {"一人": "ひとり", "二人": "ふたり"}[b]
            elif b == "家" and rd == "か" and re.match(f"[{HIRA}]", after[:1] or "x"):
                new = "いえ"            # 夏休み中家に: Sudachi's suffix か (作家) on its own is いえ
            elif b == "米" and rd != "こめ" and not after.startswith(("国", "軍")):
                new = "こめ"
            elif b == "今" and rd == "こん" and not re.match(r"[晩週月年回度夜後日世学季朝]", after):
                new = "いま"
            elif b == "金" and not after.startswith(("曜", "メダル", "色", "髪", "属", "貨", "庫", "額", "銭", "持")):
                new = "きん" if gold else "かね"
            elif len(b) == 1 and KANJI_RE.match(b) and len(rd) >= 2:
                # okurigana leaked into the ruby ([見|みる]過ぎ): Sudachi's reading
                # of exactly this span, when it is the ruby minus trailing kana
                if sud is None:
                    sud, at = {}, 0
                    for m in self._tokenizer().tokenize(text):
                        sud[(at, at + len(m.surface()))] = hira(m.reading_form())
                        # 遠から: the kanji's own kana is the reading minus the
                        # written tail (遠 とお; a transcription says とおざ)
                        mm = re.match(f"^([{KANJI}])([{HIRA}]+)$", m.surface())
                        rf = hira(m.reading_form())
                        if mm and rf.endswith(mm.group(2)) and len(rf) > len(mm.group(2)):
                            sud.setdefault((at, at + 1), (rf[:-len(mm.group(2))], m.dictionary_form()))
                        at += len(m.surface())
                pos = sum(len(x) for x, _ in pieces[:i])
                sr = sud.get((pos, pos + 1))
                if isinstance(sr, tuple):
                    # from a kanji + kana token: only when the transcription's
                    # reading is no reading of the word (埋める うずめる is one)
                    sr, dform = sr
                    tail = re.search(f"[{HIRA}]*$", dform).group(0)
                    if dform in self._kaikki_alias().get("reading", {}).get(rd + tail, ()):
                        sr = None
                if sr and sr != rd and rd.startswith(sr) and not after.startswith(rd[len(sr):]):
                    new = sr
            if new is not None and new != rd:
                pieces[i][1] = [new]
                self.stats["sentence kana: context fixes"] += 1

    def extra_corpus_rows(self, env):
        p = env.repo / "tools" / "generated_sentences.tsv"
        rows = []
        if not p.exists():
            return rows
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
        return {
            "spoken_freq": {"source": "Tatoeba jpn_sentences_detailed.tsv, (lemma, POS) token counts after "
                                      "SudachiPy tagging (spoken proxy; hermitdave ja_full.txt is not used)",
                            "licence": "CC-BY 2.0 FR", "url": self.sources[self.sentences_file]},
            "written_freq": {"source": "wordfreq (Python package), ja list (MeCab + ipadic tokenised)",
                             "licence": "CC-BY-SA-4.0"},
            "indices": {"source": "Tatoeba jpn_indices (curated JMdict lemma per word)", "licence": "CC-BY 2.0 FR",
                        "url": self.sources[self.indices_file]},
            "sentence_kana": {"source": "Tatoeba jpn_transcriptions (furigana), else SudachiPy readings",
                              "licence": "CC-BY 2.0 FR", "url": self.sources[self.transcriptions_file]},
            "generated_sentences": {
                "source": "written for this pack (tools/generated_sentences.tsv), marked \"src\": \"gen\"",
                "licence": "CC-BY-SA-4.0", "count": n, "audio": "none (TTS)"},
        }

    def pack_json_extra(self):
        # Japanese glyph shapes: without a ja font list browsers on Apple
        # devices fall back to PingFang SC (Chinese forms); Noto Sans JP loads
        # from Google Fonts for devices with no Japanese font
        out = {"spaced": False, "rtl": False, "langTag": "ja",
               "fontFamily": '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Yu Gothic", sans-serif',
               "fonts": ["Noto Sans JP:wght@400;700"]}
        if self.compounds:
            out["compounds"] = self.compounds
        return out

    # ---- finishing ---------------------------------------------------------------------
    def finalize_words(self, env, ctx, words):
        from ..core.lexicon import GROUP_LABEL
        from ..core.tag import iter_tagged
        lx = ctx["lexicon"]
        groups = ctx.get("lemma_groups")
        info = self._group_info()
        hand_glosses = set(FIXED.values()) | {v for k, v in self.gloss_overrides.items() if not k.startswith("_")}
        rows = ctx["rows_by_sid"]
        key_to_word = {w["_key"]: w for w in words}
        self.build_keys = {w["id"]: f"{w['_key'][0]}|{GROUP_LABEL.get(w['_key'][1], w['pos'])}" for w in words}
        # --- conjugated units per token (a content token + its inflection tail)
        units = defaultdict(Counter)            # key -> Counter(unit surface), whole corpus
        ship_units = defaultdict(Counter)       # key -> Counter(unit surface) linked in shipped sentences
        unit_norm = defaultdict(Counter)        # (key, unit) -> Counter(Sudachi normal form of its head)
        sfx_units = defaultdict(Counter)        # key -> Counter(noun + taught suffix), shipped sentences
        shipped = set(self._shipped)
        ship_toks = {}
        for sid, toks in iter_tagged(ctx["tagged"]):
            row = rows.get(sid)
            if not row or not row[3]:
                continue
            res = lx.resolve_sentence(toks, groups)
            if sid in shipped:
                ship_toks[sid] = (toks, res)
            for i, r in enumerate(res):
                if r is None or r not in key_to_word:
                    continue
                j = i + 1
                if r[1] in ("VERB", "ADJ") and toks[i][2] in ("VERB", "ADJ"):
                    while j < len(toks) and toks[j][2] in ("AUX", "PART") and \
                            (toks[j][2] == "AUX" or toks[j][0] in ("て", "で", "ば", "たり", "だり", "ちゃ", "じゃ")):
                        j += 1
                        if toks[j - 1][0] in ("て", "で", "ば", "たり", "だり"):
                            break
                u = toks[i][0] + "".join(t[0] for t in toks[i + 1:j])
                if r[0].startswith("〜") and r[0][1:] not in SUFFIX_WORDS and i and NUMERAL_RE.match(toks[i - 1][0]):
                    u = toks[i - 1][0] + u      # ７時, 五時, 何ページ: a bare 時 is also a noun
                elif r[0].startswith("〜") and i and toks[i - 1][2] in ("NOUN", "PROPN", "PRON") and sid in shipped:
                    j0 = i - 1                  # 会議中, トニー君 (with a prefix: 貴職ら)
                    if "Ctr=1" in toks[j0][3] and j0 and NUMERAL_RE.match(toks[j0 - 1][0]):
                        j0 -= 1                 # 一日中, not 日中 (にっちゅう "daytime")
                    while j0 and "Pos=接頭辞" in toks[j0 - 1][3]:
                        j0 -= 1
                    sfx_units[r]["".join(t[0] for t in toks[j0:i]) + u] += 1
                units[r][u] += 1
                unit_norm[(r, u)][feats_of(toks[i][3]).get("Norm", "")] += 1
                if sid in shipped:
                    ship_units[r][u] += 1
        head_n = Counter(self.fold(w["w"]) for w in words)
        for w in words:
            k = w["_key"]
            lem = k[0]
            w["w"] = self.fold(w["w"])          # 方（かた） is shown as 方
            other_heads = {h for h, n in head_n.items() if n > (h == w["w"])}
            d = info.get(lem, {"spell": Counter(), "read": Counter(), "gspell": {}, "n": 0})
            # --- POS labels
            if k[1] == "VERB" and lem in AUXILIARIES:
                w["pos"] = "aux"
                self.function_verbs.add(lem)
            if lem.startswith("〜"):
                w["pos"] = "counter" if k[1] == "NOUN" else w["pos"]
                self.function_lemmas.add(lem)
            # --- reading
            w["pron"] = self.word_reading(w, d)
            # --- alts: other spellings + the forms the word takes in sentences.
            # Every alt shares the word's Sudachi normal form (入れる is not a
            # form of 入る); a pure potential form counts as its verb.
            allowed = set(self._norms.get(lem, ())) | {lem, self.fold(lem)}
            for src, dst in list(self.redirect.items()) + list(POTENTIAL_OF.items()):
                if dst == lem:
                    allowed |= set(self._norms.get(src, ())) | {src}
            fixed_word = not self._norms.get(lem)
            def norm_ok(u):
                if fixed_word or w["pos"] in ("aux", "part"):
                    return True
                nc = unit_norm.get((k, u))
                return not nc or nc.most_common(1)[0][0] in allowed
            alts = []
            if not lem.startswith("〜"):
                for s, n in d["gspell"].get(k[1], Counter()).most_common():
                    if s != w["w"] and n >= 3 and JA_RE.search(s) and self._same_word_spelling(s, w):
                        alts.append(s)
                heads = [w["w"]] + alts
                # the forms linked in the shipped sentences (all of them, so each
                # example shows the word), then the corpus's most used forms
                need = [u for u, n in ship_units.get(k, Counter()).most_common()
                        if not any(h in u for h in heads) and norm_ok(u)]
                for u in sorted(need, key=lambda u: (-units[k][u], u)):
                    if u not in alts:
                        alts.append(u)
                        self.stats["alts: forms linked in shipped sentences"] += 1
                if k[1] in ("VERB", "ADJ") and w["pos"] != "aux":
                    for u, n in units.get(k, Counter()).most_common():
                        if len(alts) >= 8:
                            break
                        # a unit starting with a spelling adds nothing (大きいです, けっこうです)
                        if n >= 2 and not any(u.startswith(h) for h in heads) and u not in alts and \
                                len(u) > 1 and norm_ok(u):
                            alts.append(u)
                self.stats["alts: forms left out (another normal form)"] += sum(
                    1 for u in units.get(k, ()) if not norm_ok(u))
            else:
                alts.append(lem[1:])
                for s, n in d["gspell"].get(k[1], Counter()).most_common():
                    if s != lem[1:] and n >= 3 and JA_RE.search(s):
                        alts.append(s)          # 〜たち: 達; 〜ヶ月: か月
                # a taught suffix spelled like another word's headword (中 なか,
                # 君 きみ) cannot be found bare: it keeps its uses in the shipped
                # sentences whole (会議中, トニー君). The suffix links only where it
                # follows a noun or name (_analyse), so these are real uses
                taken = [s for s in alts if s in other_heads]
                for u, n in sorted(sfx_units.get(k, Counter()).items(), key=lambda x: (-x[1], x[0])):
                    if u not in alts and any(u.endswith(s) for s in taken):
                        alts.append(u)
                        self.stats["alts: suffix uses kept whole (bare suffix is another word)"] += 1
                # the counter with its number as the shipped sentences write it
                # (７時, 五時): a bare 時 cannot be told from the noun. A taught
                # suffix (〜さん, 〜中) keeps its bare spellings only: 会議中, 娘さん
                # are two words, and 明日君 was never one
                for u, n in sorted(ship_units.get(k, Counter()).items(), key=lambda x: (-units[k][x[0]], x[0])):
                    if u not in alts and len(u) > len(lem) - 1 and NUMERAL_RE.match(u[:-(len(lem) - 1)]):
                        alts.append(u)
                        self.stats["alts: counters with their number"] += 1
            if lem in MONTHS:
                n = MONTHS.index(lem) + 1
                alts += [f"{n}月", f"{n}月".translate(str.maketrans("0123456789", "０１２３４５６７８９"))]
            if lem == "おはよう":
                alts.append("おはようございます")
            if lem == "ありがとう":
                alts += ["ありがとうございます", "ありがとうございました"]
            if alts:
                # a homograph label never shows (分（ぶん） is 分)
                w["alt"] = list(dict.fromkeys(f for f in (self.fold(a) for a in alts) if f != w["w"]))
            else:
                w.pop("alt", None)
            hand = w["en"] in hand_glosses
            w["en"] = self._style(w["en"], verb=w["pos"] == "verb" and not hand, hand=hand)
            if lem not in NUMBERS:
                self._pron_follows_gloss(w, d)
            en2 = re.sub(r"[\s,;:、，]+$", "", w["en"])
            if en2 != w["en"]:
                self.stats["glosses: trailing punctuation removed"] += 1
                w["en"] = en2
            if re.match(r"(?i)that which\b", w["en"]):
                self.gloss_flags.append(f"{lem}: {w['en']}")
            if w["pos"] == "noun" and w["en"][:3].lower() == "to " and not hand:
                w["en"] = w["en"][0].lower() + w["en"][1:]
                w["en"] = self._suru_noun_gloss(lem, w["en"])
        # a kanji spelling shown as an alt must mean what the word means (なし
        # "without" is not 梨 "pear"; よる "to depend on" is not 寄る): the
        # spellings note_words found to be another word
        fs = getattr(self, "_foreign_spell", {})
        for w in words:
            bad = fs.get(w["_key"][0])
            if not bad or not w.get("alt"):
                continue
            # 寄る and its forms 寄って, 寄ります (the stem before the kana ending)
            stems = tuple(re.sub(f"[{HIRA}]+$", "", b) or b for b in bad)
            keep = [a for a in w["alt"] if not a.startswith(stems)]
            self.alt_sense_drops += [f"{w['w']}: {a}" for a in w["alt"] if a.startswith(stems)]
            if keep:
                w["alt"] = keep
            else:
                w.pop("alt")
        # a kana spelling that another pack word also reads (おる: 折る and the
        # humble おる; いる: 居る and 要る) cannot show which word it is: a kanji
        # word sharing its reading with another pack word keeps no kana alts
        by_pron = Counter(pr for pr, _ in {(w["pron"], w["w"]) for w in words})   # 大変 adj/adv is one headword
        kana_heads = {w["w"] for w in words if KANA_ONLY_RE.match(w["w"])}
        for w in words:
            if not KANJI_RE.search(w["w"]) or not w.get("alt"):
                continue
            if by_pron[w["pron"]] > 1 or w["pron"] in kana_heads:
                keep = [a for a in w["alt"] if not KANA_ONLY_RE.match(a)]
                self.stats["alts: kana alts dropped (reading shared with another word)"] += len(w["alt"]) - len(keep)
                if keep:
                    w["alt"] = keep
                else:
                    w.pop("alt")
        self._prune_alts(words, ship_toks, key_to_word)
        self._link_stats(words, ship_toks, key_to_word)
        from ..core.util import stat
        stat("ja", dict(sorted(self.stats.items())))
        stat("ja_pron_changes", self.pron_changes)
        stat("ja_first_sound_folded", self.sound_folded)
        stat("ja_spelling_merges", self.spelling_merges)
        stat("ja_redirects", dict(sorted(self.redirect.items())))
        stat("ja_alt_sense_drops", self.alt_sense_drops)
        stat("ja_foreign_kanji_spellings", getattr(self, "foreign_spellings", []))
        stat("ja_gloss_flags_that_which", self.gloss_flags)

    def _same_word_spelling(self, s, w):
        """A variant spelling shown as an alt: the word's kana reading, or a
        spelling Wiktionary links to it as an alternative form (観る for 見る,
        not 診る; ほとり is another reading of 辺, not an alt)."""
        if hira(s) == hira((w.get("pron") or "").lstrip("〜")):
            return True
        if KANA_ONLY_RE.match(s) and self._info:
            # a kana spelling the corpus uses for >= 20% of the word (何: なに, なん;
            # dictionary-form readings always say なに)
            sp = self._info.get(w["lemma"], {}).get("spell") or Counter()
            if sp.get(s, 0) / (sum(sp.values()) or 1) >= 0.2:
                return True
        if not KANJI_RE.search(s):
            return False          # a kana alt is the word's own reading or nothing (方 is not かた)
        alias = self._kaikki_alias()["alias"]
        heads = {w["w"], w["lemma"]} | set(alias.get(w["w"], ()))
        return bool(heads & set(alias.get(s, ()))) or s in set(alias.get(w["w"], ()))

    def _read_counts(self, lem, d):
        """Corpus readings of a word, with the tokens of reading homographs
        folded into it (金（かね） tokens count for 金)."""
        c = Counter(d.get("read") or {})
        for src, dst in self.redirect.items():
            if dst == lem and self._info and src in self._info:
                c.update(self._info[src].get("read") or {})
        return c

    def _pron_follows_gloss(self, w, d):
        """A kanji word Wiktionary reads several ways shows the reading of the
        entry its gloss came from (表 "surface, front" is おもて, not ひょう),
        when the corpus uses that reading (>= 20% of its tokens)."""
        lem = w["lemma"]
        base = self.fold(lem)
        if not KANJI_RE.search(base) or lem.startswith("〜") or lem in MONTH_PRON or lem in FIXED_READ:
            return
        ents = [e for e in (self._orig_E.get(lem) or self._lx.E.get(lem, [])) if e.get("g") and
                e["p"] not in ("name", "character", "affix", "prefix", "phrase")]
        if len({e["g"] for e in ents}) < 2:
            return
        self.stats["readings: multi-reading kanji words checked"] += 1
        first = re.split(r"[;,]", w["en"])[0].strip().lower()
        first = re.sub(r"^to ", "", re.sub(r"\s*\([^)]*\)", "", first)).strip()
        if not first:
            return
        src = {e["g"] for e in ents for sn in e["s"][:4]
               if sn[3] == "" and re.search(rf"\b{re.escape(first)}\b", sn[0].lower())}
        pron = w["pron"].lstrip("〜")
        if not src:
            return
        rc = self._read_counts(lem, d)
        tot = sum(rc.values()) or 1
        best = max(src, key=lambda r: (rc.get(r, 0), r))
        if best == pron or (pron in src and rc.get(best, 0) <= rc.get(pron, 0)):
            return
        if rc.get(best, 0) / tot >= 0.2:
            self.stats["readings: changed to the gloss entry's reading"] += 1
            self.pron_changes.append(f"{lem}: {w['pron']} -> {best}")
            w["pron"] = best
        else:
            self.stats["readings: gloss entry reading rare in corpus (kept)"] += 1

    def word_reading(self, w, d):
        """Kana reading of the word: the reading of the Wiktionary entry its
        gloss came from; the corpus reading otherwise. Katakana words keep
        katakana; counters show 〜 + reading."""
        lem = w["lemma"]
        if lem in MONTH_PRON:
            return MONTH_PRON[lem]
        if lem in FIXED_READ:
            return FIXED_READ[lem]
        if lem in COUNTER_READ:
            return "〜" + COUNTER_READ[lem]
        base = self.fold(lem[1:] if lem.startswith("〜") else lem)
        prefix = "〜" if lem.startswith("〜") else ""
        if KATA_ONLY_RE.match(base):
            return prefix + base
        if HIRA_ONLY_RE.match(base):
            return prefix + base
        # a reading must fit the headword's kana (信じる is しんじる, never しんずる)
        pat = re.compile("".join(re.escape(hira(c)) if KANA_ONLY_RE.match(c) else ".+" for c in base))
        fits = lambda r: bool(r) and bool(pat.fullmatch(hira(r)))
        corpus = next((r for r, _ in self._read_counts(lem, d).most_common() if fits(r)), "")
        ents = [e for e in self._lx.E.get(lem, []) if e["p"] == w.get("_epos")] or self._lx.E.get(lem, [])
        readings = [e["g"] for e in ents if fits(e.get("g"))]
        # the corpus reading when a Wiktionary entry of the word has it (Sudachi
        # reads the tokens in context); else the entry's own reading
        reading = corpus if corpus and (corpus in readings or not readings) else (readings[0] if readings else corpus)
        return prefix + (reading or base)

    def _suru_noun_gloss(self, lem, en):
        """A する-noun glossed from its verb sense (購入 "to purchase"): lead with
        a short noun sense when Wiktionary has one ("purchase; to purchase"),
        else mark the verb use ("to order (+ suru)")."""
        for e in self._lx.E.get(lem, []):
            if e["p"] != "noun":
                continue
            for sn in e["s"]:
                if sn[3]:
                    continue
                first = re.sub(r"^(?:a|an|the)\s+", "", sn[0].split(",")[0].split(";")[0].strip(), flags=re.I)
                if first and len(first.split()) <= 2 and not re.search(r"[^\x00-\x7f]", first):
                    return f"{first.lower()}; {en}"
                break
        return f"{en} (+ suru)"

    @staticmethod
    def _style(en, verb=False, hand=False):
        en = re.sub(r"\s*\([^()]*[぀-鿿][^()]*\)", "", en)     # (Japanese mentions)
        en = re.sub(f"[{JA}]+", "", en) if JA_RE.search(en) else en
        en = re.sub(r"\s{2,}", " ", en).strip(" ,;:")
        # "the color white" -> "white" (a color word's sense names the color)
        en = re.sub(r"^(?:the )?colou?r (?=[a-z-]+(?:$|[,;]))", "", en)
        # a gloss cut at the length cap ends mid-phrase ("situation of something that");
        # hand glosses end as written ("by, with", "or", "as far as")
        for _ in range(0 if hand else 3):
            # a verb keeps its particle ("to count on", "to get by")
            dangling = r"that|the|a|an|and|or|which|regardless" if verb else \
                r"that|of|for|the|a|an|to|and|or|which|with|by|in|on|at|from|regardless"
            en2 = re.sub(rf"\s+(?:{dangling})$", "", en)
            if en2 == en:
                break
            en = en2
        if verb:
            # every verb alternative reads "to ..." ("pay" -> "to pay")
            segs = []
            for seg in en.split("; "):
                # split on commas outside brackets: "to exist (people, animals)"
                raw_parts = re.split(r",\s+(?![^()]*\))", seg)
                parts = []
                for x in raw_parts:
                    after_be = bool(parts) and parts[-1].startswith("to be ")
                    parts.append(x if x.startswith(("to ", "(")) or not re.match(r"^[a-z]", x) or after_be
                                 else "to " + x)
                segs.append(", ".join(parts))
            en = "; ".join(segs)
        return en

    def _prune_alts(self, words, ship_toks, key_to_word):
        """An alt is kept only where it finds the word: in the shipped sentences
        every place the alt occurs as a substring must start a token of this
        word. Occurrences of any form inside another word's unit are listed in
        pack.compounds so the engine never blanks or bolds them there."""
        forms = {}
        for w in words:
            forms[w["id"]] = [w["w"]] + list(w.get("alt") or [])
        by_id = {w["id"]: w for w in words}
        id_of = {k: w["id"] for k, w in key_to_word.items()}
        lemma_id = {}
        for w in sorted(words, key=lambda x: x["rank"]):
            lemma_id.setdefault(w["lemma"], w["id"])
        bad_alt = defaultdict(int)
        good_alt = defaultdict(int)
        compounds = set()
        for sid, (toks, res) in sorted(ship_toks.items()):
            text = "".join(t[0] for t in toks)
            starts, ends, owner = [], [], []
            o = 0
            for t, r in zip(toks, res):
                starts.append(o)
                o += len(t[0])
                ends.append(o)
                owner.append(id_of.get(r) if r else None)
            start_of = defaultdict(set)
            for i, wid in enumerate(owner):
                if wid:
                    start_of[wid].add(starts[i])
            # a token of the word's lemma that links nothing here (する absorbed
            # by 勉強, いる in ている) is still the word's own form
            for i, t in enumerate(toks):
                if t[1] in lemma_id:
                    start_of[lemma_id[t[1]]].add(starts[i])
            for wid, fs in forms.items():
                for fi, f in enumerate(fs):
                    if not f or f not in text:
                        continue
                    at = text.find(f)
                    while at >= 0:
                        if at in start_of.get(wid, ()) or \
                                any(at < st < at + len(f) for st in start_of.get(wid, ())):
                            # the occurrence starts at, or holds, a token of the word (７時)
                            if fi:
                                good_alt[(wid, f)] += 1
                        else:
                            # the tokens covering this occurrence: listed in
                            # pack.compounds they shield it; an occurrence that is
                            # exactly other words' tokens cannot be shielded
                            i = next(j for j in range(len(toks)) if starts[j] <= at < ends[j])
                            j = next(j for j in range(i, len(toks)) if ends[j] >= at + len(f))
                            unit = text[starts[i]:ends[j]]
                            # tokens that link nothing (いく in いくつめ, 様 after a
                            # verb) in a sentence without the word show no form:
                            # the engine bolds and blanks linked words only
                            if unit == f and fi and (wid in start_of or any(owner[x] for x in range(i, j + 1))):
                                bad_alt[(wid, f)] += 1
                        at = text.find(f, at + 1)
        dropped = 0
        for w in words:
            if not w.get("alt"):
                continue
            keep = [a for a in w["alt"] if bad_alt[(w["id"], a)] == 0 or
                    good_alt[(w["id"], a)] >= 9 * bad_alt[(w["id"], a)]]
            dropped += len(w["alt"]) - len(keep)
            if keep:
                w["alt"] = keep
            else:
                w.pop("alt")
        self.stats["alts dropped (found inside other words)"] = dropped
        self._make_compounds(words, ship_toks, key_to_word, lemma_id)

    def _make_compounds(self, words, ship_toks, key_to_word, lemma_id):
        """pack.compounds shields a false occurrence of a linked word's form
        (はい inside は+いつも in a sentence linking はい) so the engine does not
        bold or blank it there. Only occurrences in sentences that link the word
        need a shield. Each shield is the shortest window around the occurrence
        (1-3 more characters) that covers no true match anywhere in the pack:
        a shield must never hide a word where it is really linked."""
        forms = {w["id"]: [x for x in [w["w"]] + list(w.get("alt") or []) if x] for w in words}
        id_of = {k: w["id"] for k, w in key_to_word.items()}
        texts, trues, needs = [], [], []
        for sid, (toks, res) in sorted(ship_toks.items()):
            text = "".join(t[0] for t in toks)
            starts, o = [], 0
            for t in toks:
                starts.append(o)
                o += len(t[0])
            start_of = defaultdict(set)
            linked = set()
            for i, r in enumerate(res):
                wid = id_of.get(r) if r else None
                if wid:
                    start_of[wid].add(starts[i])
                    linked.add(wid)
            for i, t in enumerate(toks):
                if t[1] in lemma_id:
                    start_of[lemma_id[t[1]]].add(starts[i])
            tr, nd = [], []
            for wid in linked:
                for f in forms[wid]:
                    at = text.find(f)
                    while at >= 0:
                        true = at in start_of[wid] or any(at < st < at + len(f) for st in start_of[wid])
                        (tr if true else nd).append((at, at + len(f)))
                        at = text.find(f, at + 1)
            # a false hit overlapping a true hit of the same word merges with it
            nd = [(a, b) for a, b in nd if not any(a < tb and ta < b for ta, tb in tr)]
            texts.append(text)
            trues.append(tr)
            needs.append(nd)
        sep = "\u0000"
        big = sep.join(texts)
        offs, o = [], 0
        for t in texts:
            offs.append(o)
            o += len(t) + 1
        import bisect
        true_iv = sorted((offs[i] + a, offs[i] + b) for i, tr in enumerate(trues) for a, b in tr)
        true_starts = [a for a, _ in true_iv]

        def harmful(c):
            at = big.find(c)
            while at >= 0:
                end = at + len(c)
                j = bisect.bisect_left(true_starts, at)
                while j < len(true_iv) and true_iv[j][0] < end:
                    a, b = true_iv[j]
                    if b <= end and b - a < len(c):
                        return True
                    j += 1
                at = big.find(c, at + 1)
            return False
        chosen, cache, n_need, n_none = set(), {}, 0, 0
        for i, nd in enumerate(needs):
            text = texts[i]
            for a, b in sorted(set(nd)):
                n_need += 1
                if any(text.find(c) >= 0 and any(x <= a and x + len(c) >= b
                       for x in [m.start() for m in re.finditer(re.escape(c), text)]) for c in chosen):
                    continue
                got = None
                for extra in (1, 2, 3):
                    for left in range(extra + 1):
                        l, r = a - left, b + extra - left
                        if l < 0 or r > len(text):
                            continue
                        c = text[l:r]
                        if c not in cache:
                            cache[c] = harmful(c)
                        if not cache[c]:
                            got = c
                            break
                    if got:
                        break
                if got:
                    chosen.add(got)
                else:
                    n_none += 1
        self.compounds = sorted(chosen)
        self.stats["compounds"] = len(self.compounds)
        self.stats["compounds: false occurrences in linking sentences"] = n_need
        self.stats["compounds: false occurrences left unshielded (every window hides a true match)"] = n_none

    def _link_stats(self, words, ship_toks, key_to_word):
        """How the shipped sentence links were decided: confirmed or corrected
        by jpn_indices, or Sudachi alone."""
        c = Counter()
        for sid, (toks, res) in ship_toks.items():
            for t, r in zip(toks, res):
                if r and r in key_to_word:
                    src = feats_of(t[3]).get("Src")
                    c["indices (confirmed)" if src == "idx" else "indices (corrected)" if src == "idx+"
                      else "sudachi"] += 1
        self.stats.update({f"links: {k}": v for k, v in c.items()})

    # ---- script primer ------------------------------------------------------
    script = {"stages": [{"key": "hira", "label": "ひらがな"}, {"key": "kata", "label": "カタカナ"}],
              "setsPerSession": 2, "mastered": 3, "tts": True,
              "learnKinds": ["symSound", "soundSym"],
              "reviewKinds": ["symSound", "soundSym", "compose", "wordRead"],
              "testKinds": {"symSound": 35, "soundSym": 25, "wordRead": 25, "symType": 15}}

    def script_units(self):
        return _ja_script_units()

    def script_notes(self):
        return JA_SCRIPT_NOTES

    def script_text(self, word):
        return word.get("pron")

    def _script_glyphs(self):
        if not hasattr(self, "_script_glyph_ids"):
            self._script_glyph_ids = {u["t"]: u["id"] for u in _ja_script_units()}
        return self._script_glyph_ids

    def script_tokens(self, text):
        if not _JA_KANA_RE.match(text or ""):
            return None
        g, toks, i = self._script_glyphs(), [], 0
        while i < len(text):
            two = text[i:i + 2]
            if len(two) == 2 and two[1] in _JA_SMALL and two in g:
                if two[1] in _JA_SMALL_Y:
                    # yōon: named for examples, read from its parts (き + ゃ)
                    n = len(toks)
                    toks += [(g[two], True, n, False), (g.get(two[0]), False, n), (g[two[1]], True, n)]
                else:
                    toks.append((g[two], True, len(toks)))
                i += 2
                continue
            toks.append((g.get(text[i]), text[i] in g, len(toks)))
            i += 1
        return toks

    def script_ex_policy(self, unit):
        """Katakana: the first two levels hold only 62 katakana words, so an example
        may hold two unknown katakana and come from the third level as a last
        resort (the validator warns, not errors, for a later stage's third level)."""
        return (2, 3) if unit["st"] == "kata" else (1, 2)

    def script_syllables(self, text):
        """yōon in text: (きゃ, [き, ゃ], kya, owners [きゃ, ゃ]). A hiragana yōon also
        gives its katakana twin (キャ, [キ, ャ]): the katakana stage re-teaches sounds
        the first level writes in hiragana, and has too few katakana words of its own
        to pad a compose item (A1 has one katakana yōon, ニュ). The validator accepts
        a later stage's syllable attested in a first-level word after kana folding."""
        g, out = self._script_glyphs(), []
        for i in range(len(text or "") - 1):
            two = text[i:i + 2]
            if two[1] in _JA_SMALL_Y and two in g and two[0] in g:
                out.append((two, [g[two[0]], g[two[1]]], romaji(two), [g[two], g[two[1]]]))
                kt = _ja_kata(two)
                if kt != two and kt in g:
                    out.append((kt, [g[kt[0]], g[kt[1]]], romaji(two), [g[kt], g[kt[1]]]))
        return out

    def script_ex_ok(self, word):
        """は and へ as particles are read wa and e, not their kana sound."""
        return not (word.get("pos") == "part" and word.get("w") in ("は", "へ"))

    def script_ex_roman(self, word, text, toks):
        return romaji(text)

    def script_say(self, unit):
        """Bare kana (docs/SCRIPT_PRIMER.md ss5 default), except: は/へ are said in
        katakana so a voice never reads them as the particles wa/e; を, ぢ, づ and
        the small ゃ ゅ ょ are said as the kana they sound like. っ and ー have no sound."""
        if unit.get("sound") is False:
            return None
        t = unit["t"]
        return {"は": "ハ", "へ": "ヘ", "を": "お", "ぢ": "じ", "づ": "ず",
                "ヲ": "オ", "ヂ": "ジ", "ヅ": "ズ",
                "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ"}.get(t, t)


SPEC = Japanese
