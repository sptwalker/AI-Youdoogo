"""后台步骤异步远端执行的线协议常量（docs/23 §6.3）。

放在 platform.eventing（传输层）而非某个 Context，好让出站 relay、入站 http、runtime 分叉点
共用同一组字面量而不产生 platform→context 反向依赖（runtime 侧 import 本模块 = context→platform）。
"""

from __future__ import annotations

STEP_READY_EVENT = "workflow.step.ready.v1"  # youdoo→expert：步骤就绪、请远端执行
EXPERT_COMPLETED_EVENT = "expert.execution.completed.v1"  # expert→youdoo：执行完成、请唤醒停车 step
REMOTE_SENTINEL = "remote-expert"  # 停车 step 的 lease_owner；与真人停点(WAITING_HUMAN)天然可辨

# 网关转发令牌的 aud/scope（docs/23 §6.4/§6.5）：rich sync 与异步 step.ready 两条转发点共用同一
# 字面量。放此（platform.eventing）供 relay 出站注入与 context 侧 mint 共享，避免各持一份漂移。
GATEWAY_AUDIENCE = "ai-model-gateway"
LLM_COMPLETE_SCOPE = "llm:complete"

# 工具调用环回调端点 scope（docs/23 §6.8）：youdoo 同步 Provider 端点（capability_execution
# entrypoint）与 rich sync mint（agent_execution）共用同一字面量，避免各持一份漂移。
CAPABILITIES_EXECUTE_SCOPE = "capabilities:execute"

# 工具广告（docs/23 §6.8）：capabilities_token 非空时追加进 global_prompt / 经 tool_advert 随体，
# 教模型用文本标记调 data_query。放此（platform.eventing）供 rich sync 的 remote_prepare_adapter
# 与异步 step.ready 的 StepReadyRelay 共享单一真源。ponytail: 首版单工具硬编码，多工具改 catalog。
DATA_QUERY_TOOL_ADVERT = (
    "\n\n[可用工具] 需要查询业务数据时可调用 data_query 工具。调用方式：单独输出一行以下格式的标记"
    "（哨兵包裹单行 JSON），系统会执行并把结果回灌给你，你再据结果继续回答：\n"
    "<<<CAPABILITY_CALL>>>\n"
    '{"capability":"data_query","arguments":{"sql":"你的只读 SQL"}}\n'
    "<<<END>>>\n"
    "不需要数据时正常作答，不要输出该标记。"
)
