"""
Code Index Builder Service - 代码库索引构建服务
基于 LlamaIndex 实现代码库的向量化索引
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
)
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core.node_parser import CodeSplitter
from llama_index.core.schema import Document

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


def delete_indexed_files(repo_id: int, file_paths: List[str]):
    """从向量存储中删除指定文件的索引"""
    from app.models import IndexedFile, db
    
    if not file_paths:
        return
    
    # 删除数据库记录（级联删除向量存储中的数据）
    for file_path in file_paths:
        record = IndexedFile.query.filter_by(repo_id=repo_id, file_path=file_path).first()
        if record:
            db.session.delete(record)
    
    db.session.commit()
    logger.info(f"已删除 {len(file_paths)} 个文件的索引")


def build_index(repo_id: int, repo_name: str, repo_path: str, reindex: bool = True, mode: str = 'full', progress_callback=None):
    """
    构建代码库索引
    
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
        logger.info(f"开始构建索引: {repo_name} ({repo_path}), 模式: {mode}")

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

        _report_progress(6, '初始化 Embedding 模型...')
        # 初始化 Embedding 模型
        embed_api_base = current_app.config.get('CODE_INDEX_EMBED_API_BASE', 'http://localhost:11434/v1')
        embed_api_key = current_app.config.get('CODE_INDEX_EMBED_API_KEY', 'ollama')
        embed_model = current_app.config.get('CODE_INDEX_EMBED_MODEL', 'qwen3-embedding:8b')

        # 移除 /v1 后缀（OllamaEmbedding 不需要）
        embed_base_url = embed_api_base.rstrip('/').replace('/v1', '')

        embed_model_instance = OllamaEmbedding(
            model_name=embed_model,
            base_url=embed_base_url,
            api_key=embed_api_key,
        )
        Settings.embed_model = embed_model_instance

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
            
            # 删除已移除的文件
            if files_to_delete:
                delete_indexed_files(repo_id, files_to_delete)
            
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

        _report_progress(19, '创建向量存储...')
        # 创建 PGVectorStore
        # PGVectorStore 会自动添加 data_ 前缀，所以传入 code_embeddings_{repo_name}
        # 实际创建的表名是 data_code_embeddings_{repo_name}
        table_name = f"code_embeddings_{repo_name}"

        vector_store = PGVectorStore.from_params(
            database=db_name,
            host=db_host,
            port=str(db_port),
            user=db_user,
            password=db_password,
            table_name=table_name,
            embed_dim=4096,  # qwen3-embedding:8b 的维度
        )

        # 如果重新索引，先清空表
        if reindex:
            logger.info(f"重新索引模式，将清空表: data_{table_name}")
            # PGVectorStore 会在创建时自动处理

        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        _report_progress(20, '开始构建向量索引...')
        # 构建索引 - 批量处理以支持进度更新
        logger.info("开始构建向量索引...")
        
        # 分批插入文档，每批更新进度
        batch_size = max(10, len(sanitized_documents) // 10)  # 分10批，每批至少10个
        total_batches = (len(sanitized_documents) + batch_size - 1) // batch_size
        processed = 0
        
        # 先用第一批创建索引
        first_batch = sanitized_documents[:batch_size]
        index = VectorStoreIndex.from_documents(
            first_batch,
            storage_context=storage_context,
            show_progress=False,
        )
        processed += len(first_batch)
        progress = 20 + int((processed / len(sanitized_documents)) * 75)
        _report_progress(progress, f'已处理 {processed}/{len(sanitized_documents)} 个文件')
        
        # 然后逐批插入剩余文档
        for i in range(1, total_batches):
            start_idx = i * batch_size
            end_idx = min(start_idx + batch_size, len(sanitized_documents))
            batch = sanitized_documents[start_idx:end_idx]
            
            # 插入当前批次
            index.insert_nodes([Document(text=doc.text, metadata=doc.metadata) for doc in batch])
            processed += len(batch)
            
            # 更新进度 (20% - 95%)
            progress = 20 + int((processed / len(sanitized_documents)) * 75)
            _report_progress(progress, f'已处理 {processed}/{len(sanitized_documents)} 个文件')
        
        _report_progress(98, '索引构建完成，正在保存...')

        # 获取索引统计 - 从 PGVectorStore 中查询实际的分块数
        # 注意：PGVectorStore 会自动添加 data_ 前缀，所以实际表名是 data_{table_name}
        actual_table_name = f"data_{table_name}"
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
            cursor.execute(f"SELECT COUNT(*) FROM {actual_table_name}")
            num_chunks = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            logger.info(f"实际分块数: {num_chunks}")
        except Exception as e:
            logger.warning(f"无法获取分块数: {e}, 使用文档数作为估算")
            num_chunks = len(sanitized_documents)

        logger.info(f"索引构建完成: {len(sanitized_documents)} 个文件, {num_chunks} 个分块")

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
            logger.error(f"索引构建失败: {e}", exc_info=True)
        return {
            'status': 'error',
            'repo_name': repo_name,
            'error': str(e),
        }


def delete_index(repo_name: str) -> dict:
    """
    删除代码库索引
    
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
        table_name = f"data_code_embeddings_{repo_name}"

        # 删除表
        with engine.connect() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            conn.commit()

        logger.info(f"已删除索引表: {table_name}")

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
