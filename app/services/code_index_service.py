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


def _parse_metadata(metadata_json):
    """
    解析元数据，兼容 JSONB 和 JSON 字符串两种格式
    
    PGVectorStore 的 metadata_ 列是 JSONB 格式，psycopg2 读取时自动转为 dict。
    但也可能是 JSON 字符串格式，需要兼容处理。
    """
    if metadata_json is None:
        return {}
    if isinstance(metadata_json, dict):
        return metadata_json
    if isinstance(metadata_json, str):
        try:
            return json.loads(metadata_json)
        except:
            return {}
    return {}


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
    """获取 embedding 客户端（统一使用 EMBEDDING_* 配置）"""
    return OpenAI(
        api_key=current_app.config.get("EMBEDDING_API_KEY", "ollama"),
        base_url=current_app.config["EMBEDDING_BASE_URL"],
    )


def get_query_embedding(text: str) -> list[float]:
    """将查询文本转换为向量"""
    client = get_embedding_client()
    model = current_app.config["EMBEDDING_MODEL"]
    response = client.embeddings.create(model=model, input=[text])
    return response.data[0].embedding


def search_code(query: str, repo_name: str = None, top_k: int = None, user_id: int = None) -> list[dict]:
    """
    在代码库两层索引中搜索相关代码片段
    
    搜索流程：
    1. 第一层：在文件摘要中找到最相关的3-5个文件
    2. 第二层：在这些文件的代码块中精确搜索
    3. 降级：如果两层搜索无结果，回退到单层全量搜索
    
    Args:
        query: 查询文本
        repo_name: 仓库名称（不传则搜索用户所有仓库）
        top_k: 返回结果数量（不传则使用配置值）
        user_id: 用户ID，用于权限隔离（只搜索该用户拥有的仓库）
    
    Returns:
        相关代码片段列表，包含 content, file_path, file_name, file_type, score
    """
    if not current_app.config.get("CODE_INDEX_ENABLED", False):
        logger.warning("代码索引功能未启用")
        return []
    
    if top_k is None:
        top_k = current_app.config.get("CODE_INDEX_TOP_K", 8)
    
    if repo_name is not None:
        # 指定了仓库名，校验该用户是否有权限访问
        if user_id is not None:
            allowed_repos = list_indexed_repos(user_id=user_id)
            if repo_name not in allowed_repos:
                logger.warning(f"用户 {user_id} 无权访问仓库 {repo_name}")
                return []
        repos_to_search = [repo_name]
    else:
        # 没有指定仓库时，搜索该用户有权限的所有仓库
        indexed_repos = list_indexed_repos(user_id=user_id)
        if not indexed_repos:
            logger.warning("没有找到任何已索引的代码库")
            return []
        repos_to_search = indexed_repos
        logger.info(f"未指定仓库名，搜索用户可访问的仓库: {', '.join(repos_to_search)}")
    
    all_results = []
    
    for repo_name in repos_to_search:
        logger.info(f"开始两层搜索: repo={repo_name}, query={query[:50]}, top_k={top_k}")
        
        summaries_table = f"data_code_summaries_{repo_name}"
        chunks_table = f"data_code_chunks_{repo_name}"
        
        try:
            # 1. 生成查询向量
            query_embedding = get_query_embedding(query)
            logger.info(f"查询向量生成成功，维度: {len(query_embedding)}")
            
            # 2. 查询数据库
            conn = get_code_index_db_connection()
            cursor = conn.cursor()
            
            # ========== 第一层：在文件摘要中查找最相关的文件 ==========
            logger.info(f"第一层搜索: 查询 {summaries_table} 表")
            summary_sql = f"""
                SELECT 
                    text,
                    metadata_,
                    1 - (embedding <=> %s::vector) as similarity
                FROM {summaries_table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            
            cursor.execute(summary_sql, (query_embedding, query_embedding, top_k * 2))
            summary_results = cursor.fetchall()
            
            logger.info(f"第一层搜索结果: {len(summary_results)} 条")
            
            if not summary_results:
                logger.warning("第一层搜索未找到任何结果，尝试降级到单层搜索")
                cursor.close()
                conn.close()
                # 降级到单层搜索
                fallback_results = _fallback_single_layer_search(query, repo_name, top_k, query_embedding)
                all_results.extend(fallback_results)
                continue
            
            # 提取相关文件路径
            relevant_files = []
            for i, (_, metadata_json, similarity) in enumerate(summary_results):
                try:
                    metadata = _parse_metadata(metadata_json)
                    file_path = metadata.get('file_path', '')
                    if file_path and file_path not in relevant_files:
                        relevant_files.append(file_path)
                        if i < 3:  # 只记录前3个
                            logger.debug(f"  相关文件 {i+1}: {file_path} (相似度: {similarity:.3f})")
                except:
                    pass
            
            if not relevant_files:
                logger.warning("第一层搜索未提取到文件路径，尝试降级到单层搜索")
                cursor.close()
                conn.close()
                fallback_results = _fallback_single_layer_search(query, repo_name, top_k, query_embedding)
                all_results.extend(fallback_results)
                continue
            
            logger.info(f"第一层搜索找到 {len(relevant_files)} 个相关文件")
            
            # ========== 第二层：在相关文件的代码块中精确搜索 ==========
            logger.info(f"第二层搜索: 在 {len(relevant_files)} 个文件中查询 {chunks_table} 表")
            
            # 构建 IN 子句（使用参数化查询防止 SQL 注入）
            placeholders = ','.join(['%s'] * len(relevant_files))
            
            chunk_sql = f"""
                SELECT 
                    text,
                    metadata_,
                    1 - (embedding <=> %s::vector) as similarity
                FROM {chunks_table}
                WHERE metadata_->>'file_path' IN ({placeholders})
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            
            # 参数：query_embedding, file_paths..., query_embedding, top_k
            chunk_params = [query_embedding] + relevant_files + [query_embedding, top_k]
            cursor.execute(chunk_sql, chunk_params)
            chunk_results = cursor.fetchall()
            
            logger.info(f"第二层搜索结果: {len(chunk_results)} 条")
            
            cursor.close()
            conn.close()
            
            # 3. 格式化结果
            for text, metadata_json, similarity in chunk_results:
                try:
                    metadata = _parse_metadata(metadata_json)
                except:
                    metadata = {}
                
                all_results.append({
                    "content": text,
                    "file_path": metadata.get("file_path", ""),
                    "file_name": metadata.get("file_name", ""),
                    "file_type": metadata.get("file_type", ""),
                    "repo": metadata.get("repo", repo_name),
                    "score": float(similarity) if similarity else 0.0,
                })
            
            if not chunk_results:
                logger.warning("两层搜索未返回结果，尝试降级到单层搜索")
                fallback_results = _fallback_single_layer_search(query, repo_name, top_k, query_embedding)
                all_results.extend(fallback_results)
            
        except psycopg2.Error as e:
            # 表不存在（LLM 幻觉编造仓库名）是正常情况，降级为 WARNING
            if "does not exist" in str(e):
                logger.warning(f"仓库 '{repo_name}' 的索引表不存在（可能是 LLM 幻觉）")
            else:
                logger.error(f"Code index 数据库查询失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Code index 查询异常: {e}", exc_info=True)
    
    # 按分数排序，取前 top_k 个
    all_results.sort(key=lambda x: x['score'], reverse=True)
    formatted_results = all_results[:top_k]
    
    logger.info(f"跨仓库搜索完成，共返回 {len(formatted_results)} 个代码块（来自 {len(repos_to_search)} 个仓库）")
    return formatted_results


