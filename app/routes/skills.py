"""
Skills 管理 API - 提供 Skill 和 MCP 服务器的管理接口
"""
from flask import Blueprint, jsonify, request
from app.services.security_service import require_api_key
from app.services.tool_service import get_skill_loader, get_mcp_manager

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
def test_skill_tool(skill_name):
    """测试 Skill 中的工具"""
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

@skills_bp.route('/mcp/servers', methods=['GET'])
@require_api_key
def list_mcp_servers():
    """列出所有 MCP 服务器"""
    manager = get_mcp_manager()
    
    if manager is None:
        return jsonify({
            'success': False,
            'error': 'MCP is not enabled'
        }), 400
    
    servers = manager.list_servers()
    
    return jsonify({
        'success': True,
        'count': len(servers),
        'servers': servers
    })


@skills_bp.route('/mcp/servers/<server_name>/info', methods=['GET'])
@require_api_key
def get_mcp_server_info(server_name):
    """获取 MCP 服务器信息"""
    manager = get_mcp_manager()
    
    if manager is None:
        return jsonify({
            'success': False,
            'error': 'MCP is not enabled'
        }), 400
    
    info = manager.get_server_info(server_name)
    
    if info is None:
        return jsonify({
            'success': False,
            'error': f'MCP server not found: {server_name}'
        }), 404
    
    return jsonify({
        'success': True,
        'server': info
    })


@skills_bp.route('/mcp/servers/add', methods=['POST'])
@require_api_key
async def add_mcp_server():
    """添加并连接 MCP 服务器"""
    data = request.get_json() or {}
    
    server_name = data.get('name')
    transport = data.get('transport', 'stdio')
    command = data.get('command')
    args = data.get('args', [])
    url = data.get('url')
    headers = data.get('headers', {})
    env = data.get('env', {})
    
    if not server_name:
        return jsonify({
            'success': False,
            'error': 'Server name is required'
        }), 400
    
    manager = get_mcp_manager()
    
    if manager is None:
        return jsonify({
            'success': False,
            'error': 'MCP is not enabled'
        }), 400
    
    try:
        server_config = {
            'transport': transport,
            'command': command,
            'args': args,
            'url': url,
            'headers': headers,
            'env': env
        }
        
        success = await manager.add_server(server_name, server_config)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'MCP server {server_name} added and connected'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to connect to MCP server: {server_name}'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@skills_bp.route('/mcp/servers/<server_name>/remove', methods=['POST'])
@require_api_key
async def remove_mcp_server(server_name):
    """移除 MCP 服务器"""
    manager = get_mcp_manager()
    
    if manager is None:
        return jsonify({
            'success': False,
            'error': 'MCP is not enabled'
        }), 400
    
    try:
        success = await manager.remove_server(server_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'MCP server {server_name} removed'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'MCP server not found: {server_name}'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@skills_bp.route('/mcp/servers/<server_name>/reconnect', methods=['POST'])
@require_api_key
async def reconnect_mcp_server(server_name):
    """重新连接 MCP 服务器"""
    manager = get_mcp_manager()
    
    if manager is None:
        return jsonify({
            'success': False,
            'error': 'MCP is not enabled'
        }), 400
    
    try:
        # 先断开
        if server_name in manager.connections:
            await manager.connections[server_name].disconnect()
        
        # 再重新连接
        success = await manager.connections[server_name].connect()
        
        if success:
            return jsonify({
                'success': True,
                'message': f'MCP server {server_name} reconnected'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to reconnect: {server_name}'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
