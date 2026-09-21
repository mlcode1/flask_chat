// conversation.js - 对话管理

import { escapeHtml } from './utils.js';

export function addConvToSidebar(convList, id, title, callbacks = {}) {
    const item = document.createElement("div");
    item.className = "conversation-item active";
    item.dataset.id = id;
    item.innerHTML = `<span class="conv-title">${escapeHtml(title)}</span><button class="rename-btn" data-id="${id}" title="重命名"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path></svg></button><button class="delete-btn" data-id="${id}">×</button>`;

    document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
    convList.prepend(item);
    bindConvEvents(item, callbacks);
}

export function bindConvEvents(item, callbacks = {}) {
    item.addEventListener("click", function (e) {
        if (e.target.classList.contains("delete-btn")) return;
        if (e.target.classList.contains("rename-btn")) return;
        if (e.target.classList.contains("rename-input")) return;
        
        document.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("active"));
        item.classList.add("active");
        
        const convId = item.dataset.id;
        if (callbacks.onConvSelect) {
            callbacks.onConvSelect(convId);
        }
    });

    const titleEl = item.querySelector(".conv-title");
    const renameBtn = item.querySelector(".rename-btn");
    if (renameBtn && titleEl) {
        renameBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            startRename(item, titleEl, callbacks);
        });
    }

    const delBtn = item.querySelector(".delete-btn");
    if (delBtn) {
        delBtn.addEventListener("click", async function (e) {
            e.stopPropagation();
            const id = this.dataset.id;
            await fetch(`/api/conversations/${id}`, { method: "DELETE" });
            item.remove();
            
            if (callbacks.onConvDelete) {
                callbacks.onConvDelete(id);
            }
        });
    }
}

function startRename(item, titleEl, callbacks = {}) {
    if (item.querySelector(".rename-input")) return;

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
            await renameConversation(item.dataset.id, newTitle, titleEl, callbacks);
        }
    };

    input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); finish(true); }
        else if (e.key === "Escape") { finish(false); }
    });
    input.addEventListener("blur", function () { finish(true); });
}

async function renameConversation(id, title, titleEl, callbacks = {}) {
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

export async function loadMessages(convId, messagesContainer, socket, callbacks = {}) {
    if (socket && socket.currentConvId && socket.currentConvId !== convId) {
        socket.leave(socket.currentConvId);
    }
    
    socket.currentConvId = convId;
    
    try {
        const res = await fetch(`/api/conversations/${convId}/messages`);
        const data = await res.json();
        const messages = data.messages || data;
        
        messagesContainer.innerHTML = "";
        
        if (messages.length === 0) {
            messagesContainer.innerHTML = `
                <div class="welcome-message">
                    <p>你好！我是AI智能助手，有什么可以帮你的吗？</p>
                    <p class="hint">支持工具调用 · 流式输出 · 上下文压缩 · RAG知识检索</p>
                </div>`;
        } else {
            const filteredMessages = messages.filter(m => {
                if (m.role === 'assistant' && m.status === 'generating') {
                    return m.content && m.content.trim().length > 0;
                }
                return true;
            });
            
            filteredMessages.forEach(m => {
                if (callbacks.onMessageRender) {
                    callbacks.onMessageRender(m);
                }
            });
        }
        
        if (socket) {
            socket.join(convId);
        }
    } catch (e) {
        console.error("加载消息失败:", e);
    }
}

export function promptForTitle() {
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
