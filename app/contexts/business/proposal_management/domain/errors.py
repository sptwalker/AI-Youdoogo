"""Proposal-management business rule failures without delivery concerns."""


class ProposalError(Exception):
    """Base class for user-safe proposal-management failures."""


class ProposalResearchNotAllowed(ProposalError):
    """AI research cannot run after a proposal has reached a terminal state."""

    def __init__(self) -> None:
        super().__init__("提案已完成评审，不可再预研")


class InvalidProposalDecision(ProposalError):
    """A human review supplied an unsupported decision."""

    def __init__(self) -> None:
        super().__init__("decision 仅支持 approve / reject")


class ProposalReviewNotAllowed(ProposalError):
    """A proposal is not in the reviewed state required for human review."""

    def __init__(self, current_status: str) -> None:
        super().__init__(f"提案当前状态 {current_status} 不可评审（需先完成 AI 预研至 reviewed）")


class ProposalNotApproved(ProposalError):
    """A proposal cannot be converted before human approval."""

    def __init__(self) -> None:
        super().__init__("仅『已通过』的提案可转任务卡（决议须真人确认）")


class ProposalAlreadyConverted(ProposalError):
    """A proposal cannot create more than one task card."""

    def __init__(self) -> None:
        super().__init__("该提案已转过任务卡")
