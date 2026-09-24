"""
认证路由：用户注册、登录、登出、获取当前用户信息
"""
from flask import Blueprint, request, jsonify, g
from app.services.auth_service import register_user, login_user, get_current_user, login_required
from app.models import User

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '请求数据不能为空'}), 400
    
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    
    if not username or not email or not password:
        return jsonify({'error': '用户名、邮箱和密码都不能为空'}), 400
    
    if len(username) < 3:
        return jsonify({'error': '用户名至少3个字符'}), 400
    
    if len(password) < 6:
        return jsonify({'error': '密码至少6个字符'}), 400
    
    user, error = register_user(username, email, password)
    if error:
        return jsonify({'error': error}), 400
    
    return jsonify({
        'message': '注册成功',
        'user': user.to_dict()
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '请求数据不能为空'}), 400
    
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': '用户名和密码都不能为空'}), 400
    
    token, error = login_user(username, password)
    if error:
        return jsonify({'error': error}), 401
    
    # 直接从数据库查询用户信息（不能用 get_current_user，因为登录请求本身没有 token）
    user = User.query.filter_by(username=username).first()
    
    return jsonify({
        'message': '登录成功',
        'token': token,
        'user': user.to_dict()
    }), 200


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """用户登出（前端清除 token 即可，后端无需特殊处理）"""
    return jsonify({'message': '登出成功'}), 200


@auth_bp.route('/me', methods=['GET'])
@login_required
def get_me():
    """获取当前登录用户信息"""
    return jsonify({
        'user': g.current_user.to_dict()
    }), 200


@auth_bp.route('/verify', methods=['GET'])
@login_required
def verify_token():
    """验证 token 是否有效"""
    return jsonify({
        'valid': True,
        'user': g.current_user.to_dict()
    }), 200
