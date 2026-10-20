/**
 * Shadow Voice Autonomous Studio — Application Controller
 * ========================================================
 * Complete client-side engine matching LinkedIn Nexus & FP Nexus Agents:
 * - Live Web Phone & WebSocket Audio Stream
 * - Real-time Waveform Canvas Visualizer
 * - Instruction Studio & Section 7.1 Human Quality Auditor
 * - Cognitive Brain & Customer Question Learning Approvals
 * - Pluggable Dialers & CTI Hub (VICIdial, Asterisk, CPaaS, Web Phone)
 * - Agent Reach Eyes (URL Scanner & Brain Digest)
 * - Transcripts, Latency Metrics & Chart.js Visualizations
 */

let activeCallSessionId = null;
let webphoneSocket = null;
let isMuted = false;
let animFrameId = null;
let currentPendingQuestionId = null;
let lastReachAnalysis = null;
let chartDispositions = null;
let chartLatency = null;

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    const port = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
    const gwLabel = document.getElementById("gateway-status-label");
    if (gwLabel) {
        gwLabel.textContent = `Gateway Active (:${port})`;
    }

    lucide.createIcons();
    loadInstructions();
    loadVoiceProfiles();
    loadCustomerQuestions();
    loadBrainStats();
    loadStoryBank();
    loadDialers();
    loadCallHistory();
    loadAnalytics();
    loadSettings();
    initWaveformIdle();
});

// =========================================================================
// 1. NAVIGATION & TAB SWITCHING
// =========================================================================
function switchTab(tabId) {
    document.querySelectorAll(".tab-pane").forEach(el => el.classList.add("hidden"));
    const target = document.getElementById(tabId);
    if (target) target.classList.remove("hidden");

    document.querySelectorAll("#nav-tabs .nav-item").forEach(btn => {
        if (btn.getAttribute("data-tab") === tabId) {
            btn.className = "nav-item w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition text-white bg-brand-600/20 border border-brand-500/30";
            const icon = btn.querySelector("i");
            if (icon) icon.className = "w-4 h-4 text-brand-400";
        } else {
            btn.className = "nav-item w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition text-slate-400 hover:text-slate-200 hover:bg-dark-800";
            const icon = btn.querySelector("i");
            if (icon) icon.className = "w-4 h-4 text-slate-400";
        }
    });

    if (tabId === "tab-analytics") {
        setTimeout(renderAnalyticsCharts, 100);
    }
    if (tabId === "tab-voices") {
        loadVoiceProfiles();
    }
    if (tabId === "tab-dialers") {
        loadDialers();
        loadSoftphones();
    }

    lucide.createIcons();
}

// =========================================================================
// 2. LIVE WEB PHONE & SOFTPHONE CONSOLE
// =========================================================================
function initWaveformIdle() {
    const canvas = document.getElementById("waveform-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let step = 0;

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = activeCallSessionId ? "#818cf8" : "#374151";
        ctx.lineWidth = 2;
        ctx.beginPath();

        const amplitude = activeCallSessionId ? 25 : 4;
        const freq = activeCallSessionId ? 0.08 : 0.02;

        for (let x = 0; x < canvas.width; x++) {
            const y = (canvas.height / 2) + Math.sin((x * freq) + step) * amplitude * Math.cos(x * 0.01);
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        step += 0.05;
        animFrameId = requestAnimationFrame(draw);
    }
    draw();
}

async function startWebPhoneCall() {
    const phone = document.getElementById("phone-input").value.trim() || "+1 (555) 019-2834";
    const btnStart = document.getElementById("btn-start-call");
    const btnEnd = document.getElementById("btn-end-call");
    const badge = document.getElementById("call-state-badge");
    const feed = document.getElementById("transcript-feed");

    try {
        const resp = await fetch("/api/calls/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone_number: phone })
        });
        const data = await resp.json();

        activeCallSessionId = data.session_id;
        badge.textContent = "CONNECTED (CALLING)";
        badge.className = "px-3 py-1 rounded-full text-xs font-mono font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse";

        btnStart.disabled = true;
        btnStart.className = "flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-dark-800 text-slate-500 text-sm font-medium cursor-not-allowed";

        btnEnd.disabled = false;
        btnEnd.className = "flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-medium text-sm transition shadow-lg shadow-rose-600/20";

        document.getElementById("btn-transfer-warm").disabled = false;
        document.getElementById("btn-transfer-blind").disabled = false;
        document.getElementById("audio-status-label").textContent = `Call connected with ${phone}. Live streaming active.`;

        // Render initial greeting
        feed.innerHTML = "";
        appendTranscript("agent", data.greeting.text, data.greeting.latency, data.greeting.audio_url, data.greeting.voice_name);
        updateLatencyDisplay(data.greeting.latency);

    } catch (err) {
        alert("Failed to start softphone call: " + err.message);
    }
}

async function endWebPhoneCall(dispo = "CALLBK") {
    if (!activeCallSessionId) return;

    try {
        await fetch("/api/calls/end", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: activeCallSessionId, disposition: dispo })
        });
    } catch (e) {}

    resetCallState();
    loadCallHistory();
    loadBrainStats();
    loadCustomerQuestions();
}

function resetCallState() {
    activeCallSessionId = null;
    const btnStart = document.getElementById("btn-start-call");
    const btnEnd = document.getElementById("btn-end-call");
    const badge = document.getElementById("call-state-badge");

    badge.textContent = "STANDBY";
    badge.className = "px-3 py-1 rounded-full text-xs font-mono font-medium bg-slate-800 text-slate-400 border border-slate-700";

    btnStart.disabled = false;
    btnStart.className = "flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-sm transition shadow-lg shadow-emerald-600/20";

    btnEnd.disabled = true;
    btnEnd.className = "flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-rose-600/30 border border-rose-500/30 text-rose-300 font-medium text-sm transition opacity-50 cursor-not-allowed";

    document.getElementById("btn-transfer-warm").disabled = true;
    document.getElementById("btn-transfer-blind").disabled = true;
    document.getElementById("audio-status-label").textContent = "Microphone ready. Start call to begin voice loop.";
    document.getElementById("fsm-stage-pill").textContent = "COMPLETED";
}

function toggleMute() {
    isMuted = !isMuted;
    const btn = document.getElementById("btn-mute");
    if (isMuted) {
        btn.classList.add("bg-rose-500/20", "text-rose-400", "border-rose-500/30");
        document.getElementById("audio-status-label").textContent = "Muted (Ingress audio disabled).";
    } else {
        btn.classList.remove("bg-rose-500/20", "text-rose-400", "border-rose-500/30");
        document.getElementById("audio-status-label").textContent = "Microphone unmuted.";
    }
}

async function sendCallerUtterance(event) {
    if (event) event.preventDefault();
    const input = document.getElementById("caller-input");
    const text = input.value.trim();
    if (!text) return;

    if (!activeCallSessionId) {
        await startWebPhoneCall();
    }

    appendTranscript("caller", text);
    input.value = "";

    try {
        const resp = await fetch("/api/calls/turn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: activeCallSessionId, user_text: text })
        });
        const data = await resp.json();

        appendTranscript("agent", data.text, data.latency, data.audio_url, data.voice_name);
        updateLatencyDisplay(data.latency);
        document.getElementById("fsm-stage-pill").textContent = data.stage || "IN_PROGRESS";

        if (data.action === "DNC" || data.action === "TRANSFER_WARM" || data.action === "HANGUP") {
            setTimeout(() => {
                resetCallState();
                loadCallHistory();
                loadBrainStats();
                loadCustomerQuestions();
            }, 1500);
        }
    } catch (err) {
        console.error(err);
    }
}

function quickTestCaller(text) {
    document.getElementById("caller-input").value = text;
    sendCallerUtterance();
}

let currentAgentAudio = null;

function playAgentClonedAudio(audioUrl, textFallback) {
    if (isMuted) return;
    if (currentAgentAudio) {
        try {
            currentAgentAudio.pause();
            currentAgentAudio = null;
        } catch (e) {}
    }
    if ('speechSynthesis' in window) {
        try { window.speechSynthesis.cancel(); } catch (e) {}
    }
    if (audioUrl) {
        try {
            currentAgentAudio = new Audio(audioUrl);
            currentAgentAudio.play().catch(e => {
                console.log("Audio play error, falling back to speech synth:", e);
                speakAgentVoice(textFallback);
            });
            return;
        } catch (e) {
            console.warn("Failed to play cloned audio URL:", e);
        }
    }
    speakAgentVoice(textFallback);
}

function appendTranscript(speaker, text, latency, audioUrl = null, voiceName = null) {
    const feed = document.getElementById("transcript-feed");
    const div = document.createElement("div");

    if (speaker === "agent") {
        const vName = voiceName || (activeVoiceProfile ? activeVoiceProfile.name : "Jordan (Voice Agent)");
        div.className = "p-3.5 rounded-xl bg-dark-800/80 border border-dark-700/80 space-y-1.5 shadow-sm";
        div.innerHTML = `
            <div class="flex items-center justify-between text-[11px]">
                <span class="font-bold text-indigo-400 flex items-center gap-1.5">
                    <span class="w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
                    ${vName}
                </span>
                <span class="font-mono text-emerald-400">${latency ? latency.total_ms + ' ms' : ''}</span>
            </div>
            <p class="text-sm text-slate-100">${text}</p>
            ${audioUrl ? `
                <div class="pt-1.5 flex items-center gap-2">
                    <audio controls src="${audioUrl}" class="h-6 w-52 opacity-90"></audio>
                    <span class="text-[10px] text-slate-500 font-mono">16kHz Cloned</span>
                </div>
            ` : ''}
        `;
        playAgentClonedAudio(audioUrl, text);
    } else {
        div.className = "p-3.5 rounded-xl bg-dark-950 border border-dark-800 space-y-1 shadow-sm";
        div.innerHTML = `
            <div class="text-[11px] font-bold text-slate-400 flex items-center gap-1.5">
                <span class="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
                Caller (Prospect)
            </div>
            <p class="text-sm text-slate-200">${text}</p>
        `;
    }

    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;
}

// ---- VOICE GENERATION (Text-to-Speech) ----
function speakAgentVoice(text) {
    if (!('speechSynthesis' in window)) return;
    try {
        window.speechSynthesis.cancel(); // Flush previous buffer (instant barge-in support)
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.05; // Human cadence
        utterance.pitch = 1.0;
        const voices = window.speechSynthesis.getVoices();
        const naturalVoice = voices.find(v => v.lang.startsWith("en") && (v.name.includes("Natural") || v.name.includes("Online") || v.name.includes("Guy") || v.name.includes("David") || v.name.includes("Google")));
        if (naturalVoice) utterance.voice = naturalVoice;
        window.speechSynthesis.speak(utterance);
    } catch (e) {
        console.error("SpeechSynthesis error:", e);
    }
}

// ---- VOICE RECOGNITION (Microphone Speech-to-Text) ----
let recognition = null;
let isRecordingMic = false;

function toggleMicRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert("Speech recognition is not supported natively in this browser version. You can type directly in the message box below.");
        return;
    }

    if (isRecordingMic && recognition) {
        recognition.stop();
        isRecordingMic = false;
        const btn = document.getElementById("btn-voice-mic");
        if (btn) btn.classList.remove("bg-rose-500", "animate-pulse");
        document.getElementById("audio-status-label").textContent = "Microphone listening stopped.";
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onstart = () => {
        isRecordingMic = true;
        const btn = document.getElementById("btn-voice-mic");
        if (btn) btn.classList.add("bg-rose-500", "animate-pulse");
        document.getElementById("audio-status-label").textContent = "Listening to your voice... Speak clearly into microphone!";
    };

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        document.getElementById("caller-input").value = transcript;
        sendCallerUtterance();
    };

    recognition.onerror = (e) => {
        console.error("SpeechRecognition error:", e);
        isRecordingMic = false;
        const btn = document.getElementById("btn-voice-mic");
        if (btn) btn.classList.remove("bg-rose-500", "animate-pulse");
        document.getElementById("audio-status-label").textContent = "Microphone ready. Start call to begin voice loop.";
    };

    recognition.onend = () => {
        isRecordingMic = false;
        const btn = document.getElementById("btn-voice-mic");
        if (btn) btn.classList.remove("bg-rose-500", "animate-pulse");
    };

    recognition.start();
}

function playRecording(audioUrl) {
    if (!audioUrl) return;
    const audio = new Audio(audioUrl);
    audio.play().catch(e => console.error("Audio playback error:", e));
}


function updateLatencyDisplay(lat) {
    if (!lat) return;
    document.getElementById("latency-stt").textContent = `${lat.stt_ms || 0} ms`;
    document.getElementById("latency-llm").textContent = `${lat.llm_ttft_ms || 0} ms`;
    document.getElementById("latency-tts").textContent = `${lat.tts_ms || 0} ms`;
    document.getElementById("latency-total").textContent = `${lat.total_ms || 0} ms`;
    document.getElementById("header-p95").textContent = `${lat.total_ms || 540} ms`;
}

async function triggerTransfer(type = "WARM") {
    if (!activeCallSessionId) return;
    try {
        const resp = await fetch("/api/calls/transfer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: activeCallSessionId,
                target_extension: "8300",
                transfer_type: type
            })
        });
        const data = await resp.json();
        alert(data.message);
        resetCallState();
        loadCallHistory();
    } catch (e) {
        alert("Transfer failed: " + e.message);
    }
}

async function applyDisposition() {
    const dispo = document.getElementById("select-disposition").value;
    if (activeCallSessionId) {
        await endWebPhoneCall(dispo);
    }
}

// =========================================================================
// 3. INSTRUCTION STUDIO & SECTION 7.1 AUDITOR
// =========================================================================
async function loadInstructions() {
    try {
        const resp = await fetch("/api/instructions/");
        const data = await resp.json();

        document.getElementById("inst-agent-name").value = data.agent_name || "Jordan";
        document.getElementById("inst-company-name").value = data.company_name || "Shadow Voice";
        document.getElementById("inst-opening-greeting").value = data.opening_greeting || "";
        document.getElementById("inst-primary").value = data.primary_instructions || "";
        document.getElementById("inst-tone").value = data.tone || "";
        document.getElementById("inst-pricing").value = (data.approved_pricing || []).join(", ");
        document.getElementById("inst-transfer-ext").value = data.transfer_ext || "8300";

        auditGreetingLive();
    } catch (e) {
        console.error(e);
    }
}

async function auditGreetingLive() {
    const text = document.getElementById("inst-opening-greeting").value;
    const badge = document.getElementById("opening-audit-badge");
    const warning = document.getElementById("opening-warning");

    try {
        const resp = await fetch("/api/instructions/audit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text })
        });
        const data = await resp.json();

        if (data.is_natural && !data.has_banned_ai_disclosure) {
            badge.textContent = "100% NATURAL";
            badge.className = "px-2 py-0.5 text-[10px] font-semibold rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
            warning.classList.add("hidden");
        } else {
            badge.textContent = "VIOLATION DETECTED";
            badge.className = "px-2 py-0.5 text-[10px] font-semibold rounded bg-rose-500/20 text-rose-400 border border-rose-500/30";
            warning.textContent = data.violations.join(" | ");
            warning.classList.remove("hidden");
        }
    } catch (e) {}
}

async function saveInstructions() {
    const payload = {
        campaign_id: "DEFAULT_SALES_V1",
        agent_name: document.getElementById("inst-agent-name").value.trim(),
        company_name: document.getElementById("inst-company-name").value.trim(),
        industry: "Telephony Automation",
        opening_greeting: document.getElementById("inst-opening-greeting").value.trim(),
        primary_instructions: document.getElementById("inst-primary").value.trim(),
        tone: document.getElementById("inst-tone").value.trim(),
        approved_pricing: document.getElementById("inst-pricing").value.split(",").map(s => s.trim()).filter(Boolean),
        qualification_criteria: ["Decision maker", "Call volume > 5,000 mins/mo"],
        forbidden_phrases: ["I am an AI", "automated calling", "virtual assistant"],
        transfer_ext: document.getElementById("inst-transfer-ext").value.trim()
    };

    try {
        const resp = await fetch("/api/instructions/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (resp.ok) {
            alert("✓ Instructions saved and compiled into Cognitive Brain!");
        } else {
            alert("Save failed: " + (res.detail || "Error"));
        }
    } catch (e) {
        alert("Save failed: " + e.message);
    }
}

async function runSimulation(event) {
    if (event) event.preventDefault();
    const input = document.getElementById("sim-prompt-input");
    const userMessage = input.value.trim();
    if (!userMessage) return;

    const box = document.getElementById("sim-chat-box");
    box.innerHTML += `
        <div class="p-2.5 rounded-lg bg-dark-950 border border-dark-800 text-xs text-slate-200">
            <b>User:</b> ${userMessage}
        </div>
    `;
    input.value = "";

    try {
        const resp = await fetch("/api/instructions/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_message: userMessage })
        });
        const data = await resp.json();
        box.innerHTML += `
            <div class="p-2.5 rounded-lg bg-dark-800/80 border border-dark-700 text-xs text-indigo-300">
                <b>Agent:</b> ${data.text}
                <div class="text-[10px] text-slate-500 mt-1">Stage: ${data.stage} | Action: ${data.action}</div>
            </div>
        `;
        box.scrollTop = box.scrollHeight;
    } catch (e) {
        console.error(e);
    }
}

function clearSimChat() {
    document.getElementById("sim-chat-box").innerHTML = `
        <div class="p-3 rounded-xl bg-dark-800/40 border border-dark-800 text-xs text-slate-400">
            Send any test prompt or question to verify how the agent responds.
        </div>
    `;
}

// =========================================================================
// 4. COGNITIVE BRAIN & CUSTOMER LEARNING BANK
// =========================================================================
async function loadBrainStats() {
    try {
        const resp = await fetch("/api/brain/stats");
        const data = await resp.json();
        document.getElementById("stat-total-q").textContent = data.total_learned_questions;
        document.getElementById("stat-pending-q").textContent = data.pending_review_count;
        document.getElementById("stat-approved-q").textContent = data.approved_count;
        document.getElementById("stat-receipts").textContent = data.story_bank_receipts_count;

        const natEl = document.getElementById("evolution-nat-score");
        if (natEl) {
            natEl.firstElementChild.textContent = `${data.naturalness_score || 98.0}%`;
        }
        const roundsEl = document.getElementById("evolution-rounds-label");
        if (roundsEl) {
            roundsEl.textContent = `${data.evolution_rounds_count || 0} Rounds Done`;
        }
    } catch (e) {}
}

async function triggerAutonomousEvolution() {
    const btn = document.getElementById("btn-trigger-evolve");
    const originalText = btn.innerHTML;
    btn.innerHTML = `<span class="animate-spin inline-block mr-1">⟳</span> Reflecting & Evolving...`;
    btn.disabled = true;

    try {
        const resp = await fetch("/api/brain/evolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ limit_calls: 15, auto_approve: true })
        });
        const res = await resp.json();

        const insightsBox = document.getElementById("evolution-insights-text");
        if (insightsBox) {
            insightsBox.textContent = res.insights_summary || "Autonomous self-evolution complete.";
        }

        const natEl = document.getElementById("evolution-nat-score");
        if (natEl && res.naturalness_score) {
            natEl.firstElementChild.textContent = `${res.naturalness_score}%`;
        }

        await loadBrainStats();
        await loadCustomerQuestions();
        alert(`✓ Autonomous Evolution Complete!\n${res.insights_summary}`);
    } catch (e) {
        alert("Failed to run evolution: " + e.message);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
        lucide.createIcons();
    }
}

window.customerQuestionsMap = {};

async function loadCustomerQuestions() {
    const status = document.getElementById("filter-q-status").value;
    const tbody = document.getElementById("customer-questions-tbody");

    try {
        const resp = await fetch(`/api/brain/questions?status=${status}`);
        const list = await resp.json();

        if (!list || list.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-slate-500">No questions recorded in this filter.</td></tr>`;
            return;
        }

        window.customerQuestionsMap = {};
        tbody.innerHTML = list.map(q => {
            window.customerQuestionsMap[q.id] = q;
            return `
            <tr class="hover:bg-dark-800/50">
                <td class="py-3 px-3 font-medium text-white">${q.question_text}</td>
                <td class="py-3 px-3 font-mono text-brand-cyan">${q.frequency}x</td>
                <td class="py-3 px-3 uppercase text-[10px] text-slate-400">${q.category || 'general'}</td>
                <td class="py-3 px-3 text-slate-300 max-w-xs truncate">${q.approved_answer || q.proposed_answer || 'Pending user answer'}</td>
                <td class="py-3 px-3">
                    <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${q.status === 'approved' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'}">
                        ${q.status}
                    </span>
                </td>
                <td class="py-3 px-3 text-right space-x-1">
                    <button onclick="openApproveModal(${q.id})" class="px-2.5 py-1 bg-dark-800 hover:bg-dark-700 text-xs font-medium text-slate-200 border border-dark-700 rounded-lg">
                        ${q.status === 'approved' ? 'Edit' : 'Review & Approve'}
                    </button>
                    <button onclick="deleteQuestion(${q.id})" class="px-2 py-1 bg-dark-800 hover:bg-rose-500/20 text-xs font-medium text-rose-400 border border-dark-700 rounded-lg" title="Delete Question">
                        &times;
                    </button>
                </td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-rose-400">Failed to load questions.</td></tr>`;
    }
}

function openApproveModal(id) {
    const q = window.customerQuestionsMap[id];
    if (!q) return;
    currentPendingQuestionId = id;
    document.getElementById("modal-q-text").textContent = q.question_text;
    document.getElementById("modal-q-answer").value = q.approved_answer || q.proposed_answer || "";
    document.getElementById("modal-approve-q").classList.remove("hidden");
}

async function deleteQuestion(id) {
    if (!confirm("Are you sure you want to delete this learned question?")) return;
    try {
        const resp = await fetch(`/api/brain/questions/${id}`, { method: "DELETE" });
        if (resp.ok) {
            loadCustomerQuestions();
            loadBrainStats();
        } else {
            const err = await resp.json();
            alert("Delete failed: " + (err.detail || "Error"));
        }
    } catch (e) {
        alert("Delete failed: " + e.message);
    }
}

function closeApproveModal() {
    document.getElementById("modal-approve-q").classList.add("hidden");
    currentPendingQuestionId = null;
}

async function submitApproveQuestion() {
    if (!currentPendingQuestionId) return;
    const answer = document.getElementById("modal-q-answer").value.trim();
    if (!answer) {
        alert("Please provide an answer for the agent to speak.");
        return;
    }

    try {
        const resp = await fetch(`/api/brain/questions/${currentPendingQuestionId}/approve`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved_answer: answer, status: "approved" })
        });
        if (resp.ok) {
            closeApproveModal();
            loadCustomerQuestions();
            loadBrainStats();
        }
    } catch (e) {
        alert("Failed to approve question: " + e.message);
    }
}

