# Language data sources (verified 2026-09-23)

Scout findings per language: sources, licences, counts, and pipeline gotchas. Italian and Spanish sources are documented in their repos. Audio counts are Tatoeba clips with permissive licences (CC BY / CC BY-SA / CC0) only.

# French (fr / Tatoeba fra) — verified 2026-09-23
- hermitdave fr_full.txt 834,768 rows, lowercased; elision fragments (c', l', j', d', qu') are standalone tokens → reattach
- wordfreq fr ok (large)
- kaikki French jsonl.gz 57MB
- Tatoeba fra_sentences_detailed 726,753; links.tar.bz2 149.8MB; eng 24.9MB
- Audio: 106,472 clips, permissive only 4,093 (CC BY 4.0 3,396; CC BY-SA 672; CC0 25). Top permissive: Igider, vlecomte, Meksems, Them, MisterTrouser
- Tagger: spaCy fr_core_news_sm 3.8.0, LGPL-LR (no NC)
- Kelly mirror data/fr.json is FAKE (rebucketed wordfreq) — don't use for sanity
- Gotchas: elision merge; gender/articles le/la/l'/les, un/une; clitics precede verb; reflexive "se" verbs (se lever) lemma convention; contractions au/du/aux/des; spaCy apostrophe tokens; typing lenient accents A1/A2 (é/è/ê/ç); TTS fr-FR fine; STT fr-FR

# Russian (ru / Tatoeba rus) — verified 2026-09-23
- hermitdave ru_full.txt 615,157 rows; ё NOT normalised (её 201,916 vs ее 232,065; 12,513 ё lines) → fold both sides to е for matching, display kaikki ё
- wordfreq ru large
- kaikki Russian jsonl.gz 89MB; entries carry stressed headwords (соба́ка) → pron display from kaikki accents
- Tatoeba rus_sentences_detailed 1,225,086; links.tar.bz2; eng_sentences_detailed 34.9MB
- Audio: 32,606 clips; permissive only 1,390 (CC BY 4.0 1,093; CC BY-SA 295; CC0 2); 81% NC-ND from CK
- Tagger: spaCy ru_core_news_sm 3.8.0 MIT; lemmatiser pymorphy3 (MIT) required
- Kelly ru.json: 8,958 words, real CEFR tiers, "research use only" → sanity only
- TORFL lexical minimum: no open copy
- Gotchas: aspect pairs → separate entries (делать / сделать), cross-link via alt? no — separate; -ся verbs separate lemmas; A1 sentences prefer Nom/Acc (use Case= morph), defer other cases to A2/B1; typing lenient ё/е and no stress; no articles; TTS ru-RU; STT ru-RU

# German (de / Tatoeba deu) — verified 2026-09-23
- hermitdave de_full.txt 1,157,685 rows, 100% lowercased → noun capitalisation lost; recover case from kaikki headword, disambiguate homographs (essen/Essen) by kaikki POS
- wordfreq de large (633,824)
- kaikki German jsonl.gz 96.7MB; gender (der/die/das) + plural from head_templates/forms — field names unverified, sample ~5 entries (gehen, Tisch, anfangen) before locking
- Tatoeba deu_sentences_detailed 781,130; deu-eng_links 584,787 (direct file)
- Audio: 86,209 clips; permissive only 2,881 (CC BY 4.0 2,423; CC BY-SA 434; CC0 24). Top permissive: Igider, MisterTrouser, fjay69, Auride, Meksems
- Tagger: spaCy de_core_news_sm 3.8.0 MIT (TIGER corpus commercial-licensed to Explosion, WikiNER CC BY 4.0; model weights redistributable)
- Graded lists: Goethe Wortlisten copyrighted (don't ship); Kelly has no German; GitHub CEFR lists are Goethe transcriptions / unlicensed → sanity-only at best
- Gotchas: separable verbs (anfangen → fängt … an; spaCy dep svp) → rejoin prefix+verb for lemma, sentence-linking must catch split occurrences; compounds kept as single lemmas above freq threshold, never decomposed; strong-verb lemmatiser quality unverified → sample check; modals drilled as content words; formal Sie vs sie case-sensitive matching (freq list lowercased); Präteritum of sein/haben/modals A1, other Präteritum B1; typing lenient ae/oe/ue/ss at A1/A2; TTS de-DE / STT de-DE untested

# Persian (fa / Tatoeba pes) — verified 2026-09-23
- hermitdave fa_full.txt: 445,744 lines, CC-BY-SA 4.0
- wordfreq: only small_fa exists (no large_fa) → thinner written frequency
- kaikki Persian jsonl.gz 13MB
- Tatoeba: pes_sentences_detailed 31,792; pes-eng_links 8,476 (direct file); audio 11,467 clips but only 381 permissive (352 CC BY 4.0, 29 CC BY-SA)
- Tagger: Stanza fa (Apache 2.0; model UD Persian-Seraji CC BY-SA 4.0). Hazm MIT alt.
- No CEFR list. User CSV ~/Downloads/persian_common_words_1000_clean.csv: sanity only, never ship.
- Gotchas: engine needs rtl flag; ZWNJ normalisation; ی/ي ک/ك normalise to Persian codepoints; ezafe unwritten; compound light verbs (کار کردن) as multiword lemmas w/ hand list; plurals -ها + broken plurals hand table; colloquial subtitles (میخوام) vs formal wordfreq/Wiktionary — normalise before matching; pron = kaikki romanisation (coverage unverified); typing: null; TTS fa-IR unverified (Android likely, desktop patchy); STT fa-IR ok.

# Indonesian (id / Tatoeba ind) — verified 2026-09-23
- hermitdave id_full.txt 357,441 lines; colloquial-heavy (gue, lo, nggak, banget)
- wordfreq: small_id only
- kaikki Indonesian jsonl.gz 9.9MB
- Tatoeba ind_sentences_detailed 28,311; ind-eng_links 25,718 (direct file)
- Audio: 1,740 clips, only 18 CC BY 4.0 → effectively no audio; TTS only (id-ID unverified)
- Tagger: Stanza id gsd (UD_Indonesian-GSD CC BY-SA 4.0); Sastrawi (MIT) stemmer as cross-check
- Gotchas: lemma = root (Wiktionary headword), affixed forms as link forms/alt; reduplication as inflection; flag colloquial register (subtitles) vs formal; no gender/tense/articles; typing trivial; STT id-ID

# Japanese (ja / Tatoeba jpn) — verified 2026-09-23
- hermitdave ja_full.txt BROKEN (34,504 rows, kanji stems; conjugation stripped) → don't use for ranking; use wordfreq[cjk] (needs mecab-python3+ipadic) + Tatoeba corpus token counts via Sudachi as the spoken proxy
- kaikki Japanese jsonl.gz 47MB; entries have forms[].ruby readings + romanization entries
- Tatoeba jpn_sentences_detailed 248,909; jpn-eng_links 280,706; jpn_transcriptions.tsv.bz2 (furigana [漢字|かな]) 249,007 rows; jpn_indices.csv 17MB (curated lemma(reading){surface} per token — use for links!)
- Audio: 6,420 clips, only 27 permissive → TTS ja-JP only
- Tokeniser: SudachiPy mode C + SudachiDict-core (Apache-2.0); alt fugashi+unidic-lite (MIT)
- JLPT lists (elzup/jlpt-word-list MIT but provenance unclear) → sanity only; N5≈A1 N4≈A2 N3≈B1
- Gotchas: lemma = dictionary form; pron = kana reading (+romaji optional); particles/aux/copula = functionWords; counters bound morphemes; casual register skew; showPron toggle for kana; typing "pron" since 2026-09-26 (typed kana reading + typed written form); spaced:false in pack (no spaces) — engine cloze substring mode

# Korean (ko / Tatoeba kor) — verified 2026-09-23
- hermitdave ko_full.txt 688,129 rows, eojeol units (particles attached) → lemmatise via spaCy before ranking
- wordfreq ko small only (its tokeniser needs mecab-ko; not needed if spaCy tokenises)
- kaikki ko-extract.jsonl.gz 24.6MB (URL: kaikki.org downloads/ko/ko-extract.jsonl.gz)
- Tatoeba kor_sentences_detailed 15,940 (TINY); kor-eng_links 11,598; audio 25 permissive → TTS ko-KR
- Tagger: spaCy ko_core_news_sm 3.8.0, CC BY-SA 4.0, no external tokenizer dep. Avoid KoNLPy (GPL).
- NIKL 한국어 학습용 어휘 목록 5,965 words graded 초/중/고 (982/2,111/2,872), KOGL Type 1 (≈CC BY) → could SHIP as level source (초급≈A1-A2, 중급≈B1); fetch needs browser (gongu.copyright.or.kr mirror)
- Gotchas: lemma -다 form; register 반말/존댓말 (prefer polite in examples); Sino vs native numerals both; romanisation: write own RR (avoid GPL lib); typing: null; sentence coverage risk — supplement Tatoeba with other CC corpora or generated+reviewed sentences

# Arabic (ar / Tatoeba ara) — verified 2026-09-23
- hermitdave ar_full.txt 2,507,189 lines (punctuation not stripped; MSA+dialect mix)
- wordfreq ar large
- kaikki Arabic jsonl.gz 50MB (~65k entries); vocalised headword in head_templates args; romanization forms ~29% coverage
- Tatoeba ara_sentences_detailed 68,543; ara-eng_links 48,742; audio 483 clips all from elmassoudi, licence blank → treat as none unless resolved (TTS ar)
- Dialect exports arq 2,457 / arz 1,582 / apc 160 / ary 117 — ignore (MSA target)
- Tagger: CAMeL Tools (MIT) primary; Stanza ar PADT is CC BY-NC-SA; Farasa research-only
- Kelly ar.json hybrid (Kelly core + wordfreq tail) → soft sanity only
- Gotchas: MSA filter = require kaikki entry + tagger POS; clitic split via CAMeL; strip ال for lemma, display nouns without article; normalise alef variants/ة-ه/ى-ي/tatweel before matching; broken plurals from kaikki forms + hand table; verb lemma 3sg masc perfective; rtl:true; pron = vocalised headword (+romanization when present); typing: null; TTS ar-SA/ar-EG, STT ar unverified

# Hindi (hi / hin) — verified 2026-09-23
- hermitdave hi_full.txt 21,309 rows (real words; danda । as punct); wordfreq small_hi (26.6k)
- kaikki Hindi jsonl.gz 17.4MB, 39,220 entries; gender in head_templates; romanization 99.8%
- Tatoeba hin 16,475 sentences, 13,286 w/ eng link; audio 3,506, 105 permissive
- Tagger: Stanza hi (UD Hindi-HDTB, CC BY-NC-SA 4.0 — non-commercial like Italian); indic_nlp_library MIT for normalisation
- No graded list
- Gotchas: nukta/chandrabindu normalisation; compound verbs (कर देना) multiword; gender m/f; verb lemma -ना; LTR Devanagari; pron = kaikki romanization; typing null; TTS hi-IN unverified
# Urdu (ur / urd)
- hermitdave ur_full.txt 9,592 rows; wordfreq small_ur (23.1k)
- kaikki Urdu jsonl.gz 4.9MB, 10,421 entries; romanization 99.5%; vocalised forms in head args
- Tatoeba urd 2,851 sentences, 2,433 w/ eng link (THIN); audio 2 permissive → none; hin↔urd links only 246
- Tagger: Stanza ur (UD Urdu-UDTB, CC BY-NC-SA 4.0)
- Gotchas: RTL + Noto Nastaliq Urdu (Google Fonts ok) + larger line-height; normalise ي/ك/ه → ی/ک/ہ, ZWNJ; sentences per word sparse → supplement with reviewed generated sentences; typing null

# Swahili / Somali — verified 2026-09-23 → BOTH DEFERRED TO TODO (user rule: if problematic, TODO)
## Swahili (swh) VIABLE-WEAK
- No hermitdave sw, no wordfreq sw, no tagger (UD_Swahili-OPUSGV empty), no Stanza
- kaikki Swahili 76.7MB ~23.5k senses; Tatoeba swh 4,583 (4,403 eng-linked); OPUS GlobalVoices en-sw 32,307 pairs; Tanzil (religious); FLORES-200 ~2,009 CC BY-SA
- Would need: surface-frequency over ~37k sentences + noun-class/ku- prefix-stripping heuristic; est. 70–85% gloss coverage; audio unverified (CommonVoice gated)
## Somali (som) NOT VIABLE
- kaikki ~1,285 senses total (<half of 2000 target); Tatoeba 164 (126 eng-linked); no GlobalVoices; only Tanzil + FLORES (2,009)
- Needs a bigger open dictionary or generated glosses/sentences outside the open-data constraint

