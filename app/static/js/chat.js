(function () {
    // ========== 元素引用（可能为 null，需做安全检查） ==========
    const messagesContainer = document.getElementById("messages-container");
    const messageInput = document.getElementById("message-input");
    const sendBtn = document.getElementById("send-btn");
    const interruptBtn = document.getElementById("interrupt-btn");
    const newChatBtn = document.getElementById("new-chat-btn");
    const convList = document.getElementById("conversation-list");
    const modelSelector = document.getElementById("model-selector");
    const fileUpload = document.getElementById("file-upload");
    const kbDocList = document.getElementById("kb-doc-list");
    const verifySwitch = document.getElementById("verify-switch");
    const knowledgeSearchSwitch = document.getElementById("knowledge-search-switch");
    const codeIndexSwitch = document.getElementById("code-index-switch");
    const shareBtn = document.getElementById("share-btn");
    const exportBtn = document.getElementById("export-btn");
    const codeRepoList = document.getElementById("code-repo-list");

    // 判断当前页面类型
    const isChatPage = !!messagesContainer;
    const isCodeReposPage = !!codeRepoList && !isChatPage;

    let currentConvId = null;
    let isStreaming = false;
    let verifyEnabled = false;
    
    // ========== Socket.IO 连接 ==========
    let socket = null;
    let currentMessageId = null;  // 当前正在生成的消息ID
    let currentBubble = null;     // 当前正在显示的气泡
    let fullContent = "";         // 累积的完整内容
    let toolCalls = [];           // 工具调用记录
    
    // 初始化 Socket.IO 连接
    function initSocket() {
        if (socket) return;  // 已连接
        
        socket = io({
            transports: ['websocket'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 5
        });
        
        // 连接成功
        socket.on('connect', () => {
            console.log('WebSocket 已连接');
            // 如果有当前对话，加入对应的房间
            if (currentConvId) {
                socket.emit('join', { conversation_id: currentConvId });
            }
        });
        
        // 连接断开
        socket.on('disconnect', () => {
            console.log('WebSocket 已断开');
        });
        
        // 接收 token
        socket.on('token', (data) => {
            // 如果当前没有 message_id 但有 bubble，说明是刚发送的消息，自动绑定
            if (!currentMessageId && currentBubble) {
                currentMessageId = data.message_id;
                console.log('[WS] Auto-bound message_id from first token:', currentMessageId);
            }
            
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            fullContent += data.token;
            const cursor = currentBubble.querySelector(".typing-cursor");
            if (cursor) cursor.remove();
            currentBubble.innerHTML = formatContent(fullContent);
            currentBubble.appendChild(createCursor());
            scrollToBottom();
        });
        
        // 接收工具调用
        socket.on('tool_calls', (data) => {
            // 同样支持自动绑定
            if (!currentMessageId && currentBubble) {
                currentMessageId = data.message_id;
                console.log('[WS] Auto-bound message_id from tool_calls:', currentMessageId);
            }
            
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            toolCalls = toolCalls.concat(data.tool_calls);
            renderToolCalls(currentBubble, toolCalls);
            scrollToBottom();
        });
        
        // 生成完成
        socket.on('generation_completed', (data) => {
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            const cursor = currentBubble.querySelector(".typing-cursor");
            if (cursor) cursor.remove();
            
            fullContent = data.content;
            currentBubble.innerHTML = formatContent(fullContent);
            
            // 重置状态
            isStreaming = false;
            sendBtn.disabled = false;
            interruptBtn.style.display = "none";
            currentMessageId = null;
            currentBubble = null;
            fullContent = "";
            toolCalls = [];
        });
        
        // 生成被停止
        socket.on('generation_stopped', (data) => {
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            const cursor = currentBubble.querySelector(".typing-cursor");
            if (cursor) cursor.remove();
            
            // 显示已停止标记
            const tag = document.createElement("span");
            tag.className = "interrupted-tag";
            tag.textContent = "已打断";
            currentBubble.appendChild(tag);
            
            // 重置状态
            isStreaming = false;
            sendBtn.disabled = false;
            interruptBtn.style.display = "none";
            currentMessageId = null;
            currentBubble = null;
            fullContent = "";
            toolCalls = [];
        });
        
        // 验证开始
        socket.on('verifying', (data) => {
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            const indicator = document.createElement("div");
            indicator.className = "verifying-indicator";
            indicator.id = "current-verifying";
            indicator.innerHTML = `<span class="dot-loader"></span><span>正在进行结果验证...</span>`;
            currentBubble.appendChild(indicator);
            scrollToBottom();
        });
        
        // 验证完成
        socket.on('verified', (data) => {
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            const indicator = document.getElementById("current-verifying");
            if (indicator) indicator.remove();
            
            renderVerification(currentBubble, data.verification);
            scrollToBottom();
        });
        
        // 错误
        socket.on('generation_error', (data) => {
            if (!currentBubble || currentMessageId !== data.message_id) return;
            
            currentBubble.innerHTML = `
                <div class="error-state">
                    <span style="color:var(--danger)">回复失败，请重试</span>
                    <button class="retry-btn">重试</button>
                </div>`;
            currentBubble.querySelector(".retry-btn").onclick = () => {
                currentBubble.parentElement.remove();
                messageInput.value = data.user_content;
                sendMessage();
            };
            
            // 重置状态
            isStreaming = false;
            sendBtn.disabled = false;
            interruptBtn.style.display = "none";
            currentMessageId = null;
            currentBubble = null;
            fullContent = "";
            toolCalls = [];
        });
        
        // 恢复中断的生成（断点续传）
        socket.on('generation_resume', (data) => {
            // 如果当前没有正在进行的生成，但有消息ID，说明是恢复
            if (!isStreaming && data.message_id) {
                currentMessageId = data.message_id;
                fullContent = data.content || "";
                currentBubble = createStreamingBubble();
                
                if (fullContent) {
                    currentBubble.innerHTML = formatContent(fullContent);
                    currentBubble.appendChild(createCursor());
                }
                
                isStreaming = true;
                sendBtn.disabled = true;
                interruptBtn.style.display = "inline-block";
            }
        });
    }
    
    // 初始化连接（仅在聊天页面）
    if (isChatPage) {
        initSocket();
    }

    // ========== 通用函数 ==========
    function scrollToBottom() {
        if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // ========== 聊天页专用初始化 ==========
    if (isChatPage) {
        if (modelSelector) loadModels();
        if (verifySwitch) loadVerifyConfig();
        loadToolsConfig();
        if (kbDocList) loadDocuments();
        addDebugButton();

        const activeConvs = document.querySelectorAll(".conversation-item");
        if (activeConvs.length > 0) {
            currentConvId = activeConvs[0].dataset.id;
            loadMessages(currentConvId);
        }
    }

    async function loadModels() {
        try {
            const res = await fetch("/api/models");
            const data = await res.json();
            modelSelector.innerHTML = "";
            data.models.forEach(m => {
                const opt = document.createElement("option");
                opt.value = m;
                opt.textContent = m;
                if (m === data.default) opt.selected = true;
                modelSelector.appendChild(opt);
            });
        } catch (e) {
            console.error("加载模型列表失败:", e);
        }
    }

    async function loadVerifyConfig() {
        if (!verifySwitch) return;
        try {
            const res = await fetch("/api/config/verify");
            const data = await res.json();
            verifyEnabled = data.enabled;
            verifySwitch.checked = verifyEnabled;
        } catch (e) {
            console.error("加载验证配置失败:", e);
        }
    }

    async function loadToolsConfig() {
        if (!knowledgeSearchSwitch && !codeIndexSwitch) return;
        try {
            const res = await fetch("/api/config/tools");
            const data = await res.json();
            if (knowledgeSearchSwitch) knowledgeSearchSwitch.checked = data.knowledge_search;
            if (codeIndexSwitch) codeIndexSwitch.checked = data.code_index;
        } catch (e) {
            console.error("加载工具配置失败:", e);
        }
    }

    if (knowledgeSearchSwitch) {
        knowledgeSearchSwitch.addEventListener("change", async function() {
            try {
                await fetch("/api/config/tools", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ knowledge_search: this.checked })
                });
            } catch (e) {
                console.error("更新知识库查询配置失败:", e);
                this.checked = !this.checked;
            }
        });
    }

    if (codeIndexSwitch) {
        codeIndexSwitch.addEventListener("change", async function() {
            try {
                await fetch("/api/config/tools", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ code_index: this.checked })
                });
            } catch (e) {
                console.error("更新代码库查询配置失败:", e);
                this.checked = !this.checked;
            }
        });
    }

    if (verifySwitch) {
        verifySwitch.addEventListener("change", async function() {
            verifyEnabled = this.checked;
            try {
                await fetch("/api/config/verify", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ enabled: verifyEnabled })
                });
            } catch (e) {
                console.error("更新验证配置失败:", e);
                this.checked = !verifyEnabled;
            }
        });
    }

    function addMessage(role, content, interrupted, verification, messageId, toolCalls) {
        const welcome = messagesContainer.querySelector(".welcome-message");
        if (welcome) welcome.remove();

        const row = document.createElement("div");
        row.className = `message-row ${role}`;

        const avatar = document.createElement("div");
        avatar.className = `avatar ${role}`;
        avatar.textContent = role === "user" ? "我" : "AI";

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.innerHTML = formatContent(content);

        if (interrupted) {
            const tag = document.createElement("span");
            tag.className = "interrupted-tag";
            tag.textContent = "已打断";
            bubble.appendChild(tag);
        }

        // 渲染验证结果
        if (verification) {
            renderVerification(bubble, verification);
        } else if (role === "assistant" && verifyEnabled && messageId) {
            // 添加手动验证按钮
            const verifyBtn = document.createElement("button");
            verifyBtn.className = "verify-btn";
            verifyBtn.textContent = "🔍 结果验证";
            verifyBtn.onclick = () => manualVerify(messageId, bubble);
            bubble.appendChild(verifyBtn);
        }

        // 为 AI 消息添加反馈按钮
        if (role === "assistant" && messageId) {
            const feedbackDiv = document.createElement("div");
            feedbackDiv.className = "feedback-buttons";
            feedbackDiv.innerHTML = `
                <button class="feedback-btn like-btn" data-message-id="${messageId}" data-feedback="like" title="有帮助">👍</button>
                <button class="feedback-btn dislike-btn" data-message-id="${messageId}" data-feedback="dislike" title="需要改进">👎</button>
            `;
            bubble.appendChild(feedbackDiv);

            // 绑定反馈事件
            feedbackDiv.querySelectorAll('.feedback-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    submitFeedback(this.dataset.messageId, this.dataset.feedback, this);
                });
            });
        }

        // 渲染历史消息中的工具调用
        if (toolCalls && toolCalls.length > 0) {
            renderToolCalls(bubble, toolCalls);
        }

        row.appendChild(avatar);
        row.appendChild(bubble);
        messagesContainer.appendChild(row);
        scrollToBottom();
        return bubble;
    }

    // 提交反馈
    async function submitFeedback(messageId, feedback, btn) {
        try {
            const res = await fetch(`/api/messages/${messageId}/feedback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ feedback })
            });
            
            if (res.ok) {
                // 高亮选中的按钮
                const parent = btn.parentElement;
                parent.querySelectorAll('.feedback-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                // 显示反馈成功提示
                const toast = document.createElement('div');
                toast.className = 'feedback-toast';
                toast.textContent = feedback === 'like' ? '感谢反馈！🎉' : '感谢反馈，我们会改进！';
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 2000);
            }
        } catch (e) {
            console.error("提交反馈失败:", e);
        }
    }

    // 配置 Marked.js
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
    });

    function formatContent(text) {
        // 使用 Marked.js 渲染 Markdown
        let html = marked.parse(text);
        
        // 为代码块添加语法高亮（简单的颜色标记）
        html = html.replace(/<pre><code>([\s\S]*?)<\/code><\/pre>/g, (match, code) => {
            return `<pre class="code-block"><code>${code}</code><button class="copy-btn" onclick="copyCode(this)">复制</button></pre>`;
        });
        
        // 为行内代码添加样式
        html = html.replace(/<code>([^<]+)<\/code>/g, '<code class="inline-code">$1</code>');
        
        return html;
    }

    // 工具调用可视化
    function renderToolCalls(bubble, toolCalls) {
        const container = document.createElement("div");
        container.className = "tool-calls-container";
        
        const header = document.createElement("div");
        header.className = "tool-calls-header";
        header.innerHTML = `<span class="tool-icon">🔧</span><span>工具调用 (${toolCalls.length})</span>`;
        
        const toggleBtn = document.createElement("button");
        toggleBtn.className = "toggle-tool-details";
        toggleBtn.textContent = "展开";
        toggleBtn.onclick = () => {
            const details = container.querySelector(".tool-calls-details");
            const isHidden = details.style.display === "none";
            details.style.display = isHidden ? "block" : "none";
            toggleBtn.textContent = isHidden ? "收起" : "展开";
        };
        header.appendChild(toggleBtn);
        
        const details = document.createElement("div");
        details.className = "tool-calls-details";
        details.style.display = "none";
        
        toolCalls.forEach((tc, idx) => {
            // 兼容 OpenAI 标准格式 {function:{name,arguments}} 和 旧格式 {name,arguments}
            const fn = tc.function || tc;
            const name = fn.name || "未知工具";
            const args = fn.arguments || "";
            const result = tc._result || tc.result || "";
            const call = document.createElement("div");
            call.className = "tool-call-item";
            call.innerHTML = `
                <div class="tool-call-name">${escapeHtml(name)}</div>
                <div class="tool-call-args"><pre>${escapeHtml(args)}</pre></div>
                ${result ? `<div class="tool-call-result"><pre>${escapeHtml(result)}</pre></div>` : ''}
            `;
            details.appendChild(call);
        });
        
        container.appendChild(header);
        container.appendChild(details);
        bubble.appendChild(container);
    }
    
    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }
    
    // 调试面板
    function showDebugPanel() {
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
        
        // 加载调试信息
        loadDebugInfo();
    }
    
    async function loadDebugInfo() {
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

            // 加载 Token 统计
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

    function formatTokenCount(n) {
        if (!n) return "0";
        if (n >= 10000) return (n / 10000).toFixed(1) + "万";
        if (n >= 1000) return (n / 1000).toFixed(1) + "k";
        return String(n);
    }
    
    // 添加调试按钮到页面
    function addDebugButton() {
        const btn = document.createElement("button");
        btn.className = "debug-toggle-btn";
        btn.textContent = "🐛";
        btn.title = "调试面板";
        btn.onclick = showDebugPanel;
        document.body.appendChild(btn);
    }
    
    // 复制代码功能
    window.copyCode = function(btn) {
        const code = btn.previousElementSibling.textContent;
        navigator.clipboard.writeText(code).then(() => {
            btn.textContent = '已复制';
            setTimeout(() => btn.textContent = '复制', 2000);
        });
    };

    function renderVerification(bubble, verification) {
        // 跳过（无需校验或异常）时，不展示任何验证卡片
        if (!verification || verification.status === "skipped") {
            return;
        }

        const container = document.createElement("div");
        container.className = "verification-result";

        if (verification.status === "failed" || verification.is_correct === false) {
            container.classList.add("verify-fail");
            const issuesHtml = verification.issues && verification.issues.length > 0
                ? `<ul class="verify-issues">${verification.issues.map(i => `<li>${i}</li>`).join("")}</ul>`
                : "";
            container.innerHTML = `
                <div class="verify-header">
                    <span>❌ 结果验证未通过</span>
                    <span class="verify-confidence">置信度: ${(verification.confidence * 100).toFixed(0)}%</span>
                </div>
                <div class="verify-explanation">${verification.explanation || ""}</div>
                ${issuesHtml}
            `;
        } else {
            // verified / 通过
            container.classList.add("verify-pass");
            container.innerHTML = `
                <div class="verify-header">
                    <span>✅ 结果验证通过</span>
                    <span class="verify-confidence">置信度: ${(verification.confidence * 100).toFixed(0)}%</span>
                </div>
                <div class="verify-explanation">${verification.explanation || "回答内容合理"}</div>
            `;
        }

        bubble.appendChild(container);
    }

    async function manualVerify(messageId, bubble) {
        const btn = bubble.querySelector(".verify-btn");
        if (btn) btn.remove();

        const indicator = document.createElement("div");
        indicator.className = "verifying-indicator";
        indicator.innerHTML = `<span class="dot-loader"></span><span>正在结果验证...</span>`;
        bubble.appendChild(indicator);

        try {
            const res = await fetch(`/api/conversations/${currentConvId}/messages/${messageId}/verify`, {
                method: "POST"
            });
            const verification = await res.json();
            indicator.remove();
            // skipped 状态（异常 / 无需校验）静默处理，不显示任何卡片
            renderVerification(bubble, verification);
        } catch (e) {
            // 网络错误等异常也静默处理
            indicator.remove();
        }
    }

    function createStreamingBubble() {
        const welcome = messagesContainer.querySelector(".welcome-message");
        if (welcome) welcome.remove();

        const row = document.createElement("div");
        row.className = "message-row assistant";

        const avatar = document.createElement("div");
        avatar.className = "avatar assistant";
        avatar.textContent = "AI";

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        
        // 显示"正在回复中..."占位文本
        const loadingText = document.createElement("span");
        loadingText.className = "loading-text";
        loadingText.textContent = "正在回复中...";
        bubble.appendChild(loadingText);

        row.appendChild(avatar);
        row.appendChild(bubble);
        messagesContainer.appendChild(row);
        scrollToBottom();
        return bubble;
    }

    async function loadMessages(convId) {
        // 如果之前有加入房间，先离开
        if (socket && currentConvId && currentConvId !== convId) {
            socket.emit('leave', { conversation_id: currentConvId });
        }
        
        currentConvId = convId;
        
        try {
            const res = await fetch(`/api/conversations/${convId}/messages`);
            const messages = await res.json();
            messagesContainer.innerHTML = "";
            if (messages.length === 0) {
                messagesContainer.innerHTML = `
                    <div class="welcome-message">
                        <p>你好！我是AI智能助手，有什么可以帮你的吗？</p>
                        <p class="hint">支持工具调用 · 流式输出 · 上下文压缩 · RAG知识检索</p>
                    </div>`;
            } else {
                // 过滤掉正在生成的消息（避免显示空白气泡）
                const filteredMessages = messages.filter(m => {
                    if (m.role === 'assistant' && m.status === 'generating') {
                        // 如果有内容，保留；如果为空，跳过
                        return m.content && m.content.trim().length > 0;
                    }
                    return true;
                });
                filteredMessages.forEach(m => addMessage(m.role, m.content, m.interrupted, m.verification, m.id, m.tool_calls));
            }
            
            // 加入新房间
            if (socket) {
                socket.emit('join', { conversation_id: convId });
            }
        } catch (e) {
            console.error("加载消息失败:", e);
        }
    }

    async function sendMessage() {
        const content = messageInput.value.trim();
        if (!content || isStreaming) return;

        if (!currentConvId) {
            const res = await fetch("/api/conversations", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });
            const conv = await res.json();
            currentConvId = conv.id;
            addConvToSidebar(conv.id, conv.title);
        }

        addMessage("user", content);
        messageInput.value = "";
        messageInput.style.height = "auto";
        isStreaming = true;
        sendBtn.disabled = true;
        interruptBtn.style.display = "inline-block";

        const bubble = createStreamingBubble();
        currentBubble = bubble;
        fullContent = "";
        toolCalls = [];

        // 先注册 message_created 监听器，再 emit chat_message
        // 避免事件在监听器注册前到达导致丢失
        socket.once('message_created', (data) => {
            currentMessageId = data.message_id;
            console.log('[WS] Message created:', currentMessageId);
        });

        // 通过 WebSocket 发送消息
        socket.emit('chat_message', {
            conversation_id: currentConvId,
            content: content,
            model: modelSelector.value,
            image_urls: []
        });
        
        // 备用方案：如果 3 秒内没收到 message_created，轮询获取最新的 assistant 消息 ID
        setTimeout(() => {
            if (!currentMessageId && currentBubble) {
                console.log('[WS] message_created 超时，轮询获取消息 ID');
                fetch(`/api/conversations/${currentConvId}/messages`)
                    .then(res => res.json())
                    .then(messages => {
                        const lastAssistant = messages.filter(m => m.role === 'assistant').pop();
                        if (lastAssistant) {
                            currentMessageId = lastAssistant.id;
                            console.log('[WS] 轮询获取到 message_id:', currentMessageId);
                        }
                    })
                    .catch(err => console.error('[WS] 轮询失败:', err));
            }
        }, 3000);
    }

    function createCursor() {
        const c = document.createElement("span");
        c.className = "typing-cursor";
        return c;
    }

    async function interrupt() {
        if (!currentConvId || !isStreaming || !currentMessageId) return;
        try {
            // 通过 WebSocket 发送中断请求
            socket.emit('stop_generation', { message_id: currentMessageId });
        } catch (e) {
            console.error("打断失败:", e);
        }
    }

    function addConvToSidebar(id, title) {
        const item = document.createElement("div");
        item.className = "conversation-item active";
        item.dataset.id = id;
        item.innerHTML = `<span class="conv-title">${escapeHtml(title)}</span><button class="rename-btn" data-id="${id}" title="重命名"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path></svg></button><button class="delete-btn" data-id="${id}">×</button>`;

        document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
        convList.prepend(item);
        bindConvEvents(item);
    }

    function bindConvEvents(item) {
        item.addEventListener("click", function (e) {
            if (e.target.classList.contains("delete-btn")) return;
            if (e.target.classList.contains("rename-btn")) return;
            if (e.target.classList.contains("rename-input")) return; // 重命名输入框内点击不切换
            document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            currentConvId = item.dataset.id;
            loadMessages(currentConvId);
        });

        // 点击编辑按钮进入重命名
        const titleEl = item.querySelector(".conv-title");
        const renameBtn = item.querySelector(".rename-btn");
        if (renameBtn && titleEl) {
            renameBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                startRename(item, titleEl);
            });
        }

        const delBtn = item.querySelector(".delete-btn");
        if (delBtn) {
            delBtn.addEventListener("click", async function (e) {
                e.stopPropagation();
                const id = this.dataset.id;
                await fetch(`/api/conversations/${id}`, { method: "DELETE" });
                item.remove();
                if (currentConvId === id) {
                    const first = convList.querySelector(".conversation-item");
                    if (first) {
                        first.click();
                    } else {
                        currentConvId = null;
                        messagesContainer.innerHTML = `
                            <div class="welcome-message">
                                <p>你好！我是AI智能助手，有什么可以帮你的吗？</p>
                                <p class="hint">支持工具调用 · 流式输出 · 上下文压缩 · RAG知识检索</p>
                            </div>`;
                    }
                }
            });
        }
    }

    // 进入重命名模式：把标题换成输入框
    function startRename(item, titleEl) {
        if (item.querySelector(".rename-input")) return; // 已在重命名中

        const oldTitle = titleEl.textContent;
        const input = document.createElement("input");
        input.type = "text";
        input.className = "rename-input";
        input.value = oldTitle;
        input.maxLength = 50;

        titleEl.style.display = "none";
        item.insertBefore(input, titleEl.nextSibling);

        input.focus();
        input.select();

        let finished = false;
        const finish = async (save) => {
            if (finished) return;
            finished = true;

            const newTitle = input.value.trim();
            input.remove();
            titleEl.style.display = "";

            if (save && newTitle && newTitle !== oldTitle) {
                await renameConversation(item.dataset.id, newTitle, titleEl);
            }
        };

        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); finish(true); }
            else if (e.key === "Escape") { finish(false); }
        });
        input.addEventListener("blur", function () { finish(true); });
    }

    // 调用后端重命名接口
    async function renameConversation(id, title, titleEl) {
        try {
            const res = await fetch(`/api/conversations/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title }),
            });
            const data = await res.json();
            if (data.error) {
                alert(data.error);
                return;
            }
            titleEl.textContent = data.title;
        } catch (e) {
            console.error("重命名失败:", e);
        }
    }

    document.querySelectorAll(".conversation-item").forEach(bindConvEvents);

    // ========== 聊天页专用功能 ==========
    if (isChatPage) {
        newChatBtn.addEventListener("click", async function () {
            const title = await promptForTitle();
            if (title === null) return; // 用户取消

            const res = await fetch("/api/conversations", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(title ? { title } : {}),
            });
            const conv = await res.json();
            addConvToSidebar(conv.id, conv.title);
            currentConvId = conv.id;
            messagesContainer.innerHTML = `
                <div class="welcome-message">
                    <p>你好！我是AI智能助手，有什么可以帮你的吗？</p>
                    <p class="hint">支持工具调用 · 流式输出 · 上下文压缩 · RAG知识检索</p>
                </div>`;
        });

        // 弹窗让用户输入新对话标题；返回 null 表示取消，空字符串表示用默认
        function promptForTitle() {
            return new Promise((resolve) => {
                const overlay = document.createElement("div");
                overlay.className = "modal-overlay";

                const box = document.createElement("div");
                box.className = "modal-box";
                box.innerHTML = `
                    <div class="modal-title">新建对话</div>
                    <input type="text" class="modal-input" placeholder="输入对话标题（留空则自动生成）" maxlength="50" />
                    <div class="modal-actions">
                        <button class="modal-btn modal-cancel">取消</button>
                        <button class="modal-btn modal-confirm">创建</button>
                    </div>
                `;
                overlay.appendChild(box);
                document.body.appendChild(overlay);

                const input = box.querySelector(".modal-input");
                const cancelBtn = box.querySelector(".modal-cancel");
                const confirmBtn = box.querySelector(".modal-confirm");

                input.focus();

                const close = (val) => {
                    overlay.remove();
                    resolve(val);
                };

                cancelBtn.addEventListener("click", () => close(null));
                overlay.addEventListener("click", (e) => { if (e.target === overlay) close(null); });
                input.addEventListener("keydown", (e) => {
                    if (e.key === "Enter") close(input.value);
                    else if (e.key === "Escape") close(null);
                });
                confirmBtn.addEventListener("click", () => close(input.value));
            });
        }

        shareBtn.addEventListener("click", async function () {
            if (!currentConvId) {
                alert("请先选择一个对话");
                return;
            }
            try {
                const res = await fetch(`/api/conversations/${currentConvId}/share`, { method: "POST" });
                const data = await res.json();
                if (data.error) {
                    alert(data.error);
                    return;
                }
                const shareUrl = `${window.location.origin}/share/${data.share_token}`;
                const toast = document.createElement("div");
                toast.className = "share-toast";
                toast.innerHTML = `
                    <div class="share-toast-content">
                        <span class="share-toast-icon">🔗</span>
                        <div class="share-toast-text">
                            <div class="share-toast-title">分享链接已生成</div>
                            <div class="share-toast-url">${shareUrl}</div>
                        </div>
                    </div>
                `;
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 5000);
                navigator.clipboard.writeText(shareUrl).catch(() => {});
            } catch (e) {
                console.error("分享失败:", e);
                alert("分享失败，请稍后重试");
            }
        });

        exportBtn.addEventListener("click", function () {
            if (!currentConvId) {
                alert("请先选择一个对话");
                return;
            }
            const existing = document.querySelector(".export-menu");
            if (existing) {
                existing.remove();
                return;
            }
            const menu = document.createElement("div");
            menu.className = "export-menu";
            menu.innerHTML = `
                <div class="export-menu-title">导出对话</div>
                <button class="export-option" data-format="markdown">
                    <span class="export-icon">📝</span>
                    <span>Markdown (.md)</span>
                </button>
                <button class="export-option" data-format="json">
                    <span class="export-icon">📊</span>
                    <span>JSON (.json)</span>
                </button>
                <button class="export-option" data-format="txt">
                    <span class="export-icon">📄</span>
                    <span>纯文本 (.txt)</span>
                </button>
            `;
            document.body.appendChild(menu);
            menu.querySelectorAll(".export-option").forEach(btn => {
                btn.addEventListener("click", async function () {
                    const format = this.dataset.format;
                    try {
                        const res = await fetch(`/api/conversations/${currentConvId}/export?format=${format}`);
                        if (!res.ok) throw new Error("导出失败");
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `conversation_${currentConvId}.${format === "markdown" ? "md" : format}`;
                        a.click();
                        URL.revokeObjectURL(url);
                        menu.remove();
                    } catch (e) {
                        console.error("导出失败:", e);
                        alert("导出失败，请稍后重试");
                    }
                });
            });
            setTimeout(() => {
                document.addEventListener("click", function closeMenu(e) {
                    if (!menu.contains(e.target) && e.target !== exportBtn) {
                        menu.remove();
                        document.removeEventListener("click", closeMenu);
                    }
                });
            }, 0);
        });

        sendBtn.addEventListener("click", sendMessage);
        interruptBtn.addEventListener("click", interrupt);

        messageInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        messageInput.addEventListener("input", function () {
            this.style.height = "auto";
            this.style.height = Math.min(this.scrollHeight, 120) + "px";
        });
    }

    async function loadDocuments() {
        try {
            const res = await fetch("/api/documents");
            const docs = await res.json();
            renderDocuments(docs);
        } catch (e) {
            console.error("加载文档列表失败:", e);
        }
    }

    function renderDocuments(docs) {
        if (!docs || docs.length === 0) {
            kbDocList.innerHTML = '<div class="kb-empty">暂无文档，点击 + 上传</div>';
            return;
        }
        kbDocList.innerHTML = "";
        docs.forEach(doc => {
            const item = document.createElement("div");
            item.className = "kb-doc-item";
            const sizeStr = doc.file_size > 1024 * 1024
                ? (doc.file_size / 1024 / 1024).toFixed(1) + " MB"
                : (doc.file_size / 1024).toFixed(1) + " KB";
            item.innerHTML = `
                <div class="kb-doc-info">
                    <span class="kb-doc-name" title="${doc.filename}">${doc.filename}</span>
                    <span class="kb-doc-meta">${doc.chunk_count} 块 · ${sizeStr}</span>
                </div>
                <button class="kb-doc-delete" data-id="${doc.id}">×</button>
            `;
            const delBtn = item.querySelector(".kb-doc-delete");
            delBtn.addEventListener("click", async () => {
                await fetch(`/api/documents/${doc.id}`, { method: "DELETE" });
                loadDocuments();
            });
            kbDocList.appendChild(item);
        });
    }

    if (fileUpload && kbDocList) {
        fileUpload.addEventListener("change", async function () {
            const file = this.files[0];
            if (!file) return;
            this.value = "";

            kbDocList.innerHTML = `
                <div class="kb-uploading">
                    正在处理 ${file.name}...
                    <div class="upload-progress"><div class="upload-progress-bar"></div></div>
                </div>
            `;

            const formData = new FormData();
            formData.append("file", file);

            try {
                const res = await fetch("/api/documents/upload", {
                    method: "POST",
                    body: formData,
                });
                const data = await res.json();
                if (!res.ok) {
                    alert(data.error || "上传失败");
                }
                loadDocuments();
            } catch (e) {
                alert("上传失败: " + e.message);
                loadDocuments();
            }
        });
    }

    // ==================== 代码库索引管理 ====================
    const addRepoBtn = document.getElementById("add-repo-btn");
    const addRepoModal = document.getElementById("add-repo-modal");
    const searchTestModal = document.getElementById("search-test-modal");
    const confirmModal = document.getElementById("confirm-modal");
    const confirmAddRepoBtn = document.getElementById("confirm-add-repo");
    const runSearchBtn = document.getElementById("run-search-btn");

    let currentRepoForSearch = null;
    let progressPollingIntervals = {}; // 存储每个仓库的进度轮询定时器

    // Toast 提示函数
    function showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('toast-hiding');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // 确认弹窗函数
    function showConfirm(title, message) {
        return new Promise((resolve) => {
            const confirmTitle = document.getElementById('confirm-title');
            const confirmMessage = document.getElementById('confirm-message');
            const confirmOk = document.getElementById('confirm-ok');
            const confirmCancel = document.getElementById('confirm-cancel');
            
            confirmTitle.textContent = title;
            confirmMessage.textContent = message;
            confirmModal.style.display = 'flex';
            
            const handleOk = () => {
                confirmModal.style.display = 'none';
                confirmOk.removeEventListener('click', handleOk);
                confirmCancel.removeEventListener('click', handleCancel);
                resolve(true);
            };
            
            const handleCancel = () => {
                confirmModal.style.display = 'none';
                confirmOk.removeEventListener('click', handleOk);
                confirmCancel.removeEventListener('click', handleCancel);
                resolve(false);
            };
            
            confirmOk.addEventListener('click', handleOk);
            confirmCancel.addEventListener('click', handleCancel);
        });
    }

    // 索引模式选择弹窗函数
    function showIndexModeConfirm(isPending) {
        return new Promise((resolve) => {
            const indexModeModal = document.getElementById('index-mode-modal');
            const indexModeOk = document.getElementById('index-mode-ok');
            const indexModeCancel = document.getElementById('index-mode-cancel');
            
            // 如果是待索引状态，默认选中增量；否则默认选中全量
            const defaultMode = isPending ? 'incremental' : 'full';
            document.querySelector(`input[name="index-mode"][value="${defaultMode}"]`).checked = true;
            
            indexModeModal.style.display = 'flex';
            
            const handleOk = () => {
                const selectedMode = document.querySelector('input[name="index-mode"]:checked').value;
                indexModeModal.style.display = 'none';
                indexModeOk.removeEventListener('click', handleOk);
                indexModeCancel.removeEventListener('click', handleCancel);
                
                // 全量模式时 reindex=true，增量模式时 reindex=false
                resolve({
                    mode: selectedMode,
                    reindex: selectedMode === 'full'
                });
            };
            
            const handleCancel = () => {
                indexModeModal.style.display = 'none';
                indexModeOk.removeEventListener('click', handleOk);
                indexModeCancel.removeEventListener('click', handleCancel);
                resolve(null);
            };
            
            indexModeOk.addEventListener('click', handleOk);
            indexModeCancel.addEventListener('click', handleCancel);
        });
    }

    // 加载代码库列表
    async function loadCodeRepos() {
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
                
                // 绑定事件
                bindCodeRepoEvents();
                
                // 对正在索引的仓库启动进度轮询
                data.repos.forEach(repo => {
                    if (repo.status === 'indexing') {
                        startProgressPolling(repo.id);
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

    function formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleString('zh-CN', { 
            month: '2-digit', 
            day: '2-digit', 
            hour: '2-digit', 
            minute: '2-digit' 
        });
    }

    // 进度轮询
    function startProgressPolling(repoId) {
        if (progressPollingIntervals[repoId]) return; // 已经在轮询
        
        progressPollingIntervals[repoId] = setInterval(async () => {
            try {
                const res = await fetch(`/api/code-repos/${repoId}/progress`);
                const data = await res.json();
                
                if (data.status === 'success') {
                    // 更新进度条
                    const repoItem = document.querySelector(`.code-repo-item[data-id="${repoId}"]`);
                    if (repoItem) {
                        const progressFill = repoItem.querySelector('.progress-fill');
                        const progressText = repoItem.querySelector('.progress-text');
                        
                        if (progressFill) {
                            const progressPercent = data.progress || 0;
                            progressFill.style.width = `${progressPercent}%`;
                            // 添加强制重绘
                            progressFill.offsetHeight;
                        }
                        if (progressText) {
                            const progressPercent = data.progress || 0;
                            const message = data.message || '处理中...';
                            progressText.textContent = `${message} (${progressPercent}%)`;
                        }
                    }
                    
                    // 如果索引完成或失败，停止轮询并刷新列表
                    if (data.repo_status !== 'indexing') {
                        stopProgressPolling(repoId);
                        loadCodeRepos();
                        
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
        }, 3000); // 每 3 秒查询一次进度
    }

    function stopProgressPolling(repoId) {
        if (progressPollingIntervals[repoId]) {
            clearInterval(progressPollingIntervals[repoId]);
            delete progressPollingIntervals[repoId];
        }
    }

    function bindCodeRepoEvents() {
        // 测试搜索按钮
        document.querySelectorAll('.search-test-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const repoId = btn.dataset.id;
                currentRepoForSearch = repoId;
                document.getElementById('search-query-input').value = '';
                document.getElementById('search-results').innerHTML = '';
                searchTestModal.style.display = 'flex';
            });
        });

        // 刷新索引按钮
        document.querySelectorAll('.refresh-index-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const repoId = btn.dataset.id;
                const repoItem = btn.closest('.code-repo-item');
                const statusBadge = repoItem.querySelector('.repo-status-badge');
                const isPending = statusBadge && statusBadge.classList.contains('status-pending');
                
                // 显示索引模式选择弹窗
                const result = await showIndexModeConfirm(isPending);
                if (result) {
                    await triggerIndex(repoId, result.mode, result.reindex);
                }
            });
        });

        // 删除按钮
        document.querySelectorAll('.delete-repo-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const repoId = btn.dataset.id;
                const confirmed = await showConfirm(
                    '删除代码库',
                    '确定要删除此代码库配置及其索引吗？此操作不可恢复。'
                );
                if (confirmed) {
                    await deleteRepo(repoId);
                }
            });
        });

        // 取消索引按钮
        document.querySelectorAll('.cancel-index-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const repoId = btn.dataset.id;
                const confirmed = await showConfirm(
                    '取消索引',
                    '确定要取消正在进行的索引任务吗？'
                );
                if (confirmed) {
                    await cancelIndex(repoId);
                }
            });
        });
    }

    // 添加仓库按钮
    if (addRepoBtn) {
        addRepoBtn.addEventListener('click', () => {
            addRepoModal.style.display = 'flex';
        });
    }

    // 关闭模态框
    document.querySelectorAll('.modal-close, .modal-cancel').forEach(btn => {
        btn.addEventListener('click', () => {
            addRepoModal.style.display = 'none';
            searchTestModal.style.display = 'none';
        });
    });

    // 确认添加仓库
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
                    loadCodeRepos(); // 只刷新列表，不自动索引
                } else {
                    showToast(data.message || '添加失败', 'error');
                }
            } catch (e) {
                showToast('添加失败: ' + e.message, 'error');
            }
        });
    }

    // 触发索引
    async function triggerIndex(repoId, mode = 'full', reindex = true) {
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
                loadCodeRepos(); // 刷新列表以显示进度条
            } else {
                showToast(data.message || '索引失败', 'error');
                loadCodeRepos();
            }
        } catch (e) {
            showToast('索引失败: ' + e.message, 'error');
            loadCodeRepos();
        }
    }

    // 删除仓库
    async function deleteRepo(repoId) {
        try {
            const res = await fetch(`/api/code-repos/${repoId}`, {
                method: 'DELETE'
            });
            const data = await res.json();

            if (data.status === 'success') {
                showToast('仓库已删除', 'success');
                loadCodeRepos();
            } else {
                showToast(data.message || '删除失败', 'error');
            }
        } catch (e) {
            showToast('删除失败: ' + e.message, 'error');
        }
    }

    // 取消索引
    async function cancelIndex(repoId) {
        try {
            const res = await fetch(`/api/code-repos/${repoId}/cancel`, {
                method: 'POST'
            });
            const data = await res.json();

            if (data.status === 'success') {
                showToast('已取消索引任务', 'success');
                stopProgressPolling(repoId);
                loadCodeRepos();
            } else {
                showToast(data.message || '取消失败', 'error');
            }
        } catch (e) {
            showToast('取消失败: ' + e.message, 'error');
        }
    }

    // 运行搜索测试
    if (runSearchBtn) {
        runSearchBtn.addEventListener('click', async () => {
            const query = document.getElementById('search-query-input').value.trim();
            const topK = parseInt(document.getElementById('search-top-k-input').value) || 5;
            const resultsDiv = document.getElementById('search-results');

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

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 加载知识库文档数量（用于主页导航徽章）
    async function loadKnowledgeCount() {
        try {
            const response = await fetch('/api/documents');
            const data = await response.json();
            // API 直接返回数组
            const count = Array.isArray(data) ? data.length : (data.documents ? data.documents.length : 0);
            const badge = document.getElementById('knowledge-count');
            if (badge) {
                badge.textContent = count;
            }
        } catch (error) {
            console.error('加载知识库数量失败:', error);
        }
    }

    // 加载代码库数量（用于主页导航徽章）
    async function loadCodeReposCount() {
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

    // 初始加载（按页面类型）
    if (isCodeReposPage && codeRepoList) {
        loadCodeRepos();
    }
    if (isChatPage) {
        loadKnowledgeCount();
        loadCodeReposCount();
    }

    // 暴露给其他页面使用
    window.loadCodeRepos = loadCodeRepos;
    window.loadDocuments = loadDocuments;
    // 暴露到全局作用域，供独立页面调用
    window.loadCodeRepos = loadCodeRepos;
    window.showToast = showToast;
    window.showConfirm = showConfirm;
    window.showIndexModeConfirm = showIndexModeConfirm;
    window.triggerIndex = triggerIndex;
    window.deleteRepo = deleteRepo;
    window.cancelIndex = cancelIndex;

})();
