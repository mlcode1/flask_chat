"""
Skills Package - 技能系统

提供可插拔的技能管理能力
"""
from app.skills.base import BaseSkill
from app.skills.loader import SkillLoader

__all__ = ['BaseSkill', 'SkillLoader']
