"""个人经验自动沉淀（docs/27 B1.3）：AI 产出事件 → 写产出人个人知识库。

事件契约（`PERSONAL_KNOWLEDGE_SINK_V1`）与生产者（`enqueue_personal_knowledge_sink`）住
`knowledge_indexing.public` facade；本模块只留消费者 handler，单向依赖 public，
避免 public↔infra 环。消费者由装配期注册到 workflow 事件路由，落个人库。
红线：写个人库属 knowledge_index（AUTOMATIC，内部辅助执行，不外发）；内容可编辑/删除。

# ponytail: 先接「直连 AI 产出」一个源，文档/纪要/复盘留 backlog——事件契约已就位，
#           追加源只需在各产出点再 enqueue 同一 event_type 即可，handler 无需改。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    PERSONAL_KNOWLEDGE_SINK_V1 as PERSONAL_KNOWLEDGE_SINK_V1,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    build_knowledge_index_port,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    enqueue_personal_knowledge_sink as enqueue_personal_knowledge_sink,
)
from app.contexts.foundations.knowledge.wiki_management.public import ensure_personal_kb


def handles(event_type: str) -> bool:
    return event_type == PERSONAL_KNOWLEDGE_SINK_V1


async def handle_personal_knowledge_sink(session: AsyncSession, event: Any) -> None:
    """消费沉淀事件：落产出人个人知识库。source_record_id 复用为文档 id → handler 重入幂等。"""
    payload = event.payload or {}
    owner_user_id = uuid.UUID(str(payload["owner_user_id"]))
    source_record_id = uuid.UUID(str(payload["source_record_id"]))
    kb_id = await ensure_personal_kb(session, owner_user_id)
    await build_knowledge_index_port(session).index_text(
        IndexTextCommand(
            title=str(payload["title"]),
            text=str(payload["content"]),
            uploader_id=owner_user_id,
            knowledge_base_id=kb_id,
            category="ai_output",
            document_id=source_record_id,
        )
    )
