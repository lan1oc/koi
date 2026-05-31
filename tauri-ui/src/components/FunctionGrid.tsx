import type { KoiModule } from '../lib/types';

type FunctionGridProps = {
  module: KoiModule;
  onOpen: (index: number) => void;
};

export function FunctionGrid({ module, onOpen }: FunctionGridProps) {
  return (
    <section className="function-list-page">
      <h1>{module.title}</h1>
      <div className="function-grid">
        {module.functions.map((page, index) => (
          <button key={page.id} className="rainbow-button" onClick={() => onOpen(index)}>
            {page.title}
          </button>
        ))}
      </div>
    </section>
  );
}
