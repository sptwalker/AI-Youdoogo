"""Framework-independent Wiki Management rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contexts.foundations.knowledge.wiki_management.contracts import KnowledgeScope
from app.contexts.shared_kernel import RuleViolation


@dataclass(slots=True)
class KnowledgeBase:
    id: uuid.UUID
    name: str
    code: str
    scope: KnowledgeScope
    department_id: uuid.UUID | None = None
    owner_agent_id: uuid.UUID | None = None
    is_confidential: bool = False
    is_default: bool = False
    is_active: bool = True
    description: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise RuleViolation("知识库名称必填")
        if self.scope is KnowledgeScope.DEPARTMENT and self.department_id is None:
            raise RuleViolation("部门知识库需指定所属部门")
        if self.scope is KnowledgeScope.PERSONAL and self.owner_agent_id is None:
            raise RuleViolation("个人知识区需指定归属的智能体")

    def apply_update(
        self,
        *,
        name: str | None,
        is_confidential: bool | None,
        description: str | None,
        is_active: bool | None,
        department_id: uuid.UUID | None,
    ) -> None:
        if name is not None:
            self.name = name
        if is_confidential is not None:
            self.is_confidential = is_confidential
        if description is not None:
            self.description = description
        if is_active is not None:
            self.is_active = is_active
        if department_id is not None:
            self.department_id = department_id
        self.validate()

    def ensure_deletable(self, *, document_count: int) -> None:
        if self.is_default:
            raise RuleViolation("公司公共知识库不可删除")
        if document_count:
            raise RuleViolation(f"该知识库下还有 {document_count} 个文档，请先删除文档")
