"""The phone renders the faults the server measures - and only those.

The contract this test holds used to be an accident. Cues.kt re-derived the
faults with regular expressions over the server's prose and its own copies of
0.85, 0.75 and 0.4, so the same threshold existed in three files and the same
fault detection depended on a sentence nobody thought of as an interface. A
copy edit on the server switched coaching off on every device, silently.

The server ships the fired faults now - name, value, threshold, comparison -
and the phone renders names. These tests are that handover:

    - every fault name the taxonomy can produce renders on the phone, in the
      over-the-video verdict and in the Improve panel;
    - no name on the phone exists that the server can never emit;
    - Cues.kt parses no prose and holds no threshold, except the one constant
      the legacy path keeps for payload shapes predating `faults`, which is
      checked for value parity with config.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from barra.config import THRESHOLDS
from barra.faults_taxonomy import all_fault_names

ROOT = Path(__file__).resolve().parents[1]
CUES_KT = ROOT / "app" / "src" / "main" / "java" / "com" / "barrapp" / "Cues.kt"


def _cues_source() -> str:
    return CUES_KT.read_text()


def _block(text: str, header: str, opener: str) -> str:
    """The source between the first `opener` after `header` and its match."""
    i = text.index(header)
    start = text.index(opener, i)
    close = {"{": "}", "(": ")"}[opener]
    depth = 0
    for pos in range(start, len(text)):
        if text[pos] == opener:
            depth += 1
        elif text[pos] == close:
            depth -= 1
            if depth == 0:
                return text[start + 1:pos]
    raise AssertionError(f"unbalanced {opener!r} after {header!r}")


def _when_branches(text: str) -> set[str]:
    """The fault names the over-the-video verdict knows how to render."""
    block = _block(text, "fun repFault(rep: RepRow): String? = when", "{")
    names: set[str] = set()
    for line in block.splitlines():
        lhs, _, _rhs = line.partition("->")
        names.update(re.findall(r'"([^"]+)"', lhs))
    return names


def _cue_strings(text: str) -> set[str]:
    """The fault names the Improve panel has a coaching string for."""
    block = _block(text, "private val CUES = mapOf(", "(")
    names: set[str] = set()
    for line in block.splitlines():
        lhs, _, _rhs = line.partition(" to ")
        names.update(re.findall(r'"([^"]+)"', lhs))
    return names


def _cue_order(text: str) -> set[str]:
    block = _block(text, "private val CUE_ORDER = listOf(", "(")
    return set(re.findall(r'"([^"]+)"', block))


def test_every_server_fault_renders_over_the_video():
    missing = set(all_fault_names()) - _when_branches(_cues_source())
    assert not missing, f"taxonomy faults with no repFault branch: {sorted(missing)}"


def test_every_server_fault_has_a_coaching_string():
    missing = set(all_fault_names()) - _cue_strings(_cues_source())
    assert not missing, f"taxonomy faults with no CUES entry: {sorted(missing)}"


def test_no_phone_only_fault_names():
    """A name the server can never emit is dead code wearing a cue."""
    server = set(all_fault_names())
    phone = _when_branches(_cues_source()) | _cue_strings(_cues_source()) \
        | _cue_order(_cues_source())
    orphans = phone - server
    assert not orphans, f"phone knows faults the taxonomy never fires: {sorted(orphans)}"


def test_cues_kt_parses_no_prose():
    """The whole point of the structured faults array. Back means regress."""
    text = _cues_source()
    offenders = [(n, line) for n, line in enumerate(text.splitlines(), 1)
                 if "Regex(" in line]
    assert not offenders, f"Cues.kt derives faults from prose again: {offenders}"


def test_cues_kt_holds_no_threshold_constants():
    """No second home for a threshold - the one legacy constant is checked
    for value parity in test_legacy_threshold_matches_config()."""
    text = _cues_source()
    offenders = [(n, line) for n, line in enumerate(text.splitlines(), 1)
                 if re.search(r"val (SWING_TORSO|LOCKOUT_MIN|HANG_MIN|"
                              r"CONTROLLED_TEMPO|STALL_RATE)\b", line)]
    assert not offenders, f"Cues.kt pinned a threshold locally: {offenders}"


def test_legacy_threshold_matches_config():
    """LEGACY_SWING_TORSO exists for rows measured before the server named its
    own faults. While it lives, it must agree with the value the rest of the
    pipeline uses - otherwise old history cues off a number nothing else does."""
    text = _cues_source()
    m = re.search(r"LEGACY_SWING_TORSO\s*=\s*([\d.]+)", text)
    assert m, "LEGACY_SWING_TORSO vanished without the legacy path going with it"
    assert float(m.group(1)) == THRESHOLDS.swing_torso, \
        f"legacy phone threshold {m.group(1)} != THRESHOLDS.swing_torso"
