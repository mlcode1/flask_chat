"""
Webhook 路由：管理出站 Webhook 和入站对话触发
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.security_service import require_api_key
from app.services import webhook_service
from app.services.ssrf_guard import SSRFValidationError, validate_url

webhook_bp = Blueprint('webhook', __name__, url_prefix='/api/webhooks')


def _check_webhook_url(url):
    """SSRF 校验 webhook 回调地址。返回错误信息，合法则返回 None。

    为什么需要：回调 URL 由**服务端**发起 POST（webhook_service.send_completion_webhook
    → requests.post），不校验就是 SSRF —— 可填 http://169.254.169.254/... 读云厂商
    实例元数据，或填 http://127.0.0.1:6379/ 探测本机 Redis。

    复用 MCP sse 那套校验（app/services/ssrf_guard.py），但白名单独立：
    webhook 回调不该自动继承 MCP_SSE_ALLOWED_HOSTS，否则放开一处等于放开两处。
    本地调试可设 WEBHOOK_ALLOWED_HOSTS=127.0.0.1。

    fail-closed：校验逻辑自身出错时按拒绝处理。
    """
    try:
        validate_url(
            url,
            current_app.config.get('WEBHOOK_ALLOWED_HOSTS'),
            label='webhook',
        )
    except SSRFValidationError as e:
        return str(e)
    except Exception as e:
        return f'URL 校验失败（{type(e).__name__}），请检查后重试'
    return None


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

    # SSRF 校验：这个 url 会被存下来，对话完成时由服务端 POST 过去。
    # 必须在入库前拦，否则恶意地址会一直留在配置里反复触发。
    url_err = _check_webhook_url(url)
    if url_err:
        return jsonify({'error': url_err}), 400

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
@require_api_key
def trigger_conversation():
    """外部系统触发新对话

    ⚠️ 此路由曾漏加 @require_api_key（同文件其余 4 个路由都有）——
    它会创建对话并消耗 LLM 额度，未认证暴露等于免费算力入口。
    注意 require_api_key 在 API_KEY 为空时会直接放行，
    所以生产环境必须配置 API_KEY，否则加了装饰器也等于没加。
    """
    data = request.get_json() or {}

    user_content = data.get('content')
    model = data.get('model')

    if not user_content:
        return jsonify({'error': 'content is required'}), 400

    result = webhook_service.WebhookService.trigger_conversation(
        user_content, model
    )

    return jsonify(result), 201
