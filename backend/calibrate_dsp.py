"""Offline calibration utility for CHAABI's acoustic replay-risk score.

This tool reads recordings from user-supplied folders, runs the normal DSP
engine, writes only derived measurements, and recommends a decision threshold.
It never modifies ``dsp_engine.py`` and never copies the source recordings.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Iterable

from dsp_engine import AudioProcessingError, process_audio_buffer


SCENARIOS = {"live": False, "replay": True}
RESULT_FIELDS = [
    "trial_id",
    "scenario",
    "expected_replay",
    "status",
    "sample_rate",
    "duration_ms",
    "speech_detected",
    "formant_confidence",
    "f1_hz",
    "f2_hz",
    "f3_hz",
    "high_frequency_energy_ratio",
    "replay_risk_score",
    "replay_risk_level",
    "predicted_replay",
    "correct",
    "reason_codes",
    "error",
]


class CalibrationError(ValueError):
    """Raised when a calibration dataset cannot be evaluated."""


def _wav_files(folder: Path) -> Iterable[Path]:
    return sorted(path for path in folder.rglob("*") if path.suffix.lower() == ".wav")


def _result_row(
    trial_id: str,
    scenario: str,
    expected_replay: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    quality = result["audio_quality"]
    features = result["features"]
    formants = result["formant_summary"]
    formant_frames = result["formant_frames"]
    formant_confidence = (
        sum(float(frame["confidence"]) for frame in formant_frames)
        / len(formant_frames)
        if formant_frames
        else 0.0
    )
    replay_risk_score = (
        round(1.0 - float(result["liveness_score"]), 3)
        if result["liveness_score"] is not None
        else None
    )
    if replay_risk_score is None:
        replay_risk_level = "unavailable"
    elif result["is_replay_attack"]:
        replay_risk_level = "high"
    elif replay_risk_score >= 0.30:
        replay_risk_level = "medium"
    else:
        replay_risk_level = "low"
    predicted = result["is_replay_attack"]
    comparable = result["liveness_available"]
    return {
        "trial_id": trial_id,
        "scenario": scenario,
        "expected_replay": expected_replay,
        "status": "evaluated" if comparable else "inconclusive",
        "sample_rate": quality["sample_rate"],
        "duration_ms": quality["duration_ms"],
        "speech_detected": quality["speech_detected"],
        "formant_confidence": round(formant_confidence, 3),
        "f1_hz": formants["f1_hz"],
        "f2_hz": formants["f2_hz"],
        "f3_hz": formants["f3_hz"],
        "high_frequency_energy_ratio": features["high_frequency_energy_ratio"],
        "replay_risk_score": replay_risk_score,
        "replay_risk_level": replay_risk_level,
        "predicted_replay": predicted,
        "correct": predicted == expected_replay if comparable else None,
        "reason_codes": "|".join(result["reason_codes"]),
        "error": "",
    }


def evaluate_dataset(dataset_root: Path) -> list[dict[str, Any]]:
    """Evaluate ``live`` and ``replay`` WAV folders without retaining audio."""
    dataset_root = Path(dataset_root)
    rows: list[dict[str, Any]] = []
    trial_number = 1

    for scenario, expected_replay in SCENARIOS.items():
        scenario_folder = dataset_root / scenario
        if not scenario_folder.is_dir():
            continue
        for audio_path in _wav_files(scenario_folder):
            trial_id = f"{scenario}-{trial_number:03d}"
            trial_number += 1
            try:
                result = process_audio_buffer(audio_path.read_bytes(), "audio/wav")
                rows.append(_result_row(trial_id, scenario, expected_replay, result))
            except (AudioProcessingError, OSError) as error:
                rows.append(
                    {
                        **{field: "" for field in RESULT_FIELDS},
                        "trial_id": trial_id,
                        "scenario": scenario,
                        "expected_replay": expected_replay,
                        "status": "error",
                        "error": str(error),
                    }
                )

    if not rows:
        raise CalibrationError(
            "No WAV files found. Add recordings under live/ and replay/."
        )
    return rows


def recommend_threshold(rows: list[dict[str, Any]]) -> dict[str, float | int] | None:
    """Find the score boundary with the highest accuracy on available trials."""
    usable = [
        row
        for row in rows
        if row["status"] == "evaluated" and row["replay_risk_score"] is not None
    ]
    if not usable or {bool(row["expected_replay"]) for row in usable} != {False, True}:
        return None

    scores = sorted({float(row["replay_risk_score"]) for row in usable})
    candidates = [0.0, 1.0]
    candidates.extend((left + right) / 2.0 for left, right in zip(scores, scores[1:]))
    candidates.extend(scores)

    best_threshold = 0.5
    best_correct = -1
    for threshold in candidates:
        correct = sum(
            (float(row["replay_risk_score"]) >= threshold)
            == bool(row["expected_replay"])
            for row in usable
        )
        if correct > best_correct:
            best_correct = correct
            best_threshold = threshold

    return {
        "recommended_threshold": round(best_threshold, 3),
        "evaluated_trials": len(usable),
        "correct_trials": best_correct,
        "accuracy": round(best_correct / len(usable), 3),
    }


def write_results(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset",
        type=Path,
        help="Folder containing live/ and replay/ WAV subfolders.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("calibration-results") / "dsp_measurements.csv",
        help="CSV destination for derived measurements only.",
    )
    args = parser.parse_args()

    rows = evaluate_dataset(args.dataset)
    write_results(rows, args.output)
    recommendation = recommend_threshold(rows)

    evaluated = sum(row["status"] == "evaluated" for row in rows)
    inconclusive = sum(row["status"] == "inconclusive" for row in rows)
    errors = sum(row["status"] == "error" for row in rows)
    print(f"Processed: {len(rows)}")
    print(f"Evaluated: {evaluated}")
    print(f"Inconclusive: {inconclusive}")
    print(f"Errors: {errors}")
    print(f"Results: {args.output.resolve()}")
    if recommendation:
        print(
            "Recommended CHAABI_HIGH_REPLAY_RISK_THRESHOLD: "
            f"{recommendation['recommended_threshold']} "
            f"(observed accuracy {recommendation['accuracy']:.1%})"
        )
    else:
        print("Threshold recommendation requires usable live and replay samples.")


if __name__ == "__main__":
    main()
