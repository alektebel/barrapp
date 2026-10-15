import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "round2_phone_report.py"


def test_phone_report_uses_all_attempts_as_denominator(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "fast", "bootId": "boot", "startedNs": 1_000_000_000,
         "completeOrigin": True, "submittedNs": 3_000_000_000,
         "resultNs": 10_000_000_000, "renderedNs": 12_000_000_000,
         "pollCount": 8, "phaseMs": {"pollGet": 140, "pollSleep": 4_500,
                                      "pollHandle": 45},
         "countStatus": "geometry", "repCount": 4},
        {"attemptId": "slow", "bootId": "boot", "startedNs": 1_000_000_000,
         "completeOrigin": True, "submittedNs": 3_000_000_000,
         "resultNs": 17_000_000_000, "renderedNs": 18_000_000_000,
         "countStatus": "vision", "repCount": 5},
        {"attemptId": "missing", "bootId": "boot", "startedNs": 1_000_000_000,
         "completeOrigin": True, "submittedNs": 3_000_000_000,
         "resultNs": 0, "renderedNs": 0},
    ]))

    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["attempts"] == 3
    assert report["completed"] == 2
    assert report["incomplete"] == 1
    assert report["under_target"] == 1
    assert report["under_target_fraction"] == 1 / 3
    assert report["count_status_proxy_completed"] == 1
    assert report["under_target_count_status_proxy"] == 1
    assert report["under_target_count_status_proxy_fraction"] == 1 / 3
    assert report["completed_total_ms"]["p50"] == 14_000
    assert report["completed_total_ms"]["p95"] == 16_700
    assert report["completed_poll_count"] == {
        "comparable_attempts": 1, "p50": 8, "p95": 8,
    }
    assert report["completed_phase_ms"]["pollGet"] == {"p50": 140, "p95": 140}
    assert report["completed_phase_ms"]["pollSleep"] == {"p50": 4_500, "p95": 4_500}
    assert report["completed_phase_ms"]["pollHandle"] == {"p50": 45, "p95": 45}


def test_phone_report_keeps_result_milestones_for_unrendered_attempts(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "result-no-frame", "bootId": "boot",
         "startedNs": 1_000_000_000, "completeOrigin": True,
         "submittedNs": 4_000_000_000, "resultNs": 15_370_000_000,
         "renderedNs": 0, "pollCount": 14,
         "phaseMs": {"partTransfer": 1_610, "pollGet": 7_131,
                     "pollSleep": 3_262},
         "countStatus": "unmeasured", "repCount": 0},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["attempts"] == 1
    assert report["completed"] == 0
    assert report["under_target"] == 0
    assert report["observed_result_ms"] == {
        "comparable_attempts": 1, "p50": 14_370, "p95": 14_370,
    }
    assert report["observed_submit_to_result_ms"] == {
        "comparable_attempts": 1, "p50": 11_370, "p95": 11_370,
    }
    assert report["observed_phase_ms"]["pollGet"] == {
        "comparable_attempts": 1, "p50": 7_131, "p95": 7_131,
    }


def test_phone_report_rejects_cross_boot_and_incomplete_origins(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "resume", "bootId": "boot-a", "startedNs": 1,
         "completeOrigin": True, "submittedNs": 2, "resultNs": 3,
         "renderedNs": 4},
        {"attemptId": "old", "bootId": "boot-a", "startedNs": 1,
         "completeOrigin": False, "submittedNs": 2, "resultNs": 3,
         "renderedNs": 4},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot-b"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["attempts"] == 2
    assert report["completed"] == 0
    assert report["incomplete"] == 2
    assert report["under_target_fraction"] == 0


def test_fast_unmeasured_result_does_not_pass_count_status_proxy(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "unmeasured", "bootId": "boot", "startedNs": 1_000_000_000,
         "completeOrigin": True, "submittedNs": 3_000_000_000,
         "resultNs": 4_000_000_000, "renderedNs": 5_000_000_000,
         "countStatus": "unmeasured", "repCount": 0},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["under_target"] == 1
    assert report["under_target_count_status_proxy"] == 0
    assert report["under_target_count_status_proxy_fraction"] == 0


def test_fast_frame_estimate_does_not_pass_count_status_proxy(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "vision", "bootId": "boot", "startedNs": 1_000_000_000,
         "completeOrigin": True, "submittedNs": 3_000_000_000,
         "resultNs": 4_000_000_000, "renderedNs": 5_000_000_000,
         "countStatus": "vision", "repCount": 5},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["under_target"] == 1
    assert report["under_target_count_status_proxy"] == 0


def test_geometry_zero_is_only_a_proxy_without_explicit_quality_review(tmp_path):
    path = tmp_path / "round2-timings.json"
    base = {"bootId": "boot", "startedNs": 1_000_000_000,
            "completeOrigin": True, "submittedNs": 2_000_000_000,
            "resultNs": 3_000_000_000, "renderedNs": 4_000_000_000,
            "countStatus": "geometry", "repCount": 0}
    path.write_text(json.dumps([
        {"attemptId": "proxy-only", **base},
        {"attemptId": "reviewed", **base, "qualityApproved": True},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["under_target_count_status_proxy"] == 2
    assert report["under_target_quality_approved"] == 1
    assert report["quality_approved_completed"] == 1


def test_phone_report_compares_source_and_prepared_clip_bytes(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "trimmed", "bootId": "boot", "startedNs": 1,
         "completeOrigin": True, "submittedNs": 2, "resultNs": 3,
         "renderedNs": 4, "sourceBytes": 10_000, "preparedBytes": 2_000},
        {"attemptId": "grew", "bootId": "boot", "startedNs": 1,
         "completeOrigin": True, "submittedNs": 2, "resultNs": 3,
         "renderedNs": 4, "sourceBytes": 1_000, "preparedBytes": 1_500},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["clip_bytes"] == {
        "comparable_attempts": 2,
        "source_p50": 5_500,
        "prepared_p50": 1_750,
        "prepared_larger_than_source": 1,
    }


def test_phone_report_breaks_upload_into_phases_and_estimates_transfer_rate(tmp_path):
    path = tmp_path / "round2-timings.json"
    path.write_text(json.dumps([
        {"attemptId": "put", "bootId": "boot", "startedNs": 1_000_000_000,
         "completeOrigin": True, "submittedNs": 4_000_000_000,
         "resultNs": 8_000_000_000, "renderedNs": 9_000_000_000,
         "preparedBytes": 2_000_000,
         "phaseMs": {"jobCreate": 100, "singlePut": 2_000, "submit": 100}},
    ]))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                            "--current-boot-id", "boot"],
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["completed_phase_ms"] == {
        "jobCreate": {"p50": 100, "p95": 100},
        "singlePut": {"p50": 2_000, "p95": 2_000},
        "submit": {"p50": 100, "p95": 100},
    }
    assert report["effective_transfer_mbps"] == {
        "comparable_attempts": 1, "p50": 8.0, "p95": 8.0,
    }
