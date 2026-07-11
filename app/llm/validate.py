"""LLM 输出格式校验 — 移植自 Bottleneck-Hunter llm_clients.validate。

只判「明显坏」，宁漏勿误杀：
- 空输出 → 坏
- 看起来是 JSON（以 {/[ 或 ```json 开头）但解析失败 → 坏
- 极短且以拒答话术开头 → 坏（很保守）
- 其余（含中文自由分析）一律放行 —— 绝不做语义正确性判定。

角色无关：靠内容形态自判。流式路径不校验（首 token 后无法安全换模型）。
相对源实现的减法：删除 BH_SCHEDULER_VALIDATE 环境开关（校验恒开）。
"""

from __future__ import annotations

import json
import re
from typing import Any

_REFUSAL_MARKERS = (
    "作为一个ai", "作为ai", "作为人工智能", "我无法提供", "我不能提供",
    "as an ai", "i cannot assist", "i'm unable to", "i am unable to",
)
_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*(.+?)\s*```$", re.S)


def _strip_fence(t: str) -> str:
    """剥掉包裹全文的 ```json code fence（若有）。"""
    m = _FENCE_RE.match(t)
    return m.group(1).strip() if m else t


def validate_output(message: Any) -> tuple[bool, str]:
    """校验模型输出格式，返回 (ok, reason)。ok=False 表示明显坏、应触发换模型。"""
    text = getattr(message, "content", message)
    if not isinstance(text, str):
        return True, ""  # 工具调用/非文本消息不判
    t = text.strip()
    if not t:
        return False, "输出为空"
    body = _strip_fence(t)
    # 看起来是 JSON 但解析失败。raw_decode 接受「合法 JSON + 尾随说明文字」，
    # 只判真正结构损坏，贯彻「宁漏勿误杀」。
    if body[:1] in ("{", "["):
        try:
            json.JSONDecoder().raw_decode(body)
        except ValueError:
            return False, "JSON格式损坏"
    # 极短 + 拒答话术开头（很保守，避免误杀正常短答）
    low = t.lower()
    if len(t) < 120 and any(low.startswith(m) or m in low[:40] for m in _REFUSAL_MARKERS):
        return False, "疑似拒答"
    return True, ""
