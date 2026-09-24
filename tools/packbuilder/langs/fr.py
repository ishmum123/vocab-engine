"""French (fr): everything French-specific in the pack pipeline.

The A1 core list, gloss overrides and the aspirated-h list live in the french
repo (tools/). Rules are described in the french repo's tools/REPORT.md.

Tagger: fr_core_news_lg. The small model tags second-person dialogue badly
(Tatoeba sample of 3000 sentences, subject pronoun tagged PRON: sm 90.5%,
lg 99.7%; word after the subject tagged VERB/AUX: sm 88.8%, lg 96.9%;
"tu" often ADP, "fais"/"viens" NOUN). Same licence (LGPL-LR), same speed.
"""
import math
import re

from .base import LanguageSpec, SENSITIVE_EN, SENSITIVE_GLOSS_EN, TATOEBA_ENG, TATOEBA_LINKS, TATOEBA_AUDIO

LETTERS = "a-zàâäçéèêëîïôöùûüÿœæ"
VOWELS = "aeiouàâäéèêëîïôöùûüœæ"      # y counts as a consonant for elision (le yaourt)

DAYS = "lundi mardi mercredi jeudi vendredi samedi dimanche".split()
MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
SEASONS = "printemps été automne hiver".split()
NUMBERS = ("zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize "
           "dix-sept dix-huit dix-neuf vingt trente quarante cinquante soixante soixante-dix quatre-vingts "
           "quatre-vingt-dix cent mille").split()
COLOURS = "rouge bleu vert jaune noir blanc gris marron brun rose orange violet".split()
NATIONALITIES = "français anglais allemand espagnol italien américain".split()

# elided forms -> (lemma, group); "l'"/"qu'"/"s'" depend on the tag (see _elided)
ELIDED = {"j'": ("je", "PRON"), "m'": ("me", "PRON"), "t'": ("te", "PRON"), "c'": ("ce", "PRON"),
          "n'": ("ne", "ADV"), "d'": ("de", "ADP"), "jusqu'": ("jusque", "ADP"),
          "lorsqu'": ("lorsque", "CONJ"), "puisqu'": ("puisque", "CONJ"), "quoiqu'": ("quoique", "CONJ"),
          "presqu'": ("presque", "ADV"), "quelqu'": ("quelque", "DET")}
# hyphen-attached clitics after an imperative or an inverted verb (donne-moi,
# lève-toi, peux-tu, allez-y): the token is "-moi"; "-t-" is euphonic
HYPHEN_CLITIC = {c: (c, "PRON") for c in
                 "moi toi lui leur nous vous y en je tu il elle on ils elles ce".split()}
HYPHEN_CLITIC.update({"le": ("le", "PRON"), "la": ("le", "PRON"), "les": ("le", "PRON"),
                      "là": ("là", "ADV")})
HYPHEN_SKIP = {"-", "‐", "-t", "-t-", "‐t"}
# fixed single-token readings the tagger gets wrong ("quelqu'un" PROPN)
SURFACE_FIXED = {"quelqu'un": ("quelqu'un", "PRON"), "ça": ("ça", "PRON"), "eux": ("eux", "PRON"),
                 "tu": ("tu", "PRON"), "marre": ("marre", "ADV"), "voilà": ("voilà", "INTJ"),
                 "voici": ("voici", "INTJ"), "enceinte": ("enceinte", "ADJ"), "enceintes": ("enceinte", "ADJ"),
                 # adjective forms before a vowel
                 "bel": ("beau", "ADJ"), "petit-déjeuner": ("petit déjeuner", "NOUN"),
                 "petits-déjeuners": ("petit déjeuner", "NOUN"), "nouvel": ("nouveau", "ADJ"), "vieil": ("vieux", "ADJ"),
                 "fol": ("fou", "ADJ")}
# determiner paradigms: one entry each, the other forms are alts (see finalize_words)
DET_PARADIGM = {"ce": "cet", "cet": "cet", "cette": "cet", "ces": "cet",
                "mon": "mon", "ma": "mon", "mes": "mon", "ton": "ton", "ta": "ton", "tes": "ton",
                "son": "son", "sa": "son", "ses": "son", "notre": "notre", "nos": "notre",
                "votre": "votre", "vos": "votre", "leur": "leur", "leurs": "leur",
                "quel": "quel", "quelle": "quel", "quels": "quel", "quelles": "quel",
                "aucun": "aucun", "aucune": "aucun"}
DET_ALTS = {"cet": ("ce", ["cet", "cette", "ces"]), "mon": ("mon", ["ma", "mes"]), "ton": ("ton", ["ta", "tes"]),
            "son": ("son", ["sa", "ses"]), "notre": ("notre", ["nos"]), "votre": ("votre", ["vos"]),
            "leur": ("leur", ["leurs"]), "quel": ("quel", ["quelle", "quels", "quelles"]),
            "aucun": ("aucun", ["aucune"])}
# verbs always shown with se (their non-reflexive use is rare or another verb)
ALWAYS_PRONOMINAL = {"taire", "marrer", "souvenir", "moquer", "méfier", "évanouir", "enfuir", "dépêcher",
                     "écrier", "efforcer", "absenter", "suicider"}
# words the tokenizer must keep whole (the hyphen/elision rules split them)
KEEP_WHOLE = ["quelqu'un", "c'est-à-dire", "week-end", "week-ends", "là-bas", "grands-parents",
              "petits-enfants", "arc-en-ciel", "au-dessous", "aujourd'hui"]
# spelling folds for frequency-list surfaces typed without the œ ligature
OE_WORDS = ("cœur sœur œil œuf œufs œuvre œuvres vœu vœux nœud bœuf mœurs cœurs sœurs manœuvre "
            "chœur œillet").split()
OE_FOLD = {w.replace("œ", "oe"): w for w in OE_WORDS}

SINGULAR_ARTICLES = {"le", "la", "l'", "le/la"}
# wordfreq drops the elision apostrophe: l, c, qu stand for l', c', qu'
ELISION_LETTERS = {"l", "c", "d", "j", "m", "n", "s", "t", "qu", "jusqu", "lorsqu", "puisqu"}
REFORM_RE = re.compile(rf"^(?:post-1990|pre-1990|superseded) spelling of ([{LETTERS}' -]+)$")
GROUP_HEAD_RE = re.compile(r"^(.+?),? in (?:its|their|all its) (?:various )?senses?(?:, including)?:?$")
EN_IDIOM_RE = re.compile(r"\b(if a day|to boot|for the life of me|by a long shot|in a nutshell|beats me|"
                         r"break a leg|piece of cake|under the weather|kick the bucket|raining cats|"
                         r"hit the sack|hit the hay|spill the beans|bite the bullet|cost an arm|"
                         r"once in a blue moon|the ball is in your court|pull(ing)? your leg|"
                         r"a dime a dozen|call it a day|cut corners|get the ball rolling)\b", re.I)
VIOLENT_LEMMAS = {"tuer", "meurtre", "meurtrier", "assassin", "assassiner", "assassinat", "cadavre", "sang",
                  "pistolet", "fusil", "arme", "poignarder", "bombe", "massacre", "mort", "mourir", "cercueil",
                  "noyer", "pendre", "étrangler", "tirer", "blesser", "blessure", "guerre", "violence", "frapper",
                  "battre", "gifler", "enterrer", "exécuter", "otage", "kidnapper", "voler", "voleur", "prison"}
MARKED_SENSE_TAGS = {"figuratively", "figurative", "colloquial", "slang", "informal", "humorous", "euphemistic",
                     "pejorative", "derogatory", "vulgar", "familiar", "idiomatic", "by-extension", "metonymically",
                     "especially", "Louisiana", "Quebec", "Belgium", "Switzerland", "Canada", "US",
                     "North-America", "Africa"}
# gender homographs whose Wiktionary-first entry is the corpus minority
# (le tour 200 : la tour 102, le poste 218 : la poste 62, counted from the
# determiner before the noun); the gloss names the other gender's sense
PRON_ALTS = {"le": ["la", "les"]}
MAJORITY_GENDER = {"tour": "m", "poste": "m"}
# passé simple forms Wiktionary also lists as participles or nouns (dus, bus,
# lus): marked only right after a subject. Forms shared with the present
# (dit, vit, finit) are not listed.
AUX_FORMS = set("""suis es est sommes êtes sont étais était étions étiez étaient serai seras sera serons serez
    seront serais serait serions seriez seraient sois soit soyons soyez soient fus fut été ai as a avons avez ont
    avais avait avions aviez avaient aurai auras aura aurons aurez auront aurais aurait aurions auriez auraient
    aie aies ait ayons ayez aient eu""".split())
# nouns in avoir/être idioms that can look like participles (avoir tort: tordre)
AVOIR_IDIOM_NOUNS = {"besoin", "peur", "faim", "soif", "raison", "tort", "honte", "envie", "lieu", "mal",
                     "confiance", "droit", "tendance", "horreur", "conscience", "froid", "chaud", "sommeil"}
PRENOMINAL_ADJ = {"beau", "bon", "grand", "gros", "haut", "jeune", "joli", "long", "mauvais", "meilleur",
                  "nouveau", "petit", "vieux", "vrai", "faux", "premier", "dernier", "seul", "autre", "même",
                  "prochain", "ancien", "pauvre", "cher", "double", "pire", "moindre"}


def clause_end(toks, i):
    """Index of the first punctuation token after i (or the end)."""
    for j in range(i + 1, len(toks)):
        if toks[j][2] == "PUNCT":
            return j
    return len(toks)


