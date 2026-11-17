// Builds an installer for the system this runs on: a .dmg on macOS, an .exe
// installer on Windows. Each must be built on its own system because the
// Python engine is frozen into a native binary.
// Usage: node scripts/package.mjs [--dir]   --dir skips the installer and only makes the app folder
import { spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const engine = join(root, "engine");
const desktop = join(root, "apps", "desktop");
const win = process.platform === "win32";
const venvPy = join(engine, ".venv", win ? "Scripts" : "bin", win ? "python.exe" : "python");
const require = createRequire(import.meta.url);

function run(label, cmd, args, cwd) {
  console.log(`\n== ${label}`);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit" });
  if (r.error || r.status !== 0) {
    console.error(`Failed: ${label}${r.error ? ` (${r.error.message})` : ""}`);
    process.exit(r.status ?? 1);
  }
}

if (!existsSync(venvPy)) {
  console.error('Engine is not set up yet. Run "npm run engine:setup" first.');
  process.exit(1);
}

// 1. UI
const vite = join(dirname(require.resolve("vite/package.json")), "bin", "vite.js");
run("Build UI", process.execPath, [vite, "build"], join(root, "apps", "web"));

// 2. Engine -> engine/dist/quant-engine/
run("Install PyInstaller", venvPy, ["-m", "pip", "install", "-q", "-e", ".[build]"], engine);
rmSync(join(engine, "dist"), { recursive: true, force: true });
run("Freeze engine", venvPy, [
  "-m", "PyInstaller", "run_engine.py",
  "--name", "quant-engine",
  "--onedir", "--noconfirm", "--clean", "--log-level", "WARN",
  "--collect-submodules", "uvicorn",
  "--collect-submodules", "websockets",
  "--collect-submodules", "keyring",
  "--collect-all", "yfinance",
  "--collect-all", "curl_cffi",
  "--exclude-module", "tkinter",
  "--exclude-module", "matplotlib",
  "--exclude-module", "IPython",
  "--exclude-module", "pytest",
], engine);

// 3. Desktop app + installer -> release/
const builder = join(dirname(require.resolve("electron-builder/package.json")), "cli.js");
const args = [builder, win ? "--win" : "--mac", "--publish", "never"];   // releases are published by the GitHub workflow
if (process.argv.includes("--dir")) args.push("--dir");
run("Package desktop app", process.execPath, args, desktop);

console.log(`\nDone. Output is in ${join(root, "release")}`);