async function loadStoryBank() {
    const grid = document.getElementById("story-bank-grid");
    try {
        const resp = await fetch("/api/brain/stories");
        const list = await resp.json();

        grid.innerHTML = list.map(s => `
            <div class="bg-dark-950 border border-dark-800 rounded-xl p-4 space-y-2 relative">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                        ${s.category}
                    </span>
                    <button onclick="deleteStory(${s.id})" class="text-slate-500 hover:text-rose-400 text-xs" title="Delete Receipt">&times;</button>
                </div>
                <h4 class="text-sm font-bold text-white">${s.title}</h4>
                <p class="text-xs text-slate-300">${s.detail}</p>
                <div class="text-[11px] font-mono text-emerald-400 pt-1 border-t border-dark-800">
                    ${s.verified_metrics || 'Verified receipt'}
                </div>
            </div>
        `).join("");
    } catch (e) {}
}

function openAddReceiptModal() {
    document.getElementById("modal-add-receipt").classList.remove("hidden");
}
function closeAddReceiptModal() {
    document.getElementById("modal-add-receipt").classList.add("hidden");
}

async function submitAddReceipt() {
    const title = document.getElementById("receipt-title").value.trim();
    const category = document.getElementById("receipt-category").value;
    const detail = document.getElementById("receipt-detail").value.trim();
    const metrics = document.getElementById("receipt-metrics").value.trim();

    if (!title || !detail) {
        alert("Title and detail are required.");
        return;
    }

    try {
        await fetch("/api/brain/stories", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category, title, detail, verified_metrics: metrics, tags: category })
        });
        closeAddReceiptModal();
        loadStoryBank();
        loadBrainStats();
    } catch (e) {
        alert("Failed to add receipt: " + e.message);
    }
}

async function deleteStory(id) {
    if (!confirm("Delete this verified receipt?")) return;
    try {
        await fetch(`/api/brain/stories/${id}`, { method: "DELETE" });
        loadStoryBank();
        loadBrainStats();
    } catch (e) {}
}

// =========================================================================
// 5. DIALERS & CTI HUB
// =========================================================================
async function loadDialers() {
    const container = document.getElementById("dialer-cards-container");
    try {
        const resp = await fetch("/api/dialers/");
        const dialers = await resp.json();

        container.innerHTML = dialers.map(d => `
            <div class="bg-dark-900 border border-dark-700/80 rounded-2xl p-5 shadow-xl space-y-4 flex flex-col justify-between">
                <div class="space-y-3">
                    <div class="flex items-center justify-between pb-3 border-b border-dark-800">
                        <div class="flex items-center space-x-2.5">
                            <div class="w-8 h-8 rounded-lg bg-dark-800 flex items-center justify-center text-brand-400">
                                <i data-lucide="${d.dialer_type === 'vicidial' ? 'server' : (d.dialer_type === 'webphone' ? 'phone' : 'radio')}" class="w-4 h-4"></i>
                            </div>
                            <div>
                                <h3 class="text-sm font-bold text-white">${d.name}</h3>
                                <span class="text-[11px] text-slate-400 font-mono uppercase">${d.dialer_type}</span>
                            </div>
                        </div>
                        <span id="badge-dialer-${d.id}" class="px-2.5 py-0.5 rounded-full text-[10px] font-semibold ${d.is_active ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800 text-slate-500'}">
                            ${d.is_active ? 'ACTIVE' : 'STANDBY'}
                        </span>
                    </div>

                    <div class="space-y-2 text-xs">
                        <div class="flex justify-between text-slate-400">
                            <span>Host / API URL:</span>
                            <span class="text-slate-200 font-mono">${d.api_url || d.host || 'N/A'}</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>Campaign / Closer:</span>
                            <span class="text-slate-200 font-mono">${d.campaign_id || 'N/A'} / ${d.closer_group || 'N/A'}</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>AudioSocket / SIP Port:</span>
                            <span class="text-slate-200 font-mono">${d.audiosocket_port || 9092} / ${d.sip_port || 5060}</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>Simulation Mode:</span>
                            <span class="${d.simulated ? 'text-amber-400' : 'text-emerald-400'} font-mono">${d.simulated ? 'ENABLED (Safe Test)' : 'LIVE CLUSTER'}</span>
                        </div>
                        ${d.notes ? `<div class="text-[11px] text-slate-400 italic pt-1 border-t border-dark-800/60">${d.notes}</div>` : ''}
                    </div>
                </div>

                <div class="pt-3 border-t border-dark-800 space-y-2">
                    <div class="flex flex-wrap items-center justify-between gap-1.5">
                        <div class="flex items-center gap-1.5">
                            <button onclick="openEditDialerModal('${d.id}')" class="px-2.5 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-200 rounded-lg text-xs font-medium border border-dark-700 flex items-center gap-1 transition">
                                <i data-lucide="settings-2" class="w-3.5 h-3.5 text-brand-cyan"></i>
                                <span>Configure</span>
                            </button>
                            <button onclick="openDialerGuideModal('${d.id}')" class="px-2.5 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-200 rounded-lg text-xs font-medium border border-dark-700 flex items-center gap-1 transition">
                                <i data-lucide="book-open" class="w-3.5 h-3.5 text-emerald-400"></i>
                                <span>Dialplan</span>
                            </button>
                        </div>
                        <div class="flex items-center gap-1.5">
                            ${d.id === 'vicidial' || d.id === 'asterisk' ? `
                                <button onclick="simulateInboundDialerCall('${d.id}')" class="px-2.5 py-1.5 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 rounded-lg text-xs font-medium flex items-center gap-1 transition">
                                    <i data-lucide="phone-incoming" class="w-3.5 h-3.5"></i>
                                    <span>Simulate Call</span>
                                </button>
                            ` : ''}
                            <button onclick="testDialerConnection('${d.id}')" class="px-2.5 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-200 rounded-lg text-xs font-medium border border-dark-700 flex items-center gap-1 transition">
                                <i data-lucide="activity" class="w-3.5 h-3.5"></i>
                                <span>Test Ping</span>
                            </button>
                        </div>
                    </div>
                    <div id="test-result-${d.id}" class="hidden text-xs p-2 rounded bg-dark-950 border border-dark-800"></div>
                </div>
            </div>
        `).join("");
        lucide.createIcons();
        await loadSoftphones();
    } catch (e) {}
}

// ==============================================================
// SOFTPHONE AGENT WORKSTATIONS (EYEBEAM & X-LITE)
// ==============================================================

