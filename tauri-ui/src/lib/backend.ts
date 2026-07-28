import { invoke } from '@tauri-apps/api/core';

type BackendResponse<T> = {
  ok: boolean;
  data: T;
  error?: string | null;
};

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

function backendUnavailableError(error?: unknown) {
  const detail = error instanceof Error ? error.message : String(error ?? '');
  if (detail && !detail.includes('undefined')) {
    return new Error(`Tauri/Python 后端调用不可用: ${detail}`);
  }
  return new Error('当前是浏览器预览环境，无法调用 Tauri/Python 后端。请在 Tauri 桌面窗口中使用此功能。');
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

export async function resetBackendSidecar(): Promise<boolean> {
  if (!isTauriRuntime()) {
    throw backendUnavailableError();
  }
  try {
    return await invoke<boolean>('reset_backend_sidecar');
  } catch (error) {
    throw backendUnavailableError(error);
  }
}