PS_AFTER_SUBJECT = set("""dus dut dûmes durent fus fut fûmes furent eus eut eûmes eurent fis fit fîmes firent
    pus put purent sus sut surent vins vint vînmes vinrent tins tint tinrent voulus voulut voulurent mit mirent
    prit prirent crus crut crurent bus but burent lus lut lurent connus connut connurent parus parut parurent
    mourut moururent naquit naquirent plut reçus reçut reçurent vécus vécut vécurent sortit sortirent partit
    partirent ouvrit ouvrirent offrit offrirent rendit rendirent perdit perdirent attendit attendirent
    entendit entendirent répondit répondirent devint devinrent revint revinrent""".split())
REFLEXIVE_SENSE_SHARE = 0.15   # share of a plain verb's corpus uses with a reflexive clitic
# hand se-senses for common verbs (used with >= 5 reflexive corpus uses, any share)
REFL_SENSE = {"trouver": "to be (located)", "rendre": "to go (to)", "passer": "to happen",
              "mettre": "to start (se mettre à)", "tenir": "to stand; to behave", "retrouver": "to end up; to meet up",
              "présenter": "to introduce oneself", "nommer": "to be called", "appeler": "to be called",
              "demander": "to wonder", "douter": "to suspect", "réaliser": "to come true",
              "servir": "to help oneself; to use (se servir de)", "battre": "to fight", "remettre": "to recover (from)",
              "entraîner": "to practise, to train", "accorder": "to agree", "révéler": "to turn out",
              "arrêter": "to stop", "sentir": "to feel", "faire": "to get (done)",
              "aller": "to go away (s'en aller)", "rappeler": "to remember", "lever": "to get up",
              "coucher": "to go to bed", "laver": "to wash (oneself)", "promener": "to go for a walk",
              "habiller": "to get dressed", "reposer": "to rest", "marier": "to get married",
              "occuper": "to look after (s'occuper de)", "inquiéter": "to worry", "tromper": "to make a mistake",
              "perdre": "to get lost", "voir": "to see each other; to be seen", "dire": "to say to oneself",
              "maintenir": "to remain, to hold", "élever": "to rise", "arranger": "to work out; to manage",
              "imposer": "to be essential; to assert oneself", "disputer": "to argue", "adapter": "to adapt",
              "débarrasser": "to get rid (of)", "éloigner": "to move away", "relever": "to get up again",
              "taper": "to put up with (informal)", "appliquer": "to apply oneself; to apply (to)",
              "mêler": "to interfere (in)", "habituer": "to get used (to)", "accrocher": "to hold on (to)",
              "figurer": "to imagine", "éteindre": "to die out, to go out", "arracher": "to fight over"}
# the displayed se-form when it is not se/s' + verb
REFL_FORM = {"aller": "s'en aller"}
NOT_PLAIN_TAGS = MARKED_SENSE_TAGS | {"dialectal", "archaic", "obsolete", "dated", "rare", "literary",
                                      "regional", "historical", "nonstandard", "proscribed", "Louisiana"}
# a usage note, not a translation: does not count as a plain sense
USAGE_NOTE_RE = re.compile(r"^(used|creates?|replaces?|indicates?|forms?|introduces?|expresses?|denotes?|"
                           r"marks?|serves?)\b", re.I)
IN_THE_FORM_RE = re.compile(r"\b(?:in|into) the (?:form|shape) of\b")
# adjectives that stay adjectives after an article (le premier, les autres)
DET_LIKE_ADJ = {"premier", "dernier", "seul", "même", "autre", "meilleur", "pire", "prochain", "suivant",
                "deuxième", "second", "troisième", "tel", "nombreux", "certain", "moindre", "tout"}
# cut a gloss at an explanatory tail: "a sponge cake, i.e. a cake...", "dollar, usually the US dollar"
TAIL_CUT_RE = re.compile(r",?\s+(?:i\.\s?e\b\.?|e\.\s?g\b\.?|viz\b\.?|especially|usually|typically|particularly|"
                         r"generally|mainly|mostly|chiefly|such as|including|in particular)\b")
META_SENSE_RE = re.compile(r"^(general senses?|in general|literally|figuratively|other senses?)$", re.I)
FEM_ADJ_RE = re.compile(rf"^feminine(?: singular)? of ([{LETTERS}-]+)$")
FEM_DET = {"la", "une", "cette", "ma", "ta", "sa", "quelle", "aucune", "nulle", "toute"}
MASC_DET = {"le", "un", "ce", "cet", "du", "au", "mon", "ton", "son", "quel", "aucun", "nul", "tout"}
SUBJ_PRON = {"je", "j'", "tu", "il", "elle", "on", "ils", "elles"}
OBJ_CLITICS = {"ne", "n'", "me", "m'", "te", "t'", "se", "s'", "le", "la", "les", "l'", "lui", "leur",
               "y", "en", "nous", "vous"}
NOMINAL_BEFORE = {"le", "la", "l'", "une", "un", "cette", "chaque", "une", "quelle", "seule", "même",
                  "autre", "aucune", "toute", "la", "ma", "ta", "sa", "notre", "votre", "leur"}
POSS_PRON = {"mien", "mienne", "miens", "miennes", "tien", "tienne", "tiens", "tiennes", "sien", "sienne",
             "siens", "siennes", "nôtre", "nôtres", "vôtre", "vôtres", "leur", "leurs"}
# nouns used bare after être that also have an adjective reading (je suis étudiant)
PREDICATE_NOUNS = {"étudiant", "étudiante", "enfant", "témoin"}
# nouns shown in the plural (their singular is another sense): lemma -> plural
PLURAL_DISPLAY = {"vacance": "vacances"}
VERB_GLOSS_KEEP = re.compile(r"^(can|must|may|might|should|will|would|here|there|that|it|ago|have to)\b")
DEFN_PART_RE = re.compile(r"\b(that|which|who|whose|whom|helping|used|being|such as|especially)\b")
# fixed expressions whose content word does not carry its headword sense
# (bon marché = cheap, not a market): that token links nothing
# (token alternatives, index of the token left unlinked)
IDIOM_UNLINK = [
    (({"bon"}, {"marché"}), 1),
    (({"en"}, {"général"}), 1),
    (({"à"}, {"part"}), 1),
    (({"en"}, {"conserve"}), 1),
    (({"en"}, {"conserves"}), 1),
    (({"au"}, {"fait"}), 1),
]
Y_A = {"a", "avait", "aura", "aurait", "ait", "eut", "avoir", "aurai"}
# multiword expressions: (token alternatives, lemma, group, anchor token index)
MWES = [
    (({"parce"}, {"que", "qu'"}), "parce que", "CONJ", 0),
    (({"quelque"}, {"chose"}), "quelque chose", "PRON", 1),
    (({"d'"}, {"abord"}), "d'abord", "ADV", 1),
    (({"d'"}, {"accord"}), "d'accord", "ADV", 1),
    (({"tout"}, {"le"}, {"monde"}), "tout le monde", "PRON", 2),
    (({"tout"}, {"de"}, {"suite"}), "tout de suite", "ADV", 2),
    (({"tout"}, {"à"}, {"fait"}), "tout à fait", "ADV", 2),
    (({"tout"}, {"à"}, {"coup"}), "tout à coup", "ADV", 2),
    (({"tout"}, {"à"}, {"l'"}, {"heure"}), "tout à l'heure", "ADV", 3),
    (({"à"}, {"peu"}, {"près"}), "à peu près", "ADV", 2),
    (({"bien"}, {"sûr"}), "bien sûr", "ADV", 1),
    (({"au"}, {"moins"}), "au moins", "ADV", 1),
    (({"en"}, {"fait"}), "en fait", "ADV", 1),
    (({"à"}, {"cause"}, {"de", "d'", "du", "des"}), "à cause de", "ADP", 1),
    (({"afin"}, {"de", "d'"}), "afin de", "CONJ", 0),
    (({"en"}, {"train"}, {"de", "d'"}), "en train de", "ADV", 1),
    (({"à"}, {"peine"}), "à peine", "ADV", 1),
    (({"grâce"}, {"à", "au", "aux"}), "grâce à", "ADP", 0),
    (({"quand"}, {"même"}), "quand même", "ADV", 1),
    (({"de"}, {"temps"}, {"en"}, {"temps"}), "de temps en temps", "ADV", 1),
    (({"en"}, {"même"}, {"temps"}), "en même temps", "ADV", 2),
    (({"tant"}, {"pis"}), "tant pis", "ADV", 1),
    (({"à"}, {"la"}, {"fois"}), "à la fois", "ADV", 2),
    (({"au"}, {"lieu"}, {"de", "d'", "du", "des"}), "au lieu de", "ADP", 1),
    (({"petit", "petits"}, {"déjeuner", "déjeuners"}), "petit déjeuner", "NOUN", 1),
    (({"lors"}, {"de", "d'", "du", "des"}), "lors de", "ADP", 0),
    (({"à"}, {"travers"}), "à travers", "ADP", 1),
    # fixed phrases, token level (the parts link nothing else): tenses of il y a,
    # "il n'y a" (ne keeps its own link), reform spelling plait
    (({"il"}, {"y"}, Y_A), "il y a", "PHRASE", 2),
    (({"il"}, {"n'", "ne"}, {"y"}, Y_A), "il y a", "PHRASE", 3),
    (({"est"}, {"-ce", "ce"}, {"que", "qu'"}), "est-ce que", "PHRASE", 0),
    (({"s'"}, {"il"}, {"vous"}, {"plaît", "plait"}), "s'il vous plaît", "PHRASE", 3),
    (({"s'"}, {"il"}, {"te"}, {"plaît", "plait"}), "s'il te plaît", "PHRASE", 3),
    (({"excusez"}, {"-moi"}), "excusez-moi", "PHRASE", 0),
    (({"y"}, Y_A, {"-t"}, {"-il"}), "il y a", "PHRASE", 1),      # "Combien y a-t-il ...?"
    (({"y"}, Y_A, {"-il"}), "il y a", "PHRASE", 1),              # "y avait-il"
    (({"au"}, {"revoir"}), "au revoir", "PHRASE", 1),
]
# suppletive comparatives are their own learner lemmas (Wiktionary: form-of bon/mauvais/petit)
SUPPLETIVE = {"meilleur": "better, best", "pire": "worse, worst", "moindre": "lesser, least"}
DEM_POSS_DET = {"mon", "ton", "son", "ma", "ta", "sa", "mes", "tes", "ses", "notre", "votre", "leur", "nos",
                "vos", "leurs", "ce", "cet", "cette", "ces", "chaque", "quel", "quelle", "quels", "quelles"}
