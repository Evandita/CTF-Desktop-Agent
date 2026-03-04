/**
 * Desktop Viewer
 *
 * Tries WebRTC first for low-latency streaming. If WebRTC ICE fails
 * (common in Docker environments), falls back to WebSocket JPEG streaming
 * which works reliably over TCP through Docker port mapping.
 *
 * Input events (mouse, keyboard, clipboard) are sent via:
 *   - WebRTC DataChannel (when using WebRTC)
 *   - The same WebSocket connection (when using WS fallback)
 *
 * Clipboard sharing uses two strategies:
 *   - Clipboard API (navigator.clipboard) when available (secure context)
 *     → noVNC-style: sync on focus events
 *   - Paste event fallback when Clipboard API is unavailable
 *     → intercept paste event for host→guest, hidden textarea for guest→host
 */
class DesktopViewer {
    constructor(videoElement, overlayCanvas, signalingUrl, containerApiUrl) {
        this.video = videoElement;
        this.canvas = overlayCanvas;
        this.signalingUrl = signalingUrl;       // e.g. "/api/webrtc"
        this.containerApiUrl = containerApiUrl; // e.g. "http://localhost:8888"
        this.pc = null;
        this.dataChannel = null;
        this.ws = null;
        this.connectionId = null;
        this.connected = false;
        this.mode = null; // "webrtc" or "ws"
        this.desktopWidth = 1024;
        this.desktopHeight = 768;
        this._moveThrottle = false;
        this._reconnectTimer = null;
        this._destroyed = false;
        this._webrtcAttempts = 0;
        this._maxWebrtcAttempts = 1; // Try WebRTC once before falling back to WS

        // Clipboard sharing
        this.clipboardMode = localStorage.getItem('ctf-clipboard-mode') || 'disabled';
        this._clipboardPollTimer = null;
        this._lastSentClipboard = '';     // anti-echo: last text sent host→guest
        this._lastReceivedClipboard = ''; // anti-echo: last text received guest→host
        this._pasteTimeout = null;        // fallback: timeout for paste event

        // Detect Clipboard API availability (requires secure context)
        this._hasClipboardAPI = !!(navigator.clipboard && navigator.clipboard.readText);
        console.log('[clipboard] Clipboard API available:', this._hasClipboardAPI);

        // Hidden textarea for guest→host clipboard when Clipboard API unavailable
        this._clipboardTextarea = null;

        // For WS mode: draw JPEG frames on a canvas placed behind the overlay
        this._frameCanvas = document.createElement('canvas');
        this._frameCanvas.id = 'desktop-frame-canvas';
        this._frameCanvas.width = this.desktopWidth;
        this._frameCanvas.height = this.desktopHeight;
        this._frameCanvas.style.display = 'none';
        // Insert frame canvas into the viewer container, before the overlay
        const container = this.canvas.parentElement;
        if (container) {
            container.insertBefore(this._frameCanvas, this.canvas);
        }
        this._frameCtx = this._frameCanvas.getContext('2d');

        this._setupEventListeners();
    }

    // ---------------------------------------------------------------
    // Connection lifecycle
    // ---------------------------------------------------------------

    async connect() {
        if (this._destroyed) return;
        this._clearReconnect();

        if (this._webrtcAttempts < this._maxWebrtcAttempts) {
            this._webrtcAttempts++;
            await this._connectWebRTC();
        } else {
            await this._connectWebSocket();
        }
    }

    async _connectWebRTC() {
        this._setStatus('Connecting via WebRTC...');
        let switchingToWs = false;

        const fallbackToWs = () => {
            if (switchingToWs) return; // prevent double-fallback
            switchingToWs = true;
            if (this.pc) { this.pc.close(); this.pc = null; }
            this._webrtcAttempts = this._maxWebrtcAttempts;
            this._connectWebSocket();
        };

        try {
            this.pc = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
            });

            // Track whether ICE actually connected
            let iceConnected = false;
            const iceTimeout = setTimeout(() => {
                if (!iceConnected && this.pc) {
                    console.warn('WebRTC ICE timeout — falling back to WebSocket');
                    fallbackToWs();
                }
            }, 5000);

            this.pc.ontrack = (event) => {
                this.video.srcObject = event.streams[0];
                this.video.style.display = 'block';
                this._frameCanvas.style.display = 'none';
                this.video.play().catch(() => {});
            };

