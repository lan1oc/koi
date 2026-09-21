import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputRoot = path.resolve(projectRoot, '..', 'output', 'playwright');
const baseUrl = process.env.KOI_E2E_BASE_URL || 'http://127.0.0.1:1420';
const minimumSplashLifecycleMs = 2_200;

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
  const state = {
    socketCount: 0,
    stopped: false,
    noticeStatusCalls: 0,
    noticeProgressHistory: [],
  };

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
    operations: options.agentDesktop ? {
      'operation-e2e-retest': {
        id: 'operation-e2e-retest',
        tool_name: 'retest_source_file',
        status: 'failed',
        risk: 'medium',
        arguments: { source_file: 'C:\\e2e\\notices\\beta.docx' },
        error: 'Verification endpoint was unavailable',
      },
    } : {},
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
    if (options.agentDesktop) {
      session.events.push(
        { id: 'legacy-token', type: 'token', title: 'Agent token', content: '碎', timestamp: now },
        { id: 'legacy-thought', type: 'thought', title: 'Agent reasoning', content: '根据报告证据确认待处理文件。', timestamp: now },
        { id: 'agent-chat', type: 'chat', title: 'Agent', content: '下一份通报准备复测。', timestamp: now, metadata: { role: 'agent' } },
        {
          id: 'native-operation', type: 'tool_result', title: '复测通报并生成报告',
          content: '目标接口当前不可达', timestamp: now, tone: 'warn',
          tool: { tool_id: 'retest_source_file', label: '复测通报并生成报告', status: 'failed', target: 'beta.docx' },
          metadata: { toolCallId: 'operation-e2e-retest' },
        },
      );
    }
    localStorage.setItem('koi.retest.sessions.v2', JSON.stringify({
      activeSessionId: session.sessionId,
      sessions: [session],
    }));
    sessionStorage.setItem('koi.retest.ui.active', session.sessionId);
  } else {
    localStorage.removeItem('koi.retest.sessions.v2');
    sessionStorage.removeItem('koi.retest.ui.active');
  }
  localStorage.removeItem('koi.notice.active-task.v1');

  async function backend(command, payload = {}) {
    const sessionId = String(payload.session_id || 'e2e-session');
    switch (command) {
      case 'app.version':
        return { version: '4.0.0' };
      case 'config.load':
        return { ui_settings: { dark_mode: true }, ui: { dark_mode: true }, report_counters: {} };
      case 'config.set_dark_mode':
        return { success: true };
      case 'doc.notice.process.start':
        state.noticeStatusCalls = 0;
        state.noticeProgressHistory = [1];
        return {
          success: true,
          task_id: 'notice-e2e-task',
          generation: 1,
          running: true,
          stopped: false,
          done: false,
          message: '任务已创建，正在启动...',
          progress: 1,
          logs: [],
          processed: 0,
          total_reports: 0,
        };
      case 'doc.notice.convert_failed_pdf': {
        const checkpoint = {
          file: 'C:\\e2e\\notices\\.koi_notice_process_state.json',
          size: 1024, sha256: 'a'.repeat(64),
        };
        const backup = {
          file: 'C:\\e2e\\notices\\.koi-original-' + 'b'.repeat(64) + '.docx',
          size: 4096, sha256: 'b'.repeat(64),
        };
        if (payload.action === 'preview_cleanup') {
          return { success: true, message: '发现 2 个可删除过程文件', cleanup_files: [checkpoint, backup], logs: [] };
        }
        if (payload.action === 'cleanup') {
          return { success: true, message: '清理完成：删除 2 个过程文件，失败 0 个', deleted_files: [checkpoint.file, backup.file], logs: ['已删除过程文件'] };
        }
        return {
          success: true, message: '转换完成：成功 1，删除原Word 1 个',
          output_files: ['C:\\e2e\\notices\\宁波测试有限公司存在跨站脚本攻击(XSS).pdf'],
          deleted_files: ['C:\\e2e\\notices\\宁波测试有限公司存在跨站脚本攻击(XSS).docx'],
          logs: ['PDF转换并校验成功'],
        };
      }
      case 'doc.notice.process.status': {
        const call = ++state.noticeStatusCalls;
        if (options.noticeScenario === 'reconnect-failure' && call >= 3 && call <= 5) {
          throw new Error(`simulated notice status disconnect ${call - 2}`);
        }
        const snapshots = {
          1: { progress: 3, message: '正在准备通报处理任务...', logs: ['正在准备通报处理任务...'] },
          2: { progress: 20, message: '步骤1/5: 通报改写', logs: ['正在准备通报处理任务...', '执行自动分类', '步骤1/5: 通报改写'] },
          6: { progress: 48, message: '步骤3/5: 生成责令整改通知书', logs: ['步骤1/5: 通报改写', '步骤2/5: 生成授权委托书', '步骤3/5: 生成责令整改通知书'] },
          7: { progress: 62, message: '步骤4/5: 处理处置文件', logs: ['步骤1/5: 通报改写', '步骤2/5: 生成授权委托书', '步骤3/5: 生成责令整改通知书', '步骤4/5: 处理处置文件'] },
          8: { progress: 76, message: '步骤5/5: 转换PDF', logs: ['步骤1/5: 通报改写', '步骤2/5: 生成授权委托书', '步骤3/5: 生成责令整改通知书', '步骤4/5: 处理处置文件', '步骤5/5: 转换PDF'] },
        };
        const snapshot = snapshots[call];
        if (snapshot) {
          state.noticeProgressHistory.push(snapshot.progress);
          return {
            success: true,
            task_id: 'notice-e2e-task',
            generation: 1,
            running: true,
            stopped: false,
            done: false,
            processed: 0,
            total_reports: 3,
            ...snapshot,
          };
        }
        const result = {
          success: false,
          message: '处理完成：处理 2 个文档，失败 1 个，需手动处理 1 个',
          target_path: 'C:\\e2e\\notices',
          total_reports: 3,
          processed: 2,
          generated_files: [
            'C:\\e2e\\notices\\关于宁波测试有限公司存在漏洞的通报.docx',
            'C:\\e2e\\notices\\处置文件模板.docx',
          ],
          manual_files: [{
            file: 'C:\\e2e\\notices\\损坏的复测报告.docx',
            reason: '通报候选不是有效 DOCX',
          }],
          failures: [{
            file: 'C:\\e2e\\notices\\损坏的复测报告.docx',
            reason: '通报候选不是有效 DOCX',
          }],
          pdf_outputs: ['C:\\e2e\\notices\\授权委托书.pdf'],
          logs: [
            '步骤1/5: 通报改写',
            '步骤2/5: 生成授权委托书',
            '步骤3/5: 生成责令整改通知书',
            '步骤4/5: 处理处置文件',
            '步骤5/5: 转换PDF',
            '[ERROR] 损坏的复测报告.docx: 通报候选不是有效 DOCX',
          ],
        };
        state.noticeProgressHistory.push(76);
        return {
          ...result,
          task_id: 'notice-e2e-task',
          generation: 1,
          running: false,
          stopped: false,
          done: true,
          progress: 76,
          result,
        };
      }
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
          operations: options.agentDesktop ? Object.values(agentSession(sessionId, false).operations) : [],
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
        {
          const requestedPath = String(payload.path || 'C:\\e2e');
          const normalizedPath = requestedPath.replace(/[\\/]+$/, '').toLowerCase();
          return {
            path: requestedPath,
            parent: normalizedPath === 'c:\\e2e\\notices' ? 'C:\\e2e' : null,
            entries: options.pdfScenario ? ['one.pdf', 'two.pdf'].map(name => ({
              name, path: 'C:\\e2e\\' + name, is_dir: false, extension: 'pdf',
              size: 1024, size_text: '1 KiB', modified: null, matches_filter: true,
            })) : normalizedPath === 'c:\\e2e' ? [{
              name: 'notices',
              path: 'C:\\e2e\\notices',
              is_dir: true,
              extension: '',
              size: null,
              size_text: '',
              modified: null,
              matches_filter: true,
            }] : [],
            separator: '\\',
            recovered_from: null,
          };
        }
      case 'fs.path_info':
        return { success: true, exists: true, is_dir: !String(payload.path || '').endsWith('.pdf'), path: String(payload.path || '') };
      case 'doc.pdf_extract.preview':
        return {
          success: true, message: '预览已加载', total_pages: 2,
          files: payload.pdf_files.map((file) => ({
            path: file, name: file.split('\\').at(-1), page_count: 1,
            pages: [{ page_number: 1, label: '第 1 页', width: 595, height: 842 }],
          })), logs: [],
        };
      case 'doc.pdf_extract.run':
        return { success: true, message: '已合并 2 页', output_file: 'C:\\e2e\\one_merged_pages.pdf', logs: [] };
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
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  const progressBar = page.getByRole('progressbar');
  await progressBar.waitFor({ state: 'visible' });
  const firstProgress = Number(await progressBar.getAttribute('aria-valuenow'));
  const firstWave = await page.locator('.wave-line polyline').first().getAttribute('points');
  const firstStreamValue = await page.locator('.stream-bars em').first().textContent();
  await page.waitForTimeout(400);
  const secondProgress = Number(await progressBar.getAttribute('aria-valuenow'));
  const secondWave = await page.locator('.wave-line polyline').first().getAttribute('points');
  const secondStreamValue = await page.locator('.stream-bars em').first().textContent();
  assert.ok(secondProgress > firstProgress, `Splash progress did not advance: ${firstProgress} -> ${secondProgress}`);
  assert.notEqual(secondWave, firstWave, 'Splash stream waveform did not change');
  assert.notEqual(secondStreamValue, firstStreamValue, 'Splash stream bar did not change');
  await page.locator('.splash-overlay').waitFor({ state: 'detached', timeout: 15_000 });
  const splashLifecycleMs = await page.evaluate(() => performance.now());
  assert.ok(
    splashLifecycleMs >= minimumSplashLifecycleMs,
    `Splash lifecycle was too short: ${Math.round(splashLifecycleMs)}ms`,
  );
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

async function testNoticeFiveStageReconnectAndFailure(browser) {
  const page = await bootPage(browser, { seedSession: false, noticeScenario: 'reconnect-failure' });
  try {
    await page.getByRole('button', { name: '文档处理', exact: true }).click();
    await page.getByRole('button', { name: '网信办', exact: true }).click();
    await page.getByRole('button', { name: /选择路径/ }).click();
    const dialog = page.getByRole('dialog', { name: '选择文件夹或压缩包' });
    await dialog.getByRole('button', { name: /notices/ }).click();
    await dialog.getByText('已选择: C:\\e2e\\notices', { exact: true }).waitFor();
    await dialog.getByRole('button', { name: '打开', exact: true }).click();
    await page.getByRole('button', { name: /开始处理/ }).click();
    await page.waitForFunction(() => window.__KOI_E2E__.calls.some((call) =>
      call.command === 'call_backend' && call.args?.command === 'doc.notice.process.start'));
    const [startPayload] = await backendCalls(page, 'doc.notice.process.start');
    assert.equal(startPayload.target_path, 'C:\\e2e\\notices');
    assert.equal(startPayload.auto_group, true);

    const logArea = page.locator('.notice-tools-page textarea[placeholder="等待开始处理..."]');
    await page.waitForFunction(() => document.querySelector('.notice-tools-page textarea')?.value.includes('步骤1/5'));
    await page.getByRole('button', { name: /重新连接任务/ }).waitFor({ timeout: 10_000 });
    const persistedTask = await page.evaluate(() => JSON.parse(localStorage.getItem('koi.notice.active-task.v1') || 'null'));
    assert.equal(persistedTask?.taskId, 'notice-e2e-task');
    assert.equal(persistedTask?.targetPath, 'C:\\e2e\\notices');

    await page.getByRole('button', { name: /重新连接任务/ }).click();
    await page.getByText('处理完成：处理 2 个文档，失败 1 个，需手动处理 1 个', { exact: true }).waitFor({ timeout: 10_000 });
    const logText = await logArea.inputValue();
    for (const stage of ['步骤1/5', '步骤2/5', '步骤3/5', '步骤4/5', '步骤5/5']) {
      assert.ok(logText.includes(stage), `notice log is missing ${stage}`);
    }
    assert.match(logText, /失败项:[\s\S]*损坏的复测报告\.docx -> 通报候选不是有效 DOCX/);
    await page.getByText('关于宁波测试有限公司存在漏洞的通报.docx', { exact: true }).waitFor();
    await page.getByText('授权委托书.pdf', { exact: true }).waitFor();
    await page.getByText('原因: 通报候选不是有效 DOCX', { exact: true }).waitFor();
    assert.equal(await page.locator('.notice-tools-page .progress-shell span').textContent(), '76%');
    const progressHistory = await page.evaluate(() => window.__KOI_E2E__.state.noticeProgressHistory);
    assert.deepEqual(progressHistory, [1, 3, 20, 48, 62, 76, 76]);
    assert.equal(await page.evaluate(() => localStorage.getItem('koi.notice.active-task.v1')), null);
  } finally {
    await page.close();
  }
}

async function testNoticePdfConversionAndCleanupPreview(browser) {
  const page = await bootPage(browser, { seedSession: false });
  try {
    await page.getByRole('button', { name: '文档处理', exact: true }).click();
    await page.getByRole('button', { name: '网信办', exact: true }).click();
    await page.getByRole('button', { name: /选择路径/ }).click();
    const picker = page.getByRole('dialog', { name: '选择文件夹或压缩包' });
    await picker.getByRole('button', { name: /notices/ }).click();
    await picker.getByText('已选择: C:\\e2e\\notices', { exact: true }).waitFor();
    await picker.getByRole('button', { name: '打开', exact: true }).click();
    await page.getByRole('button', { name: /转换PDF/ }).click();
    await page.getByText('转换完成：成功 1，删除原Word 1 个', { exact: true }).waitFor();
    const [conversion] = await backendCalls(page, 'doc.notice.convert_failed_pdf');
    assert.equal(conversion.scan_target, true);
    await page.getByRole('button', { name: /删除过程文件/ }).click();
    const cleanup = page.getByRole('dialog', { name: '删除通报过程文件' });
    await cleanup.getByText('.koi_notice_process_state.json', { exact: true }).waitFor();
    assert.equal((await backendCalls(page, 'doc.notice.convert_failed_pdf')).filter((payload) => payload.action === 'cleanup').length, 0);
    await cleanup.getByRole('button', { name: '取消', exact: true }).click();
    assert.equal((await backendCalls(page, 'doc.notice.convert_failed_pdf')).filter((payload) => payload.action === 'cleanup').length, 0);
    await page.getByRole('button', { name: /删除过程文件/ }).click();
    await cleanup.getByRole('button', { name: '确认删除 2 个文件', exact: true }).click();
    await page.getByText('清理完成：删除 2 个过程文件，失败 0 个', { exact: true }).waitFor();
    const [deletion] = (await backendCalls(page, 'doc.notice.convert_failed_pdf')).filter((payload) => payload.action === 'cleanup');
    assert.equal(deletion.cleanup_files.length, 2);
    assert.equal(deletion.cleanup_files[0].sha256, 'a'.repeat(64));
    assert.equal(await cleanup.count(), 0);
  } finally { await page.close(); }
}

async function testPdfBlankOutputUsesInputDirectory(browser) {
  const page = await bootPage(browser, { seedSession: false, pdfScenario: true });
  try {
    await page.getByRole('button', { name: '文档处理', exact: true }).click();
    await page.getByRole('button', { name: 'PDF处理', exact: true }).click();
    await page.locator('.pdf-extract-layout').getByRole('button', { name: /浏览/ }).first().click();
    const picker = page.getByRole('dialog', { name: '选择PDF文件' });
    await picker.getByRole('button', { name: /one.pdf/ }).click();
    await picker.getByRole('button', { name: /two.pdf/ }).click({ modifiers: ['Control'] });
    await picker.getByRole('button', { name: '打开', exact: true }).click();
    await page.getByRole('button', { name: /加载预览/ }).click();
    await page.getByRole('button', { name: /全选/ }).click();
    assert.equal(await page.getByPlaceholder(/留空保存到输入PDF/).inputValue(), '');
    await page.getByRole('button', { name: '开始提取', exact: true }).click();
    await page.getByText('已合并 2 页', { exact: true }).first().waitFor();
    const [request] = await backendCalls(page, 'doc.pdf_extract.run');
    assert.equal(Object.hasOwn(request, 'output_file'), false);
    assert.equal(request.page_selections.length, 2);
    await page.getByRole('button', { name: /打开本次结果/ }).click();
    const [opened] = await backendCalls(page, 'fs.open_path');
    assert.equal(opened.path, 'C:\\e2e\\one_merged_pages.pdf');
  } finally { await page.close(); }
}

async function testAgentDesktopLegacyEventsAndResponsiveLayout(browser) {
  const page = await bootPage(browser, { seedSession: true, agentDesktop: true });
  try {
    await openWorkbench(page);
    await page.locator('.retest-agent-inspector .retest-operation-card').waitFor();
    assert.equal(await page.getByText('Agent token', { exact: true }).count(), 0);
    assert.equal(await page.locator('.retest-agent-conversation-pane .retest-chat-row').count(), 1);
    assert.equal(await page.locator('.retest-agent-conversation-pane .retest-thought-fold').count(), 1);
    assert.match(await page.locator('.retest-agent-inspector .retest-operation-card summary').innerText(), /复测通报并生成报告/);
    assert.match(await page.locator('.retest-agent-inspector .retest-operation-card summary').innerText(), /失败/);
    await page.waitForFunction(() => {
      const saved = JSON.parse(localStorage.getItem('koi.retest.sessions.v2') || '{}');
      return saved.sessions?.[0]?.events?.every((event) => event.id !== 'legacy-token');
    });
    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('koi.retest.sessions.v2') || '{}'));
    assert.equal(saved.sessions?.[0]?.events?.some((event) => event.id === 'legacy-token'), false);
    fs.mkdirSync(outputRoot, { recursive: true });
    await page.screenshot({ path: path.join(outputRoot, 'agent-desktop-wide.png'), fullPage: true });

    await page.setViewportSize({ width: 820, height: 900 });
    await page.waitForTimeout(150);
    const geometry = await page.locator('.retest-agent-desktop').evaluate((element) => {
      const conversation = element.querySelector('.retest-agent-conversation-pane').getBoundingClientRect();
      const inspector = element.querySelector('.retest-agent-inspector').getBoundingClientRect();
      return { conversation: { bottom: conversation.bottom, left: conversation.left, right: conversation.right }, inspector: { top: inspector.top, left: inspector.left, right: inspector.right } };
    });
    assert.ok(geometry.inspector.top >= geometry.conversation.bottom - 1, 'Narrow layout should stack the inspector below the conversation');
    assert.ok(geometry.conversation.right <= geometry.inspector.right + 1, 'Conversation should not overflow the inspector width');
    await page.screenshot({ path: path.join(outputRoot, 'agent-desktop-narrow.png'), fullPage: true });
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
  await testNoticeFiveStageReconnectAndFailure(browser);
  await testNoticePdfConversionAndCleanupPreview(browser);
  await testPdfBlankOutputUsesInputDirectory(browser);
  await testAgentDesktopLegacyEventsAndResponsiveLayout(browser);

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
      'notice_five_stage_progress_reconnect_and_failure',
      'agent_desktop_legacy_token_migration_and_responsive_layout',
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
