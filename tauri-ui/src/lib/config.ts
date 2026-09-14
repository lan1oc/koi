import { callBackend } from './backend';

type AppConfig = {
  app?: { first_run?: boolean };
  ui?: { dark_mode?: boolean };
  ui_settings?: { dark_mode?: boolean };
};

export async function loadAppConfig(): Promise<AppConfig> {
  return callBackend<AppConfig>('config.load');
}

export async function saveDarkMode(darkMode: boolean): Promise<void> {
  try {
    await callBackend('config.set_dark_mode', { dark_mode: darkMode });
  } catch {
    // Keep the static shell usable if the native backend is unavailable.
  }
}
