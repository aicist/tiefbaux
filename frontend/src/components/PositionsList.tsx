import { useMemo, useState } from 'react'
import type { LVPosition, ProductSuggestion } from '../types'
import { DinBadge } from './DinBadge'

type FilterMode = 'alle' | 'zugeordnet' | 'offen' | 'dienstleistung'

const LOAD_CLASS_CATEGORIES = new Set(['Schachtabdeckungen', 'Straßenentwässerung'])

type Props = {
  positions: LVPosition[]
  activePositionId: string | null
  onSelectPosition: (id: string) => void
  selectedArticleIds: Record<string, string>
  suggestionMap: Record<string, ProductSuggestion[]>
  skippedPositionIds: Set<string>
  onToggleSkip: (positionId: string) => void
  compatibilityIssuePositionIds: Set<string>
  onEnterAssignment?: () => void
}

function formatQty(value?: number | null): string {
  if (value == null) return '-'
  if (Number.isInteger(value)) return String(value)
  return value.toLocaleString('de-DE', { maximumFractionDigits: 3 })
}

export function PositionsList({
  positions,
  activePositionId,
  onSelectPosition,
  selectedArticleIds,
  suggestionMap,
  skippedPositionIds,
  onToggleSkip,
  compatibilityIssuePositionIds,
  onEnterAssignment,
}: Props) {
  const pageSize = 10
  const [searchTerm, setSearchTerm] = useState('')
  const [filterMode, setFilterMode] = useState<FilterMode>('alle')
  const [currentPage, setCurrentPage] = useState(0)

  const filteredPositions = useMemo(() => {
    let filtered = positions

    if (filterMode !== 'alle') {
      filtered = filtered.filter((p) => {
        const isSkipped = skippedPositionIds.has(p.id)
        const hasSelection = Boolean(selectedArticleIds[p.id])
        if (filterMode === 'dienstleistung') return isSkipped
        if (isSkipped) return false
        if (filterMode === 'zugeordnet') return hasSelection
        if (filterMode === 'offen') return !hasSelection
        return true
      })
    }

    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase()
      filtered = filtered.filter(
        (p) =>
          p.description.toLowerCase().includes(term) ||
          p.ordnungszahl.includes(term) ||
          (p.parameters.product_category ?? '').toLowerCase().includes(term),
      )
    }

    return filtered
  }, [positions, searchTerm, filterMode, selectedArticleIds, skippedPositionIds])

  const totalPages = Math.ceil(filteredPositions.length / pageSize)
  const safePage = Math.min(currentPage, Math.max(0, totalPages - 1))
  const pagedPositions = filteredPositions.slice(safePage * pageSize, (safePage + 1) * pageSize)

  const assignedCount = useMemo(
    () => positions.filter((p) => selectedArticleIds[p.id] && !skippedPositionIds.has(p.id)).length,
    [positions, selectedArticleIds, skippedPositionIds],
  )
  const serviceCount = skippedPositionIds.size
  const openCount = positions.length - assignedCount - serviceCount

  return (
    <section className="panel positions-panel">
      <div className="panel-header">
        <div className="panel-number">2</div>
        <div>
          <h2>Erkannte Positionen</h2>
          <p className="panel-copy">Aus dem LV extrahierte bepreisbare Positionen.</p>
        </div>
        {onEnterAssignment && positions.length > 0 && (
          <button className="btn-toolbar btn-enter-assignment" onClick={onEnterAssignment} title="Zur fokussierten Zuordnungsansicht">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Zuordnung
          </button>
        )}
      </div>

      {positions.length > 0 && (
        <>
          <div className="positions-summary">
            <span className="summary-total">{positions.length} Positionen</span>
            <span className="summary-dot" />
            <span className="summary-matched">{assignedCount} zugeordnet</span>
            <span className="summary-dot" />
            <span className="summary-open">{openCount} offen</span>
            {serviceCount > 0 && (
              <>
                <span className="summary-dot" />
                <span className="summary-service">{serviceCount} Dienstleistung</span>
              </>
            )}
          </div>

          <div className="filter-chips">
            {(['alle', 'zugeordnet', 'offen', 'dienstleistung'] as const).map((mode) => (
              <button
                key={mode}
                className={`filter-chip ${filterMode === mode ? 'active' : ''}`}
                onClick={() => { setFilterMode(mode); setCurrentPage(0) }}
              >
                {mode === 'alle'
                  ? `Alle (${positions.length})`
                  : mode === 'zugeordnet'
                    ? `Zugeordnet (${assignedCount})`
                    : mode === 'offen'
                      ? `Offen (${openCount})`
                      : `Dienstleistung (${serviceCount})`}
              </button>
            ))}
          </div>

          <div className="search-box">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="search-icon">
              <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              placeholder="Positionen filtern..."
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setCurrentPage(0) }}
            />
          </div>
        </>
      )}

      <div className="position-list">
        {positions.length === 0 && (
          <div className="empty-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" className="empty-icon">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="1.5" />
              <polyline points="14,2 14,8 20,8" stroke="currentColor" strokeWidth="1.5" />
              <line x1="16" y1="13" x2="8" y2="13" stroke="currentColor" strokeWidth="1.5" />
              <line x1="16" y1="17" x2="8" y2="17" stroke="currentColor" strokeWidth="1.5" />
            </svg>
            <p>Laden Sie ein LV-PDF hoch, um Positionen zu extrahieren.</p>
          </div>
        )}
        {pagedPositions.map((position, index) => {
          const isActive = position.id === activePositionId
          const isSkipped = skippedPositionIds.has(position.id)
          const hasSelection = Boolean(selectedArticleIds[position.id])
          const hasSuggestions = (suggestionMap[position.id] ?? []).length > 0
          const category = position.parameters.product_category
          const hasCompatIssue = compatibilityIssuePositionIds.has(position.id)
          const showLoadClass = category ? LOAD_CLASS_CATEGORIES.has(category) : false

          let statusClass = 'status-open'
          if (isSkipped) statusClass = 'status-service'
          else if (hasSelection) statusClass = 'status-matched'
          else if (!hasSuggestions && positions.length > 0) statusClass = 'status-none'

          return (
            <div
              key={position.id}
              className={`position-row ${isActive ? 'active' : ''} ${statusClass} ${hasCompatIssue ? 'has-compat-issue' : ''}`}
              style={{ animationDelay: `${index * 30}ms` }}
            >
              <button
                type="button"
                className="position-row-content"
                onClick={() => onSelectPosition(position.id)}
              >
                <div className="position-head">
                  <span className="position-no">{position.ordnungszahl}</span>
                  <div className="position-badges">
                    {hasCompatIssue && (
                      <span className="badge badge-compat" title="Kompatibilitätsproblem">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                    )}
                    {category && <span className="badge badge-category">{category}</span>}
                    {isSkipped ? (
                      <span className="badge badge-service">
                        {position.position_type === 'dienstleistung' ? 'Dienstleistung' : 'Ausgeschlossen'}
                      </span>
                    ) : (
                      <span className={`badge ${hasSelection ? 'badge-ok' : hasSuggestions ? 'badge-warn' : 'badge-none'}`}>
                        {hasSelection ? 'zugeordnet' : hasSuggestions ? 'offen' : 'kein Treffer'}
                      </span>
                    )}
                  </div>
                </div>
                <p className="position-desc">{position.description}</p>
                {hasSelection && (() => {
                  const selectedArt = (suggestionMap[position.id] ?? []).find(
                    s => s.artikel_id === selectedArticleIds[position.id]
                  )
                  return selectedArt ? (
                    <div className="position-selected-article">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                        <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <span>{selectedArt.artikelname}</span>
                    </div>
                  ) : null
                })()}
                <div className="position-meta">
                  <span>Menge: {formatQty(position.quantity)} {position.unit ?? ''}</span>
                  {position.parameters.nominal_diameter_dn != null && (
                    <span className="meta-tag">DN {position.parameters.nominal_diameter_dn}</span>
                  )}
                  {showLoadClass && position.parameters.load_class && (
                    <span className="meta-tag">{position.parameters.load_class}</span>
                  )}
                  {position.parameters.material && (
                    <span className="meta-tag">{position.parameters.material}</span>
                  )}
                  {position.parameters.norm && (
                    <DinBadge norm={position.parameters.norm} className="meta-tag" />
                  )}
                  {position.parameters.stiffness_class_sn != null && (
                    <span className="meta-tag">SN{position.parameters.stiffness_class_sn}</span>
                  )}
                  {position.parameters.installation_area && (
                    <span className="meta-tag">{position.parameters.installation_area}</span>
                  )}
                </div>
              </button>
              <button
                className="skip-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleSkip(position.id)
                }}
                title={isSkipped ? 'Wieder einbeziehen' : 'Als Dienstleistung markieren'}
              >
                {isSkipped ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M9 14l-4-4m0 0l4-4m-4 4h11a4 4 0 010 8h-1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                )}
              </button>
            </div>
          )
        })}
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button
            className="pagination-btn"
            disabled={safePage === 0}
            onClick={() => setCurrentPage(safePage - 1)}
          >
            Zurück
          </button>
          <span className="pagination-info">
            Seite {safePage + 1} von {totalPages}
          </span>
          <button
            className="pagination-btn"
            disabled={safePage >= totalPages - 1}
            onClick={() => setCurrentPage(safePage + 1)}
          >
            Weiter
          </button>
        </div>
      )}
    </section>
  )
}
