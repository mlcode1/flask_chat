"""
Agent 路由：多步骤推理、复杂任务处理
"""
from flask import Blueprint, request, jsonify
from app.services.security_service import require_api_key
from app.services.agent_service import AgentWorkflow, TaskPlanner
from app.services.auth_service import get_current_user
from app.extensions import db
from app.models import Message, Conversation

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')


@agent_bp.route('/run', methods=['POST'])
@require_api_key
def run_agent():
    """执行 Agent 任务"""
    data = request.get_json() or {}
    
    task = data.get('task')
    context = data.get('context', '')
    model = data.get('model')
    max_steps = data.get('max_steps', 5)
    
    if not task:
        return jsonify({'error': 'task is required'}), 400
    
    agent = AgentWorkflow(model=model, max_steps=max_steps)
    result = agent.run(task, context)
    
    return jsonify({
        'success': result.success,
        'final_answer': result.final_answer,
        'steps': [
            {
                'type': step.step_type,
                'content': step.content,
                'tool_name': step.tool_name,
                'tool_args': step.tool_args,
                'tool_result': step.tool_result
            }
            for step in result.steps
        ],
        'error': result.error
    })


@agent_bp.route('/plan', methods=['POST'])
@require_api_key
def plan_task():
    """任务规划：将复杂任务分解为子任务"""
    data = request.get_json() or {}
    
    task = data.get('task')
    model = data.get('model')
    
    if not task:
        return jsonify({'error': 'task is required'}), 400
    
    planner = TaskPlanner(model=model)
    subtasks = planner.plan(task)
    
    return jsonify({
        'task': task,
        'subtasks': subtasks
    })


@agent_bp.route('/save-response', methods=['POST'])
@require_api_key
def save_agent_response():
    """保存 Agent 对话到数据库（用户消息 + Agent 回复）"""
    data = request.get_json() or {}
    
    conversation_id = data.get('conversation_id')
    user_message = data.get('user_message')
    agent_response = data.get('agent_response')
    
    if not conversation_id:
        return jsonify({'error': 'conversation_id is required'}), 400
    
    try:
        conv = db.session.get(Conversation, conversation_id)
        if not conv:
            return jsonify({'error': 'conversation not found'}), 404
        
        # 保存用户消息
        user_msg = None
        if user_message:
            user_msg = Message(
                conversation_id=conversation_id,
                role='user',
                content=user_message,
                status='completed'
            )
            db.session.add(user_msg)
        
        # 保存 Agent 回复
        assistant_msg = None
        if agent_response:
            assistant_msg = Message(
                conversation_id=conversation_id,
                role='assistant',
                content=agent_response,
                status='completed'
            )
            db.session.add(assistant_msg)
        
        db.session.commit()
        
        # 更新对话时间
        conv.updated_at = db.func.now()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'user_message_id': user_msg.id if user_msg else None,
            'assistant_message_id': assistant_msg.id if assistant_msg else None
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
