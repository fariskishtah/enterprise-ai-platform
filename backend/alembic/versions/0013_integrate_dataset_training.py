"""Persist exact Dataset Registry lineage for training and AutoML.

Revision ID: 0013_integrate_dataset_training
Revises: 0012_add_dataset_registry
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_integrate_dataset_training"
down_revision: str | None = "0012_add_dataset_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("training_jobs") as batch:
        batch.add_column(sa.Column("dataset_version_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_training_jobs_dataset_version",
            "dataset_versions",
            ["dataset_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_training_jobs_dataset_version_id", ["dataset_version_id"]
        )
    with op.batch_alter_table("automl_studies") as batch:
        batch.add_column(sa.Column("dataset_version_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_automl_studies_dataset_version",
            "dataset_versions",
            ["dataset_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_automl_studies_dataset_version", ["dataset_version_id"])


def downgrade() -> None:
    with op.batch_alter_table("automl_studies") as batch:
        batch.drop_index("ix_automl_studies_dataset_version")
        batch.drop_constraint("fk_automl_studies_dataset_version", type_="foreignkey")
        batch.drop_column("dataset_version_id")
    with op.batch_alter_table("training_jobs") as batch:
        batch.drop_index("ix_training_jobs_dataset_version_id")
        batch.drop_constraint("fk_training_jobs_dataset_version", type_="foreignkey")
        batch.drop_column("dataset_version_id")
