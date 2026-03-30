import { useMemo, useState } from 'react'
import type { LVPosition, PositionSuggestions, ProductSuggestion, SupplierInquiry } from '../types'
import { DinBadge } from './DinBadge'

type FilterMode = 'alle' | 'zugeordnet' | 'offen' | 'angefragt' | 'bestaetigt' | 'abgelehnt' | 'dienstleistung'

const LOAD_CLASS_CATEGORIES = new Set(['Schachtabdeckungen', 'Straßenentwässerung'])

type Props = {
  positions: LVPosition[]
  activePositionId: string | null
  onSelectPosition: (id: string) => void
  selectedArticleIds: Record<string, string[]>
  positionDecisions?: Record<string, 'accepted' | 'rejected' | 'inquiry_pending'>
  pendingInquiryPositionIds?: string[]
  componentSelections?: Record<string, string>
  suggestionMap: Record<string, ProductSuggestion[]>
  positionSuggestions?: PositionSuggestions[]
  onEnterAssignment?: () => void
  showAssignmentDetails?: boolean
  inquiries?: SupplierInquiry[]
  onEditPosition?: (positionId: string) => void
}

function formatQty(value?: number | null): string {
  if (value == null) return '-'
  if (Number.isInteger(value)) return String(value)
  return value.toLocaleString('de-DE', { maximumFractionDigits: 3 })
}

function formatPrice(value?: number | null): string {
  if (value == null) return '—'
  return value.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'
}

