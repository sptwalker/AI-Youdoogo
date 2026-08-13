"""SSRF 安全的主机名/URL 校验——纯 stdlib，供任意 connector 基础设施复用。

外部可控 URL 在连接前必须过此校验（防指向内网）：解析主机名的所有 IP，任一命中私有/环回/
链路本地/保留/多播/未指定即判不安全；scheme 限 http/https。无业务依赖、无状态。
`resolve_ips` 抽出为模块级函数，供单测经 `monkeypatch.setattr(net, "resolve_ips", ...)` 注入。
# ponytail: DNS-rebind（校验与连接之间 DNS 变化）为已知残余风险；做「解析全 IP 校验 + 调用方禁
#   自动重定向逐跳复校」，如需强防 rebind 再 pin IP 连接。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def resolve_ips(host: str) -> list[str]:
    """解析主机名到 IP 列表；DNS 失败返空（调用方判不安全）。抽出以便测试注入。"""
    try:
        return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]
    except OSError:
        return []


def host_is_safe(host: str) -> bool:
    """主机所有解析 IP 均非私有/环回/链路本地/保留/多播/未指定才算安全（SSRF 防护）。"""
    ips = resolve_ips(host)
    if not ips:
        return False
    for ip_str in ips:
        try:
            ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        # IPv4-mapped IPv6（::ffff:10.0.0.1）会绕过 v6 判定 → 下沉到映射的 v4 再校验
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def url_is_safe(url: str) -> tuple[bool, str]:
    """scheme 限 http/https + 主机所有 IP 非内网。返回 (是否安全, 拒绝原因)。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "仅支持 http/https 链接"
    host = parsed.hostname
    if not host:
        return False, "URL 缺少主机名"
    if not host_is_safe(host):
        return False, "目标地址指向内网/私有地址，已拒绝（SSRF 防护）"
    return True, ""
