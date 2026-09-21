// utils.js - 通用工具函数

export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

export function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', { 
        month: '2-digit', 
        day: '2-digit', 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

export function formatTokenCount(n) {
    if (!n) return "0";
    if (n >= 10000) return (n / 10000).toFixed(1) + "万";
    if (n >= 1000) return (n / 1000).toFixed(1) + "k";
    return String(n);
}

export function scrollToBottom(container) {
    if (container) container.scrollTop = container.scrollHeight;
}

// Toast 提示函数
export function showToast(message, type = 'info', duration = 3000) {
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

// 确认弹窗函数
export function showConfirm(title, message) {
    return new Promise((resolve) => {
        const confirmModal = document.getElementById('confirm-modal');
        const confirmTitle = document.getElementById('confirm-title');
        const confirmMessage = document.getElementById('confirm-message');
        const confirmOk = document.getElementById('confirm-ok');
        const confirmCancel = document.getElementById('confirm-cancel');
        
        if (!confirmModal) {
            resolve(false);
            return;
        }
        
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
export function showIndexModeConfirm(isPending) {
    return new Promise((resolve) => {
        const indexModeModal = document.getElementById('index-mode-modal');
        const indexModeOk = document.getElementById('index-mode-ok');
        const indexModeCancel = document.getElementById('index-mode-cancel');
        
        if (!indexModeModal) {
            resolve(null);
            return;
        }
        
        // 如果是待索引状态，默认选中增量；否则默认选中全量
        const defaultMode = isPending ? 'incremental' : 'full';
        const defaultRadio = document.querySelector(`input[name="index-mode"][value="${defaultMode}"]`);
        if (defaultRadio) defaultRadio.checked = true;
        
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
