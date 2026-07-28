export type KoiNavigationDetail = {
  moduleId: string;
  functionId?: string;
};

export const KOI_NAVIGATE_EVENT = 'koi:navigate-function';
const KOI_PENDING_NAVIGATION_KEY = 'koi.navigation.pending';
const KOI_PENDING_NAVIGATION_TTL_MS = 60 * 1000;

function sameNavigation(left: KoiNavigationDetail, right: KoiNavigationDetail) {
  return left.moduleId === right.moduleId && (left.functionId || '') === (right.functionId || '');
}

function parsePendingNavigation(raw: string | null) {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as KoiNavigationDetail & { createdAt?: number };
    if (!value || typeof value.moduleId !== 'string' || !value.moduleId.trim()) return null;
    const createdAt = Number(value.createdAt || 0);
    if (!createdAt || Date.now() - createdAt > KOI_PENDING_NAVIGATION_TTL_MS) return null;
    return {
      moduleId: value.moduleId,
      functionId: typeof value.functionId === 'string' && value.functionId.trim() ? value.functionId : undefined,
    };
  } catch {
    return null;
  }
}

function writePendingNavigation(detail: KoiNavigationDetail) {
  try {
    window.sessionStorage.setItem(KOI_PENDING_NAVIGATION_KEY, JSON.stringify({ ...detail, createdAt: Date.now() }));
  } catch {
    // Navigation events still work when sessionStorage is unavailable.
  }
}

export function clearPendingNavigation(detail?: KoiNavigationDetail) {
  if (typeof window === 'undefined') return;
  try {
    if (detail) {
      const pending = parsePendingNavigation(window.sessionStorage.getItem(KOI_PENDING_NAVIGATION_KEY));
      if (pending && !sameNavigation(pending, detail)) return;
    }
    window.sessionStorage.removeItem(KOI_PENDING_NAVIGATION_KEY);
  } catch {
    // Ignore storage failures in restricted WebViews.
  }
}

export function consumePendingNavigation() {
  if (typeof window === 'undefined') return null;
  try {
    const pending = parsePendingNavigation(window.sessionStorage.getItem(KOI_PENDING_NAVIGATION_KEY));
    window.sessionStorage.removeItem(KOI_PENDING_NAVIGATION_KEY);
    return pending;
  } catch {
    return null;
  }
}

export function navigateToFunction(moduleId: string, functionId?: string) {
  if (typeof window === 'undefined') return;
  const detail = { moduleId, functionId };
  writePendingNavigation(detail);
  window.dispatchEvent(new CustomEvent<KoiNavigationDetail>(KOI_NAVIGATE_EVENT, {
    detail,
  }));
}
