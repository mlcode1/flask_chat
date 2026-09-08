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

    let currentConvId = null;
    let isStreaming = false;
    let currentAbortController = null;
    let verifyEnabled = false;

    loadModels();
    loadDocuments();
    loadVerifyConfig();

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

    function addMessage(role, content, interrupted, verification, messageId) {
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
            verifyBtn.textContent = "🔍 验证此回答";
            verifyBtn.onclick = () => manualVerify(messageId, bubble);
            bubble.appendChild(verifyBtn);
        }

        row.appendChild(avatar);
        row.appendChild(bubble);
        messagesContainer.appendChild(row);
        scrollToBottom();
        return bubble;
    }

    function formatContent(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\n/g, "<br>")
            .replace(/---/g, "<hr>")
            .replace(/\*(.*?)\*/g, "<em>$1</em>");
    }

    function renderVerification(bubble, verification) {
        const container = document.createElement("div");
        container.className = "verification-result";

        if (verification.error) {
            container.classList.add("verify-error");
            container.innerHTML = `
                <div class="verify-header">
                    <span>⚠️ 验证失败</span>
                </div>
                <div class="verify-explanation">${verification.error}</div>
            `;
        } else if (verification.is_correct === true) {
            container.classList.add("verify-pass");
            container.innerHTML = `
                <div class="verify-header">
                    <span>✅ 验证通过</span>
                    <span class="verify-confidence">置信度: ${(verification.confidence * 100).toFixed(0)}%</span>
                </div>
                <div class="verify-explanation">${verification.explanation}</div>
            `;
        } else {
            container.classList.add("verify-fail");
            const issuesHtml = verification.issues && verification.issues.length > 0
                ? `<ul class="verify-issues">${verification.issues.map(i => `<li>${i}</li>`).join("")}</ul>`
                : "";
            container.innerHTML = `
                <div class="verify-header">
                    <span>❌ 验证未通过</span>
                    <span class="verify-confidence">置信度: ${(verification.confidence * 100).toFixed(0)}%</span>
                </div>
                <div class="verify-explanation">${verification.explanation}</div>
                ${issuesHtml}
            `;
        }

        bubble.appendChild(container);
    }

    async function manualVerify(messageId, bubble) {
        const btn = bubble.querySelector(".verify-btn");
        if (btn) btn.remove();

        const indicator = document.createElement("div");
        indicator.className = "verifying-indicator";
        indicator.innerHTML = `<span class="dot-loader"></span><span>正在验证...</span>`;
        bubble.appendChild(indicator);

        try {
            const res = await fetch(`/api/conversations/${currentConvId}/messages/${messageId}/verify`, {
                method: "POST"
            });
            const verification = await res.json();
            indicator.remove();
            renderVerification(bubble, verification);
        } catch (e) {
            indicator.remove();
            const errorDiv = document.createElement("div");
            errorDiv.className = "verification-result verify-error";
            errorDiv.innerHTML = `<div class="verify-header"><span>⚠️ 验证失败</span></div><div class="verify-explanation">${e.message}</div>`;
            bubble.appendChild(errorDiv);
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
            messages.forEach(m => addMessage(m.role, m.content, m.interrupted, m.verification, m.id));
        } catch (e) {
            console.error("加载消息失败:", e);
        }
    }

    async function sendMessage() {
        const content = messageInput.value.trim();
        if (!content || isStreaming) return;

        if (!currentConvId) {
            const res = await fetch("/api/conversations", { method: "POST" });
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
                            indicator.innerHTML = `<span class="dot-loader"></span><span>正在验证回答...</span>`;
                            bubble.appendChild(indicator);
                            scrollToBottom();
                        }

                        if (data.verified) {
                            // 验证完成，移除指示器并显示结果
                            const indicator = document.getElementById("current-verifying");
                            if (indicator) indicator.remove();
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

            // 如果验证开关打开且消息未被中断，添加手动验证按钮
            if (verifyEnabled && currentMessageId && !bubble.querySelector(".verification-result") && !bubble.querySelector(".verifying-indicator")) {
                const verifyBtn = document.createElement("button");
                verifyBtn.className = "verify-btn";
                verifyBtn.textContent = "🔍 验证此回答";
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
        item.innerHTML = `<span class="conv-title">${title}</span><button class="delete-btn" data-id="${id}">×</button>`;

        document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
        convList.prepend(item);
        bindConvEvents(item);
    }

    function bindConvEvents(item) {
        item.addEventListener("click", function (e) {
            if (e.target.classList.contains("delete-btn")) return;
            document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            currentConvId = item.dataset.id;
            loadMessages(currentConvId);
        });

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

    document.querySelectorAll(".conversation-item").forEach(bindConvEvents);

    newChatBtn.addEventListener("click", async function () {
        const res = await fetch("/api/conversations", { method: "POST" });
        const conv = await res.json();
        addConvToSidebar(conv.id, conv.title);
        currentConvId = conv.id;
        messagesContainer.innerHTML = `
            <div class="welcome-message">
                <p>你好！我是AI智能助手，有什么可以帮你的吗？</p>
                <p class="hint">支持工具调用 · 流式输出 · 上下文压缩 · RAG知识检索</p>
            </div>`;
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
