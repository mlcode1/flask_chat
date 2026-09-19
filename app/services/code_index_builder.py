"""
Code Index Builder Service - 两层索引构建服务
第一层：文件摘要索引（粗粒度定位）
第二层：代码块索引（精确搜索）
"""
import os
import re
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timezone

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings,
    Document,
)
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core.node_parser import CodeSplitter
from openai import OpenAI

from flask import current_app

logger = logging.getLogger(__name__)


def sanitize_sensitive_content(text: str) -> str:
    """
    清理敏感内容，防止密码、API Key、Token等被索引到向量数据库
    
    过滤规则：
    1. API Key / Secret Key 格式
    2. 密码字段赋值
    3. Token / Bearer 令牌
    4. 数据库连接字符串中的密码
    5. 私钥块
    """
    patterns = [
        # API Key / Secret
        (r'(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|private[_-]?key)\s*[=:]\s*["\']?[A-Za-z0-9+/=\-_\.]{20,}["\']?',
         r'\1 = "[REDACTED]"'),

        # 密码字段
        (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?[^"\'\n]{6,}["\']?',
         r'\1 = "[REDACTED]"'),

        # Bearer Token
        (r'(Bearer\s+)[A-Za-z0-9\-_\.]+',
         r'\1[REDACTED]'),

        # 数据库连接字符串
        (r'(postgresql\+psycopg://[^:]+:)[^@]+(@)',
         r'\1[REDACTED]\2'),

        # 私钥块
        (r'-----BEGIN[A-Z ]+PRIVATE KEY-----[\s\S]*?-----END[A-Z ]+PRIVATE KEY-----',
         '[REDACTED PRIVATE KEY]'),

        # JWT Token
        (r'eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_.+/=]+',
         '[REDACTED_JWT]'),
    ]

    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)

    return text


