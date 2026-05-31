import { callBackend } from './backend';

type OpenPathResponse = {
  success: boolean;
  message: string;
  path?: string;
};

export async function openBackendPath(path: string, setStatus: (status: string) => void) {
  if (!path.trim()) {
    setStatus('暂无可打开的输出路径');
    return;
  }

  try {
    const result = await callBackend<OpenPathResponse>('fs.open_path', { path: path.trim() });
    setStatus(result.path ? `${result.message}: ${result.path}` : result.message);
  } catch (error) {
    setStatus(`打开路径失败: ${error instanceof Error ? error.message : String(error)}`);
  }
}
