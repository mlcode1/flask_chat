"""
Code Index Routes - 代码库索引管理 API
"""
import os
import threading
import time
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, g
from app.models import db, CodeRepository, IndexedFile
from app.services.code_index_builder import build_index, delete_index
from app.services.security_service import require_api_key
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

code_index_bp = Blueprint('code_index', __name__, url_prefix='/api/code-repos')

# 全局进度追踪（简单方案，生产环境可考虑 Redis）
_indexing_progress = {}
_indexing_lock = threading.Lock()
_indexing_threads = {}  # 存储线程引用，用于取消
_cancel_flags = {}  # 取消标志

# 超时配置（秒）
PROGRESS_TIMEOUT = 600  # 10分钟无进度更新视为超时


@code_index_bp.route('', methods=['GET'])
@require_api_key
def list_repos():
    """获取所有代码仓库配置"""
    user = get_current_user()
    query = CodeRepository.query
    if user:
        query = query.filter((CodeRepository.user_id == user.id) | (CodeRepository.user_id == None))
    repos = query.order_by(CodeRepository.created_at.desc()).all()
    
    # 如果有正在索引的仓库，从内存获取最新进度
    result = []
    for repo in repos:
        repo_dict = repo.to_dict()
        if repo.status == 'indexing':
            # 从内存获取最新进度
            with _indexing_lock:
                progress_data = _indexing_progress.get(repo.id, {})
                if progress_data:
                    repo_dict['progress'] = progress_data.get('progress', repo.progress)
                    repo_dict['progress_message'] = progress_data.get('message', repo.progress_message)
        result.append(repo_dict)
    
    return jsonify({
        'status': 'success',
        'repos': result,
    })


@code_index_bp.route('', methods=['POST'])
@require_api_key
def create_repo():
    """创建新的代码仓库配置"""
    data = request.get_json()

    if not data:
        return jsonify({'status': 'error', 'message': '请求体不能为空'}), 400

    name = data.get('name', '').strip()
    path = data.get('path', '').strip()

    if not name:
        return jsonify({'status': 'error', 'message': '仓库名称不能为空'}), 400

    if not path:
        return jsonify({'status': 'error', 'message': '仓库路径不能为空'}), 400

    # 验证路径存在
    if not os.path.exists(path):
        return jsonify({'status': 'error', 'message': f'路径不存在: {path}'}), 400

    if not os.path.isdir(path):
        return jsonify({'status': 'error', 'message': f'路径不是目录: {path}'}), 400

    # 检查名称是否已存在
    existing = CodeRepository.query.filter_by(name=name).first()
    if existing:
        return jsonify({'status': 'error', 'message': f'仓库名称已存在: {name}'}), 400

    # 创建新仓库配置
    user = get_current_user()
    repo = CodeRepository(
        name=name,
        path=path,
        status='pending',
        user_id=user.id if user else None
    )
    db.session.add(repo)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'repo': repo.to_dict(),
    }), 201


@code_index_bp.route('/<int:repo_id>', methods=['GET'])
@require_api_key
def get_repo(repo_id):
    """获取单个代码仓库配置"""
    repo = CodeRepository.query.get(repo_id)

    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404
    
    # 用户权限检查
    user = get_current_user()
    if user and repo.user_id and repo.user_id != user.id:
        return jsonify({'status': 'error', 'message': '无权访问此仓库'}), 403

    return jsonify({
        'status': 'success',
        'repo': repo.to_dict(),
    })


@code_index_bp.route('/<int:repo_id>', methods=['DELETE'])
@require_api_key
def delete_repo(repo_id):
    """删除代码仓库配置及其索引"""
    repo = CodeRepository.query.get(repo_id)

    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404
    
    # 用户权限检查
    user = get_current_user()
    if user and repo.user_id and repo.user_id != user.id:
        return jsonify({'status': 'error', 'message': '无权删除此仓库'}), 403

    repo_name = repo.name

    # 删除索引数据
    try:
        result = delete_index(repo_name)
        if result['status'] == 'error':
            current_app.logger.warning(f"删除索引时出错: {result.get('error')}")
    except Exception as e:
        current_app.logger.warning(f"删除索引时出错: {e}")

    # 删除仓库配置
    db.session.delete(repo)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': f'已删除仓库配置: {repo_name}',
    })


