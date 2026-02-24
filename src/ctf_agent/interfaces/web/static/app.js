const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const containerStatus = document.getElementById('container-status');
const msgCount = document.getElementById('msg-count');
const imgCount = document.getElementById('img-count');

let ws = null;

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        containerStatus.textContent = 'Connected';
        containerStatus.className = 'status-badge connected';
    };

    ws.onclose = () => {
        containerStatus.textContent = 'Disconnected';
        containerStatus.className = 'status-badge disconnected';
        setTimeout(connectWebSocket, 3000);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleAgentEvent(data);
    };
}

function handleAgentEvent(event) {
    switch (event.type) {
        case 'thinking':
            addMessage('system', `Thinking... (iteration ${event.iteration})`);
            break;
        case 'tool_call':
            addMessage('tool-call', `${event.tool}(${JSON.stringify(event.input).substring(0, 200)})`);
            break;
        case 'tool_result': {
            const cls = event.is_error ? 'tool-error' : 'tool-result';
            const output = event.output.length > 500
                ? event.output.substring(0, 500) + '...'
                : event.output;
            addMessage(cls, output);
            break;
        }
        case 'text':
            addMessage('agent', event.text);
            break;
        case 'error':
            addMessage('tool-error', event.text || 'An error occurred');
            break;
        case 'done':
            addMessage('system', 'Agent completed task.');
            updateStatus();
            break;
    }
}

function addMessage(type, content) {
    const div = document.createElement('div');
    div.className = `message ${type}`;
    div.textContent = content;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;

    addMessage('user', message);
    messageInput.value = '';

    try {
        await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });
    } catch (err) {
        addMessage('system', `Error: ${err.message}`);
    }
}

async function stopAgent() {
    await fetch('/api/stop', { method: 'POST' });
    addMessage('system', 'Stop requested.');
}

async function clearContext() {
    await fetch('/api/clear', { method: 'POST' });
    chatMessages.innerHTML = '';
    addMessage('system', 'Context cleared.');
    updateStatus();
}

async function updateStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        msgCount.textContent = data.context?.message_count || 0;
        imgCount.textContent = data.context?.image_count || 0;

        if (data.novnc_url) {
            const frame = document.getElementById('vnc-frame');
            if (!frame.src || frame.src === window.location.href) {
                frame.src = data.novnc_url + '?autoconnect=true&resize=scale';
            }
        }

        if (data.container_running) {
            containerStatus.textContent = 'Running';
            containerStatus.className = 'status-badge connected';
        }
    } catch (err) {
        // Status update failed, ignore
    }
}

// Initialize
connectWebSocket();
updateStatus();
setInterval(updateStatus, 10000);
