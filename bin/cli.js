#!/usr/bin/env node

/**
 * Shadow Voice — Node.js CLI Entry Point
 * Used by: npx @muhdfaisalwork-gif/shadow-voice [command]
 */

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const projectRoot = path.resolve(__dirname, "..");

function findPython() {
  if (process.env.PYTHON_PATH) return process.env.PYTHON_PATH;

  const venvPythonWin = path.join(projectRoot, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPythonWin)) return venvPythonWin;

  const venvPythonPosix = path.join(projectRoot, ".venv", "bin", "python");
  if (fs.existsSync(venvPythonPosix)) return venvPythonPosix;

  if (process.platform === "win32") {
    const localPython = path.join(
      process.env.LOCALAPPDATA || "",
      "Python",
      "bin",
      "python.exe"
    );
    if (fs.existsSync(localPython)) {
      return localPython;
    }
  }

  return "python";
}

function printHelp() {
  console.log(`
🎙️ Shadow Voice — AI Voice Agent Platform & Softphone Hub
Package: @muhdfaisalwork-gif/shadow-voice

Usage:
  npx @muhdfaisalwork-gif/shadow-voice [command] [options]
  shadow-voice [command] [options]

Commands:
  dashboard      Start the Shadow Voice Web Studio & API server (default port: 9000)
  mcp            Run the Claude Desktop / Cursor MCP stdio server
  demo           Run a simulated end-to-end outbound call flow
  seo            Run GitHub SEO Agent discoverability audit on this repository
  help           Show this help message

Options:
  --port <port>  Web Studio HTTP port (default: 9000)
  --host <host>  Bind host address (default: 0.0.0.0)

Examples:
  npx @muhdfaisalwork-gif/shadow-voice dashboard --port 9000
  npx @muhdfaisalwork-gif/shadow-voice mcp
  npx @muhdfaisalwork-gif/shadow-voice demo
  npx @muhdfaisalwork-gif/shadow-voice seo
`);
}

async function main() {
  const args = process.argv.slice(2);
  const command = args[0] || "dashboard";
  const pythonBin = findPython();

  if (command === "help" || command === "--help" || command === "-h") {
    printHelp();
    process.exit(0);
  }

  if (command === "mcp") {
    const mcpScript = path.join(projectRoot, "run_mcp.py");
    const child = spawn(pythonBin, [mcpScript], {
      cwd: projectRoot,
      stdio: ["inherit", "inherit", "inherit"],
      env: process.env
    });

    child.on("error", (err) => {
      console.error(`Failed to launch Shadow Voice MCP stdio server: ${err.message}`);
      process.exit(1);
    });

    child.on("exit", (code) => {
      process.exit(code || 0);
    });
    return;
  }

  if (command === "demo") {
    const demoScript = path.join(projectRoot, "scripts", "demo_call.py");
    const child = spawn(pythonBin, [demoScript, ...args.slice(1)], {
      cwd: projectRoot,
      stdio: "inherit",
      env: process.env
    });

    child.on("exit", (code) => {
      process.exit(code || 0);
    });
    return;
  }

  if (command === "seo" || command === "audit") {
    const localSeoAgent = path.resolve(projectRoot, "..", "github-seo-agent", "github_seo_agent.py");
    if (fs.existsSync(localSeoAgent)) {
      const child = spawn(
        pythonBin,
        [localSeoAgent, "audit", "--repo-dir", projectRoot, "--owner", "muhdfaisalwork-gif", "--name", "shadow-voice"],
        { cwd: projectRoot, stdio: "inherit", env: process.env }
      );
      child.on("exit", (code) => process.exit(code || 0));
      return;
    }
    console.log("Running via npx @muhdfaisalwork-gif/github-seo-agent...");
    const npxCmd = process.platform === "win32" ? "npx.cmd" : "npx";
    const child = spawn(npxCmd, ["@muhdfaisalwork-gif/github-seo-agent", "audit", "--repo-dir", projectRoot], {
      cwd: projectRoot,
      stdio: "inherit",
      env: process.env
    });
    child.on("exit", (code) => process.exit(code || 0));
    return;
  }

  if (command === "dashboard" || command === "server" || command === "start") {
    console.log("🎙️ Starting Shadow Voice Web Studio & Telephony Gateway...");
    const runScript = path.join(projectRoot, "run.py");
    const passArgs = args[0] === "dashboard" || args[0] === "server" || args[0] === "start" ? args.slice(1) : args;
    const child = spawn(pythonBin, [runScript, ...passArgs], {
      cwd: projectRoot,
      stdio: "inherit",
      env: process.env
    });

    child.on("error", (err) => {
      console.error(`Failed to launch Shadow Voice server (${pythonBin}): ${err.message}`);
      process.exit(1);
    });

    child.on("exit", (code) => {
      process.exit(code || 0);
    });
    return;
  }

  printHelp();
}

main().catch((err) => {
  console.error("Fatal Error:", err);
  process.exit(1);
});