async function loadSoftphones() {
    const container = document.getElementById("softphones-container");
    if (!container) return;

    try {
        const resp = await fetch("/api/softphones/status");
        if (!resp.ok) return;
        const data = await resp.json();

        const installers = data.installers || {};
        const installed = data.installed || {};
        const processes = data.processes || {};
        const virtual = data.virtual_sip || {};
        const configs = data.configs || {};

        // 1. Eyebeam Card
        const ebCfg = configs.eyebeam || { extension: "1001", server_ip: "192.168.1.100", sip_port: 5060, auto_answer: 1 };
        const ebInst = installers.eyebeam || {};
        const ebProc = processes.eyebeam || {};
        const ebBin = installed.eyebeam || {};

        // 2. X-Lite Card
        const xlCfg = configs.xlite || { extension: "1002", server_ip: "192.168.1.100", sip_port: 5060, auto_answer: 1 };
        const xlInst = installers.xlite || {};
        const xlProc = processes.xlite || {};
        const xlBin = installed.xlite || {};

        // 3. Virtual SIP Card
        const vsCfg = configs.virtual_sip || { extension: "8388", server_ip: "192.168.1.100", sip_port: 5060 };
        const isVsRunning = virtual.status === "REGISTERED";

        container.innerHTML = `
            <!-- Eyebeam Card -->
            <div class="bg-dark-900 border border-dark-700/80 rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-4">
                <div class="space-y-3">
                    <div class="flex items-center justify-between pb-3 border-b border-dark-800">
                        <div class="flex items-center space-x-2.5">
                            <div class="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center font-bold text-xs">
                                <i data-lucide="phone-call" class="w-4 h-4"></i>
                            </div>
                            <div>
                                <h3 class="text-sm font-bold text-white">eyeBeam 1.5</h3>
                                <span class="text-[10px] text-slate-400 font-mono uppercase">Windows Desktop Softphone</span>
                            </div>
                        </div>
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold ${ebProc.running ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse' : 'bg-slate-800 text-slate-500'}">
                            ${ebProc.running ? `RUNNING (PID ${ebProc.pid})` : 'STOPPED'}
                        </span>
                    </div>

                    <div class="space-y-1.5 text-xs text-slate-300">
                        <div class="flex justify-between text-slate-400">
                            <span>Installer Status:</span>
                            <span class="${ebInst.available ? 'text-emerald-400 font-semibold' : 'text-slate-500'}">
                                ${ebInst.available ? `Eyebeam.exe (${ebInst.size_mb} MB)` : 'Not Found'}
                            </span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>SIP Extension / Port:</span>
                            <span class="font-mono text-slate-200">${ebCfg.extension} @ ${ebCfg.server_ip}:${ebCfg.sip_port}</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>Auto-Answer:</span>
                            <span class="text-emerald-400 font-mono font-semibold">${ebCfg.auto_answer ? 'ENABLED (0 rings)' : 'DISABLED'}</span>
                        </div>
                        <p class="text-[11px] text-slate-400 italic pt-1 border-t border-dark-800/60">
                            Picks up VICIdial MeetMe calls immediately and connects agent into conference.
                        </p>
                    </div>
                </div>

                <div class="pt-3 border-t border-dark-800 space-y-2">
                    <div class="flex items-center gap-1.5">
                        ${ebProc.running ? `
                            <button onclick="stopSoftphone('eyebeam')" class="flex-1 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30 rounded-lg text-xs font-medium flex items-center justify-center gap-1 transition">
                                <i data-lucide="square" class="w-3.5 h-3.5"></i>
                                <span>Stop</span>
                            </button>
                        ` : `
                            <button onclick="launchSoftphone('eyebeam', 'interactive')" class="flex-1 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1 transition shadow-lg shadow-indigo-600/20">
                                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                                <span>Launch Eyebeam</span>
                            </button>
                        `}
                        <button onclick="openSoftphoneConfigModal('eyebeam')" class="px-2.5 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 border border-dark-700 rounded-lg text-xs transition" title="Edit Extension & Credentials">
                            <i data-lucide="settings" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                    <div class="grid grid-cols-2 gap-1.5">
                        <button onclick="downloadSoftphoneReg('eyebeam')" class="py-1 px-2 bg-dark-800 hover:bg-dark-700 text-slate-200 border border-dark-700 rounded-lg text-[11px] font-medium flex items-center justify-center gap-1 transition">
                            <i data-lucide="download" class="w-3 h-3 text-brand-cyan"></i>
                            <span>Download .reg</span>
                        </button>
                        <button onclick="applySoftphoneReg('eyebeam')" class="py-1 px-2 bg-dark-800 hover:bg-dark-700 text-slate-200 border border-dark-700 rounded-lg text-[11px] font-medium flex items-center justify-center gap-1 transition">
                            <i data-lucide="zap" class="w-3 h-3 text-amber-400"></i>
                            <span>Apply Registry</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- X-Lite Card -->
            <div class="bg-dark-900 border border-dark-700/80 rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-4">
                <div class="space-y-3">
                    <div class="flex items-center justify-between pb-3 border-b border-dark-800">
                        <div class="flex items-center space-x-2.5">
                            <div class="w-8 h-8 rounded-lg bg-brand-500/10 text-brand-400 flex items-center justify-center font-bold text-xs">
                                <i data-lucide="phone-forwarded" class="w-4 h-4"></i>
                            </div>
                            <div>
                                <h3 class="text-sm font-bold text-white">X-Lite 3.0</h3>
                                <span class="text-[10px] text-slate-400 font-mono uppercase">CounterPath Softphone</span>
                            </div>
                        </div>
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold ${xlProc.running ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse' : 'bg-slate-800 text-slate-500'}">
                            ${xlProc.running ? `RUNNING (PID ${xlProc.pid})` : 'STOPPED'}
                        </span>
                    </div>

                    <div class="space-y-1.5 text-xs text-slate-300">
                        <div class="flex justify-between text-slate-400">
                            <span>Installer Status:</span>
                            <span class="${xlInst.available ? 'text-emerald-400 font-semibold' : 'text-slate-500'}">
                                ${xlInst.available ? `x-lite-eyebeam.exe (${xlInst.size_mb} MB)` : 'Not Found'}
                            </span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>SIP Extension / Port:</span>
                            <span class="font-mono text-slate-200">${xlCfg.extension} @ ${xlCfg.server_ip}:${xlCfg.sip_port}</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>Auto-Answer:</span>
                            <span class="text-emerald-400 font-mono font-semibold">${xlCfg.auto_answer ? 'ENABLED' : 'DISABLED'}</span>
                        </div>
                        <p class="text-[11px] text-slate-400 italic pt-1 border-t border-dark-800/60">
                            Alternative desktop softphone workstation for manual and blended campaigns.
                        </p>
                    </div>
                </div>

                <div class="pt-3 border-t border-dark-800 space-y-2">
                    <div class="flex items-center gap-1.5">
                        ${xlProc.running ? `
                            <button onclick="stopSoftphone('xlite')" class="flex-1 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30 rounded-lg text-xs font-medium flex items-center justify-center gap-1 transition">
                                <i data-lucide="square" class="w-3.5 h-3.5"></i>
                                <span>Stop</span>
                            </button>
                        ` : `
                            <button onclick="launchSoftphone('xlite', 'interactive')" class="flex-1 py-1.5 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1 transition shadow-lg shadow-brand-600/20">
                                <i data-lucide="play" class="w-3.5 h-3.5"></i>
                                <span>Launch X-Lite</span>
                            </button>
                        `}
                        <button onclick="openSoftphoneConfigModal('xlite')" class="px-2.5 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 border border-dark-700 rounded-lg text-xs transition" title="Edit Extension & Credentials">
                            <i data-lucide="settings" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                    <div class="grid grid-cols-2 gap-1.5">
                        <button onclick="downloadSoftphoneReg('xlite')" class="py-1 px-2 bg-dark-800 hover:bg-dark-700 text-slate-200 border border-dark-700 rounded-lg text-[11px] font-medium flex items-center justify-center gap-1 transition">
                            <i data-lucide="download" class="w-3 h-3 text-brand-cyan"></i>
                            <span>Download .reg</span>
                        </button>
                        <button onclick="openSoftphoneGuideModal()" class="py-1 px-2 bg-dark-800 hover:bg-dark-700 text-slate-200 border border-dark-700 rounded-lg text-[11px] font-medium flex items-center justify-center gap-1 transition">
                            <i data-lucide="book-open" class="w-3 h-3 text-indigo-400"></i>
                            <span>Guide</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Virtual SIP Agent Card -->
            <div class="bg-dark-900 border border-dark-700/80 rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-4">
                <div class="space-y-3">
                    <div class="flex items-center justify-between pb-3 border-b border-dark-800">
                        <div class="flex items-center space-x-2.5">
                            <div class="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold text-xs">
                                <i data-lucide="bot" class="w-4 h-4"></i>
                            </div>
                            <div>
                                <h3 class="text-sm font-bold text-white">Virtual SIP Agent</h3>
                                <span class="text-[10px] text-slate-400 font-mono uppercase">Headless Eyebeam Emulation</span>
                            </div>
                        </div>
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold ${isVsRunning ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse' : 'bg-slate-800 text-slate-500'}">
                            ${isVsRunning ? 'REGISTERED & READY' : 'OFFLINE'}
                        </span>
                    </div>

                    <div class="space-y-1.5 text-xs text-slate-300">
                        <div class="flex justify-between text-slate-400">
                            <span>Role:</span>
                            <span class="text-emerald-400 font-semibold">100% Automated Agent Station</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>SIP Extension:</span>
                            <span class="font-mono text-slate-200">${virtual.extension || vsCfg.extension} @ ${virtual.server_ip || vsCfg.server_ip}:${virtual.sip_port || vsCfg.sip_port}</span>
                        </div>
                        <div class="flex justify-between text-slate-400">
                            <span>Audio Routing:</span>
                            <span class="text-indigo-400 font-mono">Direct AI Engine (No GUI)</span>
                        </div>
                        <p class="text-[11px] text-slate-400 italic pt-1 border-t border-dark-800/60">
                            Directly answers MeetMe conferences and handles calls with the Cognitive Brain.
                        </p>
                    </div>
                </div>

                <div class="pt-3 border-t border-dark-800 space-y-2">
                    <div class="flex items-center gap-1.5">
                        <button onclick="toggleVirtualSIP()" class="flex-1 py-1.5 ${isVsRunning ? 'bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30' : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20'} rounded-lg text-xs font-semibold flex items-center justify-center gap-1 transition">
                            <i data-lucide="${isVsRunning ? 'power-off' : 'zap'}" class="w-3.5 h-3.5"></i>
                            <span>${isVsRunning ? 'Disconnect Virtual SIP' : 'Connect to VICIdial'}</span>
                        </button>
                        <button onclick="openSoftphoneConfigModal('virtual_sip')" class="px-2.5 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-300 border border-dark-700 rounded-lg text-xs transition" title="Edit Extension & Credentials">
                            <i data-lucide="settings" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                    <div class="text-[10px] text-slate-500 text-center font-mono">
                        Zero Windows Desktop Clutter · Zero Cable Routing
                    </div>
                </div>
            </div>
        `;
        lucide.createIcons();
    } catch (e) {
        console.error("loadSoftphones error:", e);
    }
}

async function launchSoftphone(type, mode = "interactive") {
    try {
        const resp = await fetch("/api/softphones/launch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ softphone_type: type, mode: mode })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Launch failed");

        alert(`🚀 ${data.message}`);
        await loadSoftphones();
    } catch (e) {
        alert("Launch failed: " + e.message);
    }
}

async function stopSoftphone(type) {
    try {
        const resp = await fetch("/api/softphones/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ softphone_type: type })
        });
        const data = await resp.json();
        await loadSoftphones();
    } catch (e) {
        alert("Stop failed: " + e.message);
    }
}

async function downloadSoftphoneReg(type = "eyebeam") {
    try {
        const resp = await fetch("/api/softphones/status");
        const data = await resp.json();
        const cfg = (data.configs && data.configs[type]) || { extension: "1001", server_ip: "192.168.1.100", sip_port: 5060, auto_answer: 1 };

        const url = `/api/softphones/download-reg?extension=${encodeURIComponent(cfg.extension)}&server_ip=${encodeURIComponent(cfg.server_ip)}&sip_port=${cfg.sip_port}&auto_answer=${cfg.auto_answer ? 'true' : 'false'}`;
        const a = document.createElement("a");
        a.href = url;
        a.download = `eyebeam_vicidial_${cfg.extension}.reg`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    } catch (e) {
        alert("Download failed: " + e.message);
    }
}

async function applySoftphoneReg(type = "eyebeam") {
    try {
        const resp = await fetch("/api/softphones/status");
        const data = await resp.json();
        const cfg = (data.configs && data.configs[type]) || { extension: "1001", server_ip: "192.168.1.100", sip_port: 5060, auto_answer: 1 };

        const resApply = await fetch("/api/softphones/apply-reg", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                extension: cfg.extension,
                password: "test" + cfg.extension,
                server_ip: cfg.server_ip,
                sip_port: cfg.sip_port,
                auto_answer: Boolean(cfg.auto_answer)
            })
        });
        const resData = await resApply.json();
        if (resData.success) {
            alert(`⚡ ${resData.message}\nLaunch Eyebeam now to log into VICIdial!`);
        } else {
            alert(`Registry application notice: ${resData.message}`);
        }
    } catch (e) {
        alert("Apply registry failed: " + e.message);
    }
}

async function toggleVirtualSIP() {
    try {
        const statusResp = await fetch("/api/softphones/status");
        const sData = await statusResp.json();
        const isRunning = sData.virtual_sip && sData.virtual_sip.status === "REGISTERED";

        if (isRunning) {
            await fetch("/api/softphones/virtual/unregister", { method: "POST" });
        } else {
            const cfg = (sData.configs && sData.configs.virtual_sip) || { extension: "8388", server_ip: "192.168.1.100", sip_port: 5060 };
            await fetch("/api/softphones/virtual/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    extension: cfg.extension,
                    password: "test" + cfg.extension,
                    server_ip: cfg.server_ip,
                    sip_port: cfg.sip_port
                })
            });
        }
        await loadSoftphones();
    } catch (e) {
        alert("Virtual SIP toggle failed: " + e.message);
    }
}

async function openSoftphoneConfigModal(id) {
    try {
        const resp = await fetch("/api/softphones/status");
        const data = await resp.json();
        const cfg = (data.configs && data.configs[id]) || {
            name: id.toUpperCase(),
            extension: "1001",
            server_ip: "192.168.1.100",
            sip_port: 5060,
            auto_answer: 1,
            notes: ""
        };

        document.getElementById("sp-modal-id").value = id;
        document.getElementById("sp-modal-subtitle").textContent = `${cfg.name || id} Workstation`;
        document.getElementById("sp-modal-ext").value = cfg.extension || "1001";
        document.getElementById("sp-modal-secret").value = "";
        document.getElementById("sp-modal-server").value = cfg.server_ip || "192.168.1.100";
        document.getElementById("sp-modal-port").value = cfg.sip_port || 5060;
        document.getElementById("sp-modal-auto-answer").checked = Boolean(cfg.auto_answer);
        document.getElementById("sp-modal-notes").value = cfg.notes || "";

        document.getElementById("modal-softphone-config").classList.remove("hidden");
    } catch (e) {
        alert("Failed to load config: " + e.message);
    }
}

