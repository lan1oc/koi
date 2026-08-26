import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputRoot = path.resolve(projectRoot, '..', 'output', 'playwright');
const baseUrl = process.env.KOI_E2E_BASE_URL || 'http://127.0.0.1:1420';

async function launchBrowser() {
  try {
    return await chromium.launch({ headless: true, channel: 'chrome' });
  } catch (chromeError) {
    try {
      return await chromium.launch({ headless: true });
    } catch (chromiumError) {
      throw new Error(`Unable to launch Chrome (${chromeError}) or bundled Chromium (${chromiumError})`);
    }
  }
}

function installKoiMock(options) {
  const stage = options.stage || 'judgement';
  let callbackId = 1;
  let eventId = 1;
  const callbacks = new Map();
  const eventCallbacks = new Map();
  const calls = [];
  const state = { socketCount: 0, stopped: false };

  const resumeState = (checkpointStage = stage) => ({
    canContinue: true,
    targetDir: 'C:\\e2e\\notices',
    sourceFiles: ['C:\\e2e\\notices\\alpha.docx', 'C:\\e2e\\notices\\beta.docx'],
    nextIndex: 1,
    summaries: ['alpha complete'],
    reports: ['C:\\e2e\\reports\\alpha-retest.docx'],
    completionItems: [{
      sourceFile: 'C:\\e2e\\notices\\alpha.docx',
      sourceFileName: 'alpha.docx',
      status: 'clean',
      reportPath: 'C:\\e2e\\reports\\alpha-retest.docx',
    }],
    diskCompletedFileNames: ['alpha.docx'],
    diskCompletedReportEvidence: [{
      source_file: 'C:\\e2e\\notices\\alpha.docx',
      report_path: 'C:\\e2e\\reports\\alpha-retest.docx',
    }],
    allLogs: ['alpha exact checkpoint'],
    failedCount: 0,
    generateReports: true,
    blockedReason: `${checkpointStage} checkpoint ready`,
    blockedStage: checkpointStage,
    blockedTitle: `${checkpointStage} checkpoint`,
    currentFile: {
      index: 1,
      sourceFile: 'C:\\e2e\\notices\\beta.docx',
      sourceFileName: 'beta.docx',
      stage: checkpointStage,
      resumeSnapshot: {
        source_file: 'C:\\e2e\\notices\\beta.docx',
        stage: checkpointStage,
        report_path: 'C:\\e2e\\reports\\beta-retest.docx',
        evidence_id: `${checkpointStage}-snapshot-e2e`,
      },
    },
  });

  const agentSession = (sessionId, running = false) => ({
    session_id: sessionId,
    id: sessionId,
    generation: 3,
    running,
    stopped: state.stopped,
    status: running ? 'operation_running' : 'blocked',
    message: running ? 'Agent running' : `${stage} checkpoint ready`,
    auto_approve: true,
    events: [],
    logs: [],
    operations: {},
    approvals: {},
    resume_snapshot: running ? null : resumeState(stage).currentFile.resumeSnapshot,
  });

  if (options.seedSession) {
    const now = new Date().toISOString();
    const session = {
      sessionId: 'e2e-session',
      sessionTitle: 'KOI E2E checkpoint',
      targetDir: 'C:\\e2e\\notices',
      workspaceRoot: 'C:\\e2e\\notices',
      status: '复测已停止，可继续',
      progress: stage === 'report' ? 80 : 45,
      resultText: 'alpha exact result',
      log: 'alpha exact checkpoint',
      lastReportPath: 'C:\\e2e\\reports\\alpha-retest.docx',
      latestResultData: null,
      generateReports: true,
      createdAt: now,
      updatedAt: now,
      isRunning: false,
      resumeState: resumeState(stage),
      progressEvidence: {
        targetDir: 'C:\\e2e\\notices',
        completedFileNames: ['alpha.docx'],
        latestSourceFileName: 'beta.docx',
        hasCompletionSummary: false,
        toolCalls: 1,
        errors: 0,
        completedCountHint: 1,
        nextIndexHint: 1,
      },
      events: [{
        id: 'one-click-evidence',
        type: 'status',
        title: '一键复测启动',
        detail: 'generate reports',
        status: 'ok',
        timestamp: now,
        metadata: { phase: 'one_click_start', generateReports: true },
      }],
    };
    localStorage.setItem('koi.retest.sessions.v2', JSON.stringify({
      activeSessionId: session.sessionId,
      sessions: [session],
    }));
    sessionStorage.setItem('koi.retest.ui.active', session.sessionId);
  } else {
    localStorage.removeItem('koi.retest.sessions.v2');
    sessionStorage.removeItem('koi.retest.ui.active');
  }

  async function backend(command, payload = {}) {
    const sessionId = String(payload.session_id || 'e2e-session');
    switch (command) {
      case 'app.version':
        return { version: '4.0.0' };
      case 'config.load':
        return { ui_settings: { dark_mode: true }, ui: { dark_mode: true }, report_counters: {} };
      case 'config.set_dark_mode':
        return { success: true };
      case 'doc.retest.event_stream.info':
        return {
          success: true,
          host: '127.0.0.1',
          port: 18443,
          token: 'e2e-random-token',
          ws_url: 'ws://127.0.0.1:18443/?token=e2e-random-token',
        };
      case 'doc.retest.agent.start':
        state.stopped = false;
        return {
          success: true,
          active: true,
          running: true,
          blocked: false,
          session_id: sessionId,
          status: 'Agent running one-click queue',
          message: 'Agent running one-click queue',
          progress: 10,
          logs: ['one-click accepted'],
          agent_session: agentSession(sessionId, true),
        };
      case 'doc.retest.agent.status':
        return {
          success: true,
          active: true,
          running: false,
          stopped: state.stopped,
          blocked: true,
          session_id: sessionId,
          status: state.stopped ? '复测已停止，可继续' : `${stage} checkpoint ready`,
          message: state.stopped ? '复测已停止，可继续' : `${stage} checkpoint ready`,
          progress: stage === 'report' ? 80 : 45,
          resume_state: resumeState(stage),
          agent_session: agentSession(sessionId, false),
        };
      case 'doc.agent.status':
        return {
          success: true,
          active: true,
          running: false,
          session_id: sessionId,
          status: 'blocked',
          progress: stage === 'report' ? 80 : 45,
          agent_session: agentSession(sessionId, false),
        };
      case 'doc.agent.auto_approval.status':
        return { success: true, session_id: sessionId, enabled: true, auto_approve: true };
      case 'doc.agent.auto_approval.set':
        return { success: true, session_id: sessionId, enabled: Boolean(payload.enabled) };
      case 'doc.retest.agent.message':
      case 'doc.agent.message': {
        const message = String(payload.message || '');
        if (message === 'late-result') {
          await new Promise((resolve) => setTimeout(resolve, 900));
          return {
            success: true,
            active: true,
            running: false,
            status: 'completed',
            message: 'LATE_RESULT_SHOULD_NOT_RENDER',
            final_message: 'LATE_RESULT_SHOULD_NOT_RENDER',
            reply: 'LATE_RESULT_SHOULD_NOT_RENDER',
            progress: 100,
            agent_session: agentSession(sessionId, false),
          };
        }
        return {
          success: true,
          active: true,
          running: false,
          blocked: false,
          session_id: sessionId,
          status: 'completed',
          message: 'Resume accepted with exact checkpoint',
          final_message: 'Resume accepted with exact checkpoint',
          reply: 'Resume accepted with exact checkpoint',
          progress: 100,
          logs: ['agent response complete'],
          agent_session: agentSession(sessionId, false),
        };
      }
      case 'doc.retest.agent.stop':
      case 'doc.agent.stop':
        state.stopped = true;
        return {
          success: true,
          stopped: true,
          active: true,
          running: false,
          blocked: true,
          session_id: sessionId,
          status: '复测已停止，可继续',
          message: '复测已停止，可继续',
          progress: 45,
          resume_state: resumeState(stage),
          agent_session: agentSession(sessionId, false),
        };
      case 'doc.retest.run_one.status':
        return {
          success: false,
          done: true,
          running: false,
          stopped: true,
          progress: 45,
          message: 'Stopped task snapshot',
          logs: ['stopped checkpoint retained'],
          resume_state: resumeState(stage),
        };
      case 'doc.retest.list_files':
        return {
          success: true,
          target_dir: String(payload.target_dir || 'C:\\e2e\\notices'),
          source_files: ['C:\\e2e\\notices\\alpha.docx', 'C:\\e2e\\notices\\beta.docx'],
          completed_source_file_names: ['alpha.docx'],
          existing_report_evidence: resumeState(stage).diskCompletedReportEvidence,
          next_index_hint: 1,
          next_source_file: 'C:\\e2e\\notices\\beta.docx',
          logs: ['two exact source paths'],
        };
      case 'fs.roots':
        return {
          cwd: 'C:\\e2e',
          home: 'C:\\e2e',
          roots: [{ path: 'C:\\', name: 'C:', type: 'drive' }],
          shortcuts: [],
        };
      case 'fs.list_dir':
        return {
          path: String(payload.path || 'C:\\e2e'),
          parent: null,
          entries: [],
          separator: '\\',
          recovered_from: null,
        };
      case 'fs.path_info':
        return { success: true, exists: true, is_dir: true, path: String(payload.path || '') };
      case 'fs.open_path':
      case 'fs.open_url':
        return { success: true };
      default:
        return { success: true, running: false, done: true, progress: 100, logs: [], items: [] };
    }
  }

  const NativeWebSocket = window.WebSocket;
  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.listeners = new Map();
      state.socketCount += 1;
      const connectionNumber = state.socketCount;
      setTimeout(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.dispatch('open', {});
        if (connectionNumber === 1) {
          setTimeout(() => {
            this.readyState = FakeWebSocket.CLOSED;
            this.dispatch('close', { code: 1006, reason: 'forced e2e reconnect' });
          }, 50);
        }
      }, 10);
    }

    addEventListener(type, listener) {
      const listeners = this.listeners.get(type) || [];
      listeners.push(listener);
      this.listeners.set(type, listeners);
    }

    removeEventListener(type, listener) {
      const listeners = this.listeners.get(type) || [];
      this.listeners.set(type, listeners.filter((item) => item !== listener));
    }

    dispatch(type, event) {
      for (const listener of this.listeners.get(type) || []) listener.call(this, event);
      if (typeof this[`on${type}`] === 'function') this[`on${type}`](event);
    }

    send() {}

    close() {
      this.readyState = FakeWebSocket.CLOSED;
      this.dispatch('close', { code: 1000, reason: 'client close' });
    }
  }

  function RoutedWebSocket(url, protocols) {
    if (String(url).startsWith('ws://127.0.0.1:18443/')) return new FakeWebSocket(url);
    return protocols === undefined ? new NativeWebSocket(url) : new NativeWebSocket(url, protocols);
  }
  for (const key of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) RoutedWebSocket[key] = NativeWebSocket[key];
  RoutedWebSocket.prototype = NativeWebSocket.prototype;
  window.WebSocket = RoutedWebSocket;

  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} };
  window.__TAURI_INTERNALS__ = {
    metadata: { currentWindow: { label: 'main' }, currentWebview: { label: 'main' } },
    transformCallback(callback, once = false) {
      const id = callbackId++;
      callbacks.set(id, { callback, once });
      Object.defineProperty(window, `_${id}`, {
        configurable: true,
        value: (payload) => callback?.(payload),
      });
      return id;
    },
    unregisterCallback(id) {
      callbacks.delete(id);
      delete window[`_${id}`];
    },
    convertFileSrc(value) {
      return String(value);
    },
    async invoke(command, args = {}) {
      calls.push({ command, args: JSON.parse(JSON.stringify(args || {})), at: Date.now() });
      if (command === 'initialize_runtime') {
        return { ok: true, data: { ready: true, elapsedMs: 1 }, error: null };
      }
      if (command === 'plugin:app|version') return '4.0.0';
      if (command === 'plugin:event|listen') {
        const id = eventId++;
        eventCallbacks.set(id, { event: args.event, callbackId: args.handler });
        return id;
      }
      if (command === 'plugin:event|unlisten') {
        eventCallbacks.delete(args.eventId);
        return null;
      }
      if (command === 'signal_retest_stop') {
        state.stopped = true;
        return true;
      }
      if (command === 'call_backend') {
        return { ok: true, data: await backend(args.command, args.payload || {}), error: null };
      }
      if (command === 'sync_window_region' || command === 'toggle_app_maximize') return false;
      if (command.startsWith('plugin:window|')) return command.endsWith('is_visible');
      return null;
    },
  };

  window.__KOI_E2E__ = {
    calls,
    state,
    resetCalls() {
      calls.splice(0, calls.length);
    },
  };
}

