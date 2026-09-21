// socket.js - WebSocket 连接管理

export class SocketManager {
    constructor() {
        this.socket = null;
        this.currentMessageId = null;
        this.currentBubble = null;
        this.fullContent = "";
        this.toolCalls = [];
        this.isStreaming = false;
    }

    init(currentConvId, callbacks) {
        if (this.socket) return;

        this.socket = io({
            transports: ['websocket'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 5
        });

        this.socket.on('connect', () => {
            console.log('WebSocket 已连接');
            if (currentConvId) {
                this.socket.emit('join', { conversation_id: currentConvId });
            }
        });

        this.socket.on('disconnect', () => {
            console.log('WebSocket 已断开');
        });

        this.socket.on('token', (data) => {
            if (!this.currentMessageId && this.currentBubble) {
                this.currentMessageId = data.message_id;
                console.log('[WS] Auto-bound message_id from first token:', this.currentMessageId);
            }

            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            this.fullContent += data.token;
            const cursor = this.currentBubble.querySelector(".typing-cursor");
            if (cursor) cursor.remove();
            
            if (callbacks.onToken) {
                callbacks.onToken(this.currentBubble, this.fullContent);
            }
        });

        this.socket.on('tool_calls', (data) => {
            if (!this.currentMessageId && this.currentBubble) {
                this.currentMessageId = data.message_id;
                console.log('[WS] Auto-bound message_id from tool_calls:', this.currentMessageId);
            }

            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            this.toolCalls = this.toolCalls.concat(data.tool_calls);
            if (callbacks.onToolCalls) {
                callbacks.onToolCalls(this.currentBubble, this.toolCalls);
            }
        });

        this.socket.on('generation_completed', (data) => {
            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            const cursor = this.currentBubble.querySelector(".typing-cursor");
            if (cursor) cursor.remove();

            this.fullContent = data.content;
            if (callbacks.onComplete) {
                callbacks.onComplete(this.currentBubble, this.fullContent);
            }

            this.reset();
        });

        this.socket.on('generation_stopped', (data) => {
            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            const cursor = this.currentBubble.querySelector(".typing-cursor");
            if (cursor) cursor.remove();

            if (callbacks.onStopped) {
                callbacks.onStopped(this.currentBubble);
            }

            this.reset();
        });

        this.socket.on('verifying', (data) => {
            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            if (callbacks.onVerifying) {
                callbacks.onVerifying(this.currentBubble);
            }
        });

        this.socket.on('verified', (data) => {
            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            if (callbacks.onVerified) {
                callbacks.onVerified(this.currentBubble, data.verification);
            }
        });

        this.socket.on('generation_error', (data) => {
            if (!this.currentBubble || this.currentMessageId !== data.message_id) return;

            if (callbacks.onError) {
                callbacks.onError(this.currentBubble, data);
            }

            this.reset();
        });

        this.socket.on('generation_resume', (data) => {
            if (!this.isStreaming && data.message_id) {
                this.currentMessageId = data.message_id;
                this.fullContent = data.content || "";
                
                if (callbacks.onResume) {
                    callbacks.onResume(this.currentMessageId, this.fullContent);
                }
            }
        });
    }

    join(convId) {
        if (this.socket) {
            this.socket.emit('join', { conversation_id: convId });
        }
    }

    leave(convId) {
        if (this.socket) {
            this.socket.emit('leave', { conversation_id: convId });
        }
    }

    sendMessage(convId, content, model) {
        this.socket.once('message_created', (data) => {
            this.currentMessageId = data.message_id;
            console.log('[WS] Message created:', this.currentMessageId);
        });

        this.socket.emit('chat_message', {
            conversation_id: convId,
            content: content,
            model: model,
            image_urls: []
        });
    }

    stopGeneration() {
        if (this.currentMessageId) {
            this.socket.emit('stop_generation', { message_id: this.currentMessageId });
        }
    }

    setBubble(bubble) {
        this.currentBubble = bubble;
    }

    startStreaming() {
        this.isStreaming = true;
        this.fullContent = "";
        this.toolCalls = [];
    }

    reset() {
        this.isStreaming = false;
        this.currentMessageId = null;
        this.currentBubble = null;
        this.fullContent = "";
        this.toolCalls = [];
    }
}
