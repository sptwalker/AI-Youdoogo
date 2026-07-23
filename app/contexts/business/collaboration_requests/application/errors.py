"""Collaboration Requests use-case failures."""

from app.contexts.business.collaboration_requests.domain.errors import (
    CollaborationRequestError,
)


class CollaborationAuthorizationNotFound(CollaborationRequestError):
    def __init__(self) -> None:
        super().__init__("授权不存在")


class CollaborationRequestNotFound(CollaborationRequestError):
    def __init__(self) -> None:
        super().__init__("协作请求不存在")


class CollaborationReviewForbidden(CollaborationRequestError):
    def __init__(self) -> None:
        super().__init__("仅目标部门主管或管理员可复核")
