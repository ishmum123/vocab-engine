"""Persian (fa): everything Persian-specific in the pack pipeline.

Tagger: Stanza (fa default package, UD Persian-Seraji model); spaCy has no
Persian pipeline. Stanza splits enclitics (دوستم = دوست + م); a split token is
kept whole with its host word's lemma/POS, since frequency-list surfaces are
whole tokens. Its verb lemmas are past stems (رفت); the pack lemma is the
infinitive (رفتن), and the present stem (رو) goes in alt.

Spelling: every matching side is folded (Arabic ي/ك -> Persian ی/ک, harakat and
tatweel stripped, ZWNJ removed), so می\u200cروم = میروم. The displayed word keeps
ZWNJ (finalize_words restores the corpus / dictionary spelling). Text fed to
the tagger joins detached می/نمی prefixes and -ها/-تر suffixes with ZWNJ.

Frequency: the subtitle list is colloquial Tehrani (میخوام, اون, خونه); the top
forms are mapped to their written forms before matching (COLLOQUIAL).

Light verbs: noun/adjective + کردن/شدن/زدن/... compounds from LIGHT_VERBS are
lemmas of their own (کار کردن "to work"), counted and linked when the noun and
the light verb stand within 3 tokens (کار نمی\u200cکنم, کار خواهم کرد).

Sentences: Tatoeba has only ~8.2k Persian sentences with an English link.
All 31.8k are tagged (frequency and lemma evidence); only linked ones ship.
Words left under 2 sentences get sentences written for the pack
(tools/generated_sentences.tsv, "src": "gen" in sentences.json).
"""
import gzip
import hashlib
import json
import re

from .base import LanguageSpec, TATOEBA_ENG, TATOEBA_AUDIO, DEFAULT_GROUP_KPOS, SENSITIVE_EN, SENSITIVE_GLOSS_EN, drop_all_re

ZWNJ = "\u200c"
LET = "ء-غف-يٱ-ۓۺ-ۿ"
MARKS_RE = re.compile("[\u064b-\u065f\u0670\u0640\u200d\u200e\u200f]")   # harakat, superscript alef, tatweel, ZWJ, LRM/RLM
CHAR_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "ە": "ه", "ھ": "ه",
                          "ٱ": "ا"})
TANWIN_KEEP_RE = re.compile("[\u064c-\u065f\u0670\u0640\u200d\u200e\u200f]")   # strips all marks but tanwin fath (لطفاً)
# grammatical endings a lemma may carry inside a token (plural, -ی, clitics,
# copula, comparative); anything else means the lemma is only a substring
GRAM_SUFFIX_RE = re.compile("(ها|های|هایی|ان|ات|ین|گان)?(ی|ای|یی)?"
                            "(ام|ات|اش|مان|تان|شان|م|ت|ش|یم|یش|ست|است|اند|ایم|اید|ند|ید|تر|ترین|مون|تون|شون)?")
# passages only: a comparative may come before the indefinite ی (مهم‌تری)
PASSAGE_SUFFIX_RE = re.compile("(ها|های|هایی|ان|ات|ین|گان)?(تر|ترین)?(ی|ای|یی)?"
                               "(ام|ات|اش|مان|تان|شان|م|ت|ش|یم|یش|ست|است|اند|ایم|اید|ند|ید)?")
# Tatoeba sentences with errors (ungrammatical, a typo that reads as vulgar,
# a misspelt verb, a nonsense translation): matched as substrings
BAD_SENTENCES = ("او از من شروع کرد", "مرد درخت را تحت است", "به ذهن تام رید", "حضور داشیم", "این جعبه از جوب است")
_DISPLAY_CHARS = str.maketrans({"\u064a": "\u06cc", "\u0649": "\u06cc", "\u0643": "\u06a9"})
_MI_SPACE_RE = re.compile("(^|[\\s\u200c«(])(ن?می) (?=[" + LET + "])")


DERIV_SUFFIX = [("انه", "âne"), ("ترین", "tarin"), ("ین", "in"), ("ان", "ân"), ("یی", "yi"), ("ی", "i"),
                ("یه", "iye"), ("تا", "tâ")]
_CLASSICAL = str.maketrans({"ā": "â", "ī": "i", "ū": "u", "ē": "i", "ō": "u", "i": "e", "u": "o"})
_PRON_MAP = [("x", "kh"), ("š", "sh"), ("č", "ch"), ("ž", "zh"), ("ê", "e"), ("ô", "o"), ("î", "i"), ("û", "u"),
             ("ʼ", "'"), ("’", "'")]


def normalize_pron(p, key=""):
    """One romanisation scheme for the whole pack (Iranian Persian, the
    kaikki "Iranian" reading made ASCII-light): â long a; a e o short;
    i u long; kh sh ch zh; q for ق and gh for غ (Wiktionary writes both ġ);
    ' for ع/ء. A Classical-only romanisation (ā ī ū, short i u) is converted."""
    if not p:
        return p
    p = p.strip().lower()
    if re.search("[āīūēō]", p):
        p = p.translate(_CLASSICAL)
    for a, b in _PRON_MAP:
        p = p.replace(a, b)
    letters = [c for c in fold(key) if c in "قغ"]
    k = [0]

    def qg(m):
        c = letters[k[0]] if k[0] < len(letters) else ("غ" if m.group(0) in ("gh", "ğ") else "ق")
        k[0] += 1
        return "q" if c == "ق" else "gh"
    p = re.sub("ġ|ğ|gh|q", qg, p)
    if fold(key)[:1] == "ع":
        p = p.lstrip("'ʼ")        # initial ع is silent at the start: eyd, adâlat (no apostrophe)
    return p


def display_sentence(text):
    """Sentence text as shown: Arabic yeh/kaf -> Persian letters, and the
    verbal prefix می/نمی joined with ZWNJ (می روم -> می‌روم). Matching folds
    both, so this changes display only."""
    text = text.translate(_DISPLAY_CHARS)
    return _MI_SPACE_RE.sub(lambda m: m.group(1) + m.group(2) + ZWNJ, text)


KESH_PULL = {"سیگار", "نفس", "طول", "خط", "نقشه", "دراز", "انتظار", "فریاد", "درد", "زحمت", "آه", "عکس",
             "نقاشی", "بیرون", "جیغ", "خجالت", "رنج", "سختی", "پیپ", "قلیان", "ناز", "دست", "کنار", "بالا", "پایین"}
NUM_HEADS = {"ساعت", "سال", "روز", "ماه", "هفته", "دقیقه", "ثانیه", "قرن", "شماره", "صفحه", "طبقه", "کلاس", "درجه"}
INDEF_OBJECT_LV = {("کار", "کردن"), ("دوست", "داشتن")}   # noun + indefinite -ی is the object here
INDEF_DET = {"یک", "هیچ", "چند", "چنین", "همچین", "چه", "یه"}
HOMOGRAPH_DENY = {"دعوی", "حقوق", "حقوقی", "اسرار"}
HOMOGRAPH_EN = {"کاری": r"\bcurr(y|ies)\b", "شیر": r"\b(tap|faucet)\b"}
HARAKAT_HOMOGRAPH = {"آخر": "آخُر"}
SPACED_PAIRS = {("پیش", "بینی"), ("پیش", "گیری"), ("پی", "گیری")}
SUFFIX_WORDS = {"گو", "گویی", "ریزی", "بینی", "کاری", "گیری", "آوری", "سازی", "شناسی", "گذاری", "رسانی", "نویسی", "پردازی"}

# compound nouns that take a complement between them and the light verb
# (سوار قطار شد, وارد اتاق شد, احساس خستگی کرد, علاقه‌ای به تاریخ ندارم)
COMPLEMENT_NOUNS = {"سوار", "وارد", "احساس", "تغییر", "علاقه", "پاسخ", "جواب", "سعی", "تلاش", "خارج", "عاشق",
                    "متوجه", "مراقب", "شروع", "عادت", "کمک", "نگاه", "نیاز", "احتیاج", "اعتماد", "ربط", "خبر", "اهمیت"}
CLITIC_SUFFIXES = {"م", "ت", "ش", "مان", "تان", "شان", "ی", "یم", "ید", "ند", "ست", "ام", "ای", "اید", "اند",
                   "یش", "یی", "ایم", "مون", "تون", "شون"}
COLLOQ_RAFTAN = {"برم", "بری", "بره", "بریم", "برن", "میرم", "میری", "میره", "میریم", "میرید", "میرن",
                 "نمیرم", "نمیری", "نمیره", "نمیریم", "نمیرید", "نمیرن", "نرم", "نره"}
TOKEN_PUNCT = "،؛؟!.:«»\"'()…"
PART_ADJ = {"پیچیده", "گسترده", "پخته", "سوخته", "یخزده"}   # participles taught as adjectives
GEN_SID_BASE = 90_000_000          # corpus sids of sentences written for the pack


FINAL_HAMZA_RE = re.compile("اء(?![\u0600-\u06ff])")
HAMZA_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "ؤ": "و"})


def fold(s):
    """Matching spelling: Arabic yeh/kaf -> Persian, harakat/tatweel stripped,
    ZWNJ removed, hamza carriers folded (رأی = رای, مؤسسه = موسسه, پائین = پایین)."""
    if not s:
        return s
    s = MARKS_RE.sub("", s.translate(CHAR_MAP)).replace(ZWNJ, "").translate(HAMZA_FOLD).replace("ائ", "ای")
    return FINAL_HAMZA_RE.sub("ا", s)      # ابتداء = ابتدا, انشاء = انشا


def display_norm(s):
    """Display spelling: Persian yeh/kaf, harakat/tatweel stripped, ZWNJ kept."""
    if not s:
        return s
    return MARKS_RE.sub("", s.translate(CHAR_MAP)).strip()


# ---- closed sets (folded spellings; DISPLAY restores ZWNJ) --------------------
DAYS = "شنبه یکشنبه دوشنبه سهشنبه چهارشنبه پنجشنبه جمعه".split()
MONTHS = "فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند".split()
SEASONS = "بهار تابستان پاییز زمستان".split()
NUMBERS = ("صفر یک دو سه چهار پنج شش هفت هشت نه ده یازده دوازده سیزده چهارده پانزده شانزده هفده هجده "
           "نوزده بیست سی چهل پنجاه شصت هفتاد هشتاد نود صد هزار").split()
COLOURS = "سفید سیاه قرمز سبز آبی زرد نارنجی قهوهای خاکستری صورتی بنفش".split()
GREETINGS = "بله نه سلام خداحافظ ممنون متشکرم لطفا ببخشید".split()
PRONOUNS = "من تو او ما شما آنها".split()
DEMONSTR = "این آن".split()
QUESTION = [("چه", "PRON"), ("کی", "PRON"), ("کجا", "ADV"), ("چرا", "ADV"), ("چطور", "ADV"),
            ("چگونه", "ADV"), ("چند", "DET"), ("کدام", "DET"), ("چقدر", "ADV")]
PREPS = "به از در با برای تا روی زیر بدون پیش پشت کنار بین".split()
CONJS = [("و", "CONJ"), ("یا", "CONJ"), ("اما", "CONJ"), ("ولی", "CONJ"), ("که", "CONJ"),
         ("اگر", "CONJ"), ("چون", "CONJ")]
FUNCTION = set("را که به از در با تا و یا اما".split())
DISPLAY = {"سهشنبه": "سه\u200cشنبه", "پنجشنبه": "پنج\u200cشنبه", "قهوهای": "قهوه\u200cای", "لطفا": "لطفا\u064b",
           "آنها": "آن\u200cها", "اینها": "این\u200cها", "تخممرغ": "تخم\u200cمرغ", "کتابخانه": "کتابخانه",
           "میتوان": "می\u200cتوان", "خواهش میکنم": "خواهش می\u200cکنم", "ابتدا": "ابتدا",
           # reduplicated / هیچ compounds the corpus writes without ZWNJ
           "کمکم": "کم\u200cکم", "هیچوقت": "هیچ\u200cوقت", "هیچکس": "هیچ\u200cکس", "هیچکدام": "هیچ\u200cکدام"}
# passages: English words too common to show a gloss is meant (_mark_en_gloss)
EN_GLOSS_STOP = frozenset("the and for with from into that this one who which what little".split())
# a counted unit after نه makes it "nine" (نه سال, نه نفر); corpus and passages
NINE_UNITS = frozenset({"سال", "ساعت", "روز", "ماه", "نفر", "دقیقه", "هفته", "بار", "کتاب", "تا"})
PLEASE_PHRASE = "خواهش میکنم"      # "you're welcome / please", taught as one phrase
FIXED_PRON = {"ابتدا": "ebtedâ", "همگی": "hamegi", "اینکه": "inke", "خواهش میکنم": "xâheš mikonam", "یعنی": "ya'ni", "ایشان": "išân", "لطفا": "lotfan", "متشکرم": "motešakkeram", "ببخشید": "bebaxšid", "خداحافظ": "xodâhâfez",
              "آنها": "ânhâ", "سهشنبه": "se-šanbe", "پنجشنبه": "panj-šanbe", "قهوهای": "qahve-i"}

