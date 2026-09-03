(function () {
    const messagesContainer = document.getElementById("messages-container");
    const messageInput = document.getElementById("message-input");
    const sendBtn = document.getElementById("send-btn");
    const interruptBtn = document.getElementById("interrupt-btn");
    const newChatBtn = document.getElementById("new-chat-btn");
    const convList = document.getElementById("conversation-list");
    const modelSelector = document.getElementById("model-selector");

    let currentConvId = null;
    let isStreaming = false;
    let currentAbortController = null;

    loadModels();

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

    function addMessage(role, content, interrupted) {
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
                        <p class="hint">支持工具调用 · 流式输出 · 上下文压缩</p>
                    </div>`;
                return;
            }
            messages.forEach(m => addMessage(m.role, m.content, m.interrupted));
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
                                <p class="hint">支持工具调用 · 流式输出 · 上下文压缩</p>
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
                <p class="hint">支持工具调用 · 流式输出 · 上下文压缩</p>
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
})();
