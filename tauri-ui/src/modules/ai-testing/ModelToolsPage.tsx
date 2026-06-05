import { useEffect, useMemo, useState } from 'react';
import { callBackend } from '../../lib/backend';

type SelectOption = string | { value: string; label: string };

type RetestAiProfile = {
  id: string;
  name?: string;
  provider?: string;
  base_url?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  context_window?: number;
  last_updated?: string;
  api_key_configured?: boolean;
  api_key_masked?: string;
};

type RetestAiConfig = {
  enabled?: boolean;
  active_profile_id?: string;
  active_profile?: RetestAiProfile;
  profiles?: RetestAiProfile[];
  provider?: string;
  base_url?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  context_window?: number;
  last_updated?: string;
  api_key_configured?: boolean;
  api_key_masked?: string;
};

type RetestAiConfigResponse = {
  success: boolean;
  message: string;
  config?: RetestAiConfig;
};

type RetestAiTestResponse = {
  success: boolean;
  message: string;
  provider?: string;
  model?: string;
  reply?: string;
  elapsed_ms?: number;
  error?: string;
};

type RetestAiKeyStatusResponse = {
  success: boolean;
  message: string;
  provider?: string;
  model?: string;
  endpoint?: string;
  status_code?: number;
  elapsed_ms?: number;
  summary?: Record<string, unknown>;
  data?: unknown;
  free_model_limits?: Record<string, unknown>;
  error?: string;
};

type RetestToolSpec = {
  tool_id: string;
  label: string;
  category: string;
  risk: string;
  tags?: string[];
  requires?: string[];
  description?: string;
};

type RetestToolsListResponse = {
  success: boolean;
  message: string;
  tools?: RetestToolSpec[];
  categories?: Record<string, number>;
};

type RetestExternalTool = {
  id: string;
  name?: string;
  installed?: boolean;
  command?: string[];
  source?: string;
  installable?: boolean;
  root?: string;
};

type RetestToolsStatusResponse = {
  success: boolean;
  message: string;
  tool_root?: string;
  tools?: RetestExternalTool[];
  logs?: string[];
};

type RetestToolsInstallResponse = {
  success: boolean;
  message: string;
  tool_root?: string;
  installed?: Array<{ id: string; installed?: boolean; command?: string[] }>;
  failures?: Array<{ tool: string; reason: string }>;
  logs?: string[];
  status?: RetestToolsStatusResponse;
};

const OPENROUTER_DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1';
const OPENROUTER_FREE_MODEL = 'openrouter/free';

const RETEST_AI_PROVIDER_OPTIONS = [
  { value: 'openai', label: 'OpenAI 标准' },
  { value: 'anthropic', label: 'Anthropic 标准' },
  { value: 'openrouter', label: 'OpenRouter 免费路由' },
];

function providerLabel(provider?: string) {
  if (provider === 'anthropic') return 'Anthropic';
  if (provider === 'openrouter') return 'OpenRouter';
  return 'OpenAI';
}

function providerBaseUrlPlaceholder(provider?: string) {
  if (provider === 'anthropic') return 'https://api.anthropic.com/v1';
  if (provider === 'openrouter') return OPENROUTER_DEFAULT_BASE_URL;
  return 'https://api.openai.com/v1';
}

function providerModelPlaceholder(provider?: string) {
  if (provider === 'anthropic') return 'claude-3-5-sonnet-latest';
  if (provider === 'openrouter') return OPENROUTER_FREE_MODEL;
  return 'gpt-4o-mini';
}

function defaultProfileName(provider?: string) {
  if (provider === 'anthropic') return 'Anthropic';
  if (provider === 'openrouter') return 'OpenRouter 免费路由';
  return 'OpenAI';
}

function jsonPreview(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? '');
  }
}

