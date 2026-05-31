import { useState } from 'react';
import type { KoiModule } from '../lib/types';
import { FunctionGrid } from './FunctionGrid';

type ModuleContainerProps = {
  darkMode: boolean;
  module: KoiModule;
};

export function ModuleContainer({ module }: ModuleContainerProps) {
  const [activeFunction, setActiveFunction] = useState<number | null>(null);
  const currentFunction = activeFunction === null ? null : module.functions[activeFunction];

  if (currentFunction) {
    const Detail = currentFunction.component;
    return (
      <div className="module-container detail-mode">
        <header className="detail-header">
          <button className="back-button" onClick={() => setActiveFunction(null)}>
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
      <FunctionGrid module={module} onOpen={setActiveFunction} />
    </div>
  );
}
