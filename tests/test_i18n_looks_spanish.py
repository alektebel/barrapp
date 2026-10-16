"""The untranslated-text sentinel must not flag Spanish the pipeline writes.

Caught in production on 2026-10-16: "19 flexiones: ninguna verificada" (the
headline of a set counted but not scored) has no accent and no word from the
old function-word list, so the payload sentinel called it untranslated.
"""
from barra import i18n


def test_unscored_set_headline_reads_as_spanish():
    assert i18n.looks_spanish("19 flexiones: ninguna verificada")
    assert i18n.looks_spanish("2 dominadas: ninguno verificado")


def test_english_is_still_caught():
    assert not i18n.looks_spanish("the reps were found and then rejected")