async function waitForServer(url, process) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (process?.exitCode != null) throw new Error(`Vite exited with code ${process.exitCode}`);
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Vite did not become ready at ${url}`);
}

function startVite() {
  if (process.env.KOI_E2E_BASE_URL) return null;
  const vite = path.join(projectRoot, 'node_modules', 'vite', 'bin', 'vite.js');
  return spawn(process.execPath, [vite, '--host', '127.0.0.1', '--port', '1420', '--strictPort'], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
}

async function bootPage(browser, options) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  await page.addInitScript(installKoiMock, options);
  await page.goto(baseUrl);
  await page.locator('.splash-overlay').waitFor({ state: 'detached', timeout: 15_000 });
  return page;
}

async function openWorkbench(page) {
  await page.getByRole('button', { name: 'AI测试', exact: true }).click();
  await page.getByRole('button', { name: '测试工作台', exact: true }).click();
  await page.getByPlaceholder(/直接告诉 Agent/).waitFor({ state: 'visible' });
}

function backendCalls(page, command) {
  return page.evaluate((target) => window.__KOI_E2E__.calls
    .filter((call) => call.command === 'call_backend' && call.args?.command === target)
    .map((call) => call.args.payload), command);
}

async function testFirstOneClick(browser) {
  const page = await bootPage(browser, { seedSession: false });
  try {
    await page.getByRole('button', { name: '文档处理', exact: true }).click();
    await page.getByRole('button', { name: '网信办', exact: true }).click();
    await page.getByRole('button', { name: '复测一键出', exact: true }).click();
    await page.getByRole('button', { name: /选择目录/ }).click();
    const dialog = page.getByRole('dialog', { name: '选择通报目录' });
    await dialog.getByPlaceholder('输入路径后按 Enter 跳转').fill('C:\\e2e\\notices');
    await dialog.getByRole('button', { name: '跳转', exact: true }).click();
    await dialog.getByText('已选择: C:\\e2e\\notices', { exact: true }).waitFor();
    await dialog.getByRole('button', { name: '打开', exact: true }).click();
    await page.getByRole('button', { name: 'AI Agent 复测', exact: true }).click();
    await page.waitForFunction(() => window.__KOI_E2E__.calls.some((call) =>
      call.command === 'call_backend' && call.args?.command === 'doc.retest.agent.start'));
    const [payload] = await backendCalls(page, 'doc.retest.agent.start');
    assert.equal(payload.target_dir, 'C:\\e2e\\notices');
    assert.equal(payload.generate_reports, true);
    assert.equal(payload.one_click_queue, true);
    assert.equal(payload.use_progress_evidence, true);
    assert.equal(payload.force_resume, false);
  } finally {
    await page.close();
  }
}

async function testCheckpoint(browser, stage, chat) {
  const page = await bootPage(browser, { seedSession: true, stage });
  try {
    await openWorkbench(page);
    if (stage === 'judgement') {
      await page.waitForFunction(() => window.__KOI_E2E__.state.socketCount >= 2, null, { timeout: 10_000 });
    }
    await page.evaluate(() => window.__KOI_E2E__.resetCalls());
    if (chat) {
      await page.getByPlaceholder(/直接告诉 Agent/).fill('继续');
      await page.getByRole('button', { name: '发送', exact: true }).click();
    } else {
      await page.getByRole('button', { name: '继续', exact: true }).first().click();
    }
    await page.waitForFunction(() => window.__KOI_E2E__.calls.some((call) =>
      call.command === 'call_backend' && call.args?.command === 'doc.retest.agent.message'));
    const payloads = await backendCalls(page, 'doc.retest.agent.message');
    const payload = payloads.at(-1);
    assert.equal(payload.force_resume, true);
    if (chat) assert.equal(payload.message, '继续');
    const context = JSON.stringify(payload.frontend_context || {});
    assert.match(context, /C:\\\\e2e\\\\notices\\\\beta\.docx/);
    assert.ok(context.includes(`\"stage\":\"${stage}\"`), `missing ${stage} stage in frontend context`);
    assert.ok(context.includes(`${stage}-snapshot-e2e`), `missing ${stage} snapshot evidence`);
  } finally {
    await page.close();
  }
}

