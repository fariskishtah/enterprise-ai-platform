"""Dataset metadata domain models."""

from pydantic import BaseModel, ConfigDict, Field


class DatasetInfo(BaseModel):
    """Metadata describing a versioned model-training dataset."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    dataset_name: str = Field(
        min_length=1,
        description="Human-readable dataset name.",
    )
    dataset_version: str = Field(
        min_length=1,
        description="Version identifier for the dataset.",
    )
    row_count: int = Field(
        ge=0,
        description="Number of rows in the dataset.",
    )
    column_count: int = Field(
        gt=0,
        description="Number of columns in the dataset.",
    )
    feature_columns: list[str] = Field(
        min_length=1,
        description="Dataset columns used as model inputs.",
    )
    target_column: str = Field(
        min_length=1,
        description="Dataset column the model is intended to predict.",
    )
