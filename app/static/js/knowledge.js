/**
 * knowledge.js - 知识库管理页面专用脚本
 * 用于 /knowledge 页面
 */
(function () {
    const fileUpload = document.getElementById("file-upload");
    const kbDocList = document.getElementById("kb-doc-list");
    const statsEl = document.getElementById("knowledge-stats");

    // ========== 加载文档列表 ==========
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
        if (!kbDocList) return;
        if (!docs || docs.length === 0) {
            kbDocList.innerHTML = '<div class="kb-empty">暂无文档，点击上方按钮上传</div>';
            return;
        }
        kbDocList.innerHTML = "";
        docs.forEach(doc => {
            const item = document.createElement("div");
            item.className = "kb-doc-item";
            const sizeStr = doc.file_size > 1024 * 1024
                ? (doc.file_size / 1024 / 1024).toFixed(1) + ' MB'
                : (doc.file_size / 1024).toFixed(1) + ' KB';
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
                loadKnowledgeStats();
            });
            kbDocList.appendChild(item);
        });
    }

    // ========== 文件上传 ==========
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
                    showToast(data.error || "上传失败", 'error');
                } else {
                    showToast('文档上传成功', 'success');
                }
                loadDocuments();
                loadKnowledgeStats();
            } catch (e) {
                showToast("上传失败: " + e.message, 'error');
                loadDocuments();
                loadKnowledgeStats();
            }
        });
    }

    // ========== 统计信息 ==========
    async function loadKnowledgeStats() {
        try {
            const res = await fetch("/api/documents");
            const docs = await res.json();
            if (!statsEl) return;

            const totalDocs = docs.length;
            const totalChunks = docs.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
            const totalSize = docs.reduce((sum, doc) => sum + (doc.file_size || 0), 0);
            const sizeText = totalSize > 1024 * 1024
                ? (totalSize / 1024 / 1024).toFixed(1) + ' MB'
                : (totalSize / 1024).toFixed(1) + ' KB';

            statsEl.innerHTML = `
                <div class="stat-card">
                    <div class="stat-icon">📄</div>
                    <div class="stat-info">
                        <div class="stat-value">${totalDocs}</div>
                        <div class="stat-label">文档数量</div>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">🧩</div>
                    <div class="stat-info">
                        <div class="stat-value">${totalChunks}</div>
                        <div class="stat-label">分块数量</div>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">💾</div>
                    <div class="stat-info">
                        <div class="stat-value">${sizeText}</div>
                        <div class="stat-label">总大小</div>
                    </div>
                </div>
            `;
        } catch (e) {
            console.error('加载统计信息失败:', e);
        }
    }

    // ========== Toast 提示 ==========
    function showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('toast-hiding');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // ========== 初始化 ==========
    loadDocuments();
    loadKnowledgeStats();
})();
