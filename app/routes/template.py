"""
对话模板路由：模板的增删改查
"""
from flask import Blueprint, jsonify, request
from app.services.security_service import require_api_key
from app.services.template_service import (
    list_templates, get_template, create_template,
    update_template, delete_template
)

template_bp = Blueprint('template', __name__, url_prefix='/api/templates')


@template_bp.route("", methods=["GET"])
@require_api_key
def get_templates():
    """获取所有模板列表"""
    templates = list_templates()
    return jsonify({"templates": templates})


@template_bp.route("/<int:tid>", methods=["GET"])
@require_api_key
def get_template_by_id(tid):
    """获取单个模板详情"""
    template = get_template(tid)
    if not template:
        return jsonify({"error": "模板不存在"}), 404
    return jsonify({"template": template})


@template_bp.route("", methods=["POST"])
@require_api_key
def create_new_template():
    """创建新模板"""
    data = request.get_json() or {}
    
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    system_prompt = data.get("system_prompt", "").strip()
    category = data.get("category", "general").strip()
    
    if not name:
        return jsonify({"error": "模板名称不能为空"}), 400
    
    if not system_prompt:
        return jsonify({"error": "系统提示词不能为空"}), 400
    
    template, error = create_template(name, description, system_prompt, category)
    if error:
        return jsonify({"error": error}), 400
    
    return jsonify({"template": template}), 201


@template_bp.route("/<int:tid>", methods=["PUT"])
@require_api_key
def update_existing_template(tid):
    """更新模板"""
    data = request.get_json() or {}
    
    # 只更新提供的字段
    name = data.get("name")
    description = data.get("description")
    system_prompt = data.get("system_prompt")
    category = data.get("category")
    
    template, error = update_template(
        tid, 
        name=name, 
        description=description, 
        system_prompt=system_prompt, 
        category=category
    )
    
    if error:
        return jsonify({"error": error}), 400
    
    if not template:
        return jsonify({"error": "模板不存在"}), 404
    
    return jsonify({"template": template})


@template_bp.route("/<int:tid>", methods=["DELETE"])
@require_api_key
def delete_existing_template(tid):
    """删除模板"""
    success, error = delete_template(tid)
    
    if error:
        return jsonify({"error": error}), 404
    
    return jsonify({"status": "deleted"})