function formatOpenRouterKeyStatus(result: RetestAiKeyStatusResponse) {
  const lines: string[] = [];
  lines.push(result.message || (result.success ? 'OpenRouter Key 状态已读取' : 'OpenRouter Key 状态查询失败'));
  const meta = [result.provider, result.model, result.endpoint].filter(Boolean).join(' / ');
  if (meta) lines.push(`目标: ${meta}`);
  if (typeof result.elapsed_ms === 'number') lines.push(`耗时: ${result.elapsed_ms}ms`);
  if (result.free_model_limits) {
    const limits = result.free_model_limits;
    lines.push(`免费模型限制: ${limits.requests_per_minute ?? 20} 次/分钟；未购买积分 ${limits.daily_without_credits ?? 50} 次/天；购买至少 $${limits.credits_threshold_usd ?? 10} 后 ${limits.daily_with_credits ?? 1000} 次/天`);
  }
  if (result.summary && Object.keys(result.summary).length) {
    lines.push(`摘要:\n${jsonPreview(result.summary)}`);
  }
  if (result.data) {
    lines.push(`OpenRouter 返回:\n${jsonPreview(result.data).slice(0, 5000)}`);
  }
  if (result.error) lines.push(`错误: ${result.error}`);
  return lines.join('\n\n');
}

function ConfigSelectInput({ options, value, onChange }: { options: SelectOption[]; value?: string; onChange?: (value: string) => void }) {
  return (
    <select className="koi-input" value={value} onChange={(event) => onChange?.(event.target.value)}>
      {options.map((option) => {
        const item = typeof option === 'string' ? { value: option, label: option } : option;
        return <option key={item.value} value={item.value}>{item.label}</option>;
      })}
    </select>
  );
}

function makeFallbackRetestAiProfile(config?: RetestAiConfig): RetestAiProfile {
  return {
    id: config?.active_profile_id || 'default',
    name: '默认 OpenAI',
    provider: config?.provider || 'openai',
    base_url: config?.base_url || '',
    model: config?.model || '',
    temperature: config?.temperature ?? 0.1,
    max_tokens: config?.max_tokens ?? 800,
    context_window: config?.context_window ?? 128000,
    api_key_configured: Boolean(config?.api_key_configured),
    api_key_masked: config?.api_key_masked || '',
  };
}

