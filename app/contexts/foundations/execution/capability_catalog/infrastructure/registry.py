"""Current in-process catalog of versioned capability definitions."""

from __future__ import annotations

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
    CapabilityRisk,
    CapabilitySideEffect,
)

CAPABILITY_DEFINITIONS = (
    CapabilityDefinition(
        key="env_context",
        version="1.0",
        label="环境快照",
        description="感知组织架构、AI 花名册、真人用户和数据接口",
        input_schema_json='{"type":"object","additionalProperties":false}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        permission_keys=(),
        handler_identity="environment.snapshot",
        feature_flag="agent_env_context",
    ),
    CapabilityDefinition(
        key="collab",
        version="1.0",
        label="协作原语",
        description="咨询其他 AI 或发起需真人复核的跨部门协作",
        input_schema_json='{"type":"object","required":["kind"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.MEDIUM,
        side_effect=CapabilitySideEffect.INTERNAL_WRITE,
        permission_keys=("collab",),
        handler_identity="collaboration.execute",
        feature_flag="agent_collab_protocol",
    ),
    CapabilityDefinition(
        key="deliver",
        version="1.0",
        label="文件交付",
        description="生成文件并交付到用户工作桌面",
        input_schema_json='{"type":"object","required":["name","format","body"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.MEDIUM,
        side_effect=CapabilitySideEffect.EXTERNAL_WRITE,
        permission_keys=("deliver",),
        handler_identity="deliverable.create",
        feature_flag="agent_deliver",
    ),
    CapabilityDefinition(
        key="data_query",
        version="1.0",
        label="数据取数",
        description="通过只读 SQL 护栏查询授权运营数据",
        input_schema_json='{"type":"object","required":["sql"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        permission_keys=("data_query",),
        handler_identity="governed_data_query.execute",
        feature_flag="agent_data_query",
    ),
    CapabilityDefinition(
        key="read_url",
        version="1.0",
        label="读网页",
        description="抓取指定网址正文，结合知识库综合成报告（只读，无副作用）",
        input_schema_json='{"type":"object","required":["url"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        permission_keys=("read_url",),
        handler_identity="read_url.execute",
        feature_flag="agent_read_url",
    ),
    CapabilityDefinition(
        key="read_attachment",
        version="1.0",
        label="读附件",
        description="解析本轮用户上传附件正文，结合知识库综合成报告（只读，仅限本轮受信附件）",
        input_schema_json='{"type":"object","required":["storage_path","name"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        permission_keys=("read_attachment",),
        handler_identity="read_attachment.execute",
        feature_flag="agent_read_attachment",
    ),
    CapabilityDefinition(
        key="knowledge_search",
        version="1.0",
        label="检索历史案例",
        description="在可见知识库中检索同类历史案例并回喂综合（只读，无副作用，无同类如实声明）",
        input_schema_json='{"type":"object","required":["query"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        permission_keys=("knowledge_search",),
        handler_identity="knowledge_search.execute",
        feature_flag="agent_knowledge_search",
    ),
    CapabilityDefinition(
        key="compose_feishu",
        version="1.0",
        label="整理飞书草稿",
        description="把内容整理成飞书云文档/多维表格草稿（红线，先出草稿待真人验收后才发布，本步不调飞书）",
        input_schema_json='{"type":"object"}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.MEDIUM,
        side_effect=CapabilitySideEffect.INTERNAL_WRITE,
        permission_keys=("compose_feishu",),
        handler_identity="feishu_output.compose",
        feature_flag="agent_feishu_output",
    ),
    CapabilityDefinition(
        key="feishu_notify",
        version="1.0",
        label="飞书运营群播报",
        description="把已确认的结论/通知播报到固定飞书运营群（运维旁路，best-effort，无真人停点）",
        input_schema_json='{"type":"object","required":["text"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.MEDIUM,
        side_effect=CapabilitySideEffect.EXTERNAL_WRITE,
        permission_keys=("feishu_notify",),
        handler_identity="feishu_notify.broadcast",
        feature_flag="agent_feishu_notify",
    ),
    CapabilityDefinition(
        key="feishu_notify_person",
        version="1.0",
        label="整理定向飞书草稿",
        description="把已确认的简报/结论整理成定向飞书草稿（红线·先出草稿待真人验收后才发，本步不调飞书）",
        input_schema_json='{"type":"object"}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.MEDIUM,
        side_effect=CapabilitySideEffect.INTERNAL_WRITE,
        permission_keys=("feishu_notify_person",),
        handler_identity="feishu_notify_person.compose",
        feature_flag="agent_feishu_notify_person",
        default_enabled=False,
    ),
    CapabilityDefinition(
        key="knowledge_index",
        version="1.0",
        label="留存知识库",
        description="把已确认的结论/报告留存到公司知识库（内部写入·可检索复用·非对外发布）",
        input_schema_json='{"type":"object","required":["title","body"]}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.INTERNAL_WRITE,
        permission_keys=("knowledge_index",),
        handler_identity="knowledge_indexing.index_text",
        feature_flag="agent_knowledge_index",
    ),
)


class InMemoryCapabilityCatalog:
    def __init__(
        self, definitions: tuple[CapabilityDefinition, ...] = CAPABILITY_DEFINITIONS
    ) -> None:
        self._definitions = definitions
        self._by_key = {definition.key: definition for definition in definitions}

    async def resolve(self, key: str, version: str | None) -> CapabilityDefinition | None:
        definition = self._by_key.get(key)
        if definition is None:
            return None
        if version is not None and version != definition.version:
            return None
        return definition

    async def list_definitions(self) -> tuple[CapabilityDefinition, ...]:
        return self._definitions
