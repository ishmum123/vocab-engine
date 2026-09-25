"""Cross-pack drop-everywhere policy (spec.drop_all_levels = base.DROP_ALL_EN +
own-language terms, via base.drop_all_re). Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_drop_all.py     (from vocab-engine/)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import drop_all_re  # noqa: E402

LANGS = ("it", "es", "fr", "de", "ru", "fa", "id", "ko", "ja")

# every spec drops these English translations (the shared half)
EN_DROP = ("She was raped.", "He was sexually assaulted.", "He molested a child.", "It was child abuse.",
           "He committed suicide.", "I want to kill myself.", "She killed herself.", "Tom hanged himself.",
           "I cut myself on purpose.", "He took his own life.", "She died of an overdose.",
           "Self-harm is serious.", "The Suicide Squad is a film.")
# and keeps these (controls)
EN_KEEP = ("I killed the light.", "The rapeseed field is yellow.", "Grapes are sweet.", "He killed time.",
           "Stop bothering me.", "The drapes are new.", "I cut the bread.", "Hang your coat.",
           "Take your time.", "He's a therapist.", "The end of my life story", "I overslept.")
# own-language sample sentences that must drop, and benign controls that must not
OWN = {
    "it": (("È stata violentata.", "Ha tentato il suicidio.", "Voleva uccidersi.", "Voglio farla finita.",
            "Si è ucciso.", "Una violenza sessuale."),
           ("Non voglio molestare nessuno.", "Mangio le carote.", "Facciamola finita con le bugie.", "È molto violento?")),
    "es": (("La violaron.", "Fue una agresión sexual.", "Intentó suicidarse.", "Quería matarse.",
            "Voy a matarme.", "Se quitó la vida."),
           ("Él violó la ley.", "No quiero molestar.", "El jefe está molesto.", "Mi madre va a matarme.")),
    "fr": (("Elle a été violée.", "Une agression sexuelle.", "Il s'est suicidé.", "Il a voulu se tuer.",
            "Je vais me tuer.", "Il a mis fin à ses jours."),
           ("Il a violé la loi.", "Ma mère va me tuer.", "Tu es mon ami.", "Le violon est beau.")),
    "de": (("Sie wurde vergewaltigt.", "Ein sexueller Übergriff.", "Er beging Selbstmord.", "Suizid ist ernst.",
            "Er wollte sich umbringen.", "Er brachte sich um.", "Das ist Missbrauch."),
           ("Er bringt mich um den Schlaf.", "Ich bringe dich nach Hause.", "Alkoholmissbrauch schadet.",
            "Er hat mich umarmt.")),
    "ru": (("Её изнасиловали.", "Сексуальное насилие.", "Он совершил самоубийство.", "Он покончил с собой.",
            "Я хочу убить себя."),
           ("Он убил время.", "Я люблю себя.", "Насилие недопустимо.", "Она покончила с работой.")),
    "fa": (("به او تجاوز کردند.", "آزار جنسی جرم است.", "خودکشی یک مشکل جدی است."),
           ("من خودم آمدم.", "کشی را دیدم.", "آزار ندهید.")),
    "id": (("Dia diperkosa.", "Itu pelecehan seksual.", "Dia bunuh diri.", "Itu kekerasan seksual."),
           ("Jaga dirimu.", "Pastikan kamu tidak melukai dirimu sendiri.", "Dia membunuh waktu.")),
    "ko": (("그는 자살했다.", "성폭행은 범죄다.", "성추행을 당했다.", "강간 사건.", "자해하지 마."),
           ("자리에 앉으세요.", "살고 싶어요.", "그는 해를 봤다.")),
    "ja": (("彼は自殺した。", "性的暴行の事件。", "レイプは犯罪だ。", "性的虐待。", "自傷行為。"),
           ("自分で殺虫剤を買った。", "自動車が好きだ。", "性格がいい。", "傷が治った。")),
}


class DropAllLevels(unittest.TestCase):
    def test_every_spec_has_shared_and_own_terms(self):
        for code in LANGS:
            d = get_spec(code, None).drop_all_levels
            self.assertIsNotNone(d, code)
            for s in EN_DROP:
                self.assertTrue(d.search(s), f"{code}: {s!r} should drop")
            for s in EN_KEEP:
                self.assertFalse(d.search(s), f"{code}: {s!r} should stay")
            drop, keep = OWN[code]
            for s in drop:
                self.assertTrue(d.search(s), f"{code}: {s!r} should drop")
            for s in keep:
                self.assertFalse(d.search(s), f"{code}: {s!r} should stay")

    def test_helper_keeps_own_pattern_and_flags(self):
        d = drop_all_re(r"\bfoo\b")
        self.assertTrue(d.search("FOO bar"))            # re.I default
        self.assertTrue(d.search("He was raped."))
        self.assertFalse(d.search("food"))
        self.assertTrue(drop_all_re().search("suicide"))


if __name__ == "__main__":
    unittest.main()
