const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const containerStatus = document.getElementById('container-status');
const msgCount = document.getElementById('msg-count');
const imgCount = document.getElementById('img-count');
const hitlStatus = document.getElementById('hitl-status');
const hitlPending = document.getElementById('hitl-pending');

let ws = null;

// ============================
// Theme toggle
// ============================

function getTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('ctf-theme', theme);
    updateThemeIcon();
}

function toggleTheme() {
    setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

function updateThemeIcon() {
    const btn = document.getElementById('theme-toggle');
    if (btn) {
        btn.textContent = getTheme() === 'dark' ? '\u2600' : '\u263D';
        btn.title = getTheme() === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }
}

updateThemeIcon();

// ============================
// Sidebar mode (docked / overlay)
// ============================

function getSidebarMode() {
    return document.documentElement.getAttribute('data-sidebar') || 'docked';
}

function isSidebarOpen() {
    return document.documentElement.getAttribute('data-sidebar-open') !== 'false';
}

function setSidebarMode(mode) {
    document.documentElement.setAttribute('data-sidebar', mode);
    localStorage.setItem('ctf-sidebar-mode', mode);

    if (mode === 'overlay') {
        const wasOpen = localStorage.getItem('ctf-sidebar-open') !== 'false';
        setSidebarOpen(wasOpen);
    } else {
        document.documentElement.removeAttribute('data-sidebar-open');
    }

    updateSidebarModeIcon();
    updateSidebarOverlayIcon();
}

function setSidebarOpen(open) {
    document.documentElement.setAttribute('data-sidebar-open', open ? 'true' : 'false');
    localStorage.setItem('ctf-sidebar-open', open ? 'true' : 'false');
    updateSidebarOverlayIcon();
}

function toggleSidebarMode() {
    setSidebarMode(getSidebarMode() === 'docked' ? 'overlay' : 'docked');
}

function toggleSidebarOverlay() {
    if (getSidebarMode() !== 'overlay') return;
    setSidebarOpen(!isSidebarOpen());
}

function updateSidebarModeIcon() {
    const btn = document.getElementById('sidebar-mode-toggle');
    if (!btn) return;
    if (getSidebarMode() === 'docked') {
        btn.textContent = '\u29C9'; // two overlapping squares — "float" hint
        btn.title = 'Switch to overlay sidebar';
    } else {
        btn.textContent = '\u25EB'; // square with right half — "dock" hint
        btn.title = 'Switch to docked sidebar';
    }
}

function updateSidebarOverlayIcon() {
    const btn = document.getElementById('sidebar-overlay-toggle');
    if (!btn) return;
    if (isSidebarOpen()) {
        btn.textContent = '\u203A'; // › chevron right — "close"
        btn.title = 'Hide agent panel';
    } else {
        btn.textContent = '\u2039'; // ‹ chevron left — "open"
        btn.title = 'Show agent panel';
    }
}

updateSidebarModeIcon();
updateSidebarOverlayIcon();

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

// ============================
// Clipboard Mode
// ============================

function setClipboardMode(mode) {
    localStorage.setItem('ctf-clipboard-mode', mode);
    const select = document.getElementById('clipboard-mode');
    if (select) select.value = mode;
    if (_desktopViewer) {
        _desktopViewer.setClipboardMode(mode);
    }
}

// Restore saved clipboard mode on load
(function initClipboardMode() {
    const saved = localStorage.getItem('ctf-clipboard-mode') || 'disabled';
    const select = document.getElementById('clipboard-mode');
    if (select) select.value = saved;
})();

// ============================
// WebRTC Desktop Viewer
// ============================

let _desktopViewer = null;

function initDesktopViewer(signalingUrl, containerApiUrl) {
    if (_desktopViewer) return;
    const video = document.getElementById('desktop-video');
    const canvas = document.getElementById('desktop-overlay');
    if (!video || !canvas) return;
    _desktopViewer = new DesktopViewer(video, canvas, signalingUrl, containerApiUrl);
    _desktopViewer.connect();
}


async function updateStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        msgCount.textContent = data.context?.message_count || 0;
        imgCount.textContent = data.context?.image_count || 0;

        // Initialize desktop viewer when container is running
        if (data.container_running && !_desktopViewer) {
            initDesktopViewer('/api/webrtc', data.container_api_url);
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

// ============================
// Recording Playback (inline panel)
// ============================

let _playbackData = null;
let _playbackIndex = -1;
let _playbackTimer = null;
let _playbackSpeed = 500;
let _activeSessionId = null;

function openRecordings() {
    stopPlayback();
    document.getElementById('chat-view').style.display = 'none';
    document.getElementById('recordings-view').style.display = 'flex';
    loadRecordingList();
}

function closeRecordings() {
    stopPlayback();
    hidePlaybackScreenshot();
    document.getElementById('recordings-view').style.display = 'none';
    document.getElementById('chat-view').style.display = 'flex';
}

function backToSessions() {
    stopPlayback();
    hidePlaybackScreenshot();
    _activeSessionId = null;
    _playbackData = null;
    document.getElementById('events-area').style.display = 'none';
    document.getElementById('sessions-area').style.display = 'flex';
}

function showPlaybackScreenshot(sessionId, filename) {
    const img = document.getElementById('playback-screenshot');
    const viewerContainer = document.getElementById('desktop-viewer-container');
    img.src = `/api/recordings/${sessionId}/screenshot/${filename}`;
    img.style.display = 'block';
    if (viewerContainer) viewerContainer.style.visibility = 'hidden';
    document.getElementById('desktop-title').textContent = 'Recording Playback';
}

function hidePlaybackScreenshot() {
    const img = document.getElementById('playback-screenshot');
    const viewerContainer = document.getElementById('desktop-viewer-container');
    img.style.display = 'none';
    if (viewerContainer) viewerContainer.style.visibility = 'visible';
    document.getElementById('desktop-title').textContent = 'Live Desktop';
}

async function loadRecordingList() {
    const listEl = document.getElementById('session-list');
    try {
        const resp = await fetch('/api/recordings');
        const sessions = await resp.json();

        if (!sessions.length) {
            listEl.innerHTML = '<div class="sessions-empty">No recordings yet. Start a task to record.</div>';
            return;
        }

        listEl.innerHTML = sessions.map(s => {
            const date = new Date(s.started_at * 1000).toLocaleString();
            const dur = s.duration_seconds ? `${Math.round(s.duration_seconds)}s` : 'running';
            const evts = s.total_events || '?';
            return `
                <div class="session-card" onclick="loadRecording('${s.session_id}')">
                    <div class="session-card-task">${escapeHtml(s.task || 'Untitled')}</div>
                    <div class="session-card-meta">
                        <span>${date}</span>
                        <span>${dur} / ${evts} events</span>
                        <button class="session-card-delete" onclick="event.stopPropagation(); deleteRecording('${s.session_id}')" title="Delete">&times;</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        listEl.innerHTML = '<div class="sessions-empty">Failed to load recordings.</div>';
    }
}

function formatEventItem(ev, i, startTime) {
    const elapsed = ((ev.timestamp || 0) - startTime).toFixed(1);
    let detail = '';
    const d = ev.data || {};

    switch (ev.event_type) {
        case 'tool_call':
            detail = d.tool || '';
            if (d.input) {
                const inp = typeof d.input === 'string' ? d.input : JSON.stringify(d.input);
                detail += '\n' + inp;
            }
            break;
        case 'tool_result':
            detail = d.output || '';
            if (d.is_error) detail = '[ERROR] ' + detail;
            break;
        case 'text':
            detail = d.text || '';
            break;
        case 'thinking':
            detail = d.iteration ? `iteration ${d.iteration}` : '';
            break;
        case 'error':
            detail = d.text || '';
            break;
        case 'done':
            detail = d.text || 'Task completed';
            break;
    }

    return `
        <div class="event-item" id="event-${i}" onclick="seekToFrame(${i})">
            <span class="event-time">+${elapsed}s</span>
            <span class="event-type ${ev.event_type}">${ev.event_type}</span>
            ${detail ? `<div class="event-detail">${escapeHtml(detail)}</div>` : ''}
        </div>
    `;
}

async function loadRecording(sessionId) {
    stopPlayback();
    _activeSessionId = sessionId;
    _playbackIndex = -1;

    try {
        const resp = await fetch(`/api/recordings/${sessionId}`);
        _playbackData = await resp.json();

        if (_playbackData.error) {
            return;
        }

        // Switch from session list to events view
        document.getElementById('sessions-area').style.display = 'none';
        document.getElementById('events-area').style.display = 'flex';

        // Show task name
        document.getElementById('recording-task-name').textContent =
            _playbackData.task || 'Untitled';

        // Render all events (hidden by default via CSS display:none)
        const eventsEl = document.getElementById('events-list');
        const startTime = _playbackData.started_at || 0;

        eventsEl.innerHTML = _playbackData.events
            .map((ev, i) => formatEventItem(ev, i, startTime))
            .join('');

        // Configure scrubber
        const scrubber = document.getElementById('playback-scrubber');
        scrubber.max = Math.max(0, _playbackData.events.length - 1);
        scrubber.value = 0;
        document.getElementById('playback-frame-info').textContent =
            `0 / ${_playbackData.events.length}`;

        // Show first event
        seekToFrame(0);
    } catch (err) {
        // ignore
    }
}

function seekToFrame(index) {
    if (!_playbackData || !_playbackData.events.length) return;

    _playbackIndex = Math.max(0, Math.min(index, _playbackData.events.length - 1));

    // Update scrubber
    document.getElementById('playback-scrubber').value = _playbackIndex;
    document.getElementById('playback-frame-info').textContent =
        `${_playbackIndex + 1} / ${_playbackData.events.length}`;

    // Show events up to current index (display:block), hide the rest (display:none)
    document.querySelectorAll('.event-item').forEach((el, i) => {
        el.classList.toggle('visible', i <= _playbackIndex);
        el.classList.toggle('active', i === _playbackIndex);
    });

    // Show screenshot: find the most recent event with a screenshot (at or before current)
    let screenshotFile = null;
    for (let i = _playbackIndex; i >= 0; i--) {
        if (_playbackData.events[i].screenshot) {
            screenshotFile = _playbackData.events[i].screenshot;
            break;
        }
    }
    if (screenshotFile && _activeSessionId) {
        showPlaybackScreenshot(_activeSessionId, screenshotFile);
    }

    // Scroll to current event
    const activeEl = document.getElementById(`event-${_playbackIndex}`);
    if (activeEl) {
        activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
}

function seekRelative(delta) {
    seekToFrame(_playbackIndex + delta);
}

function togglePlayback() {
    const btn = document.getElementById('playback-toggle');
    if (_playbackTimer) {
        stopPlayback();
    } else {
        btn.textContent = 'Pause';
        _playbackTimer = setInterval(() => {
            if (_playbackIndex >= (_playbackData?.events?.length || 0) - 1) {
                stopPlayback();
                return;
            }
            seekToFrame(_playbackIndex + 1);
        }, _playbackSpeed);
    }
}

function stopPlayback() {
    if (_playbackTimer) {
        clearInterval(_playbackTimer);
        _playbackTimer = null;
    }
    const btn = document.getElementById('playback-toggle');
    if (btn) btn.textContent = 'Play';
}

function setPlaybackSpeed(ms) {
    _playbackSpeed = parseInt(ms);
    if (_playbackTimer) {
        stopPlayback();
        togglePlayback();
    }
}

async function deleteRecording(sessionId) {
    try {
        await fetch(`/api/recordings/${sessionId}`, { method: 'DELETE' });
        if (sessionId === _activeSessionId) {
            backToSessions();
        }
        await loadRecordingList();
    } catch (err) {
        // ignore
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Initialize
connectWebSocket();
updateStatus();
setInterval(updateStatus, 10000);
