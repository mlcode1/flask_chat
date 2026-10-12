"""
MCP Client Manager - 管理 MCP 服务器连接和工具调用
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Any

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


class MCPServerConnection:
    """单个 MCP 服务器的连接管理"""
    
    def __init__(self, name: str, server_config: Dict[str, Any]):
        """
        初始化服务器连接
        
        Args:
            name: 服务器名称
            server_config: 服务器配置
                {
                    "transport": "stdio" | "sse",
                    "command": "命令" (stdio),
                    "args": [] (stdio),
                    "env": {} (stdio),
                    "url": "URL" (sse),
                    "headers": {} (sse)
                }
        """
        self.name = name
        self.config = server_config
        self.transport = server_config.get('transport', 'stdio')
        self.session: Optional[ClientSession] = None
        self.tools: List[Dict[str, Any]] = []
        self._connected = False
    
    async def connect(self) -> bool:
        """
        连接到 MCP 服务器
        
        Returns:
            bool: 是否连接成功
        """
        if not MCP_AVAILABLE:
            logger.error("MCP library not installed, cannot connect to MCP server")
            return False
            
        try:
            if self.transport == 'stdio':
                await self._connect_stdio()
            elif self.transport == 'sse':
                await self._connect_sse()
            else:
                logger.error(f"Unsupported transport: {self.transport}")
                return False
            
            # 获取可用工具列表
            await self._list_tools()
            
            self._connected = True
            logger.debug(f"Connected to MCP server: {self.name} ({len(self.tools)} tools)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.name}: {e}", exc_info=True)
            return False
    
    async def _connect_stdio(self):
        """通过 stdio 连接到 MCP 服务器"""
        command = self.config.get('command')
        args = self.config.get('args', [])
        env = self.config.get('env', {})
        
        if not command:
            raise ValueError("stdio transport requires 'command' parameter")
        
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env
        )
        
        # 创建 stdio 客户端
        client = await stdio_client(server_params).__aenter__()
        self.session = ClientSession(client)
        
        # 初始化会话
        await self.session.initialize()
    
    async def _connect_sse(self):
        """通过 SSE 连接到 MCP 服务器"""
        url = self.config.get('url')
        headers = self.config.get('headers', {})
        
        if not url:
            raise ValueError("sse transport requires 'url' parameter")
        
        # 创建 SSE 客户端
        client = await sse_client(url, headers=headers).__aenter__()
        self.session = ClientSession(client)
        
        # 初始化会话
        await self.session.initialize()
    
    async def _list_tools(self):
        """获取服务器提供的工具列表"""
        try:
            response = await self.session.list_tools()
            
            for tool in response.tools:
                # 转换为 OpenAI Function Calling 格式
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": f"{self.name}__{tool.name}",  # 添加服务器前缀
                        "description": tool.description or "",
                        "parameters": {
                            "type": "object",
                            "properties": tool.inputSchema.get("properties", {}),
                            "required": tool.inputSchema.get("required", [])
                        }
                    }
                }
                self.tools.append(tool_def)
                logger.debug(f"Discovered MCP tool: {tool_def['function']['name']}")
                
        except Exception as e:
            logger.error(f"Failed to list tools from {self.name}: {e}", exc_info=True)
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具
        
        Args:
            tool_name: 工具名称（不含服务器前缀）
            arguments: 工具参数
        
        Returns:
            str: 工具执行结果
        """
        if not self.session:
            return json.dumps({"error": f"MCP server {self.name} not connected"}, ensure_ascii=False)
        
        try:
            logger.info(f"Executing MCP tool: {self.name}.{tool_name} with args: {arguments}")
            
            # 调用工具
            result = await self.session.call_tool(tool_name, arguments)
            
            # 提取文本内容
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
        """断开连接"""
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing session for {self.name}: {e}")
        
        self.session = None
        self._connected = False
        logger.debug(f"Disconnected from MCP server: {self.name}")
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected and self.session is not None


class MCPClientManager:
    """MCP 客户端管理器，管理多个 MCP 服务器"""
    
    def __init__(self):
        """初始化管理器"""
        self.servers: Dict[str, MCPServerConnection] = {}
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def add_server(self, name: str, server_config: Dict[str, Any]) -> bool:
        """
        添加并连接 MCP 服务器
        
        Args:
            name: 服务器名称
            server_config: 服务器配置
        
        Returns:
            bool: 是否添加成功
        """
        if name in self.servers:
            logger.warning(f"MCP server {name} already exists")
            return False
        
        connection = MCPServerConnection(name, server_config)
        
        if await connection.connect():
            self.servers[name] = connection
            return True
        else:
            return False
    
    async def remove_server(self, name: str) -> bool:
        """
        移除 MCP 服务器
        
        Args:
            name: 服务器名称
        
        Returns:
            bool: 是否移除成功
        """
        if name not in self.servers:
            logger.warning(f"MCP server {name} not found")
            return False
        
        connection = self.servers[name]
        await connection.disconnect()
        del self.servers[name]
        
        logger.debug(f"Removed MCP server: {name}")
        return True
    
    def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有已连接服务器的工具
        
        Returns:
            List[Dict]: 工具定义列表
        """
        all_tools = []
        
        for server in self.servers.values():
            if server.is_connected:
                all_tools.extend(server.tools)
        
        return all_tools
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具
        
        Args:
            tool_name: 完整工具名称（server_name__tool_name）
            arguments: 工具参数
        
        Returns:
            str: 工具执行结果
        """
        # 解析服务器名称和工具名称
        if '__' not in tool_name:
            return json.dumps({"error": f"Invalid MCP tool name format: {tool_name}"}, ensure_ascii=False)
        
        server_name, actual_tool_name = tool_name.split('__', 1)
        
        # 查找服务器
        if server_name not in self.servers:
            return json.dumps({"error": f"MCP server not found: {server_name}"}, ensure_ascii=False)
        
        server = self.servers[server_name]
        
        if not server.is_connected:
            return json.dumps({"error": f"MCP server {server_name} not connected"}, ensure_ascii=False)
        
        # 执行工具
        return await server.execute_tool(actual_tool_name, arguments)
    
    async def connect_all(self, server_configs: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        """
        批量连接多个服务器
        
        Args:
            server_configs: 服务器配置字典 {name: config}
        
        Returns:
            Dict[str, bool]: 每个服务器的连接结果
        """
        results = {}
        
        for name, config in server_configs.items():
            success = await self.add_server(name, config)
            results[name] = success
        
        return results
    
    async def disconnect_all(self):
        """断开所有服务器连接"""
        for name in list(self.servers.keys()):
            await self.remove_server(name)
        
        logger.debug("All MCP servers disconnected")
    
    def get_connected_servers(self) -> List[str]:
        """获取已连接的服务器列表"""
        return [name for name, server in self.servers.items() if server.is_connected]
    
    def get_server_info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取服务器信息
        
        Args:
            name: 服务器名称
        
        Returns:
            Optional[Dict]: 服务器信息
        """
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
