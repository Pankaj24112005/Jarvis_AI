/**
 * JARVIS Cybernetic Arc Reactor & HUD Telemetry Controller (Phase 5)
 * 60 FPS Procedural Canvas Animation Engine & WebSocket Client
 */

// State color definitions (RGB tuples for smooth LERP interpolation)
const STATE_THEMES = {
    IDLE: { hex: "#00f0ff", r: 0, g: 240, b: 255, sub: "STANDBY" },
    LISTENING: { hex: "#0099ff", r: 0, g: 153, b: 255, sub: "MIC ACTIVE // CAPTURING" },
    THINKING: { hex: "#ffb700", r: 255, g: 183, b: 0, sub: "REASONING // GENERATING" },
    SPEAKING: { hex: "#00ff88", r: 0, g: 255, b: 136, sub: "STREAMING AUDIO // 24kHz" },
    TOOL_EXECUTION: { hex: "#d900ff", r: 217, g: 0, b: 255, sub: "TOOL PIPELINE ACTIVE" },
    WAITING_FOR_PERMISSION: { hex: "#ff2a4b", r: 255, g: 42, b: 75, sub: "SECURITY GATE // CONFIRM" },
    INTERRUPTED: { hex: "#0044ff", r: 0, g: 68, b: 255, sub: "BARGE-IN CUTOFF" },
    RECONNECTING: { hex: "#ff7700", r: 255, g: 119, b: 0, sub: "RESTORING CONNECTION" },
    ERROR: { hex: "#ff0033", r: 255, g: 0, b: 51, sub: "FAULT OCCURRED" },
};

class JarvisHUD {
    constructor() {
        this.currentState = "IDLE";
        this.targetColor = STATE_THEMES.IDLE;
        this.currentColor = { r: 0, g: 240, b: 255 };
        this.audioEnergy = 0.0;
        this.currentTool = null;
        this.pendingPermission = null;

        this.canvas = document.getElementById("reactorCanvas");
        this.ctx = this.canvas.getContext("2d");

        // Rotation angles
        this.angleOuter = 0;
        this.angleMid = 0;
        this.angleInner = 0;
        this.shockwaveRadius = 0;

        // Particle field
        this.particles = [];
        this.initParticles(80);

        // Elements
        this.statePill = document.getElementById("statePill");
        this.stateText = document.getElementById("stateText");
        this.stateDot = document.getElementById("stateDot");
        this.connBadge = document.getElementById("connBadge");
        this.connText = document.getElementById("connText");
        this.clockText = document.getElementById("clockText");
        this.valState = document.getElementById("valState");
        this.valVoice = document.getElementById("valVoice");
        this.valPtt = document.getElementById("valPtt");
        this.valSpeaking = document.getElementById("valSpeaking");
        this.energyFill = document.getElementById("energyFill");
        this.coreStatus = document.getElementById("coreStatus");
        this.coreSub = document.getElementById("coreSub");
        this.radarEmpty = document.getElementById("radarEmpty");
        this.radarActive = document.getElementById("radarActive");
        this.toolNameEl = document.getElementById("toolName");
        this.toolStatusBadge = document.getElementById("toolStatusBadge");
        this.toolArgsPre = document.getElementById("toolArgsPre");
        this.logStream = document.getElementById("logStream");
        this.footerMessage = document.getElementById("footerMessage");

        // Modal
        this.permissionModal = document.getElementById("permissionModal");
        this.permToolName = document.getElementById("permToolName");
        this.permLevel = document.getElementById("permLevel");
        this.permDescription = document.getElementById("permDescription");
        this.permArgsPre = document.getElementById("permArgsPre");
        this.btnAllow = document.getElementById("btnAllow");
        this.btnDeny = document.getElementById("btnDeny");

        this.initEventListeners();
        this.startClock();
        this.connectWebSocket();
        this.renderLoop();
    }

    initParticles(count) {
        this.particles = [];
        for (let i = 0; i < count; i++) {
            this.particles.push({
                dist: 40 + Math.random() * 180,
                angle: Math.random() * Math.PI * 2,
                speed: (0.002 + Math.random() * 0.008) * (Math.random() > 0.5 ? 1 : -1),
                size: 1 + Math.random() * 2,
                alpha: 0.2 + Math.random() * 0.6,
            });
        }
    }

