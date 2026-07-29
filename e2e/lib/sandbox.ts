import { execSync, spawn } from 'child_process';
import * as path from 'path';

export const SANDBOX_DIR = 'E:\\tmp\\qe-sandbox';
export const SANDBOX_URL = 'http://127.0.0.1:8010';
const VENV_PY = path.join(
  'E:\\Quantamental Models\\Quantamental Engine v2.0\\Quantamental Engine v2.0 Code Base',
  '.venv',
  'Scripts',
  'python.exe',
);

/** PID that owns :8010, or null. */
export function sandboxPid(): number | null {
  try {
    const out = execSync('netstat -ano', { encoding: 'utf8' });
    for (const line of out.split(/\r?\n/)) {
      if (line.includes(':8010') && line.includes('LISTENING')) {
        const pid = Number(line.trim().split(/\s+/).pop());
        if (pid > 0) return pid;
      }
    }
  } catch {
    /* netstat unavailable */
  }
  return null;
}

/** Hard-kill the sandbox engine (the degraded-state trigger). SANDBOX ONLY. */
export function sandboxKill(): boolean {
  const pid = sandboxPid();
  if (!pid) return false;
  execSync(`taskkill /F /PID ${pid}`, { encoding: 'utf8' });
  return true;
}

/** Relaunch the sandbox engine detached; resolves when /v3 answers 200. */
export async function sandboxLaunch(timeoutMs = 120_000): Promise<void> {
  if (sandboxPid()) return;
  const child = spawn(VENV_PY, ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8010'], {
    cwd: SANDBOX_DIR,
    detached: true,
    stdio: 'ignore',
  });
  child.unref();
  // P7 harness debt: sandbox-down.ps1 reads .sandbox.pid — without this
  // rewrite it reported "not running" while the relaunched engine still
  // held :8010 (swept manually twice in Phase 7). Best-effort.
  try {
    const fs = await import('fs');
    if (child.pid) {
      fs.writeFileSync(path.join(SANDBOX_DIR, '.sandbox.pid'), String(child.pid), 'ascii');
    }
  } catch { /* pid-file bookkeeping must never fail a relaunch */ }
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    await new Promise((r) => setTimeout(r, 2500));
    try {
      const res = await fetch(SANDBOX_URL + '/v3');
      if (res.status === 200) return;
    } catch {
      /* booting */
    }
  }
  throw new Error('[e2e] sandbox relaunch did not come up in time');
}