def _fallback_single_layer_search(query: str, repo_name: str, top_k: int, query_embedding: list) -> list[dict]:
    """
    降级到单层搜索：直接搜索代码块，不使用摘要过滤
    
    用于处理两层搜索失败的情况（如概括性问题）
    """
    logger.info(f"执行降级单层搜索: repo={repo_name}, query={query[:50]}")
    
    chunks_table = f"data_code_chunks_{repo_name}"
    
    try:
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        # 直接搜索代码块，不使用文件过滤
        sql = f"""
            SELECT 
                text,
                metadata_,
                1 - (embedding <=> %s::vector) as similarity
            FROM {chunks_table}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        
        cursor.execute(sql, (query_embedding, query_embedding, top_k))
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        logger.info(f"单层搜索结果: {len(results)} 条")
        
        # 格式化结果
        formatted_results = []
        for text, metadata_json, similarity in results:
            try:
                metadata = _parse_metadata(metadata_json)
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
        
    except Exception as e:
        logger.error(f"降级搜索失败: {e}", exc_info=True)
        return []


def list_indexed_repos(user_id=None) -> list[str]:
    """列出已索引的仓库
    
    Args:
        user_id: 用户ID。如果提供，只返回该用户拥有的仓库 + 公共仓库（user_id IS NULL）。
                 如果不提供，返回所有仓库（向后兼容）。
    """
    if not current_app.config.get("CODE_INDEX_ENABLED", False):
        return []
    
    try:
        from app.extensions import db
        from app.models import CodeRepository
        
        # 获取所有已索引的仓库名称（从 code_index 数据库的表名推断）
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name LIKE 'data_code_summaries_%'
        """)
        indexed_table_names = set(
            row[0].replace("data_code_summaries_", "") for row in cursor.fetchall()
        )
        cursor.close()
        conn.close()
        
        if not indexed_table_names:
            return []
        
        # 从 flask_chat 数据库的 code_repositories 表查询用户权限
        query = CodeRepository.query.filter(
            CodeRepository.name.in_(indexed_table_names),
            CodeRepository.status == 'indexed'
        )
        
        if user_id is not None:
            # 只返回当前用户拥有的仓库 + 公共仓库（user_id IS NULL）
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    CodeRepository.user_id == user_id,
                    CodeRepository.user_id == None
                )
            )
        
        repos = [repo.name for repo in query.all()]
        return sorted(repos)
        
    except Exception as e:
        logger.error(f"获取已索引仓库列表失败: {e}")
        return []


