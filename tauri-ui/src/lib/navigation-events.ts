export type KoiNavigationDetail = {
  moduleId: string;
  functionId?: string;
};

export const KOI_NAVIGATE_EVENT = 'koi:navigate-function';

export function navigateToFunction(moduleId: string, functionId?: string) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<KoiNavigationDetail>(KOI_NAVIGATE_EVENT, {
    detail: { moduleId, functionId },
  }));
}
