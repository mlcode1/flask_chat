// message.js - 消息渲染和格式化

import { escapeHtml } from './utils.js';

// 配置 Marked.js
if (typeof marked !== 'undefined') {
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
    });
}

export function formatContent(text) {
    if (typeof marked === 'undefined') {
        return escapeHtml(text);
    }
    
    let html = marked.parse(text);
    
    // 为代码块添加复制按钮
    html = html.replace(/<pre><code>([\s\S]*?)<\/code><\/pre>/g, (match, code) => {
        return `<pre class="code-block"><code>${code}</code><button class="copy-btn" onclick="copyCode(this)">复制</button></pre>`;
    });
    
    // 为行内代码添加样式
    html = html.replace(/<code>([^<]+)<\/code>/g, '<code class="inline-code">$1</code>');
    
    return html;
}

export function createCursor() {
    const c = document.createElement("span");
    c.className = "typing-cursor";
    return c;
}

export function renderToolCalls(bubble, toolCalls) {
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

export function renderVerification(bubble, verification) {
    if (!verification || verification.status === "skipped") {
        return;
    }

    const container = document.createElement("div");
    container.className = "verification-result";

    if (verification.status === "failed" || verification.is_correct === false) {
        container.classList.add("verify-fail");
        const issuesHtml = verification.issues && verification.issues.length > 0
            ? `<ul class="verify-issues">${verification.issues.map(i => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`
            : "";
        container.innerHTML = `
            <div class="verify-header">
                <span>❌ 结果验证未通过</span>
                <span class="verify-confidence">置信度: ${(verification.confidence * 100).toFixed(0)}%</span>
            </div>
            <div class="verify-explanation">${escapeHtml(verification.explanation || "")}</div>
            ${issuesHtml}
        `;
    } else {
        container.classList.add("verify-pass");
        container.innerHTML = `
            <div class="verify-header">
                <span>✅ 结果验证通过</span>
                <span class="verify-confidence">置信度: ${(verification.confidence * 100).toFixed(0)}%</span>
            </div>
            <div class="verify-explanation">${escapeHtml(verification.explanation || "回答内容合理")}</div>
        `;
    }

    bubble.appendChild(container);
}

export function addMessage(messagesContainer, role, content, interrupted, verification, messageId, toolCalls, options = {}) {
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

    if (verification) {
        renderVerification(bubble, verification);
    } else if (role === "assistant" && options.verifyEnabled && messageId) {
        const verifyBtn = document.createElement("button");
        verifyBtn.className = "verify-btn";
        verifyBtn.textContent = "🔍 结果验证";
        verifyBtn.onclick = () => {
            if (options.onManualVerify) {
                options.onManualVerify(messageId, bubble);
            }
        };
        bubble.appendChild(verifyBtn);
    }

    if (role === "assistant" && messageId) {
        const feedbackDiv = document.createElement("div");
        feedbackDiv.className = "feedback-buttons";
        feedbackDiv.innerHTML = `
            <button class="feedback-btn like-btn" data-message-id="${messageId}" data-feedback="like" title="有帮助">👍</button>
            <button class="feedback-btn dislike-btn" data-message-id="${messageId}" data-feedback="dislike" title="需要改进">👎</button>
        `;
        bubble.appendChild(feedbackDiv);

        feedbackDiv.querySelectorAll('.feedback-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                if (options.onSubmitFeedback) {
                    options.onSubmitFeedback(this.dataset.messageId, this.dataset.feedback, this);
                }
            });
        });
    }

    if (toolCalls && toolCalls.length > 0) {
        renderToolCalls(bubble, toolCalls);
    }

    row.appendChild(avatar);
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    
    return bubble;
}

export function createStreamingBubble(messagesContainer) {
    const welcome = messagesContainer.querySelector(".welcome-message");
    if (welcome) welcome.remove();

    const row = document.createElement("div");
    row.className = "message-row assistant";

    const avatar = document.createElement("div");
    avatar.className = "avatar assistant";
    avatar.textContent = "AI";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    
    const loadingText = document.createElement("span");
    loadingText.className = "loading-text";
    loadingText.textContent = "正在回复中...";
    bubble.appendChild(loadingText);

    row.appendChild(avatar);
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    
    return bubble;
}

// 复制代码功能（暴露到全局）
window.copyCode = function(btn) {
    const code = btn.previousElementSibling.textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '已复制';
        setTimeout(() => btn.textContent = '复制', 2000);
    });
};
