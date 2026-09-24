"""
认证服务：用户注册、登录、JWT Token 管理
"""
import jwt
import datetime
from functools import wraps
from flask import request, jsonify, current_app, g
from app.models import User
from app.extensions import db


def generate_token(user_id, expires_hours=24):
    """生成 JWT Token"""
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=expires_hours),
        'iat': datetime.datetime.utcnow()
    }
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


def verify_token(token):
    """验证 JWT Token"""
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user():
    """获取当前登录用户"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header.split(' ')[1]
    user_id = verify_token(token)
    if not user_id:
        return None
    
    return User.query.get(user_id)


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '请先登录'}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """管理员权限验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '请先登录'}), 401
        if not user.is_admin:
            return jsonify({'error': '需要管理员权限'}), 403
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def register_user(username, email, password):
    """用户注册"""
    # 检查用户名是否已存在
    if User.query.filter_by(username=username).first():
        return None, '用户名已存在'
    
    # 检查邮箱是否已存在
    if User.query.filter_by(email=email).first():
        return None, '邮箱已被注册'
    
    # 创建用户
    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    return user, None


def login_user(username, password):
    """用户登录"""
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return None, '用户名或密码错误'
    
    if not user.is_active:
        return None, '账号已被禁用'
    
    # 更新最后登录时间
    user.last_login = datetime.datetime.utcnow()
    db.session.commit()
    
    # 生成 token
    token = generate_token(user.id)
    return token, None


def get_current_user_from_token(token):
    """从 JWT token 获取用户（用于 WebSocket 认证）"""
    if not token:
        return None
    
    user_id = verify_token(token)
    if not user_id:
        return None
    
    return User.query.get(user_id)
