"""initial schema — conversation_logs, agent_configs, tenants

Revision ID: 0001
Revises:
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("sector", sa.String(length=32), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("bot_reply", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("rag_chunks", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("escalated", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_logs_session_id", "conversation_logs", ["session_id"])
    op.create_index("ix_conversation_logs_tenant_id", "conversation_logs", ["tenant_id"])
    op.create_index("ix_conversation_logs_sector", "conversation_logs", ["sector"])
    op.create_index("ix_conversation_logs_created_at", "conversation_logs", ["created_at"])

    op.create_table(
        "agent_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("sector", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("intents", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("guardrail_rules", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_configs_tenant_id", "agent_configs", ["tenant_id"])

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("api_key", sa.String(length=128), nullable=False),
        sa.Column("sectors", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("rate_limit", sa.Integer(), nullable=True, server_default="60"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
        sa.UniqueConstraint("api_key"),
    )


def downgrade() -> None:
    op.drop_table("tenants")
    op.drop_index("ix_agent_configs_tenant_id", table_name="agent_configs")
    op.drop_table("agent_configs")
    op.drop_index("ix_conversation_logs_created_at", table_name="conversation_logs")
    op.drop_index("ix_conversation_logs_sector", table_name="conversation_logs")
    op.drop_index("ix_conversation_logs_tenant_id", table_name="conversation_logs")
    op.drop_index("ix_conversation_logs_session_id", table_name="conversation_logs")
    op.drop_table("conversation_logs")
