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