def diagnose_index(repo_name: str) -> dict:
    """
    诊断索引状态：检查两层索引的数据完整性
    
    Returns:
        dict: 包含各层数据状态、示例数据、问题诊断
    """
    logger.info(f"开始诊断索引: repo={repo_name}")
    
    summaries_table = f"data_code_summaries_{repo_name}"
    chunks_table = f"data_code_chunks_{repo_name}"
    
    result = {
        "repo_name": repo_name,
        "summaries": {"exists": False, "count": 0, "sample": []},
        "chunks": {"exists": False, "count": 0, "sample": []},
        "issues": [],
        "suggestions": []
    }
    
    try:
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        # 检查第一层：摘要表
        logger.info(f"检查摘要表: {summaries_table}")
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (summaries_table,))
        
        summaries_exists = cursor.fetchone()[0]
        result["summaries"]["exists"] = summaries_exists
        
        if summaries_exists:
            cursor.execute(f"SELECT COUNT(*) FROM {summaries_table}")
            result["summaries"]["count"] = cursor.fetchone()[0]
            
            if result["summaries"]["count"] > 0:
                # 获取示例数据
                cursor.execute(f"""
                    SELECT text, metadata_
                    FROM {summaries_table}
                    LIMIT 3
                """)
                samples = cursor.fetchall()
                result["summaries"]["sample"] = [
                    {"text": text[:200], "metadata": _parse_metadata(meta)}
                    for text, meta in samples
                ]
                logger.info(f"摘要表有 {result['summaries']['count']} 条记录")
            else:
                result["issues"].append("摘要表存在但为空")
                result["suggestions"].append("需要重新构建索引，或检查索引构建是否成功")
        else:
            result["issues"].append(f"摘要表不存在: {summaries_table}")
            result["suggestions"].append("可能使用了旧版单层索引，需要删除后重新构建两层索引")
        
        # 检查第二层：代码块表
        logger.info(f"检查代码块表: {chunks_table}")
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (chunks_table,))
        
        chunks_exists = cursor.fetchone()[0]
        result["chunks"]["exists"] = chunks_exists
        
        if chunks_exists:
            cursor.execute(f"SELECT COUNT(*) FROM {chunks_table}")
            result["chunks"]["count"] = cursor.fetchone()[0]
            
            if result["chunks"]["count"] > 0:
                # 获取示例数据
                cursor.execute(f"""
                    SELECT text, metadata_
                    FROM {chunks_table}
                    LIMIT 3
                """)
                samples = cursor.fetchall()
                result["chunks"]["sample"] = [
                    {"text": text[:200], "metadata": _parse_metadata(meta)}
                    for text, meta in samples
                ]
                logger.info(f"代码块表有 {result['chunks']['count']} 条记录")
                
                # 检查文件路径一致性
                if summaries_exists and result["summaries"]["count"] > 0:
                    cursor.execute(f"""
                        SELECT COUNT(DISTINCT metadata_->>'file_path')
                        FROM {chunks_table}
                    """)
                    unique_files = cursor.fetchone()[0]
                    result["chunks"]["unique_files"] = unique_files
                    logger.info(f"代码块表包含 {unique_files} 个不同文件")
            else:
                result["issues"].append("代码块表存在但为空")
                result["suggestions"].append("需要重新构建索引")
        else:
            result["issues"].append(f"代码块表不存在: {chunks_table}")
            result["suggestions"].append("可能使用了旧版单层索引，需要删除后重新构建两层索引")
        
        # 检查旧的单层表
        old_table = f"data_code_embeddings_{repo_name}"
        logger.info(f"检查旧版单层表: {old_table}")
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (old_table,))
        
        old_exists = cursor.fetchone()[0]
        if old_exists:
            result["old_single_layer"] = {"exists": True}
            cursor.execute(f"SELECT COUNT(*) FROM {old_table}")
            result["old_single_layer"]["count"] = cursor.fetchone()[0]
            result["issues"].append(f"发现旧版单层索引表: {old_table}")
            result["suggestions"].append("建议删除旧表后重新构建两层索引")
            logger.warning(f"发现旧版单层表，有 {result['old_single_layer']['count']} 条记录")
        
        cursor.close()
        conn.close()
        
        # 综合诊断
        if not result["issues"]:
            if result["summaries"]["count"] > 0 and result["chunks"]["count"] > 0:
                result["status"] = "healthy"
                result["message"] = f"索引健康: {result['summaries']['count']} 个文件摘要, {result['chunks']['count']} 个代码块"
            else:
                result["status"] = "empty"
                result["message"] = "索引表存在但数据为空"
        else:
            result["status"] = "error"
            result["message"] = f"发现 {len(result['issues'])} 个问题"
        
        logger.info(f"诊断完成: {result['status']} - {result['message']}")
        return result
        
    except Exception as e:
        logger.error(f"诊断失败: {e}", exc_info=True)
        return {
            "repo_name": repo_name,
            "status": "error",
            "message": f"诊断过程出错: {str(e)}",
            "issues": [str(e)]
        }