def calculate_file_hash(file_path: str) -> str:
    """计算文件的 SHA256 哈希值"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_file_info(file_path: str, base_path: str) -> Dict:
    """获取文件的元数据信息"""
    path = Path(file_path)
    stat = path.stat()
    
    return {
        'file_path': str(path.relative_to(base_path)),
        'content_hash': calculate_file_hash(file_path),
        'file_size': stat.st_size,
        'last_modified_time': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    }


def scan_files_for_incremental(repo_id: int, repo_path: str, supported_exts: List[str], 
                                exclude_patterns: List[str]) -> Tuple[List[Dict], List[str], List[str]]:
    """
    扫描文件并确定增量索引需要的操作
    
    Returns:
        - files_to_index: 需要索引的文件列表
        - files_to_delete: 需要删除的文件路径列表
        - files_skipped: 跳过的文件路径列表
    """
    from app.models import IndexedFile, db
    
    # 1. 扫描文件系统
    base_path = Path(repo_path)
    current_files = {}
    
    for ext in supported_exts:
        for file_path in base_path.rglob(f"*{ext}"):
            # 检查是否在排除列表中
            rel_path = file_path.relative_to(base_path)
            if any(pattern in str(rel_path) for pattern in exclude_patterns):
                continue
            
            try:
                file_info = get_file_info(str(file_path), repo_path)
                current_files[file_info['file_path']] = file_info
            except Exception as e:
                logger.warning(f"无法读取文件 {file_path}: {e}")
    
    # 2. 查询数据库中的索引记录
    indexed_records = IndexedFile.query.filter_by(repo_id=repo_id).all()
    indexed_map = {record.file_path: record for record in indexed_records}
    
    # 3. 比较确定操作
    files_to_index = []
    files_skipped = []
    files_to_delete = []
    
    for file_path, file_info in current_files.items():
        if file_path not in indexed_map:
            # 新文件，需要索引
            files_to_index.append(file_info)
        else:
            # 已存在的文件，检查是否有变化
            indexed_record = indexed_map[file_path]
            if indexed_record.content_hash != file_info['content_hash']:
                # 内容已变化，需要重新索引
                files_to_index.append(file_info)
            else:
                # 内容未变化，跳过
                files_skipped.append(file_path)
    
    # 4. 检查已删除的文件
    for file_path in indexed_map.keys():
        if file_path not in current_files:
            files_to_delete.append(file_path)
    
    return files_to_index, files_to_delete, files_skipped


def delete_indexed_files(repo_id: int, repo_name: str, file_paths: List[str]):
    """从向量存储中删除指定文件的索引（包括摘要和代码块）"""
    from app.models import IndexedFile, db
    
    if not file_paths:
        return
    
    # 1. 删除 PGVectorStore 中的向量数据
    if file_paths:
        try:
            import psycopg2
            db_host = current_app.config.get('CODE_INDEX_DB_HOST', 'localhost')
            db_port = current_app.config.get('CODE_INDEX_DB_PORT', 5432)
            db_user = current_app.config.get('CODE_INDEX_DB_USER', 'postgres')
            db_password = current_app.config.get('CODE_INDEX_DB_PASSWORD', 'postgres')
            db_name = current_app.config.get('CODE_INDEX_DB_NAME', 'flask_chat')
            
            conn = psycopg2.connect(
                host=db_host, port=db_port, user=db_user,
                password=db_password, database=db_name
            )
            cursor = conn.cursor()
            
            # 删除第一层摘要表中的记录
            summaries_table = f"data_code_summaries_{repo_name}"
            placeholders = ','.join(['%s'] * len(file_paths))
            cursor.execute(
                f"DELETE FROM {summaries_table} WHERE metadata_->>'file_path' IN ({placeholders})",
                file_paths
            )
            
            # 删除第二层代码块表中的记录
            chunks_table = f"data_code_chunks_{repo_name}"
            cursor.execute(
                f"DELETE FROM {chunks_table} WHERE metadata_->>'file_path' IN ({placeholders})",
                file_paths
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"已从向量表删除 {len(file_paths)} 个文件的旧数据")
        except Exception as e:
            logger.warning(f"删除向量数据失败: {e}")
    
    # 2. 删除 indexed_files 表记录
    for file_path in file_paths:
        record = IndexedFile.query.filter_by(repo_id=repo_id, file_path=file_path).first()
        if record:
            db.session.delete(record)
    
    db.session.commit()
    logger.info(f"已删除 {len(file_paths)} 个文件的索引记录")


def generate_file_summary(file_path: str, content: str, client: OpenAI, model: str) -> str:
    """
    为文件生成摘要，用于第一层索引
    
    提取文件的关键信息：
    - 文件类型（Python/JavaScript等）
    - 主要类和函数
    - 核心功能描述
    """
    # 提取文件扩展名
    ext = Path(file_path).suffix.lower()
    
    # 根据文件类型提取关键信息
    if ext == '.py':
        # Python: 提取类名和函数名
        classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
        functions = re.findall(r'^def\s+(\w+)', content, re.MULTILINE)
        key_elements = classes + functions[:10]  # 最多取10个函数
    elif ext in ['.js', '.ts', '.tsx', '.jsx']:
        # JavaScript/TypeScript: 提取函数和类
        functions = re.findall(r'function\s+(\w+)', content)
        classes = re.findall(r'class\s+(\w+)', content)
        key_elements = classes + functions[:10]
    else:
        # 其他文件类型：取前200字符
        key_elements = []
    
    # 构建摘要提示
    if key_elements:
        prompt = f"""为以下代码文件生成简短摘要（不超过100字）：
文件路径: {file_path}
包含的元素: {', '.join(key_elements[:15])}

请用一句话描述这个文件的主要功能和用途。"""
    else:
        # 对于没有明显结构的文件，使用内容前缀
        content_preview = content[:500]
        prompt = f"""为以下文件生成简短摘要（不超过100字）：
文件路径: {file_path}
内容预览: {content_preview}

