"""
MCP 服务器配置持久化服务

职责：
  - 把界面添加的 MCP 服务器配置写入 mcp_servers 表（此前仅存内存，重启即丢）
  - 启动时合并加载：.env 的 MCP_SERVERS_CONFIG + 数据库记录
  - 维护「服务器名 → 归属用户」映射，供工具层做权限校验

归属模型：
  user_id IS NULL → 全局服务器，所有用户可用
  user_id = N     → 仅用户 N 可用（定制服务器）

⚠️ 安全：stdio transport 会 spawn 任意本地进程（等价 RCE），
   因此只有管理员能添加 stdio 服务器。用户自助定制默认仅允许 sse。
   通过 MCP_ALLOW_USER_CUSTOM 开关控制是否开放用户自助。
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

from app.extensions import db
from app.models import MCPServer

logger = logging.getLogger(__name__)


# 允许用户自助添加的 transport 白名单。
# stdio 被排除：它接受任意 command + args + env 并 spawn 子进程。
USER_ALLOWED_TRANSPORTS = ("sse",)


# ===== 用户级懒连接的状态簿记 =====
#
# 用户定制服务器不在启动时连接（否则要为每个用户 spawn 子进程），
# 改为在该用户 WebSocket 上线时连接。由此带来三个必须处理的问题：
#   1. 同一用户开多个标签页会重复触发 → 用「已尝试」时间戳去重
#   2. 连接失败后每次刷新都重试，反复 spawn 注定失败的子进程 → 负缓存（冷却期）
#   3. 并发触发时的竞态 → _connect_lock 保护簿记
#
# ⚠️ 锁内只做簿记，绝不在锁内执行连接：连接是阻塞操作（单服务器最长 30s），
#    在 eventlet 下持锁阻塞会连带卡住其他 greenlet 的上线流程。

# user_id -> 最近一次「尝试连接」的单调时钟时间戳。
# 无论成功失败都记录，配合 USER_LOAD_COOLDOWN_SECONDS 控制重试频率。
_users_loaded: Dict[int, float] = {}

_connect_lock = threading.Lock()

# 连接失败后的重试冷却时间（秒）。设为 0 表示每次上线都重试。
USER_LOAD_COOLDOWN_SECONDS = 300


def _claim_user_load_slot(user_id: int) -> bool:
    """原子地占用「该用户本轮连接」的执行权。

    Returns:
        True  = 本次调用应负责连接（已抢到执行权，并已写入时间戳）
        False = 冷却期内已有其他调用处理过，本次应跳过

    时间戳在连接**之前**写入：即使连接耗时 30s，期间上线的第二个标签页
    也会因冷却期而跳过，不会重复 spawn 子进程。
    """
    with _connect_lock:
        now = time.monotonic()
        last = _users_loaded.get(user_id)
        if last is not None and (now - last) < USER_LOAD_COOLDOWN_SECONDS:
            return False
        _users_loaded[user_id] = now
        return True


def invalidate_user_load(user_id: Optional[int]):
    """清除某用户的连接簿记，使其下次上线时重新连接。

    必须在这两个时机调用，否则配置改了但不生效：
      - 用户新增 / 更新 / 删除 / 启停了自己的 MCP 服务器
      - 管理员为用户添加了定制服务器
    传 None 清除全部用户的簿记（例如全局配置批量变更后）。
    """
    with _connect_lock:
        if user_id is None:
            _users_loaded.clear()
        else:
            _users_loaded.pop(user_id, None)


def ensure_user_servers_connected(user_id: Optional[int]) -> Dict[str, bool]:
    """连接该用户定制的、且尚未连接的 MCP 服务器。

    调用时机：用户 WebSocket 上线（handle_connect）。
    ⚠️ 这是**阻塞**调用（每个服务器最长 30s），调用方应放到后台任务里执行，
       不要放在连接握手路径上 —— 否则用户要等所有 MCP 服务器连完才能开始聊天。

    幂等且自带节流：
      - 冷却期内重复调用直接返回空 dict（多标签页场景）
      - 已连接的服务器会被跳过（manager 内存态即真相）
      - 连接失败的服务器状态回写为 failed，冷却期后才会重试

    Returns:
        {server_name: 是否连接成功}；被节流跳过时返回空 dict
    """
    if not user_id:
        return {}

    # 节流：冷却期内已有调用处理过该用户
    if not _claim_user_load_slot(user_id):
        logger.debug(f"用户 {user_id} 的 MCP 连接在冷却期内，跳过")
        return {}

    from app.services.tool_service import get_mcp_manager

    results: Dict[str, bool] = {}
    try:
        # 只取该用户的定制服务器；全局服务器已在启动时连接
        servers = MCPServer.query.filter(
            MCPServer.user_id == user_id,
            MCPServer.enabled.is_(True)
        ).all()

        if not servers:
            return {}

        manager = get_mcp_manager()
        for server in servers:
            name = server.name

            # 已连接则跳过（可能是同一进程内重连，或另一个标签页刚连上）
            existing = manager.servers.get(name)
            if existing is not None and existing.is_connected:
                results[name] = True
                continue

            try:
                ok = manager.ensure_connected_sync(name, server.to_connection_config())
            except Exception as e:
                logger.error(f"连接用户 {user_id} 的 MCP 服务器 {name} 异常: {e}", exc_info=True)
                ok = False

            results[name] = ok
            tools_count = (
                len(manager.servers[name].tools)
                if ok and name in manager.servers else 0
            )
            update_runtime_state(
                name,
                status='connected' if ok else 'failed',
                tools_count=tools_count,
                error_message=None if ok else '上线自动连接失败，可在界面点「重连」'
            )

        ok_names = [n for n, v in results.items() if v]
        failed_names = [n for n, v in results.items() if not v]
        logger.info(
            f"用户 {user_id} 的 MCP 定制服务器懒连接完成: "
            f"成功 {ok_names or '无'}" + (f", 失败 {failed_names}" if failed_names else "")
        )

    except Exception as e:
        logger.error(f"用户 {user_id} 的 MCP 懒连接流程异常: {e}", exc_info=True)
        # 流程级异常时清掉簿记，允许下次上线立即重试（不等冷却期）
        invalidate_user_load(user_id)

    return results


class MCPOwnershipError(Exception):
    """用户无权访问某个 MCP 服务器。"""


def _now():
    return datetime.now(timezone.utc)


# ===== 配置读写 =====

def list_server_configs(user_id: Optional[int] = None,
                        include_disabled: bool = False) -> List[MCPServer]:
    """列出可见的 MCP 服务器配置。

    Args:
        user_id: 当前用户 ID。None 表示只返回全局服务器。
        include_disabled: 是否包含 enabled=False 的记录（管理界面需要）
    """
    from sqlalchemy import or_

    query = MCPServer.query
    if user_id is not None:
        query = query.filter(or_(MCPServer.user_id == user_id, MCPServer.user_id.is_(None)))
    else:
        query = query.filter(MCPServer.user_id.is_(None))

    if not include_disabled:
        query = query.filter(MCPServer.enabled.is_(True))

    return query.order_by(MCPServer.id.asc()).all()


def get_server_by_name(name: str) -> Optional[MCPServer]:
    return MCPServer.query.filter_by(name=name).first()


def can_access(server: MCPServer, user_id: Optional[int]) -> bool:
    """判断 user_id 是否有权使用该服务器。

    全局服务器（user_id 为 NULL）对所有登录用户开放；
    定制服务器仅归属者可用。管理员不受限。
    """
    if server is None:
        return False
    if server.user_id is None:
        return True
    if user_id is None:
        return False
    if server.user_id == user_id:
        return True

    # 管理员可访问全部
    from app.models import User
    user = db.session.get(User, user_id)
    return bool(user and user.is_admin)


def upsert_server(name: str,
                  transport: str,
                  config: Dict[str, Any],
                  user_id: Optional[int] = None,
                  source: str = "user") -> MCPServer:
    """新增或更新 MCP 服务器配置（幂等）。

    连接成功与否都会写入记录 —— 配置本身应当持久化，
    这样重启后可以自动重试连接，而不是让用户重新填一遍。
    """
    server = MCPServer.query.filter_by(name=name).first()

    if server is None:
        server = MCPServer(name=name)
        db.session.add(server)

    server.transport = transport
    server.config = config
    server.user_id = user_id
    server.source = source
    server.updated_at = _now()

    db.session.commit()
    logger.info(f"MCP 服务器配置已持久化: name={name}, transport={transport}, "
                f"scope={'global' if user_id is None else f'user:{user_id}'}")
    return server


def delete_server(name: str) -> bool:
    """删除 MCP 服务器配置记录。"""
    server = MCPServer.query.filter_by(name=name).first()
    if server is None:
        return False
    db.session.delete(server)
    db.session.commit()
    logger.info(f"MCP 服务器配置已删除: name={name}")
    return True


def set_enabled(name: str, enabled: bool) -> bool:
    """启用/禁用某个服务器（不删除配置，仅停止加载）。"""
    server = MCPServer.query.filter_by(name=name).first()
    if server is None:
        return False
    server.enabled = enabled
    server.updated_at = _now()
    db.session.commit()
    return True


def update_runtime_state(name: str,
                         status: str,
                         tools_count: int = 0,
                         error_message: Optional[str] = None):
    """回写运行时状态（连接结果、工具数、错误信息）。

    仅更新状态字段，不碰 config —— 避免运行时信息覆盖用户配置。
    """
    server = MCPServer.query.filter_by(name=name).first()
    if server is None:
        return

    server.status = status
    server.tools_count = tools_count
    server.error_message = error_message
    if status == "connected":
        server.last_connected_at = _now()

    db.session.commit()


# ===== 启动时合并加载 =====

def build_effective_configs(env_configs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """合并 .env 配置与数据库配置，返回最终要连接的服务器集合。

    优先级：数据库 > .env（用户通过界面显式添加/修改的应生效）。

    .env 中的服务器会同步一份到数据库（source='env'，user_id=NULL），
    这样它们也能出现在管理界面里、能被统一启停。
    """
    effective: Dict[str, Dict[str, Any]] = {}

    # 1. 先登记 .env 的服务器，并同步到数据库（便于界面统一管理）
    for name, cfg in (env_configs or {}).items():
        transport = cfg.get("transport", "stdio")
        body = {k: v for k, v in cfg.items() if k != "transport"}

        existing = get_server_by_name(name)
        if existing is None:
            upsert_server(name, transport, body, user_id=None, source="env")
        else:
            # 已存在：仅当它源自 env 时才用最新 env 值覆盖，
            # 若用户已在界面上改过（source='user'），不覆盖用户配置
            if existing.source == "env":
                upsert_server(name, transport, body, user_id=existing.user_id, source="env")

    # 2. 从数据库读取全部启用的服务器作为最终集合
    for server in list_server_configs(user_id=None, include_disabled=False):
        # 只取全局服务器用于启动连接。用户定制服务器不在此连接 ——
        # 否则启动时要为每个用户 spawn 子进程，启动时间与内存都不可控。
        # 它们改为在用户 WebSocket 上线时懒连接，见 ensure_user_servers_connected()。
        if server.user_id is None:
            effective[server.name] = server.to_connection_config()

    logger.info(f"MCP 有效配置: {len(effective)} 个全局服务器 {list(effective.keys())}")
    return effective


# ===== 归属校验（供工具层使用）=====
#
# 为什么需要：MCPClientManager.servers 以 name 为键、全局共享，不含归属信息。
# 工具执行时必须能判断「当前用户是否有权调用这个服务器」，
# 否则用户 A 的定制服务器会被用户 B 通过猜测工具名直接调用。
#
# 归属一律查数据库（唯一真相源），不用内存缓存 ——
# 内存缓存在增删服务器或多 worker 部署下会陈旧，而这正是本次要修的问题。

def is_visible_to(server_name: str, user_id: Optional[int]) -> bool:
    """该 MCP 服务器对 user_id 是否可见/可调用。

    fail-closed：数据库里没有这个名字（纯内存临时服务器）一律返回 False。
    """
    server = MCPServer.query.filter_by(name=server_name).first()
    if server is None:
        return False
    return can_access(server, user_id)


def visible_server_names(user_id: Optional[int]) -> List[str]:
    """返回 user_id 有权使用的全部服务器名。"""
    return [s.name for s in list_server_configs(user_id=user_id, include_disabled=False)]
