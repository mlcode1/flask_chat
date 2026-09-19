#!/usr/bin/env python
"""
诊断两层索引问题

对比分析：
1. 检查单层表 (data_code_embeddings_{repo}) 的数据
2. 检查两层表 (data_code_summaries_{repo}, data_code_chunks_{repo}) 的数据
3. 对比元数据结构差异
4. 测试搜索效果
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services import code_index_service

def diagnose(repo_name="code_index"):
    """诊断索引状态"""
    print("=" * 80)
    print(f"诊断索引状态: {repo_name}")
    print("=" * 80)
    
    # 1. 基础诊断
    print("\n【1. 基础状态检查】")
    diag = code_index_service.diagnose_index(repo_name)
    
    print(f"\n状态: {diag['status']}")
    print(f"消息: {diag['message']}")
    
    # 摘要表
    print(f"\n摘要表 (data_code_summaries_{repo_name}):")
    print(f"  存在: {diag['summaries']['exists']}")
    print(f"  记录数: {diag['summaries']['count']}")
    
    # 代码块表
    print(f"\n代码块表 (data_code_chunks_{repo_name}):")
    print(f"  存在: {diag['chunks']['exists']}")
    print(f"  记录数: {diag['chunks']['count']}")
    
    # 旧版单层表
    if 'old_single_layer' in diag:
        print(f"\n旧版单层表 (data_code_embeddings_{repo_name}):")
        print(f"  存在: {diag['old_single_layer']['exists']}")
        print(f"  记录数: {diag['old_single_layer']['count']}")
    
    # 问题和建议
    if diag['issues']:
        print(f"\n发现的问题:")
        for i, issue in enumerate(diag['issues'], 1):
            print(f"  {i}. {issue}")
    
    if diag['suggestions']:
        print(f"\n建议:")
        for i, suggestion in enumerate(diag['suggestions'], 1):
            print(f"  {i}. {suggestion}")
    
    # 2. 元数据结构对比
    print("\n" + "=" * 80)
    print("【2. 元数据结构对比】")
    print("=" * 80)
    
    if diag['summaries']['sample']:
        print("\n摘要表元数据示例:")
        for i, sample in enumerate(diag['summaries']['sample'][:2], 1):
            print(f"\n  示例 {i}:")
            print(f"    文本: {sample['text'][:100]}...")
            print(f"    元数据: {sample['metadata']}")
    
    if diag['chunks']['sample']:
        print("\n代码块表元数据示例:")
        for i, sample in enumerate(diag['chunks']['sample'][:2], 1):
            print(f"\n  示例 {i}:")
            print(f"    文本: {sample['text'][:100]}...")
            print(f"    元数据: {sample['metadata']}")
    
    # 3. 搜索测试
    print("\n" + "=" * 80)
    print("【3. 搜索测试】")
    print("=" * 80)
    
    test_query = f"{repo_name}这个项目是干什么的"
    print(f"\n测试查询: {test_query}")
    
    # 测试第一层
    print("\n--- 第一层搜索（仅摘要） ---")
    result1 = code_index_service.test_search(test_query, repo_name, mode="first-layer")
    print(f"结果数: {result1.get('debug', {}).get('result_count', 0)}")
    if result1['results']:
        for i, r in enumerate(result1['results'][:3], 1):
            print(f"\n  结果 {i} (相似度: {r['score']:.3f}):")
            print(f"    文件: {r['metadata'].get('file_path', 'N/A')}")
            print(f"    内容: {r['text'][:150]}...")
    
    # 测试第二层（全量）
    print("\n--- 第二层搜索（全量代码块） ---")
    result2 = code_index_service.test_search(test_query, repo_name, mode="second-layer")
    print(f"结果数: {result2.get('debug', {}).get('result_count', 0)}")
    if result2['results']:
        for i, r in enumerate(result2['results'][:3], 1):
            print(f"\n  结果 {i} (相似度: {r['score']:.3f}):")
            print(f"    文件: {r['metadata'].get('file_path', 'N/A')}")
            print(f"    内容: {r['text'][:150]}...")
    
    # 测试完整两层搜索
    print("\n--- 完整两层搜索 ---")
    result3 = code_index_service.test_search(test_query, repo_name, mode="two-layer")
    print(f"结果数: {result3.get('debug', {}).get('result_count', 0)}")
    if result3['results']:
        for i, r in enumerate(result3['results'][:3], 1):
            print(f"\n  结果 {i} (相似度: {r['score']:.3f}):")
            print(f"    文件: {r['metadata'].get('file_path', 'N/A')}")
            print(f"    内容: {r['text'][:150]}...")
    
    # 测试降级搜索
    print("\n--- 降级搜索（直接搜索代码块） ---")
    result4 = code_index_service.test_search(test_query, repo_name, mode="fallback")
    print(f"结果数: {result4.get('debug', {}).get('result_count', 0)}")
    if result4['results']:
        for i, r in enumerate(result4['results'][:3], 1):
            print(f"\n  结果 {i} (相似度: {r['score']:.3f}):")
            print(f"    文件: {r['metadata'].get('file_path', 'N/A')}")
            print(f"    内容: {r['text'][:150]}...")
    
    # 4. 根本原因分析
    print("\n" + "=" * 80)
    print("【4. 根本原因分析】")
    print("=" * 80)
    
    if result1.get('debug', {}).get('result_count', 0) == 0:
        print("\n❌ 第一层搜索无结果")
        print("   原因: 摘要表为空或不存在")
        print("   解决: 需要重新构建两层索引")
    
    if result2.get('debug', {}).get('result_count', 0) == 0:
        print("\n❌ 第二层搜索无结果")
        print("   原因: 代码块表为空或不存在")
        print("   解决: 需要重新构建两层索引")
    
    if (result1.get('debug', {}).get('result_count', 0) > 0 and 
        result2.get('debug', {}).get('result_count', 0) > 0 and
        result3.get('debug', {}).get('result_count', 0) == 0):
        print("\n❌ 两层搜索无结果，但单层搜索有结果")
        print("   原因: 第一层和第二层的 file_path 不匹配")
        print("   可能:")
        print("     1. 摘要表的 metadata 中没有 file_path")
        print("     2. 代码块表的 metadata 中没有 file_path")
        print("     3. 两层表的 file_path 格式不一致")
        print("   解决: 检查元数据结构，确保两层表的 file_path 一致")
    
    if (result2.get('debug', {}).get('result_count', 0) > 0 and
        result4.get('debug', {}).get('result_count', 0) > 0 and
        result3.get('debug', {}).get('result_count', 0) == 0):
        print("\n❌ 降级搜索有结果，但两层搜索无结果")
        print("   原因: 两层搜索的文件过滤逻辑有问题")
        print("   可能:")
        print("     1. 第一层返回的 file_path 在第二层表中不存在")
        print("     2. SQL 查询的 IN 子句有问题")
        print("   解决: 检查第一层返回的 file_path 列表，对比第二层表中的 file_path")
    
    print("\n" + "=" * 80)
    print("【5. 解决方案】")
    print("=" * 80)
    
    print("\n如果两层表不存在或为空:")
    print("  1. 在代码库管理页面，删除 code_index 仓库")
    print("  2. 重新添加 code_index 仓库")
    print("  3. 点击'构建索引'（选择全量构建）")
    print("  4. 等待索引构建完成")
    print("  5. 再次测试搜索")
    
    print("\n如果两层表存在但搜索失败:")
    print("  1. 检查上面的元数据结构对比，确认 file_path 格式一致")
    print("  2. 查看第一层搜索返回的 file_path 列表")
    print("  3. 对比第二层表中的 file_path 列表")
    print("  4. 如果不一致，需要修复索引构建逻辑")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        repo = sys.argv[1] if len(sys.argv) > 1 else "code_index"
        diagnose(repo)
