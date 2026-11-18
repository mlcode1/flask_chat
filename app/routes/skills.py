"""
Skills 管理 API - 提供 Skill 和 MCP 服务器的管理接口

权限说明：
- Skill 管理（reload / enable / disable / test）：admin_required
  Skill 代码在主进程内运行，等于任意代码执行，仅管理员可操作。

- MCP 服务器管理：配置持久化到 mcp_servers 表，按「归属」而非一律管理员控制
  * 添加 stdio 类型（spawn 本地进程，等价 RCE）→ 仅管理员
  * 添加 sse 类型（远程 HTTP）→ 管理员，或 MCP_ALLOW_USER_CUSTOM=true 时的登录用户
  * 非管理员添加的服务器归属自己，仅本人可见可用（get_tools / execute_tool 双重过滤）
  * 改删重连 → 管理员或归属者
  * GET 列表/详情 → 默认对 env / headers 脱敏（常含 API Key、代理凭据）
"""
import logging

from flask import Blueprint, jsonify, request
from app.services.security_service import require_api_key
from app.services.auth_service import admin_required
from app.services.tool_service import get_skill_loader, get_mcp_manager

logger = logging.getLogger(__name__)

skills_bp = Blueprint('skills', __name__, url_prefix='/api/skills')


@skills_bp.route('/list', methods=['GET'])
@require_api_key
def list_skills():
    """列出所有已加载的 Skills"""
    loader = get_skill_loader()
    skills_info = loader.list_skills()
    
    return jsonify({
        'success': True,
        'count': len(skills_info),
        'skills': skills_info
    })


@skills_bp.route('/<skill_name>/info', methods=['GET'])
@require_api_key
def get_skill_info(skill_name):
    """获取指定 Skill 的详细信息"""
    loader = get_skill_loader()
    info = loader.get_skill_info(skill_name)
    
    if info is None:
        return jsonify({
            'success': False,
            'error': f'Skill not found: {skill_name}'
        }), 404
    
    return jsonify({
        'success': True,
        'skill': info
    })


