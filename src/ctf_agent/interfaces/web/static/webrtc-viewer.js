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
                console.log('Desktop viewer: WebSocket connected to', wsUrl);
                // Hide video element, show frame canvas for WS rendering
                this.video.style.display = 'none';
                this._frameCanvas.style.display = 'block';
            };

            this.ws.onmessage = (event) => {
                if (event.data instanceof Blob) {
                    this._renderFrame(event.data);
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
            e.preventDefault();

            if (e.ctrlKey || e.altKey || e.metaKey) {
                const keys = [];
                if (e.ctrlKey) keys.push('ctrl');
                if (e.altKey) keys.push('alt');
                if (e.shiftKey) keys.push('shift');
                if (e.metaKey) keys.push('super');
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

        // --- Clipboard paste ---
        canvas.addEventListener('paste', (e) => {
            const text = (e.clipboardData || window.clipboardData).getData('text');
            if (text) {
                this._send({ type: 'clipboard', action: 'set', text });
                this._send({ type: 'key', action: 'key_combo', keys: ['ctrl', 'v'] });
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

        const x = Math.round((mouseEvent.clientX - rect.left - offsetX) * this.desktopWidth / renderedW);
        const y = Math.round((mouseEvent.clientY - rect.top - offsetY) * this.desktopHeight / renderedH);

        // Clamp to valid desktop range
        return {
            x: Math.max(0, Math.min(this.desktopWidth - 1, x)),
            y: Math.max(0, Math.min(this.desktopHeight - 1, y)),
        };
    }

    _sendMouse(action, mouseEvent) {
        const coords = this._getCoords(mouseEvent);
        this._send({ type: 'mouse', action, x: coords.x, y: coords.y });
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
