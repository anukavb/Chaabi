"""Enrollment-profile and speaker-similarity logic for CHAABI."""

from __future__ import annotations

import itertools
import os
from typing import Any, Iterable

import numpy as np


PROFILE_VERSION = "ecapa-voxceleb-multi-template-v1"
MIN_ENROLLMENT_SIMILARITY = float(
    os.getenv("CHAABI_ECAPA_MIN_ENROLLMENT_SIMILARITY", "0.35")
)
BASE_AUTHENTICATION_THRESHOLD = float(
    os.getenv("CHAABI_ECAPA_SPEAKER_THRESHOLD", "0.30")
)
MAX_AUTHENTICATION_THRESHOLD = float(
    os.getenv("CHAABI_ECAPA_MAX_THRESHOLD", "0.42")
)
AUTHENTICATION_MARGIN = float(os.getenv("CHAABI_ECAPA_ENROLLMENT_MARGIN", "0.20"))
MINIMUM_TEMPLATE_MATCHES = 2


class SpeakerVerificationError(ValueError):
    """Raised when a speaker profile cannot be created or compared safely."""

    def __init__(
        self, message: str, *, pairwise_similarities: Iterable[float] = ()
    ) -> None:
        super().__init__(message)
        self.pairwise_similarities = [
            round(float(similarity), 4) for similarity in pairwise_similarities
        ]


def _validate_configuration() -> None:
    ratios = {
        "CHAABI_ECAPA_MIN_ENROLLMENT_SIMILARITY": MIN_ENROLLMENT_SIMILARITY,
        "CHAABI_ECAPA_SPEAKER_THRESHOLD": BASE_AUTHENTICATION_THRESHOLD,
        "CHAABI_ECAPA_MAX_THRESHOLD": MAX_AUTHENTICATION_THRESHOLD,
        "CHAABI_ECAPA_ENROLLMENT_MARGIN": AUTHENTICATION_MARGIN,
    }
    for name, value in ratios.items():
        if not 0.0 <= value <= 1.0:
            raise RuntimeError(f"{name} must be between 0 and 1.")
    if BASE_AUTHENTICATION_THRESHOLD > MAX_AUTHENTICATION_THRESHOLD:
        raise RuntimeError(
            "CHAABI_ECAPA_SPEAKER_THRESHOLD cannot exceed "
            "CHAABI_ECAPA_MAX_THRESHOLD."
        )


_validate_configuration()


def _normalized(embedding: Iterable[float]) -> np.ndarray:
    vector = np.asarray(list(embedding), dtype=np.float64)
    if vector.ndim != 1 or vector.size == 0 or not np.all(np.isfinite(vector)):
        raise SpeakerVerificationError("Invalid speaker embedding.")
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise SpeakerVerificationError("Speaker embedding has no usable energy.")
    return vector / norm


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    first = _normalized(left)
    second = _normalized(right)
    if first.shape != second.shape:
        raise SpeakerVerificationError("Speaker embedding dimensions do not match.")
    return float(np.clip(np.dot(first, second), -1.0, 1.0))


def build_speaker_profile(embeddings: Iterable[Iterable[float]]) -> dict[str, Any]:
    """Keep phrase-varied templates and derive a robust user threshold.

    Authentication scores the best two templates, so enrollment uses the
    strongest agreeing pair as its consistency signal as well. A noisier third
    recording remains useful as a template, but no longer causes all otherwise
    consistent enrollment audio to be discarded.
    """
    vectors = [_normalized(embedding) for embedding in embeddings]
    if len(vectors) < 3:
        raise SpeakerVerificationError("Three speaker embeddings are required.")
    dimensions = {vector.size for vector in vectors}
    if len(dimensions) != 1:
        raise SpeakerVerificationError("Enrollment embedding dimensions do not match.")

    pairwise_similarities = [
        float(np.dot(left, right))
        for left, right in itertools.combinations(vectors, 2)
    ]
    minimum_similarity = min(pairwise_similarities)
    enrollment_consistency = max(pairwise_similarities)
    if enrollment_consistency < MIN_ENROLLMENT_SIMILARITY:
        raise SpeakerVerificationError(
            "No two enrollment recordings sound consistent enough.",
            pairwise_similarities=pairwise_similarities,
        )
    threshold = max(
        BASE_AUTHENTICATION_THRESHOLD,
        min(
            MAX_AUTHENTICATION_THRESHOLD,
            minimum_similarity - AUTHENTICATION_MARGIN,
        ),
    )
    return {
        "version": PROFILE_VERSION,
        "templates": [
            [round(float(value), 8) for value in vector]
            for vector in vectors
        ],
        "template_count": len(vectors),
        "score_strategy": "second-best-template",
        "threshold": round(threshold, 4),
        "enrollment_consistency": round(enrollment_consistency, 4),
        "enrollment_min_similarity": round(minimum_similarity, 4),
        "enrollment_pair_similarities": [
            round(similarity, 4) for similarity in pairwise_similarities
        ],
    }


def compare_speaker(
    live_embedding: Iterable[float], profile: dict[str, Any]
) -> tuple[bool, float, float, list[float]]:
    """Compare against every template and average the two strongest matches."""
    if profile.get("version") != PROFILE_VERSION:
        raise SpeakerVerificationError("Unsupported speaker profile version.")
    threshold = float(profile.get("threshold", BASE_AUTHENTICATION_THRESHOLD))
    if not 0.0 <= threshold <= 1.0:
        raise SpeakerVerificationError("Invalid speaker threshold.")
    raw_templates = profile.get("templates")
    if not isinstance(raw_templates, list) or len(raw_templates) < MINIMUM_TEMPLATE_MATCHES:
        raise SpeakerVerificationError("Stored speaker templates are unavailable.")

    live_vector = _normalized(live_embedding)
    template_similarities = [
        cosine_similarity(live_vector, template) for template in raw_templates
    ]
    strongest = sorted(template_similarities, reverse=True)[:MINIMUM_TEMPLATE_MATCHES]
    # Passing requires agreement with two separate enrollment recordings. A
    # single unusually high template score can no longer outweigh a mismatch.
    similarity = float(strongest[-1])
    return (
        similarity >= threshold,
        round(similarity, 4),
        round(threshold, 4),
        [round(score, 4) for score in template_similarities],
    )
