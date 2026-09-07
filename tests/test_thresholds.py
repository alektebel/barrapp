"""The fault thresholds have one home.

Three copies of 0.85 used to exist: barra/faults.py, barra/faults_taxonomy.py
and the phone's Cues.kt. Nothing enforced that they agreed - a comment asked
the reader to change them together. These tests are that enforcement, on the
two Python copies here and on the phone contract in test_cues_parity.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from barra import faults, faults_taxonomy, quality
from barra.config import THRESHOLDS

ROOT = Path(__file__).resolve().parents[1]

MIRRORED = {
    "SWING_TORSO": "swing_torso",
    "LOCKOUT_MIN": "lockout_min",
    "HANG_MIN": "hang_min",
    "CONTROLLED_TEMPO": "controlled_tempo",
    "STALL_RATE": "stall_rate",
    "STRAIGHT_ARM": "straight_arm",
    "STRAIGHT_LEG": "straight_leg",
    "HORIZONTAL": "horizontal",
    "STRICT_HORIZONTAL": "strict_horizontal",
    "PIKE": "pike",
    "PISTOL_DEPTH": "pistol_depth",
    "PISTOL_VALGUS": "pistol_valgus",
}


def test_modules_use_the_config_value():
    for module in (faults, faults_taxonomy, quality):
        for name, field in MIRRORED.items():
            if hasattr(module, name):
                assert getattr(module, name) == getattr(THRESHOLDS, field), \
                    f"{module.__name__}.{name} disagrees with THRESHOLDS.{field}"


def test_no_module_redefines_a_threshold_as_a_literal():
    """A number, not a reference, is how the copies drifted in the first place."""
    literal = re.compile(r"^(%s)\s*=\s*[-\d.]" % "|".join(MIRRORED))
    for rel in ("barra/faults.py", "barra/faults_taxonomy.py", "barra/quality.py"):
        for i, line in enumerate((ROOT / rel).read_text().splitlines(), 1):
            assert not literal.match(line), f"{rel}:{i} pins a threshold locally: {line}"


def test_thresholds_are_frozen():
    """Pinned before labels are seen (docs/CORE.md), so not writable at runtime."""
    import dataclasses
    import pytest
    assert dataclasses.is_dataclass(THRESHOLDS)
    with pytest.raises(dataclasses.FrozenInstanceError):
        THRESHOLDS.swing_torso = 0.9  # type: ignore[misc]