# ---- light-verb compounds: "noun verb|gloss"; a leading preposition is part of
# the compound (از دست دادن "to lose" vs دست دادن "to shake hands") -------------
LIGHT_VERBS_SRC = """
کار کردن|to work
دیر کردن|to be late
صحبت کردن|to talk, to speak
فکر کردن|to think
حرف زدن|to talk, to speak
دوست داشتن|to like, to love
زندگی کردن|to live
کمک کردن|to help
پیدا کردن|to find
پیدا شدن|to be found, to turn up
گوش دادن|to listen
گوش کردن|to listen
نگاه کردن|to look, to watch
شروع کردن|to start, to begin
شروع شدن|to start, to begin (intr.)
استفاده کردن|to use
صبر کردن|to wait
باز کردن|to open
باز شدن|to open (intr.)
بسته شدن|to close (intr.)
بلند شدن|to get up, to stand up
بلند کردن|to lift, to raise
درست کردن|to make, to fix
درست شدن|to be fixed, to work out
تمام کردن|to finish
تمام شدن|to end, to be finished
گریه کردن|to cry
زنگ زدن|to call, to phone
خرید کردن|to shop
سفر کردن|to travel
عوض کردن|to change
عوض شدن|to change (intr.)
تغییر کردن|to change (intr.)
تغییر دادن|to change
یاد گرفتن|to learn
یاد دادن|to teach
دوش گرفتن|to take a shower
تصمیم گرفتن|to decide
عکس گرفتن|to take a photo
جواب دادن|to answer
پاسخ دادن|to answer, to reply
قول دادن|to promise
اجازه دادن|to allow
نشان دادن|to show
انجام دادن|to do, to carry out
انجام شدن|to be done
ادامه دادن|to continue
توضیح دادن|to explain
دست زدن|to touch; to clap
دست دادن|to shake hands
از دست دادن|to lose
قدم زدن|to walk, to stroll
حدس زدن|to guess
صدا زدن|to call (someone)
صدا کردن|to call (someone)
سر زدن|to drop by, to visit
گول زدن|to trick, to fool
حرکت کردن|to move, to set off
عجله کردن|to hurry
تماس گرفتن|to contact, to call
تلفن کردن|to phone
ازدواج کردن|to marry
فراموش کردن|to forget
باور کردن|to believe
قبول کردن|to accept
رانندگی کردن|to drive
آشپزی کردن|to cook
بازی کردن|to play
تمرین کردن|to practise
مطالعه کردن|to study, to read
درس خواندن|to study
ورزش کردن|to exercise
استراحت کردن|to rest
خواهش کردن|to ask, to request
تشکر کردن|to thank
عذرخواهی کردن|to apologise
دعوت کردن|to invite
آماده کردن|to prepare
آماده شدن|to get ready
عصبانی شدن|to get angry
ناراحت شدن|to get upset
خسته شدن|to get tired
بیدار شدن|to wake up
بیدار کردن|to wake (someone) up
سوار شدن|to get on, to board
پیاده شدن|to get off
وارد شدن|to enter
خارج شدن|to go out, to leave
گم شدن|to get lost
گم کردن|to lose
متوجه شدن|to notice, to realise
عاشق شدن|to fall in love
بزرگ شدن|to grow up
آشنا شدن|to get to know, to meet
مریض شدن|to get sick
دیر شدن|to get late
موفق شدن|to succeed
برنده شدن|to win
باعث شدن|to cause
مجبور شدن|to be forced to
مجبور کردن|to force
خوش آمدن|to like, to please
به دنیا آمدن|to be born
به نظر رسیدن|to seem
به دست آوردن|to get, to obtain
به یاد آوردن|to remember
از بین رفتن|to disappear, to be destroyed
از بین بردن|to destroy
خواب دیدن|to dream
آسیب دیدن|to get hurt
خبر داشتن|to know, to be aware
نیاز داشتن|to need
احتیاج داشتن|to need
وجود داشتن|to exist
قرار داشتن|to be located
قرار گذاشتن|to arrange to meet
قرار دادن|to put, to place
قرار گرفتن|to be placed, to be located
اعتماد کردن|to trust
عادت کردن|to get used to
دقت کردن|to pay attention
احساس کردن|to feel
حس کردن|to feel, to sense
تعجب کردن|to be surprised
شک کردن|to doubt
دعوا کردن|to quarrel, to fight
شوخی کردن|to joke
تمیز کردن|to clean
خاموش کردن|to turn off
روشن کردن|to turn on, to light
خاموش شدن|to go out, to turn off
پرداخت کردن|to pay
خرج کردن|to spend
پس دادن|to give back
پس گرفتن|to take back
ترک کردن|to leave, to quit
فرار کردن|to run away, to escape
دنبال کردن|to follow
پنهان کردن|to hide
امتحان کردن|to try, to test
سعی کردن|to try
تلاش کردن|to try, to strive
جمع کردن|to collect, to gather
عبور کردن|to cross, to pass
رشد کردن|to grow
گرم کردن|to warm up, to heat
سرد شدن|to get cold
تعریف کردن|to tell (a story); to praise
دروغ گفتن|to lie, to tell a lie
تبریک گفتن|to congratulate
خداحافظی کردن|to say goodbye
سلام کردن|to say hello, to greet
غذا خوردن|to eat (a meal)
صبحانه خوردن|to have breakfast
زمین خوردن|to fall down
شکست خوردن|to be defeated, to fail
سرما خوردن|to catch a cold
قسم خوردن|to swear
تکان دادن|to shake, to wave
تکان خوردن|to move, to budge
طول کشیدن|to take (time), to last
سیگار کشیدن|to smoke
خجالت کشیدن|to be embarrassed
دراز کشیدن|to lie down
نفس کشیدن|to breathe
جا گذاشتن|to leave behind
کنار گذاشتن|to put aside
احترام گذاشتن|to respect
تنها گذاشتن|to leave alone
دست برداشتن|to give up, to stop
راه رفتن|to walk
راه افتادن|to set off
اتفاق افتادن|to happen
دوست شدن|to become friends
نگه داشتن|to keep, to hold
سوال کردن|to ask (a question)
مراقبت کردن|to take care
مواظب بودن|to be careful
مراقب بودن|to be careful
آرزو کردن|to wish
حمام کردن|to bathe
مسواک زدن|to brush one's teeth
شنا کردن|to swim
پارک کردن|to park
فوت کردن|to pass away
درک کردن|to understand
حل کردن|to solve
حفظ کردن|to memorise; to preserve
اشتباه کردن|to make a mistake
تکرار کردن|to repeat
تعمیر کردن|to repair
ملاقات کردن|to meet, to visit
دیدن کردن|to visit
اضافه کردن|to add
کم کردن|to reduce
پر کردن|to fill
خالی کردن|to empty
پاک کردن|to wipe, to clean
حساب کردن|to count; to settle up
امضا کردن|to sign
تحمل کردن|to bear, to put up with
خیال کردن|to imagine, to suppose
بحث کردن|to argue, to discuss
قطع کردن|to cut off; to hang up
دریافت کردن|to receive
ترجمه کردن|to translate
آرام شدن|to calm down
دیوانه شدن|to go mad
ساکت شدن|to go quiet
نزدیک شدن|to approach
دور شدن|to move away
جدا شدن|to separate, to split up
پیر شدن|to grow old
چاق شدن|to put on weight
لاغر شدن|to lose weight
خراب شدن|to break down
خراب کردن|to ruin, to break
پیشنهاد کردن|to suggest
پیشنهاد دادن|to suggest, to offer
دستور دادن|to order
گزارش دادن|to report
هدیه دادن|to give a present
رای دادن|to vote
درس دادن|to teach
یاد داشتن|to know how to
رخ دادن|to happen, to occur
لو رفتن|to be revealed, to leak out
لو دادن|to give away, to betray
ترجیح دادن|to prefer
وانمود کردن|to pretend
نادیده گرفتن|to ignore
تصور کردن|to imagine
معرفی کردن|to introduce
ادعا کردن|to claim
توهین کردن|to insult
ربط داشتن|to be related, to have to do with
دسترسی داشتن|to have access
قایم شدن|to hide (oneself)
قایم کردن|to hide (something)
جرات کردن|to dare
تشویق کردن|to encourage
رزرو کردن|to book, to reserve
فرا گرفتن|to learn; to surround
در آوردن|to take out; to earn
پی بردن|to realise, to find out
اعلام کردن|to announce
آغاز شدن|to begin (intr.)
آغاز کردن|to begin
اعتراض کردن|to protest, to object
ول کردن|to let go, to leave
پخش شدن|to spread; to be broadcast
کشف کردن|to discover
شکست دادن|to defeat
بستگی داشتن|to depend
تعلق داشتن|to belong
تقسیم کردن|to divide, to share
محدود کردن|to limit
ثابت کردن|to prove
حمله کردن|to attack
تولید کردن|to produce
ایجاد کردن|to create
ایجاد شدن|to be created, to arise
تبدیل شدن|to turn into, to become
تبدیل کردن|to turn into, to convert
اشاره کردن|to point, to refer
بررسی کردن|to examine, to check
اجرا کردن|to perform, to carry out
ثبت کردن|to register, to record
برگزار شدن|to be held
منتشر شدن|to be published
منتشر کردن|to publish
متولد شدن|to be born
دستگیر شدن|to be arrested
دستگیر کردن|to arrest
نجات دادن|to save, to rescue
شرکت کردن|to take part
انتخاب کردن|to choose
کنترل کردن|to control
عمل کردن|to act; to operate
فرق داشتن|to differ
فرق کردن|to differ, to be different
علاقه داشتن|to be interested
اهمیت دادن|to care about
اهمیت داشتن|to matter
توجه کردن|to pay attention
انتظار داشتن|to expect
جمع شدن|to gather
بیمار شدن|to fall ill
"""
LIGHT_VERBS = {}          # folded compound -> gloss
LV_INDEX = {}             # folded light verb -> {folded noun: [(folded prefix or "", compound)]}
for _line in LIGHT_VERBS_SRC.strip().splitlines():
    _phrase, _gloss = _line.split("|")
    _parts = [fold(p) for p in _phrase.split()]
    _comp = " ".join(_parts)
    LIGHT_VERBS[_comp] = _gloss
    _pre = _parts[0] if len(_parts) == 3 else ""
    LV_INDEX.setdefault(_parts[-1], {}).setdefault(_parts[-2], []).append((_pre, _comp))

