"""
Skill Loader - 技能加载器，负责发现、加载和管理技能
"""
import os
import json
import importlib.util
import sys
from typing import Dict, List, Optional, Any
import logging

from app.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class SkillLoader:
    """技能加载器，管理所有已加载的技能"""
    
    def __init__(self, skills_dir: str = "skills"):
        """
        初始化技能加载器
        
        Args:
            skills_dir: 技能目录路径（相对于项目根目录）
        """
        # 获取项目根目录
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.skills_dir = os.path.join(self.project_root, skills_dir)
        
        self.skills: Dict[str, BaseSkill] = {}
        self._skill_modules: Dict[str, Any] = {}  # 存储模块引用，用于热重载
        
        logger.debug(f"SkillLoader initialized with skills_dir: {self.skills_dir}")
    
    def discover_skills(self) -> List[str]:
        """
        扫描技能目录，发现所有可用的技能
        
        Returns:
            List[str]: 技能名称列表
        """
        if not os.path.exists(self.skills_dir):
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return []
        
        skill_names = []
        for item in os.listdir(self.skills_dir):
            skill_path = os.path.join(self.skills_dir, item)
            
            # 必须是目录
            if not os.path.isdir(skill_path):
                continue
            
            # 检查是否有 skill.json
            metadata_path = os.path.join(skill_path, 'skill.json')
            if not os.path.exists(metadata_path):
                logger.warning(f"Skill '{item}' missing skill.json, skipping")
                continue
            
            # 检查是否有 __init__.py
            init_path = os.path.join(skill_path, '__init__.py')
            if not os.path.exists(init_path):
                logger.warning(f"Skill '{item}' missing __init__.py, skipping")
                continue
            
            skill_names.append(item)
        
        logger.debug(f"Discovered {len(skill_names)} skills: {skill_names}")
        return skill_names
    
    def load_skill(self, name: str, config: Optional[Dict] = None) -> bool:
        """
        加载单个技能
        
        Args:
            name: 技能名称
            config: 技能配置（可选，会覆盖 skill.json 中的配置）
        
        Returns:
            bool: 是否加载成功
        """
        if name in self.skills:
            logger.warning(f"Skill '{name}' already loaded, skipping")
            return False
        
        skill_path = os.path.join(self.skills_dir, name)
        metadata_path = os.path.join(skill_path, 'skill.json')
        
        try:
            # 1. 读取元数据
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # 2. 合并配置
            skill_config = metadata.get('config', {})
            if config:
                skill_config.update(config)
            
            # 3. 动态导入模块
            init_path = os.path.join(skill_path, '__init__.py')
            spec = importlib.util.spec_from_file_location(f"skills.{name}", init_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"skills.{name}"] = module
            spec.loader.exec_module(module)
            
            # 4. 获取 Skill 类
            if not hasattr(module, 'Skill'):
                raise ValueError(f"Skill '{name}' must define a 'Skill' class")
            
            skill_class = getattr(module, 'Skill')
            
            # 5. 验证是否继承 BaseSkill
            if not issubclass(skill_class, BaseSkill):
                raise ValueError(f"Skill class must inherit from BaseSkill")
            
            # 6. 实例化 Skill
            skill_instance = skill_class(config=skill_config)
            
            # 7. 调用加载回调
            skill_instance.on_load()
            
            # 8. 注册到技能表
            self.skills[name] = skill_instance
            self._skill_modules[name] = module
            
            logger.debug(f"Skill '{name}' v{skill_instance.version} loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load skill '{name}': {e}", exc_info=True)
            return False
    
    def unload_skill(self, name: str) -> bool:
        """
        卸载单个技能
        
        Args:
            name: 技能名称
        
        Returns:
            bool: 是否卸载成功
        """
        if name not in self.skills:
            logger.warning(f"Skill '{name}' not loaded")
            return False
        
        try:
            skill = self.skills[name]
            
            # 调用卸载回调
            skill.on_unload()
            
            # 从技能表移除
            del self.skills[name]
            
            # 从模块表移除
            if name in self._skill_modules:
                module_name = f"skills.{name}"
                if module_name in sys.modules:
                    del sys.modules[module_name]
                del self._skill_modules[name]
            
            logger.debug(f"Skill '{name}' unloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unload skill '{name}': {e}", exc_info=True)
            return False
    
    def reload_skill(self, name: str, config: Optional[Dict] = None) -> bool:
        """
        重新加载技能
        
        Args:
            name: 技能名称
            config: 技能配置（可选）
        
        Returns:
            bool: 是否重载成功
        """
        logger.debug(f"Reloading skill '{name}'")
        self.unload_skill(name)
        return self.load_skill(name, config)
    
    def load_all_skills(self) -> int:
        """
        加载所有发现的技能
        
        Returns:
            int: 成功加载的技能数量
        """
        skill_names = self.discover_skills()
        loaded_count = 0
        
        for name in skill_names:
            if self.load_skill(name):
                loaded_count += 1
        
        logger.debug(f"Loaded {loaded_count}/{len(skill_names)} skills")
        return loaded_count
    
    def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有已加载技能的工具定义
        
        Returns:
            List[Dict]: 所有工具的定义（OpenAI Function Calling 格式）
        """
        all_tools = []
        for skill in self.skills.values():
            tools = skill.get_tools()
            all_tools.extend(tools)
        
        logger.debug(f"Total tools from skills: {len(all_tools)}")
        return all_tools
    
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any], skill_name: str = None) -> str:
        """
        执行工具
        
        Args:
            tool_name: 工具名称（如果提供了 skill_name，则是不含前缀的纯工具名；否则是完整名称 skill_name__tool_name）
            arguments: 工具参数
            skill_name: 技能名称（可选，如果提供则直接在指定技能中查找工具）
        
        Returns:
            str: 工具执行结果（JSON 字符串）
        """
        # 如果提供了 skill_name，直接使用
        if skill_name:
            actual_skill_name = skill_name
            actual_tool_name = tool_name
        else:
            # 解析工具名称（格式：skill_name__tool_name）
            parts = tool_name.split('__', 1)
            if len(parts) != 2:
                error_msg = f"Invalid tool name format: {tool_name}, expected 'skill_name__tool_name'"
                logger.error(error_msg)
                return json.dumps({"error": error_msg}, ensure_ascii=False)
            
            actual_skill_name, actual_tool_name = parts
        
        # 检查技能是否存在
        if actual_skill_name not in self.skills:
            error_msg = f"Skill '{actual_skill_name}' not loaded"
            logger.error(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        
        # 执行工具
        logger.info(f"Executing tool: {actual_skill_name}__{actual_tool_name} with arguments: {arguments}")
        return self.skills[actual_skill_name].execute_tool(actual_tool_name, arguments)
    
    def get_skill_info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取技能信息
        
        Args:
            name: 技能名称
        
        Returns:
            Optional[Dict]: 技能信息，如果不存在返回 None
        """
        if name not in self.skills:
            return None
        
        return self.skills[name].get_info()
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """
        列出所有已加载的技能
        
        Returns:
            List[Dict]: 技能信息列表
        """
        return [skill.get_info() for skill in self.skills.values()]