    initEventListeners() {
        this.btnAllow.addEventListener("click", () => this.submitPermission(true));
        this.btnDeny.addEventListener("click", () => this.submitPermission(false));

        window.addEventListener("keydown", (e) => {
            if (this.pendingPermission && !this.permissionModal.classList.contains("hidden")) {
                if (e.key === "Escape") this.submitPermission(false);
                if (e.key === "Enter") this.submitPermission(true);
            }
        });
    }

    startClock() {
        const updateClock = () => {
            const d = new Date();
            const pad = (n) => String(n).padStart(2, "0");
            this.clockText.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        };
        updateClock();
        setInterval(updateClock, 1000);
    }

    connectWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.connBadge.classList.add("connected");
            this.connText.textContent = "CONNECTED";
            this.addLog("WebSocket telemetry stream connected.", "sys");
        };

        this.ws.onmessage = (event) => {
            try {
                const packet = JSON.parse(event.data);
                this.handleTelemetryPacket(packet);
            } catch (err) {
                console.error("Error parsing telemetry frame:", err);
            }
        };

        this.ws.onclose = () => {
            this.connBadge.classList.remove("connected");
            this.connText.textContent = "DISCONNECTED";
            setTimeout(() => this.connectWebSocket(), 1500);
        };

        this.ws.onerror = (err) => {
            console.debug("WebSocket error:", err);
        };
    }

    handleTelemetryPacket(packet) {
        const type = packet.type;
        const data = packet.data || {};

        switch (type) {
            case "snapshot":
                this.hydrateSnapshot(data);
                break;
            case "state_change":
                this.setAgentState(data.new_state, data.reason);
                break;
            case "audio_energy":
                this.setAudioEnergy(data.energy || 0);
                break;
            case "speech_activity":
                if (data.ptt_pressed !== undefined) {
                    this.valPtt.textContent = data.ptt_pressed ? "HELD" : "RELEASED";
                    this.valPtt.className = data.ptt_pressed ? "metric-value highlight" : "metric-value";
                }
                if (data.is_speaking !== undefined) {
                    this.valSpeaking.textContent = data.is_speaking ? "ACTIVE" : "INACTIVE";
                    this.valSpeaking.className = data.is_speaking ? "metric-value highlight" : "metric-value";
                }
                break;
            case "tool_activity":
                this.handleToolActivity(data);
                break;
            case "permission_alert":
                this.handlePermissionAlert(data);
                break;
            case "system_error":
                this.addLog(`[ERROR] ${data.error}`, "alert");
                break;
        }
    }

    hydrateSnapshot(snap) {
        if (snap.agent_state) this.setAgentState(snap.agent_state);
        if (snap.voice_name) this.valVoice.textContent = snap.voice_name;
        if (snap.ptt_pressed !== undefined) {
            this.valPtt.textContent = snap.ptt_pressed ? "HELD" : "RELEASED";
        }
        if (snap.is_speaking !== undefined) {
            this.valSpeaking.textContent = snap.is_speaking ? "ACTIVE" : "INACTIVE";
        }
        if (snap.pending_permission) {
            this.handlePermissionAlert(snap.pending_permission);
        }
    }

    setAgentState(state, reason = "") {
        if (!STATE_THEMES[state]) return;
        this.currentState = state;
        this.targetColor = STATE_THEMES[state];

        // Update Theme in DOM
        document.documentElement.style.setProperty("--accent-glow", this.targetColor.hex);
        document.documentElement.style.setProperty(
            "--accent-glow-rgb",
            `${this.targetColor.r}, ${this.targetColor.g}, ${this.targetColor.b}`
        );

        this.stateText.textContent = state;
        this.valState.textContent = state;
        this.coreStatus.textContent = state;
        this.coreSub.textContent = this.targetColor.sub;
        this.footerMessage.textContent = reason ? `STATE TRANSITION: ${state} (${reason})` : `SYSTEM STATE: ${state}`;

        if (state === "INTERRUPTED") {
            this.shockwaveRadius = 20;
            this.addLog(`[INTERRUPT] Barge-in registered. Audio playback halted.`, "alert");
        } else {
            this.addLog(`State changed -> ${state}${reason ? ` (${reason})` : ""}`, "state");
        }

        if (state === "IDLE") {
            this.setAudioEnergy(0);
            this.valSpeaking.textContent = "INACTIVE";
            this.valSpeaking.className = "metric-value";
            this.radarEmpty.classList.remove("hidden");
            this.radarActive.classList.add("hidden");
        }
    }

    setAudioEnergy(val) {
        this.audioEnergy = Math.max(0, Math.min(1.0, val));
        this.energyFill.style.width = `${Math.round(this.audioEnergy * 100)}%`;
    }

    handleToolActivity(data) {
        const tool = data.tool;
        const status = data.status;

        if (status === "REQUESTED") {
            this.radarEmpty.classList.add("hidden");
            this.radarActive.classList.remove("hidden");
            this.toolNameEl.textContent = tool;
            this.toolStatusBadge.textContent = "REQUESTED";
            this.toolStatusBadge.style.color = "#eab308";
            this.toolArgsPre.textContent = JSON.stringify(data.arguments || {}, null, 2);
            this.addLog(`[TOOL REQUESTED] ${tool}`, "tool");
        } else if (status === "EXECUTED") {
            this.toolStatusBadge.textContent = "EXECUTED";
            this.toolStatusBadge.style.color = "#10b981";
            this.addLog(`[TOOL EXECUTED] ${tool}`, "tool");
        } else if (status === "FAILED") {
            this.toolStatusBadge.textContent = "FAILED";
            this.toolStatusBadge.style.color = "#ef4444";
            this.addLog(`[TOOL FAILED] ${tool}: ${data.error || ""}`, "alert");
        }
    }

    handlePermissionAlert(data) {
        if (data.status === "GRANTED" || data.status === "DENIED") {
            this.permissionModal.classList.add("hidden");
            this.pendingPermission = null;
            return;
        }

        this.pendingPermission = data;
        this.permToolName.textContent = data.tool || "Action";
        this.permLevel.textContent = `LEVEL ${data.level || 3} (MANDATORY APPROVAL)`;
        this.permDescription.textContent = data.description || "Authorization requested by JARVIS.";
        this.permArgsPre.textContent = JSON.stringify(data.arguments || {}, null, 2);
        this.permissionModal.classList.remove("hidden");
        this.addLog(`[SECURITY ALERT] Confirmation required for ${data.tool}`, "alert");
    }

    async submitPermission(approved) {
        if (!this.pendingPermission) return;
        const reqId = this.pendingPermission.request_id;
        this.permissionModal.classList.add("hidden");

        try {
            const resp = await fetch(`/api/permission/${reqId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approved: approved }),
            });
            const res = await resp.json();
            this.addLog(`[SECURITY] Permission ${approved ? "APPROVED" : "DENIED"} by user.`, approved ? "sys" : "alert");
        } catch (err) {
            console.error("Failed to submit permission decision:", err);
        }
        this.pendingPermission = null;
    }

    addLog(msg, type = "sys") {
        const entry = document.createElement("div");
        entry.className = `log-entry ${type}`;
        const time = new Date().toLocaleTimeString();
        entry.textContent = `[${time}] ${msg}`;
        this.logStream.appendChild(entry);
        this.logStream.scrollTop = this.logStream.scrollHeight;
    }

    renderLoop() {
        requestAnimationFrame(() => this.renderLoop());

        // LERP Color Transition
        this.currentColor.r += (this.targetColor.r - this.currentColor.r) * 0.08;
        this.currentColor.g += (this.targetColor.g - this.currentColor.g) * 0.08;
        this.currentColor.b += (this.targetColor.b - this.currentColor.b) * 0.08;

        const colorStr = `rgb(${Math.round(this.currentColor.r)}, ${Math.round(this.currentColor.g)}, ${Math.round(this.currentColor.b)})`;
        const glowColor = `rgba(${Math.round(this.currentColor.r)}, ${Math.round(this.currentColor.g)}, ${Math.round(this.currentColor.b)}, 0.45)`;

        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        const cx = w / 2;
        const cy = h / 2;

        ctx.clearRect(0, 0, w, h);

        // Rotation speed depends on state
        const speedMult = this.currentState === "THINKING" ? 4.5 : (this.currentState === "LISTENING" ? 2.0 : 1.0);
        this.angleOuter += 0.005 * speedMult;
        this.angleMid -= 0.008 * speedMult;
        this.angleInner += 0.012 * speedMult;

        // Dynamic radius modulated by audio energy
        const energyPulse = this.audioEnergy * 24;

        // 1. Particle Field
        for (const p of this.particles) {
            p.angle += p.speed * speedMult;
            const px = cx + Math.cos(p.angle) * p.dist;
            const py = cy + Math.sin(p.angle) * p.dist;

            ctx.beginPath();
            ctx.arc(px, py, p.size, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${Math.round(this.currentColor.r)}, ${Math.round(this.currentColor.g)}, ${Math.round(this.currentColor.b)}, ${p.alpha})`;
            ctx.fill();
        }

        // 2. Shockwave (Interrupted state)
        if (this.shockwaveRadius > 0) {
            ctx.beginPath();
            ctx.arc(cx, cy, this.shockwaveRadius, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(${Math.round(this.currentColor.r)}, ${Math.round(this.currentColor.g)}, ${Math.round(this.currentColor.b)}, ${(240 - this.shockwaveRadius) / 240})`;
            ctx.lineWidth = 4;
            ctx.stroke();
            this.shockwaveRadius += 6;
            if (this.shockwaveRadius > 240) this.shockwaveRadius = 0;
        }

        // 3. Outer Notched Ring (r = 230)
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(this.angleOuter);
        ctx.strokeStyle = colorStr;
        ctx.lineWidth = 1.5;
        ctx.shadowColor = glowColor;
        ctx.shadowBlur = 12;

        ctx.beginPath();
        ctx.arc(0, 0, 230 + energyPulse * 0.2, 0, Math.PI * 2);
        ctx.stroke();

        // Outer ticks
        const ticks = 36;
        for (let i = 0; i < ticks; i++) {
            const a = (i / ticks) * Math.PI * 2;
            const len = i % 3 === 0 ? 10 : 4;
            ctx.beginPath();
            ctx.moveTo(Math.cos(a) * (230 + energyPulse * 0.2), Math.sin(a) * (230 + energyPulse * 0.2));
            ctx.lineTo(Math.cos(a) * (230 - len + energyPulse * 0.2), Math.sin(a) * (230 - len + energyPulse * 0.2));
            ctx.stroke();
        }
        ctx.restore();

        // 4. Middle Segmented Ring (r = 180)
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(this.angleMid);
        ctx.shadowColor = glowColor;
        ctx.shadowBlur = 14;

        const segments = 12;
        const segAngle = (Math.PI * 2) / segments;
        for (let i = 0; i < segments; i++) {
            if (i % 2 === 0) {
                ctx.beginPath();
                ctx.arc(0, 0, 180 + energyPulse * 0.4, i * segAngle, i * segAngle + segAngle * 0.7);
                ctx.strokeStyle = colorStr;
                ctx.lineWidth = 3.5;
                ctx.stroke();
            }
        }
        ctx.restore();

        // 5. Inner Orbit Ring (r = 130)
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(this.angleInner);
        ctx.shadowColor = glowColor;
        ctx.shadowBlur = 16;

        ctx.beginPath();
        ctx.arc(0, 0, 130 + energyPulse * 0.6, 0, Math.PI * 1.6);
        ctx.strokeStyle = colorStr;
        ctx.lineWidth = 2.5;
        ctx.stroke();
        ctx.restore();

        // 6. Central Arc Reactor Core
        const coreRadius = 70 + energyPulse;
        const grad = ctx.createRadialGradient(cx, cy, 10, cx, cy, coreRadius);
        grad.addColorStop(0, "rgba(255, 255, 255, 0.95)");
        grad.addColorStop(0.3, colorStr);
        grad.addColorStop(1, "rgba(0, 0, 0, 0.2)");

        ctx.beginPath();
        ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.shadowColor = colorStr;
        ctx.shadowBlur = 28 + energyPulse * 1.5;
        ctx.fill();

        // Core Inner Geometry
        ctx.beginPath();
        ctx.arc(cx, cy, 35, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(255, 255, 255, 0.7)";
        ctx.lineWidth = 2;
        ctx.stroke();
    }
}

// Instantiate on DOM load
window.addEventListener("DOMContentLoaded", () => {
    window.jarvisHUD = new JarvisHUD();
});
