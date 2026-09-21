// debug.js - 调试工具

import { formatTokenCount } from './utils.js';

export function showDebugPanel(currentConvId) {
    let panel = document.getElementById("debug-panel");
    if (!panel) {
        panel = document.createElement("div");
        panel.id = "debug-panel";
        panel.className = "debug-panel";
        panel.innerHTML = `
            <div class="debug-header">
                <span>🐛 调试面板</span>
                <button class="close-debug" onclick="this.parentElement.parentElement.style.display='none'">×</button>
            </div>
            <div class="debug-content">
                <div class="debug-section">
                    <h4>系统状态</h4>
                    <div id="debug-system-info">加载中...</div>
                </div>
                <div class="debug-section">
                    <h4>Token 统计</h4>
                    <div id="debug-token-stats">暂无数据</div>
                </div>
                <div class="debug-section">
                    <h4>缓存状态</h4>
                    <div id="debug-cache-info">加载中...</div>
                </div>
            </div>
        `;
        document.body.appendChild(panel);
    } else {
        panel.style.display = "block";
    }
    
    loadDebugInfo(currentConvId);
}

async function loadDebugInfo(currentConvId) {
    try {
        const res = await fetch("/api/health");
        const data = await res.json();
        
        const systemInfo = document.getElementById("debug-system-info");
        systemInfo.innerHTML = `
            <div>状态: <span class="${data.status === 'healthy' ? 'status-ok' : 'status-warn'}">${data.status}</span></div>
            <div>数据库: ${data.database}</div>
            <div>缓存: ${data.cache}</div>
            <div>默认模型: ${data.models?.default || '-'}</div>
            <div>可用模型: ${(data.models?.available || []).join(', ') || '-'}</div>
            <div>时间: ${data.timestamp}</div>
        `;
        
        const cacheInfo = document.getElementById("debug-cache-info");
        if (data.cache_stats) {
            cacheInfo.innerHTML = `
                <div>缓存条目: ${data.cache_stats.total_entries}</div>
                <div>最大容量: ${data.cache_stats.max_size}</div>
            `;
        } else {
            cacheInfo.textContent = "缓存未启用";
        }

        const tokenStatsEl = document.getElementById("debug-token-stats");
        if (currentConvId) {
            try {
                const statsRes = await fetch(`/api/conversations/${currentConvId}/stats`);
                const stats = await statsRes.json();
                tokenStatsEl.innerHTML = `
                    <div class="token-stat-row"><span>总消息数</span><span>${stats.total_messages}</span></div>
                    <div class="token-stat-row"><span>总 Token</span><span class="token-value">${formatTokenCount(stats.total_tokens)}</span></div>
                    <div class="token-stat-row"><span>用户 Token</span><span class="token-value user">${formatTokenCount(stats.user_tokens)}</span></div>
                    <div class="token-stat-row"><span>AI Token</span><span class="token-value ai">${formatTokenCount(stats.assistant_tokens)}</span></div>
                    ${stats.total_tokens > 0 ? `
                    <div class="token-bar">
                        <div class="token-bar-user" style="width:${(stats.user_tokens / stats.total_tokens * 100).toFixed(1)}%" title="用户 ${stats.user_tokens}"></div>
                        <div class="token-bar-ai" style="width:${(stats.assistant_tokens / stats.total_tokens * 100).toFixed(1)}%" title="AI ${stats.assistant_tokens}"></div>
                    </div>` : ''}
                `;
            } catch (e) {
                tokenStatsEl.textContent = "加载失败";
            }
        } else {
            tokenStatsEl.textContent = "请先选择一个对话";
        }
    } catch (e) {
        console.error("加载调试信息失败:", e);
    }
}

export function addDebugButton(getCurrentConvId) {
    const btn = document.createElement("button");
    btn.className = "debug-toggle-btn";
    btn.textContent = "🐛";
    btn.title = "调试面板";
    btn.onclick = () => showDebugPanel(getCurrentConvId());
    document.body.appendChild(btn);
}
