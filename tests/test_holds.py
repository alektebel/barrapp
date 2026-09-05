"""Static positions are results, not failures to find a set.

Fixtures are parametric, like the classifier's: a body posed on a bar or on
the floor, jittered, held. Each hold is dialled in by the one geometric fact
that defines it and the test asks only about that fact.
"""
from __future__ import annotations

import unittest

import numpy as np

from barra import schema as S
from barra.classify import classify
from barra.holds import (HUMAN, MIN_HOLD_S, SKILL, classify_hold,
                         longest_parked_run)
from barra.skills import SKILLS


def _fill(kp, f, points, rng, conf=0.95):
    for name, x, y in points:
        kp[f, S.KP_INDEX[name]] = (x + rng.normal(0, 0.6), y + rng.normal(0, 0.6), conf)
    for n in ("left_eye", "right_eye", "left_ear", "right_ear"):
        kp[f, S.KP_INDEX[n]] = kp[f, S.KP_INDEX["nose"]]


def held(pose: dict, frames: int = 240, seed: int = 0, nose_conf: float = 0.95,
         lead_in: int = 0) -> np.ndarray:
    """A body in one pose, jittered, for `frames` frames. `pose` maps a
    landmark name to (x, y); left/right pairs are placed 30px apart.
    `lead_in` frames of a different pose (standing) come first."""
    rng = np.random.default_rng(seed)
    total = lead_in + frames
    kp = np.zeros((total, 17, 3), np.float32)
    standing = {"wrist": (300, 560), "shoulder": (300, 380), "hip": (300, 500),
                "knee": (300, 590), "ankle": (300, 680), "nose": (300, 350),
                "elbow": (300, 470)}
    for f in range(total):
        p = standing if f < lead_in else pose
        pts = []
        for name, (x, y) in p.items():
            if name == "nose":
                pts.append(("nose", x, y))
            else:
                pts.append((f"left_{name}", x - 15, y))
                pts.append((f"right_{name}", x + 15, y))
        _fill(kp, f, pts, rng)
        kp[f, S.KP_INDEX["nose"], 2] = nose_conf
    return kp


# torso is 120px in every pose below, so torso-lengths read off directly.
DEAD_HANG = {"wrist": (300, 100), "elbow": (300, 170), "shoulder": (300, 245),
             "hip": (300, 365), "knee": (300, 455), "ankle": (300, 545),
             "nose": (300, 215)}
FLEXED_HANG = {"wrist": (300, 100), "elbow": (300, 130), "shoulder": (300, 145),
               "hip": (300, 265), "knee": (300, 355), "ankle": (300, 445),
               "nose": (300, 115)}
INVERTED = {"wrist": (300, 100), "elbow": (300, 170), "shoulder": (300, 320),
            "hip": (300, 200), "knee": (300, 130), "ankle": (300, 90),
            "nose": (300, 355)}
FRONT_LEVER = {"wrist": (300, 100), "elbow": (310, 160), "shoulder": (320, 230),
               "hip": (440, 235), "knee": (530, 238), "ankle": (620, 240),
               "nose": (285, 215)}          # face up: nose above the shoulders
BACK_LEVER = {"wrist": (300, 100), "elbow": (310, 160), "shoulder": (320, 230),
              "hip": (440, 235), "knee": (530, 238), "ankle": (620, 240),
              "nose": (285, 250)}           # face down: nose below the shoulders
TUCK_FRONT_LEVER = {"wrist": (300, 100), "elbow": (310, 160), "shoulder": (320, 230),
                    "hip": (440, 235), "knee": (470, 190), "ankle": (450, 250),
                    "nose": (285, 215)}
HANDSTAND = {"wrist": (300, 600), "elbow": (300, 530), "shoulder": (300, 460),
             "hip": (300, 340), "knee": (300, 250), "ankle": (300, 160),
             "nose": (290, 495)}
PLANK = {"wrist": (300, 600), "elbow": (300, 560), "shoulder": (305, 520),
         "hip": (425, 530), "knee": (515, 545), "ankle": (605, 560),
         "nose": (285, 505)}
L_SIT = {"wrist": (300, 600), "elbow": (300, 540), "shoulder": (300, 470),
         "hip": (310, 590), "knee": (400, 585), "ankle": (500, 585),
         "nose": (300, 440)}
# The sample clip's geometry, as the estimator reported it: torso flattened
# to 6 degrees from horizontal, legs pointing straight up.
FOLDED_INVERSION = {"wrist": (300, 100), "elbow": (310, 160), "shoulder": (320, 235),
                    "hip": (440, 222), "knee": (470, 115), "ankle": (480, 12),
                    "nose": (285, 205)}
SUPPORT = {"wrist": (300, 560), "elbow": (300, 520), "shoulder": (300, 470),
           "hip": (300, 590), "knee": (300, 680), "ankle": (300, 770),
           "nose": (300, 440)}