function closeSoftphoneConfigModal() {
    document.getElementById("modal-softphone-config").classList.add("hidden");
}

async function saveSoftphoneConfig(e) {
    e.preventDefault();
    const id = document.getElementById("sp-modal-id").value;
    const ext = document.getElementById("sp-modal-ext").value.trim();
    const sec = document.getElementById("sp-modal-secret").value;
    const srv = document.getElementById("sp-modal-server").value.trim();
    const port = parseInt(document.getElementById("sp-modal-port").value, 10) || 5060;
    const autoAns = document.getElementById("sp-modal-auto-answer").checked;
    const notes = document.getElementById("sp-modal-notes").value.trim();

    try {
        const resp = await fetch(`/api/softphones/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                extension: ext,
                secret: sec || undefined,
                server_ip: srv,
                sip_port: port,
                auto_answer: autoAns,
                notes: notes
            })
        });
        if (!resp.ok) throw new Error("Failed to save softphone configuration");

        closeSoftphoneConfigModal();
        await loadSoftphones();
    } catch (e) {
        alert("Save failed: " + e.message);
    }
}

function openSoftphoneGuideModal() {
    document.getElementById("modal-softphone-guide").classList.remove("hidden");
    lucide.createIcons();
}

function closeSoftphoneGuideModal() {
    document.getElementById("modal-softphone-guide").classList.add("hidden");
}

async function testDialerConnection(dialerId) {
    const resBox = document.getElementById(`test-result-${dialerId}`);
    resBox.classList.remove("hidden");
    resBox.textContent = "Pinging endpoint...";

    try {
        const resp = await fetch(`/api/dialers/${dialerId}/test`, { method: "POST" });
        const data = await resp.json();

        resBox.textContent = `[${data.status.toUpperCase()}] ${data.message}`;
        resBox.className = `text-xs p-2 rounded bg-dark-950 border ${data.success ? 'border-emerald-500/40 text-emerald-400' : 'border-rose-500/40 text-rose-400'}`;
    } catch (e) {
        resBox.textContent = "Connection test failed: " + e.message;
        resBox.className = "text-xs p-2 rounded bg-dark-950 border border-rose-500/40 text-rose-400";
    }
}

async function openEditDialerModal(dialerId) {
    try {
        const resp = await fetch(`/api/dialers/${dialerId}/raw`);
        const d = await resp.json();

        document.getElementById("edit-dialer-id").value = d.id;
        document.getElementById("edit-dialer-title-name").textContent = d.name;
        document.getElementById("edit-dialer-name").value = d.name || "";
        document.getElementById("edit-dialer-host").value = d.host || "";
        document.getElementById("edit-dialer-api-url").value = d.api_url || "";
        document.getElementById("edit-dialer-api-user").value = d.api_user || "";
        document.getElementById("edit-dialer-api-pass").value = d.api_pass || "";
        document.getElementById("edit-dialer-campaign").value = d.campaign_id || "";
        document.getElementById("edit-dialer-closer").value = d.closer_group || "";
        document.getElementById("edit-dialer-as-port").value = d.audiosocket_port || 9092;
        document.getElementById("edit-dialer-sip-port").value = d.sip_port || 5060;
        document.getElementById("edit-dialer-notes").value = d.notes || "";
        document.getElementById("edit-dialer-simulated").checked = Boolean(d.simulated);

        document.getElementById("modal-edit-dialer").classList.remove("hidden");
    } catch (e) {
        alert("Failed to load dialer configuration: " + e.message);
    }
}

function closeEditDialerModal() {
    document.getElementById("modal-edit-dialer").classList.add("hidden");
}

async function submitEditDialer() {
    const dialerId = document.getElementById("edit-dialer-id").value;
    const body = {
        name: document.getElementById("edit-dialer-name").value.trim(),
        host: document.getElementById("edit-dialer-host").value.trim(),
        api_url: document.getElementById("edit-dialer-api-url").value.trim(),
        api_user: document.getElementById("edit-dialer-api-user").value.trim(),
        api_pass: document.getElementById("edit-dialer-api-pass").value,
        campaign_id: document.getElementById("edit-dialer-campaign").value.trim(),
        closer_group: document.getElementById("edit-dialer-closer").value.trim(),
        audiosocket_port: parseInt(document.getElementById("edit-dialer-as-port").value) || 9092,
        sip_port: parseInt(document.getElementById("edit-dialer-sip-port").value) || 5060,
        notes: document.getElementById("edit-dialer-notes").value.trim(),
        simulated: document.getElementById("edit-dialer-simulated").checked,
        is_active: true
    };

    const btn = document.getElementById("btn-save-dialer");
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
        const resp = await fetch(`/api/dialers/${dialerId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        if (!resp.ok) throw new Error("Failed to save dialer");

        closeEditDialerModal();
        await loadDialers();
        alert(`✓ ${body.name} configuration saved!`);
    } catch (e) {
        alert("Save failed: " + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "Save Dialer Configuration";
    }
}

async function openDialerGuideModal(dialerId = "vicidial") {
    try {
        const resp = await fetch(`/api/dialers/${dialerId}/guide`);
        const g = await resp.json();

        document.getElementById("guide-dialer-subtitle").textContent = `${g.name} (${g.dialer_id.toUpperCase()})`;
        document.getElementById("guide-architecture-text").textContent = g.architecture;
        document.getElementById("guide-dialplan-code").textContent = g.asterisk_dialplan;
        document.getElementById("guide-webhook-url").value = g.dispo_webhook_url || "";

        const stepsCont = document.getElementById("guide-steps-container");
        const steps = g.vicidial_admin_steps || g.asterisk_admin_steps || [];
        stepsCont.innerHTML = steps.map(s => `
            <div class="p-3 rounded-xl bg-dark-950 border border-dark-800 space-y-1">
                <div class="font-bold text-white flex items-center gap-2">
                    <span class="w-5 h-5 rounded-full bg-brand-500/20 text-brand-cyan flex items-center justify-center text-xs font-mono">${s.step}</span>
                    <span>${s.title}</span>
                </div>
                <p class="text-slate-400 text-[11px] pl-7">${s.instruction}</p>
            </div>
        `).join("");

        document.getElementById("modal-dialer-guide").classList.remove("hidden");
        lucide.createIcons();
    } catch (e) {
        alert("Failed to load setup guide: " + e.message);
    }
}

function closeDialerGuideModal() {
    document.getElementById("modal-dialer-guide").classList.add("hidden");
}

function copyGuideDialplan() {
    const code = document.getElementById("guide-dialplan-code").textContent;
    navigator.clipboard.writeText(code).then(() => {
        const btn = document.getElementById("btn-copy-dialplan");
        const orig = btn.innerHTML;
        btn.innerHTML = `<span class="text-emerald-400">✓ Copied!</span>`;
        setTimeout(() => { btn.innerHTML = orig; }, 1800);
    });
}

function copyGuideWebhook() {
    const url = document.getElementById("guide-webhook-url").value;
    navigator.clipboard.writeText(url).then(() => {
        alert("Dispo Webhook URL copied to clipboard!");
    });
}

async function simulateInboundDialerCall(dialerId = "vicidial") {
    try {
        const resp = await fetch(`/api/dialers/${dialerId}/simulate-call`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                lead_id: `VICI_${Math.floor(10000 + Math.random() * 90000)}`,
                phone_number: "+1 (312) 555-0199",
                customer_name: "David Miller (Logistics Director)",
                campaign_id: "SALES_OUT"
            })
        });
        const data = await resp.json();

        // Switch to webphone tab
        switchTab("tab-webphone");

        activeCallSessionId = data.session_id;
        document.getElementById("phone-input").value = data.phone_number;

        const badge = document.getElementById("call-state-badge");
        badge.textContent = `CONNECTED (${dialerId.toUpperCase()} LEAD)`;
        badge.className = "px-3 py-1 rounded-full text-xs font-mono font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse";

        const btnStart = document.getElementById("btn-start-call");
        btnStart.disabled = true;
        btnStart.className = "flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-dark-800 text-slate-500 text-sm font-medium cursor-not-allowed";

        const btnEnd = document.getElementById("btn-end-call");
        btnEnd.disabled = false;
        btnEnd.className = "flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-medium text-sm transition shadow-lg shadow-rose-600/20";

        document.getElementById("btn-transfer-warm").disabled = false;
        document.getElementById("btn-transfer-blind").disabled = false;
        document.getElementById("audio-status-label").textContent = data.message;

        // Render initial greeting
        const feed = document.getElementById("transcript-feed");
        feed.innerHTML = `
            <div class="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-xs text-indigo-300 flex items-center justify-between">
                <span><b>${dialerId.toUpperCase()} Inbound Lead Dispatched:</b> Lead #${data.lead_id} — ${data.customer_name}</span>
                <span class="font-mono text-emerald-400">AudioSocket :9092 Linked</span>
            </div>
        `;
        appendTranscript("agent", data.greeting.text, data.greeting.latency, data.greeting.audio_url, data.greeting.voice_name);
        updateLatencyDisplay(data.greeting.latency);

    } catch (e) {
        alert("Failed to simulate dialer call: " + e.message);
    }
}

let isDemoRunning = false;

async function runAutomatedDemoCall() {
    if (isDemoRunning) return;
    isDemoRunning = true;

    // Switch to webphone tab
    switchTab("tab-webphone");

    const btn = document.getElementById("btn-demo-call");
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Running Interactive Demo Call...</span>`;
    lucide.createIcons();

    try {
        // Step 1: Start Call
        await startWebPhoneCall("+1 (312) 555-0188");
        await new Promise(r => setTimeout(r, 2200));

        // Step 2: Caller Turn 1
        const t1 = "Hi Jordan, do you guys integrate directly with VICIdial and what is your latency?";
        document.getElementById("caller-input").value = t1;
        await sendCallerUtterance();
        await new Promise(r => setTimeout(r, 3200));

        // Step 3: Caller Turn 2 (Objection / Pricing)
        const t2 = "How much does it cost per connected minute, and do you require long term contracts?";
        document.getElementById("caller-input").value = t2;
        await sendCallerUtterance();
        await new Promise(r => setTimeout(r, 3200));

        // Step 4: Caller Turn 3 (Demo acceptance & handoff)
        const t3 = "That sounds great. Can you connect me with your closer right now?";
        document.getElementById("caller-input").value = t3;
        await sendCallerUtterance();
        await new Promise(r => setTimeout(r, 2500));

        // Step 5: Execute Warm Transfer
        await triggerTransfer("WARM");

        alert("✓ 4-Turn Automated Demo Call Complete!\nDemonstrated: Sub-600ms latency, Section 7.1 natural human cadence, objection handling, and warm transfer to live closer.");
    } catch (e) {
        console.error("Demo call error:", e);
    } finally {
        isDemoRunning = false;
        btn.disabled = false;
        btn.innerHTML = origText;
        lucide.createIcons();
    }
}

// =========================================================================
// 6. AGENT REACH EYES
// =========================================================================
function setReachUrl(url) {
    document.getElementById("reach-url-input").value = url;
}

async function scanUrlWithReachEyes() {
    const url = document.getElementById("reach-url-input").value.trim();
    if (!url) {
        alert("Please enter a target URL to scan.");
        return;
    }

    const btn = document.getElementById("btn-scan-reach");
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Scanning...</span>`;
    lucide.createIcons();

    try {
        const resp = await fetch("/api/reach/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url })
        });
        const res = await resp.json();

        if (!resp.ok) {
            alert("Scan failed: " + (res.detail || "Error"));
            return;
        }

        lastReachAnalysis = res.analysis;
        renderReachResults(res.analysis);
    } catch (e) {
        alert("Error scanning URL: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="search" class="w-4 h-4"></i><span>Scan with Reach Eyes</span>`;
        lucide.createIcons();
    }
}

