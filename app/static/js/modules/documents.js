// documents.js - 知识库文档管理

import { escapeHtml } from './utils.js';

export async function loadDocuments(kbDocList) {
    try {
        const res = await fetch("/api/documents");
        const docs = await res.json();
        renderDocuments(kbDocList, docs);
    } catch (e) {
        console.error("加载文档列表失败:", e);
    }
}

export function renderDocuments(kbDocList, docs) {
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
            loadDocuments(kbDocList);
        });
        kbDocList.appendChild(item);
    });
}

export function setupFileUpload(fileUpload, kbDocList) {
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
                loadDocuments(kbDocList);
            } catch (e) {
                alert("上传失败: " + e.message);
                loadDocuments(kbDocList);
            }
        });
    }
}

export async function loadKnowledgeCount() {
    try {
        const response = await fetch('/api/documents');
        const data = await response.json();
        const count = Array.isArray(data) ? data.length : (data.documents ? data.documents.length : 0);
        const badge = document.getElementById('knowledge-count');
        if (badge) {
            badge.textContent = count;
        }
    } catch (error) {
        console.error('加载知识库数量失败:', error);
    }
}
