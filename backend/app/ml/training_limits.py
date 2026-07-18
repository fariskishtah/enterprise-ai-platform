"""Bounded MVP transport and persistence limits for AI training requests."""

MAX_TRAINING_ROWS = 10_000
MAX_EVALUATION_ROWS = 5_000
MAX_PREDICTION_ROWS = 10_000
MAX_FEATURE_COLUMNS = 256
MAX_TOTAL_FEATURE_CELLS = 1_000_000
MAX_TRAINING_TAGS = 32
MAX_TRAINING_TAG_KEY_LENGTH = 250
MAX_TRAINING_TAG_VALUE_LENGTH = 5_000
MAX_TRAINING_RUN_NAME_LENGTH = 255
MAX_MODEL_DESCRIPTION_LENGTH = 5_000


def validate_training_matrix_limits(
    *,
    training_rows: int,
    evaluation_rows: int,
    feature_columns: int,
) -> None:
    """Reject training matrices outside the shared synchronous/job boundary."""
    if training_rows > MAX_TRAINING_ROWS:
        raise ValueError(
            f"training_features may contain at most {MAX_TRAINING_ROWS} rows.",
        )
    if evaluation_rows > MAX_EVALUATION_ROWS:
        raise ValueError(
            f"evaluation_features may contain at most {MAX_EVALUATION_ROWS} rows.",
        )
    if feature_columns > MAX_FEATURE_COLUMNS:
        raise ValueError(
            f"feature matrices may contain at most {MAX_FEATURE_COLUMNS} columns.",
        )
    total_cells = (training_rows + evaluation_rows) * feature_columns
    if total_cells > MAX_TOTAL_FEATURE_CELLS:
        raise ValueError(
            "training and evaluation feature matrices may contain at most "
            f"{MAX_TOTAL_FEATURE_CELLS} total cells.",
        )


def validate_prediction_matrix_limits(*, rows: int, feature_columns: int) -> None:
    """Bound prediction transport and its per-request monitoring summaries."""
    if rows > MAX_PREDICTION_ROWS:
        raise ValueError(
            f"prediction features may contain at most {MAX_PREDICTION_ROWS} rows.",
        )
    if feature_columns > MAX_FEATURE_COLUMNS:
        raise ValueError(
            f"prediction features may contain at most {MAX_FEATURE_COLUMNS} columns.",
        )
    if rows * feature_columns > MAX_TOTAL_FEATURE_CELLS:
        raise ValueError(
            "prediction features may contain at most "
            f"{MAX_TOTAL_FEATURE_CELLS} total cells.",
        )
