// code-repos.js - 代码库索引管理

import { showToast, showConfirm, showIndexModeConfirm, escapeHtml, formatDate } from './utils.js';

const progressPollingIntervals = {};

export async function loadCodeRepos(codeRepoList, callbacks = {}) {
    try {
        const res = await fetch("/api/code-repos");
        const data = await res.json();
        
        if (data.status === "success" && data.repos.length > 0) {
            codeRepoList.innerHTML = data.repos.map(repo => {
                const isIndexing = repo.status === 'indexing';
                const progressHtml = isIndexing ? `
                    <div class="repo-progress">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${repo.progress || 0}%"></div>
                        </div>
                        <div class="progress-text">${repo.progress_message || '准备中...'}</div>
                    </div>
                ` : '';
                
                return `
                    <div class="code-repo-item" data-id="${repo.id}">
                        <div class="repo-info">
                            <div class="repo-info-left">
                                <div class="repo-name">${repo.name}</div>
                                <div class="repo-path">${repo.path}</div>
                                <span class="repo-status-badge status-${repo.status}">${getStatusText(repo.status)}</span>
                                <div class="repo-stats">
                                    文件: ${repo.file_count || 0} | 分块: ${repo.chunk_count || 0}
                                    ${repo.last_indexed_at ? ' | 最后索引: ' + formatDate(repo.last_indexed_at) : ''}
                                </div>
                                ${progressHtml}
                                ${repo.error_message ? `<div class="repo-error">${repo.error_message}</div>` : ''}
                            </div>
                            <div class="repo-actions">
                                <button class="repo-action-btn search-test-btn" data-id="${repo.id}" title="测试搜索" ${isIndexing ? 'disabled' : ''}>🔍</button>
                                ${isIndexing 
                                    ? `<button class="repo-action-btn cancel-index-btn danger" data-id="${repo.id}" title="取消索引">⏹️</button>`
                                    : `<button class="repo-action-btn refresh-index-btn" data-id="${repo.id}" title="构建索引">🔨</button>`
                                }
                                <button class="repo-action-btn delete-repo-btn danger" data-id="${repo.id}" title="删除" ${isIndexing ? 'disabled' : ''}>🗑️</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join("");
            
            bindCodeRepoEvents(codeRepoList, callbacks);
            
            data.repos.forEach(repo => {
                if (repo.status === 'indexing') {
                    startProgressPolling(repo.id, codeRepoList);
                } else {
                    stopProgressPolling(repo.id);
                }
            });
        } else {
            codeRepoList.innerHTML = '<div class="kb-empty">暂无代码库，点击 + 添加</div>';
        }
    } catch (e) {
        console.error("加载代码库列表失败:", e);
    }
}

function getStatusText(status) {
    const statusMap = {
        'pending': '待索引',
        'indexing': '索引中',
        'indexed': '已索引',
        'failed': '失败'
    };
    return statusMap[status] || status;
}

function startProgressPolling(repoId, codeRepoList) {
    if (progressPollingIntervals[repoId]) return;
    
    progressPollingIntervals[repoId] = setInterval(async () => {
        try {
            const res = await fetch(`/api/code-repos/${repoId}/progress`);
            const data = await res.json();
            
            if (data.status === 'success') {
                const repoItem = document.querySelector(`.code-repo-item[data-id="${repoId}"]`);
                if (repoItem) {
                    const progressFill = repoItem.querySelector('.progress-fill');
                    const progressText = repoItem.querySelector('.progress-text');
                    
                    if (progressFill) {
                        const progressPercent = data.progress || 0;
                        progressFill.style.width = `${progressPercent}%`;
                        progressFill.offsetHeight;
                    }
                    if (progressText) {
                        const progressPercent = data.progress || 0;
                        const message = data.message || '处理中...';
                        progressText.textContent = `${message} (${progressPercent}%)`;
                    }
                }
                
                if (data.repo_status !== 'indexing') {
                    stopProgressPolling(repoId);
                    loadCodeRepos(codeRepoList);
                    
                    if (data.repo_status === 'indexed') {
                        showToast('索引构建完成', 'success');
                    } else if (data.repo_status === 'failed') {
                        showToast('索引构建失败', 'error');
                    }
                }
            }
        } catch (e) {
            console.error('轮询进度失败:', e);
        }
    }, 3000);
}

function stopProgressPolling(repoId) {
    if (progressPollingIntervals[repoId]) {
        clearInterval(progressPollingIntervals[repoId]);
        delete progressPollingIntervals[repoId];
    }
}

function bindCodeRepoEvents(codeRepoList, callbacks = {}) {
    document.querySelectorAll('.search-test-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const repoId = btn.dataset.id;
            if (callbacks.onSearchTest) {
                callbacks.onSearchTest(repoId);
            }
        });
    });

    document.querySelectorAll('.refresh-index-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const repoId = btn.dataset.id;
            const repoItem = btn.closest('.code-repo-item');
            const statusBadge = repoItem.querySelector('.repo-status-badge');
            const isPending = statusBadge && statusBadge.classList.contains('status-pending');
            
            const result = await showIndexModeConfirm(isPending);
            if (result) {
                await triggerIndex(repoId, codeRepoList, result.mode, result.reindex);
            }
        });
    });

    document.querySelectorAll('.delete-repo-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const repoId = btn.dataset.id;
            const confirmed = await showConfirm(
                '删除代码库',
                '确定要删除此代码库配置及其索引吗？此操作不可恢复。'
            );
            if (confirmed) {
                await deleteRepo(repoId, codeRepoList);
            }
        });
    });

    document.querySelectorAll('.cancel-index-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const repoId = btn.dataset.id;
            const confirmed = await showConfirm(
                '取消索引',
                '确定要取消正在进行的索引任务吗？'
            );
            if (confirmed) {
                await cancelIndex(repoId, codeRepoList);
            }
        });
    });
}

export async function triggerIndex(repoId, codeRepoList, mode = 'full', reindex = true) {
    try {
        const res = await fetch(`/api/code-repos/${repoId}/index`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, reindex })
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            const modeText = mode === 'full' ? '全量' : '增量';
            showToast(`${modeText}索引任务已启动`, 'success');
            loadCodeRepos(codeRepoList);
        } else {
            showToast(data.message || '索引失败', 'error');
            loadCodeRepos(codeRepoList);
        }
    } catch (e) {
        showToast('索引失败: ' + e.message, 'error');
        loadCodeRepos(codeRepoList);
    }
}

export async function deleteRepo(repoId, codeRepoList) {
    try {
        const res = await fetch(`/api/code-repos/${repoId}`, {
            method: 'DELETE'
        });
        const data = await res.json();

        if (data.status === 'success') {
            showToast('仓库已删除', 'success');
            loadCodeRepos(codeRepoList);
        } else {
            showToast(data.message || '删除失败', 'error');
        }
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

export async function cancelIndex(repoId, codeRepoList) {
    try {
        const res = await fetch(`/api/code-repos/${repoId}/cancel`, {
            method: 'POST'
        });
        const data = await res.json();

        if (data.status === 'success') {
            showToast('已取消索引任务', 'success');
            stopProgressPolling(repoId);
            loadCodeRepos(codeRepoList);
        } else {
            showToast(data.message || '取消失败', 'error');
        }
    } catch (e) {
        showToast('取消失败: ' + e.message, 'error');
    }
}

export function setupAddRepoButton(addRepoBtn, addRepoModal, confirmAddRepoBtn, codeRepoList) {
    if (addRepoBtn) {
        addRepoBtn.addEventListener('click', () => {
            addRepoModal.style.display = 'flex';
        });
    }

    if (confirmAddRepoBtn) {
        confirmAddRepoBtn.addEventListener('click', async () => {
            const name = document.getElementById('repo-name-input').value.trim();
            const path = document.getElementById('repo-path-input').value.trim();

            if (!name || !path) {
                showToast('请填写仓库名称和路径', 'error');
                return;
            }

            try {
                const res = await fetch('/api/code-repos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, path })
                });
                const data = await res.json();

                if (data.status === 'success') {
                    addRepoModal.style.display = 'none';
                    document.getElementById('repo-name-input').value = '';
                    document.getElementById('repo-path-input').value = '';
                    
                    showToast('仓库已添加', 'success');
                    loadCodeRepos(codeRepoList);
                } else {
                    showToast(data.message || '添加失败', 'error');
                }
            } catch (e) {
                showToast('添加失败: ' + e.message, 'error');
            }
        });
    }
}

export function setupSearchTest(runSearchBtn) {
    if (runSearchBtn) {
        runSearchBtn.addEventListener('click', async () => {
            const query = document.getElementById('search-query-input').value.trim();
            const topK = parseInt(document.getElementById('search-top-k-input').value) || 5;
            const resultsDiv = document.getElementById('search-results');
            const currentRepoForSearch = window.currentRepoForSearch;

            if (!query) {
                showToast('请输入搜索内容', 'error');
                return;
            }

            resultsDiv.innerHTML = '<div class="loading">搜索中...</div>';

            try {
                const res = await fetch('/api/code-repos/test-search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        repo_id: currentRepoForSearch,
                        query: query,
                        top_k: topK
                    })
                });
                const data = await res.json();

                if (data.status === 'success' && data.results && data.results.length > 0) {
                    resultsDiv.innerHTML = `
                        <div class="search-stats">
                            找到 ${data.results.length} 个结果 (耗时: ${data.time_ms}ms)
                        </div>
                        ${data.results.map((result, idx) => `
                            <div class="search-result-item">
                                <div class="search-result-header">
                                    <span class="search-result-file">${result.file_path || result.file_name || 'Unknown'}</span>
                                    <span class="search-result-score">相似度: ${(result.score * 100).toFixed(2)}%</span>
                                </div>
                                <div class="search-result-content">${escapeHtml(result.content)}</div>
                            </div>
                        `).join('')}
                    `;
                } else {
                    resultsDiv.innerHTML = '<div class="kb-empty">未找到相关结果</div>';
                }
            } catch (e) {
                resultsDiv.innerHTML = `<div class="repo-error">搜索失败: ${e.message}</div>`;
            }
        });
    }
}

export async function loadCodeReposCount() {
    try {
        const response = await fetch('/api/code-repos');
        const data = await response.json();
        const count = data.repos ? data.repos.length : 0;
        const badge = document.getElementById('code-repos-count');
        if (badge) {
            badge.textContent = count;
        }
    } catch (error) {
        console.error('加载代码库数量失败:', error);
    }
}
