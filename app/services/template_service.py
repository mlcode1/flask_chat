"""
对话模板服务：管理预设的对话模板
"""
import logging
from app.models import ConversationTemplate
from app.extensions import db

logger = logging.getLogger(__name__)


def list_templates():
    """获取所有模板"""
    templates = ConversationTemplate.query.order_by(ConversationTemplate.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in templates
    ]


def get_template(template_id):
    """获取单个模板"""
    template = ConversationTemplate.query.get(template_id)
    if not template:
        return None
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "system_prompt": template.system_prompt,
        "category": template.category,
        "created_at": template.created_at.isoformat() if template.created_at else None,
    }


def create_template(name, description, system_prompt, category="general"):
    """创建模板"""
    if not name or not name.strip():
        return None, "模板名称不能为空"
    
    if not system_prompt or not system_prompt.strip():
        return None, "系统提示词不能为空"
    
    # 检查名称是否重复
    existing = ConversationTemplate.query.filter_by(name=name).first()
    if existing:
        return None, f"模板名称 '{name}' 已存在"
    
    template = ConversationTemplate(
        name=name.strip(),
        description=description.strip() if description else "",
        system_prompt=system_prompt.strip(),
        category=category.strip() if category else "general"
    )
    db.session.add(template)
    db.session.commit()
    
    logger.info(f"创建对话模板: {template.name}")
    return get_template(template.id), None


def update_template(template_id, name=None, description=None, system_prompt=None, category=None):
    """更新模板"""
    template = ConversationTemplate.query.get(template_id)
    if not template:
        return None, "模板不存在"
    
    if name is not None:
        if not name.strip():
            return None, "模板名称不能为空"
        # 检查名称是否与其他模板重复
        existing = ConversationTemplate.query.filter(
            ConversationTemplate.name == name.strip(),
            ConversationTemplate.id != template_id
        ).first()
        if existing:
            return None, f"模板名称 '{name}' 已存在"
        template.name = name.strip()
    
    if description is not None:
        template.description = description.strip()
    
    if system_prompt is not None:
        if not system_prompt.strip():
            return None, "系统提示词不能为空"
        template.system_prompt = system_prompt.strip()
    
    if category is not None:
        template.category = category.strip() if category else "general"
    
    db.session.commit()
    logger.info(f"更新对话模板: {template.name}")
    return get_template(template.id), None


def delete_template(template_id):
    """删除模板"""
    template = ConversationTemplate.query.get(template_id)
    if not template:
        return False, "模板不存在"
    
    db.session.delete(template)
    db.session.commit()
    logger.info(f"删除对话模板: {template.name}")
    return True, None


def create_default_templates():
    """创建默认模板（首次启动时调用）"""
    if ConversationTemplate.query.count() > 0:
        return  # 已有模板，不创建默认模板
    
    default_templates = [
        {
            "name": "代码审查助手",
            "description": "帮助审查代码，提供改进建议",
            "system_prompt": """你是一个专业的代码审查助手。你的任务是：
1. 分析用户提供的代码
2. 识别潜在的 bug、性能问题、安全风险
3. 提供具体的改进建议
4. 解释为什么这些改进是必要的

请用清晰、专业的语言回复，给出具体的代码示例。""",
            "category": "development"
        },
        {
            "name": "知识库问答",
            "description": "基于上传的文档回答专业问题",
            "system_prompt": """你是一个知识库问答助手。请基于提供的文档内容回答用户问题：
1. 只基于文档中的信息回答，不要编造
2. 如果文档中没有相关信息，明确告知用户
3. 引用文档来源时要准确
4. 用清晰、结构化的方式组织答案""",
            "category": "knowledge"
        },
        {
            "name": "技术架构顾问",
            "description": "讨论系统架构设计和技术选型",
            "system_prompt": """你是一个资深的技术架构顾问。帮助用户：
1. 分析系统架构的优缺点
2. 提供技术选型建议
3. 讨论可扩展性、性能、安全性
4. 给出具体的实施方案

请基于业界最佳实践提供建议，考虑成本、复杂度、团队能力等因素。""",
            "category": "development"
        },
        {
            "name": "SQL 分析师",
            "description": "帮助编写和优化 SQL 查询",
            "system_prompt": """你是一个 SQL 专家。帮助用户：
1. 编写高效的 SQL 查询
2. 优化现有查询的性能
3. 解释查询执行计划
4. 提供索引建议

请考虑数据库类型（PostgreSQL/MySQL/SQLite 等），给出具体的 SQL 代码和解释。""",
            "category": "data"
        },
        {
            "name": "学习导师",
            "description": "耐心解答技术问题，适合初学者",
            "system_prompt": """你是一个耐心的技术导师。你的目标是：
1. 用简单易懂的语言解释复杂概念
2. 提供循序渐进的学习路径
3. 给出实践练习建议
4. 鼓励用户提问

请避免使用过多术语，必要时提供类比和示例。""",
            "category": "education"
        },
    ]
    
    for t_data in default_templates:
        template = ConversationTemplate(**t_data)
        db.session.add(template)
    
    db.session.commit()
    logger.info(f"创建了 {len(default_templates)} 个默认对话模板")
