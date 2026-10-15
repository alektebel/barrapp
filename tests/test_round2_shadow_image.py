"""The isolated Lambda image must match the current reviewed phone candidate."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "server" / "Dockerfile.round2-yolo11s-stride3"


class Round2ShadowImage(unittest.TestCase):
    def test_image_pins_the_screened_candidate_without_changing_production(self):
        text = DOCKERFILE.read_text()
        for setting in (
            "BARRA_POSE_BACKEND=ultralytics",
            "BARRA_POSE_WORKERS=6",
            "BARRA_POSE_WORKER_MODE=fork",
            "BARRA_POSE_CPU_THREADS=1",
            "BARRA_YOLO_POSE_STRIDE=3",
            "BARRA_YOLO_POSE_IMGSZ=480",
            "BARRA_ULTRALYTICS_FUSION_POLICY=ultralytics-geometry-supported-v3",
            "BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE=0.25",
            "/opt/barra/models/yolo11s-pose.pt",
            "1060bda4a27012060eca246f9b2adeea22eabb045a1e58f8d229be29b7ebc2ba",
            'CMD ["handler.worker"]',
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, text)
        self.assertNotRegex(text, r"(?m)^\s*RUN .*deploy\.sh")
        self.assertNotIn("samconfig.toml", text)


if __name__ == "__main__":
    unittest.main()
