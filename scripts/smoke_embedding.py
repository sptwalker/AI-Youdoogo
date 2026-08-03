"""真实冒烟：用 .env 的 DASHSCOPE 密钥对通义 embedding 打一条真实请求，验证 1024 维。

用法：uv run python scripts/smoke_embedding.py
无密钥时打印提示并以退出码 1 结束（会产生极少量真实调用费用）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许以脚本方式直跑
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows GBK 控制台兼容

from app.contexts.foundations.knowledge.embedding_gateway import embed_query  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.knowledge import EMBED_DIM  # noqa: E402


async def _run() -> int:
    if not get_settings().dashscope_api_key:
        print("未配置 DASHSCOPE_API_KEY（请在 .env 中填入），冒烟跳过。")
        return 1
    vec = await embed_query("创想悦动 AI 决策大脑")
    print(f"返回向量维度={len(vec)}（预期 {EMBED_DIM}），前 5 维={vec[:5]}")
    return 0 if len(vec) == EMBED_DIM else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
