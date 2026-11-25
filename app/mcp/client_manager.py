"""
MCP Client Manager - 管理 MCP 服务器连接和工具调用

架构：所有 MCP 异步操作都在一个持久后台事件循环线程上执行，
避免与 Flask/eventlet 的同步上下文冲突。MCPClientManager 对外提供
同步接口（run_sync），内部自动调度到后台线程。
"""
import asyncio
import json
import logging
import threading
from typing import Dict, List, Optional, Any, Awaitable, Callable, Iterable

# 延迟导入 mcp 库，避免未安装时导致启动失败
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    sse_client = None

logger = logging.getLogger(__name__)


# sse URL 的主机白名单（来自 config.MCP_SSE_ALLOWED_HOSTS）。
# 模块级而非 current_app：_connect_sse 运行在 MCP 专用事件循环线程上，
# 该线程没有 Flask app context，读 current_app 必然 RuntimeError。
# 由 create_app() 调用 configure_sse_guard() 注入，进程内全局生效。
_sse_allowed_hosts: Optional[frozenset] = None

# MCP 连接超时（秒）。同样是模块级 + 注入，原因同 _sse_allowed_hosts。
#
# connect() 原先把 30s 硬编码成 range(300) 次 0.1s 轮询，注释里写着"最多等待 30 秒"
# 却没有任何常量承载这个语义，改起来要同时动注释和循环次数，极易失配。
CONNECT_TIMEOUT_SECONDS = 30.0

# sse_client 的 HTTP 超时。mcp 的默认值是 **5.0 秒**（实测 inspect.signature 确认），
# 对远端 MCP 服务偏紧：握手慢于 5s 就失败，且异常被 anyio 包成 ExceptionGroup，
# 日志里看不出是超时，排查成本很高。
SSE_HTTP_TIMEOUT_SECONDS = 30.0

# sse_client 的「等待下一个 SSE 事件」超时，mcp 默认 300s。
# ⚠️ 这个不能设太短：它是**空闲连接**的存活上限，不是握手超时。
# 一个空闲的 MCP 服务器在 300s 内没推任何事件就会被断开。
SSE_READ_TIMEOUT_SECONDS = 300.0


def configure_mcp_timeouts(connect=None, sse_http=None, sse_read=None) -> None:
    """注入 MCP 超时配置。应在 create_app() 中、启动连接之前调用一次。

    与 configure_sse_guard 同理：连接跑在 MCP 专用事件循环线程上，
    那里读不到 Flask app context，只能靠模块级变量传配置。
    传 None 的参数保持当前值，便于只覆盖其中一项。
    """
    global CONNECT_TIMEOUT_SECONDS, SSE_HTTP_TIMEOUT_SECONDS, SSE_READ_TIMEOUT_SECONDS
    if connect is not None:
        CONNECT_TIMEOUT_SECONDS = float(connect)
    if sse_http is not None:
        SSE_HTTP_TIMEOUT_SECONDS = float(sse_http)
    if sse_read is not None:
        SSE_READ_TIMEOUT_SECONDS = float(sse_read)
    logger.info(
        f"MCP 超时已配置: connect={CONNECT_TIMEOUT_SECONDS}s, "
        f"sse_http={SSE_HTTP_TIMEOUT_SECONDS}s, sse_read={SSE_READ_TIMEOUT_SECONDS}s"
    )


def configure_sse_guard(allowed_hosts) -> None:
    """注入 sse SSRF 白名单配置。应在 create_app() 中调用一次。

    Args:
        allowed_hosts: 可迭代的主机名集合（set/frozenset/list），None 表示空白名单。
    """
    global _sse_allowed_hosts
    if not allowed_hosts:
        _sse_allowed_hosts = frozenset()
    else:
        _sse_allowed_hosts = frozenset(
            str(h).strip().lower().strip("[]") for h in allowed_hosts if str(h).strip()
        )
    logger.info(f"MCP sse SSRF 白名单已配置: {sorted(_sse_allowed_hosts) or '（空，全部主机都校验）'}")


