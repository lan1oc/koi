import { invoke } from '@tauri-apps/api/core';

type BackendResponse<T> = {
  ok: boolean;
  data: T;
  error?: string | null;
};

export type InitializationProgress = {
  stage: 'paths' | 'config' | 'database' | 'resources' | 'runtime' | 'ready';
  status: 'starting' | 'completed' | 'error';
  completedSteps: number;
  totalSteps: number;
  percent: number;
  message: string;
  error?: string | null;
};

export type InitializationReport = {
  ready: boolean;
  elapsedMs: number;
};

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

function backendUnavailableError(error?: unknown) {
  const detail = error instanceof Error ? error.message : String(error ?? '');
  if (detail && !detail.includes('undefined')) {
    return new Error(`Tauri/Rust 后端调用不可用: ${detail}`);
  }
  return new Error('当前是浏览器预览环境，无法调用 Tauri/Rust 后端。请在 Tauri 桌面窗口中使用此功能。');
}

export async function callBackend<T>(command: string, payload: unknown = {}): Promise<T> {
  if (!isTauriRuntime()) {
    throw backendUnavailableError();
  }

  let response: BackendResponse<T>;
  try {
    response = await invoke<BackendResponse<T>>('call_backend', { command, payload });
  } catch (error) {
    throw backendUnavailableError(error);
  }

  if (!response.ok) {
    throw new Error(response.error ?? '后端调用失败');
  }
  return response.data;
}

export async function initializeRuntime(): Promise<InitializationReport> {
  if (!isTauriRuntime()) {
    return { ready: true, elapsedMs: 0 };
  }
  let response: BackendResponse<InitializationReport>;
  try {
    response = await invoke<BackendResponse<InitializationReport>>('initialize_runtime');
  } catch (error) {
    throw backendUnavailableError(error);
  }
  if (!response.ok || !response.data?.ready) {
    throw new Error(response.error ?? 'Runtime initialization did not reach ready state');
  }
  return response.data;
}

export async function signalRetestStop(sessionId: string, taskId?: string | null): Promise<boolean> {
  if (!isTauriRuntime()) {
    throw backendUnavailableError();
  }
  try {
    return await invoke<boolean>('signal_retest_stop', {
      sessionId,
      taskId: taskId || null,
    });
  } catch (error) {
    throw backendUnavailableError(error);
  }
}