async function testStopDiscardsLateResult(browser) {
  const page = await bootPage(browser, { seedSession: true, stage: 'report' });
  try {
    await openWorkbench(page);
    await page.evaluate(() => window.__KOI_E2E__.resetCalls());
    await page.getByPlaceholder(/直接告诉 Agent/).fill('late-result');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.waitForFunction(() => window.__KOI_E2E__.calls.some((call) =>
      call.command === 'call_backend' && ['doc.retest.agent.message', 'doc.agent.message'].includes(call.args?.command)));
    await page.getByRole('button', { name: '停止', exact: true }).click();
    await page.waitForFunction(() => window.__KOI_E2E__.calls.some((call) => call.command === 'signal_retest_stop'));
    await page.waitForTimeout(1_200);
    assert.equal(await page.locator('body').innerText().then((text) => text.includes('LATE_RESULT_SHOULD_NOT_RENDER')), false);
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('koi.retest.sessions.v2') || '{}'));
    const session = stored.sessions?.find((item) => item.sessionId === 'e2e-session');
    assert.match(session?.status || '', /停止/);
    assert.equal(session?.isRunning, false);
    assert.equal(session?.resumeState?.currentFile?.stage, 'report');
  } finally {
    await page.close();
  }
}

const viteProcess = startVite();
let browser;
try {
  await waitForServer(baseUrl, viteProcess);
  browser = await launchBrowser();
  await testFirstOneClick(browser);
  await testCheckpoint(browser, 'judgement', false);
  await testCheckpoint(browser, 'report', false);
  await testCheckpoint(browser, 'report', true);
  await testStopDiscardsLateResult(browser);

  fs.mkdirSync(outputRoot, { recursive: true });
  fs.writeFileSync(path.join(outputRoot, 'koi-4.0.0-retest-e2e-ci.json'), `${JSON.stringify({
    format: 'koi-playwright-ci-v1',
    version: '4.0.0',
    passed: true,
    checks: [
      'first_one_click',
      'websocket_reconnect',
      'continue_judgement_checkpoint',
      'continue_report_checkpoint',
      'chat_continue_report_checkpoint',
      'stop_discards_late_result',
    ],
  }, null, 2)}\n`);
  console.log('Playwright retest workflow checks passed.');
} catch (error) {
  fs.mkdirSync(outputRoot, { recursive: true });
  if (browser) {
    const pages = browser.contexts().flatMap((context) => context.pages());
    if (pages[0]) await pages[0].screenshot({ path: path.join(outputRoot, 'koi-e2e-failure.png'), fullPage: true }).catch(() => {});
  }
  throw error;
} finally {
  await browser?.close();
  viteProcess?.kill();
}
