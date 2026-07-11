"""真实冒烟：用 .env 里的 DeepSeek 密钥问一句 ping（会产生极少量真实调用费用）。

用法：uv run python scripts/smoke_llm.py
无密钥时打印提示并以退出码 1 结束。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许以脚本方式直跑
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows GBK 控制台兼容

from app.core.config import get_settings  # noqa: E402
from app.llm import create_llm  # noqa: E402


def main() -> int:
    """执行冒烟：deepseek-chat 回答 'ping'，打印回复。"""
    settings = get_settings()
    if not settings.deepseek_api_key:
        print("未配置 DEEPSEEK_API_KEY（请在 .env 中填入），冒烟跳过。")
        return 1
    llm = create_llm("deepseek", "deepseek-chat", with_fallback=False, temperature=0)
    reply = llm.invoke("ping")
    print(reply.content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
