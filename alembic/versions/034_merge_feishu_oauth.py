"""merge AI platform and Feishu OAuth migration branches

Revision ID: 034_merge_feishu_oauth
Revises: 033_eval_case, 019_feishu_oauth
Create Date: 2026-07-20

GitHub 与 GitLab 从 018_ui_secrets 分别演进。此迁移只汇合版本图，
不执行额外的数据库结构变更。
"""

from collections.abc import Sequence

revision: str = "034_merge_feishu_oauth"
down_revision: tuple[str, str] = ("033_eval_case", "019_feishu_oauth")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
