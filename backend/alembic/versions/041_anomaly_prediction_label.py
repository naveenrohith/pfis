"""Record whether an anomaly adjudication was sampled as an alert."""

import sqlalchemy as sa
from alembic import op

revision = "041_anomaly_prediction_label"
down_revision = "040_recommend_feedback_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "anomaly_adjudications",
        sa.Column("predicted_alert", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("anomaly_adjudications", "predicted_alert", server_default=None)


def downgrade() -> None:
    op.drop_column("anomaly_adjudications", "predicted_alert")
