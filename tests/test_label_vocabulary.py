"""The labelling tool must accept the whole skill graph, not the ten movements
that happen to have fault rules.

Before this, `label_reps.py` refused any clip whose movement was not in
`barra.rules.RULES` - 78 of the 88 skills - and said "no rules for 'handstand'"
as though the clip were the problem. The movement a person confirms is ground
truth whether or not the fault layer has anything to ask about it, and for a
hold it is the only ground truth there is.
"""
from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import label_reps  # noqa: E402

from barra.rules import RULES  # noqa: E402
from barra.skills import MEASURED, SKILLS  # noqa: E402


class TestVocabulary(unittest.TestCase):
    def test_the_picker_offers_every_skill(self):
        vocab = label_reps.movement_vocabulary()
        self.assertEqual(len(vocab), len(SKILLS))
        self.assertEqual({m["id"] for m in vocab}, set(SKILLS))

    def test_each_entry_says_whether_it_can_be_measured_or_faulted(self):
        """The page uses these to explain why a clip has no fault questions.
        Getting them wrong would show a reviewer an empty fault grid with no
        reason for it."""
        for m in label_reps.movement_vocabulary():
            self.assertEqual(m["measurable"], m["id"] in MEASURED)
            self.assertEqual(m["hasRules"], m["id"] in RULES)

    def test_the_vocabulary_is_grouped_and_ordered_for_reading(self):
        vocab = label_reps.movement_vocabulary()
        keys = [(m["family"], m["name"]) for m in vocab]
        self.assertEqual(keys, sorted(keys))

    def test_most_of_the_graph_has_no_fault_rules(self):
        """The premise of the change, asserted so it cannot quietly stop being
        true: if fault rules ever covered the whole graph, the whole-clip path
        would be dead code worth deleting."""
        without = [k for k in SKILLS if k not in RULES]
        self.assertGreater(len(without), 50)


class TestAdjudication(unittest.TestCase):
    """A movement verdict must land in the corpus sheet the rest of the repo
    already treats as truth - not in a second store competing with it."""

    def setUp(self):
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.sheet = self.tmp / "labels-adjudicated.csv"
        self.patch = mock.patch.object(label_reps, "ADJUDICATED", self.sheet)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _rows(self):
        with self.sheet.open() as f:
            return list(csv.DictReader(f))

    def test_a_verdict_creates_the_sheet_when_there_is_none(self):
        self.assertTrue(label_reps.record_movement("a.mp4", "front_lever"))
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clip"], "a.mp4")
        self.assertEqual(rows[0]["verdict"], "front_lever")

    def test_a_second_verdict_for_the_same_clip_updates_it_in_place(self):
        label_reps.record_movement("a.mp4", "front_lever")
        label_reps.record_movement("a.mp4", "half_front_lever")
        rows = self._rows()
        self.assertEqual(len(rows), 1, "the clip was appended twice")
        self.assertEqual(rows[0]["verdict"], "half_front_lever")

    def test_an_existing_row_keeps_its_other_columns(self):
        """The sheet carries the directory label, the vision read and the
        description. A human settling the movement must not erase the evidence
        that made the clip worth settling."""
        self.sheet.write_text(
            "clip,directory,vision,model,verdict,description\n"
            "a.mp4,back_lever,front_lever,muscle_up,,a person on parallettes\n")
        label_reps.record_movement("a.mp4", "back_lever")
        row = self._rows()[0]
        self.assertEqual(row["verdict"], "back_lever")
        self.assertEqual(row["directory"], "back_lever")
        self.assertEqual(row["vision"], "front_lever")
        self.assertEqual(row["description"], "a person on parallettes")

    def test_unclear_is_not_recorded_as_a_verdict(self):
        """'I cannot tell' is a real answer in the UI and must not become a
        label that later reads as certainty."""
        self.assertFalse(label_reps.record_movement("a.mp4", label_reps.UNCLEAR))
        self.assertFalse(self.sheet.exists())

    def test_an_empty_verdict_is_not_recorded(self):
        self.assertFalse(label_reps.record_movement("a.mp4", ""))
        self.assertFalse(self.sheet.exists())

    def test_a_reason_is_stored_beside_the_verdict(self):
        label_reps.record_movement("a.mp4", "dip", "the hands are at hip "
                                   "height and the torso is above them")
        row = self._rows()[0]
        self.assertEqual(row["verdict"], "dip")
        self.assertIn("hip height", row["reason"])

    def test_a_reason_never_overwrites_the_clip_description(self):
        """`description` is the vision pass's account of the clip and is the
        evidence that made it worth settling. An earlier version of this wrote
        the reviewer's note into it, destroying that evidence."""
        self.sheet.write_text(
            "clip,directory,vision,model,verdict,reason,description\n"
            "a.mp4,back_lever,front_lever,,,,a person on parallettes\n")
        label_reps.record_movement("a.mp4", "back_lever", "the chest faces down")
        row = self._rows()[0]
        self.assertEqual(row["description"], "a person on parallettes")
        self.assertEqual(row["reason"], "the chest faces down")

    def test_a_new_row_records_what_the_label_was_corrected_from(self):
        """Without it the reason has nothing to point at: 'the rear foot is on
        a bench' only means something next to the label it overturned."""
        label_reps.record_movement("a.mp4", "bulgarian_split_squat",
                                   "the rear foot is on a bench",
                                   declared="split_squat")
        row = self._rows()[0]
        self.assertEqual(row["directory"], "split_squat")
        self.assertEqual(row["verdict"], "bulgarian_split_squat")

    def test_a_reason_is_bounded(self):
        label_reps.record_movement("a.mp4", "dip", "x" * 5000)
        self.assertLessEqual(len(self._rows()[0]["reason"]), 500)

    def test_a_path_is_reduced_to_the_clip_name(self):
        """The sheet is keyed by basename, because classify_eval reads it that
        way. A row keyed by a full path would silently never match."""
        label_reps.record_movement("videos/own/a.mp4", "dip")
        self.assertEqual(self._rows()[0]["clip"], "a.mp4")


class TestDisputesDoesNotDestroyHumanWork(unittest.TestCase):
    """`label_disputes.py` rebuilds this sheet from the scraped corpus on every
    run. It used to carry across only `verdict`, for corpus clips only - so a
    reviewer's REASON was erased each run, and any row for a clip the corpus
    does not contain (somebody's own filmed clips, labelled through
    label_reps.py) vanished entirely. Both are unrecoverable human work.
    """

    def setUp(self):
        import label_disputes
        self.mod = label_disputes
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.sheet = self.tmp / "labels-adjudicated.csv"

    def test_existing_rows_are_read_back_by_clip(self):
        self.sheet.write_text(
            "clip,directory,vision,model,verdict,reason,description\n"
            "a.mp4,squat,squat,,pistol_squat,only one foot is down,x\n")
        prior = self.mod.existing_rows(self.sheet)
        self.assertIn("a.mp4", prior)
        self.assertEqual(prior["a.mp4"]["reason"], "only one foot is down")

    def test_a_missing_sheet_is_not_an_error(self):
        self.assertEqual(self.mod.existing_rows(self.tmp / "nope.csv"), {})

    def test_the_reason_column_is_part_of_the_schema(self):
        """If this script's field list and label_reps' disagree, whichever
        writes last silently drops the other's column."""
        self.assertIn("reason", self.mod.FIELDS)
        self.assertEqual(set(self.mod.FIELDS),
                         set(label_reps.ADJUDICATED_FIELDS))


if __name__ == "__main__":
    unittest.main()
