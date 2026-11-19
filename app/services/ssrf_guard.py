"""SSRF 防护：校验用户提交的 URL 是否指向公网。

背景：MCP 的 sse transport 接受任意 url，由**服务端**发起 HTTP 请求。
若不校验，用户可填 `http://169.254.169.254/latest/meta-data/` 读云厂商
实例元数据（含临时凭证），或填 `http://127.0.0.1:5432/` 探测本机服务 ——
经典 SSRF，且响应内容会回流到工具列表/调用结果，构成有读回通道的 SSRF。

本模块只负责「判断 URL 是否安全」，不负责权限（谁能添加 MCP 由路由层决定）。

⚠️ 已知残余风险 —— DNS rebinding / TOCTOU：
本模块在**校验时**解析 DNS，但真正发请求的是 mcp 的 sse_client（httpx），
它会**再解析一次**。若攻击者的权威 DNS 对两次查询返回不同 IP
（第一次公网、第二次 127.0.0.1），校验就被绕过。
彻底解法是「校验后 pin 住解析到的 IP，用该 IP 连接」，但 mcp 2.3.0 的
`sse_client` 只暴露 `httpx_client_factory(headers, timeout, auth)`，
无法注入自定义 transport，故当前无法 pin。
调用方 `_connect_sse` 会复检一次以缩小窗口，但不能消除。
若你的部署暴露在公网且开放用户自助添加 sse，请改用
`MCP_SSE_ALLOWED_HOSTS` 显式白名单（见 validate_sse_url）。
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# sse_client 底层是 httpx，只认 http/https。
# 显式白名单而非黑名单：file:// gopher:// dict:// 等一律拒绝。
ALLOWED_SCHEMES = frozenset({"http", "https"})

# 知名云厂商元数据服务地址。
# 169.254.169.254 落在 link-local 段、fd00:ec2::254 落在 ULA 段，
# 已被下面的通用规则覆盖；此处显式列出是为了：
#   1. 给出更明确的错误信息（这是 SSRF 最高价值的目标）
#   2. 纵深防御 —— 不依赖 ipaddress 各版本对 is_private 的定义完全一致
_METADATA_ADDRESSES = frozenset({
    "169.254.169.254",   # AWS / GCP / Azure / 阿里云 / 腾讯云
    "169.254.170.2",     # AWS ECS 容器凭证
    "fd00:ec2::254",     # AWS IPv6 元数据
})

# DNS 解析最多返回多少个地址就放弃（防恶意 DNS 返回海量记录拖慢请求）
_MAX_RESOLVED_ADDRESSES = 32


class SSRFValidationError(ValueError):
    """URL 未通过 SSRF 校验。str(e) 可直接作为面向用户的错误信息。"""


def _classify_ip(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> str | None:
    """该 IP 被拒绝的原因；允许连接则返回 None。"""
    # IPv4-mapped IPv6（::ffff:127.0.0.1）必须先还原成 IPv4 再判断 ——
    # 否则它的 is_loopback / is_private 均为 False，是最常见的绕过手法。
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    # IPv4-in-IPv6（::127.0.0.1 形式，非标准但部分解析器接受）
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        ip = ip.sixtofour

    if str(ip) in _METADATA_ADDRESSES:
        return "云厂商元数据服务地址"
    if ip.is_loopback:
        return "环回地址（127.0.0.0/8、::1）"
    if ip.is_link_local:
        return "链路本地地址（169.254.0.0/16，含云元数据服务）"
    if ip.is_private:
        return "内网私有地址（10/8、172.16/12、192.168/16、fc00::/7 等）"
    if ip.is_multicast:
        return "组播地址"
    if ip.is_unspecified:
        return "未指定地址（0.0.0.0、::）"
    if ip.is_reserved:
        return "保留地址"

    # 最终兜底：只放行「全球可路由」地址。
    # ⚠️ 这一条不是冗余 —— 实测 Python 3.14 的 ipaddress 对以下地址
    #    is_private / is_reserved 均为 False，只有 is_global 是 False：
    #      100.64.0.1（RFC 6598 CGNAT，运营商内网，SSRF 常用目标）
    #    若只靠前面几个 is_* 判断，这些地址会被放行。
    #    已验证 8.8.8.8 / 1.1.1.1 / api.github.com / pypi.org（含 IPv6）
    #    的 is_global 均为 True，不会误伤正常公网服务。
    if not ip.is_global:
        return "非全球可路由地址（如 100.64/10 CGNAT 运营商内网）"

    return None


def _parse_ip_literal(text: str) -> "ipaddress.IPv4Address | ipaddress.IPv6Address | None":
    """把字符串当 IP 字面量解析；不是合法 IP 则返回 None。"""
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _resolve_all_ips(host: str, port: int | None) -> list["ipaddress.IPv4Address | ipaddress.IPv6Address"]:
    """解析 host 的**全部** A/AAAA 记录。

    ⚠️ 必须检查所有记录而非第一条：攻击者可让权威 DNS 返回
    「一个公网 IP + 一个 127.0.0.1」，客户端可能挑后者连接。
    """
    service = str(port) if port else None
    try:
        infos = socket.getaddrinfo(host, service, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFValidationError(f"域名无法解析：{host}（{e.strerror or e}）") from e

    ips = []
    seen = set()
    for info in infos:
        sockaddr = info[4]
        raw = sockaddr[0]
        if not raw:
            continue
        # IPv6 的 sockaddr[0] 可能带 scope id（fe80::1%en0），
        # ipaddress 不认 %scope，必须先剥掉。
        raw = raw.split("%", 1)[0]
        if raw in seen:
            continue
        seen.add(raw)
        ip = _parse_ip_literal(raw)
        if ip is None:
            # 解析器返回了无法解析的地址 —— fail-closed
            raise SSRFValidationError(f"地址解析结果异常，已拒绝：{raw}")
        ips.append(ip)
        if len(ips) >= _MAX_RESOLVED_ADDRESSES:
            raise SSRFValidationError(f"域名 {host} 解析出的地址过多，已拒绝")

    if not ips:
        raise SSRFValidationError(f"域名 {host} 未解析出任何地址")
    return ips


def validate_sse_url(raw_url, allowed_hosts: "set[str] | frozenset[str] | None" = None) -> str:
    """校验 sse MCP 服务器的 URL。通过则返回原 URL，否则抛 SSRFValidationError。

    Args:
        raw_url: 用户提交的 URL
        allowed_hosts: 显式主机白名单（小写，不含端口）。命中则**跳过 IP 校验**。
            这是对抗 DNS rebinding 的唯一可靠手段 —— 白名单里的主机由管理员
            事先确认过，即使它解析到内网也放行。
            来自 config.MCP_SSE_ALLOWED_HOSTS（逗号分隔）。

    Raises:
        SSRFValidationError: 拒绝原因，str(e) 可直接回给前端
    """
    if not raw_url or not isinstance(raw_url, str):
        raise SSRFValidationError("sse 类型必须提供 url")

    url = raw_url.strip()
    if len(url) > 2048:
        raise SSRFValidationError("url 过长（上限 2048 字符）")

    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise SSRFValidationError(f"url 格式非法：{e}") from e

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFValidationError(
            f"不支持的协议 '{parsed.scheme}'，sse 只允许 http / https"
        )

    # urlparse 对 "http://user:pass@host" 会解析出 username/password。
    # 不禁止（部分 MCP 服务用 basic auth），但要警惕它被用来混淆 host：
    # "http://expected.com@evil.com/" 的真实 host 是 evil.com。
    # 我们一律以 parsed.hostname 为准，所以这类混淆天然无效 —— 但仍拒绝
    # 含 @ 的写法，避免用户误以为自己在连前面那个域名。
    if "@" in (parsed.netloc or ""):
        raise SSRFValidationError(
            "url 中不得包含 '@'（凭据请放在 headers 的 Authorization 里；"
            "带 @ 的写法容易被误读为连接前一个域名）"
        )

    host = parsed.hostname
    if not host:
        raise SSRFValidationError("url 缺少主机名")

    # port 可能因 "http://host:/path" 这种写法而抛 ValueError
    try:
        port = parsed.port
    except ValueError as e:
        raise SSRFValidationError(f"url 端口非法：{e}") from e

    host_key = host.lower().strip("[]")
    if allowed_hosts and host_key in {h.lower() for h in allowed_hosts}:
        logger.info("sse url 命中显式白名单，跳过 SSRF 校验: %s", host_key)
        return raw_url

    # 先看 host 本身是不是 IP 字面量（含 ::ffff:127.0.0.1 这类映射写法）
    literal = _parse_ip_literal(host_key)
    if literal is not None:
        reason = _classify_ip(literal)
        if reason:
            raise SSRFValidationError(f"禁止连接{reason}：{host}")
        return raw_url

    # 是域名：解析并检查全部记录
    for ip in _resolve_all_ips(host, port):
        reason = _classify_ip(ip)
        if reason:
            raise SSRFValidationError(
                f"禁止连接{reason}：{host} 解析到 {ip}"
            )

    return raw_url


def parse_allowed_hosts(raw: str) -> frozenset:
    """把 config 里逗号分隔的白名单字符串解析成集合。"""
    if not raw or not isinstance(raw, str):
        return frozenset()
    return frozenset(
        item.strip().lower().strip("[]")
        for item in raw.split(",")
        if item.strip()
    )
