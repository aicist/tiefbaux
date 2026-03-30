import type { AppView, User } from '../types'

type Props = {
  activeView: AppView
  onViewChange: (view: AppView) => void
  user?: User | null
  onLogout?: () => void
}

export function Header({ activeView, onViewChange, user, onLogout }: Props) {
  return (
    <header className="app-header">
      <div className="header-content">
        <div className="logo-group">
          <div className="logo-icon">
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="8" fill="#146c60" />
              <path d="M8 12h16M8 16h12M8 20h14M16 8v4" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <h1>TiefbauX</h1>
            <p className="subtitle">Leistungsverzeichnis-Analyse & Angebotsassistent</p>
          </div>
        </div>
        <nav className="view-tabs">
          <button
            className={`view-tab ${activeView === 'analysis' ? 'view-tab--active' : ''}`}
            onClick={() => onViewChange('analysis')}
          >
            Neue Analyse
          </button>
          <button
            className={`view-tab ${activeView === 'archive' ? 'view-tab--active' : ''}`}
            onClick={() => onViewChange('archive')}
          >
            Projektarchiv
          </button>
          <button
            className={`view-tab ${activeView === 'radar' ? 'view-tab--active' : ''}`}
            onClick={() => onViewChange('radar')}
          >
            Objektradar
          </button>
          {user?.role === 'admin' && (
            <button
              className={`view-tab ${activeView === 'admin' ? 'view-tab--active' : ''}`}
              onClick={() => onViewChange('admin')}
            >
              Verwaltung
            </button>
          )}
        </nav>
        {user && (
          <div className="header-user">
            <span className="header-user-name">{user.name}</span>
            <span className={`header-user-role header-user-role--${user.role}`}>
              {user.role === 'admin' ? 'Admin' : 'Mitarbeiter'}
            </span>
            <button className="header-logout" onClick={onLogout} title="Abmelden">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