export function ModelToolsPage() {
  const [agentEnabled, setAgentEnabled] = useState(false);
  const [profiles, setProfiles] = useState<RetestAiProfile[]>([]);
  const [activeProfileId, setActiveProfileId] = useState('default');
  const [profileName, setProfileName] = useState('');
  const [aiProvider, setAiProvider] = useState('openai');
  const [aiBaseUrl, setAiBaseUrl] = useState('');
  const [aiApiKey, setAiApiKey] = useState('');
  const [aiModel, setAiModel] = useState('');
  const [aiTemperature, setAiTemperature] = useState('0.1');
  const [aiMaxTokens, setAiMaxTokens] = useState('800');
  const [aiContextWindow, setAiContextWindow] = useState('128000');
  const [aiKeyConfigured, setAiKeyConfigured] = useState(false);
  const [clearAiKey, setClearAiKey] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  const [newProfileProvider, setNewProfileProvider] = useState('openai');
  const [status, setStatus] = useState('正在读取 AI 配置...');
  const [isBusy, setIsBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [keyStatusBusy, setKeyStatusBusy] = useState(false);
  const [keyStatusText, setKeyStatusText] = useState('');
  const [installBusy, setInstallBusy] = useState(false);
  const [toolCatalog, setToolCatalog] = useState<RetestToolSpec[]>([]);
  const [toolCategories, setToolCategories] = useState<Record<string, number>>({});
  const [externalToolStatus, setExternalToolStatus] = useState<RetestToolsStatusResponse | null>(null);
  const [toolInstallLog, setToolInstallLog] = useState('');

  const applyAiConfig = (config?: RetestAiConfig) => {
    const fallback = makeFallbackRetestAiProfile(config);
    const loadedProfiles = config?.profiles?.length ? config.profiles : [config?.active_profile ?? fallback];
    const activeId = config?.active_profile_id || config?.active_profile?.id || loadedProfiles[0]?.id || fallback.id;
    const activeProfile = loadedProfiles.find((profile) => profile.id === activeId) ?? config?.active_profile ?? loadedProfiles[0] ?? fallback;
    const nextProfiles = loadedProfiles.some((profile) => profile.id === activeProfile.id) ? loadedProfiles : [activeProfile, ...loadedProfiles];

    setAgentEnabled(Boolean(config?.enabled));
    setProfiles(nextProfiles);
    setActiveProfileId(activeProfile.id || activeId);
    setProfileName(activeProfile.name || activeProfile.id || '默认 OpenAI');
    setAiProvider(activeProfile.provider || 'openai');
    setAiBaseUrl(activeProfile.base_url || '');
    setAiModel(activeProfile.model || '');
    setAiTemperature(String(activeProfile.temperature ?? 0.1));
    setAiMaxTokens(String(activeProfile.max_tokens ?? 800));
    setAiContextWindow(String(activeProfile.context_window ?? 128000));
    setAiKeyConfigured(Boolean(activeProfile.api_key_configured));
    setAiApiKey('');
    setClearAiKey(false);
    setKeyStatusText('');
  };

  const loadRetestAgentConfig = async () => {
    setIsBusy(true);
    try {
      const [configResult, toolsResult, externalResult] = await Promise.all([
        callBackend<RetestAiConfigResponse>('doc.retest.ai_config.get', {}),
        callBackend<RetestToolsListResponse>('doc.retest.tools.list', {}),
        callBackend<RetestToolsStatusResponse>('doc.retest.tools.status', {}),
      ]);
      applyAiConfig(configResult.config);
      setToolCatalog(toolsResult.tools ?? []);
      setToolCategories(toolsResult.categories ?? {});
      setExternalToolStatus(externalResult);
      setStatus([configResult.message, toolsResult.message, externalResult.message].filter(Boolean).join(' / ') || '配置已加载');
    } catch (error) {
      setStatus(`AI 配置读取失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  useEffect(() => {
    void loadRetestAgentConfig();
  }, []);

  const buildRetestAgentPayload = () => ({
    profile_id: activeProfileId,
    provider: aiProvider,
    base_url: aiBaseUrl.trim(),
    api_key: aiApiKey.trim(),
    clear_api_key: clearAiKey,
    model: aiModel.trim(),
    temperature: Number(aiTemperature || 0.1),
    max_tokens: Number(aiMaxTokens || 800),
    context_window: Number(aiContextWindow || 128000),
  });

  const changeAiProvider = (provider: string) => {
    const previousProvider = aiProvider;
    setAiProvider(provider);
    setKeyStatusText('');
    if (provider === 'openrouter') {
      const base = aiBaseUrl.trim();
      const model = aiModel.trim();
      if (!base || base === providerBaseUrlPlaceholder(previousProvider)) {
        setAiBaseUrl(OPENROUTER_DEFAULT_BASE_URL);
      }
      if (!model || model === providerModelPlaceholder(previousProvider)) {
        setAiModel(OPENROUTER_FREE_MODEL);
      }
      if (!profileName.trim() || profileName.trim() === defaultProfileName(previousProvider)) {
        setProfileName(defaultProfileName(provider));
      }
      return;
    }
    if (aiBaseUrl.trim() === OPENROUTER_DEFAULT_BASE_URL) {
      setAiBaseUrl('');
    }
    if (aiModel.trim() === OPENROUTER_FREE_MODEL) {
      setAiModel('');
    }
    if (!profileName.trim() || profileName.trim() === defaultProfileName(previousProvider)) {
      setProfileName(defaultProfileName(provider));
    }
  };

  const saveRetestAgentConfig = async () => {
    setIsBusy(true);
    try {
      const result = await callBackend<RetestAiConfigResponse>('doc.retest.ai_config.set', {
        action: 'save_profile',
        enabled: agentEnabled,
        name: profileName.trim() || activeProfileId,
        ...buildRetestAgentPayload(),
      });
      applyAiConfig(result.config);
      setStatus(result.message || (result.success ? 'AI 配置已保存' : 'AI 配置保存失败'));
    } catch (error) {
      setStatus(`AI 配置保存失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const testRetestAgentConfig = async () => {
    setTestBusy(true);
    setStatus('正在测试模型通信...');
    try {
      const result = await callBackend<RetestAiTestResponse>('doc.retest.ai_config.test', buildRetestAgentPayload());
      const modelText = [result.provider, result.model].filter(Boolean).join(' / ');
      const elapsedText = typeof result.elapsed_ms === 'number' ? `，耗时 ${result.elapsed_ms}ms` : '';
      const replyText = result.reply ? `，返回：${result.reply.slice(0, 240)}` : '';
      setStatus(`${result.success ? '模型测试成功' : '模型测试失败'}${modelText ? `（${modelText}）` : ''}${elapsedText}：${result.message}${replyText}`);
    } catch (error) {
      setStatus(`模型测试失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTestBusy(false);
    }
  };

  const queryOpenRouterKeyStatus = async () => {
    setKeyStatusBusy(true);
    setStatus('正在查询 OpenRouter Key 限制和剩余额度...');
    try {
      const result = await callBackend<RetestAiKeyStatusResponse>('doc.retest.ai_config.key_status', buildRetestAgentPayload());
      const text = formatOpenRouterKeyStatus(result);
      setKeyStatusText(text);
      setStatus(result.success ? 'OpenRouter Key 状态已读取' : result.message || 'OpenRouter Key 状态查询失败');
    } catch (error) {
      const message = `OpenRouter Key 状态查询失败: ${error instanceof Error ? error.message : String(error)}`;
      setKeyStatusText(message);
      setStatus(message);
    } finally {
      setKeyStatusBusy(false);
    }
  };

  const switchRetestProfile = async (profileId: string) => {
    if (!profileId || profileId === activeProfileId) return;
    setIsBusy(true);
    try {
      const result = await callBackend<RetestAiConfigResponse>('doc.retest.ai_config.set', {
        action: 'switch_profile',
        enabled: agentEnabled,
        profile_id: profileId,
      });
      applyAiConfig(result.config);
      setStatus(result.message || '已切换 AI 配置档');
    } catch (error) {
      setStatus(`AI 配置切换失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const updateAgentEnabled = async (enabled: boolean) => {
    const previous = agentEnabled;
    setAgentEnabled(enabled);
    setIsBusy(true);
    try {
      const result = await callBackend<RetestAiConfigResponse>('doc.retest.ai_config.set', {
        action: 'set_enabled',
        enabled,
        profile_id: activeProfileId,
      });
      applyAiConfig(result.config);
      setStatus(result.message || (enabled ? 'AI 规划已启用' : 'AI 规划已关闭'));
    } catch (error) {
      setAgentEnabled(previous);
      setStatus(`AI 开关保存失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const createRetestProfile = async () => {
    setIsBusy(true);
    try {
      const result = await callBackend<RetestAiConfigResponse>('doc.retest.ai_config.set', {
        action: 'create_profile',
        enabled: agentEnabled,
        name: newProfileName.trim() || defaultProfileName(newProfileProvider),
        provider: newProfileProvider,
      });
      applyAiConfig(result.config);
      setNewProfileName('');
      setStatus(result.message || 'AI 配置档已创建');
    } catch (error) {
      setStatus(`AI 配置档创建失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const deleteRetestProfile = async () => {
    if (profiles.length <= 1) {
      setStatus('至少需要保留一个 AI 配置档');
      return;
    }
    const displayName = profileName.trim() || activeProfileId;
    if (!window.confirm(`删除 AI 配置档「${displayName}」？`)) return;
    setIsBusy(true);
    try {
      const result = await callBackend<RetestAiConfigResponse>('doc.retest.ai_config.set', {
        action: 'delete_profile',
        enabled: agentEnabled,
        profile_id: activeProfileId,
      });
      applyAiConfig(result.config);
      setStatus(result.message || 'AI 配置档已删除');
    } catch (error) {
      setStatus(`AI 配置档删除失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const refreshExternalTools = async () => {
    setIsBusy(true);
    try {
      const result = await callBackend<RetestToolsStatusResponse>('doc.retest.tools.status', {});
      setExternalToolStatus(result);
      setStatus(result.message || '外部工具状态已刷新');
    } catch (error) {
      setStatus(`外部工具状态读取失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const installExternalTools = async (tools?: string[]) => {
    setInstallBusy(true);
    const selected = tools?.length ? tools : ['nmap', 'sqlmap', 'ffuf'];
    setStatus(`正在一键下载外部工具: ${selected.join(', ')}`);
    setToolInstallLog('');
    try {
      const result = await callBackend<RetestToolsInstallResponse>('doc.retest.tools.install', { tools: selected });
      if (result.status) {
        setExternalToolStatus(result.status);
      } else {
        const statusResult = await callBackend<RetestToolsStatusResponse>('doc.retest.tools.status', {});
        setExternalToolStatus(statusResult);
      }
      const failureText = result.failures?.length
        ? `\n失败:\n${result.failures.map((item) => `- ${item.tool}: ${item.reason}`).join('\n')}`
        : '';
      setToolInstallLog([...(result.logs ?? []), failureText].filter(Boolean).join('\n'));
      setStatus(result.message || (result.success ? '外部工具下载完成' : '外部工具下载失败'));
    } catch (error) {
      setStatus(`一键下载外部工具失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setInstallBusy(false);
    }
  };

  const sortedTools = useMemo(
    () => [...toolCatalog].sort((left, right) => `${left.category}:${left.tool_id}`.localeCompare(`${right.category}:${right.tool_id}`)),
    [toolCatalog],
  );
  const toolCategoryText = useMemo(
    () => Object.entries(toolCategories).sort(([left], [right]) => left.localeCompare(right)).map(([category, count]) => `${category}:${count}`).join(' / '),
    [toolCategories],
  );
  const externalTools = externalToolStatus?.tools ?? [];
  const missingExternalTools = externalTools.filter((tool) => !tool.installed);
  const externalToolSummary = externalTools.length
    ? `已配置 ${externalTools.length - missingExternalTools.length}/${externalTools.length}`
    : '未读取';

  return (
    <div className="vertical-detail scroll-page-layout retest-agent-config-page">
      <fieldset className="koi-group retest-agent-config-card"><legend>配置档切换</legend>
        <div className="retest-profile-switcher">
          {profiles.map((profile) => (
            <button key={profile.id} type="button" className={`retest-profile-button${profile.id === activeProfileId ? ' active' : ''}`} onClick={() => void switchRetestProfile(profile.id)} disabled={isBusy} title={profile.id}>
              <strong>{profile.name || profile.id}</strong>
              <span>{providerLabel(profile.provider)}{profile.model ? ` / ${profile.model}` : ''}</span>
            </button>
          ))}
        </div>
        <div className="retest-agent-actions">
          <label className="checkbox-row retest-agent-toggle"><input type="checkbox" checked={agentEnabled} onChange={(event) => void updateAgentEnabled(event.target.checked)} disabled={isBusy} /> 启用 AI 规划</label>
          <input className="koi-input retest-new-profile-input" placeholder="新配置名称" value={newProfileName} onChange={(event) => setNewProfileName(event.target.value)} />
          <ConfigSelectInput options={RETEST_AI_PROVIDER_OPTIONS} value={newProfileProvider} onChange={setNewProfileProvider} />
          <button type="button" className="koi-button secondary compact-button" onClick={createRetestProfile} disabled={isBusy}>新建配置</button>
          <button type="button" className="koi-button secondary compact-button" onClick={loadRetestAgentConfig} disabled={isBusy}>刷新</button>
        </div>
      </fieldset>

      <fieldset className="koi-group retest-agent-config-card"><legend>当前配置</legend>
        <div className="retest-agent-grid">
          <label>配置名称:<input className="koi-input" value={profileName} onChange={(event) => setProfileName(event.target.value)} /></label>
          <label>Provider:<ConfigSelectInput options={RETEST_AI_PROVIDER_OPTIONS} value={aiProvider} onChange={changeAiProvider} /></label>
          <label>Base URL:<input className="koi-input" placeholder={providerBaseUrlPlaceholder(aiProvider)} value={aiBaseUrl} onChange={(event) => setAiBaseUrl(event.target.value)} /></label>
          <label>Model:<input className="koi-input" placeholder={providerModelPlaceholder(aiProvider)} value={aiModel} onChange={(event) => setAiModel(event.target.value)} /></label>
          <label>API Key:<input className="koi-input" type="password" placeholder={aiKeyConfigured ? '已配置，留空不覆盖' : '未配置'} value={aiApiKey} onChange={(event) => setAiApiKey(event.target.value)} /></label>
          <label>Temperature:<input className="koi-input compact-number" value={aiTemperature} onChange={(event) => setAiTemperature(event.target.value)} /></label>
          <label>上下文窗口 Tokens:<input className="koi-input compact-number" value={aiContextWindow} onChange={(event) => setAiContextWindow(event.target.value)} /></label>
          <label>最大输出 Tokens:<input className="koi-input compact-number" value={aiMaxTokens} onChange={(event) => setAiMaxTokens(event.target.value)} /></label>
          <label className="checkbox-row retest-clear-key"><input type="checkbox" checked={clearAiKey} onChange={(event) => setClearAiKey(event.target.checked)} /> 清除已保存 Key</label>
        </div>
        <div className="retest-agent-config-note">上下文窗口用于 Agent 估算可放入多少通报/日志上下文；最大输出 Tokens 才会作为模型 API 的 max_tokens 发送。</div>
        <div className="retest-agent-actions">
          <span className={`cookie-status-detail ${aiKeyConfigured ? 'ok' : 'warn'}`}>Key {aiKeyConfigured ? '已配置' : '未配置'}</span>
          <span className="retest-tool-summary">当前: {activeProfileId}</span>
          <button type="button" className="koi-button secondary compact-button" onClick={testRetestAgentConfig} disabled={isBusy || testBusy}>{testBusy ? '测试中...' : '测试模型'}</button>
          {aiProvider === 'openrouter' ? (
            <button type="button" className="koi-button secondary compact-button" onClick={queryOpenRouterKeyStatus} disabled={isBusy || keyStatusBusy}>
              {keyStatusBusy ? '查询中...' : '查询 Key 限制/余额'}
            </button>
          ) : null}
          <button type="button" className="koi-button primary compact-button" onClick={saveRetestAgentConfig} disabled={isBusy}>保存当前配置</button>
          <button type="button" className="koi-button danger compact-button" onClick={deleteRetestProfile} disabled={isBusy || profiles.length <= 1}>删除当前配置</button>
        </div>
        {keyStatusText ? <pre className="retest-key-status">{keyStatusText}</pre> : null}
        {status ? <div className="classification-status retest-agent-status">{status}</div> : null}
      </fieldset>

      <fieldset className="koi-group retest-external-tools-panel"><legend>外部工具自动检测</legend>
        <div className="retest-tool-summary-row">
          <span>{externalToolSummary}{externalToolStatus?.tool_root ? ` / 下载目录: ${externalToolStatus.tool_root}` : ''}</span>
          <div className="retest-agent-actions">
            <button type="button" className="koi-button secondary compact-button" onClick={refreshExternalTools} disabled={isBusy || installBusy}>重新检测</button>
            <button type="button" className="koi-button primary compact-button" onClick={() => void installExternalTools(missingExternalTools.map((tool) => tool.id))} disabled={installBusy || !missingExternalTools.length}>{installBusy ? '下载中...' : '一键下载缺失工具'}</button>
            <button type="button" className="koi-button secondary compact-button" onClick={() => void installExternalTools()} disabled={installBusy}>下载全部</button>
          </div>
        </div>
        <div className="retest-agent-config-note">检测顺序为项目工具目录、本机用户工具目录、系统 PATH。下载完成后执行器会自动使用检测到的 nmap/sqlmap/ffuf，不需要手动配置 PATH；在测试工作台也可以直接对 Agent 说“下载工具”。</div>
        <div className="retest-tool-list retest-external-tool-list">
          {externalTools.map((tool) => (
            <div key={tool.id} className={`retest-tool-row retest-external-tool-row${tool.installed ? ' installed' : ' missing'}`}>
              <div className="retest-tool-main">
                <strong>{tool.name || tool.id}</strong>
                <span>{tool.installed ? (tool.command?.join(' ') || '已配置') : '未检测到，可一键下载'}</span>
                {tool.root ? <code>{tool.root}</code> : null}
              </div>
              <div className="retest-tool-meta">
                <span>{tool.installed ? '已配置' : '缺失'}</span>
                {tool.source ? <span>{tool.source}</span> : null}
                {tool.installable ? <span>可下载</span> : null}
              </div>
            </div>
          ))}
          {!externalTools.length ? <div className="modal-message">暂无外部工具状态。点击“重新检测”读取。</div> : null}
        </div>
        {toolInstallLog ? <pre className="retest-tool-install-log">{toolInstallLog}</pre> : null}
      </fieldset>

      <fieldset className="koi-group retest-tool-catalog-panel"><legend>复测工具目录</legend>
        <div className="retest-tool-summary-row">
          <span>工具 {toolCatalog.length}{toolCategoryText ? ` (${toolCategoryText})` : ''}</span>
        </div>
        <div className="retest-tool-list">
          {sortedTools.map((tool) => (
            <div key={tool.tool_id} className="retest-tool-row">
              <div className="retest-tool-main">
                <strong>{tool.label}</strong>
                <span>{tool.description || tool.tool_id}</span>
              </div>
              <div className="retest-tool-meta">
                <span>{tool.category}</span>
                <span>{tool.risk}</span>
              </div>
            </div>
          ))}
          {!sortedTools.length ? <div className="modal-message">暂无工具目录</div> : null}
        </div>
      </fieldset>
    </div>
  );
}