def _get_or_create_event_loop():
    """获取当前线程的事件循环，没有则创建"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


class MCPServerConnection:
    """单个 MCP 服务器的连接管理"""

    def __init__(self, name: str, server_config: Dict[str, Any]):
        """
        Args:
            name: 服务器名称（也作为工具名前缀，如 filesystem__read_file）
            server_config:
                {
                    "transport": "stdio" | "sse",
                    "command": str (stdio),
                    "args": list (stdio),
                    "env": dict (stdio),
                    "url": str (sse),
                    "headers": dict (sse)
                }
        """
        self.name = name
        self.config = server_config
        self.transport = server_config.get('transport', 'stdio')
        self.session: Optional[ClientSession] = None
        self.tools: List[Dict[str, Any]] = []
        self._connected = False
        self._stop_event: Optional[asyncio.Event] = None

    async def connect(self) -> bool:
        """连接服务器并拉取工具列表"""
        if not MCP_AVAILABLE:
            logger.error("MCP library not installed, cannot connect")
            return False

        try:
            self._stop_event = asyncio.Event()
            
            # 在后台任务中启动连接
            if self.transport == 'stdio':
                connect_task = asyncio.create_task(self._connect_stdio())
            elif self.transport == 'sse':
                connect_task = asyncio.create_task(self._connect_sse())
            else:
                logger.error(f"Unsupported transport: {self.transport}")
                return False
            
            # 等待连接就绪（上限 CONNECT_TIMEOUT_SECONDS，按 0.1s 粒度轮询）
            for _ in range(int(CONNECT_TIMEOUT_SECONDS / 0.1)):
                if self._connected:
                    return True
                if connect_task.done():
                    # 任务完成但连接未建立，说明失败了
                    try:
                        await connect_task
                    except Exception as e:
                        logger.error(f"Connect task failed: {e}")
                    return False
                await asyncio.sleep(0.1)
            
            # ⚠️ 超时必须 cancel 任务，否则子进程泄漏。
            # _connect_stdio / _connect_sse 内部是 `async with stdio_client(...)`，
            # 那个上下文管理器持有 npx/uvx 拉起的子进程。只 return False 而留着
            # 任务继续跑，子进程就成了孤儿 —— 反复重连会累积几十个僵尸进程
            # （atexit 钩子只能兜住退出时还挂在 manager 上的连接，兜不住这种）。
            #
            # cancel 后必须 await，让 CancelledError 真正传播进去、触发
            # async with 的 __aexit__ 去 kill 子进程。不 await 的话取消只是
            # 「打了个标记」，我们却已经返回了，清理根本没发生。
            logger.error(
                f"Timeout waiting for MCP server {self.name} to connect "
                f"({CONNECT_TIMEOUT_SECONDS}s)，取消连接任务以回收子进程"
            )
            connect_task.cancel()
            try:
                await connect_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                # 取消过程中底层可能抛出被包装的异常，记录但不影响返回结果
                logger.warning(f"取消 {self.name} 连接任务时出现异常: {e}")
            self._connected = False
            self.session = None
            return False
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.name}: {e}", exc_info=True)
            self._connected = False
            return False

    async def _connect_stdio(self):
        """通过 stdio 连接到 MCP 服务器（在后台任务中运行）"""
        import os
        
        command = self.config.get('command')
        args = self.config.get('args', [])
        # 合并环境变量：继承父进程环境 + 配置中的额外变量
        config_env = self.config.get('env', {}) or {}
        env = {**os.environ, **config_env} if config_env else None

        if not command:
            raise ValueError("stdio transport requires 'command' parameter")

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self.session = session
                
                await self._list_tools()
                self._connected = True
                logger.info(f"Connected to MCP server: {self.name} ({len(self.tools)} tools)")
                
                await self._stop_event.wait()
                
                self._connected = False
                self.session = None

    async def _connect_sse(self):
        """通过 SSE 连接到 MCP 服务器（在后台任务中运行）"""
        url = self.config.get('url')
        headers = self.config.get('headers', {})

        if not url:
            raise ValueError("sse transport requires 'url' parameter")

        # 纵深防御：连接前复检 SSRF。
        # 路由层已校验过，但这里的配置还可能来自：
        #   - .env 的 MCP_SERVERS_CONFIG（不经过路由）
        #   - 管理员直接改数据库
        #   - reconnect 接口（只校验归属，不校验 url）
        # 复检可把 DNS rebinding 的时间窗从「添加时」压缩到「连接时」。
        # ⚠️ 仍不能彻底消除 rebinding —— sse_client 内部会再解析一次 DNS，
        #    且其 httpx_client_factory 不支持注入 transport，无法 pin IP。
        #    需要硬保证时用 MCP_SSE_ALLOWED_HOSTS 白名单。
        #
        # 白名单用模块级变量而非 current_app：本方法运行在 MCP 专用事件循环
        # 线程上，没有 Flask app context，读 current_app 必然抛 RuntimeError。
        try:
            from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
            validate_sse_url(url, _sse_allowed_hosts)
        except SSRFValidationError as e:
            logger.error(f"拒绝连接 MCP 服务器 {self.name}：SSRF 校验未通过 - {e}")
            raise ValueError(f"URL 未通过 SSRF 校验: {e}") from e

        # 使用 async with 自动管理上下文。
        #
        # ⚠️ 两个超时都必须显式传，不能用 mcp 的默认值：
        #   timeout          mcp 默认仅 **5.0s**（实测 inspect.signature 确认），
        #                    控制握手等常规 HTTP 操作。远端 MCP 服务冷启动或
        #                    跨网络时很容易超过 5s，失败后异常还会被 anyio 包成
        #                    ExceptionGroup，日志里看不出是超时，排查成本极高。
        #   sse_read_timeout 控制「等待下一个 SSE 事件」，是**空闲连接**的存活
        #                    上限而非握手超时，默认 300s。设太短会把正常的空闲
        #                    连接掐断，所以保守保留 300s 并做成可配置。
        async with sse_client(
            url,
            headers=headers,
            timeout=SSE_HTTP_TIMEOUT_SECONDS,
            sse_read_timeout=SSE_READ_TIMEOUT_SECONDS,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self.session = session
                
                # 拉取工具列表
                await self._list_tools()
                self._connected = True
                logger.debug(f"Connected to MCP server: {self.name} ({len(self.tools)} tools)")
                
                # 保持连接活跃，直到收到停止信号
                await self._stop_event.wait()
                
                self._connected = False
                self.session = None

    async def _list_tools(self):
        """拉取工具列表并转换为 OpenAI function calling 格式"""
        try:
            response = await self.session.list_tools()
            self.tools = []
            for tool in response.tools:
                # MCP SDK uses snake_case: input_schema (not inputSchema)
                schema = getattr(tool, 'input_schema', None) or {}
                if not isinstance(schema, dict):
                    schema = {}
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": f"{self.name}__{tool.name}",
                        "description": tool.description or "",
                        "parameters": {
                            "type": "object",
                            "properties": schema.get("properties", {}),
                            "required": schema.get("required", [])
                        }
                    }
                }
                self.tools.append(tool_def)
                logger.debug(f"Discovered MCP tool: {tool_def['function']['name']} with {len(schema.get('properties', {}))} params")
        except Exception as e:
            logger.error(f"Failed to list tools from {self.name}: {e}", exc_info=True)

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行单个工具（tool_name 不含服务器前缀）"""
        if not self.session:
            return json.dumps({"error": f"MCP server {self.name} not connected"}, ensure_ascii=False)

        try:
            logger.info(f"Executing MCP tool: {self.name}.{tool_name} with args: {arguments}")
            result = await self.session.call_tool(tool_name, arguments)

            if result.content:
                text_parts = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        text_parts.append(content.text)
                response_text = "\n".join(text_parts) if text_parts else "No content"
                logger.info(f"MCP tool {self.name}.{tool_name} executed successfully")
                return response_text
            else:
                return json.dumps({"result": "success"}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"MCP tool execution failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg}, ensure_ascii=False)

    async def disconnect(self):
        """断开连接 - 只需要设置停止信号，async with 会自动清理资源"""
        if self._stop_event:
            self._stop_event.set()
        
        self._connected = False
        self.session = None
        logger.debug(f"Disconnected from MCP server: {self.name}")

    @property
    def is_connected(self) -> bool:
        return self._connected and self.session is not None


class MCPClientManager:
    """
    MCP 客户端管理器，管理多个 MCP 服务器。

    对外提供同步接口：
      - connect_all_sync(configs)     # 启动时批量连接
      - run_sync(coro_factory)        # 执行异步操作
      - execute_tool_sync(name, args) # 同步调用工具
      - disconnect_all_sync()         # 断开所有
    """

    def __init__(self):
        self.servers: Dict[str, MCPServerConnection] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    # ===== 后台事件循环线程 =====

    def _ensure_loop(self):
        """确保后台事件循环线程存在且运行中"""
        if self._loop is not None and not self._loop.is_closed() and self._thread is not None and self._thread.is_alive():
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(self._loop,),
            daemon=True,
            name="mcp-event-loop"
        )
        self._thread.start()
        logger.debug("MCP background event loop thread started")

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop):
        """后台线程主函数"""
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run_sync(self, coro_factory: Callable[[], Awaitable]):
        """在后台事件循环上执行一个异步协程，同步等待结果。

        Args:
            coro_factory: 返回协程的无参工厂函数（lambda / callable）
        """
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        return future.result()  # 阻塞等待

    # ===== 对外同步接口 =====

    def connect_all_sync(self, server_configs: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        """启动时批量连接所有配置的 MCP 服务器"""
        self._ensure_loop()

        async def _connect_all():
            results = {}
            for name, config in server_configs.items():
                success = await self._add_server_async(name, config)
                results[name] = success
            return results

        return self.run_sync(_connect_all)

    async def _add_server_async(self, name: str, server_config: Dict[str, Any]) -> bool:
        if name in self.servers:
            logger.warning(f"MCP server {name} already exists")
            return False

        connection = MCPServerConnection(name, server_config)
        if await connection.connect():
            self.servers[name] = connection
            return True
        return False

    def ensure_connected_sync(self, name: str, server_config: Dict[str, Any]) -> bool:
        """确保指定服务器已连接；未连接则按给定配置连接。

        用于用户定制服务器的按需拉起 —— 不在启动时全量连接，
        避免为每个用户的每个 stdio 服务器都常驻一个子进程。

        Returns:
            True 表示调用返回后该服务器处于已连接状态。
        """
        existing = self.servers.get(name)
        if existing is not None and existing.is_connected:
            return True

        # 已存在但断线：先摘掉旧连接对象，再重连
        if existing is not None:
            logger.info(f"MCP server {name} 已存在但未连接，重新连接")
            try:
                # run_sync 需要协程工厂（callable），不是协程对象
                self.run_sync(lambda: self._remove_async(name))
            except Exception as e:
                logger.warning(f"清理旧连接失败: {e}")

        self._ensure_loop()
        return self.run_sync(lambda: self._add_server_async(name, server_config))

    async def _remove_async(self, name: str) -> bool:
        conn = self.servers.pop(name, None)
        if conn:
            await conn.disconnect()
        return True

    def remove_server_sync(self, name: str) -> bool:
        """同步移除指定服务器"""
        if name not in self.servers:
            return False

        async def _remove():
            conn = self.servers.pop(name, None)
            if conn:
                await conn.disconnect()
            return True

        return self.run_sync(_remove)

    def execute_tool_sync(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """同步执行 MCP 工具调用。tool_name 格式：server_name__tool_name"""
        if '__' not in tool_name:
            return json.dumps({"error": f"Invalid MCP tool name format: {tool_name}"}, ensure_ascii=False)

        server_name, actual_tool_name = tool_name.split('__', 1)

        if server_name not in self.servers:
            return json.dumps({"error": f"MCP server not found: {server_name}"}, ensure_ascii=False)

        server = self.servers[server_name]
        if not server.is_connected:
            return json.dumps({"error": f"MCP server {server_name} not connected"}, ensure_ascii=False)

        async def _exec():
            return await server.execute_tool(actual_tool_name, arguments)

        return self.run_sync(_exec)

    def disconnect_all_sync(self):
        """同步断开所有服务器"""
        async def _disconnect():
            for conn in list(self.servers.values()):
                await conn.disconnect()
            self.servers.clear()

        self.run_sync(_disconnect)
        # 关闭后台线程
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._loop and not self._loop.is_closed():
            self._loop.close()
        self._loop = None
        self._thread = None

    # ===== 查询接口（同步，不涉及异步） =====

    def get_all_tools(self, allowed_servers: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """返回可用工具列表。

        Args:
            allowed_servers: 白名单服务器名集合。None 表示不过滤（返回全部已连接服务器的工具）。
                ⚠️ 多用户场景下必须传白名单 —— manager.servers 以 name 为全局键、
                不含归属信息，不过滤会把用户 A 的定制服务器工具暴露给用户 B。
        """
        allowed = set(allowed_servers) if allowed_servers is not None else None

        all_tools = []
        for name, server in self.servers.items():
            if not server.is_connected:
                continue
            if allowed is not None and name not in allowed:
                continue
            all_tools.extend(server.tools)
        return all_tools

    def list_servers(self, allowed_servers: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """列出已配置的 MCP 服务器信息。

        Args:
            allowed_servers: 白名单。None 表示返回全部（仅管理员场景使用）。
        """
        allowed = set(allowed_servers) if allowed_servers is not None else None
        return [
            self.get_server_info(name)
            for name in self.servers
            if allowed is None or name in allowed
        ]

    def get_connected_servers(self) -> List[str]:
        return [name for name, server in self.servers.items() if server.is_connected]

    def get_server_info(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self.servers:
            return None
        server = self.servers[name]
        return {
            "name": name,
            "transport": server.transport,
            "connected": server.is_connected,
            "tools_count": len(server.tools),
            "tools": [t['function']['name'] for t in server.tools]
        }

    # ===== 向后兼容的异步接口（HTTP 路由用）=====

    async def add_server(self, name: str, server_config: Dict[str, Any]) -> bool:
        return await self._add_server_async(name, server_config)

    async def remove_server(self, name: str) -> bool:
        if name not in self.servers:
            return False
        connection = self.servers.pop(name, None)
        if connection:
            await connection.disconnect()
        return True

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if '__' not in tool_name:
            return json.dumps({"error": f"Invalid MCP tool name format: {tool_name}"}, ensure_ascii=False)
        server_name, actual_tool_name = tool_name.split('__', 1)
        if server_name not in self.servers:
            return json.dumps({"error": f"MCP server not found: {server_name}"}, ensure_ascii=False)
        server = self.servers[server_name]
        if not server.is_connected:
            return json.dumps({"error": f"MCP server {server_name} not connected"}, ensure_ascii=False)
        return await server.execute_tool(actual_tool_name, arguments)

    async def connect_all(self, server_configs: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        results = {}
        for name, config in server_configs.items():
            results[name] = await self._add_server_async(name, config)
        return results

    async def disconnect_all(self):
        for name in list(self.servers.keys()):
            await self.remove_server(name)