def test_search(query: str, repo_name: str, mode: str = "two-layer") -> dict:
    """
    测试搜索：支持分别测试第一层、第二层、降级搜索
    
    Args:
        query: 查询文本
        repo_name: 仓库名称
        mode: 搜索模式 - "first-layer", "second-layer", "fallback", "two-layer"
    
    Returns:
        dict: 包含搜索结果和调试信息
    """
    logger.info(f"测试搜索: repo={repo_name}, query={query[:50]}, mode={mode}")
    
    summaries_table = f"data_code_summaries_{repo_name}"
    chunks_table = f"data_code_chunks_{repo_name}"
    
    result = {
        "mode": mode,
        "query": query,
        "repo_name": repo_name,
        "results": [],
        "debug": {}
    }
    
    try:
        # 生成查询向量
        query_embedding = get_query_embedding(query)
        result["debug"]["embedding_dim"] = len(query_embedding)
        
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        if mode == "first-layer":
            # 只测试第一层
            logger.info("测试第一层搜索")
            sql = f"""
                SELECT text, metadata_, 1 - (embedding <=> %s::vector) as similarity
                FROM {summaries_table}
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """
            cursor.execute(sql, (query_embedding, query_embedding))
            rows = cursor.fetchall()
            
            result["results"] = [
                {
                    "text": text[:300],
                    "metadata": _parse_metadata(meta),
                    "score": float(score)
                }
                for text, meta, score in rows
            ]
            result["debug"]["result_count"] = len(rows)
            
        elif mode == "second-layer":
            # 只测试第二层（全量搜索，不过滤文件）
            logger.info("测试第二层搜索（全量）")
            sql = f"""
                SELECT text, metadata_, 1 - (embedding <=> %s::vector) as similarity
                FROM {chunks_table}
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """
            cursor.execute(sql, (query_embedding, query_embedding))
            rows = cursor.fetchall()
            
            result["results"] = [
                {
                    "text": text[:300],
                    "metadata": _parse_metadata(meta),
                    "score": float(score)
                }
                for text, meta, score in rows
            ]
            result["debug"]["result_count"] = len(rows)
            
        elif mode == "fallback":
            # 测试降级搜索
            logger.info("测试降级搜索")
            result["results"] = _fallback_single_layer_search(query, repo_name, 10, query_embedding)
            result["debug"]["result_count"] = len(result["results"])
            
        elif mode == "two-layer":
            # 测试完整的两层搜索
            logger.info("测试完整两层搜索")
            result["results"] = search_code(query, repo_name, 10)
            result["debug"]["result_count"] = len(result["results"])
        
        cursor.close()
        conn.close()
        
        logger.info(f"测试完成: 返回 {len(result['results'])} 条结果")
        return result
        
    except Exception as e:
        logger.error(f"测试搜索失败: {e}", exc_info=True)
        return {
            "mode": mode,
            "query": query,
            "repo_name": repo_name,
            "error": str(e),
            "results": []
        }