ARTICLES = {"le", "la", "l'", "les", "un", "une", "des", "du"}
# je vis / il vit: vivre (present) or voir (passé simple); a following
# place/manner word means vivre ("Je vis dans un appartement")
VIVRE_NEXT = {"à", "au", "aux", "dans", "en", "avec", "chez", "ici", "là", "seul", "seule", "toujours",
              "encore", "près", "loin", "bien", "heureux", "heureuse", "ensemble", "depuis", "sans"}
# colloquial t' for tu before a second-person avoir/être form (t'as, t'es)
T_TU_NEXT = {"as", "es", "avais", "étais", "auras", "seras", "aurais", "serais", "avait", "était"}
# Wiktionary form tags that make a surface more than a literary past
NON_LITERARY_FORM_TAGS = {"present", "imperfect", "future", "conditional", "imperative", "participle",
                          "infinitive", "gerund"}


def _content_words(gloss):
    return {w for w in re.findall(r"[a-z]+", re.sub(r"\(.*?\)", " ", gloss.lower()))
            if w not in ("a", "an", "the", "of", "to", "or", "and", "in", "on", "one", "side", "hand")}


class HyphenCliticTokenMatch:
    """spaCy's French token_match keeps "dis-le-moi" whole; clitic-final
    hyphen words must fall through to the suffix rule instead. Picklable."""

    def __init__(self, orig):
        self.orig = orig
        self.clre = re.compile(r"[-‐](?:%s)$" % "|".join(sorted(HYPHEN_CLITIC)), re.I)

    def __call__(self, s):
        if self.clre.search(s):
            return None
        return self.orig(s) if self.orig else None


