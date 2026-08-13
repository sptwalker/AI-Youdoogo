"""通用网页读取 connector（抓 URL → trafilatura 抽正文）。

与 web_search 的差异：这里是「取一个网址的正文」而非「调搜索 API」，故无 api_key、无 provider 预设，
但**必须做 SSRF 防护**（外部可控 URL 可指向内网）。无 URL/命中 SSRF/httpx 错/抽取空 → 返空 +
结构化原因、**不抛穿**（仿 web_search，不打断桌面消息流）。日志只记 host + `type(exc).__name__`，
绝不打完整 URL。无 DB 依赖、无状态。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from app.platform import net

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 20
_MAX_BYTES = 2 * 1024 * 1024  # 响应正文读取上限 ~2MB，防超大页面 OOM
_MAX_TEXT = 8000  # 抽取正文截断（喂回模型的素材上限）
_MAX_REDIRECTS = 3  # 手动逐跳跟随上限；每跳重做 SSRF 校验
_USER_AGENT = "Mozilla/5.0 (compatible; YoudoogoBot/1.0)"


@dataclass(frozen=True, slots=True)
class ReadUrlOutcome:
    """归一化正文 + 结构化失败原因（交由上层折进 note，不抛穿）。"""

    results: list[dict[str, str]]
    reason: str = ""


def _decode(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:  # 非法编码名 → 回落 utf-8
        return raw.decode("utf-8", errors="replace")


def _extract(html: str, url: str) -> ReadUrlOutcome:
    if not html.strip():
        return ReadUrlOutcome(results=[], reason="网页内容为空")
    # trafilatura 无类型 stub（ignore_missing_imports）→ 返回值为 Any，下方按运行时形状处理
    text = trafilatura.extract(html, include_comments=False, include_tables=True)
    if not text or not str(text).strip():
        return ReadUrlOutcome(results=[], reason="未能从网页提取正文（可能是脚本渲染页或空页）")
    title = ""
    meta = trafilatura.extract_metadata(html)
    if meta is not None and getattr(meta, "title", None):
        title = str(meta.title)
    return ReadUrlOutcome(
        results=[{"title": title, "url": url, "text": str(text).strip()[:_MAX_TEXT]}]
    )


class UrlReader:
    """抓单个 URL 正文：SSRF 防护 + 禁自动重定向逐跳校验 + 大小/类型上限 + trafilatura 抽正文。"""

    async def fetch(
        self,
        url: str,
        *,
        timeout: int = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> ReadUrlOutcome:
        # ponytail: DNS-rebind（校验与连接之间 DNS 变化）为已知残余风险；首版做「解析全 IP 校验 +
        # 禁自动重定向逐跳校验」，如需强防 rebind 再 pin IP 连接。
        current = url
        raw = b""
        encoding = "utf-8"
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=transport, follow_redirects=False
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    ok, reason = net.url_is_safe(current)
                    if not ok:
                        return ReadUrlOutcome(results=[], reason=reason)
                    async with client.stream("GET", current, headers=headers) as response:
                        if response.is_redirect:
                            location = response.headers.get("location", "")
                            if not location:
                                return ReadUrlOutcome(results=[], reason="重定向缺少目标地址")
                            current = urljoin(current, location)  # 下一跳循环开头重做 SSRF 校验
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").lower()
                        if "html" not in content_type and "text/plain" not in content_type:
                            return ReadUrlOutcome(
                                results=[],
                                reason=f"目标不是网页内容（{content_type[:40] or '未知类型'}）",
                            )
                        async for chunk in response.aiter_bytes():
                            raw += chunk
                            if len(raw) >= _MAX_BYTES:
                                raw = raw[:_MAX_BYTES]  # 流式读到上限即停，不整页进内存
                                break
                        encoding = response.encoding or "utf-8"
                        break
                else:
                    return ReadUrlOutcome(results=[], reason="重定向次数过多")
        except httpx.HTTPError as exc:
            # 不复用 str(exc)：httpx 异常文本可能含完整 URL
            logger.warning(
                "网页读取失败 host=%s err=%s", urlparse(current).hostname, type(exc).__name__
            )
            return ReadUrlOutcome(results=[], reason=f"网页读取失败（{type(exc).__name__}）")
        return _extract(_decode(raw, encoding), url)