function renderReachResults(data) {
    const panel = document.getElementById("reach-results-panel");
    panel.classList.remove("hidden");

    document.getElementById("reach-title").textContent = data.company_name;
    document.getElementById("reach-url-label").textContent = data.url;

    // Value Props
    const vpList = document.getElementById("reach-value-props");
    vpList.innerHTML = (data.value_propositions || []).map(vp => `<li>${vp}</li>`).join("");

    // Pricing tags
    const priceDiv = document.getElementById("reach-pricing-tags");
    priceDiv.innerHTML = (data.pricing_highlights || []).map(p => `
        <span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-mono text-xs">${p}</span>
    `).join("");

    // Q&As
    const qasDiv = document.getElementById("reach-qas-list");
    qasDiv.innerHTML = (data.suggested_qas || []).map(qa => `
        <div class="p-2.5 rounded-lg bg-dark-900 border border-dark-800 space-y-1">
            <div class="text-xs font-semibold text-brand-400">Q: ${qa.question}</div>
            <div class="text-xs text-slate-300">A: ${qa.answer}</div>
        </div>
    `).join("");
}

async function digestReachIntoBrain() {
    if (!lastReachAnalysis) return;
    const btn = document.getElementById("btn-digest");
    btn.disabled = true;
    btn.textContent = "Ingesting into Brain...";

    try {
        const resp = await fetch("/api/reach/digest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ analysis: lastReachAnalysis })
        });
        const res = await resp.json();
        alert("✓ " + res.message);
        loadBrainStats();
        loadCustomerQuestions();
        loadStoryBank();
    } catch (e) {
        alert("Ingestion failed: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="sparkles" class="w-4 h-4"></i><span>Digest into Cognitive Brain</span>`;
        lucide.createIcons();
    }
}

// =========================================================================
// 7. CALL HISTORY & TRANSCRIPTS
// =========================================================================
window.callHistoryMap = {};
window.activeTranscriptSessionId = null;

async function loadCallHistory() {
    const tbody = document.getElementById("history-tbody");
    try {
        const resp = await fetch("/api/calls/history");
        const calls = await resp.json();

        if (!calls || calls.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-slate-500">No calls logged yet. Start a test call to record history.</td></tr>`;
            return;
        }

        window.callHistoryMap = {};
        tbody.innerHTML = calls.map(c => {
            window.callHistoryMap[c.session_id] = c;
            return `
            <tr class="hover:bg-dark-800/50">
                <td class="py-3 px-3 font-mono text-slate-300">${c.session_id}</td>
                <td class="py-3 px-3 font-mono text-slate-400">${c.phone_number}</td>
                <td class="py-3 px-3 font-mono text-slate-300">${c.duration_sec}s</td>
                <td class="py-3 px-3">
                    <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${c.disposition === 'SALE' ? 'bg-emerald-500/20 text-emerald-400' : (c.disposition === 'DNC' ? 'bg-rose-500/20 text-rose-400' : 'bg-slate-700 text-slate-300')}">
                        ${c.disposition}
                    </span>
                </td>
                <td class="py-3 px-3 font-mono text-emerald-400">${c.latency_p95_ms}ms</td>
                <td class="py-3 px-3 text-brand-cyan">${Array.isArray(c.customer_questions_detected) ? c.customer_questions_detected.length : 0} detected</td>
                <td class="py-3 px-3 text-right space-x-1.5">
                    ${c.audio_url ? `
                        <button onclick="playRecording('${c.audio_url}')" class="px-2 py-1 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 border border-emerald-500/30 text-xs font-medium rounded-lg inline-flex items-center gap-1">
                            Play Audio
                        </button>
                    ` : ''}
                    <button onclick="viewTranscriptModal('${c.session_id}')" class="px-2.5 py-1 bg-dark-800 hover:bg-dark-700 text-xs font-medium text-brand-cyan border border-dark-700 rounded-lg inline-flex items-center gap-1">
                        <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                        <span>Transcript & Train</span>
                    </button>
                </td>
            </tr>
            `;
        }).join("");
        lucide.createIcons();
    } catch (e) {}
}

function viewTranscriptModal(sessionId) {
    window.activeTranscriptSessionId = sessionId;
    const modal = document.getElementById("modal-view-transcript");
    const container = document.getElementById("modal-transcript-content");
    const call = window.callHistoryMap[sessionId] || {};
    const transcript = call.transcript || [];

    document.getElementById("transcript-session-pill").textContent = sessionId;
    document.getElementById("transcript-dispo-pill").textContent = call.disposition || "CALLBK";
    closeTrainTurnDrawer();

    if (!transcript || transcript.length === 0) {
        container.innerHTML = `<p class="text-slate-500 p-4 text-center">No transcript turns available for this session.</p>`;
    } else {
        container.innerHTML = transcript.map((t, idx) => {
            const ts = typeof t.timestamp === 'number' ? `+${t.timestamp.toFixed(1)}s` : '';
            if (t.speaker === 'caller') {
                const nextAgent = (idx + 1 < transcript.length && transcript[idx + 1].speaker === 'agent') ? transcript[idx + 1].text : '';
                return `
                <div class="p-3 rounded-xl bg-dark-950 border border-dark-800 space-y-1.5 shadow-sm">
                    <div class="flex items-center justify-between text-[11px]">
                        <span class="font-bold text-slate-300 uppercase flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full bg-brand-cyan"></span>
                            Customer ${ts ? `<span class="text-slate-500 font-mono text-[10px]">(${ts})</span>` : ''}
                        </span>
                        <button onclick="openTrainTurnDrawer('${escapeJsStr(t.text)}', '${escapeJsStr(nextAgent)}')" class="px-2.5 py-1 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-lg text-xs font-semibold flex items-center gap-1 transition">
                            <i data-lucide="sparkles" class="w-3 h-3"></i>
                            <span>Train Brain</span>
                        </button>
                    </div>
                    <div class="text-xs text-slate-100 font-medium pl-3.5 border-l-2 border-brand-cyan/40">${t.text}</div>
                </div>
                `;
            } else {
                const lat = t.latency_ms ? `<span class="font-mono text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">Turn Latency: ${t.latency_ms}ms</span>` : '';
                return `
                <div class="p-3 rounded-xl bg-dark-800/80 border border-dark-700/80 space-y-1.5 ml-4 shadow-sm">
                    <div class="flex items-center justify-between text-[11px]">
                        <span class="font-bold text-brand-cyan uppercase flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full bg-brand-400"></span>
                            Jordan (Shadow Voice Agent) ${ts ? `<span class="text-slate-400 font-mono text-[10px]">(${ts})</span>` : ''}
                        </span>
                        ${lat}
                    </div>
                    <div class="text-xs text-indigo-200 pl-3.5 border-l-2 border-brand-500/40">${t.text}</div>
                </div>
                `;
            }
        }).join("");
    }

    modal.classList.remove("hidden");
    lucide.createIcons();
}

function closeTranscriptModal() {
    document.getElementById("modal-view-transcript").classList.add("hidden");
    closeTrainTurnDrawer();
}

function openTrainTurnDrawer(questionText, agentText) {
    const drawer = document.getElementById("drawer-train-turn");
    document.getElementById("train-turn-question").value = questionText;
    document.getElementById("train-turn-answer").value = agentText || "We provide complete telephony automation with zero dropped calls and sub-second response times.";
    document.getElementById("train-turn-feedback").textContent = "";

    // Auto-detect category
    const qLower = questionText.toLowerCase();
    const catEl = document.getElementById("train-turn-category");
    if (qLower.includes("price") || qLower.includes("cost") || qLower.includes("rate") || qLower.includes("$")) {
        catEl.value = "pricing";
    } else if (qLower.includes("dialer") || qLower.includes("vicidial") || qLower.includes("asterisk") || qLower.includes("sip")) {
        catEl.value = "technical";
    } else if (qLower.includes("tcpa") || qLower.includes("dnc") || qLower.includes("compliance")) {
        catEl.value = "compliance";
    } else {
        catEl.value = "general";
    }

    drawer.classList.remove("hidden");
    document.getElementById("train-turn-answer").focus();
    lucide.createIcons();
}

function closeTrainTurnDrawer() {
    const drawer = document.getElementById("drawer-train-turn");
    if (drawer) drawer.classList.add("hidden");
}

async function submitTrainTurn() {
    if (!window.activeTranscriptSessionId) return;
    const q = document.getElementById("train-turn-question").value.trim();
    const a = document.getElementById("train-turn-answer").value.trim();
    const cat = document.getElementById("train-turn-category").value;
    const sent = document.getElementById("train-turn-sentiment").value;

    if (!q || !a) {
        alert("Please enter both the question and the golden answer.");
        return;
    }

    const btn = document.getElementById("btn-submit-train-turn");
    btn.disabled = true;
    try {
        const resp = await fetch(`/api/calls/${window.activeTranscriptSessionId}/train-turn`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question_text: q,
                approved_answer: a,
                category: cat,
                sentiment: sent
            })
        });
        const res = await resp.json();
        document.getElementById("train-turn-feedback").textContent = "✓ Ingested & Approved into Cognitive Brain!";
        loadBrainStats();
        loadCustomerQuestions();
        setTimeout(() => closeTrainTurnDrawer(), 1200);
    } catch (e) {
        alert("Turn training failed: " + e.message);
    } finally {
        btn.disabled = false;
    }
}

