TECHNICAL_DECISION_MODE = "technical_decision_support"
VERSION_CHANGE_MODE = "version_change_awareness"


def get_mode_settings(mode: str) -> dict:
    """
    I am keeping the mode rules here so each backend mode can grow cleanly
    without overloading the service file.
    """

    settings = {
        TECHNICAL_DECISION_MODE: {
            "max_distance": 1.10,
            "best_match_threshold": 0.98,
            "max_context_rows": 3,
            "preferred_keywords": [
                "architecture",
                "design",
                "decision",
                "choose",
                "tradeoff",
                "performance",
                "security",
                "scalability",
                "backend",
                "database",
                "fastapi",
                "postgresql",
                "react",
                "docker",
            ],
        },
        VERSION_CHANGE_MODE: {
            "max_distance": 1.20,
            "best_match_threshold": 1.05,
            "max_context_rows": 4,
            "preferred_keywords": [
                "version",
                "versions",
                "change",
                "changes",
                "breaking",
                "deprecated",
                "deprecation",
                "migration",
                "upgrade",
                "update",
                "compatibility",
                "release",
                "released",
                "as-of",
                "api",
            ],
        },
    }

    if mode not in settings:
        raise ValueError(f"Unsupported mode: {mode}")

    return settings[mode]


def score_row_for_mode(mode: str, row) -> float:
    """
    I am slightly re-scoring rows here so change-aware mode can prefer chunks
    that actually talk about versions or change signals.
    """

    base_distance = float(row.distance)
    text_blob = " ".join(
        [
            str(getattr(row, "title", "") or ""),
            str(getattr(row, "source", "") or ""),
            str(getattr(row, "content", "") or ""),
        ]
    ).lower()

    keywords = get_mode_settings(mode)["preferred_keywords"]
    keyword_hits = sum(1 for keyword in keywords if keyword in text_blob)

    # I am rewarding rows with mode-relevant language so the selected context
    # matches the endpoint purpose more clearly.
    adjusted_distance = base_distance - (keyword_hits * 0.015)

    return adjusted_distance