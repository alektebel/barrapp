"""The clip as uploaded is kept in S3 beside the trimmed copy, for debugging,
and deleting a session deletes both."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "server" / "api")]
for k, v in {"JOBS_TABLE": "t-jobs", "FEEDBACK_TABLE": "t-fb", "REFERRALS_TABLE": "t-ref",
             "UPLOADS_TABLE": "t-up", "VIDEO_BUCKET": "t-bucket",
             "AWS_DEFAULT_REGION": "eu-west-1"}.items():
    os.environ.setdefault(k, v)

import handler  # noqa: E402


def _trim_ok(src, start, end, out):
    Path(out).write_bytes(b"cut")
    return out


def test_the_original_is_copied_before_the_cut_overwrites_it(tmp_path):
    calls = []
    s3 = mock.Mock()
    s3.copy_object.side_effect = lambda **k: calls.append(("copy", k["Key"], k["CopySource"]["Key"]))
    s3.upload_file.side_effect = lambda f, b, key, **k: calls.append(("upload", key))
    with mock.patch.object(handler, "s3", s3), \
            mock.patch("barra.frames.trim_clip", side_effect=_trim_ok):
        assert handler._store_trimmed_clip(tmp_path / "c.mp4", "own", "job1", 5.0, 20.0, 30.0)
    assert calls == [("copy", "own/job1.original.mp4", "own/job1.mp4"),
                     ("upload", "own/job1.mp4")]


def test_nothing_is_overwritten_when_the_original_cannot_be_kept(tmp_path):
    s3 = mock.Mock()
    s3.copy_object.side_effect = RuntimeError("denied")
    with mock.patch.object(handler, "s3", s3), \
            mock.patch("barra.frames.trim_clip", side_effect=_trim_ok):
        assert handler._store_trimmed_clip(tmp_path / "c.mp4", "own", "job1", 5.0, 20.0, 30.0) is False
    s3.upload_file.assert_not_called()