def get_repo_stats(repo_name: str) -> dict:
    """获取仓库索引统计信息"""
    if not current_app.config.get("CODE_INDEX_ENABLED", False):
        return {"enabled": False}
    
    summaries_table = f"data_code_summaries_{repo_name}"
    chunks_table = f"data_code_chunks_{repo_name}"
    
    try:
        conn = get_code_index_db_connection()
        cursor = conn.cursor()
        
        # 检查第一层表是否存在
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (summaries_table,))
        
        summaries_exists = cursor.fetchone()[0]
        
        # 检查第二层表是否存在
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (chunks_table,))
        
        chunks_exists = cursor.fetchone()[0]
        
        if not (summaries_exists and chunks_exists):
            cursor.close()
            conn.close()
            return {"enabled": True, "indexed": False}
        
        # 查询统计信息
        cursor.execute(f"SELECT COUNT(*) FROM {summaries_table}")
        summary_count = cursor.fetchone()[0]
        
        cursor.execute(f"SELECT COUNT(*) FROM {chunks_table}")
        chunk_count = cursor.fetchone()[0]
        
        cursor.execute(f"SELECT COUNT(DISTINCT metadata_->>'file_path') FROM {chunks_table}")
        file_count = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return {
            "enabled": True,
            "indexed": True,
            "repo_name": repo_name,
            "summary_count": summary_count,
            "chunk_count": chunk_count,
            "file_count": file_count,
        }
        
    except Exception as e:
        logger.error(f"获取仓库统计失败: {e}")
        return {"enabled": True, "indexed": False, "error": str(e)}
