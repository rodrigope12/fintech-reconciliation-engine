import { FC } from 'react';

type AppView = 'validation' | 'selector' | 'processing' | 'results' | 'settings';

interface SidebarProps {
  currentView: AppView;
  onNavigate: (view: AppView) => void;
  isValidated: boolean;
  hasResults: boolean;
}

interface NavItem {
  id: AppView;
  label: string;
  icon: JSX.Element;
  disabled?: boolean;
}

export const Sidebar: FC<SidebarProps> = ({
  currentView,
  onNavigate,
  isValidated,
  hasResults,
}) => {
  const navItems: NavItem[] = [
    {
      id: 'selector',
      label: 'Clientes',
      icon: (
        <svg className="nav-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      ),
      disabled: !isValidated,
    },
    {
      id: 'results',
      label: 'Resultados',
      icon: (
        <svg className="nav-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
      disabled: !hasResults,
    },
    {
      id: 'settings',
      label: 'Ajustes',
      icon: (
        <svg className="nav-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
    },
  ];

  return (
    <aside className="sidebar">
      {/* App Icon */}
      <div className="sidebar-header">
        <div className="app-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className="app-icon-svg">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
          </svg>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${currentView === item.id ? 'nav-item-active' : ''} ${item.disabled ? 'nav-item-disabled' : ''}`}
            onClick={() => !item.disabled && onNavigate(item.id)}
            disabled={item.disabled}
            title={item.label}
          >
            {item.icon}
            <span className="nav-label">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Status Indicator */}
      <div className="sidebar-footer">
        <div className={`status-indicator ${isValidated ? 'status-valid' : 'status-invalid'}`}>
          <div className="status-dot" />
          <span className="status-text">
            {isValidated ? 'Listo' : 'Sin configurar'}
          </span>
        </div>
      </div>
    </aside>
  );
};