@code_index_bp.route('/<int:repo_id>/index', methods=['POST'])
@require_api_key
def trigger_index(repo_id):
    """触发索引构建（异步）"""
    repo = CodeRepository.query.get(repo_id)

    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404

    # 用户权限检查
    user = get_current_user()
    if user and repo.user_id and repo.user_id != user.id:
        return jsonify({'status': 'error', 'message': '无权操作此仓库'}), 403

    # 检查是否已有索引任务在运行
    if repo.status == 'indexing':
        return jsonify({'status': 'error', 'message': '索引任务正在运行中'}), 409

    # 获取请求参数
    data = request.get_json() or {}
    reindex = data.get('reindex', True)  # 默认重新索引
    mode = data.get('mode', 'full')  # 默认为全量索引

    # 验证 mode 参数
    if mode not in ['full', 'incremental']:
        return jsonify({'status': 'error', 'message': '无效的索引模式，必须是 full 或 incremental'}), 400

    # 更新状态为索引中
    repo.status = 'indexing'
    repo.index_mode = mode
    repo.error_message = None
    repo.progress = 0
    repo.progress_message = '准备索引...'
    db.session.commit()

    # 初始化进度
    with _indexing_lock:
        _indexing_progress[repo_id] = {
            'progress': 0,
            'message': '准备索引...',
            'status': 'indexing',
            'last_update': time.time()  # 添加最后更新时间
        }
    
    # 初始化取消标志
    _cancel_flags[repo_id] = False

    # 在后台任务中执行索引构建（使用 socketio.start_background_task 确保 WebSocket 可用）
    app = current_app._get_current_object()  # 获取应用对象用于后台线程
    
    def _run_index():
        with app.app_context():  # 在后台任务中创建应用上下文
            from app import socketio  # 在应用上下文中导入 socketio
            try:
                def progress_callback(progress, message):
                    # 检查取消标志
                    if _cancel_flags.get(repo_id, False):
                        raise Exception('用户取消了索引任务')
                    
                    with _indexing_lock:
                        _indexing_progress[repo_id] = {
                            'progress': progress,
                            'message': message,
                            'status': 'indexing',
                            'last_update': time.time()  # 更新最后更新时间
                        }
                    # 通过 WebSocket 推送进度给所有客户端
                    try:
                        logger.debug(f"发送进度事件: repo_id={repo_id}, progress={progress}, message={message}")
                        socketio.emit('index_progress', {
                            'repo_id': repo_id,
                            'progress': progress,
                            'message': message,
                            'status': 'indexing'
                        })
                        logger.debug("进度事件发送成功")
                    except Exception as ws_err:
                        logger.warning(f"WebSocket 推送进度失败: {ws_err}")
                    # 同时更新数据库（用于持久化）
                    try:
                        repo_ref = CodeRepository.query.get(repo_id)
                        if repo_ref:
                            repo_ref.progress = progress
                            repo_ref.progress_message = message
                            db.session.commit()
                    except:
                        pass

                result = build_index(
                    repo_id=repo_id,
                    repo_name=repo.name,
                    repo_path=repo.path,
                    reindex=reindex,
                    mode=mode,
                    progress_callback=progress_callback
                )

                repo_ref = CodeRepository.query.get(repo_id)
                if repo_ref:
                    if result['status'] == 'success':
                        repo_ref.status = 'indexed'
                        repo_ref.file_count = result.get('file_count', 0)
                        repo_ref.chunk_count = result.get('chunk_count', 0)
                        repo_ref.last_indexed_at = datetime.now(timezone.utc)
                        repo_ref.error_message = None
                        repo_ref.progress = 100
                        repo_ref.progress_message = '索引完成'
                        
                        # 如果是全量索引，更新 last_full_index_time
                        if mode == 'full':
                            repo_ref.last_full_index_time = datetime.now(timezone.utc)
                    else:
                        repo_ref.status = 'failed'
                        repo_ref.error_message = result.get('error', '未知错误')
                        repo_ref.progress = 0
                        repo_ref.progress_message = ''
                    db.session.commit()

                with _indexing_lock:
                    _indexing_progress[repo_id] = {
                        'progress': 100 if result['status'] == 'success' else 0,
                        'message': '索引完成' if result['status'] == 'success' else result.get('error'),
                        'status': result['status'],
                        'last_update': time.time()
                    }

                # 通过 WebSocket 推送最终结果
                # 注意：前端检查 status === 'indexed' || 'failed'，不是 'success'/'error'
                final_status = 'indexed' if result['status'] == 'success' else 'failed'
                try:
                    socketio.emit('index_progress', {
                        'repo_id': repo_id,
                        'progress': 100 if result['status'] == 'success' else 0,
                        'message': '索引完成' if result['status'] == 'success' else result.get('error', '未知错误'),
                        'status': final_status,
                        'file_count': result.get('file_count', 0),
                        'chunk_count': result.get('chunk_count', 0),
                    })
                    logger.info(f"索引完成推送: repo_id={repo_id}, status={final_status}")
                except Exception as ws_err:
                    logger.warning(f"WebSocket 推送完成结果失败: {ws_err}")

            except Exception as e:
                repo_ref = CodeRepository.query.get(repo_id)
                if repo_ref:
                    repo_ref.status = 'failed'
                    repo_ref.error_message = str(e)
                    repo_ref.progress = 0
                    repo_ref.progress_message = ''
                    db.session.commit()

                with _indexing_lock:
                    _indexing_progress[repo_id] = {
                        'progress': 0,
                        'message': str(e),
                        'status': 'failed',
                        'last_update': time.time()
                    }
                
                # 通过 WebSocket 推送失败结果
                try:
                    socketio.emit('index_progress', {
                        'repo_id': repo_id,
                        'progress': 0,
                        'message': str(e),
                        'status': 'failed',
                    })
                    logger.info(f"索引失败推送: repo_id={repo_id}, status=failed")
                except Exception as ws_err:
                    logger.warning(f"WebSocket 推送失败结果失败: {ws_err}")
            finally:
                # 清理线程引用
                _indexing_threads.pop(repo_id, None)
                _cancel_flags.pop(repo_id, None)

    # 使用 socketio.start_background_task 启动后台任务，确保 WebSocket 事件能正常推送
    from app import socketio
    socketio.start_background_task(_run_index)
    
    # 存储任务引用（用于取消）
    _indexing_threads[repo_id] = True

    return jsonify({
        'status': 'success',
        'message': f'索引任务已启动（{mode}模式）',
        'repo': repo.to_dict(),
    })


