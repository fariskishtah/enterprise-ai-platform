"""Scope AutoML parameter fingerprints by plugin.

Revision ID: 0011_adjust_automl_trial_uniqueness
Revises: 0010_add_automl_management
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_adjust_automl_trial_uniqueness"
down_revision: str | None = "0010_add_automl_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("automl_trials") as batch:
        batch.drop_constraint("uq_automl_trials_study_fingerprint", type_="unique")
        batch.create_unique_constraint(
            "uq_automl_trials_study_plugin_fingerprint",
            ["study_id", "plugin_id", "parameter_fingerprint"],
        )


def downgrade() -> None:
    with op.batch_alter_table("automl_trials") as batch:
        batch.drop_constraint(
            "uq_automl_trials_study_plugin_fingerprint", type_="unique"
        )
        batch.create_unique_constraint(
            "uq_automl_trials_study_fingerprint",
            ["study_id", "parameter_fingerprint"],
        )