class TestVocabulary(unittest.TestCase):
    def check(self, pose, expected, **kw):
        c = classify(held(pose, **kw))
        self.assertEqual(c.kind, "hold", f"{expected}: {c.exercise} - {c.reason}")
        self.assertEqual(c.exercise, expected, c.reason)
        self.assertIsNotNone(c.hold)
        return c

    def test_dead_hang(self):
        c = self.check(DEAD_HANG, "dead_hang")
        self.assertTrue(c.certain)

    def test_flexed_arm_hang(self):
        c = self.check(FLEXED_HANG, "flexed_hang")
        self.assertEqual(c.runner_up, "dead_hang")

    def test_inverted_hang(self):
        """The sample clip that motivated this: a 23-second inversion that
        was correctly refused as a set and then reported as nothing."""
        c = self.check(INVERTED, "inverted_hang")
        self.assertTrue(c.certain)

    def test_front_and_back_lever_split_on_the_face(self):
        front = self.check(FRONT_LEVER, "front_lever")
        back = self.check(BACK_LEVER, "back_lever")
        self.assertEqual(front.runner_up, "back_lever")
        self.assertEqual(back.runner_up, "front_lever")

    def test_a_lever_with_no_face_seen_is_just_a_lever(self):
        """One landmark decides front from back. When it was not seen, the
        answer is the thing that was seen - a lever - not a guess."""
        c = self.check(FRONT_LEVER, "lever", nose_conf=0.1)
        self.assertLess(c.confidence, 0.65)

    def test_a_folded_inversion_is_not_a_lever(self):
        """Level torso, legs at the ceiling. A lever is the whole body laid
        out; this is the real inverted hold the estimator flattened."""
        c = self.check(FOLDED_INVERSION, "inverted_hang")
        self.assertEqual(c.runner_up, "tuck_front_lever")

    def test_tuck_is_read_off_the_knees(self):
        self.check(TUCK_FRONT_LEVER, "tuck_front_lever")

    def test_handstand(self):
        self.check(HANDSTAND, "handstand")

    def test_plank(self):
        self.check(PLANK, "plank")

    def test_l_sit(self):
        self.check(L_SIT, "l_sit")

    def test_support_hold(self):
        self.check(SUPPORT, "support_hold")


class TestDuration(unittest.TestCase):
    def test_seconds_come_from_the_parked_stretch_not_the_clip(self):
        """Walking up to the bar first must not count as hanging from it."""
        kp = held(DEAD_HANG, frames=150, lead_in=90)      # 5 s held, 3 s walk
        c = classify(kp, fps=30.0)
        self.assertEqual(c.kind, "hold", c.reason)
        self.assertAlmostEqual(c.hold.seconds, 5.0, delta=0.5)
        self.assertAlmostEqual(c.hold.start_s, 3.0, delta=0.4)

    def test_a_short_pause_is_not_a_hold(self):
        kp = held(DEAD_HANG, frames=int(MIN_HOLD_S * 30) - 10)
        self.assertIsNone(classify_hold(kp, fps=30.0))

    def test_a_hang_between_attempts_is_not_the_clip(self):
        """Ten seconds of attempts on the bar hold a three-second dead hang
        among them. True of a third of the time on the bar, wrong about the
        session."""
        from tests.test_classify_quality import bar_clip
        reps = bar_clip(n_reps=5)                          # 300 moving + 40 still
        still = np.repeat(reps[-1:], 60, axis=0)
        still[:, :, :2] += np.random.default_rng(1).normal(0, 0.5, still[:, :, :2].shape)
        kp = np.concatenate([reps, still])                 # 100 still of 400 on the bar
        self.assertIsNone(classify_hold(kp, fps=30.0, family="hanging"))

    def test_a_lost_frame_does_not_end_the_run(self):
        a = np.zeros(100)
        a[50] = np.nan                       # unseen for one frame
        b = np.zeros(100)
        self.assertEqual(longest_parked_run([a, b], fps=30.0), (0, 99))

    def test_standing_beside_the_bar_is_not_the_hang(self):
        """Perfectly still, and not the position. The family mask keeps the
        search inside frames where the hands are where the hold needs them."""
        kp = held(DEAD_HANG, frames=150, lead_in=240)      # 8 s standing, 5 s hanging
        h = classify_hold(kp, fps=30.0, family="hanging")
        self.assertIsNotNone(h)
        self.assertAlmostEqual(h.start_s, 8.0, delta=0.4)
        self.assertAlmostEqual(h.seconds, 5.0, delta=0.5)

    def test_a_real_move_does_end_the_run(self):
        a = np.concatenate([np.zeros(40), np.full(30, 1.0), np.zeros(30)])
        first, last = longest_parked_run([a], fps=30.0)
        self.assertEqual((first, last), (0, 39))


class TestBoundaries(unittest.TestCase):
    def test_a_set_is_still_a_set(self):
        """The support-hold gate must not swallow a push-up set that pauses at
        the top - the arms articulate through a set, and never in a hold."""
        from tests.test_classify_quality import dip_clip, pushup_clip
        self.assertEqual(classify(pushup_clip()).kind, "set")
        self.assertEqual(classify(pushup_clip()).exercise, "push_up")
        self.assertEqual(classify(dip_clip()).exercise, "dip")

    def test_every_hold_has_a_label(self):
        for k in ("dead_hang", "flexed_hang", "inverted_hang", "front_lever",
                  "back_lever", "lever", "tuck_front_lever", "handstand",
                  "plank", "l_sit", "support_hold", "hold"):
            self.assertIn(k, HUMAN)

    def test_skill_graph_links_point_at_real_skills(self):
        for hold_id, skill_id in SKILL.items():
            self.assertIn(skill_id, SKILLS, f"{hold_id} -> {skill_id}")

    def test_hold_payload_shape(self):
        c = classify(held(HANDSTAND))
        d = c.hold.as_dict()
        for key in ("exercise", "label", "skill", "confidence", "reason",
                    "seconds", "startS", "endS", "runnerUp"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
