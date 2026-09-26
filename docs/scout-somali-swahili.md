# Data scout: Somali and Swahili (2026-09-26)

Live-verified counts (Tatoeba API, kaikki.org, rhasspy/piper-voices, Leipzig Corpora Collection).

| | Somali (so) | Swahili (sw) |
|---|---|---|
| Frequency list | none in hermitdave/wordfreq; derivable from Leipzig news/Wikipedia corpora (CC BY) | none in hermitdave/wordfreq; Leipzig Wikipedia 2021 (114,594 sentences) and Tanzania web 2013 (820,162 sentences), CC BY |
| Tatoeba total / English-linked | 202 / 79 | 4,605 / ~1,000 |
| kaikki (Wiktionary) | 1,099 words / 1,285 senses | 20,245 forms / 24,006 senses (13,147 nouns, 7,755 verbs) |
| Tagger / lemmatiser | no UD treebank, no Stanza/spaCy model; a research rule+lexicon lemmatiser (arXiv 2308.01785, 93–95%), not packaged | UD Swahili in progress (Steimel & Kübler 2023), no official release; no Stanza/spaCy model |
| TTS | no Google Cloud voice, no confirmed OS voice | no Google Cloud voice; OS voices unconfirmed |
| Piper | none | sw_CD-lanfrica-medium, MIT |
| Licences | kaikki CC BY-SA/GFDL; Leipzig CC BY | same; Piper MIT |

Generated-sentence share at 2000 words (reference: Indonesian 421 linked → mostly generated; Urdu 2.4k linked → 71%):
Somali ~97–99%, Swahili ~85–90%, both needing a native-speaker review pass.

Blockers: Somali is thin everywhere (79 linked pairs, 1,099 dictionary words, no voice, no packaged tagger,
heavy verb/pronoun cliticisation and digraph orthography). Swahili's gap is the tagger: Bantu noun-class
concord (classes 1–18) means a naive stemmer mis-lemmatises constantly.

Recommendation: Swahili viable with heavy generation (dictionary + one MIT Piper voice are real assets);
Somali not now — revisit if a Somali Piper voice or a packaged tagger appears.
