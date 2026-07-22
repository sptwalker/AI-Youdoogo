"""Proposal-management use-case failures without HTTP metadata."""

from app.contexts.business.proposal_management.domain.errors import ProposalError


class ProposalNotFound(ProposalError):
    """The requested proposal does not exist or is logically deleted."""

    def __init__(self) -> None:
        super().__init__("提案不存在")


class ProposalExpertUnavailable(ProposalError):
    """The AI research use case has no configured expert role."""

    def __init__(self) -> None:
        super().__init__("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")
