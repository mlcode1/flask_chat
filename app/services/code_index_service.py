"""
Code Index 服务：查询代码库向量索引
封装对 code_index 项目数据库的查询逻辑，使用 psycopg2 直接查询 pgvector 表
"""
import json
import logging
import psycopg2
from openai import OpenAI
from flask import current_app

logger = logging.getLogger(__name__)


def get_code_index_db_connection():
    """获取 code_index 数据库连接"""
    return psycopg2.connect(
        host=current_app.config["CODE_INDEX_DB_HOST"],
        port=current_app.config["CODE_INDEX_DB_PORT"],
        user=current_app.config["CODE_INDEX_DB_USER"],
        password=current_app.config["CODE_INDEX_DB_PASSWORD"],
        database=current_app.config["CODE_INDEX_DB_NAME"]
    )


def get_embedding_client():
    """获取 embedding 客户端（使用与 code_index 相同的模型）"""
    return OpenAI(
        api_key=current_app.config.get("CODE_INDEX_EMBED_API_KEY", "ollama"),
        base_url=current_app.config["CODE_INDEX_EMBED_API_BASE"],
    )


def get_query_embedding(text: str) -> list[float]:
    """将查询文本转换为向量"""
    client = get_embedding_client()
    model = current_app.config["CODE_INDEX_EMBED_MODEL"]
    response = client.embeddings.create(model=model, input=[text])
    return response.data[0].embedding


def search_code(query: str, repo_name: str = None, top_k: int = None) -> list[dict]:
    """
    在代码库向量索引中搜索相关代码片段
    
    Args:
        query: 查询文本
        repo_name: 仓库名称（不传则使用默认仓库）
        top_k: 返回结果数量（不传则使用配置值）
    
    Returns:
        相关代码片段列表，包含 content, file_path, file_name, file_type, score
    """
    if not current_app.config.get("CODE_INDEX_ENABLED", False):
        return []
    
    if top_k is None:
        top_k = current_app.config.get("CODE_INDEX_TOP_K", 8)
    
    if repo_name is not None:
        # 指定了仓库名，先校验该仓库是否已索引
        indexed_repos = list_indexed_repos()
        if repo_name not in indexed_repos:
            if indexed_repos:
                logger.warning(f"仓库 '{repo_name}' 未索引，已索引的仓库: {', '.join(indexed_repos)}")
            else:
                logger.warning("没有找到任何已索引的代码库")
            return []
    else:
        # 没有指定仓库时，自动查找已索引的仓库
        indexed_repos = list_indexed_repos()
        if not indexed_repos:
            logger.warning("没有找到任何已索引的代码库")
            return []
        # 优先使用配置中的默认仓库，如果它已索引的话
        default_repo = current_app.config.get("CODE_INDEX_DEFAULT_REPO", "")
        if default_repo and default_repo in indexed_repos:
            repo_name = default_repo
        else:
            # 使用第一个已索引的仓库
            repo_name = indexed_repos[0]
            logger.info(f"未指定仓库名，自动选择: {repo_name}")
    
    table_name = f"data_code_embeddings_{repo_name}"
    
    try:
        # 1. 生成查询向量
        query_embedding = get_query_embedding(query)
        
        # 2. 查询数据库
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        # 使用余弦相似度搜索
        sql = f"""
            SELECT 
                text,
                metadata_,
                1 - (embedding <=> %s::vector) as similarity
            FROM {table_name}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        
        cursor.execute(sql, (query_embedding, query_embedding, top_k))
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # 3. 格式化结果
        formatted_results = []
        for text, metadata_json, similarity in results:
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
            except:
                metadata = {}
            
            formatted_results.append({
                "content": text,
                "file_path": metadata.get("file_path", ""),
                "file_name": metadata.get("file_name", ""),
                "file_type": metadata.get("file_type", ""),
                "repo": metadata.get("repo", repo_name),
                "score": float(similarity) if similarity else 0.0,
            })
        
        return formatted_results
        
    except psycopg2.Error as e:
        logger.error(f"Code index 数据库查询失败: {e}")
        return []
    except Exception as e:
        logger.error(f"Code index 查询异常: {e}")
        return []


def list_indexed_repos() -> list[str]:
    """列出已索引的仓库"""
    if not current_app.config.get("CODE_INDEX_ENABLED", False):
        return []
    
    conn = None
    cursor = None
    try:
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        # 查询所有 data_code_embeddings_* 表（llama_index PGVectorStore 固定加 data_ 前缀）
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name LIKE 'data_code_embeddings_%'
        """)
        
        tables = cursor.fetchall()
        
        repos = [table[0].replace("data_code_embeddings_", "") for table in tables]
        return sorted(repos)
        
    except Exception as e:
        logger.error(f"获取已索引仓库列表失败: {e}")
        return []
    finally:
        # 确保连接和游标被正确关闭
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass


def get_repo_stats(repo_name: str) -> dict:
    """获取仓库索引统计信息"""
    if not current_app.config.get("CODE_INDEX_ENABLED", False):
        return {"enabled": False}
    
    table_name = f"data_code_embeddings_{repo_name}"
    
    try:
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (table_name,))
        
        exists = cursor.fetchone()[0]
        
        if not exists:
            cursor.close()
            conn.close()
            return {"enabled": True, "indexed": False}
        
        # 查询统计信息
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        chunk_count = cursor.fetchone()[0]
        
        cursor.execute(f"SELECT COUNT(DISTINCT metadata_->>'file_path') FROM {table_name}")
        file_count = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return {
            "enabled": True,
            "indexed": True,
            "repo_name": repo_name,
            "chunk_count": chunk_count,
            "file_count": file_count,
        }
        
    except Exception as e:
        logger.error(f"获取仓库统计失败: {e}")
        return {"enabled": True, "indexed": False, "error": str(e)}