class French(LanguageSpec):
    code = "fr"
    name_en = "French"
    pack_name = "French (A1–B1)"
    tts = "fr-FR"
    stt = "fr-FR"
    tatoeba_code = "fra"

    spacy_model = "fr_core_news_lg"
    spacy_n_process = 3
    tagger_attribution = {
        "source": "spaCy (MIT) + fr_core_news_lg 3.8.0 model (LGPL-LR, trained on UD French Sequoia and WikiNER)",
        "licence": "LGPL-LR (model)",
        "note": "Used at build time only; the pack ships no model files.",
    }

    subtitles_file = "fr_full.txt"
    kaikki_file = "kaikki_fr.jsonl.gz"
    sentences_file = "fra_detailed.tsv.bz2"
    kelly_file = None       # no usable open CEFR list for French
    sources = {
        "fr_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/fr/fr_full.txt",
        "kaikki_fr.jsonl.gz": "https://kaikki.org/dictionary/French/kaikki.org-dictionary-French.jsonl.gz",
        "fra_detailed.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/fra/fra_sentences_detailed.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_LINKS[0]: TATOEBA_LINKS[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
    }
    versions = {"corpus": "c1", "tag": "t2", "lex": "l4"}

    word_re = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœÆæ]+")
    # multiword headwords (parce que, tout le monde) are kept for MWES
    # tokens kept whole by setup_nlp that the tagger often reads as PROPN
    # (là-bas 99% PROPN, week-end 27%): fixed reading whatever the tag
    closed_surfaces = {"là-bas": ("là-bas", "ADV"), "week-end": ("week-end", "NOUN"),
                       "week-ends": ("week-end", "NOUN"), "petit-déjeuner": ("petit déjeuner", "NOUN"),
                       "petits-déjeuners": ("petit déjeuner", "NOUN"), "arc-en-ciel": ("arc-en-ciel", "NOUN"),
                       "arcs-en-ciel": ("arc-en-ciel", "NOUN"), "grands-parents": ("grands-parents", "NOUN"),
                       "petits-enfants": ("petits-enfants", "NOUN"), "au-dessous": ("au-dessous", "ADV"),
                       "aujourd'hui": ("aujourd'hui", "ADV")}
    lex_word_re = re.compile(rf"^[{LETTERS}]+(?:[' -][{LETTERS}]+)*'?$")
    sub_token_re = re.compile(rf"^[{LETTERS}]+(?:['-][{LETTERS}]+)*'?$")
    form_target_re = re.compile(rf"\bof ([{LETTERS}'-]+)")
    fem_of_re = re.compile(rf"(?:female equivalent|(?:singular )?feminine(?: singular)?) of ([{LETTERS}-]+)")
    # capital À is often typed A: a/à, la/là, ou/où, du/dû
    accent_variants = {"a": "à", "u": "ùû"}

    noun_head_template = "fr-noun"
    group_kpos = dict(LanguageSpec.group_kpos, ADV=["adv", "particle", "conj", "prep"])      # ne: particle
    regional_tags = {"US", "North-America", "Quebec", "Louisiana", "Belgium", "Switzerland", "Canada", "Africa", "Acadia",
                     "Cajun", "Haiti", "Provence", "Southern-France", "Northern-France", "New-Caledonia",
                     "Canada-French", "Réunion", "Maghreb", "Ivory-Coast", "Cameroon", "Congo"}

    art_prep = {"au": "à", "aux": "à", "du": "de", "des": "de"}
    article_forms = {"le": {"le", "la", "l'", "les"}, "un": {"un", "une"}}
    definite_article = "le"
    pluralia_tantum = {"gens", "lunettes", "ciseaux", "fiançailles", "environs", "mœurs", "obsèques",
                       "funérailles", "vacances", "frais", "affaires", "toilettes", "courses", "cheveux"}
    copulas = {"être", "devenir", "sembler", "rester", "paraître", "demeurer"}
    refl_clitics = {"me": ("1", "Sing"), "m'": ("1", "Sing"), "te": ("2", "Sing"), "t'": ("2", "Sing"),
                    "se": ("3", None), "s'": ("3", None), "nous": ("1", "Plur"), "vous": ("2", None)}
    clitic_of = {"l'": "le", "la": "le", "les": "le", "j'": "je", "m'": "me", "t'": "te", "s'": "se",
                 "c'": "ce"}
    verb_endings = ("er", "ir", "re", "ïr")
    function_verbs = {"être", "avoir"}

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS + SEASONS] + [(w, "NUM") for w in NUMBERS] +
                     [(w, "ADJ") for w in COLOURS + NATIONALITIES] +
                     [("oui", "INTJ"), ("non", "INTJ"), ("bonjour", "INTJ"), ("bonsoir", "INTJ"),
                      ("merci", "INTJ"), ("pardon", "INTJ"), ("salut", "INTJ"), ("petit déjeuner", "NOUN"), ("y", "PRON"), ("leur", "PRON"),
                      ("s'il vous plaît", "PHRASE"), ("au revoir", "PHRASE"), ("il y a", "PHRASE"),
                      ("est-ce que", "PHRASE"), ("excusez-moi", "PHRASE"), ("s'il te plaît", "PHRASE"),
                      ("ça", "PRON"), ("cet", "DET"), ("eux", "PRON"), ("voilà", "INTJ"), ("voici", "INTJ"),
                      ("et", "CONJ"), ("ou", "CONJ"), ("à", "ADP"), ("de", "ADP"), ("en", "ADP")])
    no_article = set(DAYS + MONTHS) | {"madame", "mademoiselle", "monsieur"}   # titles
    allowed_num = set(NUMBERS)
    fixed_gloss = {
        ("le", "DET"): "the (le, la, l', les)", ("un", "DET"): "a, an (un, une)",
        ("s'il vous plaît", "PHRASE"): "please", ("au revoir", "PHRASE"): "goodbye",
        ("il y a", "PHRASE"): "there is, there are; ago", ("est-ce que", "PHRASE"): "(question marker: is it that ...?)",
        ("excusez-moi", "PHRASE"): "excuse me", ("s'il te plaît", "PHRASE"): "please (informal)",
        ("cet", "DET"): "this, that (ce, cet, cette, ces)", ("enceinte", "ADJ"): "pregnant",
        ("eux", "PRON"): "them (stressed: avec eux, chez eux)",
        ("y", "PRON"): "there; about it, to it (j'y pense: I think about it)",
        ("leur", "PRON"): "(to) them (je leur parle: I speak to them)",
    }
    fixed_word = {("le", "DET"): ("le", ["la", "l'", "les"]),
                  ("un", "DET"): ("un", ["une"])}
    multiword = {"s'il vous plaît": ("s'il", "vous", "plaît"), "au revoir": ("au", "revoir"),
                 "il y a": ("il", "y", "a"), "est-ce que": ("est-ce", "que"), "excusez-moi": ("excusez", "moi"),
                 "s'il te plaît": ("s'il", "te", "plaît")}
    phrase_absorbs_parts = True        # "il y a" links the phrase, not avoir
    homograph_by_translation = True    # les morts "the dead" links mort (adj), not la mort
    strict_selection = True
    revert_dedupe_gloss = True
    strict_pronominal_links = True
    example_shows_word = True     # one example shows vouloir / l'an itself, not only veux / ans
    # kept to B1 (sex, drugs, suicide, rape, terrorism, torture); violence is only avoided (sentence_rank)
    sensitive_re = re.compile(
        r"\b(sexe|sexuel\w*|sexy|suicid\w*|porno\w*|prostitu\w*|préservatif\w*|drogu\w*|nue?s?|"
        r"viol|viols|viol(er|é|ée|és|ées|ait|ent|eur\w*|ons|ez|era\w*)|"
        # threats and violence (cross-pack policy): tuer in any form (never
        # the pronoun tu), meurtre, assassiner, tirer sur, "t'es mort"
        r"tu(er|e|es|ent|é|ée|és|ées|ons|ez|ait|aient|ais|a|âmes|èrent|era\w*|erai\w*|ant)|"
        r"meurtr\w*|assassin\w*|poignard\w*|étrangl\w*|fusill\w*|tueur\w*|tueuse\w*|"
        # death and weapons (re-QA v2): mourir in every form, arme, frapper,
        # coups, crever, gueule, sang, pistolet, couteau
        r"mour(ir|ais|ait|ions|iez|aient|ant|ra\w*|rai\w*|us|ut|ûmes|urent|ût)|meur(s|t|e|es|ent)|"
        r"morte?s?|armes?|frapp\w*|coups?|crev\w*|gueules?|sang|pistolet\w*|fusils?|couteaux?|"
        r"se suicid\w*|bless(é|ée|és|ées|er|ure\w*)|"
        r"tir(er|e|es|ent|é|ez|ons|ait|aient|era\w*) sur|"
        r"(t'es|tu es|vous êtes|il est|t'êtes) (un homme )?mort|te (veux|voudrais) mort|"
        + SENSITIVE_EN + r"|die|dies|died|dying|weapons?|guns?|knife|knives|serial killer)\b", re.I)
    # removed at every level: rape, sexual/child abuse
    drop_all_levels = re.compile(
        r"\b(viol|viols|viol(er|é|ée|és|ées|ait|aient|ent|eur\w*|era\w*)"
        r"(?! (la|les|une|un|ses|son|sa|leur|leurs|cette|ce|des|nos|vos|l')\s?(loi|lois|règle\w*|contrat\w*|"
        r"promesse\w*|accord\w*|traité\w*|droit\w*|frontière\w*|espace|secret\w*|domicile|intimité|vie privée))|abus sexuels?|abus(é|ée) sexuellement|"
        r"attouchements?|pédophil\w*|inceste|"
        r"rape[ds]?|raping|rapist\w*|molest\w*|child abuse|sexual(?:ly)? abuse\w*|paedophil\w*|pedophil\w*)\b",
        re.I)
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)   # vulgar senses never lead
    lower_level_gloss_re = re.compile(r"\b(" + SENSITIVE_EN + r"|die|dies|died|dying|weapons?|guns?)\b", re.I)
    # tokens of these (lemma, group) keys link to the forced entry instead
    drop_keys = {("non", "ADV"): ("non", "INTJ"), ("oui", "ADV"): ("oui", "INTJ"),
                 ("baiser", "VERB"): None,                   # vulgar in modern use (le baiser "kiss" stays)
                 # names and fillers read as words: "Ben", "Al Jazeera"; "ca" (ça) read as circa
                 ("ben", "NOUN"): None, ("ben", "ADV"): None, ("al", "PRON"): None, ("circa", "ADP"): None,
                 # unassimilated English loans (informal register): the brief excludes loanwords
                 ("party", "NOUN"): None, ("job", "NOUN"): None, ("fan", "NOUN"): None, ("star", "NOUN"): None,
                 ("cool", "ADJ"): None, ("sexy", "ADJ"): None, ("ok", "ADV"): None, ("ok", "INTJ"): None,
                 ("super", "ADV"): ("super", "ADJ"),
                 ("fait", "ADJ"): ("faire", "VERB"),
                 ("gay", "NOUN"): None, ("gay", "ADJ"): None,
                 ("compris", "ADJ"): ("comprendre", "VERB")}        # participle of faire, not its own adjective
    # a nationality noun (le français "French language") links to the forced adjective
    drop_keys.update({(n, "NOUN"): (n, "ADJ") for n in NATIONALITIES})
    profane_stems = ("connard", "connass", "putain", "salop", "encul", "emmerd", "branl", "enfoir",
                     "niqu", "chiant", "foutr", "foutu", "pédé")
    profanity = {"merde", "bordel", "foutre", "foutu", "chier", "bite", "couille", "couilles", "pute",
                 "con", "conne", "cul", "salaud", "salope", "bâtard", "nique", "niquer", "putain",
                 "enculé", "connard", "chiant", "emmerder", "merdique", "flic", "bouffer", "connerie",
                 "bite", "zizi", "nichon", "baise", "pisser"}
    bad_text_re = re.compile(r"\b(putain|merde|connard|connasse|salope|salaud|encul\w*|bordel|niqu\w*|foutre|"
                             r"chier|pute|bite|couilles?|emmerd\w*|branl\w*|enfoiré\w*|con|conne|conneries?|pisse\w*)\b"
                             # interrogative/copula agreement errors in Tatoeba ("Quelle sont votre taille")
                             r"|\b(quelle|quel) sont\b|\b(quels|quelles) est\b|\b(quelle|quel)s? (étaient|seront)\b"
                             r"|\b(quels|quelles) (était|sera)\b|\bce sont (un|une)\b|\bil sont\b|\bils est\b"
                             r"|\belle sont\b|\belles est\b|\bnous est\b|\bvous est\b|\bje suis allés\b", re.I)

    report_title = "French A1-B1 pack (v1, corpus-tagged)"
    forced_description = ("days, months, seasons, numbers 0-20 + tens + cent/mille, colours, nationalities, "
                          "greetings, et/ou/à/de/en, A1 core list")
    numeral_exclusion = "numeral outside 0-20/tens/100/1000"
    article_pool_note = "; articles le/un kept alongside"
    marked_past_name = "Passé simple"
    uses_historic_past_forms = False   # je finis/dis/vis are present and passé simple alike

    h_aspire_file = "tools/h_aspire.txt"

    def __init__(self, repo=None):
        super().__init__(repo)
        self.h_aspire = set()
        self._lx = None
        self._lp_cache = {}

    def load(self):
        super().load()
        p = self.repo / self.h_aspire_file
        if p.exists():
            self.h_aspire = {w.strip() for w in p.read_text().split() if w.strip()}
        return self

    # ---- tagging -----------------------------------------------------------
    def tag_text(self, text):
        return text.replace("’", "'").replace(" ", " ").replace(" ", " ")

    def setup_nlp(self, nlp):
        """Split every hyphen-attached clitic (peux-tu, lève-toi, dis-le-moi),
        which the stock suffix rule does only for some pronouns; keep a few
        compounds whole."""
        from spacy.symbols import ORTH
        from spacy.util import compile_suffix_regex
        tok = nlp.tokenizer
        alpha = "A-Za-zÀ-ÖØ-öø-ÿŒœÆæ"
        cl = sorted(HYPHEN_CLITIC)
        pat = r"(?<=[%s])[-‐](?:%s)$" % (alpha, "|".join(cl + [c.upper() for c in cl]))
        tok.suffix_search = compile_suffix_regex(list(nlp.Defaults.suffixes) + [pat]).search
        tok.token_match = HyphenCliticTokenMatch(tok.token_match)
        for w in KEEP_WHOLE:
            for v in {w, w[0].upper() + w[1:]}:
                tok.add_special_case(v, [{ORTH: v}])

    def fix_token(self, tok):
        """Hyphen-attached clitics are PRON whatever the tagger said (it has no
        "-toi" in training); the bare hyphen and euphonic -t- are punctuation."""
        text, lemma, upos, ms = tok
        t = text.lower()
        if t in HYPHEN_SKIP:
            return [text, t, "PUNCT", ""]
        if self.is_hyphen_clitic(t):
            lem, g = HYPHEN_CLITIC[t[1:]]
            return [text, lem, "ADV" if g == "ADV" else "PRON", ms]
        return tok

    def fix_sentence(self, toks, row, doc):
        """Determiners the tagger left without Gender get it from their form
        (son poste is masculine), so a noun links only to the entry of its
        gender (le poste "job" is not la poste "post office")."""
        for i, (text, lemma, upos, ms) in enumerate(toks):
            t = text.lower()
            if upos not in ("DET", "ADP") or "Gender=" in ms:
                continue
            g = None
            if t in FEM_DET:
                g = "Fem"
            elif t in MASC_DET:
                nxt = toks[i + 1][0].lower() if i + 1 < len(toks) else ""
                if t in ("mon", "ton", "son") and nxt and self.elides(nxt):
                    continue            # mon amie: masculine form before a vowel
                g = "Masc"
            if g:
                toks[i] = [text, lemma, upos, f"Gender={g}" + ("|" + ms if ms else "")]
        return toks

    # ---- resolution --------------------------------------------------------
    def bind_lexicon(self, lexicon):
        """Adjust the loaded Wiktionary lexicon:
        - feminine nouns with a masculine counterpart in their head template
          (amie m=ami, chanteuse m=chanteur) get a "female equivalent of" form
          line, so the core folds them into the masculine entry when the
          glosses agree;
        - a feminine noun with its own entry and a sense unrelated to the
          masculine noun (la droite "straight line; right-hand side" vs le droit
          "law") loses the adjective line "feminine singular of droit", so it
          never folds into the masculine through a shared English word;
        - reflexive/pronominal senses of a verb that also has other senses
          rank after them (briser "to break" before "to become broken"); the
          pronominal display still uses them;
        - post-1990 spellings (connaitre, boite) point to the traditional one."""
        self._lx = lexicon
        E = lexicon.E
        for word, gl in SUPPLETIVE.items():
            for e in E.get(word, []):
                if e["p"] == "adj":
                    e["s"] = [[gl, "", ["comparative"], ""]] + [sn for sn in e["s"] if sn[3] != "form"]
            lexicon.F.pop(word, None)
        for word, ents in E.items():
            for e in ents:
                g = e.get("g") or ""
                if "|m=" in g:
                    masc = g.split("|m=", 1)[1]
                    if masc != word and not any(sn[3] == "form" for sn in e["s"]):
                        e["s"].append([f"female equivalent of {masc}", "", ["form-of"], "form"])
                defs = [sn for sn in e["s"] if sn[3] == ""]
                marked = [sn for sn in defs if MARKED_SENSE_TAGS & set(sn[2])]
                plain = [sn for sn in defs if not NOT_PLAIN_TAGS & set(sn[2]) and not USAGE_NOTE_RE.match(sn[0])]
                if marked and plain:
                    # figurative / colloquial / slang senses rank after plain ones
                    # (blesser "to wound" before "to hurt one's feelings")
                    for sn in marked:
                        if "rare" not in sn[2]:
                            sn[2] = sorted(set(sn[2]) | {"rare"})
                if e["p"] == "verb":
                    refl = [sn for sn in defs if {"reflexive", "pronominal"} & set(sn[2])]
                    if refl and len(refl) < len(defs):
                        for sn in refl:
                            if "rare" not in sn[2]:
                                sn[2] = sorted(set(sn[2]) | {"rare"})
                for sn in e["s"]:
                    # the core reads "tree (..., anything in the form of a
                    # tree)" as a form-of line: untagged, it is a definition
                    if sn[3] == "form" and "form-of" not in sn[2] and IN_THE_FORM_RE.search(sn[0]):
                        sn[3] = ""
                    # sense groups: the parent line carries the translation
                    # ("field in its various senses, including:" / "a vector
                    # field..."; "attempt, try, effort" / "general senses")
                    if sn[3] == "" and sn[1]:
                        mg = GROUP_HEAD_RE.match(sn[1])
                        child = re.sub(r"^(a|an|the) ", "", re.sub(r"\s*\(.*?\)", "", sn[0])).strip(" .")
                        head = re.sub(r"\s*\(.*?\)", "", sn[1]).strip(" .:")
                        if META_SENSE_RE.match(sn[0]):
                            sn[0] = mg.group(1) if mg else sn[1]
                        elif mg:
                            # "a chamber in its various senses" / "a room": keep
                            # a short child; a definitional one takes the head
                            if len(child.split()) >= 3:
                                sn[0] = mg.group(1)
                        elif len(head.split()) <= 3 and not head.lower().startswith(("used", "inflection")):
                            sn[0] = sn[1]            # "to verify" / "to confirm": the head translates
                    if sn[3] == "":
                        tags = set(sn[2])
                        if "France" in tags and tags & self.regional_tags:
                            # a sense used in France is standard even if other
                            # regions share it (déjeuner "lunch": France, Africa...)
                            sn[2] = sorted(tags - self.regional_tags)
                    m = REFORM_RE.match(sn[0]) if sn[3] == "" else None
                    if m and self.lex_word_re.match(m.group(1)):
                        sn[3] = "alt"
                        lexicon.F.setdefault(word, [])
                        if [m.group(1), e["p"], "alt"] not in lexicon.F[word]:
                            lexicon.F[word].append([m.group(1), e["p"], "alt"])
        for word, ents in E.items():
            nouns = [e for e in ents if e["p"] == "noun" and (e.get("g") or "").split("|")[0] == "f"
                     and "|m=" not in (e.get("g") or "")]
            if not nouns:
                continue
            for e in ents:
                if e["p"] != "adj":
                    continue
                for sn in e["s"]:
                    m = FEM_ADJ_RE.match(sn[0]) if sn[3] == "form" else None
                    if not m:
                        continue
                    masc_words = {w for me in E.get(m.group(1), []) if me["p"] == "noun"
                                  for s2 in me["s"] if s2[3] == "" for w in _content_words(s2[0])}
                    own = [_content_words(s2[0]) for ne in nouns for s2 in ne["s"] if s2[3] == ""]
                    if masc_words and any(ws and not (ws & masc_words) for ws in own):
                        sn[0] = "inflection (feminine singular) " + m.group(1)

    def gender_from_entry(self, d):
        """fr-noun gender, plus "|m=<masculine>" when the head names one."""
        g = super().gender_from_entry(d)
        if d.get("pos") == "noun" and d.get("word") in MAJORITY_GENDER and g:
            return MAJORITY_GENDER[d["word"]]    # le tour / la tour: the corpus-majority gender
        for ht in d.get("head_templates", []):
            if ht.get("name") == "fr-noun":
                m = str(ht.get("args", {}).get("m", "")).split("<")[0]
                if m and m != "+" and self.lex_word_re.match(m) and g and "f" in g and "m" not in g:
                    return f"{g}|m={m}"
        return g

    def parse_gender(self, g):
        """A plain "mf" (not "mfbysense": amour, bus) is a gender that varies by
        region or number, not a common-gender noun: the corpus decides."""
        g = g.split("|", 1)[0] if g else g
        if g in ("mf", "mf-s"):
            return None, False
        return super().parse_gender(g)

    def fold(self, s):
        """Frequency-list spellings: oe for œ (coeur), wordfreq's elisions
        without the apostrophe (l, c, qu), quelqu' (split from quelqu'un)."""
        if s in ELISION_LETTERS:
            return s + "'"
        if s == "quelqu'":
            return "quelqu'un"
        return OE_FOLD.get(s, s)

    def accent_candidates(self, s):
        if s == "ca":
            return ["ça"]
        return super().accent_candidates(s)

    def is_hyphen_clitic(self, text):
        t = text.lower()
        return t[:1] in "-‐" and t[1:] in HYPHEN_CLITIC

    def _elided(self, s, upos, toks, i):
        if s == "t'" and i + 1 < len(toks) and toks[i + 1][0].lower() in T_TU_NEXT:
            return ("tu", "PRON")                  # t'as, t'es: colloquial tu
        if s in ELIDED:
            return ELIDED[s]
        if s == "l'":
            nxt = toks[i + 1][2] if i + 1 < len(toks) else ""
            if upos == "PRON":
                return ("le", "PRON")
            if nxt in ("VERB", "AUX"):
                if i == 0 or toks[i - 1][2] == "PUNCT":
                    return ("le", "DET")                 # "L'offre ...": sentence-initial article
                pl = toks[i - 1][0].lower()
                if pl in SUBJ_PRON or pl in OBJ_CLITICS or toks[i - 1][2] in ("VERB", "AUX"):
                    return ("le", "PRON")                # "il l'offre", "je veux l'offrir"
                nx = toks[i + 1][0].lower()
                has_noun = bool(self._lx and self._lx.candidates(nx, ["noun"]))
                return ("le", "DET" if has_noun else "PRON")
            return ("le", "DET")
        if s == "qu'":
            return ("que", "PRON" if upos == "PRON" else "CONJ")
        if s == "s'":
            nxt = toks[i + 1][0].lower() if i + 1 < len(toks) else ""
            return ("si", "CONJ") if nxt in ("il", "ils") else ("se", "PRON")
        return None

    def _mwe(self, toks, out):
        """Multiword expressions read as one word on their anchor token (the
        rest skipped): parce que, quelque chose, d'abord, tout le monde..."""
        low = [t[0].lower() for t in toks]
        n = len(toks)
        done = set()
        for i in range(n):
            for parts, lemma, group, anchor in MWES:
                k = len(parts)
                if i + k > n or any(low[i + j] not in parts[j] for j in range(k)):
                    continue
                if lemma == "en fait" and toks[i][2] != "ADP":
                    continue             # "il en fait": pronoun en + verb
                for j in range(k):
                    if low[i + j] in ("n'", "ne") and j != anchor:
                        continue         # "il n'y a pas": ne keeps its own link
                    # a sentence-initial part gets the expression too: the core
                    # links a capitalised initial pack word it cannot resolve
                    # ("Tout le monde..." must not also link tout)
                    initial = i + j == 0 or toks[i + j - 1][2] == "PUNCT"
                    out[i + j] = (lemma, group) if initial else None
                    done.add(i + j)
                out[i + anchor] = (lemma, group)
                break
        for i in range(n):
            for parts, skip in IDIOM_UNLINK:
                k = len(parts)
                if i + k <= n and all(low[i + j] in parts[j] for j in range(k)):
                    out[i + skip] = None
                    done.add(i + skip)
        return done

    def post_resolve(self, toks, out):
        """French context rules on top of the core resolution:
        elided forms (j' -> je, s'il -> si), hyphen-attached clitics (-moi ->
        moi, euphonic -t- skipped), multiword expressions, and tagger repairs:
        a verb before a hyphen clitic (peux-tu), a noun right after a subject
        pronoun (tu restes), a bare noun after a copula that has an adjective
        reading (c'est drôle), personne without a determiner in a negative
        clause (nobody), possessive pronouns (la tienne is not tenir)."""
        lx = self._lx
        out = list(out)
        n = len(toks)
        low = [t[0].lower() for t in toks]
        done = self._mwe(toks, out)
        has_neg = any(x in ("ne", "n'") for x in low)
        for i, (text, sl, upos, ms) in enumerate(toks):
            if i in done:
                continue
            s = low[i]
            if s in HYPHEN_SKIP:
                out[i] = None
                continue
            if self.is_hyphen_clitic(s):
                out[i] = HYPHEN_CLITIC[s[1:]]
                continue
            if s == "l'" and i + 1 < n and low[i + 1] in ("un", "une") and \
                    toks[i + 1][2] in ("PRON", "NUM", "ADJ"):
                out[i] = None            # "l'une de mes amies": the pronoun l'un, not the article
                continue
            e = self._elided(s, upos, toks, i)
            if e:
                out[i] = e
                continue
            if s in OE_FOLD:
                out[i] = lx.resolve(OE_FOLD[s], sl, upos, ms) if lx is not None else out[i]
                continue
            if s in SURFACE_FIXED:
                out[i] = SURFACE_FIXED[s]
                continue
            if s in DET_PARADIGM and (upos == "DET" or (i + 1 < n and toks[i + 1][2] in ("NOUN", "ADJ") and
                                                         not (i > 0 and toks[i - 1][2] == "DET"))):
                out[i] = (DET_PARADIGM[s], "DET")      # cette -> ce, sa -> son: one entry per paradigm
                continue
            if lx is None:
                continue
            if s == "soit" and not (i + 1 < n and self.is_hyphen_clitic(low[i + 1])) and \
                    not any(x in ("que", "qu'") for x in low[max(0, i - 3):i]):
                out[i] = ("soit", "CONJ")                # "Soit ... soit", "soit dit": not être
                continue
            if i >= 3 and low[i - 3:i - 1] == ["en", "train"] and low[i - 1] in ("de", "d'") and \
                    s in lx.verbs_only(lx.candidates(s, ["verb"])):
                out[i] = (s, "VERB")                     # "en train de rire": the infinitive
                continue
            prev = low[i - 1] if i else ""
            if (i and low[i - 1] in ("-", "‐")) or (i + 1 < n and low[i + 1] in ("-", "‐")):
                out[i] = None            # part of a split hyphen compound (coffre-fort)
                continue
            if s in POSS_PRON and prev in ("le", "la", "les", "l'"):
                out[i] = None            # le mien / la tienne: no pack entry, never tenir
                continue
            r = out[i]
            if i + 1 < n and self.is_hyphen_clitic(low[i + 1]) and (r is None or r[1] != "VERB"):
                c = lx.verbs_only(lx.candidates(s, ["verb"]))
                if c:
                    out[i] = (lx.best_by_freq(c), "VERB")
                continue
            if r is None:
                continue
            nxt_up = toks[i + 1][2] if i + 1 < n else "PUNCT"
            if r[1] in ("VERB", "ADJ") and r[0] != s:
                a = lx.candidates(s, ["adj"])
                al = lx.best_by_freq(a) if a else None
                if al is None:           # désolée/désolés: listed only as participle forms
                    al = next((s[:-len(suf)] for suf in ("es", "e", "s")
                               if s.endswith(suf) and lx.usable_entries(s[:-len(suf)], ["adj"])), None)
                if al and al != r[0] and lx.zipf(al) >= lx.zipf(r[0]) + 1.5:
                    out[i] = (al, "ADJ")  # désolé(e), not désoler: the verb lemma is barely used
                    continue
            j = i - 1
            if j >= 1 and toks[j][2] == "ADJ":
                j -= 1                   # "un joyeux sourire"
            if r[1] == "VERB" and j >= 0 and j < i and \
                    (toks[j][2] == "DET" or (out[j] is not None and out[j][1] == "DET")) and \
                    low[j] not in ("tout", "tous", "toute", "toutes") and \
                    not (j >= 1 and (low[j - 1] in SUBJ_PRON or low[j - 1] in OBJ_CLITICS)) and \
                    (prev in DEM_POSS_DET or j < i - 1 or low[j] in ARTICLES):
                c = lx.candidates(s, ["noun"])
                if c:
                    out[i] = (lx.best_by_freq(c), "NOUN")      # "Ma montre": the noun
                    continue
            if r[1] == "ADJ" and i >= 2 and out[i - 1] is not None and out[i - 1] == (out[i - 1][0], "ADJ") and \
                    out[i - 1][0] in PRENOMINAL_ADJ and (low[i - 2] in ARTICLES or low[i - 2] in DEM_POSS_DET):
                c = lx.candidates(s, ["noun"])
                if c:
                    out[i] = (lx.best_by_freq(c), "NOUN")      # "une nouvelle politique": the noun
                    continue
            if r[1] == "ADJ" and prev in ARTICLES and r[0] not in DET_LIKE_ADJ and \
                    not (r[0] in PRENOMINAL_ADJ and nxt_up == "ADJ" and lx.candidates(low[i + 1], ["noun"])) and \
                    ((nxt_up == "ADJ" and (i + 2 >= n or toks[i + 2][2] != "NOUN")) or
                     nxt_up in ("PUNCT", "ADP", "CCONJ")):
                c = lx.candidates(s, ["noun"])
                if c:
                    out[i] = (lx.best_by_freq(c), "NOUN")      # "La logique féminine"
                    continue
            if r[1] == "NOUN" and i and toks[i - 1][2] == "NOUN" and text[:1].islower():
                a = lx.candidates(s, ["adj"])
                if a:
                    out[i] = (lx.best_by_freq(a), "ADJ")       # "des questions bêtes"
                    continue
            if r == ("voir", "VERB") and s in ("vis", "vit") and i + 1 < n and \
                    (low[i + 1] in VIVRE_NEXT or nxt_up in ("ADV", "ADP", "ADJ", "PUNCT")) and \
                    not self.marks_sentence(toks):
                out[i] = ("vivre", "VERB")
                continue
            if r[1] == "ADJ":
                j = i - 1
                while j >= 0 and (toks[j][2] == "ADV" or low[j] in ("ne", "n'", "pas")):
                    j -= 1
                if j >= 0 and out[j] == ("avoir", "VERB"):
                    c = lx.verbs_only(lx.candidates(s, ["verb"]))
                    if c:
                        out[i] = (lx.best_by_freq(c), "VERB")   # "il a compris": the participle
                        continue
            if s == "personne" and has_neg and prev not in NOMINAL_BEFORE and \
                    (not i or toks[i - 1][2] not in ("DET", "ADJ", "NUM")):
                out[i] = ("personne", "PRON")
                continue
            if r[1] in ("NOUN", "ADJ") and (i == 0 or toks[i - 1][2] == "PUNCT") and i + 1 < n and \
                    (toks[i + 1][2] == "PUNCT" or low[i + 1] in ("moi", "-moi", "bien", "donc") or
                     ((toks[i + 1][2] in ("DET", "ADV", "PRON", "ADP") or low[i + 1] in DET_PARADIGM or
                       low[i + 1] in ARTICLES) and
                      not any(t[2] in ("VERB", "AUX") for t in toks[i + 1:clause_end(toks, i)]))):
                v = lx.imperative_form(s)
                if v:
                    out[i] = (v, "VERB")         # "Écoute ton cœur", "Ferme doucement la porte": imperative
                    continue
            if r[1] == "NOUN" and i + 1 < n and (toks[i + 1][2] == "NOUN" or lx.candidates(low[i + 1], ["noun"])) \
                    and toks[i + 1][2] not in ("VERB", "AUX", "ADP", "PUNCT") and i > 0 and \
                    (toks[i - 1][2] == "DET" or low[i - 1] in DEM_POSS_DET):
                a = lx.candidates(s, ["adj"])
                al = lx.best_by_freq(a) if a else None
                if al in PRENOMINAL_ADJ:
                    out[i] = (al, "ADJ")         # "une nouvelle politique": nouveau, not la nouvelle
                    continue
            if r[1] == "NOUN" and s not in AVOIR_IDIOM_NOUNS:
                # a verb form read as its noun homograph: a past participle after an
                # auxiliary ("sont partis", "l'ai prise", "es-tu revenu") or tagged
                # Part, a verb form after ne or a reflexive clitic ("n'écoute",
                # "se plante", "se couche"): the verb, never the noun
                j = i - 1
                while j >= 0 and (self.is_hyphen_clitic(low[j]) or low[j] in OBJ_CLITICS - {"ne", "n'"} or
                                  low[j] in ("pas", "jamais", "plus", "déjà", "bien", "toujours")):
                    j -= 1
                prev1 = low[i - 1] if i else ""
                part = "VerbForm=Part" in (ms or "") or self._past_participle(s)
                if (part and j >= 0 and low[j] in AUX_FORMS) or prev1 in ("ne", "n'", "se", "s'", "me", "m'", "te", "t'") or \
                        ("VerbForm=Part" in (ms or "")):
                    v = self._verb_of(s)
                    if v:
                        out[i] = (v, "VERB")
                        continue
            if r[1] == "NOUN":
                j = i - 1
                while j >= 0 and low[j] in OBJ_CLITICS:
                    j -= 1
                if j >= 0 and (low[j] in SUBJ_PRON or (low[j] in ("nous", "vous") and
                                                        (j == 0 or toks[j - 1][2] == "PUNCT"))):
                    c = lx.verbs_only(lx.candidates(s, ["verb"]))
                    out[i] = (lx.best_by_freq(c), "VERB") if c else None   # "Je peine": never the noun
                    continue
                j = i - 1
                while j >= 0 and toks[j][2] == "ADV":
                    j -= 1
                if j >= 0 and out[j] is not None and out[j][1] == "VERB" and out[j][0] in self.copulas \
                        and s not in PREDICATE_NOUNS:
                    a = lx.candidates(s, ["adj"])
                    if a:
                        out[i] = (lx.best_by_freq(a), "ADJ")
        return out

    # ---- finishing ----------------------------------------------------------
    def _tidy(self, text, pos):
        """One gloss segment: drop definitional tails after the first
        alternative ("eye, helping organisms to see", "water, a liquid that
        is transparent"), stray brackets, dangling words; verbs get "to"."""
        text = text.replace("[", "").replace("]", "").strip()
        text = TAIL_CUT_RE.split(text)[0].strip()
        if re.match(r"^(se |s')\S+:", text):
            return text                      # "s'occuper: to take care of"
        parts = [p.strip() for p in text.split(",") if p.strip()]
        keep = []
        for k, p in enumerate(parts):
            words = p.split()
            if k and (DEFN_PART_RE.search(p) or len(words) > 4 or
                      (len(words) > 1 and words[0] in ("a", "an") and k)):
                continue
            p = re.sub(r"^(especially|usually|often|chiefly|also as form of address:)\s+", "", p)
            p = re.sub(r"\s+(or|and|the|a|an)$", "", p)
            if len(p.split()) > 4 and " or " in p:
                a, b = p.split(" or ", 1)
                p = a if len(b.split()) > 2 else f"{a}, {b}"
            p = re.sub(r"^(a|an) (?!(lot|little|bit|few)\b)", "", p) if len(p.split()) <= 5 else p
            if pos == "verb" and not p.startswith("to ") and not VERB_GLOSS_KEEP.match(p):
                p = "to " + p
            if p and p not in keep:
                keep.append(p)
        return ", ".join(keep) if keep else text

    def finalize_words(self, env, ctx, words):
        """Gloss tidying (see _tidy) for every word without a hand/fixed gloss;
        a reverted pronominal gloss whose two halves agree keeps one ("to rest;
        se reposer: to rest" -> "to rest"); nouns in PLURAL_DISPLAY are shown
        in the plural (les vacances)."""
        fixed = {f"{k[0]}|{k[1].lower()}" for k in self.fixed_gloss}
        for w in words:
            key = f"{w['_key'][0]}|{w['pos']}"
            if key in self.gloss_overrides or w["_key"] in self.fixed_gloss or w["pos"] in ("art", "phrase"):
                continue
            en = w["en"]
            m = re.search(r" \((m|f|m/f|pl\.)\)$", en)
            tail = m.group(0) if m else ""
            body = en[: len(en) - len(tail)]
            segs = [x.strip() for x in body.split(";") if x.strip()]
            if len(segs) == 2 and ":" in segs[1]:
                refl, rgl = segs[1].split(":", 1)
                if rgl.strip().split(",")[0].strip() == segs[0].split(",")[0].strip():
                    segs = [segs[0]]
            segs = [self._tidy(x, w["pos"]) for x in segs]
            w["en"] = "; ".join(segs) + tail
        for w in words:
            if w["pos"] == "det" and w["lemma"] in DET_ALTS:
                shown, alts = DET_ALTS[w["lemma"]]
                w["lemma"], w["w"] = shown, shown
                w["alt"] = [a for a in alts if a != shown]
            if w["pos"] == "pron" and w["lemma"] in PRON_ALTS:
                w["alt"] = list(PRON_ALTS[w["lemma"]])      # le: la, les (same paradigm convention as DET_ALTS)
            if w["pos"] == "verb" and w["lemma"] in ALWAYS_PRONOMINAL:
                base = w["lemma"]
                w["lemma"] = w["w"] = self.pronominal_form(base)
                w["alt"] = [base]
                w["en"] = re.sub(r";\s*(se |s')\S+:\s*", "; ", w["en"])
        for w in words:
            # the core's pronominal revert rebuilds a verb gloss from the
            # pre-override base sense: a hand override wins
            ov = self.gloss_overrides.get(f"{w['_key'][0]}|verb") if w["pos"] == "verb" else None
            if ov and not self.pronominal_base(w["lemma"]):
                w["en"] = ov
        self._append_reflexive_senses(ctx, words)
        for w in words:
            pl = PLURAL_DISPLAY.get(w["lemma"])
            if w["pos"] == "noun" and pl:
                w["lemma"], w["w"] = pl, f"les {pl}"
                w["alt"] = [pl] + [a for a in (w.get("alt") or []) if a != pl]
                w["en"] = re.sub(r" \((m|f|m/f)\)$", "", w["en"]) + ("" if w["en"].endswith("(pl.)") else " (pl.)")

    def _reflexive_sense(self, base):
        """First translation-like sense of se <base>: its own entry, else the
        base entry's reflexive/pronominal senses."""
        lx = self._lx
        for e in lx.usable_entries(self.pronominal_form(base), ["verb"]):
            for sn in e["s"]:
                if sn[3] == "" and sn[0].startswith("to ") and not (NOT_PLAIN_TAGS - {"rare"}) & set(sn[2]):
                    return sn[0]
        for e in lx.usable_entries(base, ["verb"]):
            for sn in e["s"]:
                if sn[3] == "" and {"reflexive", "pronominal"} & set(sn[2]) and sn[0].startswith("to ") and \
                        not (NOT_PLAIN_TAGS - {"rare"}) & set(sn[2]):
                    return sn[0]
        return None

    def _append_reflexive_senses(self, ctx, words):
        """A plain verb whose corpus uses often carry a reflexive clitic gets
        the se-sense appended (appeler "to call; s'appeler: to be called")."""
        refl = ctx.get("refl") or {}
        stative = refl.get("_stative", {}) if refl else {}
        raw = ctx.get("raw_upos") or {}
        added = []
        for w in words:
            if w["pos"] != "verb" or self.pronominal_base(w["lemma"]) or ":" in w["en"] or \
                    re.search(r"\b(se |s')", w["en"]):
                continue
            k = w["_key"]
            active = sum(raw.get(k, {}).values()) - stative.get(k, 0)
            r = refl.get(k, 0)
            hand = REFL_SENSE.get(w["lemma"])
            if r < 5 or (not hand and (active < 10 or r / active < REFLEXIVE_SENSE_SHARE)):
                continue
            sense = hand or self._reflexive_sense(w["lemma"])
            if not sense:
                continue
            if not hand:
                sense = self._tidy(re.split(r"[;,](?![^(]*\))", sense)[0].strip(), "verb")
                if "(" in sense and ")" not in sense:
                    sense = sense.split("(")[0].strip()
            if sense.lower() in w["en"].lower():
                continue
            if w["lemma"] == "aller":
                sense = "to go away"
            form = REFL_FORM.get(w["lemma"]) or self.pronominal_form(w["lemma"])
            w["en"] = f"{w['en']}; {form}: {sense}"
            added.append(w["lemma"])
        self._reflexive_senses_added = added

    # ---- morphology hooks ----------------------------------------------------
    def elides(self, w):
        """Article elides before this word: vowel or mute h."""
        f = w[:1]
        return f in VOWELS or (f == "h" and w not in self.h_aspire)

    def pronominal_base(self, lemma):
        if lemma.startswith("se "):
            return lemma[3:]
        if lemma.startswith("s'"):
            return lemma[2:]
        return None

    def pronominal_form(self, lemma):
        return ("s'" + lemma) if self.elides(lemma) else ("se " + lemma)

    @staticmethod
    def _morph(ms):
        return dict(kv.split("=", 1) for kv in ms.split("|") if "=" in kv)

    SUBJECTS = {"je": ("1", "Sing"), "j'": ("1", "Sing"), "tu": ("2", "Sing"), "il": ("3", "Sing"),
                "elle": ("3", "Sing"), "on": ("3", "Sing"), "nous": ("1", "Plur"), "vous": ("2", None),
                "ils": ("3", "Plur"), "elles": ("3", "Plur")}
    SKIP_BETWEEN = {"ne", "n'", "y", "en", "le", "la", "les", "l'", "lui", "leur"}

    def _refl(self, toks, i, strict):
        """Verb token i carries a reflexive clitic: before it or its auxiliary
        ("je me lève", "il s'est levé", "ne s'en souvient", "vais me coucher"),
        or hyphen-attached after an imperative ("lève-toi", "asseyez-vous")."""
        text, sl, upos, ms = toks[i]
        question = any(t[0] == "?" for t in toks[i + 1:])
        if i + 1 < len(toks) and self.is_hyphen_clitic(toks[i + 1][0]):
            cl = toks[i + 1][0].lower()[1:]
            if cl == "toi":
                return True
            if cl in ("vous", "nous") and not question:
                m = self._morph(ms)
                return m.get("Person") in (None, "1" if cl == "nous" else "2")
        j = i - 1
        finite = ms
        while j >= 0 and (toks[j][2] == "AUX" or toks[j][0].lower() in self.SKIP_BETWEEN):
            if toks[j][2] == "AUX":
                finite = toks[j][3] or finite
            j -= 1
        if j < 0:
            return False
        cl = toks[j][0].lower()
        if cl not in self.refl_clitics:
            return False
        person, number = self.refl_clitics[cl]
        if cl in ("nous", "vous"):
            # "nous parlons": the subject, not a clitic; reflexive needs a
            # subject nous/vous before it ("nous nous levons")
            k = j - 1
            while k >= 0 and toks[k][0].lower() in ("ne", "n'"):
                k -= 1
            if k < 0 or toks[k][0].lower() != cl:
                subj = next((toks[x][0].lower() for x in range(j - 1, -1, -1)
                             if toks[x][0].lower() in self.SUBJECTS), None)
                if not ("VerbForm=Inf" in ms and subj == cl):
                    return False
            return True
        if cl in ("se", "s'"):
            return True
        if not strict:
            return True
        m = self._morph(finite)
        if "VerbForm=Inf" in ms and m.get("Person") is None:
            # "je vais me coucher" (finite verb before it), "tu dois te lever"
            subj = next((toks[x][0].lower() for x in range(j - 1, -1, -1)
                         if toks[x][0].lower() in self.SUBJECTS), None)
            return subj is not None and self.SUBJECTS[subj][0] == person
        if m.get("Person") is None:
            subj = next((toks[x][0].lower() for x in range(j - 1, -1, -1)
                         if toks[x][0].lower() in self.SUBJECTS), None)
            return subj is not None and self.SUBJECTS[subj][0] == person
        return m.get("Person") == person

    def is_reflexive(self, toks, i):
        return self._refl(toks, i, strict=True)

    def carries_refl_clitic(self, toks, i):
        return self._refl(toks, i, strict=False)

    def stative_aux(self, toks, i):
        j = i - 1
        while j >= 0 and (toks[j][2] == "ADV" or toks[j][0].lower() in ("ne", "n'", "pas")):
            j -= 1
        return j >= 0 and toks[j][2] in ("AUX", "VERB") and toks[j][1].lower() == "être"

    def _literary_past(self, s):
        """The surface is only ever a passé simple or imperfect subjunctive form
        in Wiktionary (jouâmes, alla, fût), never a present/imperfect/... form
        (finit, dit are both)."""
        c = self._lp_cache.get(s)
        if c is None:
            lx = self._lx
            forms = [set(sn[2]) for e in (lx.E.get(s, []) if lx else []) if e["p"] == "verb"
                     for sn in e["s"] if sn[3] == "form"]
            lit = [t for t in forms if {"historic", "past"} <= t or {"imperfect", "subjunctive"} <= t]
            other = [t for t in forms if t not in lit and t & NON_LITERARY_FORM_TAGS]
            c = self._lp_cache[s] = bool(lit) and not other
        return c

    def _past_participle(self, s):
        """Wiktionary lists s as a past participle form of a verb."""
        for e in self._lx.E.get(s, []):
            if e["p"] == "verb" and any(sn[3] == "form" and "participle" in sn[2] and "present" not in sn[2]
                                        for sn in e["s"]):
                return True
        return self._participle_guess(s) is not None

    def _participle_guess(self, s):
        """Verb of a regular past participle Wiktionary does not list
        (arrivée -> arriver, finies -> finir)."""
        lx = self._lx
        for suf in ("es", "e", "s", ""):
            if suf and not s.endswith(suf):
                continue
            b = s[: len(s) - len(suf)] if suf else s
            for end, inf in (("é", "er"), ("i", "ir"), ("u", "re")):
                if b.endswith(end) and lx.usable_entries(b[: -len(end)] + inf, ["verb"]):
                    return b[: -len(end)] + inf
        return None

    def _verb_of(self, s):
        """Verb lemma for a verb-form surface: Wiktionary forms, else a regular
        participle, else a first-group present form (base -> baser)."""
        lx = self._lx
        c = lx.verbs_only(lx.candidates(s, ["verb"]))
        if c:
            return lx.best_by_freq(c)
        g = self._participle_guess(s)
        if g:
            return g
        for suf, add in (("ent", "er"), ("es", "er"), ("e", "er")):
            if s.endswith(suf) and lx.usable_entries(s[: -len(suf)] + add, ["verb"]):
                return s[: -len(suf)] + add
        return None

    def marks_sentence(self, toks):
        """Passé simple the tagger missed (it tags trouvâmes as present):
        a verb token whose surface is only a literary past form."""
        lx = self._lx
        low = [t[0].lower() for t in toks]
        for i, w in enumerate(low):
            if w in PS_AFTER_SUBJECT:
                j = i - 1
                while j >= 0 and low[j] in OBJ_CLITICS:
                    j -= 1
                if j >= 0 and (low[j] in SUBJ_PRON or toks[j][2] in ("PROPN", "NOUN")):
                    return True          # "Je dus partir", "Tom fut surpris"
        for t in toks:
            w = t[0].lower()
            if not self._literary_past(w):
                continue
            # the tagger calls jouâmes an adjective; a homograph with a real
            # entry of another POS (cela, pronoun) counts only when tagged a verb
            if t[2] in ("VERB", "AUX") or not any(e["p"] != "verb" and lx.entry_usable(e)
                                                  for e in lx.E.get(w, [])):
                return True
        return False

    def extra_wordfreq(self, raw):
        """wordfreq splits week-end / là-bas / petit-déjeuner at the hyphen, so
        its top list never has them: take their (multi-token) zipf for the
        hyphenated subtitle surfaces that Wiktionary lists as words (as ru)."""
        from wordfreq import zipf_frequency
        from ..core.util import Env
        from ..core.lex import stage_lex
        heads = {k for k in stage_lex(Env(self))["entries"] if "-" in k}
        hy, total = {}, 0
        with open(self.repo / ".cache" / self.subtitles_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                w, _, c = line.rstrip("\n").partition(" ")
                c = int(c) if c.isdigit() else 0
                total += c
                w = self.fold(w)
                if i < 20000 and "-" in w and w in heads and w not in raw:
                    hy[w] = c
        for w, c in hy.items():
            # wordfreq's multi-token zipf is the phrase frequency ("en cas",
            # "bien être"): capped at the subtitle zipf of the hyphenated word
            z = min(zipf_frequency(w, self.wordfreq_code), math.log10(c / total * 1e9) if c else 0)
            if z > 0:
                raw[w] = 10 ** z

    def translation_mismatch(self, toks, en):
        """English idioms with no literal link to the French ("Il a au moins
        soixante ans" = "He is sixty, if a day") teach the wrong meaning."""
        return bool(EN_IDIOM_RE.search(en))

    def sentence_rank(self, toks, lv):
        """A1/A2 examples avoid violence when another sentence will do (sex,
        drugs, suicide... are kept to B1 by sensitive_re)."""
        if lv == self.level_ids[-1]:
            return 0
        return 1 if any(t[1].lower() in VIOLENT_LEMMAS for t in toks) else 0

    def is_marked_past(self, ms):
        # passé simple: finite indicative past (passé composé is aux + participle)
        return "Tense=Past" in ms and "Mood=Ind" in ms and "VerbForm=Fin" in ms

    # ---- nouns / articles -------------------------------------------------
    def default_gender(self, lemma):
        return "f" if lemma.endswith(("tion", "sion", "té", "ette", "ance", "ence", "ure", "ie", "ade")) else "m"

    def noun_display(self, lemma, gender, plural, en):
        gender = MAJORITY_GENDER.get(lemma, gender)
        if plural:
            return f"les {lemma}", f"{en} (pl.)"
        if self.elides(lemma):
            tag = "m/f" if gender == "mf" else gender
            return f"l'{lemma}", f"{en} ({tag})"
        if gender == "mf":
            return f"le/la {lemma}", en
        return f"{'la' if gender == 'f' else 'le'} {lemma}", en

    def clean_sentence_text(self, t):
        return t

    def check_word(self, w):
        """A noun shows a singular article that fits its first letter (l' before
        a vowel or mute h, le/la otherwise), "les" only for pluralia tantum, and
        alt[0] is the bare lemma. No A1/A2 gloss matches lower_level_gloss_re."""
        if w.get("lv") != self.level_ids[-1] and self.lower_level_gloss_re.search(w.get("en", "")):
            return f"word {w['id']} {w['w']!r}: sensitive gloss below {self.level_ids[-1]}: {w['en']!r}"
        if w.get("pos") != "noun":
            return None
        shown, lemma = w["w"], w["lemma"]
        if shown == lemma:
            if lemma in self.no_article:
                return None
            return f"noun {w['id']} {shown!r}: no article"
        alt = w.get("alt") or []
        if not alt or alt[0] != lemma:
            return f"noun {w['id']} {shown!r}: alt[0] {alt[:1]} is not the bare lemma {lemma!r}"
        if shown == f"l'{lemma}":
            art = "l'"
        elif shown.endswith(" " + lemma):
            art = shown[: -len(lemma) - 1]
        else:
            return f"noun {w['id']} {shown!r}: display does not end in its lemma {lemma!r}"
        if art == "les":
            if lemma not in self.pluralia_tantum:
                return f"noun {w['id']} {shown!r}: plural article on a lemma outside pluralia_tantum"
            return None
        if art not in SINGULAR_ARTICLES:
            return f"noun {w['id']} {shown!r}: article {art!r} not in {sorted(SINGULAR_ARTICLES)}"
        if (art == "l'") != self.elides(lemma):
            return f"noun {w['id']} {shown!r}: wrong article form for {lemma!r} (elision)"
        if art == "l'" and not re.search(r"\((m|f|m/f)\)", w.get("en", "")):
            return f"noun {w['id']} {shown!r}: l' noun without a (m)/(f) gender tag"
        return None

    # ---- QA scans -----------------------------------------------------------
    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS), "seasons": " ".join(SEASONS),
        "num": " ".join(NUMBERS), "col": " ".join(COLOURS),
        "core": "et ou à de en être avoir oui non bonjour merci pardon salut",
    }
    qa_verb_re = r"(er|ir|re|ïr)$"
    qa_article_rules = [
        (r"^(le|la) [aeiouàâäéèêëîïôöùûüœæ]", "le/la+vowel"),
        (r"^l'[^aeiouàâäéèêëîïôöùûüœæh]", "l'+cons"),
        (r"^la \S*(age|ment|isme|eau)$(?<!plage)(?<!page)(?<!image)(?<!cage)(?<!rage)(?<!nage)(?<!eau)", "la -age/-ment"),
        (r"^le \S*(tion|sion|té|ette|ance|ence)$(?<!été)(?<!côté)(?<!comité)(?<!pâté)(?<!squelette)(?<!silence)", "le -tion/-té"),
    ]
    qa_clitic_verb_re = r"-(moi|toi|le|la|les|lui|leur|nous|vous|y|en)$"
    qa_clitic_cluster_re = r"^([a-zé]+'|-)"
    qa_adj_inflected_re = r"(euse|ive|ienne|onne|ée|ées|és|aux|eaux|elle)$"
    qa_foreign_letters_re = r"[wk]"
    qa_proper_re = r"\b(Paris|France|Jesus|God|Christ|Marseille|Belgium|Quebec|Lyon)\b"
    qa_plural_article_re = r"^les "


SPEC = French
