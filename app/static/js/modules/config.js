// config.js - 配置管理

export async function loadModels(modelSelector) {
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

export async function loadVerifyConfig(verifySwitch) {
    if (!verifySwitch) return false;
    try {
        const res = await fetch("/api/config/verify");
        const data = await res.json();
        verifySwitch.checked = data.enabled;
        return data.enabled;
    } catch (e) {
        console.error("加载验证配置失败:", e);
        return false;
    }
}

export async function loadToolsConfig(knowledgeSearchSwitch, codeIndexSwitch) {
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

export function setupConfigListeners(knowledgeSearchSwitch, codeIndexSwitch, verifySwitch, callbacks = {}) {
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
            const verifyEnabled = this.checked;
            try {
                await fetch("/api/config/verify", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ enabled: verifyEnabled })
                });
                if (callbacks.onVerifyConfigChange) {
                    callbacks.onVerifyConfigChange(verifyEnabled);
                }
            } catch (e) {
                console.error("更新验证配置失败:", e);
                this.checked = !verifyEnabled;
            }
        });
    }
}