async function exportCurrentTranscript(format) {
    if (!window.activeTranscriptSessionId) return;
    try {
        const resp = await fetch(`/api/calls/${window.activeTranscriptSessionId}/export?format=${format}`);
        const data = await resp.json();

        const content = format === 'text' ? data.content : JSON.stringify(data, null, 2);
        const mimeType = format === 'text' ? 'text/plain' : 'application/json';
        const ext = format === 'text' ? 'txt' : 'json';

        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `call_transcript_${window.activeTranscriptSessionId}.${ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert("Export failed: " + e.message);
    }
}

function escapeJsStr(str) {
    if (!str) return "";
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\n/g, ' ');
}

// =========================================================================
// 8. ANALYTICS & COMPLIANCE
// =========================================================================
async function loadAnalytics() {
    try {
        const resp = await fetch("/api/analytics/summary");
        const data = await resp.json();
        // Charts rendered on demand when tab opens
    } catch (e) {}
}

async function renderAnalyticsCharts() {
    try {
        const resp = await fetch("/api/analytics/summary");
        const data = await resp.json();

        // Dispositions Chart
        const ctxD = document.getElementById("chart-dispositions");
        if (ctxD) {
            if (chartDispositions) chartDispositions.destroy();
            const labels = Object.keys(data.dispositions);
            const values = Object.values(data.dispositions);

            chartDispositions = new Chart(ctxD, {
                type: 'doughnut',
                data: {
                    labels,
                    datasets: [{
                        data: values,
                        backgroundColor: ['#10b981', '#3b82f6', '#8b5cf6', '#64748b', '#ef4444', '#f59e0b'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8' } } }
                }
            });
        }

        // Latency Chart
        const ctxL = document.getElementById("chart-latency");
        if (ctxL) {
            if (chartLatency) chartLatency.destroy();
            chartLatency = new Chart(ctxL, {
                type: 'bar',
                data: {
                    labels: ['P50 (Median)', 'P95 (Tail)', 'P99 (Max)', 'Safe Harbor Limit'],
                    datasets: [{
                        label: 'Latency (ms)',
                        data: [data.latency_metrics.p50_ms, data.latency_metrics.p95_ms, data.latency_metrics.p99_ms, data.latency_metrics.target_ms],
                        backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444'],
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { grid: { color: '#1f2937' }, ticks: { color: '#94a3b8' } },
                        x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        }
    } catch (e) {}
}

async function testDncScrub() {
    const phone = document.getElementById("dnc-test-phone").value.trim();
    const box = document.getElementById("dnc-test-result");
    if (!phone) return;

    box.classList.remove("hidden");
    box.textContent = "Scrubbing registries...";

    try {
        const resp = await fetch("/api/analytics/dnc-check", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone_number: phone })
        });
        const res = await resp.json();

        box.className = `p-3 rounded-xl bg-dark-950 border ${res.is_scrubbed_clean ? 'border-emerald-500/40 text-emerald-400' : 'border-rose-500/40 text-rose-400'} text-xs space-y-1`;
        box.innerHTML = `
            <div><b>Phone:</b> ${res.phone_number}</div>
            <div><b>DNC Registry Status:</b> ${res.is_scrubbed_clean ? 'CLEAN (Dialing Allowed)' : 'BLOCKED (' + res.dnc_block_reason + ')'}</div>
            <div><b>Calling Window:</b> ${res.calling_window_permitted ? 'PERMITTED (8am-9pm daytime)' : 'OUTSIDE HOURS'}</div>
        `;
    } catch (e) {
        box.textContent = "Check error: " + e.message;
    }
}

// =========================================================================
// 9. SETTINGS, UNIVERSAL MODELS & KILL SWITCH
// =========================================================================
async function loadSettings() {
    try {
        const resp = await fetch("/api/settings/");
        const data = await resp.json();
        const s = data.settings || {};

        const prov = s.LLM_PROVIDER || "ollama";
        document.getElementById("setting-llm-provider").value = prov;
        document.getElementById("setting-model-name").value = s.SELECTED_MODEL || s.OLLAMA_MODEL || s.OPENROUTER_MODEL || "llama3.2:latest";
        document.getElementById("setting-base-url").value = s.OLLAMA_BASE_URL || s.CUSTOM_LLM_BASE_URL || (prov === "ollama" ? "http://localhost:11434" : (prov === "custom" ? "http://localhost:1234/v1" : ""));
        document.getElementById("setting-api-key").value = s.API_KEY || "";
        document.getElementById("setting-stt-engine").value = s.STT_ENGINE || "deepgram_nova3";
        document.getElementById("setting-tts-engine").value = s.TTS_ENGINE || "cartesia_sonic";
        document.getElementById("setting-spend-ceiling").value = s.DAILY_SPEND_CEILING_USD || "150.0";
        document.getElementById("setting-drop-limit").value = s.SAFE_HARBOR_DROP_LIMIT || "3.0";

        const statusEl = document.getElementById("model-connection-status");
        if (data.ollama_connected) {
            statusEl.textContent = "Ollama: Connected (Local)";
            statusEl.className = "text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-medium";
        } else {
            statusEl.textContent = `${prov.toUpperCase()}: Ready`;
            statusEl.className = "text-[11px] px-2 py-0.5 rounded-full bg-dark-800 text-slate-300 border border-dark-700 font-medium";
        }

        updateKillSwitchUI(data.kill_switch_active);
    } catch (e) {}
}

function onProviderChanged() {
    const prov = document.getElementById("setting-llm-provider").value;
    const urlInput = document.getElementById("setting-base-url");
    const modelInput = document.getElementById("setting-model-name");

    if (prov === "ollama") {
        urlInput.placeholder = "http://localhost:11434";
        if (!urlInput.value || urlInput.value.includes("1234")) urlInput.value = "http://localhost:11434";
        modelInput.placeholder = "llama3.2:latest, deepseek-r1:latest, qwen2.5:latest";
    } else if (prov === "custom") {
        urlInput.placeholder = "http://localhost:1234/v1";
        if (!urlInput.value || urlInput.value.includes("11434")) urlInput.value = "http://localhost:1234/v1";
        modelInput.placeholder = "local-model, mistral-7b, llama-3-8b";
    } else if (prov === "groq") {
        urlInput.placeholder = "https://api.groq.com/openai/v1";
        modelInput.placeholder = "llama-3.3-70b-versatile";
    } else if (prov === "openai") {
        urlInput.placeholder = "https://api.openai.com/v1";
        modelInput.placeholder = "gpt-4o-mini, gpt-4o";
    } else if (prov === "gemini") {
        urlInput.placeholder = "https://generativelanguage.googleapis.com/v1beta/openai";
        modelInput.placeholder = "gemini-2.0-flash";
    } else if (prov === "anthropic") {
        urlInput.placeholder = "https://api.anthropic.com";
        modelInput.placeholder = "claude-3-5-sonnet-20241022";
    } else {
        urlInput.placeholder = "https://openrouter.ai/api/v1";
        modelInput.placeholder = "google/gemma-4-31b-it:free";
    }
}

async function testProviderConnection() {
    const prov = document.getElementById("setting-llm-provider").value;
    const url = document.getElementById("setting-base-url").value.trim();
    const key = document.getElementById("setting-api-key").value.trim();
    const model = document.getElementById("setting-model-name").value.trim();
    const statusEl = document.getElementById("model-connection-status");

    statusEl.textContent = "Connecting...";
    statusEl.className = "text-[11px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30";

    try {
        const resp = await fetch("/api/settings/test-llm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                provider: prov,
                base_url: url || null,
                api_key: key || null,
                model: model || null,
                test_prompt: "Ping"
            })
        });
        const res = await resp.json();
        if (res.connected) {
            statusEl.textContent = `Connected (${res.provider}) [${res.latency_ms}ms]`;
            statusEl.className = "text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-medium";
            alert(`✓ Connection successful!\nProvider: ${res.provider}\nLatency: ${res.latency_ms}ms`);
        } else {
            statusEl.textContent = "Local Server Offline";
            statusEl.className = "text-[11px] px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/30 font-medium";
            alert(`Connection status: Provider offline or unreachable at ${url || 'default endpoint'}. Using fallback.`);
        }
    } catch (e) {
        statusEl.textContent = "Error";
        alert("Connection check failed: " + e.message);
    }
}

async function runLiveModelTest() {
    const prov = document.getElementById("setting-llm-provider").value;
    const url = document.getElementById("setting-base-url").value.trim();
    const key = document.getElementById("setting-api-key").value.trim();
    const model = document.getElementById("setting-model-name").value.trim();
    const prompt = document.getElementById("test-prompt-input").value.trim() || "Hi Jordan, what do you specialize in?";

    const resBox = document.getElementById("model-test-result");
    const resModel = document.getElementById("test-res-model");
    const resLat = document.getElementById("test-res-latency");
    const resText = document.getElementById("test-res-text");

    resBox.classList.remove("hidden");
    resText.textContent = "Streaming model inference...";
    resLat.textContent = "...";
    resModel.textContent = model || prov;

    try {
        const resp = await fetch("/api/settings/test-llm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                provider: prov,
                base_url: url || null,
                api_key: key || null,
                model: model || null,
                test_prompt: prompt
            })
        });
        const res = await resp.json();

        resModel.textContent = res.model_used || model || prov;
        resLat.textContent = `${res.latency_ms}ms`;
        resText.textContent = `"${res.response || 'No text generated'}"`;
    } catch (e) {
        resText.textContent = "Test error: " + e.message;
    }
}

async function saveSettings() {
    const prov = document.getElementById("setting-llm-provider").value;
    const model = document.getElementById("setting-model-name").value;
    const baseUrl = document.getElementById("setting-base-url").value;
    const apiKey = document.getElementById("setting-api-key").value;

    const payload = {
        settings: {
            LLM_PROVIDER: prov,
            SELECTED_MODEL: model,
            OLLAMA_MODEL: prov === "ollama" ? model : undefined,
            CUSTOM_LLM_MODEL: prov === "custom" ? model : undefined,
            OLLAMA_BASE_URL: prov === "ollama" ? baseUrl : undefined,
            CUSTOM_LLM_BASE_URL: prov === "custom" ? baseUrl : undefined,
            API_KEY: apiKey,
            STT_ENGINE: document.getElementById("setting-stt-engine").value,
            TTS_ENGINE: document.getElementById("setting-tts-engine").value,
            DAILY_SPEND_CEILING_USD: document.getElementById("setting-spend-ceiling").value,
            SAFE_HARBOR_DROP_LIMIT: document.getElementById("setting-drop-limit").value
        }
    };

    Object.keys(payload.settings).forEach(k => {
        if (payload.settings[k] === undefined) delete payload.settings[k];
    });

    try {
        await fetch("/api/settings/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        alert("✓ Settings and model configuration saved successfully.");
    } catch (e) {
        alert("Failed to save settings: " + e.message);
    }
}

async function toggleKillSwitch() {
    const btn = document.getElementById("btn-kill-switch");
    const isCurrentlyActive = btn.classList.contains("bg-rose-600");
    const action = isCurrentlyActive ? "DEACTIVATE" : "ACTIVATE";

    if (!confirm(`Are you sure you want to ${action} the system-wide emergency Kill Switch?`)) return;

    try {
        const resp = await fetch("/api/settings/kill-switch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ trigger: !isCurrentlyActive, role: "PM" })
        });
        const data = await resp.json();
        updateKillSwitchUI(data.kill_switch_active);
    } catch (e) {
        alert("Failed to toggle kill switch: " + e.message);
    }
}

function updateKillSwitchUI(isActive) {
    const btn = document.getElementById("btn-kill-switch");
    const txt = document.getElementById("kill-switch-text");
    if (isActive) {
        btn.className = "flex items-center space-x-1.5 text-xs bg-rose-600 hover:bg-rose-500 text-white px-3 py-1.5 rounded-lg font-bold transition animate-pulse";
        txt.textContent = "KILL SWITCH: ACTIVE";
    } else {
        btn.className = "flex items-center space-x-1.5 text-xs bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1.5 rounded-lg font-medium transition";
        txt.textContent = "Kill Switch: Ready";
    }
}

// =========================================================================
// 10. VOICE STUDIO & REFERENCE AUDIO CLONING CONTROLLER
// =========================================================================
let registeredVoiceProfiles = [];
let activeVoiceProfile = null;
let selectedVoiceUploadFile = null;

async function loadVoiceProfiles() {
    try {
        const resp = await fetch("/api/voices/");
        const data = await resp.json();
        registeredVoiceProfiles = data.voices || [];
        activeVoiceProfile = data.active_voice || (registeredVoiceProfiles.length > 0 ? registeredVoiceProfiles[0] : null);

        updateVoiceBadges();
        renderVoicesLibrary();
        populateTesterVoicesDropdown();
    } catch (e) {
        console.error("Failed to load voice profiles:", e);
    }
}

function updateVoiceBadges() {
    if (!activeVoiceProfile) return;

    const pill = document.getElementById("active-voice-pill");
    if (pill) {
        pill.textContent = `${activeVoiceProfile.name} (${activeVoiceProfile.engine})`;
    }

    const webphoneBadge = document.getElementById("webphone-active-voice-badge");
    if (webphoneBadge) {
        webphoneBadge.textContent = `${activeVoiceProfile.name}`;
    }

    const instLabel = document.getElementById("inst-voice-label");
    if (instLabel) {
        const pitch = activeVoiceProfile.estimated_pitch_hz ? ` — ${activeVoiceProfile.estimated_pitch_hz}Hz` : '';
        instLabel.textContent = `${activeVoiceProfile.name} (${activeVoiceProfile.engine}${pitch})`;
    }
}

function renderVoicesLibrary() {
    const grid = document.getElementById("voices-list-grid");
    if (!grid) return;

    if (registeredVoiceProfiles.length === 0) {
        grid.innerHTML = `<div class="col-span-3 text-center py-6 text-slate-500 text-xs">No voice profiles found. Upload a sample above.</div>`;
        return;
    }

    grid.innerHTML = registeredVoiceProfiles.map(v => {
        const isActive = activeVoiceProfile && activeVoiceProfile.id === v.id;
        const isCustom = v.id.startsWith("ref_") || v.id.startsWith("voice-");
        const pitchHz = v.estimated_pitch_hz || 195.0;

        return `
            <div class="p-4 rounded-xl border ${isActive ? 'border-brand-500 bg-brand-500/5 shadow-lg shadow-brand-500/10' : 'border-dark-800 bg-dark-950'} space-y-3 flex flex-col justify-between">
                <div class="space-y-2">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-2">
                            <div class="w-8 h-8 rounded-lg ${isActive ? 'bg-brand-500/20 text-brand-cyan' : 'bg-dark-800 text-slate-400'} flex items-center justify-center">
                                <i data-lucide="waveform" class="w-4 h-4"></i>
                            </div>
                            <div>
                                <h4 class="text-xs font-bold text-white">${v.name}</h4>
                                <div class="text-[10px] text-slate-500 uppercase font-mono">${v.engine}</div>
                            </div>
                        </div>
                        ${isActive ? `
                            <span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                ACTIVE
                            </span>
                        ` : ''}
                    </div>

                    <p class="text-xs text-slate-400 line-clamp-2">${v.description || 'Custom cloned voice model'}</p>

                    <div class="flex items-center gap-3 text-[11px] text-slate-400 pt-1 border-t border-dark-800/80">
                        <span>Pitch: <b class="font-mono text-slate-200">${pitchHz} Hz</b></span>
                        ${v.reference_audio_url ? `<span>Ref: <a href="${v.reference_audio_url}" target="_blank" class="text-brand-cyan hover:underline font-mono">Audio File</a></span>` : ''}
                    </div>

                    ${v.reference_audio_url ? `
                        <div class="pt-1">
                            <audio controls src="${v.reference_audio_url}" class="h-6 w-full opacity-80"></audio>
                        </div>
                    ` : ''}
                </div>

                <div class="flex items-center gap-2 pt-2 border-t border-dark-800">
                    <button type="button" onclick="selectVoiceForTester('${v.id}')" class="flex-1 py-1.5 rounded-lg bg-dark-800 hover:bg-dark-700 text-slate-300 text-xs font-medium transition flex items-center justify-center gap-1">
                        <i data-lucide="play" class="w-3 h-3"></i>
                        <span>Test Voice</span>
                    </button>
                    ${!isActive ? `
                        <button type="button" onclick="activateVoice('${v.id}')" class="flex-1 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold transition">
                            Set Active
                        </button>
                    ` : `
                        <span class="flex-1 py-1.5 text-center text-xs text-emerald-400 font-semibold">Active Dialer Voice</span>
                    `}
                    ${isCustom ? `
                        <button type="button" onclick="deleteVoice('${v.id}')" class="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition" title="Delete voice">
                            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join("");

    lucide.createIcons();
}

function populateTesterVoicesDropdown() {
    const sel = document.getElementById("tester-voice-select");
    if (!sel) return;

    const currentVal = sel.value;
    sel.innerHTML = registeredVoiceProfiles.map(v => {
        const isAct = activeVoiceProfile && activeVoiceProfile.id === v.id;
        return `<option value="${v.id}" ${isAct ? 'selected' : ''}>${v.name} (${v.engine}) ${isAct ? '★ [ACTIVE]' : ''}</option>`;
    }).join("");

    if (currentVal && registeredVoiceProfiles.some(v => v.id === currentVal)) {
        sel.value = currentVal;
    }
}

function selectVoiceForTester(voiceId) {
    const sel = document.getElementById("tester-voice-select");
    if (sel) {
        sel.value = voiceId;
        sel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function handleVoiceFileSelected(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    selectedVoiceUploadFile = file;
    const badge = document.getElementById("selected-file-badge");
    const label = document.getElementById("dropzone-label");
    const nameInput = document.getElementById("voice-name-input");

    if (badge) {
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        badge.textContent = `Selected: ${file.name} (${sizeMb} MB)`;
        badge.classList.remove("hidden");
    }

    if (label) {
        label.textContent = "Voice file ready for acoustic extraction";
    }

    if (nameInput && !nameInput.value.trim()) {
        const cleanName = file.name.replace(/\.[^/.]+$/, "").replace(/[_-]/g, " ");
        nameInput.value = cleanName.charAt(0).toUpperCase() + cleanName.slice(1);
    }
}

async function submitVoiceUpload() {
    if (!selectedVoiceUploadFile) {
        alert("Please select or drop an audio file (.wav or .mp3) of a human voice first.");
        return;
    }

    const nameInput = document.getElementById("voice-name-input");
    const name = nameInput ? nameInput.value.trim() : "";
    if (!name) {
        alert("Please enter a name for this voice profile (e.g. 'Sarah (Enterprise Closer)').");
        return;
    }

    const desc = document.getElementById("voice-desc-input").value.trim();
    const engine = document.getElementById("voice-engine-select").value;
    const autoActivate = document.getElementById("voice-auto-activate").checked;
    const btn = document.getElementById("btn-upload-voice");

    const originalBtnHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Extracting Timbre & Pitch...</span>`;
    lucide.createIcons();

    try {
        const formData = new FormData();
        formData.append("file", selectedVoiceUploadFile);
        formData.append("name", name);
        formData.append("description", desc);
        formData.append("engine", engine);
        formData.append("set_active", autoActivate);

        const resp = await fetch("/api/voices/upload", {
            method: "POST",
            body: formData
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || "Upload failed");
        }

        const data = await resp.json();

        // Render acoustics extraction card
        const card = document.getElementById("voice-acoustics-card");
        if (card && data.acoustics) {
            document.getElementById("acoustics-duration").textContent = `${data.acoustics.duration_sec || 0}s`;
            document.getElementById("acoustics-pitch").textContent = `${data.acoustics.estimated_pitch_hz || 185} Hz`;
            document.getElementById("acoustics-energy").textContent = Math.round(data.acoustics.rms_energy || 0);
            document.getElementById("acoustics-rate").textContent = `${data.acoustics.sample_rate || 16000} Hz`;
            card.classList.remove("hidden");
        }

        // Reset inputs
        selectedVoiceUploadFile = null;
        document.getElementById("voice-file-input").value = "";
        const badge = document.getElementById("selected-file-badge");
        if (badge) badge.classList.add("hidden");
        document.getElementById("dropzone-label").textContent = "Click or drag & drop human voice sample here";

        await loadVoiceProfiles();

        if (data.profile && data.profile.id) {
            selectVoiceForTester(data.profile.id);
        }

        alert(data.message || `Successfully cloned voice '${name}'!`);
    } catch (e) {
        alert("Voice cloning upload failed: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
        lucide.createIcons();
    }
}

function setTesterPreset(text) {
    const input = document.getElementById("tester-text-input");
    if (input) input.value = text;
}

function onTesterVoiceChanged() {
    const audioCont = document.getElementById("tester-audio-container");
    if (audioCont) audioCont.classList.add("hidden");
}

async function runVoicePreview() {
    const sel = document.getElementById("tester-voice-select");
    const voiceId = sel ? sel.value : null;
    if (!voiceId) {
        alert("Please select a voice profile to test.");
        return;
    }

    const textInput = document.getElementById("tester-text-input");
    const text = textInput ? textInput.value.trim() : "";
    if (!text) {
        alert("Please enter some text for the voice to speak.");
        return;
    }

    const btn = document.getElementById("btn-preview-voice");
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Synthesizing Speech...</span>`;
    lucide.createIcons();

    try {
        const resp = await fetch(`/api/voices/${voiceId}/preview`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text })
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || "Synthesis failed");
        }

        const data = await resp.json();

        const player = document.getElementById("tester-audio-player");
        const title = document.getElementById("tester-audio-title");
        const cont = document.getElementById("tester-audio-container");

        if (player && cont) {
            player.src = data.audio_url;
            if (title) title.textContent = `${data.voice_name || 'Cloned Voice'} (${data.duration_sec}s)`;
            cont.classList.remove("hidden");
            player.play().catch(e => console.log("Browser autoplay blocked:", e));
        }
    } catch (e) {
        alert("Voice preview synthesis failed: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
        lucide.createIcons();
    }
}

async function activateSelectedTesterVoice() {
    const sel = document.getElementById("tester-voice-select");
    const voiceId = sel ? sel.value : null;
    if (!voiceId) return;
    await activateVoice(voiceId);
}

async function activateVoice(voiceId) {
    try {
        const resp = await fetch(`/api/voices/${voiceId}/activate`, { method: "POST" });
        if (!resp.ok) throw new Error("Failed to activate voice");
        await loadVoiceProfiles();
    } catch (e) {
        alert("Failed to activate voice profile: " + e.message);
    }
}

async function deleteVoice(voiceId) {
    if (!confirm("Are you sure you want to delete this custom voice profile?")) return;
    try {
        const resp = await fetch(`/api/voices/${voiceId}`, { method: "DELETE" });
        if (!resp.ok) throw new Error("Failed to delete voice profile");
        await loadVoiceProfiles();
    } catch (e) {
        alert("Failed to delete voice profile: " + e.message);
    }
}
