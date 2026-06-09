import { useState } from 'react';
import type { KoiModule } from '../lib/types';
import { FunctionGrid } from './FunctionGrid';

type ModuleContainerProps = {
  activeFunctionId?: string | null;
  darkMode: boolean;
  module: KoiModule;
  onActiveFunctionIdChange?: (functionId: string | null) => void;
};

export function ModuleContainer({ activeFunctionId = null, module, onActiveFunctionIdChange }: ModuleContainerProps) {
  const [mountedFunctionIds, setMountedFunctionIds] = useState<string[]>([]);
  const currentFunction = activeFunctionId === null ? null : module.functions.find((page) => page.id === activeFunctionId) ?? null;

  if (currentFunction && !mountedFunctionIds.includes(currentFunction.id)) {
    setMountedFunctionIds((current) => [...current, currentFunction.id]);
  }

  return (
    <div className="module-container">
      <section className={`function-list-panel${currentFunction ? ' hidden-panel' : ' active-panel'}`} aria-hidden={Boolean(currentFunction)}>
        <FunctionGrid module={module} onOpen={(index) => onActiveFunctionIdChange?.(module.functions[index]?.id ?? null)} />
      </section>
      {module.functions
        .filter((page) => mountedFunctionIds.includes(page.id) || page.id === currentFunction?.id)
        .map((page) => {
          const Detail = page.component;
          const isActive = page.id === currentFunction?.id;
          return (
            <section key={page.id} className={`detail-mode detail-panel${isActive ? ' active-panel' : ' hidden-panel'}`} aria-hidden={!isActive}>
              <header className="detail-header">
                <button className="back-button" onClick={() => onActiveFunctionIdChange?.(null)}>
                  ← 返回
                </button>
                <span className="current-function-title">{page.title}</span>
              </header>
              <section className="detail-content fade-in">
                <Detail />
              </section>
            </section>
          );
        })}
    </div>
  );
}
