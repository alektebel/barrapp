"""The session description a person actually reads - in Spanish, since the
alpha is Spanish; the logic (when "verified" is earned, the three-rep floor,
advice keyed to the first blocker) is unchanged."""
import unittest

from barra.summary import describe


def payload(**over):
    base = {
        "n_reps": 4, "n_candidates": 4, "exercise": "muscle_up",
        "detected": {"exercise": "muscle_up", "label": "Muscle-up"},
        "sessionScore": 74, "sessionBand": "solid", "blockers": [],
        "duration_s": 22.0, "trim": {"startS": 2.0, "endS": 16.0},
        "reps": [
            {"label": f"r{i}", "score": 74, "total_s": f"{4.0 + 0.1 * i:.1f}",
             "components": [
                 {"name": "range", "value": 0.80, "weight": 0.4, "why": "hang 76% of full"},
                 {"name": "control", "value": 0.90, "weight": 0.25, "why": "descent 0.6x"},
                 {"name": "smoothness", "value": 0.62, "weight": 0.35,
                  "why": "31% of the ascent made no progress"},
             ]} for i in range(1, 5)
        ],
    }
    base.update(over)
    return base


class TestSessionDescription(unittest.TestCase):
    def test_it_says_what_was_recorded(self):
        head, text = describe(payload())
        self.assertIn("4 muscle-ups verificados", head)
        self.assertIn("sólida", head)
        self.assertIn("74 sobre 100", text)
        self.assertIn("serie de trabajo de 14 segundos", text)
        self.assertIn("recortada de 22 segundos", text)

    def test_it_names_the_weakest_part_with_its_evidence(self):
        """The one sentence of any report that gets acted on."""
        _, text = describe(payload())
        self.assertIn("fluidez", text)
        self.assertIn("62 %", text)
        self.assertIn("el 31 % de la subida no avanzó", text)

    def test_it_does_not_call_a_push_up_a_pull(self):
        _, text = describe(payload(
            exercise="push_up", detected={"exercise": "push_up", "label": "Push-up"}))
        self.assertNotIn("tirón", text.lower())
        self.assertNotIn("pull", text.lower())

    def test_two_reps_are_not_reported_as_a_session(self):
        """Three is the floor before a median means anything, and the text has
        to say so rather than quietly presenting a number of equal weight."""
        p = payload(n_reps=2, reps=payload()["reps"][:2])
        _, text = describe(p)
        self.assertIn("una sola observación", text)

    def test_a_scored_set_does_not_hide_unscored_reps(self):
        reps = payload()["reps"]
        reps[0] = {**reps[0], "score": None, "scoreNote": "Range was not measurable"}
        _, text = describe(payload(reps=reps))
        self.assertIn("no se pudo puntuar", text)
        self.assertIn("range was not measurable", text.lower())

    def test_no_reps_gets_a_reason_and_something_to_do(self):
        head, text = describe(payload(
            n_reps=0, n_candidates=0, reps=[], sessionScore=None,
            sessionBand="unmeasured",
            blockers=["no turnaround stood out from the noise"]))
        self.assertIn("nada que contar", head.lower())
        self.assertIn("ningún cambio de dirección", text.lower())
        self.assertIn("encuadre", text.lower())

    def test_unrecognised_clip_is_told_how_to_film_it(self):
        head, text = describe(payload(
            n_reps=0, n_candidates=0, reps=[], sessionScore=None,
            sessionBand="unmeasured", detected={"exercise": "unknown"},
            blockers=["the hands were only tracked in 31% of the clip - "
                      "they are out of frame for most of it"]))
        self.assertIn("no pudo saber", text.lower())
        self.assertIn("dentro del plano", text.lower())

    def test_it_never_claims_progress_from_one_clip(self):
        """One clip cannot support a comparison. Note the phrases checked are
        cross-session claims - "made no progress" describes a stall inside a
        single rep and is a measurement, not a claim about the athlete."""
        for p in (payload(), payload(n_reps=0, reps=[], sessionScore=None)):
            _, text = describe(p)
            for phrase in ("mejora", "mejor que", "peor que", "récord",
                           "última sesión", "desde la", "estás progresando"):
                self.assertNotIn(phrase, text.lower(), text)

    def test_a_steady_set_is_described_as_steady(self):
        reps = [{**r, "total_s": "4.0"} for r in payload()["reps"]]
        _, text = describe(payload(reps=reps))
        self.assertIn("se mantuvieron estables", text)


class TestFilmingAdvice(unittest.TestCase):
    def test_the_primary_blocker_decides_the_advice(self):
        """A clip usually fails for more than one reason, in the order the
        pipeline hit them. Searching all of them at once let an incidental
        later blocker win: a clip whose real problem was walking around the rig
        was told to keep the turnaround in frame."""
        _, text = describe(payload(
            n_reps=0, n_candidates=2, reps=[], sessionScore=None,
            sessionBand="unmeasured",
            blockers=[
                "candidate at 22.9s: the hands travelled 1.2 torso-lengths, so "
                "they were not on a fixed bar - this is movement around the rig",
                "turnaround at 32.8s was never actually tracked",
            ]))
        self.assertIn("ya estés en la barra", text)
        self.assertNotIn("de arriba abajo", text)

    def test_a_hold_is_told_to_film_reps(self):
        _, text = describe(payload(
            n_reps=0, n_candidates=0, reps=[], sessionScore=None,
            sessionBand="unmeasured", detected={"exercise": "unknown"},
            blockers=["78% of the clip is spent within a fifth of a torso-length "
                      "of one position - a hold, or resting between attempts"]))
        self.assertIn("cuenta repeticiones", text)


class TestVerifiedIsEarned(unittest.TestCase):
    def test_a_set_with_nothing_scored_is_not_called_verified(self):
        """"19 verified push-up reps" above "none of them could be scored" is a
        contradiction inside one paragraph."""
        reps = [{"label": f"r{i}", "score": None, "total_s": "1.0",
                 "scoreNote": "Range of motion could not be measured on this clip.",
                 "components": []} for i in range(19)]
        head, text = describe(payload(
            n_reps=19, reps=reps, sessionScore=None, sessionBand="unmeasured",
            exercise="push_up", detected={"exercise": "push_up", "label": "Push-up"}))
        self.assertIn("ninguna verificada", head)
        self.assertNotIn("verificad", text.split(".")[0])
        self.assertIn("19 flexiones encontradas", text)

    def test_it_says_the_reps_do_not_count_towards_a_progression(self):
        reps = [{"score": None, "total_s": "1.0", "components": []}] * 5
        _, text = describe(payload(n_reps=5, reps=reps, sessionScore=None,
                                   sessionBand="unmeasured"))
        self.assertIn("cuenta para una progresión", text)

    def test_it_does_not_point_at_a_number_that_does_not_exist(self):
        reps = [{"score": None, "total_s": "1.0", "components": []}] * 5
        _, text = describe(payload(n_reps=5, reps=reps, sessionScore=None,
                                   sessionBand="unmeasured"))
        self.assertNotIn("fuera de la cifra de arriba", text)


class TestSpanish(unittest.TestCase):
    def test_no_english_reaches_the_text(self):
        from barra.i18n import english_words
        cases = [payload(), payload(n_reps=2, reps=payload()["reps"][:2]),
                 payload(n_reps=0, n_candidates=0, reps=[], sessionScore=None,
                         sessionBand="unmeasured",
                         blockers=["no turnaround stood out from the noise"])]
        for p in cases:
            head, text = describe(p)
            self.assertEqual(english_words(head + " " + text), [], head + " | " + text)
