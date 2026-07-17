"""Create sensors.

Revision ID: 0003_create_sensors
Revises: 0002_create_manufacturing_domain
Create Date: 2026-07-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_create_sensors"
down_revision: str | None = "0002_create_manufacturing_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sensors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("sensor_type", sa.String(length=255), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("sampling_rate", sa.Float(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("max_value", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensors_machine_normalized_name",
        "sensors",
        ["machine_id", "normalized_name"],
        unique=True,
    )
    op.create_index("ix_sensors_machine_id", "sensors", ["machine_id"])
    op.create_index("ix_sensors_name", "sensors", ["name"])
    op.create_index("ix_sensors_sensor_type", "sensors", ["sensor_type"])
    op.create_index("ix_sensors_deleted_at", "sensors", ["deleted_at"])
    op.create_index(
        "ix_sensors_machine_deleted",
        "sensors",
        ["machine_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sensors_machine_deleted", table_name="sensors")
    op.drop_index("ix_sensors_deleted_at", table_name="sensors")
    op.drop_index("ix_sensors_sensor_type", table_name="sensors")
    op.drop_index("ix_sensors_name", table_name="sensors")
    op.drop_index("ix_sensors_machine_id", table_name="sensors")
    op.drop_index("ix_sensors_machine_normalized_name", table_name="sensors")
    op.drop_table("sensors")
