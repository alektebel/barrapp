"""The objectives chat (server/api/chat.py): Spanish, through the one client,
and a failure the user can read - never an exception string."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "server" / "api")]

import chat  # noqa: E402
import llm  # noqa: E402

MSGS = [{"role": "user", "content": "Hola"}]


class Chat(unittest.TestCase):
    def test_unconfigured_asks_the_first_question_in_spanish(self):
        with mock.patch.object(llm, "config", return_value=None):
            out = chat.chat(MSGS)
        self.assertIsNone(out["goals"])
        self.assertIn("¿Cómo te llamas?", out["reply"])

    def test_the_conversation_goes_through_the_one_client(self):
        with mock.patch.object(llm, "config", return_value=("b", "k")), \
                mock.patch.object(llm, "complete",
                                  return_value=llm.ChatResult("qwen3.8-flash", text="¿Y tu edad?")) as c:
            out = chat.chat(MSGS)
        self.assertEqual(out, {"reply": "¿Y tu edad?", "goals": None})
        self.assertEqual(c.call_args.args, (chat.NAN_MODEL, MSGS))
        self.assertEqual(c.call_args.kwargs["system"], chat.SYSTEM)

    def test_goals_are_split_off_the_reply(self):
        text = 'Perfecto, Ana.\n{"name": "Ana", "age": 30, "activity": "regular", "goal": "10 dominadas", "focusExercise": "pull_up"}'
        with mock.patch.object(llm, "config", return_value=("b", "k")), \
                mock.patch.object(llm, "complete", return_value=llm.ChatResult("m", text=text)):
            out = chat.chat(MSGS)
        self.assertEqual(out["reply"], "Perfecto, Ana.")
        self.assertEqual(out["goals"]["focusExercise"], "pull_up")

    def test_a_failure_is_a_spanish_sentence_not_an_exception(self):
        failed = llm.ChatResult("m", error="401 This API key does not have access", status=401)
        with mock.patch.object(llm, "config", return_value=("b", "k")), \
                mock.patch.object(llm, "complete", return_value=failed):
            out = chat.chat(MSGS)
        self.assertNotIn("401", out["reply"])
        self.assertIn("Inténtalo de nuevo", out["reply"])

    def test_the_prompt_is_spanish(self):
        self.assertIn("Responde\nsiempre en español", chat.SYSTEM)


if __name__ == "__main__":
    unittest.main()
