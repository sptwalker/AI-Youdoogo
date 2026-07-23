"""Framework-independent Collaboration Requests failures."""


class CollaborationRequestError(Exception):
    """Base class for user-safe collaboration failures."""


class InvalidReviewDecision(CollaborationRequestError):
    def __init__(self) -> None:
        super().__init__("decision 仅支持 approve/reject")


class CollaborationReviewNotAllowed(CollaborationRequestError):
    def __init__(self, current_status: str) -> None:
        super().__init__(f"请求当前状态 {current_status}，不可复核")
