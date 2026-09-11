(function () {
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
    const shareBtn = document.getElementById("share-btn");
    const exportBtn = document.getElementById("export-btn");

    let currentConvId = null;
    let isStreaming = false;
    let currentAbortController = null;
    let verifyEnabled = false;

    loadModels();
    loadDocuments();
    loadVerifyConfig();
    addDebugButton();

    const activeConvs = document.querySelectorAll(".conversation-item");
    if (activeConvs.length > 0) {
        currentConvId = activeConvs[0].dataset.id;
        loadMessages(currentConvId);
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
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
        try {
            const res = await fetch("/api/config/verify");
            const data = await res.json();
            verifyEnabled = data.enabled;
            verifySwitch.checked = verifyEnabled;
        } catch (e) {
            console.error("加载验证配置失败:", e);
        }
    }

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

        const cursor = document.createElement("span");
        cursor.className = "typing-cursor";

        bubble.appendChild(cursor);
        row.appendChild(avatar);
        row.appendChild(bubble);
        messagesContainer.appendChild(row);
        scrollToBottom();
        return bubble;
    }

    async function loadMessages(convId) {
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
                return;
            }
            messages.forEach(m => addMessage(m.role, m.content, m.interrupted, m.verification, m.id, m.tool_calls));
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
        let fullContent = "";
        let currentMessageId = null;
        let verificationStatus = null; // "verified" | "failed" | "skipped" | null

        currentAbortController = new AbortController();

        try {
            const res = await fetch(`/api/conversations/${currentConvId}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content, model: modelSelector.value }),
                signal: currentAbortController.signal,
            });

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.token) {
                            fullContent += data.token;
                            const cursor = bubble.querySelector(".typing-cursor");
                            if (cursor) cursor.remove();
                            bubble.innerHTML = formatContent(fullContent);
                            bubble.appendChild(createCursor());
                            scrollToBottom();
                        }

                        if (data.tool_calls) {
                            // 显示工具调用信息
                            renderToolCalls(bubble, data.tool_calls);
                            scrollToBottom();
                        }

                        if (data.done) {
                            const cursor = bubble.querySelector(".typing-cursor");
                            if (cursor) cursor.remove();
                            bubble.innerHTML = formatContent(data.content);
                            // 保存消息ID用于后续验证
                            currentMessageId = data.message_id;
                        }

                        if (data.verifying) {
                            // 显示验证中指示器
                            const indicator = document.createElement("div");
                            indicator.className = "verifying-indicator";
                            indicator.id = "current-verifying";
                            indicator.innerHTML = `<span class="dot-loader"></span><span>正在进行结果验证...</span>`;
                            bubble.appendChild(indicator);
                            scrollToBottom();
                        }

                        if (data.verified) {
                            // 验证完成，移除指示器并显示结果
                            const indicator = document.getElementById("current-verifying");
                            if (indicator) indicator.remove();
                            verificationStatus = data.verified.status || "skipped";
                            renderVerification(bubble, data.verified);
                            scrollToBottom();
                        }

                        if (data.error) {
                            const cursor = bubble.querySelector(".typing-cursor");
                            if (cursor) cursor.remove();
                            bubble.innerHTML = `<span style="color:var(--danger)">错误: ${data.error}</span>`;
                        }
                    } catch (e) {
                        // skip malformed lines
                    }
                }
            }
        } catch (e) {
            if (e.name !== "AbortError") {
                const cursor = bubble.querySelector(".typing-cursor");
                if (cursor) cursor.remove();
                bubble.innerHTML = `<span style="color:var(--danger)">请求失败: ${e.message}</span>`;
            }
        } finally {
            isStreaming = false;
            sendBtn.disabled = false;
            interruptBtn.style.display = "none";
            currentAbortController = null;

            // 验证开关打开 + 没有验证结果（verified/failed/skipped 都算）→ 显示手动验证按钮
            if (verifyEnabled && currentMessageId && !verificationStatus && !bubble.querySelector(".verifying-indicator")) {
                const verifyBtn = document.createElement("button");
                verifyBtn.className = "verify-btn";
                verifyBtn.textContent = "🔍 结果验证";
                verifyBtn.onclick = () => manualVerify(currentMessageId, bubble);
                bubble.appendChild(verifyBtn);
            }
        }
    }

    function createCursor() {
        const c = document.createElement("span");
        c.className = "typing-cursor";
        return c;
    }

    async function interrupt() {
        if (!currentConvId || !isStreaming) return;
        try {
            await fetch(`/api/conversations/${currentConvId}/interrupt`, { method: "POST" });
        } catch (e) {
            console.error("打断失败:", e);
        }
        if (currentAbortController) {
            currentAbortController.abort();
        }
    }

    function addConvToSidebar(id, title) {
        const item = document.createElement("div");
        item.className = "conversation-item active";
        item.dataset.id = id;
        item.innerHTML = `<span class="conv-title" title="双击重命名">${escapeHtml(title)}</span><button class="delete-btn" data-id="${id}">×</button>`;

        document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
        convList.prepend(item);
        bindConvEvents(item);
    }

    function bindConvEvents(item) {
        item.addEventListener("click", function (e) {
            if (e.target.classList.contains("delete-btn")) return;
            if (e.target.classList.contains("conv-title") || e.target.classList.contains("rename-input")) return;
            document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            currentConvId = item.dataset.id;
            loadMessages(currentConvId);
        });

        // 双击标题重命名
        const titleEl = item.querySelector(".conv-title");
        if (titleEl) {
            titleEl.addEventListener("dblclick", function (e) {
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
})();