export function PositionsList({
  positions,
  activePositionId,
  onSelectPosition,
  selectedArticleIds,
  positionDecisions = {},
  pendingInquiryPositionIds = [],
  componentSelections = {},
  suggestionMap,
  positionSuggestions = [],
  onEnterAssignment,
  showAssignmentDetails = false,
  inquiries = [],
  onEditPosition,
}: Props) {
  const pageSize = 10
  const [searchTerm, setSearchTerm] = useState('')
  const [filterMode, setFilterMode] = useState<FilterMode>('alle')
  const [currentPage, setCurrentPage] = useState(0)

  const componentSelectionCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    Object.keys(componentSelections).forEach((key) => {
      const [positionId] = key.split('::')
      counts[positionId] = (counts[positionId] ?? 0) + 1
    })
    return counts
  }, [componentSelections])

  const componentSuggestionCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    positionSuggestions.forEach((entry) => {
      const count = entry.component_suggestions?.filter((cs) => cs.suggestions.length > 0).length ?? 0
      if (count > 0) counts[entry.position_id] = count
    })
    return counts
  }, [positionSuggestions])

  const pendingInquirySet = useMemo(
    () => new Set(pendingInquiryPositionIds),
    [pendingInquiryPositionIds],
  )

  const inquiriesByPosition = useMemo(() => {
    const map: Record<string, SupplierInquiry[]> = {}
    for (const inq of inquiries) {
      if (inq.position_id) {
        ;(map[inq.position_id] ??= []).push(inq)
      }
    }
    return map
  }, [inquiries])

  const inquiryPositionSet = useMemo(
    () => new Set(Object.keys(inquiriesByPosition)),
    [inquiriesByPosition],
  )

  // Counts for filters
  const serviceCount = useMemo(() => positions.filter(p => p.position_type === 'dienstleistung').length, [positions])
  const assignedCount = useMemo(
    () => positions.filter((p) => ((selectedArticleIds[p.id]?.length ?? 0) > 0 || (componentSelectionCounts[p.id] ?? 0) > 0) && p.position_type !== 'dienstleistung').length,
    [positions, selectedArticleIds, componentSelectionCounts],
  )
  const rejectedCount = useMemo(
    () => positions.filter((p) => p.position_type !== 'dienstleistung' && positionDecisions[p.id] === 'rejected').length,
    [positions, positionDecisions],
  )
  const acceptedCount = useMemo(
    () => positions.filter((p) => p.position_type !== 'dienstleistung' && positionDecisions[p.id] === 'accepted').length,
    [positions, positionDecisions],
  )
  const inquiryCount = useMemo(
    () => positions.filter((p) => {
      const decision = positionDecisions[p.id]
      return p.position_type !== 'dienstleistung' && (decision === 'inquiry_pending' || pendingInquirySet.has(p.id) || inquiryPositionSet.has(p.id))
    }).length,
    [positions, positionDecisions, pendingInquirySet, inquiryPositionSet],
  )
  const openCount = Math.max(0, positions.length - assignedCount - serviceCount - rejectedCount)

  const filteredPositions = useMemo(() => {
    let filtered = positions

    if (filterMode !== 'alle') {
      filtered = filtered.filter((p) => {
        const isDL = p.position_type === 'dienstleistung'
        const decision = positionDecisions[p.id]
        const isRejected = decision === 'rejected'
        const isAccepted = decision === 'accepted'
        const isInquiry = decision === 'inquiry_pending' || pendingInquirySet.has(p.id) || inquiryPositionSet.has(p.id)
        const hasSelection = (selectedArticleIds[p.id]?.length ?? 0) > 0 || (componentSelectionCounts[p.id] ?? 0) > 0
        if (filterMode === 'dienstleistung') return isDL
        if (isDL) return false
        if (filterMode === 'abgelehnt') return isRejected
        if (filterMode === 'bestaetigt') return isAccepted
        if (filterMode === 'angefragt') return isInquiry && !isRejected
        if (isRejected) return false
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
  }, [positions, searchTerm, filterMode, selectedArticleIds, componentSelectionCounts, positionDecisions, pendingInquirySet, inquiryPositionSet])

  const totalPages = Math.ceil(filteredPositions.length / pageSize)
  const safePage = Math.min(currentPage, Math.max(0, totalPages - 1))
  const pagedPositions = filteredPositions.slice(safePage * pageSize, (safePage + 1) * pageSize)

  // Use extended filter set when in assignment details mode
  const standardFilters: FilterMode[] = ['alle', 'offen', 'dienstleistung']
  const extendedFilters: FilterMode[] = ['alle', 'offen', 'angefragt', 'bestaetigt', 'abgelehnt', 'dienstleistung']
  const filterSet = showAssignmentDetails ? extendedFilters : standardFilters

  function filterLabel(mode: FilterMode): string {
    switch (mode) {
      case 'alle': return `Alle (${positions.length})`
      case 'zugeordnet': return `Zugeordnet (${assignedCount})`
      case 'offen': return `Offen (${openCount})`
      case 'angefragt': return `Angefragt (${inquiryCount})`
      case 'bestaetigt': return `Bestätigt (${acceptedCount})`
      case 'abgelehnt': return `Abgelehnt (${rejectedCount})`
      case 'dienstleistung': return `Dienstleistung (${serviceCount})`
    }
  }

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
            {rejectedCount > 0 && (
              <>
                <span className="summary-dot" />
                <span className="summary-rejected">{rejectedCount} abgelehnt</span>
              </>
            )}
            {serviceCount > 0 && (
              <>
                <span className="summary-dot" />
                <span className="summary-service">{serviceCount} Dienstleistung</span>
              </>
            )}
          </div>

          <div className="filter-chips">
            {filterSet.map((mode) => (
              <button
                key={mode}
                className={`filter-chip ${filterMode === mode ? 'active' : ''}`}
                onClick={() => { setFilterMode(mode); setCurrentPage(0) }}
              >
                {filterLabel(mode)}
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
          const posInquiries = inquiriesByPosition[position.id] ?? []
          const inquiryStatus = posInquiries.some((inq) => inq.status === 'offen')
            ? 'offen'
            : posInquiries.some((inq) => inq.status === 'angefragt')
              ? 'angefragt'
              : posInquiries.some((inq) => inq.status === 'angebot_erhalten')
                ? 'angebot_erhalten'
                : null
          const isActive = position.id === activePositionId
          const isDL = position.position_type === 'dienstleistung'
          const componentSelectionCount = componentSelectionCounts[position.id] ?? 0
          const componentSuggestionCount = componentSuggestionCounts[position.id] ?? 0
          const decision = positionDecisions[position.id]
          const isRejected = decision === 'rejected'
          const isInquiryPending = decision === 'inquiry_pending'
          const hasSelection = (selectedArticleIds[position.id]?.length ?? 0) > 0 || componentSelectionCount > 0
          const hasSuggestions = (suggestionMap[position.id] ?? []).length > 0 || componentSuggestionCount > 0
          const needsInquiryFollowUp = (pendingInquirySet.has(position.id) || isInquiryPending || inquiryStatus === 'offen' || inquiryStatus === 'angefragt') && !isRejected
          const category = position.parameters.product_category
          const showLoadClass = category ? LOAD_CLASS_CATEGORIES.has(category) : false

          let statusClass = 'status-open'
          if (isDL) statusClass = 'status-service'
          else if (isRejected) statusClass = 'status-rejected'
          else if (needsInquiryFollowUp) statusClass = 'status-inquiry-open'
          else if (hasSelection) statusClass = 'status-matched'
          else if (!hasSuggestions && positions.length > 0) statusClass = 'status-none'

          return (
            <div
              key={position.id}
              className={`position-row ${isActive ? 'active' : ''} ${statusClass}`}
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
                    {!showAssignmentDetails && category && <span className="badge badge-category">{category}</span>}
                    {isDL ? (
                      <span className="badge badge-service">Dienstleistung</span>
                    ) : isRejected ? (
                      <span className="badge badge-rejected">abgelehnt</span>
                    ) : inquiryStatus ? (
                      <span className={`badge ${inquiryStatus === 'angebot_erhalten' ? 'badge-ok' : 'badge-inquiry'}`}>
                        {inquiryStatus === 'offen'
                          ? 'Anfrage offen'
                          : inquiryStatus === 'angefragt'
                            ? 'Angefragt'
                            : 'Angebot erhalten'}
                      </span>
                    ) : (
                      <span className={`badge ${hasSelection ? 'badge-ok' : hasSuggestions ? 'badge-warn' : 'badge-none'}`}>
                        {hasSelection ? 'zugeordnet' : hasSuggestions ? 'offen' : 'kein Treffer'}
                      </span>
                    )}
                  </div>
                </div>
                <p className="position-desc">{position.description}</p>
                {showAssignmentDetails && hasSelection && (() => {
                  const primaryId = selectedArticleIds[position.id]?.[0]
                  const selectedArt = primaryId ? (suggestionMap[position.id] ?? []).find(
                    s => s.artikel_id === primaryId
                  ) : undefined
                  if (!selectedArt && componentSelectionCount > 0) {
                    return (
                      <div className="position-assignment-detail">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <span className="pad-article-name">{componentSelectionCount} Artikel zugeordnet</span>
                      </div>
                    )
                  }
                  return selectedArt ? (
                    <div className="position-assignment-detail">
                      <div className="pad-main">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <span className="pad-article-name">{selectedArt.artikelname}</span>
                        {selectedArt.hersteller && <span className="pad-manufacturer">{selectedArt.hersteller}</span>}
                      </div>
                      <div className="pad-price-row">
                        <span className="pad-article-id">{selectedArt.artikel_id}</span>
                        <span className="pad-price">EP: {formatPrice(selectedArt.price_net)}</span>
                        <span className="pad-price">GP: {formatPrice(selectedArt.total_net)}</span>
                      </div>
                    </div>
                  ) : null
                })()}
                {showAssignmentDetails && !hasSelection && !isDL && !isRejected && (
                  <div className="position-assignment-detail pad-empty">
                    Kein Artikel zugeordnet
                  </div>
                )}
                {!showAssignmentDetails && hasSelection && (() => {
                  const primaryId = selectedArticleIds[position.id]?.[0]
                  const selectedArt = primaryId ? (suggestionMap[position.id] ?? []).find(
                    s => s.artikel_id === primaryId
                  ) : undefined
                  if (!selectedArt && componentSelectionCount > 0) {
                    return (
                      <div className="position-selected-article">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <span>{componentSelectionCount} Artikel zugeordnet</span>
                      </div>
                    )
                  }
                  return selectedArt ? (
                    <div className="position-selected-article">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                        <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <span>{selectedArt.artikelname}</span>
                    </div>
                  ) : null
                })()}
                {!showAssignmentDetails && !hasSelection && componentSuggestionCount > 0 && (
                  <div className="position-selected-article">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                      <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <span>{componentSuggestionCount} Artikel vorgeschlagen</span>
                  </div>
                )}
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
              {showAssignmentDetails && onEditPosition && !isDL && (
                <button
                  type="button"
                  className="position-edit-btn"
                  title="Position in Zuordnungsansicht bearbeiten"
                  onClick={(e) => { e.stopPropagation(); onEditPosition(position.id) }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              )}
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