@code_index_bp.route('/<int:repo_id>/progress', methods=['GET'])
@require_api_key
def get_index_progress(repo_id):
    """获取索引进度"""
    repo = CodeRepository.query.get(repo_id)

    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404

    # 用户权限检查
    user = get_current_user()
    if user and repo.user_id and repo.user_id != user.id:
        return jsonify({'status': 'error', 'message': '无权访问此仓库'}), 403

    with _indexing_lock:
        progress_data = _indexing_progress.get(repo_id, {
            'progress': repo.progress or 0,
            'message': repo.progress_message or '',
            'status': repo.status,
            'last_update': time.time()
        })
    
    # 超时检测：如果状态是indexing且超过PROGRESS_TIMEOUT没有更新，视为超时
    if (repo.status == 'indexing' and 
        time.time() - progress_data.get('last_update', 0) > PROGRESS_TIMEOUT):
        # 设置取消标志
        _cancel_flags[repo_id] = True
        
        # 更新数据库状态
        repo.status = 'failed'
        repo.error_message = f'索引任务超时（{PROGRESS_TIMEOUT}秒无进度更新）'
        repo.progress = 0
        repo.progress_message = ''
        db.session.commit()
        
        progress_data['status'] = 'failed'
        progress_data['message'] = repo.error_message

    return jsonify({
        'status': 'success',
        'progress': progress_data['progress'],
        'message': progress_data['message'],
        'repo_status': repo.status,
        'repo': repo.to_dict(),
    })


@code_index_bp.route('/<int:repo_id>/cancel', methods=['POST'])
@require_api_key
def cancel_index(repo_id):
    """取消索引任务"""
    repo = CodeRepository.query.get(repo_id)

    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404
    
    # 用户权限检查
    user = get_current_user()
    if user and repo.user_id and repo.user_id != user.id:
        return jsonify({'status': 'error', 'message': '无权操作此仓库'}), 403
    
    if repo.status != 'indexing':
        return jsonify({'status': 'error', 'message': '没有正在运行的索引任务'}), 400
    
    # 设置取消标志
    _cancel_flags[repo_id] = True
    
    # 更新数据库状态
    repo.status = 'failed'
    repo.error_message = '用户取消了索引任务'
    repo.progress = 0
    repo.progress_message = ''
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'message': '已取消索引任务',
        'repo': repo.to_dict(),
    })


@code_index_bp.route('/<int:repo_id>/status', methods=['GET'])
@require_api_key
def get_repo_status(repo_id):
    """获取仓库索引状态"""
    repo = CodeRepository.query.get(repo_id)

    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404

    return jsonify({
        'status': 'success',
        'repo': repo.to_dict(),
    })


@code_index_bp.route('/<int:repo_id>/stats', methods=['GET'])
@require_api_key
def get_repo_stats(repo_id):
    """获取仓库索引统计信息"""
    from app.models import IndexedFile
    
    repo = CodeRepository.query.get(repo_id)
    if not repo:
        return jsonify({'status': 'error', 'message': '仓库不存在'}), 404
    
    # 查询文件索引记录数
    indexed_files_count = IndexedFile.query.filter_by(repo_id=repo_id).count()
    
    return jsonify({
        'status': 'success',
        'stats': {
            'total_files': indexed_files_count,
            'chunk_count': repo.chunk_count,
            'last_indexed_at': repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
            'last_full_index_time': repo.last_full_index_time.isoformat() if repo.last_full_index_time else None,
            'index_mode': repo.index_mode,
            'status': repo.status
        }
    })