@skills_bp.route('/reload', methods=['POST'])
@require_api_key
@admin_required
def reload_all_skills():
    """重新加载所有 Skills"""
    loader = get_skill_loader()
    
    try:
        loader.unload_all_skills()
        loaded_count = loader.load_all_skills()
        
        return jsonify({
            'success': True,
            'message': f'Reloaded {loaded_count} skills',
            'count': loaded_count
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@skills_bp.route('/<skill_name>/reload', methods=['POST'])
@require_api_key
@admin_required
def reload_skill(skill_name):
    """重新加载指定的 Skill"""
    loader = get_skill_loader()
    
    try:
        # 先卸载
        if skill_name in loader.skills:
            loader.unload_skill(skill_name)
        
        # 再加载
        success = loader.load_skill(skill_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Skill {skill_name} reloaded successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to load skill: {skill_name}'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@skills_bp.route('/<skill_name>/enable', methods=['POST'])
@require_api_key
@admin_required
def enable_skill(skill_name):
    """启用指定的 Skill"""
    loader = get_skill_loader()
    
    try:
        if skill_name in loader.skills:
            return jsonify({
                'success': True,
                'message': f'Skill {skill_name} is already enabled'
            })
        
        success = loader.load_skill(skill_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Skill {skill_name} enabled successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to enable skill: {skill_name}'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@skills_bp.route('/<skill_name>/disable', methods=['POST'])
@require_api_key
@admin_required
def disable_skill(skill_name):
    """禁用指定的 Skill"""
    loader = get_skill_loader()
    
    try:
        if skill_name not in loader.skills:
            return jsonify({
                'success': True,
                'message': f'Skill {skill_name} is already disabled'
            })
        
        loader.unload_skill(skill_name)
        
        return jsonify({
            'success': True,
            'message': f'Skill {skill_name} disabled successfully'
        })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@skills_bp.route('/<skill_name>/test', methods=['POST'])
@require_api_key
@admin_required
def test_skill_tool(skill_name):
    """测试 Skill 中的工具（可执行任意已注册 Skill 的逻辑，限管理员）"""
    data = request.get_json() or {}
    tool_name = data.get('tool_name')
    arguments = data.get('arguments', {})
    
    if not tool_name:
        return jsonify({
            'success': False,
            'error': 'tool_name is required'
        }), 400
    
    loader = get_skill_loader()
    
    try:
        result = loader.execute_tool(tool_name, arguments, skill_name=skill_name)
        
        return jsonify({
            'success': True,
            'result': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== MCP 服务器管理 API ==========
#
# 配置持久化在 mcp_servers 表（此前仅存内存，重启即丢）。
# 归属：user_id 为 NULL = 全局；非 NULL = 该用户定制，仅本人可见可用。
#
# ⚠️ 权限：stdio transport 接受任意 command+args+env 并 spawn 子进程，
#    等价于 RCE，始终仅管理员可添加。sse 可通过 MCP_ALLOW_USER_CUSTOM
#    开放给用户自助（默认关闭）。

import re

from flask import current_app, g
from app.services.auth_service import get_current_user, login_required
from app.services import mcp_service
from app.models import MCPServer

# 服务器名会成为工具名前缀（{server}__{tool}），必须限制字符集
_SERVER_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


def _require_mcp_enabled():
    """MCP 未启用时返回统一错误响应，否则返回 None。"""
    if not current_app.config.get('MCP_ENABLED', False):
        return jsonify({
            'success': False,
            'error': 'MCP 未启用（MCP_ENABLED=false），添加后工具也不会暴露给模型'
        }), 400
    return None


def _current_user():
    """取当前登录用户；未登录返回 None。"""
    return g.get('current_user') or get_current_user()


def _validate_server_name(name):
    """校验服务器名。返回错误信息字符串，合法则返回 None。

    - 不能含 '__'：那是工具名分隔符，含它会导致路由解析错乱
    - 不能与已加载的 Skill 重名：三层分发里 MCP 优先，会静默遮蔽同名 Skill
    """
    if not name or not isinstance(name, str):
        return '服务器名不能为空'
    if not _SERVER_NAME_RE.match(name):
        return ('服务器名只能包含字母、数字、下划线、连字符，'
                '必须以字母或数字开头，长度 1-64')
    if '__' in name:
        return "服务器名不能包含连续的 '__'（它是工具名分隔符）"

    try:
        loader = get_skill_loader()
        if name in (loader.skills or {}):
            return f"名称 '{name}' 与已加载的 Skill 冲突，MCP 会遮蔽该 Skill，请换一个名字"
    except Exception:
        pass
    return None


def _check_add_permission(user, transport):
    """校验是否有权添加指定 transport 的服务器。返回错误信息，允许则返回 None。"""
    is_admin = bool(user and user.is_admin)
    if is_admin:
        return None

    if transport == 'stdio':
        return ('stdio 类型会在服务器上启动本地进程，仅管理员可添加。'
                '如需接入远程服务请使用 sse 类型')

    if not current_app.config.get('MCP_ALLOW_USER_CUSTOM', False):
        return '当前部署未开放用户自助添加 MCP 服务器，请联系管理员'

    return None


def _serialize_server(server, manager, include_secrets=False):
    """把数据库记录与运行时连接状态合并成前端需要的结构。"""
    runtime = manager.get_server_info(server.name) if manager else None
    data = server.to_dict(include_secrets=include_secrets)

    if runtime:
        data['connected'] = runtime.get('connected', False)
        data['tools'] = runtime.get('tools', [])
        data['tools_count'] = runtime.get('tools_count', server.tools_count or 0)
    else:
        data['connected'] = False
        data['tools'] = []
        data['tools_count'] = server.tools_count or 0

    return data


@skills_bp.route('/mcp/servers', methods=['GET'])
@require_api_key
def list_mcp_servers():
    """列出当前用户可见的 MCP 服务器（数据库配置 + 运行时连接状态）。

    管理员额外看到全部用户的定制服务器，并带 can_manage 标记。
    """
    err = _require_mcp_enabled()
    if err:
        return err

    manager = get_mcp_manager()
    user = _current_user()
    is_admin = bool(user and user.is_admin)

    if is_admin:
        servers = MCPServer.query.order_by(MCPServer.id.asc()).all()
    else:
        servers = mcp_service.list_server_configs(
            user_id=user.id if user else None,
            include_disabled=True
        )

    payload = []
    for s in servers:
        item = _serialize_server(s, manager)
        item['can_manage'] = is_admin or s.user_id == (user.id if user else None)
        payload.append(item)

    return jsonify({
        'success': True,
        'count': len(payload),
        'servers': payload,
        'user_custom_enabled': current_app.config.get('MCP_ALLOW_USER_CUSTOM', False),
        'is_admin': is_admin
    })


@skills_bp.route('/mcp/servers/<server_name>/info', methods=['GET'])
@require_api_key
def get_mcp_server_info(server_name):
    """获取单个 MCP 服务器详情（含归属与持久化状态）。

    ⚠️ 默认对 env / headers 脱敏 —— 这两个字段常含 API Key、代理凭据。
    只有管理员或归属者传 include_secrets=true 才返回原值。
    """
    manager = get_mcp_manager()
    server = mcp_service.get_server_by_name(server_name)

    if server is None:
        # 数据库没有：可能是 .env 配置但未同步，或纯内存临时服务器
        info = manager.get_server_info(server_name) if manager else None
        if info is None:
            return jsonify({
                'success': False,
                'error': f'MCP server not found: {server_name}'
            }), 404
        return jsonify({'success': True, 'server': info, 'persisted': False})

    user = _current_user()
    if not mcp_service.can_access(server, user.id if user else None):
        return jsonify({'success': False, 'error': '无权访问该 MCP 服务器'}), 403

    is_owner_or_admin = bool(user and (user.is_admin or server.user_id == user.id))
    include_secrets = (
        is_owner_or_admin
        and request.args.get('include_secrets', '').lower() in ('1', 'true', 'yes')
    )

    return jsonify({
        'success': True,
        'persisted': True,
        'server': _serialize_server(server, manager, include_secrets=include_secrets)
    })


@skills_bp.route('/mcp/servers/add', methods=['POST'])
@require_api_key
def add_mcp_server():
    """添加 MCP 服务器并持久化到数据库。

    权限分级：
      - stdio（spawn 本地进程，等价 RCE）→ 仅管理员
      - sse（远程 HTTP）→ 管理员，或 MCP_ALLOW_USER_CUSTOM=true 时的任意登录用户
    非管理员添加的服务器归属自己（user_id=当前用户），仅本人可见可用。

    ⚠️ 配置先入库再连接：即使连接失败，配置也已保存，
    重启后会自动重试，用户不必重填。
    """
    data = request.get_json() or {}

    server_name = (data.get('name') or '').strip()
    transport = (data.get('transport') or 'stdio').strip().lower()

    # ⚠️ 顺序：先认证授权，再校验参数。
    # 反过来的话，匿名请求无需登录就能探测命名规则、
    # 枚举已占用的服务器名，属于信息泄露。
    user = _current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'}), 401

    perm_err = _check_add_permission(user, transport)
    if perm_err:
        return jsonify({'success': False, 'error': perm_err}), 403

    err = _require_mcp_enabled()
    if err:
        return err

    name_err = _validate_server_name(server_name)
    if name_err:
        return jsonify({'success': False, 'error': name_err}), 400

    if transport not in ('stdio', 'sse'):
        return jsonify({
            'success': False,
            'error': f"不支持的 transport: '{transport}'，只能是 stdio 或 sse"
        }), 400

    # 必填字段校验
    if transport == 'stdio':
        if not data.get('command'):
            return jsonify({'success': False, 'error': 'stdio 类型必须提供 command'}), 400
    else:
        if not data.get('url'):
            return jsonify({'success': False, 'error': 'sse 类型必须提供 url'}), 400

    manager = get_mcp_manager()
    if manager is None:
        return jsonify({'success': False, 'error': 'MCP manager 初始化失败'}), 500

    # 重名检查（含权限判断：只能改自己的服务器）
    existing = mcp_service.get_server_by_name(server_name)
    if existing is not None:
        if not user.is_admin and existing.user_id != user.id:
            # 不泄露他人服务器的存在性细节，统一报占用
            return jsonify({
                'success': False,
                'error': f"名称 '{server_name}' 已被占用，请换一个"
            }), 409
        return jsonify({
            'success': False,
            'error': f"服务器 '{server_name}' 已存在，请用更新接口或直接重连"
        }), 409

    # 归属：管理员添加为全局，普通用户添加为自己的定制服务器
    owner_id = None if user.is_admin else user.id

    # 只存必要字段，避免把 transport 重复存进 config
    server_config = {
        'command': data.get('command'),
        'args': data.get('args') or [],
        'env': data.get('env') or {},
        'url': data.get('url'),
        'headers': data.get('headers') or {},
    }
    server_config = {k: v for k, v in server_config.items() if v not in (None, [], {}, '')}

    try:
        # 1. 先入库（配置持久化的核心）
        record = mcp_service.upsert_server(
            name=server_name,
            transport=transport,
            config=server_config,
            user_id=owner_id,
            source='user'
        )

        # 2. 再尝试连接
        conn_cfg = record.to_connection_config()
        connected = manager.ensure_connected_sync(server_name, conn_cfg)

        tools_count = len(manager.servers[server_name].tools) if connected and server_name in manager.servers else 0
        mcp_service.update_runtime_state(
            server_name,
            status='connected' if connected else 'failed',
            tools_count=tools_count,
            error_message=None if connected else '连接失败，请检查配置或稍后重连'
        )

        scope = '全局' if owner_id is None else f'仅用户 {user.username}'

        # 清归属用户的懒连接簿记：本次连接失败时，用户下次上线可立即重试，
        # 不必等 300s 冷却期。
        # ⚠️ 仅对定制服务器执行 —— owner_id 为 None（全局服务器）时不能调用，
        #    因为 invalidate_user_load(None) 的语义是"清空全部用户簿记"，
        #    会让所有用户的冷却期同时失效。全局服务器已在此当场连接，无需清理。
        if owner_id is not None:
            mcp_service.invalidate_user_load(owner_id)

        if connected:
            return jsonify({
                'success': True,
                'connected': True,
                'message': f'MCP 服务器 {server_name} 已添加并连接（{tools_count} 个工具，{scope}可用）'
            })

        # 连接失败但配置已保存 —— 返回 200 而非 500，因为持久化本身是成功的
        return jsonify({
            'success': True,
            'connected': False,
            'message': (f'配置已保存，但连接失败。服务已入库，'
                        f'可稍后在列表中点「重连」，重启后也会自动重试。')
        }), 200

    except Exception as e:
        # 连接阶段异常时，回滚可能已写入的半成品记录，避免留下脏配置
        try:
            from app.extensions import db as _db
            _db.session.rollback()
        except Exception:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500


def _resolve_owned_server(server_name):
    """查找服务器并校验「可管理」权限。

    ⚠️ 顺序：先认证，再查库。反过来会让匿名用户通过 404/403 的差异
    枚举出哪些服务器名已被占用（信息泄露）。

    权限模型区分两级：
      - can_access（可调用）：全局服务器所有登录用户可用 → 用于工具执行
      - 可管理（增删改、重连）：仅管理员或归属者 → 用于本函数

    Returns:
        (server, None) 校验通过；(None, (jsonify, status)) 失败时返回错误响应
    """
    user = _current_user()
    if not user:
        return None, (jsonify({'success': False, 'error': '请先登录'}), 401)

    server = mcp_service.get_server_by_name(server_name)
    if server is None:
        return None, (jsonify({
            'success': False,
            'error': f'MCP 服务器不存在: {server_name}'
        }), 404)

    if not (user.is_admin or server.user_id == user.id):
        return None, (jsonify({
            'success': False,
            'error': '无权管理该 MCP 服务器'
        }), 403)

    return server, None


@skills_bp.route('/mcp/servers/<server_name>/remove', methods=['POST'])
@require_api_key
def remove_mcp_server(server_name):
    """移除 MCP 服务器：断开连接 + 删除数据库配置。

    权限：管理员可删任意服务器；普通用户只能删自己的定制服务器。
    """
    # 先认证归属，再检查功能开关（避免未认证请求拿到 400 而非 401）
    server, perm_err = _resolve_owned_server(server_name)
    if perm_err:
        return perm_err

    err = _require_mcp_enabled()
    if err:
        return err

    manager = get_mcp_manager()

    try:
        # 先断开连接（终止子进程），再删配置
        if manager is not None:
            try:
                manager.remove_server_sync(server_name)
            except Exception as e:
                logger.warning(f"断开 MCP 服务器 {server_name} 时出错（继续删除配置）: {e}")

        # 记录归属：delete_server 之后 record 已从库里消失，无法再读 user_id
        owner_id = server.user_id

        mcp_service.delete_server(server_name)

        # 清簿记，否则用户在冷却期内上线时，懒连接仍会尝试连这个已删除的服务器
        # （虽然查库查不到会自然跳过，但清掉更干净，也让同名服务器可立即重建）
        if owner_id is not None:
            mcp_service.invalidate_user_load(owner_id)

        return jsonify({
            'success': True,
            'message': f'MCP 服务器 {server_name} 已移除（配置已从数据库删除）'
        })

    except Exception as e:
        logger.error(f"移除 MCP 服务器失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@skills_bp.route('/mcp/servers/<server_name>/reconnect', methods=['POST'])
@require_api_key
def reconnect_mcp_server(server_name):
    """按数据库中保存的配置重新连接 MCP 服务器。

    与旧实现的区别：不再依赖内存里的 manager.servers，
    而是从数据库读取配置 —— 这样即使进程重启后内存为空，也能重连。
    """
    # 先认证归属，再检查功能开关
    server, perm_err = _resolve_owned_server(server_name)
    if perm_err:
        return perm_err

    err = _require_mcp_enabled()
    if err:
        return err

    if not server.enabled:
        return jsonify({
            'success': False,
            'error': f'服务器 {server_name} 已被禁用，请先启用再重连'
        }), 400

    manager = get_mcp_manager()
    if manager is None:
        return jsonify({'success': False, 'error': 'MCP manager 初始化失败'}), 500

    try:
        conn_cfg = server.to_connection_config()

        # 已连接则先摘掉，确保是干净的重新连接
        if server_name in manager.servers:
            try:
                manager.remove_server_sync(server_name)
            except Exception as e:
                logger.warning(f"重连前断开 {server_name} 失败（继续尝试连接）: {e}")

        connected = manager.ensure_connected_sync(server_name, conn_cfg)

        tools_count = len(manager.servers[server_name].tools) if connected and server_name in manager.servers else 0
        mcp_service.update_runtime_state(
            server_name,
            status='connected' if connected else 'failed',
            tools_count=tools_count,
            error_message=None if connected else '重连失败，请检查配置'
        )

        if connected:
            return jsonify({
                'success': True,
                'connected': True,
                'message': f'已重连 {server_name}（{tools_count} 个工具）'
            })

        return jsonify({
            'success': False,
            'connected': False,
            'error': f'重连失败: {server_name}，请检查 command/url 配置是否可用'
        }), 502

    except Exception as e:
        logger.error(f"重连 MCP 服务器失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@skills_bp.route('/mcp/servers/<server_name>', methods=['PUT', 'PATCH'])
@require_api_key
def update_mcp_server(server_name):
    """更新 MCP 服务器配置并持久化，随后按新配置重连。

    权限同 remove：管理员或归属者。
    ⚠️ transport 不允许从 sse 改成 stdio —— 那等于让普通用户绕过
       "stdio 仅管理员"的限制拿到本地命令执行能力。
    """
    # 先认证归属，再检查功能开关
    server, perm_err = _resolve_owned_server(server_name)
    if perm_err:
        return perm_err

    err = _require_mcp_enabled()
    if err:
        return err

    data = request.get_json() or {}
    user = _current_user()
    is_admin = bool(user and user.is_admin)

    new_transport = (data.get('transport') or server.transport).strip().lower()
    if new_transport not in ('stdio', 'sse'):
        return jsonify({
            'success': False,
            'error': f"不支持的 transport: '{new_transport}'"
        }), 400

    # 提权防护：非管理员不得把服务器改成 stdio
    if new_transport == 'stdio' and server.transport != 'stdio' and not is_admin:
        return jsonify({
            'success': False,
            'error': '不允许将服务器类型改为 stdio（该类型可执行本地命令，仅管理员可配置）'
        }), 403

    # 非管理员不得把归属改成全局（user_id=NULL），否则等于把自己的服务器开放给所有人
    requested_scope = data.get('scope')
    new_user_id = server.user_id
    if requested_scope is not None:
        if not is_admin:
            return jsonify({
                'success': False,
                'error': '仅管理员可修改服务器归属范围'
            }), 403
        new_user_id = None if str(requested_scope).lower() == 'global' else server.user_id

    new_config = dict(server.config or {})
    for field in ('command', 'args', 'env', 'url', 'headers'):
        if field in data:
            value = data[field]
            if value in (None, [], {}, ''):
                new_config.pop(field, None)
            else:
                new_config[field] = value

    if new_transport == 'stdio' and not new_config.get('command'):
        return jsonify({'success': False, 'error': 'stdio 类型必须提供 command'}), 400
    if new_transport == 'sse' and not new_config.get('url'):
        return jsonify({'success': False, 'error': 'sse 类型必须提供 url'}), 400

    manager = get_mcp_manager()

    try:
        updated = mcp_service.upsert_server(
            name=server_name,
            transport=new_transport,
            config=new_config,
            user_id=new_user_id,
            source=server.source
        )

        # 配置变更后必须重连，否则运行中的连接仍用旧配置
        connected = False
        tools_count = 0
        if manager is not None:
            if server_name in manager.servers:
                try:
                    manager.remove_server_sync(server_name)
                except Exception as e:
                    logger.warning(f"更新前断开 {server_name} 失败: {e}")

            if updated.enabled:
                connected = manager.ensure_connected_sync(server_name, updated.to_connection_config())
                tools_count = (
                    len(manager.servers[server_name].tools)
                    if connected and server_name in manager.servers else 0
                )

            mcp_service.update_runtime_state(
                server_name,
                status='connected' if connected else 'failed',
                tools_count=tools_count,
                error_message=None if connected else '配置已更新，但连接失败'
            )

        # 清簿记：本次若连接失败，用户下次上线可立即重试而非等冷却期。
        # 归属可能被管理员改动（server.user_id → new_user_id），两个都要清：
        # 原归属者不该再连这个已不属于他的服务器，新归属者需要连上它。
        for uid in {server.user_id, new_user_id}:
            if uid is not None:
                mcp_service.invalidate_user_load(uid)

        return jsonify({
            'success': True,
            'connected': connected,
            'server': _serialize_server(updated, manager),
            'message': (f'配置已更新{"并重连成功" if connected else "，但连接失败"}')
        })

    except Exception as e:
        logger.error(f"更新 MCP 服务器失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@skills_bp.route('/mcp/servers/<server_name>/toggle', methods=['POST'])
@require_api_key
def toggle_mcp_server(server_name):
    """启用/禁用 MCP 服务器（保留配置，仅停止加载其工具）。

    禁用后会断开连接并从工具列表移除；重新启用则按配置重连。
    比"删除再加回来"更适合临时停用。
    """
    # 先认证归属，再检查功能开关
    server, perm_err = _resolve_owned_server(server_name)
    if perm_err:
        return perm_err

    err = _require_mcp_enabled()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    enabled = data.get('enabled')
    if enabled is None:
        enabled = not bool(server.enabled)
    enabled = bool(enabled)

    manager = get_mcp_manager()

    try:
        mcp_service.set_enabled(server_name, enabled)

        if not enabled:
            # 停用：断开连接，工具立即从列表消失
            if manager is not None and server_name in manager.servers:
                try:
                    manager.remove_server_sync(server_name)
                except Exception as e:
                    logger.warning(f"停用时断开 {server_name} 失败: {e}")
            mcp_service.update_runtime_state(server_name, status='disabled', tools_count=0)
            message = f'服务器 {server_name} 已禁用（配置保留）'
        else:
            # 启用：按保存的配置重连
            connected = False
            tools_count = 0
            if manager is not None:
                connected = manager.ensure_connected_sync(
                    server_name, server.to_connection_config()
                )
                tools_count = (
                    len(manager.servers[server_name].tools)
                    if connected and server_name in manager.servers else 0
                )
            mcp_service.update_runtime_state(
                server_name,
                status='connected' if connected else 'failed',
                tools_count=tools_count,
                error_message=None if connected else '启用后连接失败'
            )
            message = (f'服务器 {server_name} 已启用'
                       f'{"并连接成功" if connected else "，但连接失败"}')

        # 清簿记：启停改变了该用户的服务器集合，冷却期内也应重新计算。
        # 尤其「启用后连接失败」的情况，不清就得等 300s 才能靠上线重试。
        if server.user_id is not None:
            mcp_service.invalidate_user_load(server.user_id)

        return jsonify({'success': True, 'enabled': enabled, 'message': message})

    except Exception as e:
        logger.error(f"切换 MCP 服务器状态失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