            this.dataChannel = this.pc.createDataChannel('input', { ordered: true });
            this.dataChannel.onopen = () => {
                iceConnected = true;
                clearTimeout(iceTimeout);
                this.connected = true;
                this.mode = 'webrtc';
                this._setStatus(null);
                this._send({ type: 'clipboard_mode', mode: this.clipboardMode });
                this._updateClipboardPolling();
                console.log('Desktop viewer: WebRTC connected');
            };
            this.dataChannel.onclose = () => {
                if (switchingToWs) return; // don't reconnect if we're falling back
                this.connected = false;
                this._setStatus('Stream disconnected. Reconnecting...');
                this._scheduleReconnect();
            };

            this.pc.onconnectionstatechange = () => {
                if (this.pc && this.pc.connectionState === 'failed') {
                    clearTimeout(iceTimeout);
                    console.warn('WebRTC connection failed — falling back to WebSocket');
                    fallbackToWs();
                }
            };

            const offer = await this.pc.createOffer();
            await this.pc.setLocalDescription(offer);
            await this._waitForICE();

            const resp = await fetch(`${this.signalingUrl}/offer`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sdp: this.pc.localDescription.sdp,
                    type: this.pc.localDescription.type,
                }),
            });

            if (!resp.ok) throw new Error(`Signaling error: ${resp.status}`);

            const answer = await resp.json();
            if (answer.error) throw new Error(`Server: ${answer.error}`);
            this.connectionId = answer.connection_id;

            await this.pc.setRemoteDescription(
                new RTCSessionDescription({ sdp: answer.sdp, type: answer.type })
            );
        } catch (err) {
            console.warn('WebRTC connect failed:', err);
            if (switchingToWs) return; // already falling back
            if (this._webrtcAttempts >= this._maxWebrtcAttempts) {
                fallbackToWs();
            } else {
                this._setStatus('Connecting to desktop...');
                this._scheduleReconnect();
            }
        }
    }

    async _connectWebSocket() {
        this._setStatus('Connecting via WebSocket...');

        // Build WebSocket URL from the container API URL
        let wsUrl;
        if (this.containerApiUrl) {
            wsUrl = this.containerApiUrl.replace(/^http/, 'ws') + '/ws/desktop';
        } else {
            // Fallback: try proxied path
            const loc = window.location;
            wsUrl = `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}/api/ws/desktop`;
        }

        try {
            this.ws = new WebSocket(wsUrl);
            this.ws.binaryType = 'blob';

            this.ws.onopen = () => {
                this.connected = true;
                this.mode = 'ws';
                this._setStatus(null);
                this._send({ type: 'clipboard_mode', mode: this.clipboardMode });
                this._stopClipboardPolling(); // WS mode uses push, not polling
                console.log('Desktop viewer: WebSocket connected to', wsUrl);
                // Hide video element, show frame canvas for WS rendering
                this.video.style.display = 'none';
                this._frameCanvas.style.display = 'block';
            };

            this.ws.onmessage = (event) => {
                if (event.data instanceof Blob) {
                    this._renderFrame(event.data);
                } else if (typeof event.data === 'string') {
                    this._handleServerMessage(event.data);
                }
            };

            this.ws.onclose = () => {
                this.connected = false;
                if (!this._destroyed) {
                    this._setStatus('Stream disconnected. Reconnecting...');
                    this._scheduleReconnect();
                }
            };

            this.ws.onerror = (err) => {
                console.warn('WebSocket error:', err);
            };
        } catch (err) {
            console.warn('WebSocket connect failed:', err);
            this._setStatus('Connection failed. Retrying...');
            this._scheduleReconnect();
        }
    }

    _renderFrame(blob) {
        const url = URL.createObjectURL(blob);
        const img = new window.Image();
        img.onload = () => {
            // Update desktop dimensions from first frame
            if (this.desktopWidth !== img.width || this.desktopHeight !== img.height) {
                this.desktopWidth = img.width;
                this.desktopHeight = img.height;
                this._frameCanvas.width = img.width;
                this._frameCanvas.height = img.height;
            }
            this._frameCtx.drawImage(img, 0, 0);
            URL.revokeObjectURL(url);
        };
        img.onerror = () => URL.revokeObjectURL(url);
        img.src = url;
    }

    async disconnect() {
        this._destroyed = true;
        this._clearReconnect();
        this._stopClipboardPolling();
        if (this.connectionId) {
            fetch(`${this.signalingUrl}/disconnect`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ connection_id: this.connectionId }),
            }).catch(() => {});
        }
        if (this.pc) {
            this.pc.close();
            this.pc = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    _waitForICE() {
        return new Promise((resolve) => {
            if (this.pc.iceGatheringState === 'complete') {
                resolve();
                return;
            }
            const timeout = setTimeout(resolve, 2000);
            this.pc.onicegatheringstatechange = () => {
                if (this.pc.iceGatheringState === 'complete') {
                    clearTimeout(timeout);
                    resolve();
                }
            };
        });
    }

    _scheduleReconnect() {
        this._clearReconnect();
        if (this._destroyed) return;
        // Don't schedule reconnect if we're already connected
        if (this.connected) return;
        this._reconnectTimer = setTimeout(() => {
            if (this.pc) { this.pc.close(); this.pc = null; }
            if (this.ws) { this.ws.close(); this.ws = null; }
            this.connect();
        }, 3000);
    }

    _clearReconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
    }

    _setStatus(text) {
        const el = document.getElementById('stream-status');
        if (!el) return;
        if (text) {
            el.textContent = text;
            el.style.display = 'block';
        } else {
            el.style.display = 'none';
        }
    }

    // ---------------------------------------------------------------
    // Event listeners (mouse, keyboard, clipboard)
    // ---------------------------------------------------------------

    _setupEventListeners() {
        const canvas = this.canvas;

        // Resize canvas to match video/frame dimensions
        this.video.addEventListener('loadedmetadata', () => {
            this.desktopWidth = this.video.videoWidth || 1024;
            this.desktopHeight = this.video.videoHeight || 768;
            canvas.width = this.desktopWidth;
            canvas.height = this.desktopHeight;
        });

        // Focus canvas on click so keyboard events are captured
        canvas.addEventListener('mousedown', () => canvas.focus());

        // --- Clipboard sync ---
        if (this._hasClipboardAPI) {
            // Preferred: noVNC-style focus-based sync using Clipboard API
            canvas.addEventListener('focus', () => this._syncClipboardToGuest());
        } else {
            // Fallback: use paste events when Clipboard API is unavailable
            console.log('[clipboard] Using paste event fallback (no secure context)');
            canvas.addEventListener('paste', (e) => this._handlePasteEvent(e));
        }

        // --- Mouse events ---
        canvas.addEventListener('click', (e) => {
            e.preventDefault();
            this._sendMouse('click', e);
        });
        canvas.addEventListener('dblclick', (e) => {
            e.preventDefault();
            this._sendMouse('double_click', e);
        });
        canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            this._sendMouse('right_click', e);
        });
        // Mouse move only while button is held (for drag operations)
        canvas.addEventListener('mousemove', (e) => {
            if (!(e.buttons & 1)) return; // only track while left-button held
            if (this._moveThrottle) return;
            this._moveThrottle = true;
            this._sendMouse('move', e);
            setTimeout(() => { this._moveThrottle = false; }, 50);
        });
        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const coords = this._getCoords(e);
            if (!coords) return;
            const direction = e.deltaY > 0 ? 'down' : 'up';
            this._send({
                type: 'mouse',
                action: 'scroll',
                x: coords.x,
                y: coords.y,
                direction,
                amount: 3,
            });
        }, { passive: false });

        // --- Keyboard events ---
        canvas.addEventListener('keydown', (e) => {
            // Fallback mode: let Ctrl+V / Cmd+V through so the paste event fires
            if (!this._hasClipboardAPI && (e.ctrlKey || e.metaKey) && e.key === 'v') {
                // Set a timeout: if paste event doesn't fire within 150ms,
                // send Ctrl+V directly to the container anyway
                if (this._pasteTimeout) clearTimeout(this._pasteTimeout);
                this._pasteTimeout = setTimeout(() => {
                    this._pasteTimeout = null;
                    this._send({ type: 'key', action: 'key_combo', keys: ['ctrl', 'v'] });
                }, 150);
                return; // don't preventDefault — let the paste event fire
            }

            e.preventDefault();

            if (e.ctrlKey || e.altKey || e.metaKey) {
                const keys = [];
                // Map Cmd (metaKey) → Ctrl for Mac users controlling Linux desktop
                if (e.ctrlKey || e.metaKey) keys.push('ctrl');
                if (e.altKey) keys.push('alt');
                if (e.shiftKey) keys.push('shift');
                const mapped = this._mapSpecialKey(e.key);
                if (mapped) keys.push(mapped);
                else if (e.key.length === 1) keys.push(e.key.toLowerCase());
                else return;
                this._send({ type: 'key', action: 'key_combo', keys });
                return;
            }

            if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
                this._send({ type: 'key', action: 'type', text: e.key });
                return;
            }

            const mapped = this._mapSpecialKey(e.key);
            if (mapped) {
                this._send({ type: 'key', action: 'key', key: mapped });
            }
        });
    }

    // ---------------------------------------------------------------
    // Coordinate mapping
    // ---------------------------------------------------------------

    _getCoords(mouseEvent) {
        const rect = this.canvas.getBoundingClientRect();

        // Account for object-fit: contain letterboxing on the frame canvas.
        // The desktop image is scaled to fit while preserving aspect ratio,
        // so there may be blank bars on the sides or top/bottom.
        const containerW = rect.width;
        const containerH = rect.height;
        const canvasAspect = this.desktopWidth / this.desktopHeight;
        const containerAspect = containerW / containerH;

        let renderedW, renderedH, offsetX, offsetY;
        if (containerAspect > canvasAspect) {
            // Container is wider than desktop — pillarboxed (bars on sides)
            renderedH = containerH;
            renderedW = containerH * canvasAspect;
            offsetX = (containerW - renderedW) / 2;
            offsetY = 0;
        } else {
            // Container is taller than desktop — letterboxed (bars top/bottom)
            renderedW = containerW;
            renderedH = containerW / canvasAspect;
            offsetX = 0;
            offsetY = (containerH - renderedH) / 2;
        }

        // Position relative to the rendered desktop area (pixels)
        const rawX = mouseEvent.clientX - rect.left - offsetX;
        const rawY = mouseEvent.clientY - rect.top - offsetY;

        // Reject clicks clearly in the letterbox/pillarbox bars.
        // A small margin (5px) allows edge clicks through despite rounding.
        const margin = 5;
        if (rawX < -margin || rawX > renderedW + margin ||
            rawY < -margin || rawY > renderedH + margin) {
            return null;
        }

        // Map to desktop coordinates and clamp to valid range
        const x = Math.round(rawX * this.desktopWidth / renderedW);
        const y = Math.round(rawY * this.desktopHeight / renderedH);
        return {
            x: Math.max(0, Math.min(this.desktopWidth - 1, x)),
            y: Math.max(0, Math.min(this.desktopHeight - 1, y)),
        };
    }

    _sendMouse(action, mouseEvent) {
        const coords = this._getCoords(mouseEvent);
        if (!coords) return; // click was in the letterbox/pillarbox area
        this._send({ type: 'mouse', action, x: coords.x, y: coords.y });
    }

    // ---------------------------------------------------------------
    // Clipboard sharing
    // ---------------------------------------------------------------

    setClipboardMode(mode) {
        this.clipboardMode = mode;
        localStorage.setItem('ctf-clipboard-mode', mode);
        // Notify the container of the new mode
        this._send({ type: 'clipboard_mode', mode });
        this._updateClipboardPolling();
    }

    /**
     * noVNC-style: read the host system clipboard on focus and send to container.
     * Only used when Clipboard API is available (secure context).
     */
    async _syncClipboardToGuest() {
        if (this.clipboardMode !== 'host_to_guest' && this.clipboardMode !== 'bidirectional') return;
        try {
            const text = await navigator.clipboard.readText();
            if (text && text !== this._lastSentClipboard) {
                this._lastSentClipboard = text;
                this._send({ type: 'clipboard', action: 'set', text });
                console.log('[clipboard] host→guest synced:', text.substring(0, 50));
            }
        } catch (err) {
            console.warn('[clipboard] readText failed:', err.name, err.message);
        }
    }

    /**
     * Paste event fallback for host→guest when Clipboard API is unavailable.
     * The keydown handler lets Ctrl+V through (no preventDefault) so this fires.
     * clipboardData is always available in paste events — no permission needed.
     */
    _handlePasteEvent(e) {
        e.preventDefault();
        // Cancel the keydown timeout — we handle it here
        if (this._pasteTimeout) {
            clearTimeout(this._pasteTimeout);
            this._pasteTimeout = null;
        }
        const text = (e.clipboardData || window.clipboardData).getData('text');
        console.log('[clipboard] paste event, got', text ? text.length : 0, 'chars');
        if (text && (this.clipboardMode === 'host_to_guest' || this.clipboardMode === 'bidirectional')) {
            this._lastSentClipboard = text;
            this._send({ type: 'clipboard', action: 'set', text });
            console.log('[clipboard] host→guest via paste:', text.substring(0, 50));
        }
        // Send Ctrl+V to the container so the app pastes from the now-synced clipboard
        this._send({ type: 'key', action: 'key_combo', keys: ['ctrl', 'v'] });
    }

    _handleServerMessage(raw) {
        try {
            const msg = JSON.parse(raw);
            if (msg.type === 'clipboard' && msg.action === 'update') {
                console.log('[clipboard] guest→host received:', msg.text.substring(0, 50));
                if (this.clipboardMode === 'guest_to_host' || this.clipboardMode === 'bidirectional') {
                    // Anti-echo: mark this text so focus/paste won't re-send it
                    this._lastSentClipboard = msg.text;
                    this._writeToHostClipboard(msg.text);
                }
            }
        } catch (e) {
            console.warn('Failed to parse server message:', e);
        }
    }

    /**
     * Write text to the host system clipboard.
     * Uses Clipboard API if available, falls back to hidden textarea + execCommand.
     */
    async _writeToHostClipboard(text) {
        if (this._hasClipboardAPI) {
            try {
                await navigator.clipboard.writeText(text);
                this._lastReceivedClipboard = text;
                console.log('[clipboard] host clipboard updated via API:', text.substring(0, 50));
                return;
            } catch (err) {
                console.warn('[clipboard] writeText failed, trying textarea fallback:', err);
            }
        }

        // Fallback: hidden textarea + execCommand('copy')
        try {
            if (!this._clipboardTextarea) {
                this._clipboardTextarea = document.createElement('textarea');
                this._clipboardTextarea.style.cssText =
                    'position:fixed;left:-9999px;top:-9999px;opacity:0;';
                document.body.appendChild(this._clipboardTextarea);
            }
            this._clipboardTextarea.value = text;
            this._clipboardTextarea.select();
            document.execCommand('copy');
            // Return focus to the canvas
            this.canvas.focus();
            this._lastReceivedClipboard = text;
            console.log('[clipboard] host clipboard updated via textarea:', text.substring(0, 50));
        } catch (err) {
            console.warn('[clipboard] textarea copy fallback also failed:', err);
        }
    }

    _updateClipboardPolling() {
        // In WebRTC mode, guest→host requires REST polling since we can't
        // push from the server DataChannel easily. In WS mode, the server
        // pushes clipboard updates directly, so no polling needed.
        const needsPolling = this.mode === 'webrtc'
            && (this.clipboardMode === 'guest_to_host' || this.clipboardMode === 'bidirectional');
        if (needsPolling) {
            this._startClipboardPolling();
        } else {
            this._stopClipboardPolling();
        }
    }

    _startClipboardPolling() {
        this._stopClipboardPolling();
        if (!this.containerApiUrl) return;
        this._clipboardPollTimer = setInterval(async () => {
            try {
                const resp = await fetch(`${this.containerApiUrl}/clipboard/get`);
                const data = await resp.json();
                if (data.ok && data.text && data.text !== this._lastReceivedClipboard) {
                    this._lastReceivedClipboard = data.text;
                    this._writeToHostClipboard(data.text);
                }
            } catch (e) { /* ignore polling errors */ }
        }, 1000);
    }

    _stopClipboardPolling() {
        if (this._clipboardPollTimer) {
            clearInterval(this._clipboardPollTimer);
            this._clipboardPollTimer = null;
        }
    }

    // ---------------------------------------------------------------
    // Send helper — routes to DataChannel (WebRTC) or WebSocket
    // ---------------------------------------------------------------

    _send(data) {
        const msg = JSON.stringify(data);
        if (this.mode === 'webrtc' && this.dataChannel && this.dataChannel.readyState === 'open') {
            this.dataChannel.send(msg);
        } else if (this.mode === 'ws' && this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(msg);
        }
    }

    // ---------------------------------------------------------------
    // Key mapping (browser key names → xdotool key names)
    // ---------------------------------------------------------------

    _mapSpecialKey(browserKey) {
        const map = {
            'Enter': 'Return',
            'Backspace': 'BackSpace',
            'Tab': 'Tab',
            'Escape': 'Escape',
            'Delete': 'Delete',
            'Insert': 'Insert',
            'ArrowUp': 'Up',
            'ArrowDown': 'Down',
            'ArrowLeft': 'Left',
            'ArrowRight': 'Right',
            'Home': 'Home',
            'End': 'End',
            'PageUp': 'Prior',
            'PageDown': 'Next',
            ' ': 'space',
            'F1': 'F1', 'F2': 'F2', 'F3': 'F3', 'F4': 'F4',
            'F5': 'F5', 'F6': 'F6', 'F7': 'F7', 'F8': 'F8',
            'F9': 'F9', 'F10': 'F10', 'F11': 'F11', 'F12': 'F12',
            'Shift': 'shift',
            'Control': 'ctrl',
            'Alt': 'alt',
            'Meta': 'super',
        };
        return map[browserKey] || null;
    }
}
