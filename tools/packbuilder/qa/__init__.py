"""Pack QA: check (hard gate), scans (review aids), sample (hand-QA draws)."""
import json


def load_pack(spec):
    p = spec.repo / "pack"
    return (json.loads((p / "pack.json").read_text()), json.loads((p / "words.json").read_text()),
            json.loads((p / "sentences.json").read_text()))
