import type { AppView } from '../types'

type Props = {
  activeView: AppView
  onViewChange: (view: AppView) => void
}

export function Header({ activeView, onViewChange }: Props) {
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
        </nav>
      </div>
    </header>
  )
}
