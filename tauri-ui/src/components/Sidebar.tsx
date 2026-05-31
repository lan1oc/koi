import type { KoiModule } from '../lib/types';

type SidebarProps = {
  activeIndex: number;
  darkMode: boolean;
  modules: KoiModule[];
  onSelect: (index: number) => void;
};

export function Sidebar({ activeIndex, modules, onSelect }: SidebarProps) {
  return (
    <nav className="sidebar-scroll">
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