# ---- colloquial subtitle spellings -> written forms (folded). None drops a
# detached fragment (ها, می, ام) that the subtitle tokeniser split off ------------
COLLOQUIAL = {
    "رو": "را", "اون": "آن", "یه": "یک", "چی": "چه", "اگه": "اگر", "داره": "دارد", "دیگه": "دیگر",
    "کنه": "کند", "اونا": "آنها", "منو": "من", "میشه": "میشود", "بهت": "به", "بهم": "به", "بهش": "به",
    "خونه": "خانه", "واسه": "برای", "خوبه": "خوب", "چیه": "چه", "بشه": "بشود", "نداره": "ندارد",
    "منم": "من", "میخوام": "میخواهم", "میاد": "میآید", "میدونی": "میدانی", "میخوای": "میخواهی",
    "بگم": "بگویم", "اونو": "آن", "اینه": "این", "برم": "بروم", "دارن": "دارند", "اینو": "این",
    "دونم": "دانم", "خوام": "خواهم", "تموم": "تمام", "کنن": "کنند", "میدونم": "میدانم", "همون": "همان",
    "تونم": "توانم", "ازش": "از", "ممکنه": "ممکن", "مگه": "مگر", "برات": "برای", "باهاش": "با",
    "بذار": "بگذار", "بزار": "بگذار", "ازت": "از", "میتونم": "میتوانم", "میتونی": "میتوانی",
    "کجاست": "کجا", "نمیدونم": "نمیدانم", "اونها": "آنها", "بعدش": "بعد", "میگم": "میگویم",
    "برام": "برای", "آره": "بله", "قراره": "قرار", "کنین": "کنید", "کارو": "کار", "دونی": "دانی",
    "اومده": "آمده", "خوای": "خواهی", "بهشون": "به", "میتونه": "میتواند", "اینا": "اینها",
    "کدوم": "کدام", "میکنن": "میکنند", "میگه": "میگوید", "ازم": "از", "بهتون": "به", "عالیه": "عالی",
    "اونم": "آن", "باشن": "باشند", "میتونیم": "میتوانیم", "هستش": "هست", "توئه": "تو", "بهمون": "به",
    "بتونم": "بتوانم", "اومدی": "آمدی", "دیوونه": "دیوانه", "بازم": "باز", "میریم": "میرویم",
    "میگن": "میگویند", "پیداش": "پیدا", "دارین": "دارید", "بزنه": "بزند", "وایسا": "بایست",
    "دختره": "دختر", "میام": "میآیم", "چیزیه": "چیزی", "تکون": "تکان", "هنوزم": "هنوز", "باهام": "با",
    "میشی": "میشوی", "میشن": "میشوند", "بمون": "بمان", "بیار": "بیاور", "معلومه": "معلوم",
    "نباشه": "نباشد", "خودتون": "خودتان", "بیای": "بیایی", "خانوم": "خانم", "تورو": "تو",
    "خودتو": "خود", "خودشون": "خودشان", "بخوای": "بخواهی", "بگیره": "بگیرد", "بتونه": "بتواند",
    "اونوقت": "آنوقت", "بیاین": "بیایید", "دونه": "داند", "بکشه": "بکشد", "بگه": "بگوید", "مارو": "ما",
    "اومدن": "آمدن", "سخته": "سخت", "باشین": "باشید", "بشیم": "بشویم", "داداش": "برادر",
    "تمومش": "تمام", "چیزا": "چیزها", "براتون": "برای", "بدونی": "بدانی", "چیزایی": "چیزهایی",
    "برین": "بروید", "اونجاست": "آنجا", "همونطور": "همانطور", "برسه": "برسد", "وقته": "وقت",
    "میخوایم": "میخواهیم", "هستین": "هستید", "بخواد": "بخواهد", "همشون": "همه", "کردین": "کردید",
    "میدن": "میدهند", "اونه": "آن", "ازشون": "از", "واست": "برای", "تمومه": "تمام", "میدیم": "میدهیم",
    "خودمو": "خودم", "باشه": "باشد", "خب": "خوب", "میکنه": "میکند", "درسته": "درست", "بدم": "بدهم",
    "بریم": "برویم", "هستن": "هستند", "اونجا": "آنجا", "عزیزم": "عزیز", "بخاطر": "خاطر", "کنی": "کنی",
    "توی": "در", "مامان": "مادر", "بابا": "پدر", "یکی": "یکی", "دیگهای": "دیگری", "اینجوری": "اینطور",
    "اونجوری": "آنطور", "چجوری": "چطور", "چطوری": "چطور", "میری": "میروی", "میره": "میرود",
    "بره": "برود", "بری": "بروی", "برید": "بروید", "میگی": "میگویی", "بگی": "بگویی", "بگین": "بگویید",
    "میکنی": "میکنی", "نمیخوام": "نمیخواهم", "نمیتونم": "نمیتوانم", "نمیتونی": "نمیتوانی",
    "میتونین": "میتوانید", "میتونید": "میتوانید", "بتونی": "بتوانی", "میخواد": "میخواهد",
    "نمیخواد": "نمیخواهد", "میخواین": "میخواهید", "میخواید": "میخواهید", "بخوام": "بخواهم",
    "میدونه": "میداند", "میدونیم": "میدانیم", "میدونید": "میدانید", "نمیدونی": "نمیدانی",
    "نمیدونه": "نمیداند", "بدونم": "بدانم", "بدونه": "بداند", "بیاد": "بیاید", "نمیاد": "نمیآید",
    "بیام": "بیایم", "میان": "میآیند", "اومدم": "آمدم", "اومد": "آمد", "اومدیم": "آمدیم",
    "نیومد": "نیامد", "نیومده": "نیامده", "بمونم": "بمانم", "بمونه": "بماند", "میمونم": "میمانم",
    "میمونه": "میماند", "نشون": "نشان", "بده": "بده", "بدین": "بدهید", "میده": "میدهد", "میدی": "میدهی",
    "میدم": "میدهم", "بشی": "بشوی", "شه": "شود", "نشه": "نشود", "میشم": "میشوم", "بشم": "بشوم",
    "میشیم": "میشویم", "میشید": "میشوید", "دادن": "دادن", "داری": "داری", "دارین": "دارید",
    "نداری": "نداری", "نداریم": "نداریم", "ندارن": "ندارند", "داشتن": "داشتن", "بکنه": "بکند",
    "بکنم": "بکنم", "بکنی": "بکنی", "بکنیم": "بکنیم", "بکن": "بکن", "میزنه": "میزند", "بزنم": "بزنم",
    "بگیرم": "بگیرم", "میگیره": "میگیرد", "بخوره": "بخورد", "میخوره": "میخورد", "بخونم": "بخوانم",
    "میخونه": "میخواند", "بشینم": "بنشینم", "بشین": "بنشین", "بشینید": "بنشینید", "بپرسم": "بپرسم",
    "اینطوری": "اینطور", "همینطوری": "همینطور", "همینجوری": "همینطور", "اینجاست": "اینجا",
    "کجایی": "کجا", "چیکار": "چکار", "چکار": "چکار", "هیچکی": "هیچکس", "هیچکس": "هیچکس",
    "هرکی": "هرکس", "کسی": "کسی", "کیه": "کی", "همش": "همه", "همهی": "همه", "همه": "همه",
    "زودباش": "زود", "بیخیال": "بیخیال", "آخه": "آخر", "دیگهای": "دیگری", "مهمه": "مهم",
    "حالت": "حال", "حالم": "حال", "خیلیم": "خیلی", "شماها": "شما", "اینجوریه": "اینطور",
    "اونطوری": "آنطور", "اونطور": "آنطور", "اینکه": "اینکه", "بچهها": "بچهها", "تو": "تو",
    "یکم": "کم", "اره": "بله", "بلی": "بله", "ماست": "ما", "کجاست": "کجا", "پائین": "پایین",
    "بدست": "دست",
    "ها": None, "های": None, "هایی": None, "هام": None, "هات": None, "هاش": None, "ی": None, "ای": None,
    "ام": None, "مون": None, "تون": None, "شون": None, "می": None, "نمی": None, "ه": None, "ست": None,
    "تر": None, "ترین": None, "اید": None, "اند": None, "ایم": None, "اش": None, "ات": None,
}
# surfaces that are words of their own, not host + clitic/indefinite -ی
KEEP_SURFACE = {"کمی", "گاهی", "یکی", "مردم", "کسی", "چیزی", "جایی", "بعضی", "خیلی", "همدیگر",
                "کدام", "هیچکس", "خودش", "آنجا", "اینجا", "بیشتر", "کمتر", "بهتر", "بدتر", "بهترین"}
# stock Tatoeba names read as common words by the tagger (تام "complete", جان "life")
NAMES = {"تام", "مری", "مریم", "جان", "جک", "کن", "بیل", "جین", "مایک", "تونی", "باب", "آلیس", "لوسی",
         "جیم", "سامی", "لیلا", "بیل", "باب", "جین", "لیلی", "تامس", "ماری", "جانی", "یانی", "زیاد"}
NAME_EN = {"جان": "John", "کن": "Ken", "زیاد": "Ziad", "لیلا": "Layla", "لیلی": "Lily", "مریم": "Maryam"}
PROFANE = ("کیر", "کون", "جنده", "گاییدن", "گایید", "بگایی", "حرومزاده", "حرامزاده", "کسکش", "جاکش", "لاشی",
           "کصکش", "کسخل", "مادرجنده", "پفیوز", "کثافت", "لعنتی", "لعنت")


