/**
 * Shadow Voice — Node.js Client SDK & CLI Bridge
 * Published on GitHub Packages: @muhdfaisalwork-gif/shadow-voice
 *
 * Programmatic SDK and execution bridge for Shadow Voice AI Voice Agent Platform:
 * - Built-in WebPhone & Softphone Hub (eyeBeam / X-Lite / Virtual SIP)
 * - Asterisk AudioSocket & VICIdial CTI Integration
 * - Autonomous Cognitive Brain & Evolution Engine
 * - Claude Desktop / Cursor MCP Server
 */

const { spawn } = require("child_process");
const path = require("path");

class ShadowVoiceClient {
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || process.env.SHADOW_VOICE_URL || "http://127.0.0.1:9000").replace(/\/$/, "");
    this.timeout = options.timeout || 30000;
  }

  async _request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {})
    };

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const res = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal
      });

      clearTimeout(timer);

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Shadow Voice API Error HTTP ${res.status}: ${text}`);
      }

      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return await res.json();
      }
      return await res.text();
    } catch (err) {
      clearTimeout(timer);
      throw err;
    }
  }

  // Health & Telemetry
  async getHealth() {
    return this._request("/api/health");
  }

  async getAnalyticsSummary() {
    return this._request("/api/analytics/summary");
  }

  // Calls & WebPhone
  async startCall(params = {}) {
    return this._request("/api/calls/start", {
      method: "POST",
      body: JSON.stringify({
        phone_number: params.phoneNumber || params.phone_number || "+1 (555) 019-2834",
        lead_id: params.leadId || params.lead_id || "LEAD_SDK_001",
        campaign_id: params.campaignId || params.campaign_id || "DEFAULT_SALES_V1"
      })
    });
  }

  async sendTurn(sessionId, text) {
    return this._request(`/api/calls/${encodeURIComponent(sessionId)}/turn`, {
      method: "POST",
      body: JSON.stringify({ text })
    });
  }

  async endCall(sessionId, disposition = "CALLBK") {
    return this._request(`/api/calls/${encodeURIComponent(sessionId)}/end`, {
      method: "POST",
      body: JSON.stringify({ disposition })
    });
  }

  // Softphone Hub (eyeBeam / X-Lite / Virtual SIP)
  async getSoftphoneStatus() {
    return this._request("/api/softphones/status");
  }

  async registerVirtualSip(params = {}) {
    return this._request("/api/softphones/virtual/register", {
      method: "POST",
      body: JSON.stringify({
        extension: params.extension || "1001",
        password: params.password || "1234",
        server_ip: params.serverIp || params.server_ip || "127.0.0.1",
        sip_port: params.sipPort || params.sip_port || 5060
      })
    });
  }

  // Cognitive Brain & Evolution
  async getBrainSummary() {
    return this._request("/api/brain/summary");
  }

  async triggerEvolution(limitCalls = 10, autoApprove = true) {
    return this._request("/api/brain/evolve", {
      method: "POST",
      body: JSON.stringify({
        limit_calls: limitCalls,
        auto_approve: autoApprove
      })
    });
  }

  // Voice Cloning Lab
  async getVoices() {
    return this._request("/api/voices");
  }

  // Subprocess runners
  static spawnDashboard(options = {}) {
    const rootDir = __dirname;
    const pythonExe = process.env.PYTHON_PATH || "python";
    const runScript = path.join(rootDir, "run.py");
    const port = options.port || process.env.PORT || "9000";

    return spawn(pythonExe, [runScript, "--port", String(port)], {
      cwd: rootDir,
      stdio: "inherit",
      env: { ...process.env, ...(options.env || {}) }
    });
  }

  static spawnMcp(options = {}) {
    const rootDir = __dirname;
    const pythonExe = process.env.PYTHON_PATH || "python";
    const mcpScript = path.join(rootDir, "run_mcp.py");

    return spawn(pythonExe, [mcpScript], {
      cwd: rootDir,
      stdio: ["inherit", "inherit", "inherit"],
      env: { ...process.env, ...(options.env || {}) }
    });
  }
}

module.exports = {
  ShadowVoiceClient,
  default: ShadowVoiceClient
};
