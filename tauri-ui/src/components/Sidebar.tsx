import type { KoiModule } from '../lib/types';

type SidebarProps = {
  activeIndex: number;
  darkMode: boolean;
  modules: KoiModule[];
  onSelect: (index: number) => void;
  onCollapse: () => void;
};

export function Sidebar({ activeIndex, modules, onSelect, onCollapse }: SidebarProps) {
  return (
    <nav className="sidebar-scroll" id="module-navigation" aria-label="功能导航">
      <div className="sidebar-heading"><span>功能导航</span><button type="button" className="sidebar-collapse-toggle" onClick={onCollapse} aria-label="收起导航" aria-expanded="true" aria-controls="module-navigation" title="收起导航">‹</button></div>
      <div className="sidebar-list">
        {modules.map((module, index) => (
          <button
            key={module.id}
            className={`sidebar-button ${activeIndex === index ? 'checked' : ''}`}
            onClick={() => onSelect(index)}
          >
            {module.title}
          </button>
        ))}
      </div>
    </nav>
  );
}
