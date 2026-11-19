"""最小 SSE MCP 测试服务器 —— 用于验证 flask_chat 的 sse transport 链路。

为什么要这个：项目里 stdio 类型只有管理员能加（spawn 本地进程 = RCE），
普通用户唯一能自助添加的就是 sse。但 sse 分支（client_manager._connect_sse）
一直没有被真实跑通过，需要一个可控的服务端来验证。

启动（前台，Ctrl-C 退出）：
    /Users/marin/miniconda3/bin/python scripts/sse_test_server.py

默认监听 127.0.0.1:9111，然后在 MCP 管理界面按下面填：
    名称   sse_test
    类型   sse
    URL    http://127.0.0.1:9111/sse

⚠️ 依赖 mcp 2.x 的 MCPServer API（FastMCP 在 2.x 已改名，
   lowlevel Server 的 @list_tools/@call_tool 装饰器也已移除）。

提供 3 个工具，覆盖不同返回形态，便于验证前端渲染与结果解析：
    echo        -> 文本回显（最基础的连通性确认）
    add         -> 数字运算（验证 schema 参数解析）
    server_info -> 返回自身信息（验证无参数调用）
"""
import logging
import sys

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.responses import JSONResponse

HOST = "127.0.0.1"
PORT = 9111

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("sse-test-server")

mcp = MCPServer("sse-test")


@mcp.custom_route("/health", methods=["GET"])
async def health(request) -> JSONResponse:
    """方便在添加前用浏览器 / curl 先确认服务活着。"""
    return JSONResponse({
        "status": "ok",
        "server": "sse-test",
        "sse": f"http://{HOST}:{PORT}/sse",
    })


@mcp.tool(description="回显传入的文本，用于确认 SSE 链路连通")
def echo(message: str) -> str:
    logger.info("echo: %s", message)
    return f"[sse-test] echo: {message}"


@mcp.tool(description="计算两个数字之和，用于验证参数 schema 解析")
def add(a: float, b: float) -> float:
    logger.info("add: %s + %s", a, b)
    return a + b


@mcp.tool(description="返回本测试服务器自身信息，用于验证无参数调用")
def server_info() -> str:
    return (
        "[sse-test] name=sse-test transport=sse "
        f"endpoint=http://{HOST}:{PORT}/sse tools=echo,add,server_info"
    )


# sse_app() 返回的 Starlette 实例带 lifespan（session manager 依赖它），
# 所以要用 uvicorn.Server 跑这个 ASGI app，而不是 mcp.run() 内部再起一套。
app = mcp.sse_app(sse_path="/sse", message_path="/messages/", host=HOST)


if __name__ == "__main__":
    logger.info("=" * 62)
    logger.info("SSE MCP 测试服务器启动中")
    logger.info("  health : http://%s:%d/health", HOST, PORT)
    logger.info("  sse    : http://%s:%d/sse   <- 页面里填这个", HOST, PORT)
    logger.info("  工具   : echo / add / server_info")
    logger.info("  按 Ctrl-C 退出")
    logger.info("=" * 62)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