class Persian(LanguageSpec):
    code = "fa"
    name_en = "Persian"
    pack_name = "Persian (A1–B1)"
    tts = "fa-IR"
    stt = "fa-IR"
    tatoeba_code = "pes"
    spacy_model = None
    tagger = "stanza"
    stanza_lang = "fa"
    tagger_attribution = {
        "source": "Stanza (Apache-2.0) with its Persian default model, trained on UD Persian-Seraji",
        "licence": "Apache-2.0 (code); CC BY-SA 4.0 (UD Persian-Seraji model data)",
        "note": "Used at build time only; the pack ships no model files.",
    }
    untranslated_rows = True
    extra_corpus_files = ("tools/generated_sentences.tsv",)

    subtitles_file = "fa_full.txt"
    kaikki_file = "kaikki_fa.jsonl.gz"
    sentences_file = "pes_sentences_detailed.tsv.bz2"
    links_file = "pes-eng_links.tsv.bz2"
    sources = {
        "fa_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/fa/fa_full.txt",
        "kaikki_fa.jsonl.gz": "https://kaikki.org/dictionary/Persian/kaikki.org-dictionary-Persian.jsonl.gz",
        "pes_sentences_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/pes/pes_sentences_detailed.tsv.bz2",
        "pes-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/pes/pes-eng_links.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t25", "lex": "l3"}

    typing = None
    show_pron = True
    target_len = {"A1": 5, "A2": 6, "B1": 7}
    min_len = {"A1": 3, "A2": 4, "B1": 5}
    max_len = 14

    word_re = re.compile(f"[{LET}\u064b-\u065f\u0670\u200c]+")
    lex_word_re = re.compile(f"^[{LET}]+(?: [{LET}]+){{0,2}}$")
    sub_token_re = re.compile("^[\u064B-\u065F\u0670\u200c]*[" + LET + "][" + LET + "\u064B-\u065F\u0670\u200c]*$")
    form_target_re = re.compile(f"\\bof ([{LET}\u200c]+)")
    fem_of_re = re.compile(r"(?!)")
    group_kpos = dict(DEFAULT_GROUP_KPOS, **{
        "ADV": ["adv", "adj", "conj", "prep", "noun"],
        "ADJ": ["adj", "det", "num", "adv"],
        "DET": ["det", "pron", "adj", "num"],
        "PRON": ["pron", "det", "adv"],
        "ADP": ["prep", "postp", "adv", "conj"],
        "PART": ["particle", "adv", "intj"],
    })
    numeral_verb_rule = False
    morph_keep = ("Number", "Person", "Tense", "Mood", "VerbForm", "Polarity", "Clitic")
    caps_mark_names = False            # no letter case in Persian
    caps_proper_pool = False
    function_verbs = set()

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS + SEASONS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS] + [(w, "INTJ") for w in GREETINGS] +
                     [(w, "PRON") for w in PRONOUNS] + [(w, "DET") for w in DEMONSTR] + QUESTION +
                     [(w, "ADP") for w in PREPS] + CONJS +
                     [(c, "VERB") for c in ("کار کردن", "زندگی کردن", "دوست داشتن", "صحبت کردن", "حرف زدن")] +
                     [("یعنی", "CONJ"), ("ایشان", "PRON"), (PLEASE_PHRASE, "INTJ")])
    allowed_num = set(NUMBERS) | {"میلیون", "اول", "دوم", "سوم", "نیم"}
    fixed_gloss = {
        **{(c, "VERB"): g for c, g in LIGHT_VERBS.items()},
        ("متشکرم", "INTJ"): "thank you", ("ممنون", "INTJ"): "thanks, thank you",
        ("یعنی", "CONJ"): "that is, I mean", ("ایشان", "PRON"): "he, she (polite); they",
        (PLEASE_PHRASE, "INTJ"): "you're welcome; please (go ahead)",
        ("ببخشید", "INTJ"): "excuse me, sorry", ("خداحافظ", "INTJ"): "goodbye", ("سلام", "INTJ"): "hello, hi",
        ("بله", "INTJ"): "yes", ("وی", "PRON"): "he, she (formal)", ("نه", "INTJ"): "no", ("لطفا", "INTJ"): "please",
        ("نه", "NUM"): "nine", ("سی", "NUM"): "thirty", ("سه", "NUM"): "three", ("صد", "NUM"): "hundred",
        ("هزار", "NUM"): "thousand", ("یک", "NUM"): "one; a, an",
        ("شنبه", "NOUN"): "Saturday", ("یکشنبه", "NOUN"): "Sunday", ("دوشنبه", "NOUN"): "Monday",
        ("سهشنبه", "NOUN"): "Tuesday", ("چهارشنبه", "NOUN"): "Wednesday", ("پنجشنبه", "NOUN"): "Thursday",
        ("جمعه", "NOUN"): "Friday",
        ("فروردین", "NOUN"): "Farvardin (1st Iranian month, Mar–Apr)",
        ("اردیبهشت", "NOUN"): "Ordibehesht (2nd month, Apr–May)", ("خرداد", "NOUN"): "Khordad (3rd month, May–Jun)",
        ("تیر", "NOUN"): "Tir (4th month, Jun–Jul); arrow", ("مرداد", "NOUN"): "Mordad (5th month, Jul–Aug)",
        ("شهریور", "NOUN"): "Shahrivar (6th month, Aug–Sep)", ("مهر", "NOUN"): "Mehr (7th month, Sep–Oct); kindness",
        ("آبان", "NOUN"): "Aban (8th month, Oct–Nov)", ("آذر", "NOUN"): "Azar (9th month, Nov–Dec)",
        ("دی", "NOUN"): "Dey (10th month, Dec–Jan)", ("بهمن", "NOUN"): "Bahman (11th month, Jan–Feb)",
        ("اسفند", "NOUN"): "Esfand (12th month, Feb–Mar)",
    }
    # frequent words the Persian Wiktionary extract has no entry (or only a
    # definitional one) for: glossed by hand (fixed_gloss path, same POS as the corpus)
    fixed_gloss.update({
        ("را", "ADP"): "(direct-object marker)", ("اینکه", "CONJ"): "that (the fact that)",
        ("آنکه", "CONJ"): "(the one) who; although", ("آخرین", "ADJ"): "last, latest",
        ("همینطور", "ADV"): "likewise, also; like this", ("همانطور", "ADV"): "just as, in the same way",
        ("حداقل", "ADV"): "at least", ("دقیقا", "ADV"): "exactly", ("شرایط", "NOUN"): "conditions, circumstances",
        ("معرفی", "NOUN"): "introduction", ("متاسفانه", "ADV"): "unfortunately", ("تصور", "NOUN"): "imagination, idea",
        ("معنا", "NOUN"): "meaning", ("قطعا", "ADV"): "certainly, definitely", ("زودی", "NOUN"): "(به زودی) soon",
        ("تمامی", "DET"): "all, the whole of", ("همگی", "PRON"): "all (of us/them), everybody",
        ("توانایی", "NOUN"): "ability", ("ادعا", "NOUN"): "claim", ("ترجیح", "NOUN"): "preference",
        ("عدالت", "NOUN"): "justice", ("قبلی", "ADJ"): "previous", ("اولیه", "ADJ"): "initial, primary",
        ("بهتر", "ADJ"): "better; (بهترین) best", ("احمقانه", "ADJ"): "stupid, silly", ("سختی", "NOUN"): "difficulty, hardship",
        ("مخصوصا", "ADV"): "especially", ("آنان", "PRON"): "they (formal)", ("بسیاری", "DET"): "many, a lot of",
        ("متنفر", "ADJ"): "hating, disgusted (از ... متنفرم: I hate ...)", ("زیرا", "CONJ"): "because",
        ("مطمئنا", "ADV"): "surely, certainly", ("جرات", "NOUN"): "courage, nerve", ("نزد", "ADP"): "to, at, with (someone)",
        ("فوری", "ADJ"): "urgent, immediate", ("تفکر", "NOUN"): "thinking, thought", ("شایسته", "ADJ"): "worthy, deserving",
        ("یکسان", "ADJ"): "identical, the same", ("فورا", "ADV"): "immediately", ("مقداری", "DET"): "some, a certain amount of",
        ("دکمه", "NOUN"): "button", ("صف", "NOUN"): "queue, line", ("توهین", "NOUN"): "insult", ("تغذیه", "NOUN"): "nutrition",
        ("جسم", "NOUN"): "body; object", ("غذایی", "ADJ"): "food (adj.), dietary", ("هزاران", "DET"): "thousands of",
        ("چندتا", "DET"): "a few; how many", ("کاش", "ADV"): "if only, I wish", ("گرسنه", "ADJ"): "hungry",
        ("فوقالعاده", "ADJ"): "extraordinary, great", ("رئیسجمهور", "NOUN"): "president",
        ("وانمود", "NOUN"): "pretence", ("ربط", "NOUN"): "connection, relevance", ("دسترسی", "NOUN"): "access",
        ("تشویق", "NOUN"): "encouragement", ("رزرو", "NOUN"): "booking, reservation", ("فایل", "NOUN"): "file",
        ("سختی", "NOUN"): "difficulty, hardship", ("انتها", "NOUN"): "end", ("فروش", "NOUN"): "sale, selling",
        ("پرداخت", "NOUN"): "payment", ("خوشحالی", "NOUN"): "happiness", ("ناراحتی", "NOUN"): "sadness, upset",
        ("صادقانه", "ADV"): "honestly", ("ناگهانی", "ADJ"): "sudden", ("همیشگی", "ADJ"): "permanent, everlasting",
    })
    closed_surfaces = {"اینکه": ("اینکه", "CONJ"), "آنکه": ("آنکه", "CONJ"), "بله": ("بله", "INTJ"), "آره": ("بله", "INTJ"), "گاهی": ("گاهی", "ADV"), "وی": ("وی", "PRON"), "ببخشید": ("ببخشید", "INTJ"), "متشکرم": ("متشکرم", "INTJ"),
                       "خداحافظ": ("خداحافظ", "INTJ"), "یعنی": ("یعنی", "CONJ"), "ایشان": ("ایشان", "PRON"), "ممنونم": ("ممنون", "INTJ"), "ممنون": ("ممنون", "INTJ"),
                       "لطفا": ("لطفا", "INTJ")}
    # pronouns/conjunctions Seraji tags NOUN are still function words; در is
    # left to the tagger (its ADP majority) so the noun در "door" stays a content word
    function_lemmas = (set(FUNCTION) - {"در"}) | {"همه", "چیزی", "اینکه", "وقتی", "کسی", "انگار", "مگر", "هیچکس",
                                                 "آنچه", "متعلق", "هرکس", "آنکه", "هیچکدام"}
    # (lemma, group) keys that are not learner words, or link elsewhere:
    # subtitle fragments split off at a ZWNJ (تر, اس, دار, ساز, پی, تی), a
    # colloquial pronoun (توش), variant spellings/forms of a pack word
    drop_keys = {("بلی", "ADV"): ("بله", "INTJ"), ("بلی", "INTJ"): ("بله", "INTJ"), ("اره", "NOUN"): ("بله", "INTJ"),
                 ("آره", "INTJ"): ("بله", "INTJ"), ("هم", "PRON"): ("هم", "ADV"), ("روی", "NOUN"): ("روی", "ADP"),
                 ("پیش", "NOUN"): ("پیش", "ADP"), ("پائین", "NOUN"): ("پایین", "NOUN"),
                 ("دور", "NOUN"): ("دور", "ADJ"), ("یکم", "ADJ"): None, ("یکم", "NUM"): None,
                 ("تر", "ADJ"): None, ("اس", "NOUN"): None, ("دار", "NOUN"): None, ("ساز", "NOUN"): None,
                 ("پی", "NOUN"): None, ("پی", "ADP"): None, ("تی", "NOUN"): None, ("توش", "ADJ"): None,
                 ("توش", "NOUN"): None, ("کندن", "VERB"): None, ("رو", "NOUN"): None,
                 ("پائین", "ADV"): ("پایین", "ADV"), ("مگر", "ADP"): ("مگر", "CONJ"), ("بیش", "ADJ"): ("بیشتر", "ADJ"),
                 ("کش", "NOUN"): None, ("سو", "NOUN"): None, ("دارا", "ADJ"): None, ("بدست", "NOUN"): None,
                 ("ماست", "NOUN"): None, ("کرد", "NOUN"): ("کردن", "VERB"), ("دان", "NOUN"): None,
                 ("گر", "NOUN"): None, ("گر", "ADJ"): None, ("مندن", "VERB"): None, ("ور", "NOUN"): None,
                 ("ور", "ADJ"): None, ("لا", "NOUN"): None, ("درو", "NOUN"): None, ("ر", "NOUN"): None,
                 ("بدو", "NOUN"): None, ("نی", "NOUN"): None, ("بک", "NOUN"): None, ("لاک", "NOUN"): None,
                 ("سوز", "NOUN"): None, ("سوء", "NOUN"): None, ("زاد", "NOUN"): None, ("زاده", "NOUN"): None,
                 ("زیاده", "ADJ"): None, ("دارا", "NOUN"): None,
                 ("برابر", "NOUN"): ("برابر", "ADJ"), ("همراه", "ADJ"): ("همراه", "ADP"),
                 ("احمق", "NOUN"): ("احمق", "ADJ"), ("دنبال", "ADP"): ("دنبال", "NOUN"), ("گیری", "NOUN"): None,
                 ("ها", "NOUN"): None, ("برمی", "NOUN"): None, ("نا", "NOUN"): None, ("نا", "ADJ"): None,
                 # participles / fragments / prefix-stripped verb lemmas (در حالی که, برانگیختن -> انگیختن)
                 ("حالی", "ADV"): None, ("تره", "NOUN"): None, ("بردار", "NOUN"): ("برداشتن", "VERB"),
                 ("گذار", "NOUN"): None, ("زمینی", "ADJ"): None, ("رستن", "VERB"): None, ("دریدن", "VERB"): None,
                 ("جستن", "VERB"): None, ("افتاده", "NOUN"): ("افتادن", "VERB"), ("دیده", "NOUN"): ("دیدن", "VERB"),
                 ("ون", "NOUN"): None, ("آدمی", "NOUN"): ("آدم", "NOUN"), ("فارغ", "ADJ"): None,
                 ("مسیح", "NOUN"): None, ("انگیختن", "VERB"): None, ("تنیدن", "VERB"): None, ("آمیختن", "VERB"): None,
                 ("شنفتن", "VERB"): ("شنیدن", "VERB"), ("مک", "NOUN"): None, ("لی", "NOUN"): None, ("خواسته", "ADJ"): None, ("هو", "NOUN"): None, ("وب", "NOUN"): None, ("اسباب", "NOUN"): None, ("بیشترین", "ADJ"): None, ("فوق", "NOUN"): None, ("کوچولو", "NOUN"): None,
                 ("شبه", "NOUN"): None}
    min_corpus_tokens = 3     # subtitle fragments (ال, ری), names, web-only words (زیرنویس, اوکی)
    profanity = set(PROFANE) | {"گه", "ریدن"}
    bad_text_re = re.compile("(?<![" + LET + "])(?:" + "|".join(PROFANE) + ")|" + "|".join(map(re.escape, BAD_SENTENCES)), re.I)
    # removed at every level: rape, sexual abuse, child abuse, suicide, self-harm
    drop_all_levels = drop_all_re(re.compile(
        "(?<![" + LET + "a-z])(?:تجاوز\\w*|آزار\\s*جنسی|کودک\u200c?آزاری|بچه\u200c?بازی|"
        "خودکشی|خودزنی|"
        "rape[ds]?|raping|rapist\\w*|molest\\w*|child abuse|sexual(?:ly)? abuse\\w*|paedophil\\w*|pedophil\\w*)"
        "(?![" + LET + "a-z])", re.I))
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)
    # A1/A2 tier: sexual content, threats/violence, dying/death wishes, weapons
    sensitive_re = re.compile(
        "(?<![" + LET + "a-z])(?:بمیر\\w*|می\u200c?میر\\w*|نمیر\\w*|مرده|مرگ\\w*|بکشمت|بکشیمت|بکشش|"
        "(?:ب|می\u200c?|ن)?کشت(?:ن|ند|م|یم|ید|ه)?|چاقو\\w*|کارد|شمشیر|گلوله|بمب|سلاح\\w*|شلیک|زخمی|جسد|"
        "die[ds]?|dying|death|weapons?|guns?|pistols?|rifles?|knife|knives|shot|bomb\\w*|serial killer|corpse|"
        "کشتن|سکس\\w*|جنسی|تجاوز\\s*جنسی|برهنه|لخت|خودکشی|قتل|قاتل|بکشمت|میکشمت|میکشیم|"
        "کشتمش|کشتمت|بکشید|بکشند|کشته\\s*شد|اعدام|تیراندازی|اسلحه|تفنگ|هفت\\s*تیر|چاقو\\s*زد|خون\\s*ریخت|"
        # illicit drugs and abuse (A1/A2 tier)
        "موادّ?\\s*مخدّ?ر|مخدّ?ر\\w*|هروئین|کوکائین|تریاک|ماری\u200c?جوانا|سوء\\s*استفاده|آزار\\w*|"
        "(?:illicit|illegal) drugs?|drug (?:dealer|addict|abuse|traffick\\w*)s?|narcotics?|cocaine|heroin|"
        "marijuana|cannabis|overdose|abus(?:e|ed|es|ing|er|ers|ive)|"
        + SENSITIVE_EN + ")(?![" + LET + "a-z])", re.I)

    report_title = "Persian A1-B1 pack (corpus-tagged)"
    forced_description = ("days, Iranian months, seasons, numbers 0-20 + tens + صد/هزار, colours, greetings, "
                          "pronouns, question words, core prepositions/conjunctions, five light verbs, A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000/million/ordinals 1-3"

    # ---- spelling / frequency --------------------------------------------------
    def fold(self, s):
        return fold(s)

    def subtitle_surface(self, w):
        if w in COLLOQUIAL:
            return COLLOQUIAL[w]
        return w

    def extra_wordfreq(self, raw):
        """wordfreq's Persian list mixes in colloquial spellings (رو, اون,
        میخوام): move their weight to the written form, as for the subtitles."""
        for w in sorted(k for k in raw if k in COLLOQUIAL):
            c = raw.pop(w)
            tgt = COLLOQUIAL[w]
            if tgt:
                raw[tgt] = raw.get(tgt, 0) + c

    def is_verb_lemma(self, w):
        return w.endswith(("تن", "دن")) or w == "باید"

    def is_profane(self, w):
        return w in self.profanity

    # ---- tagging (Stanza) ---------------------------------------------------------
    def tagger_desc(self):
        import stanza
        return f"Stanza {stanza.__version__}, fa default package (UD Persian-Seraji)"

    def tag_text(self, text):
        """Tagger input: Persian yeh/kaf, and detached affixes joined with ZWNJ
        (می خواهم -> می\u200cخواهم, کتاب ها -> کتاب\u200cها, رفته اند -> رفته\u200cاند);
        Stanza mis-tags a detached می as a noun."""
        t = display_norm(text)
        # به fused onto a noun: بدست آوردن, بخاطر (the compound / به خاطر)
        t = re.sub(f"(?<![{LET}\u200c])ب(دست|خاطر|سوی|جای|عنوان|طور|نظر|وسیله|جز|زودی)(?![{LET}])", "به \\1", t)
        t = re.sub(f"(?<![{LET}\u200c])(بر|در)(اساس|حال|واقع|مورد)(?![{LET}])", "\\1 \\2", t)
        t = re.sub(f"(?<![{LET}\u200c])(فوق|رئیس) (العاده|جمهور)(?![{LET}])", "\\1" + ZWNJ + "\\2", t)
        t = re.sub(f"(?<![{LET}\u200c])((?:بر|در|باز|فرو)?ن?می) (?=[{LET}])", "\\1" + ZWNJ, t)
        t = re.sub(f"(?<=[{LET}]) (ها|های|هایی|هایم|هایت|هایش|هایمان|هایتان|هایشان|تر|ترین)(?![{LET}])",
                   ZWNJ + "\\1", t)
        t = re.sub(f"(?<=[{LET}]ه) (ام|ای|ایم|اید|اند)(?![{LET}])", ZWNJ + "\\1", t)
        # detached derivational suffixes (بازی گر, علاقه مند, غوطه ور): one word
        t = re.sub(f"(?<=[{LET}]) (گر|گری|ور|وری|مند|مندی|مندان|مندند|مندم|مندید|وار|ناک|ستان|زار)(?![{LET}])",
                   ZWNJ + "\\1", t)
        return t

    span_joiners = " "          # tag_text joins "می روم", "کتاب ها" with ZWNJ; fold drops it

    def span_fold(self, s):
        """Passages span alignment: fix_token's surfaces are fold()ed (applied
        per word, so پائین = پایین and final ابتداء = ابتدا)."""
        return fold(s)

    # ---- reading passages only (never run by `build`) -----------------------
    X_POS = (("noun", "NOUN"), ("adj", "ADJ"), ("adv", "ADV"), ("pron", "PRON"), ("prep", "ADP"))

    def passage_retag(self, toks):
        """Seraji leaves some plain words as X, mostly the parts of a set
        phrase ("فردا شب", "به سر کار"): X is skipped, so they would be
        neither counted nor linked. A letters-only X token gets its
        dictionary class (noun, adj, adv, pron, prep; first that has a lemma
        entry) and goes through fix_token again (UPOS_FIX: فردا, بعد). A verb
        whose lemma is still no infinitive after fix_token ("از او چه خواست؟":
        Stanza lemma خوا) is re-read from its surface alone (خواستن); a noun
        split as host + copula (or with a lemma the dictionary lacks) whose
        surface is a past stem is that verb. An ordinal the pack lacks (سیزدهم)
        is a numeral."""
        info, infs, pack = self._info(), self._verbs()[0], self._passage_pack()
        for k, t in enumerate(toks):
            if t[2] == "X" and t[0] and all(ch.isalpha() or ch == ZWNJ for ch in t[0]):
                rows = info.get(fold(t[0]), [])
                for kpos, up in self.X_POS:
                    if any(r[1] == kpos and r[4] for r in rows):
                        toks[k] = self.fix_token([t[0], t[0], up, t[3]])
                        break
            elif t[2] == "NOUN" and fold(t[0]) + "ن" in infs and fold(t[0]) != t[1] and \
                    (not info.get(t[1]) or "Clitic=Yes" in t[3]):
                # a past-tense verb read as a noun + copula ("چه خواست؟": خوا "taste" + ست)
                t[1], t[2] = fold(t[0]) + "ن", "VERB"
            elif fold(t[0]) not in pack and any(fold(t[0]).endswith(e) and fold(t[0])[:-len(e)] in NUMBERS
                                                for e in ("مین", "م", "ام")):
                # an ordinal the pack does not teach (سیزدهم): a numeral, not counted
                t[1], t[2] = fold(t[0]), "NUM"
            elif t[2] in ("VERB", "AUX") and t[1] not in infs and t[1] != "باید":
                # Stanza's lemma was no past stem ("چه خواست؟" -> خوا): read the surface alone
                alt = self._formal_inf(self._verb_lemma(fold(t[0]), fold(t[0])))
                if alt in infs:
                    t[1] = alt
        # homographs the tagger reads by position; each needs its neighbours
        f = [fold(t[0] or "") for t in toks]
        for k, t in enumerate(toks):
            prev, nxt = (f[k - 1] if k else ""), (f[k + 1] if k + 1 < len(f) else "")
            if f[k] == "نه" and t[2] == "NUM" and not (
                    prev == "ساعت" or nxt in NINE_UNITS or (prev in ("از", "تا") and any(
                        j != k and (toks[j][2] == "NUM" or f[j] == "ساعت") for j in range(len(toks))))):
                # نه is "nine" only as a time, a range or before a bare unit
                # (ساعت نه, از نه تا پنج, نه سال, نه نفر); elsewhere "not": a
                # unit with ی is no count ("، نه هفته‌ای یک بار": not once a week)
                t[2] = "ADV"
            elif f[k] == "در" and t[2] == "ADP" and nxt in ("آن", "این") and \
                    (f[k + 2] if k + 2 < len(f) else "") == "را":
                # a preposition never heads an object: "در آن را ببندید" is its lid/door
                t[1], t[2] = "در", "NOUN"
            elif t[2] == "NOUN" and t[1] in infs and f[k] != t[1] and f[k].startswith(t[1]) and \
                    f[k][len(t[1]):] in ("ش", "م", "ت", "اش", "شان", "مان", "تان"):
                # an infinitive with a pronoun clitic ("درست کردنش": repairing it)
                # is the verb, so its compound (درست کردن) can form
                t[2] = "VERB"
        return toks

    def passage_post_resolve(self, toks, out):
        """fix_token makes بهتر "better", بیشتر "more", کمتر "less" words of
        their own (lemma بهتر, not به "to"); the resolver still reads بهتر as
        the comparative of به "good", which then falls back to the preposition
        به. A token whose tagger lemma is such a comparative keeps it
        (بهترین: بهتر). Then, against the pack's own lemmas: a light-verb
        compound the pack lacks splits into its parts, and a noun/adjective
        with indefinite/ezafe ی read as a non-pack derived word is its stem, and
        a preposition with a pronoun clitic (برایت) is the preposition, and a
        comparative kept whole (بزرگ‌ترها) is its adjective. A compound whose
        noun is the object of a bare preposition (بعد از غذا بخورید) splits,
        when its verb is finite (از اشتباه کردن, برای یاد گرفتن stay) and the
        preposition carries no clitic (برایش دست زدند stays)."""
        for i, t in enumerate(toks):
            r, lem = out[i], t[1]
            if r is None or r[1] not in ("ADJ", "ADV"):
                continue
            cand = lem[:-2] if lem.endswith("ترین") else lem
            if cand.endswith("تر") and cand[:-2] in ("به", "بیش", "کم") and r[0] in (lem, cand + "ین", cand[:-2]):
                out[i] = (cand, r[1])
        for i, t in enumerate(toks):
            r = out[i]
            if r and " " in r[0] and r[1] == "VERB" and t[2] not in ("VERB", "AUX") and \
                    (i == 0 or out[i - 1] != r) and i and toks[i - 1][2] == "ADP" and toks[i - 1][1] != "را" and \
                    fold(toks[i - 1][0]) == toks[i - 1][1] and not r[0].startswith(toks[i - 1][1] + " ") and \
                    any(out[j] == r and toks[j][2] in ("VERB", "AUX") and fold(toks[j][0]) != toks[j][1]
                        for j in range(i + 1, len(toks))):
                # the noun is a preposition's object ("بعد از غذا بخورید": take it
                # after food), not the light verb's (غذا خوردن); به دنیا آمدن keeps it
                for j in range(i, len(toks)):
                    if out[j] == r:
                        out[j] = (toks[j][1], "VERB" if toks[j][2] in ("VERB", "AUX") else toks[j][2])
        pack = self._passage_pack()
        for i, t in enumerate(toks):
            r, w = out[i], fold(t[0] or "")
            if r and r[1] == "NOUN" and t[2] == "NOUN" and t[1] == w and w != r[0] and \
                    "noun" in pack.get(w, ()) and "noun" in pack.get(r[0], ()) and \
                    any(w == r[0] + e for e in ("ی", "ای", "یی")) and "EnGloss=Yes" in (t[3] or ""):
                # the resolver stripped an indefinite ی off a surface that is
                # itself a pack noun the tagger kept whole, and the English names
                # that noun (_mark_en_gloss): یک ماهی بزرگ "a large fish" is fish,
                # not ماه; یک گوشی نو "a new phone" is گوشی, not گوش. Without
                # it the stem stays (یک دوستی "a friend", ماهی یک بار "once a
                # month"). An adjective stem (روز خوبی: خوب) or a participle
                # keeps its stem: the surface is no pack noun there.
                out[i] = (w, "NOUN")
        for i, t in enumerate(toks):
            r = out[i]
            if r is None and t[2] in ("NOUN", "ADJ", "ADV") and t[1] in pack and fold(t[0]).startswith(t[1]) and \
                    PASSAGE_SUFFIX_RE.fullmatch(fold(t[0])[len(t[1]):]):
                # the substring guard dropped a pack word with a comparative
                # before its indefinite ی (پروژه‌های مهم‌تری): the word
                out[i] = (t[1], t[2])
                continue
            w = fold(t[0] or "")
            cuts = [k for k in range(2, len(w) - 1) if "noun" in pack.get(w[:k], ()) and "noun" in pack.get(w[k:], ())]
            if (r is None or r[0] == w) and t[2] == "NOUN" and w == t[1] and w not in pack and len(cuts) == 1:
                # a noun compound (written with ZWNJ, which the tagger input
                # drops) whose two nouns the pack teaches but not the whole
                # (ثبت‌نام = ثبت + نام): its head noun
                out[i] = (w[:cuts[0]], "NOUN")
                continue
            if r is None or r[0] in pack:
                continue
            if " " in r[0] and r[1] == "VERB":
                # a light-verb compound the pack does not teach (دوست شدن):
                # its parts read as themselves (دوست, شدن)
                for j in range(len(toks)):
                    if out[j] == r:
                        up = "VERB" if toks[j][2] in ("VERB", "AUX") else toks[j][2]
                        out[j] = (toks[j][1], up)
            elif r[1] in ("ADP", "NOUN", "ADJ", "ADV") and any(
                    fold(t[0]).endswith(c) and fold(t[0])[:-len(c)] in pack and "prep" in pack[fold(t[0])[:-len(c)]]
                    for c in ("شان", "تان", "مان", "ش", "ت", "م")):
                # preposition + pronoun clitic (برایت, برایش): the preposition
                w = fold(t[0])
                c = next(c for c in ("شان", "تان", "مان", "ش", "ت", "م")
                         if w.endswith(c) and w[:-len(c)] in pack and "prep" in pack[w[:-len(c)]])
                out[i] = (w[:-len(c)], "ADP")
            elif r[1] in ("NOUN", "ADJ", "ADV") and re.search("(تر|ترین)(ها|های|ی)?$", fold(t[0])) and \
                    re.sub("(تر|ترین)(ها|های|ی)?$", "", fold(t[0])) in pack and \
                    "adj" in pack[re.sub("(تر|ترین)(ها|های|ی)?$", "", fold(t[0]))]:
                # a comparative/superlative the resolver kept whole (بزرگ‌ترها "elders"): its adjective
                out[i] = (re.sub("(تر|ترین)(ها|های|ی)?$", "", fold(t[0])), "ADJ")
            elif r[1] in ("NOUN", "ADJ"):
                # a noun/adjective + indefinite or ezafe ی read as a derived
                # word the pack does not have (زن خوب و آرامی: آرام, not
                # آرامی "calmness"); خوبی, which the pack has, stays
                done = False
                for w in (r[0], fold(t[0])):      # the lemma first: کودکی‌اش has lemma کودکی
                    for end in ("یی", "ای", "ی"):
                        stem = w[:-len(end)]
                        if w.endswith(end) and len(stem) >= 2 and stem in pack:
                            grp = r[1] if r[1].lower() in pack[stem] else \
                                ("ADJ" if "adj" in pack[stem] else "NOUN" if "noun" in pack[stem] else None)
                            if grp:
                                out[i] = (stem, grp)
                            done = True
                            break
                    if done:
                        break
        return out

    def _passage_gloss(self):
        """{folded pack lemma: its glosses joined} from pack/words.json (passages only)."""
        if not hasattr(self, "_p_gloss"):
            g = {}
            for w in json.loads((self.repo / "pack" / "words.json").read_text(encoding="utf-8")):
                k = fold(w["lemma"])
                g[k] = (g[k] + "; " if k in g else "") + w["en"]
            self._p_gloss = g
        return self._p_gloss

    def _passage_pack(self):
        """{folded pack lemma: {pos}} from pack/words.json (passages only)."""
        if not hasattr(self, "_p_pack"):
            pk = {}
            for w in json.loads((self.repo / "pack" / "words.json").read_text(encoding="utf-8")):
                pk.setdefault(fold(w["lemma"]), set()).add(w["pos"])
            self._p_pack = pk
        return self._p_pack

    # Tagger lemma -> pack lemma for the passage lemma fallback. ساله ("هفت
    # ساله", N years old) is سال. پزیدن: Wiktionary also lists an infinitive
    # built on the present stem پز, which shadows the pack verb پختن (بپزم,
    # می‌پزد). It is the only such shadow of a pack verb that is not itself a
    # pack word (بریدن/بردن, کشیدن/کشتن, گردیدن/گشتن are all pack verbs).
    passage_lemma_alias = {"ساله": "سال", "پزیدن": "پختن"}

    def _stanza_dir(self):
        return str(self.repo / ".cache" / "stanza")

    def tag_texts(self, texts):
        """Stanza tokenize+mwt+pos+lemma, one sentence per text. Raw output is
        cached per text (.cache/derived/stanza_raw_*.jsonl.gz) so rule changes
        in fix_token never re-run the model. A multi-word token (دوستم = دوست
        + م) is kept as one token with its first word's lemma, POS and features."""
        import stanza
        cache = self.repo / ".cache" / "derived" / f"stanza_raw_{stanza.__version__}.jsonl.gz"
        raw = {}
        if cache.exists():
            with gzip.open(cache, "rt", encoding="utf-8") as f:
                for line in f:
                    t, toks = json.loads(line)
                    raw[t] = toks
        todo = sorted({t for t in texts if t not in raw})
        if todo:
            stanza.download(self.stanza_lang, model_dir=self._stanza_dir(), processors="tokenize,mwt,pos,lemma",
                            logging_level="WARN")
            nlp = stanza.Pipeline(self.stanza_lang, dir=self._stanza_dir(), processors="tokenize,mwt,pos,lemma",
                                  tokenize_no_ssplit=True, logging_level="WARN", download_method=None,
                                  use_gpu=False)
            for i in range(0, len(todo), 500):
                chunk = todo[i:i + 500]
                docs = nlp.bulk_process([stanza.Document([], text=t) for t in chunk])
                for t, d in zip(chunk, docs):
                    toks = []
                    for s in d.sentences:
                        for tok in s.tokens:
                            w = tok.words[0]
                            feats = dict(kv.split("=", 1) for kv in (w.feats or "").split("|") if "=" in kv)
                            toks.append([tok.text, w.lemma or tok.text, w.upos, feats,
                                         [[x.text, x.lemma, x.upos] for x in tok.words] if len(tok.words) > 1 else None])
                    raw[t] = toks
            tmp = cache.with_suffix(".part")
            with gzip.GzipFile(tmp, "wb", mtime=0) as g:
                for t in sorted(raw):
                    g.write((json.dumps([t, raw[t]], ensure_ascii=False) + "\n").encode("utf-8"))
            tmp.replace(cache)
        for t in texts:
            # Clitic=Yes: a host + enclitic(s) token kept whole
            # Clitic=Yes: a host + enclitic(s) token kept whole; Host= its host word's UPOS
            yield [(x[0], x[1], x[2], dict(x[3], Clitic="Yes") if x[4] else x[3]) for x in raw[t]]

    # ---- kaikki side info (verbs: present stems; romanisation) -------------------------
    def _info(self):
        """{folded headword: [[display word, pos, romanisation, present stem, is_lemma, gloss]]}."""
        if hasattr(self, "_info_cache"):
            return self._info_cache
        from ..core.util import Env, file_sig
        from ..core.sources import kaikki_plain
        env = Env(self)
        src = kaikki_plain(env)
        sig = hashlib.sha1(f"fainfo5|{file_sig(src)}".encode()).hexdigest()[:10]
        out = env.derived / f"fa_info_{sig}.json.gz"
        if out.exists():
            with gzip.open(out, "rt", encoding="utf-8") as f:
                self._info_cache = json.load(f)
            return self._info_cache
        info = {}
        with open(src, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("lang_code") != "fa":
                    continue
                word = display_norm(d.get("word", ""))
                roms, prstem = [], None
                for fm in d.get("forms", []):
                    tags = fm.get("tags") or []
                    if "romanization" in tags and fm.get("form"):
                        roms.append(fm["form"])
                    if "present" in tags and "stem" in tags and fm.get("form") and prstem is None:
                        prstem = display_norm(fm["form"])
                if not roms:
                    # no romanization form: the head line's "(internet)", "(hiss / hess)"
                    for h in d.get("head_templates", []):
                        m = re.search(r"•\s*\(([^)]*)\)", h.get("expansion") or "")
                        if m and re.fullmatch(r"[a-zâāêēīîôōūûčšžġğxʼ'\- /]+", m.group(1)):
                            roms.append(m.group(1).split(" / ")[-1].strip())
                            break
                senses = d.get("senses", [])
                is_lemma = any(not (s.get("form_of") or s.get("alt_of") or
                                    set(s.get("tags", [])) & {"form-of", "alt-of", "misspelling"})
                               for s in senses)
                gloss = "; ".join((s.get("glosses") or [""])[-1] for s in senses[:4])
                info.setdefault(fold(word), []).append([word, d.get("pos", ""), roms[-1] if roms else None,
                                                        prstem, is_lemma, gloss])
        env.derived.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(out, "wb", mtime=0) as g:
            g.write(json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        self._info_cache = info
        return info

    def _verbs(self):
        """(infinitives, present stem -> infinitive, past stem -> infinitive), folded."""
        if hasattr(self, "_verb_cache"):
            return self._verb_cache
        infs, prs = set(), {}
        for key, rows in sorted(self._info().items()):
            for word, pos, rom, prstem, is_lemma, gloss in rows:
                if pos == "verb" and is_lemma and key.endswith(("تن", "دن")) and " " not in key:
                    infs.add(key)
                    if prstem and " " not in prstem:
                        prs.setdefault(fold(prstem), key)
        self._verb_cache = (infs, prs)
        return self._verb_cache

    VERB_LEMMA_FIX = {"است": "بودن", "هست": "بودن", "نیست": "بودن", "بود": "بودن", "باش": "بودن",
                      "بایست": "باید", "باید": "باید"}
    PERSON_ENDINGS = ("یم", "ید", "ند", "م", "ی", "د", "")

    PREVERBS = ("بر", "در", "باز", "فرا", "فرو", "وا")

    def _verb_lemma(self, surface, lemma):
        infs, prs = self._verbs()
        inf = self._verb_lemma1(surface, lemma)
        for pv in self.PREVERBS:
            # Stanza drops the preverb: بردارید -> داشت, برگشتم -> گشت
            if surface.startswith(pv) and not inf.startswith(pv) and pv + inf in infs:
                rest = surface[len(pv):]
                if self._verb_lemma1(rest, lemma) == inf:
                    return pv + inf
        return inf

    def _verb_lemma1(self, surface, lemma):
        infs, prs = self._verbs()
        if lemma in self.VERB_LEMMA_FIX:
            return self.VERB_LEMMA_FIX[lemma]
        if lemma in infs:
            return lemma
        if lemma + "ن" in infs:
            return lemma + "ن"
        if lemma in prs:
            return prs[lemma]
        s = surface
        for pre in ("نمی", "می", "ن", "ب", ""):
            if not s.startswith(pre):
                continue
            core = s[len(pre):]
            if core.endswith("ه") and len(core) > 2 and core[:-1] + "ن" in infs:
                return core[:-1] + "ن"          # past participle, also negated: نخورده -> خوردن
            for end in self.PERSON_ENDINGS:
                if end and not core.endswith(end):
                    continue
                stem = core[:len(core) - len(end)] if end else core
                if len(stem) < 2:
                    continue
                if stem + "ن" in infs:
                    return stem + "ن"
                if stem in prs:
                    return prs[stem]
                if stem.endswith("ی") and stem[:-1] in prs:
                    return prs[stem[:-1]]      # بیایم: stem آی
        return lemma + "ن" if lemma.endswith(("ت", "د")) else lemma

    # UD Persian-Seraji tags these ADJ/NOUN; the pack teaches them as adverbs /
    # prepositions / adjectives (POS decides distractors and the word's label)
    UPOS_FIX = {"دوباره": "ADV", "زود": "ADV", "دیر": "ADV", "اینطور": "ADV", "آنطور": "ADV", "همینطور": "ADV",
                "همانطور": "ADV", "بیرون": "ADV", "قبل": "ADV", "بعد": "ADV", "راجع": "ADP", "شبیه": "ADJ",
                "تنها": "ADV", "فورا": "ADV", "آهسته": "ADV", "بالا": "ADV", "پایین": "ADV", "واقعا": "ADV",
                "یکی": "PRON", "تمام": "ADJ", "پس": "ADV", "یعنی": "CONJ", "چپ": "ADJ", "کاش": "ADV",
                "بسیاری": "DET", "تمامی": "DET", "مقداری": "DET", "هزاران": "DET", "همگی": "PRON",
                "صادقانه": "ADV", "تعداد": "NOUN", "کنار": "ADP", "روبرو": "ADP", "اکثر": "ADJ", "حسابی": "ADJ", "کلیه": "NOUN"}
    LEMMA_FIX = {"ابتداء": "ابتدا", "پائین": "پایین", "بیش": "بیشتر", "مساله": "مسئله", "مسایل": "مسئله", "هیچی": "هیچ",
                 "ساله": "سال", "الان": "الآن", "دیگری": "دیگر", "بالای": "بالا", "روبروی": "روبرو"}

    def _formal_inf(self, w):
        """Colloquial infinitive (دونستن, موندن, تونستن) -> written form (ون -> ان).
        Wiktionary lists the colloquial ones as verbs too; the ان form wins
        whenever it is also an infinitive."""
        infs = self._verbs()[0]
        if "ون" not in w:
            return w
        for m in re.finditer("ون", w):
            c = w[:m.start()] + "ان" + w[m.end():]
            if c in infs:
                return c
        return w

    def fallback_lemma(self, surface, lemma):
        return self._formal_inf(lemma)

    def fix_token(self, tok):
        text, lemma, upos, ms = tok
        ftext, flemma = fold(text), fold(lemma)
        if upos != "PUNCT":
            # Stanza keeps a clitic token whole with the punctuation after it
            # (چیست؟ زیباست. متشکرم!): the word without the punctuation
            ftext, flemma = ftext.strip(TOKEN_PUNCT) or ftext, flemma.strip(TOKEN_PUNCT) or flemma
        flemma = self.LEMMA_FIX.get(flemma, flemma)
        if ftext == "رو" and upos == "ADP":
            flemma = "را"                       # colloquial object marker
        if flemma in self.UPOS_FIX and upos in ("ADJ", "NOUN", "ADV", "ADP"):
            upos = self.UPOS_FIX[flemma]
        if ftext in NAMES and ftext not in NAME_EN:
            upos = "PROPN"                      # تام, مری: Tatoeba's stock names
        if upos in ("VERB", "AUX"):
            flemma = self._formal_inf(self._verb_lemma(ftext, flemma))
        elif upos == "NOUN" and ftext == flemma and (flemma in self._verbs()[0] or (
                flemma.startswith("ن") and flemma[1:] in self._verbs()[0])):
            # کردن, شدن, نکردن as verbal nouns: the verb
            upos, flemma = "VERB", flemma if flemma in self._verbs()[0] else flemma[1:]
        elif upos in ("NOUN", "ADJ") and ftext == flemma and not self._info().get(ftext):
            # an enclitic pronoun Stanza left on the noun (زندگیم, سرت, کمکت,
            # انجامش): the host noun, when the dictionary has it
            for cl in ("مان", "تان", "شان", "یم", "یش", "م", "ت", "ش"):   # not -یت: فردیت is "individuality"
                host = ftext[:-len(cl)]
                if ftext.endswith(cl) and len(host) >= 2 and any(
                        r[1] in ("noun", "adj") and r[4] for r in self._info().get(host, [])):
                    flemma, ms = host, (ms + "|" if ms else "") + "Clitic=Yes"
                    break
        elif upos in ("ADJ", "ADV") and flemma in ("به", "بیش", "کم") and ftext.startswith(flemma + "تر"):
            flemma = ftext[:len(flemma) + 2] + ("ین" if ftext[len(flemma) + 2:].startswith("ین") else "")
            # بهتر "better", بیشتر "more" are words of their own, not به "to" / بیش
        info = self._info()
        is_lemma_pos = lambda w, poses: any(r[1] in poses and r[4] for r in info.get(w, []))
        if ftext in NUMBERS and upos in ("NOUN", "ADJ", "PROPN"):
            upos, flemma = "NUM", ftext             # ساعت هشت: the numeral
        elif upos == "PROPN" and ftext not in NAMES and is_lemma_pos(ftext, ("noun", "adj")) and \
                not any(r[1] == "name" for r in info.get(ftext, [])):
            upos, flemma = "NOUN", ftext            # شمال, جهان: common nouns Seraji tags PROPN
        elif "Clitic=Yes" in ms and upos in ("ADP", "PRON", "CCONJ", "SCONJ", "AUX") and \
                is_lemma_pos(ftext, ("noun", "adj")):
            upos, flemma = "NOUN", ftext            # درمان split as در + مان: the noun
        elif upos in ("VERB", "AUX") and flemma not in self._verbs()[0] and flemma != "باید":
            # adjective/noun + copula clitic lemmatised as a made-up verb
            # (خوشحالیم -> خوشیدن): the adjective or noun
            for end in ("ایم", "اید", "اند", "است", "یم", "ید", "ند", "ست", "ام", "ای", "م", "ی"):
                host = ftext[:-len(end)]
                if ftext.endswith(end) and len(host) >= 2 and is_lemma_pos(host, ("adj", "noun")):
                    upos = "ADJ" if is_lemma_pos(host, ("adj",)) else "NOUN"
                    flemma, ms = host, (ms + "|" if ms else "") + "Clitic=Yes"
                    break
        if upos == "VERB" and "VerbForm=Part" in ms and ftext in PART_ADJ:
            upos, flemma = "ADJ", ftext             # پیچیده است: "is complex", not a perfect tense
        elif upos == "ADJ" and ftext != flemma and ftext.endswith("ی") and \
                not any(r[1] == "adj" for r in info.get(flemma, [])) and is_lemma_pos(flemma, ("noun",)):
            upos = "NOUN"                           # بودجه‌ی مدرسه: noun + ezafe tagged ADJ
        elif upos == "NOUN" and flemma != ftext and not info.get(flemma) and ftext.endswith("ی") and \
                is_lemma_pos(ftext[:-1], ("noun",)):
            flemma = ftext[:-1]                     # اژدهای -> اژد (-ها read as a plural): اژدها
        if ftext in ("لطفا", "متشکرم") or flemma == "لطفا":
            flemma, upos = ftext if ftext == "متشکرم" else "لطفا", "INTJ"   # greetings Stanza reads as ADJ(+copula)
        return [ftext, flemma, upos, ms]

    def fix_sentence(self, toks, row, doc):
        """Stock names whose spelling is also a word (جان "life", کن "do!")
        are names when the English translation has the name."""
        en = row[3] if row else ""
        units = NINE_UNITS
        for i, t in enumerate(toks):
            nxt = toks[i + 1][2] if i + 1 < len(toks) else "PUNCT"
            nxt_t = toks[i + 1][0] if i + 1 < len(toks) else ""
            if (nxt_t in SUFFIX_WORDS and (t[2] in ("NOUN", "ADJ") or (t[0], nxt_t) in SPACED_PAIRS)) or \
                    (i and t[0] in SUFFIX_WORDS and (toks[i - 1][2] in ("NOUN", "ADJ", "X") or (toks[i - 1][0], t[0]) in SPACED_PAIRS)):
                # compound written with a space (برنامه ریزی, پیش بینی, روغن کاری, جمع آوری):
                # neither half is its own word ("small", "nose", "work")
                t[1], t[2] = t[0], "X"
            if t[2] in ("VERB", "AUX") and t[1] in ("کشیدن", "کشتن") and "کشت" not in t[0] and "کشید" not in t[0] \
                    and re.search("کش(م|ی|د|یم|ید|ند|ن)?$", t[0]):
                # present-stem کش is both کشیدن "pull, smoke, last, draw" and کشتن "kill":
                # decide from the sentence, else leave it unlinked
                forms = {x[0] for x in toks}
                if re.search(r"\b(kill|killed|kills|killing|murder|slay|slaughter)", en, re.I) or "قتل" in forms:
                    t[1] = "کشتن"
                elif forms & KESH_PULL or re.search(r"\b(smok|breath|draw|pull|last|take[sn]? \w+ (time|hours?|days?|minutes?)|stretch|wait|drag)", en, re.I):
                    t[1] = "کشیدن"
                else:
                    t[2] = "X"
            if t[2] in ("VERB", "AUX") and t[1] in ("گشتن", "گردیدن") and "گرد" in t[0] and "گردید" not in t[0] and \
                    (t[0].startswith(("بر", "باز")) or (i and toks[i - 1][0] in ("بر", "باز"))):
                # preverb, joined or spaced (برنگردد, بر می‌گردم): برگشتن / بازگشتن "return"
                pv = "باز" if (t[0].startswith("باز") or (i and toks[i - 1][0] == "باز")) else "بر"
                t[1] = pv + "گشتن"
                if not t[0].startswith(pv):
                    toks[i - 1][2] = "X"
            elif t[2] in ("VERB", "AUX") and t[1] in ("گشتن", "گردیدن") and "گرد" in t[0] and "گردید" not in t[0]:
                # present stem گرد is گشتن "turn, search, wander" and گردیدن "become"
                # (formal passive: منتشر می‌گردد); decide from the sentence, else unlinked
                prev = toks[i - 1] if i else None
                if re.search(r"\b(turn|search|look(ing|s|ed)? for|wander|walk(s|ed|ing)? around|go(es|ing)? around|"
                             r"roam|spin|circl|rotat|revolv|hunt)", en, re.I):
                    t[1] = "گشتن"
                elif prev is not None and (prev[2] in ("ADJ", "NOUN") or "VerbForm=Part" in prev[3]):
                    t[1] = "گردیدن"
                else:
                    t[2] = "X"
            if i + 1 < len(toks) and t[2] != "X" and toks[i + 1][2] in ("NOUN", "ADJ") and \
                    (t[0] in ("بی", "نا", "با") or t[2] in ("NOUN", "ADJ")) and len(t[0]) >= 2 - (t[0] in ("بی", "نا", "با")) and \
                    any(r[1] in ("noun", "adj") and r[4] for r in self._info().get(t[0] + toks[i + 1][0], [])):
                # a compound written with a space (نا امید, بی ادب, راه آهن, تازه کار):
                # neither half is its own word ("hope", "politeness", "iron")
                t[2] = toks[i + 1][2] = "X"
            for surf, en_re in HOMOGRAPH_EN.items():
                if t[0] == surf and re.search(en_re, en, re.I):
                    t[2] = "X"                  # کاری "curry", not کار
            if t[0] in HARAKAT_HOMOGRAPH and HARAKAT_HOMOGRAPH[t[0]] in (row[1] if row else ""):
                t[2] = "X"                      # آخُر "manger" (the damma says so), not آخر "end"
            if t[0] in ("سی", "دی") and ((i + 1 < len(toks) and (t[0], toks[i + 1][0]) == ("سی", "دی")) or
                                          (i and (toks[i - 1][0], t[0]) == ("سی", "دی"))):
                t[1], t[2] = t[0], "X"          # سی دی: CD, not thirty + the month Dey
            near = [x for x in toks[max(i - 2, 0):i + 3] if x is not t and x[2] != "PUNCT"]
            if t[0] == "نه" and sum(1 for x in near if x[0] in NUMBERS) >= 2:
                t[1], t[2] = "نه", "NUM"        # a list of numbers (هشت، نه، ده): nine
            if t[0] == "نه" and ((i + 1 < len(toks) and toks[i + 1][1] in units) or (i and toks[i - 1][0] == "ساعت")):
                t[1], t[2] = "نه", "NUM"        # نه سال, ساعت نه: nine, not "no"
            if t[0] == "رو" and i and toks[i - 1][2] in ("NOUN", "PRON", "PROPN", "DET", "ADJ") and \
                    nxt not in ("NOUN", "PROPN", "PRON"):
                t[1], t[2] = "را", "ADP"        # colloquial object marker (کاغذها رو بردارید)
            if t[0] in NAME_EN and re.search(r"\b" + NAME_EN[t[0]] + r"\b", en):
                t[2] = "PROPN"
        if row and row[0] == "passage":
            self._mark_en_gloss(toks, en)       # passages only; the corpus never has this row id
        return toks

    def _mark_en_gloss(self, toks, en):
        """Passage rows only: a token spelled like a pack noun X+ی whose stem X
        is also a pack noun (ماهی/ماه, گوشی/گوش, دوستی/دوست) gets the morph
        flag EnGloss=Yes when the English names a gloss word of X+ی ("a large
        fish", "a new phone"). passage_post_resolve keeps such a token whole;
        without the flag it is X + indefinite/ezafe ی (یک دوستی: a friend,
        ماهی یک بار: once a month)."""
        pack, gl = self._passage_pack(), self._passage_gloss()
        ew = set(re.findall("[a-z]+", en.lower()))
        ew |= {w[:-1] for w in ew if w.endswith("s")} | {w[:-2] for w in ew if w.endswith("es")}
        for t in toks:
            w = fold(t[0] or "")
            if w.endswith("ی") and "noun" in pack.get(w, ()) and "noun" in pack.get(w[:-1], ()) and \
                    ew & (set(re.findall("[a-z]{3,}", re.sub(r"\(.*?\)", " ", gl.get(w, "").lower()))) - EN_GLOSS_STOP):
                t[3] = (t[3] + "|" if t[3] else "") + "EnGloss=Yes"

    SHARED_STEM = {("کشیدن", "کشتن"), ("کشتن", "کشیدن"), ("شدن", "شستن")}

    # کمکم is کم‌کم "gradually" or کمک + م "help me". The corpus count keeps the
    # joined spelling as کم‌کم (a corpus rule re-ranked 864 words), so the
    # sentence links alone are corrected: after به, or before a form of کردن, it
    # is "help me" (the clitic links nothing, as in کمکشان).
    KAMKAM_HELP_RE = re.compile("^(?:نمی|می|ن|ب)?(?:کن|کرد)[" + LET + "]*$")
    FUTURE_AUX_RE = re.compile("^ن?خواه(?:م|ی|د|یم|ید|ند)$")    # کمکم نخواهد کرد

    def fix_links(self, row, toks, links, key_to_id):
        surf = [fold(t[0]) for t in toks]      # کُمکَم, Arabic kaf: folded
        if "کمکم" not in surf:
            return links
        if row is not None and "کمکم" not in MARKS_RE.sub("", row[1].translate(CHAR_MAP)):
            return links                       # only ZWNJ-written کم‌کم: "gradually" (tokens lose the ZWNJ)
        kam = key_to_id.get(("کمکم", "ADV"))
        if kam not in links:
            return links
        noun, compound, kardan = (key_to_id.get(("کمک", "NOUN")), key_to_id.get(("کمک کردن", "VERB")),
                                  key_to_id.get(("کردن", "VERB")))
        help_noun = help_verb = gradual = 0
        used_kardan = set()
        for i in range(len(toks)):
            if surf[i] != "کمکم":
                continue
            j = i + 1
            while j < len(toks) and self.FUTURE_AUX_RE.match(surf[j]):
                j += 1
            if j < len(toks) and self.KAMKAM_HELP_RE.match(surf[j]):
                help_verb += 1                 # کمکم کند, کمکم کن, کمکم نخواهد کرد: کمک کردن
                used_kardan.add(j)
            elif i and surf[i - 1] == "به":
                help_noun += 1                 # به کمکم آمد: the noun کمک
            else:
                gradual += 1
        if not (help_noun or help_verb):
            return links
        other_kardan = any(self.KAMKAM_HELP_RE.match(x) for j, x in enumerate(surf) if j not in used_kardan)
        return self._kamkam_relink(links, kam, noun if help_noun else None, compound if help_verb else None,
                                   None if other_kardan else kardan, gradual > 0)

    @staticmethod
    def _kamkam_relink(links, kam, noun, compound, kardan, keep_kam):
        """links with کم‌کم replaced in place by the help readings (noun, then the
        کمک کردن compound), کم‌کم kept when a token still reads "gradually", and
        کردن dropped when the compound took its only token."""
        out = []
        for wid in links:
            if wid == kam:
                if keep_kam:
                    out.append(wid)
                for x in (noun, compound):
                    if x and x not in out and x not in links:
                        out.append(x)
            elif wid == kardan and compound:
                continue
            elif wid not in out:
                out.append(wid)
        return out

    # ---- resolution ----------------------------------------------------------------
    def post_resolve(self, toks, out):
        """Light-verb compounds: a light verb with its noun/adjective up to 3
        tokens before it (skipping auxiliaries, not across را, punctuation or
        another verb) is the compound; both tokens resolve to it. A month
        name right after ماه is the month."""
        out = list(out)
        lx = self._lx
        for i, (t, r) in enumerate(zip(toks, out)):
            text, sl, upos, ms = t
            if not r or r[1] == "PROPN":
                continue
            if text == "رو" and sl == "را":
                out[i] = r = ("را", "ADP")          # colloquial object marker; Wiktionary has رو only as روی
            elif r[1] == "VERB" and text in COLLOQ_RAFTAN:
                out[i] = r = ("رفتن", "VERB")       # برم, میره: colloquial بروم, می‌رود (not بردن)
            if r[1] == "VERB" and (sl, r[0]) in self.SHARED_STEM:
                # present stem shared by two verbs (می‌کشد: pulls/smokes or kills);
                # Wiktionary's form table lists only one, the tagger reads context
                out[i] = r = (sl, "VERB")
            if r[1] in ("NOUN", "ADJ") and r[0] == text and sl and sl != text and text not in KEEP_SURFACE and \
                    text.startswith(sl) and text[len(sl):] in CLITIC_SUFFIXES and \
                    lx.usable_entries(sl, self.group_kpos[r[1]]) and \
                    not (text[len(sl):] in ("یت", "ی") and upos == "ADJ" and lx.usable_entries(text, ["adj"])) and \
                    not (text[len(sl):] == "یت" and lx.usable_entries(text, ["noun", "adj"])):
                # (سطحی "superficial" and فردیت "individuality" are words of their own)
                # host + clitic / indefinite -ی read as a rare headword of the same
                # spelling (دلم "pimple", ماست "yoghurt", مردی "manhood"): the host word
                out[i] = (sl, r[1])
            elif upos == "NOUN" and r[0] != text and not lx.usable_entries(text, ["noun"]):
                # a function word tagged NOUN reaches a noun only through an
                # alt-of pointer (چه -> چاه "well", طی -> تی "mop"): the function word
                for kp, g in (("pron", "PRON"), ("det", "DET"), ("prep", "ADP"), ("conj", "CONJ"), ("adv", "ADV"),
                              ("adj", "ADJ")):
                    # adjective only for a true alt-of pointer (کم "a little" -> شکم "belly"),
                    # not for host + -ی (زمانی stays زمان "time")
                    if kp == "adj" and text.startswith(r[0]):
                        continue
                    if lx.usable_entries(text, [kp]):
                        out[i] = (text, g)
                        break
        for i in range(len(toks) - 1):
            if toks[i][0] == "خواهش" and toks[i + 1][0] in ("میکنم", "میکنیم") and \
                    (i + 2 >= len(toks) or toks[i + 2][2] == "PUNCT"):
                out[i] = out[i + 1] = (PLEASE_PHRASE, "INTJ")   # خواهش می‌کنم: the phrase, not خواهش کردن
        for i, (t, r) in enumerate(zip(toks, out)):
            if not r or r[1] in ("VERB", "PROPN", "INTJ") or " " in r[0]:
                continue
            text = t[0]
            if r[0] == text and text.endswith("ی") and r[1] == "NOUN" and lx.usable_entries(text[:-1], ["noun"]) and \
                    lx.zipf(text[:-1]) >= lx.zipf(text) and (
                    (i and toks[i - 1][0] in INDEF_DET) or
                    (i + 1 < len(toks) and out[i + 1] and out[i + 1][0] == "داشتن")):
                # indefinite -ی (یک دوستی, هیچ دوستی, دوستی ندارد "has no friend"):
                # the base noun, not the abstract noun دوستی "friendship"
                out[i] = r = (text[:-1], "NOUN")
            if r[0] != text and text == r[0] + "ی" and lx.usable_entries(text, ["adj"]) and \
                    i + 1 < len(toks) and out[i + 1] and out[i + 1][0] in ("بودن", "شدن"):
                out[i] = r = (text, "ADJ")      # سطحی باشم "be superficial": the -ی adjective, not سطح + -ی
            if text in HOMOGRAPH_DENY:
                out[i] = None       # دعوی "lawsuit" is not دعوا "quarrel"; حقوق "law, salary" is not حق
                continue
            if r[0] != text and text.startswith(r[0]) and not GRAM_SUFFIX_RE.fullmatch(text[len(r[0]):]):
                # token-boundary guard: a lemma never matches inside a longer word
                # (مهربان is not مهر, فردیت is not فرد, شرور is not شر); the word itself or nothing
                out[i] = next(((text, g) for kp, g in (("noun", "NOUN"), ("adj", "ADJ"), ("adv", "ADV"))
                               if lx.usable_entries(text, [kp])), None)
        for i, r in enumerate(out):
            if not r or r[1] != "VERB" or r[0] not in LV_INDEX or toks[i][2] == "AUX":
                continue
            self._merge_light_verb(toks, out, i, LV_INDEX[r[0]])
        for i, t in enumerate(toks):
            if t[0] in MONTHS and i and toks[i - 1][0] == "ماه":
                out[i] = (t[0], "NOUN")
                out[i - 1] = ("ماه", "NOUN")    # در ماه تیر: ماه is "month" even when tagged PROPN
        return out

    @staticmethod
    def _between_kind(t, r):
        """One-letter class of a token standing between a compound's noun and
        its light verb: R را, A adverb, C noun/pronoun complement, P preposition."""
        if t[0] == "را":
            return "R"
        if t[2] == "ADV" or (r and r[1] == "ADV"):
            return "A"
        if t[2] in ("NOUN", "PRON"):
            return "C"
        if t[2] == "ADP":
            return "P"
        return "X"

    def _merge_light_verb(self, toks, out, i, nouns):
        """Light verb at i: merge it with its noun/adjective into the compound
        when (a) they are adjacent, or (b) one adverb stands between them, or
        (c) the noun takes a complement (COMPLEMENT_NOUNS: سوار قطار شد, وارد
        اتاق شد, علاقه‌ای به تاریخ ندارم, سعی‌ام را کردم) and only that complement,
        a preposition phrase, را and one adverb stand between. Auxiliaries and
        the future خواه- are skipped. Never across punctuation, a proper noun
        or another verb; an adjective between (دوست خارجی دارم, کشف بزرگی شد)
        blocks it, and so does a numeral/determiner before the noun (دو دوست دارم)."""
        between = []
        for j in range(i - 1, -1, -1):
            t = toks[j]
            if t[2] == "AUX" or (out[j] and out[j][0] == "خواستن" and t[0].startswith(("خواه", "نخواه"))):
                continue
            if t[2] in ("PUNCT", "PROPN") or (out[j] and out[j][1] == "VERB"):
                return
            n = out[j][0] if out[j] else t[0]
            cands = nouns.get(n) or nouns.get(t[0])
            if cands and t[0] == n + "ی" and not n.endswith("ی") and (t[2] == "ADJ" or (n, out[i][0]) in INDEF_OBJECT_LV):
                cands = None    # کشف بزرگی شد / کاری نکرده‌ام / دوستی ندارد: a noun phrase, not بزرگ شدن / کار کردن / دوست داشتن
            if cands and "Number=Plur" not in t[3]:
                kinds = "".join(reversed(between))
                infinitive = toks[i][0] == out[i][0]    # سخنرانی کردن inside عادت به سخنرانی کردن ندارم
                ok = kinds in ("", "A") or (n in COMPLEMENT_NOUNS and not infinitive and re.fullmatch("C{0,2}(PC{1,2})?R?A?", kinds))
                prev = toks[j - 1] if j else None
                if prev is not None and prev[2] in ("NUM", "DET") and prev[0] not in ("هیچ", "چه", "چند") and \
                        not (j >= 2 and toks[j - 2][0] in NUM_HEADS) and not any(pre for pre, _ in cands):
                    ok = False      # دو دوست دارم "I have two friends", not دوست داشتن
                    # (ساعت نه باز می‌شود: نه belongs to ساعت; به چه فکر می‌کنی: چه is a question word)
                if not ok:
                    return
                prev_t = prev[0] if prev is not None else ""
                comp = next((c for pre, c in cands if pre and pre == prev_t), None)
                if comp:
                    out[j - 1] = (comp, "VERB")
                else:
                    comp = next((c for pre, c in cands if not pre), None)
                if comp:
                    out[i] = out[j] = (comp, "VERB")
                return
            between.append(self._between_kind(t, out[j]))
            if len(between) > 4 or between[-1] == "X":
                return

    def bind_lexicon(self, lexicon):
        """Broken/irregular plural entries ("broken plural of کتاب") are form-of
        pointers to the singular, not lemmas; letter/character entries go."""
        self._lx = lexicon
        for ents in lexicon.E.values():
            for e in ents:
                for sn in e["s"]:
                    if "literary" in sn[2] or "formal" in sn[2]:
                        # written standard (گرسنه vs colloquial گشنه), not a marked register
                        sn[2] = [t for t in sn[2] if t not in ("literary", "formal")]
        rx = re.compile(r"^(?:broken |sound |irregular |arabic )?plural of ([^\s(]+)", re.I)
        for s, ents in lexicon.E.items():
            for e in ents:
                for sn in e["s"]:
                    m = rx.match(sn[0])
                    if m and sn[3] == "":
                        sn[3] = "form"
                        if MARKS_RE.search(m.group(1)) and lexicon.E.get(fold(m.group(1))):
                            continue    # اسرار = plural of سِرّ "secret", not of سر "head": no pointer
                        tgt = fold(m.group(1))
                        lexicon.F.setdefault(s, [])
                        if [tgt, e["p"], "form"] not in lexicon.F[s]:
                            lexicon.F[s].append([tgt, e["p"], "form"])
        for s in list(lexicon.E):
            ents = [e for e in lexicon.E[s] if e["p"] not in ("character", "suffix", "prefix", "symbol")]
            if ents:
                lexicon.E[s] = ents
            else:
                del lexicon.E[s]

    # ---- sentences written for the pack ----------------------------------------------
    def pack_json_extra(self):
        return {"spaced": True, "rtl": True, "langTag": "fa", "fontFamily": "Vazirmatn, \"Noto Naskh Arabic\", sans-serif",
                "fonts": ["Vazirmatn:wght@400;700"], "lineHeight": 1.9}

    def extra_corpus_rows(self, env):
        p = env.repo / "tools" / "generated_sentences.tsv"
        rows = []
        if not p.exists():
            return rows
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            fa, en = line.split("\t")[:2]
            rows.append([GEN_SID_BASE + len(rows), fa.strip(), "", en.strip(), None, None])
        return rows

    # example_rows: base default reads tools/generated_examples.tsv (کم‌کم,
    # whose only corpus examples are کمک + م; خودکشی, whose are policy-dropped)

    def sentence_fields(self, row):
        rec = {"t": display_sentence(row[1])}
        if row[0] >= GEN_SID_BASE:
            rec["src"] = "gen"
        return rec

    def extra_attribution(self, env, sentences):
        n = sum(1 for s in sentences if s.get("src") == "gen")
        return {"written_sentences": {
            "source": "written for this pack (tools/generated_sentences.tsv) and reviewed; marked \"src\": \"gen\"",
            "licence": "CC-BY-SA-4.0", "count": n,
            "note": "Written where Tatoeba has fewer than two usable sentences for a word; no audio."}}

    # ---- finishing ----------------------------------------------------------------------
    def finalize_words(self, env, ctx, words):
        from collections import Counter
        from ..core.gloss import strip_gloss_style
        from ..core.util import stat
        info = self._info()
        spell = {}                      # folded token -> Counter(spellings in the corpus, ZWNJ and tanwin kept)
        for r in ctx["rows_by_sid"].values():
            for m in self.word_re.finditer(TANWIN_KEEP_RE.sub("", r[1].translate(CHAR_MAP))):
                w = m.group(0).strip(ZWNJ)
                spell.setdefault(fold(w), Counter())[w] += 1

        corpus_text = "\n".join(display_norm(r[1]) for r in ctx["rows_by_sid"].values())

        def display(key):
            if key in DISPLAY:
                return DISPLAY[key]
            parts = []
            for p in key.split(" "):
                c = spell.get(p)
                best = sorted(c.items(), key=lambda kv: (-kv[1], kv[0] != p, kv[0]))[0][0] if c else p
                parts.append(best if c and sum(c.values()) >= 2 else
                             next((x[0] for x in info.get(p, []) if ZWNJ in x[0]), p))
            return " ".join(parts)

        def rom(key, pos=None, en=None):
            if key in FIXED_PRON:
                return normalize_pron(FIXED_PRON[key], key)
            rows = info.get(key, [])
            cands = [r for r in rows if r[2] and r[4] and (pos is None or r[1] == pos)] or \
                    [r for r in rows if r[2] and r[4]] or [r for r in rows if r[2]]
            if en and len(cands) > 1:
                # homographs (چک čak "slap" / ček "cheque"): the entry whose gloss shares a word with ours
                ours = set(re.findall(r"[a-z]{3,}", en.lower()))
                cands = sorted(cands, key=lambda r: -len(ours & set(re.findall(r"[a-z]{3,}", (r[5] or "").lower()))))
            return normalize_pron(cands[0][2], key) if cands else None

        def derive(key, shown=""):
            """No romanisation in Wiktionary: build it from a base word plus a
            derivational suffix (دقیقاً = daqiq + an, آخرین = âkhar + in, سختی =
            sakht + i), or from two words (اینکه = in + ke, همینطور = hamin + towr)."""
            key = key.replace(" ", "")
            if shown.endswith("\u0627\u064b") and rom(key[:-1]):
                return rom(key[:-1]).split(" ")[0] + "an"     # tanwin: دقیقاً = daqiq + an
            for suf, sr in DERIV_SUFFIX:
                if key.endswith(suf) and len(key) > len(suf) + 1:
                    b = rom(key[:-len(suf)])
                    if b:
                        return b.split(" ")[0] + sr
            for first in ("این", "آن", "همین", "همان", "چند", "هر", "هیچ"):
                if key.startswith(first) and len(key) > len(first) + 1 and rom(first) and rom(key[len(first):]):
                    return rom(first) + rom(key[len(first):])
            return None

        no_pron = []
        for w in words:
            w["en"] = strip_gloss_style(w["en"])
            # a sense list cut after a connective ("betrayal, including"): drop the dangling tail
            w["en"] = re.sub(r"[,;]\s*(including|such as|e\.g\.|namely|like|especially|of|and|or)\s*$", "", w["en"])
            key = w["lemma"]
            w["w"] = w["lemma"] = display(key)
            pos = {"noun": "noun", "verb": "verb", "adj": "adj", "adv": "adv", "pron": "pron", "prep": "prep",
                   "conj": "conj", "num": "num", "intj": "intj", "det": "det"}.get(w["pos"])
            p = rom(key, pos, w["en"])
            if p is None and " " in key:
                ps = [rom(x) or derive(x) for x in key.split(" ")]
                p = " ".join(ps) if all(ps) else None
            if p is None:
                p = derive(key, w["w"])
            if p:
                w["pron"] = p
            else:
                no_pron.append(key)
            if key == PLEASE_PHRASE:
                w["pos"] = "phrase"     # forced as INTJ to hold the gloss; taught as one phrase
            if w["pos"] == "verb":
                stem = None
                for r in info.get(key, []):
                    if r[1] == "verb" and r[3]:
                        stem = r[3]
                        break
                if stem and fold(stem) != key and " " not in key:
                    # the present stem (رو for رفتن); a compound verb keeps no alt:
                    # the engine reads alt[0] of a multiword w as its bare trailing token
                    w["alt"] = [stem]
                else:
                    w.pop("alt", None)
            elif w.get("alt"):
                w.pop("alt", None)
            if ZWNJ in w["w"]:
                # the engine matches examples literally: a ZWNJ headword (آن‌ها,
                # کم‌کم) also carries its joined spelling, and its spaced one
                # when the corpus writes it so (آن ها), or those examples go unfound
                forms = [w["w"].replace(ZWNJ, "")]
                spaced = w["w"].replace(ZWNJ, " ")
                if re.search(f"(?<![{LET}\u200c]){re.escape(spaced)}(?![{LET}\u200c])", corpus_text):
                    forms.append(spaced)
                w["alt"] = (w.get("alt") or []) + [f for f in forms if f not in (w.get("alt") or [])]
        stat("fa_display", {"words_without_pron": sorted(no_pron),
                            "pron_coverage": f"{len(words) - len(no_pron)}/{len(words)}"})

    # ---- checks ----------------------------------------------------------------------
    def check_word(self, w):
        f = fold(w["w"])
        if w.get("pos") == "noun" and (w["w"].endswith(ZWNJ + "ها") or (
                f.endswith("ها") and any(r[1] == "noun" for r in self._info().get(f[:-2], [])))):
            return f"noun {w['id']} {w['w']!r}: plural -ها form as a lemma"
        if w.get("pos") == "verb" and not (re.search("(تن|دن)$", w["w"]) or w["w"] == "باید"):
            return f"verb {w['id']} {w['w']!r}: not an infinitive"
        if w.get("pos") == "adj" and f.endswith("ترین"):
            return f"adj {w['id']} {w['w']!r}: superlative -ترین form as a lemma"
        if re.search("[يك\u064c-\u065f]", w["w"]):
            return f"word {w['id']} {w['w']!r}: Arabic yeh/kaf or harakat in w"
        return None

    # ---- QA scans ------------------------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DISPLAY.get(x, x) for x in DAYS), "months": " ".join(MONTHS),
        "seasons": " ".join(SEASONS), "num": " ".join(NUMBERS),
        "col": " ".join(DISPLAY.get(x, x) for x in COLOURS),
        "core": " ".join([DISPLAY.get(x, x) for x in GREETINGS + PRONOUNS + DEMONSTR + PREPS] +
                         [x for x, _ in QUESTION + CONJS]),
    }
    qa_verb_re = r"(تن|دن)$|^باید$"
    qa_foreign_letters_re = r"[a-z]"
    qa_proper_re = r"\b(Iran|Tehran|Persia|Islam|Muhammad|God|Allah)\b"


SPEC = Persian