请用一句话描述这个文件的主要功能和用途。"""
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,  # reasoning 模型需要更多 tokens（推理 + 输出）
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM 返回空内容")
        
        summary = content.strip()
        # 清理摘要，移除多余空白
        summary = re.sub(r'\s+', ' ', summary)
        
        # 如果清理后还是空，走降级逻辑
        if not summary:
            raise ValueError("LLM 返回空白内容")
        
        return summary
    except Exception as e:
        logger.warning(f"生成文件摘要失败 {file_path}: {e}")
        # 降级：使用文件名和扩展名
        return f"{Path(file_path).name} - {ext}文件"


def build_index(repo_id: int, repo_name: str, repo_path: str, reindex: bool = True, mode: str = 'full', progress_callback=None):
    """
    构建两层代码库索引
    
    第一层：文件摘要索引（用于粗粒度定位）
    第二层：代码块索引（用于精确搜索）
    
    Args:
        repo_id: 仓库ID
        repo_name: 仓库名称（用于表名）
        repo_path: 仓库路径
        reindex: 是否重新索引（默认清空已有索引）
        mode: 索引模式 - 'full' 全量索引，'incremental' 增量索引
        progress_callback: 进度回调函数 callback(progress: int, message: str)
    
    Returns:
        dict: 包含文件数、分块数、状态等信息
    """
    def _report_progress(progress, message):
        if progress_callback:
            progress_callback(progress, message)
    
    try:
        _report_progress(2, '验证仓库路径...')
        logger.info(f"开始构建两层索引: {repo_name} ({repo_path}), 模式: {mode}")

        # 验证路径存在
        path = Path(repo_path)
        if not path.exists():
            raise ValueError(f"仓库路径不存在: {repo_path}")
        if not path.is_dir():
            raise ValueError(f"路径不是目录: {repo_path}")

        _report_progress(4, '读取配置参数...')

        # 从配置获取参数
        chunk_lines = current_app.config.get('CODE_INDEX_CHUNK_LINES', 100)
        chunk_lines_overlap = current_app.config.get('CODE_INDEX_CHUNK_LINES_OVERLAP', 10)
        max_chars = current_app.config.get('CODE_INDEX_MAX_CHARS', 1500)
        supported_exts = current_app.config.get('CODE_INDEX_SUPPORTED_EXTS', ['.py', '.js', '.ts', '.md'])
        exclude_patterns = current_app.config.get('CODE_INDEX_EXCLUDE_PATTERNS', ['.git', '__pycache__', 'node_modules'])

        _report_progress(6, '初始化 Embedding 模型和 LLM...')
        # 初始化 Embedding 模型（统一使用 EMBEDDING_* 配置）
        embed_api_base = current_app.config.get('EMBEDDING_BASE_URL', 'http://localhost:11434/v1')
        embed_api_key = current_app.config.get('EMBEDDING_API_KEY', 'ollama')
        embed_model = current_app.config.get('EMBEDDING_MODEL', 'qwen3-embedding:8b')

        # 移除 /v1 后缀（OllamaEmbedding 不需要）
        embed_base_url = embed_api_base.rstrip('/').replace('/v1', '')

        embed_model_instance = OllamaEmbedding(
            model_name=embed_model,
            base_url=embed_base_url,
            api_key=embed_api_key,
        )
        Settings.embed_model = embed_model_instance

        # 初始化 OpenAI 客户端（用于生成文件摘要，复用主 LLM 配置）
        summary_client = OpenAI(
            api_key=current_app.config.get('OPENAI_API_KEY'),
            base_url=current_app.config.get('OPENAI_BASE_URL'),
        )
        summary_model = current_app.config.get('OPENAI_MODEL')

        _report_progress(8, '初始化代码分割器...')
        # 初始化代码分割器
        try:
            import tree_sitter_python
            from tree_sitter import Language, Parser

            py_parser = Parser(Language(tree_sitter_python.language()))

            code_splitter = CodeSplitter(
                language="python",
                chunk_lines=chunk_lines,
                chunk_lines_overlap=chunk_lines_overlap,
                max_chars=max_chars,
                parser=py_parser,
            )
            Settings.text_splitter = code_splitter
            logger.info("使用 CodeSplitter 进行代码分割")
        except Exception as e:
            logger.warning(f"无法初始化 CodeSplitter，将使用默认分割器: {e}")

        # 增量索引模式
        if mode == 'incremental' and not reindex:
            _report_progress(10, '扫描文件变化...')
            files_to_index, files_to_delete, files_skipped = scan_files_for_incremental(
                repo_id, repo_path, supported_exts, exclude_patterns
            )
            
            _report_progress(12, f'发现 {len(files_to_index)} 个新增/修改文件, {len(files_to_delete)} 个删除文件')
            
            # 删除已移除文件的向量
            if files_to_delete:
                delete_indexed_files(repo_id, repo_name, files_to_delete)
            
            # 删除要重新索引的文件的旧向量（避免重复）
            files_to_reindex_paths = [f['file_path'] for f in files_to_index]
            if files_to_reindex_paths:
                delete_indexed_files(repo_id, repo_name, files_to_reindex_paths)
            
            # 如果没有需要索引的文件
            if not files_to_index:
                _report_progress(100, '没有文件需要索引')
                return {
                    'status': 'success',
                    'repo_name': repo_name,
                    'file_count': 0,
                    'chunk_count': 0,
                    'sanitized_count': 0,
                    'mode': 'incremental',
                    'files_added': 0,
                    'files_modified': len(files_to_index),
                    'files_deleted': len(files_to_delete),
                    'files_skipped': len(files_skipped)
                }
            
            # 读取需要索引的文件
            _report_progress(14, '读取需要索引的文件...')
            documents = []
            for file_info in files_to_index:
                full_path = os.path.join(repo_path, file_info['file_path'])
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    doc = Document(
                        text=content,
                        metadata={
                            'repo': repo_name,
                            'file_path': file_info['file_path'],
                            'file_name': os.path.basename(file_info['file_path'])
                        }
                    )
                    documents.append(doc)
                except Exception as e:
                    logger.warning(f"无法读取文件 {full_path}: {e}")
            
            if not documents:
                _report_progress(100, '没有有效的文件内容')
                return {
                    'status': 'success',
                    'repo_name': repo_name,
                    'file_count': 0,
                    'chunk_count': 0,
                    'sanitized_count': 0,
                    'mode': 'incremental',
                    'files_added': 0,
                    'files_modified': len(files_to_index),
                    'files_deleted': len(files_to_delete),
                    'files_skipped': len(files_skipped)
                }
        else:
            # 全量索引模式
            _report_progress(10, '读取代码文件...')
            # 读取代码文件
            reader = SimpleDirectoryReader(
                input_dir=repo_path,
                recursive=True,
                required_exts=supported_exts,
                exclude_hidden=True,
                exclude=exclude_patterns,
            )
            documents = reader.load_data()
            files_to_index = []
            files_to_delete = []
            files_skipped = []

        if not documents:
            raise ValueError("未找到符合条件的代码文件")

        logger.info(f"读取到 {len(documents)} 个文件")
        _report_progress(15, f'读取到 {len(documents)} 个文件，正在清理敏感内容...')

        # 清理敏感内容
        sanitized_documents = []
        sanitized_count = 0

        for doc in documents:
            original_text = doc.text
            cleaned_text = sanitize_sensitive_content(original_text)

            if cleaned_text != original_text:
                sanitized_count += 1
                # 创建新的 Document 对象
                new_doc = Document(
                    text=cleaned_text,
                    metadata={
                        **doc.metadata,
                        'repo': repo_name,
                    }
                )
                sanitized_documents.append(new_doc)
            else:
                # 添加 repo 元数据
                doc.metadata['repo'] = repo_name
                sanitized_documents.append(doc)

        logger.info(f"清理了 {sanitized_count} 个文件中的敏感信息")
        _report_progress(18, f'清理了 {sanitized_count} 个文件中的敏感信息，正在连接数据库...')

        # 获取数据库连接配置
        db_host = current_app.config.get('CODE_INDEX_DB_HOST', 'localhost')
        db_port = current_app.config.get('CODE_INDEX_DB_PORT', 5432)
        db_user = current_app.config.get('CODE_INDEX_DB_USER', 'postgres')
        db_password = current_app.config.get('CODE_INDEX_DB_PASSWORD', 'postgres')
        db_name = current_app.config.get('CODE_INDEX_DB_NAME', 'flask_chat')

        _report_progress(19, '创建两层向量存储...')
        
        # 第一层：文件摘要表
        summaries_table_name = f"code_summaries_{repo_name}"
        summaries_vector_store = PGVectorStore.from_params(
            database=db_name,
            host=db_host,
            port=str(db_port),
            user=db_user,
            password=db_password,
            table_name=summaries_table_name,
            embed_dim=4096,
        )
        
        # 第二层：代码块表
        chunks_table_name = f"code_chunks_{repo_name}"
        chunks_vector_store = PGVectorStore.from_params(
            database=db_name,
            host=db_host,
            port=str(db_port),
            user=db_user,
            password=db_password,
            table_name=chunks_table_name,
            embed_dim=4096,
        )

        # 如果重新索引，先清空表
        if reindex:
            logger.info(f"重新索引模式，将清空表: data_{summaries_table_name}, data_{chunks_table_name}")

        summaries_storage_context = StorageContext.from_defaults(vector_store=summaries_vector_store)
        chunks_storage_context = StorageContext.from_defaults(vector_store=chunks_vector_store)

        # ========== 第一层：生成文件摘要索引 ==========
        _report_progress(20, '生成文件摘要...')
        logger.info("开始生成文件摘要（第一层索引）...")
        
        summary_documents = []
        for i, doc in enumerate(sanitized_documents):
            file_path = doc.metadata.get('file_path', 'unknown')
            
            # 生成摘要
            summary_text = generate_file_summary(file_path, doc.text, summary_client, summary_model)
            
            # 创建摘要文档
            summary_doc = Document(
                text=summary_text,
                metadata={
                    'repo': repo_name,
                    'file_path': file_path,
                    'file_name': doc.metadata.get('file_name', ''),
                    'layer': 'summary',
                }
            )
            summary_documents.append(summary_doc)
            
            # 更新进度 (20% - 35%)
            if (i + 1) % 5 == 0 or i == len(sanitized_documents) - 1:
                progress = 20 + int((i + 1) / len(sanitized_documents) * 15)
                _report_progress(progress, f'已生成 {i + 1}/{len(sanitized_documents)} 个文件摘要')
        
        # 构建第一层索引
        _report_progress(35, '构建文件摘要索引...')
        
        # 临时切换到普通文本分割器（摘要不是代码）
        from llama_index.core.node_parser import SentenceSplitter
        original_splitter = Settings.text_splitter
        Settings.text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
        
        summaries_index = VectorStoreIndex.from_documents(
            summary_documents,
            storage_context=summaries_storage_context,
            show_progress=False,
        )
        
        # 恢复 CodeSplitter
        Settings.text_splitter = original_splitter
        
        logger.info(f"第一层索引完成: {len(summary_documents)} 个文件摘要")

        # ========== 第二层：生成代码块索引 ==========
        _report_progress(40, '开始构建代码块索引...')
        logger.info("开始构建代码块索引（第二层索引）...")
        
        # 分批插入文档，每批更新进度
        batch_size = max(10, len(sanitized_documents) // 10)
        total_batches = (len(sanitized_documents) + batch_size - 1) // batch_size
        processed = 0
        
        # 先用第一批创建索引
        first_batch = sanitized_documents[:batch_size]
        
        # 为每个文档添加 layer 标记
        first_batch_with_layer = []
        for doc in first_batch:
            new_doc = Document(
                text=doc.text,
                metadata={
                    **doc.metadata,
                    'layer': 'chunk',
                }
            )
            first_batch_with_layer.append(new_doc)
        
        chunks_index = VectorStoreIndex.from_documents(
            first_batch_with_layer,
            storage_context=chunks_storage_context,
            show_progress=False,
        )
        processed += len(first_batch)
        progress = 40 + int((processed / len(sanitized_documents)) * 55)
        _report_progress(progress, f'已处理 {processed}/{len(sanitized_documents)} 个文件的代码块')
        
        # 然后逐批插入剩余文档
        for i in range(1, total_batches):
            start_idx = i * batch_size
            end_idx = min(start_idx + batch_size, len(sanitized_documents))
            batch = sanitized_documents[start_idx:end_idx]
            
            # 添加 layer 标记
            batch_with_layer = []
            for doc in batch:
                new_doc = Document(
                    text=doc.text,
                    metadata={
                        **doc.metadata,
                        'layer': 'chunk',
                    }
                )
                batch_with_layer.append(new_doc)
            
            # 插入当前批次
            chunks_index.insert_nodes(batch_with_layer)
            processed += len(batch)
            
            # 更新进度 (40% - 95%)
            progress = 40 + int((processed / len(sanitized_documents)) * 55)
            _report_progress(progress, f'已处理 {processed}/{len(sanitized_documents)} 个文件的代码块')
        
        _report_progress(98, '两层索引构建完成，正在保存...')

        # 获取索引统计
        actual_summaries_table = f"data_{summaries_table_name}"
        actual_chunks_table = f"data_{chunks_table_name}"
        
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_password,
                database=db_name
            )
            cursor = conn.cursor()
            
            # 统计文件摘要数
            cursor.execute(f"SELECT COUNT(*) FROM {actual_summaries_table}")
            num_summaries = cursor.fetchone()[0]
            
            # 统计代码块数
            cursor.execute(f"SELECT COUNT(*) FROM {actual_chunks_table}")
            num_chunks = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            logger.info(f"两层索引完成: {num_summaries} 个文件摘要, {num_chunks} 个代码块")
        except Exception as e:
            logger.warning(f"无法获取索引统计: {e}")
            num_summaries = len(sanitized_documents)
            num_chunks = len(sanitized_documents) * 5  # 估算

        logger.info(f"两层索引构建完成: {len(sanitized_documents)} 个文件, {num_summaries} 个摘要, {num_chunks} 个代码块")

        # 更新 IndexedFile 表记录（增量索引模式下）
        if mode == 'incremental' and not reindex and files_to_index:
            from app.models import IndexedFile, db
            for file_info in files_to_index:
                existing = IndexedFile.query.filter_by(
                    repo_id=repo_id, 
                    file_path=file_info['file_path']
                ).first()
                
                if existing:
                    # 更新已有记录
                    existing.content_hash = file_info['content_hash']
                    existing.file_size = file_info['file_size']
                    existing.last_modified_time = file_info['last_modified_time']
                    existing.last_indexed_time = datetime.utcnow()
                else:
                    # 创建新记录
                    new_record = IndexedFile(
                        repo_id=repo_id,
                        file_path=file_info['file_path'],
                        content_hash=file_info['content_hash'],
                        file_size=file_info['file_size'],
                        last_modified_time=file_info['last_modified_time'],
                        last_indexed_time=datetime.utcnow()
                    )
                    db.session.add(new_record)
            
            db.session.commit()
            logger.info(f"已更新 {len(files_to_index)} 条 IndexedFile 记录")

        return {
            'status': 'success',
            'repo_name': repo_name,
            'file_count': len(sanitized_documents),
            'summary_count': num_summaries,
            'chunk_count': num_chunks,
            'sanitized_count': sanitized_count,
            'mode': mode,
            'files_added': len([f for f in files_to_index if f not in [skip for skip in files_skipped]]),
            'files_modified': len(files_to_index),
            'files_deleted': len(files_to_delete),
            'files_skipped': len(files_skipped)
        }

    except Exception as e:
        if str(e) == '用户取消了索引任务':
            logger.info("索引构建被用户取消")
        else:
            logger.error(f"两层索引构建失败: {e}", exc_info=True)
        return {
            'status': 'error',
            'repo_name': repo_name,
            'error': str(e),
        }


def delete_index(repo_name: str) -> dict:
    """
    删除代码库的两层索引
    
    Args:
        repo_name: 仓库名称
    
    Returns:
        dict: 删除结果
    """
    try:
        from sqlalchemy import create_engine, text

        # 获取数据库连接配置
        db_host = current_app.config.get('CODE_INDEX_DB_HOST', 'localhost')
        db_port = current_app.config.get('CODE_INDEX_DB_PORT', 5432)
        db_user = current_app.config.get('CODE_INDEX_DB_USER', 'postgres')
        db_password = current_app.config.get('CODE_INDEX_DB_PASSWORD', 'postgres')
        db_name = current_app.config.get('CODE_INDEX_DB_NAME', 'flask_chat')

        # 构建数据库 URL
        db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

        engine = create_engine(db_url)
        
        # 删除两个表
        summaries_table = f"data_code_summaries_{repo_name}"
        chunks_table = f"data_code_chunks_{repo_name}"

        with engine.connect() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {summaries_table}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {chunks_table}"))
            conn.commit()

        logger.info(f"已删除两层索引表: {summaries_table}, {chunks_table}")

        return {
            'status': 'success',
            'repo_name': repo_name,
        }

    except Exception as e:
        logger.error(f"删除索引失败: {e}", exc_info=True)
        return {
            'status': 'error',
            'repo_name': repo_name,
            'error': str(e),
        }
