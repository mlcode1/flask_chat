"""
Webhook 路由：管理出站 Webhook 和入站对话触发
"""
from flask import Blueprint, request, jsonify
from app.services.security_service import require_api_key
from app.services import webhook_service

webhook_bp = Blueprint('webhook', __name__, url_prefix='/api/webhooks')


@webhook_bp.route('', methods=['GET'])
@require_api_key
def list_webhooks():
    """列出所有 Webhook 配置"""
    return jsonify({
        'webhooks': webhook_service.list_webhooks()
    })


@webhook_bp.route('', methods=['POST'])
@require_api_key
def register_webhook():
    """注册新的 Webhook"""
    data = request.get_json() or {}
    
    conversation_id = data.get('conversation_id')
    url = data.get('url')
    secret = data.get('secret')
    events = data.get('events', ['conversation.completed'])
    
    if not conversation_id or not url:
        return jsonify({'error': 'conversation_id and url are required'}), 400
    
    webhook_service.register_webhook(conversation_id, url, secret, events)
    
    return jsonify({
        'status': 'registered',
        'conversation_id': conversation_id
    }), 201


@webhook_bp.route('/<int:conversation_id>', methods=['GET'])
@require_api_key
def get_webhook(conversation_id):
    """获取指定对话的 Webhook 配置"""
    config = webhook_service.get_webhook_config(conversation_id)
    
    if not config:
        return jsonify({'error': 'Webhook not found'}), 404
    
    return jsonify(config)


@webhook_bp.route('/<int:conversation_id>', methods=['DELETE'])
@require_api_key
def delete_webhook(conversation_id):
    """删除 Webhook 配置"""
    deleted = webhook_service.delete_webhook(conversation_id)
    
    if not deleted:
        return jsonify({'error': 'Webhook not found'}), 404
    
    return jsonify({'status': 'deleted'})


# 入站 API：外部系统触发对话
@webhook_bp.route('/trigger', methods=['POST'])
def trigger_conversation():
    """外部系统触发新对话"""
    data = request.get_json() or {}
    
    user_content = data.get('content')
    model = data.get('model')
    webhook_url = data.get('webhook_url')  # 可选：完成后回调
    
    if not user_content:
        return jsonify({'error': 'content is required'}), 400
    
    result = webhook_service.WebhookService.trigger_conversation(
        user_content, model, webhook_url
    )
    
    return jsonify(result), 201
