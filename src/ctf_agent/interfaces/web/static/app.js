const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const containerStatus = document.getElementById('container-status');
const msgCount = document.getElementById('msg-count');
const imgCount = document.getElementById('img-count');
const hitlStatus = document.getElementById('hitl-status');
const hitlPending = document.getElementById('hitl-pending');

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

        // --- HITL events ---
        case 'approval_request':
            showApprovalDialog(event);
            break;
        case 'checkpoint':
            showApprovalDialog({
                ...event,
                approval_type: 'checkpoint',
                data: event.data || event,
            });
            break;
        case 'agent_question':
            showApprovalDialog({
                ...event,
                approval_type: 'agent_question',
                data: event.data || event,
            });
            break;
        case 'tool_approval_requested':
            addMessage('system', `Awaiting approval for: ${event.tool}`);
            break;
        case 'tool_rejected':
            addMessage('tool-error', `Tool rejected: ${event.tool} — ${event.reason || 'no reason'}`);
            break;
    }
}

function showApprovalDialog(event) {
    const requestId = event.request_id;
    const approvalType = event.approval_type;
    const data = event.data || {};

    const container = document.createElement('div');
    container.className = 'message approval-request';
    container.id = `approval-${requestId}`;

    let content = '';
    if (approvalType === 'tool_approval') {
        const toolName = data.tool_name || '';
        const toolInput = JSON.stringify(data.tool_input || {}, null, 2);
        content = `
            <div class="approval-header">Tool Approval Required</div>
            <div class="approval-tool">${toolName}</div>
            <pre class="approval-args">${toolInput}</pre>
        `;
    } else if (approvalType === 'checkpoint') {
        content = `
            <div class="approval-header">Checkpoint</div>
            <div>${data.message || 'Checkpoint reached. Continue?'}</div>
        `;
    } else if (approvalType === 'agent_question') {
        const question = data.question || data.tool_input?.question || '';
        content = `
            <div class="approval-header">Agent Question</div>
            <div class="approval-question">${question}</div>
        `;
    }

    content += `
        <div class="approval-actions">
            <input type="text" class="approval-message"
                   placeholder="${approvalType === 'agent_question' ? 'Your answer...' : 'Optional message...'}"
                   onkeydown="if(event.key==='Enter') submitApproval('${requestId}', 'approve')" />
            <button class="btn-approve" onclick="submitApproval('${requestId}', 'approve')">
                ${approvalType === 'agent_question' ? 'Send' : 'Approve'}
            </button>
            <button class="btn-reject" onclick="submitApproval('${requestId}', 'reject')">
                Reject
            </button>
        </div>
    `;

    container.innerHTML = content;
    chatMessages.appendChild(container);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    // Focus the input
    const input = container.querySelector('.approval-message');
    if (input) input.focus();

    updateHITLPending(1);
}

function submitApproval(requestId, decision) {
    const container = document.getElementById(`approval-${requestId}`);
    const msgInput = container?.querySelector('.approval-message');
    const message = msgInput?.value || '';

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'approval_response',
            request_id: requestId,
            decision: decision,
            message: message,
        }));
    }

    // Update UI to show decision was made
    if (container) {
        const actions = container.querySelector('.approval-actions');
        if (actions) {
            const cls = decision === 'approve' ? 'approved' : 'rejected';
            const label = decision === 'approve' ? 'APPROVED' : 'REJECTED';
            const extra = message ? ` — ${message}` : '';
            actions.innerHTML = `<span class="${cls}">${label}${extra}</span>`;
        }
    }

    updateHITLPending(-1);
}

function updateHITLPending(delta) {
    if (hitlPending) {
        const current = parseInt(hitlPending.textContent) || 0;
        hitlPending.textContent = Math.max(0, current + delta);
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

        // Update HITL status
        if (hitlStatus) {
            if (data.hitl?.enabled) {
                hitlStatus.textContent = 'Enabled';
                hitlStatus.className = 'hitl-enabled';
            } else {
                hitlStatus.textContent = 'Disabled';
                hitlStatus.className = '';
            }
        }
        if (hitlPending && data.hitl?.pending_count !== undefined) {
            hitlPending.textContent = data.hitl.pending_count;
        }
    } catch (err) {
        // Status update failed, ignore
    }
}

// Initialize
connectWebSocket();
updateStatus();
setInterval(updateStatus, 10000);
