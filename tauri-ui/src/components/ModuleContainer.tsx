import type { KoiModule } from '../lib/types';
import { FunctionGrid } from './FunctionGrid';

type ModuleContainerProps = {
  activeFunctionId?: string | null;
  darkMode: boolean;
  module: KoiModule;
  onActiveFunctionIdChange?: (functionId: string | null) => void;
};

export function ModuleContainer({ activeFunctionId = null, module, onActiveFunctionIdChange }: ModuleContainerProps) {
  const currentFunction = activeFunctionId === null ? null : module.functions.find((page) => page.id === activeFunctionId) ?? null;

  if (currentFunction) {
    const Detail = currentFunction.component;
    return (
      <div className="module-container detail-mode">
        <header className="detail-header">
          <button className="back-button" onClick={() => onActiveFunctionIdChange?.(null)}>
            ← 返回
          </button>
          <span className="current-function-title">{currentFunction.title}</span>
        </header>
        <section className="detail-content fade-in">
          <Detail />
        </section>
      </div>
    );
  }

  return (
    <div className="module-container fade-in">
      <FunctionGrid module={module} onOpen={(index) => onActiveFunctionIdChange?.(module.functions[index]?.id ?? null)} />
    </div>
  );
}
