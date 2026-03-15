import { useCallback, useEffect, useMemo, useState } from 'react'
import type { LVPosition, PriceAdjustment, ProductSearchResult, ProductSuggestion } from '../types'
import { DinBadge } from './DinBadge'
import { PriceAdjustmentControl } from './PriceAdjustmentControl'
import { ProductSearchModal } from './ProductSearchModal'
import { computeAdjustedTotal, computeAdjustedUnitPrice, isAdjustedPrice } from '../utils/pricing'

const PARAM_STYLES: Record<string, React.CSSProperties> = {
  match: { background: '#dcfce7', color: '#166534' },
  mismatch: { background: '#fee2e2', color: '#991b1b' },
  neutral: { background: '#f1f5f9', color: '#334155' },
}

const LOAD_CLASS_CATEGORIES = new Set(['Schachtabdeckungen', 'Straßenentwässerung'])

function ParamBadge({ label, status }: { label: string; status: 'match' | 'mismatch' | 'neutral' }) {
  return (
    <span
      className={`param-badge param-${status}`}
      style={{ ...PARAM_STYLES[status], padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}
    >
      {label}
    </span>
  )
}

function extractSnFromText(text: string): number | null {
  const match = text.match(/SN\s*(\d+)/i)
  return match ? parseInt(match[1], 10) : null
}

function formatMoney(value?: number | null, currency = 'EUR'): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value)
}

function scoreColor(score: number): string {
  if (score >= 50) return '#16a34a'
  if (score >= 30) return '#ca8a04'
  return '#dc2626'
}

function stockStatus(stock?: number | null): { label: string; className: string } {
  if (stock == null || stock <= 0) return { label: 'Nicht auf Lager', className: 'stock-red' }
  if (stock < 10) return { label: `${stock} auf Lager`, className: 'stock-amber' }
  return { label: `${stock} auf Lager`, className: 'stock-green' }
}

export type AssignmentDecision = 'accepted' | 'rejected' | 'skipped'

type FilterTab = 'alle' | 'zugeordnet' | 'offen' | 'dienstleistung'

type Props = {
  positions: LVPosition[]
  suggestionMap: Record<string, ProductSuggestion[]>
  selectedArticleIds: Record<string, string>
  skippedPositionIds: Set<string>
  priceAdjustments: Record<string, PriceAdjustment>
  onAccept: (positionId: string, artikelId: string) => void
  onReject: (positionId: string) => void
  onManualSelect: (positionId: string, product: ProductSearchResult) => void
  onPriceAdjustmentChange: (positionId: string, adjustment: PriceAdjustment) => void
  onFinish: () => void
  onBackToOverview: () => void
}

export function AssignmentView({
  positions,
  suggestionMap,
  selectedArticleIds,
  skippedPositionIds,
  priceAdjustments,
  onAccept,
  onReject,
  onManualSelect,
  onPriceAdjustmentChange,
  onFinish,
  onBackToOverview,
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(0)
  const [decisions, setDecisions] = useState<Record<string, AssignmentDecision>>({})
  const [searchOpen, setSearchOpen] = useState(false)
  const [slideDirection, setSlideDirection] = useState<'left' | 'right' | null>(null)
  const [activeFilter, setActiveFilter] = useState<FilterTab>('alle')

  // Categorize positions
  const materialPositions = useMemo(
    () => positions.filter(p => !skippedPositionIds.has(p.id)),
    [positions, skippedPositionIds],
  )

  const servicePositions = useMemo(
    () => positions.filter(p => skippedPositionIds.has(p.id)),
    [positions, skippedPositionIds],
  )

  // Filtered positions based on active tab
  const filteredPositions = useMemo(() => {
    switch (activeFilter) {
      case 'zugeordnet':
        return materialPositions.filter(p => selectedArticleIds[p.id])
      case 'offen':
        return materialPositions.filter(p => !selectedArticleIds[p.id])
      case 'dienstleistung':
        return servicePositions
      default:
        return materialPositions
    }
  }, [activeFilter, materialPositions, servicePositions, selectedArticleIds])

  // Tab counts
  const assignedCount = useMemo(
    () => materialPositions.filter(p => selectedArticleIds[p.id]).length,
    [materialPositions, selectedArticleIds],
  )
  const openCount = useMemo(
    () => materialPositions.filter(p => !selectedArticleIds[p.id]).length,
    [materialPositions, selectedArticleIds],
  )

  const currentPosition = filteredPositions[currentIndex] ?? null
  const currentSuggestions = currentPosition ? suggestionMap[currentPosition.id] ?? [] : []
  const currentSelectedArticle = currentPosition ? selectedArticleIds[currentPosition.id] : undefined
  const totalCount = filteredPositions.length
  const decidedCount = Object.keys(decisions).length

  const isFinished = currentIndex >= totalCount

  // Reset index when filter changes
  useEffect(() => {
    setCurrentIndex(0)
  }, [activeFilter])

  // Slide animation
  useEffect(() => {
    if (slideDirection) {
      const timer = setTimeout(() => setSlideDirection(null), 300)
      return () => clearTimeout(timer)
    }
  }, [slideDirection])

  const goNext = useCallback(() => {
    setSlideDirection('left')
    setCurrentIndex(prev => Math.min(prev + 1, totalCount))
  }, [totalCount])

  const goPrev = useCallback(() => {
    if (currentIndex > 0) {
      setSlideDirection('right')
      setCurrentIndex(prev => prev - 1)
    }
  }, [currentIndex])

  const handleSelectArticle = useCallback((artikelId: string) => {
    if (!currentPosition) return
    onAccept(currentPosition.id, artikelId)
  }, [currentPosition, onAccept])

  const handleContinue = useCallback(() => {
    if (!currentPosition || !currentSelectedArticle) return
    setDecisions(prev => ({ ...prev, [currentPosition.id]: 'accepted' }))
    goNext()
  }, [currentPosition, currentSelectedArticle, goNext])

  const handleReject = useCallback(() => {
    if (!currentPosition) return
    onReject(currentPosition.id)
    setDecisions(prev => ({ ...prev, [currentPosition.id]: 'rejected' }))
    goNext()
  }, [currentPosition, onReject, goNext])

  const handleSkip = useCallback(() => {
    if (!currentPosition) return
    setDecisions(prev => ({ ...prev, [currentPosition.id]: 'skipped' }))
    goNext()
  }, [currentPosition, goNext])

  const handleManualSearchSelect = useCallback((product: ProductSearchResult) => {
    if (!currentPosition) return
    onManualSelect(currentPosition.id, product)
    setSearchOpen(false)
  }, [currentPosition, onManualSelect])

  const handleSkipAll = useCallback(() => {
    filteredPositions.forEach(p => {
      if (!decisions[p.id]) {
        setDecisions(prev => ({ ...prev, [p.id]: 'skipped' }))
      }
    })
    setCurrentIndex(totalCount)
  }, [filteredPositions, decisions, totalCount])

  // Keyboard shortcuts
  useEffect(() => {
    if (isFinished || searchOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

      switch (e.key) {
        case 'Enter':
          e.preventDefault()
          if (currentSelectedArticle ?? currentSuggestions[0]?.artikel_id) {
            handleContinue()
          }
          break
        case 'Escape':
          e.preventDefault()
          handleReject()
          break
        case 'ArrowRight':
          e.preventDefault()
          handleSkip()
          break
        case 'ArrowLeft':
          e.preventDefault()
          goPrev()
          break
        case 's':
        case 'S':
          e.preventDefault()
          setSearchOpen(true)
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isFinished, searchOpen, currentSuggestions, currentSelectedArticle, handleContinue, handleReject, handleSkip, goPrev])

  // Summary screen
  if (isFinished) {
    const acceptedCount = Object.values(decisions).filter(d => d === 'accepted').length
    const rejectedCount = Object.values(decisions).filter(d => d === 'rejected').length
    const skippedCount = totalCount - acceptedCount - rejectedCount
    const svcCount = positions.length - materialPositions.length

    // Calculate total value
    let totalValue = 0
    for (const [posId, artId] of Object.entries(selectedArticleIds)) {
      if (skippedPositionIds.has(posId)) continue
      const suggestions = suggestionMap[posId]
      if (!suggestions) continue
      const match = suggestions.find(s => s.artikel_id === artId)
      const position = positions.find(p => p.id === posId)
      const adjustedTotal = computeAdjustedTotal(
        computeAdjustedUnitPrice(match?.price_net, priceAdjustments[posId]),
        position?.quantity,
      )
      if (adjustedTotal != null) totalValue += adjustedTotal
    }

    return (
      <div className="assignment-view">
        <div className="assignment-summary">
          <div className="summary-icon">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="#16a34a" strokeWidth="1.5" />
              <path d="M8 12l3 3 5-5" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h2>Zuordnung abgeschlossen</h2>

          <div className="summary-stats">
            <div className="summary-stat stat-accepted">
              <span className="stat-number">{acceptedCount}</span>
              <span className="stat-label">Zugeordnet</span>
            </div>
            <div className="summary-stat stat-rejected">
              <span className="stat-number">{rejectedCount}</span>
              <span className="stat-label">Ohne Zuordnung</span>
            </div>
            <div className="summary-stat stat-skipped">
              <span className="stat-number">{skippedCount}</span>
              <span className="stat-label">Übersprungen</span>
            </div>
            {svcCount > 0 && (
              <div className="summary-stat stat-service">
                <span className="stat-number">{svcCount}</span>
                <span className="stat-label">Dienstleistungen</span>
              </div>
            )}
          </div>

          {totalValue > 0 && (
            <div className="summary-total">
              Geschätzter Gesamtwert: {formatMoney(totalValue)}
            </div>
          )}

          <div className="summary-actions">
            <button className="btn btn-secondary" onClick={() => { setCurrentIndex(0); setDecisions({}) }}>
              Nochmal durchgehen
            </button>
            <button className="btn btn-secondary" onClick={onBackToOverview}>
              Zur Übersicht
            </button>
            <button className="btn btn-primary" onClick={onFinish}>
              Angebot exportieren
            </button>
          </div>
        </div>
      </div>
    )
  }

  const isServiceView = activeFilter === 'dienstleistung'
  const topSuggestion = currentSuggestions[0] ?? null
  const otherSuggestions = currentSuggestions.slice(1)
  const showLoadClass = currentPosition ? LOAD_CLASS_CATEGORIES.has(currentPosition.parameters.product_category ?? '') : false
  const currentPriceAdjustment = currentPosition ? priceAdjustments[currentPosition.id] : undefined
  const pricingReferenceSuggestion = currentSuggestions.find((s) => s.artikel_id === currentSelectedArticle) ?? topSuggestion
  const progressPercent = totalCount > 0 ? (currentIndex / totalCount) * 100 : 0

  return (
    <div className="assignment-view">
      {/* Filter tabs */}
      <div className="assignment-tabs">
        <button
          className={`tab-btn ${activeFilter === 'alle' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('alle')}
        >
          Alle ({materialPositions.length})
        </button>
        <button
          className={`tab-btn ${activeFilter === 'zugeordnet' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('zugeordnet')}
        >
          Zugeordnet ({assignedCount})
        </button>
        <button
          className={`tab-btn ${activeFilter === 'offen' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('offen')}
        >
          Offen ({openCount})
        </button>
        <button
          className={`tab-btn ${activeFilter === 'dienstleistung' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('dienstleistung')}
        >
          Dienstleistung ({servicePositions.length})
        </button>
        <div className="tab-spacer" />
        <button className="btn btn-ghost btn-overview" onClick={onBackToOverview}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="14" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Übersicht
        </button>
      </div>

      {/* Progress bar */}
      <div className="assignment-progress">
        <div className="progress-text">
          <span>{totalCount > 0 ? currentIndex + 1 : 0} / {totalCount} Positionen</span>
          <span className="progress-decided">{decidedCount} bearbeitet</span>
        </div>
        <div className="progress-bar-track">
          <div className="progress-bar-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="progress-shortcuts">
          Enter = Übernehmen & weiter &middot; Esc = Ablehnen &middot; Pfeiltasten = Navigation &middot; S = Suchen
        </div>
      </div>

      {/* Empty state when no positions in filter */}
      {totalCount === 0 && (
        <div className="assignment-card">
          <div className="assignment-no-match">
            <p>Keine Positionen in dieser Kategorie.</p>
          </div>
        </div>
      )}

      {/* Position card */}
      {currentPosition && (
        <div className={`assignment-card ${slideDirection === 'left' ? 'slide-out-left' : slideDirection === 'right' ? 'slide-out-right' : 'slide-in'}`}>
          <div className="assignment-position">
            <div className="position-oz">OZ {currentPosition.ordnungszahl}</div>
            <div className="position-desc">{currentPosition.description}</div>
            <div className="position-params">
              {currentPosition.parameters.nominal_diameter_dn && (
                <span className="param-chip">DN {currentPosition.parameters.nominal_diameter_dn}</span>
              )}
              {currentPosition.parameters.material && (
                <span className="param-chip">{currentPosition.parameters.material}</span>
              )}
              {currentPosition.parameters.product_category && (
                <span className="param-chip">{currentPosition.parameters.product_category}</span>
              )}
              {currentPosition.parameters.load_class && (
                <span className="param-chip">{currentPosition.parameters.load_class}</span>
              )}
              {currentPosition.parameters.stiffness_class_sn && (
                <span className="param-chip">SN{currentPosition.parameters.stiffness_class_sn}</span>
              )}
              {currentPosition.quantity != null && currentPosition.unit && (
                <span className="param-chip quantity">{currentPosition.quantity} {currentPosition.unit}</span>
              )}
            </div>
            {isServiceView && (
              <div className="service-badge-info">Dienstleistung — nicht im Angebot enthalten</div>
            )}
          </div>

          {!isServiceView && currentPosition && pricingReferenceSuggestion && (
            <PriceAdjustmentControl
              adjustment={currentPriceAdjustment}
              baseUnitPrice={pricingReferenceSuggestion.price_net}
              quantity={currentPosition.quantity}
              currency={pricingReferenceSuggestion.currency}
              onChange={(next) => onPriceAdjustmentChange(currentPosition.id, next)}
            />
          )}

          {/* Top suggestion (not for service positions) */}
          {!isServiceView && topSuggestion && (
            <div className="assignment-top-suggestion">
              <div className="top-label">Bester Vorschlag</div>
              {renderSuggestionCard(
                topSuggestion,
                currentPosition,
                showLoadClass,
                true,
                currentPriceAdjustment,
                currentSelectedArticle,
                () => handleSelectArticle(topSuggestion.artikel_id),
              )}
              <div className="top-actions">
                <button className="btn btn-accept" onClick={handleContinue} disabled={!currentSelectedArticle}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Übernehmen & weiter
                </button>
                <button className="btn btn-reject" onClick={handleReject}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                  </svg>
                  Ablehnen
                </button>
              </div>
            </div>
          )}

          {!isServiceView && !topSuggestion && (
            <div className="assignment-no-match">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
                <path d="M8 12h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <p>Kein passender Artikel gefunden</p>
              <div className="top-actions">
                <button className="btn btn-primary" onClick={() => setSearchOpen(true)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                    <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Manuell suchen
                </button>
              </div>
            </div>
          )}

          {/* Other suggestions (collapsed) */}
          {!isServiceView && otherSuggestions.length > 0 && (
            <details className="assignment-alternatives">
              <summary>Weitere Vorschläge ({otherSuggestions.length})</summary>
              <div className="alternatives-list">
                {otherSuggestions.map(s => (
                  <div key={s.artikel_id} className="alternative-card">
                    {renderSuggestionCard(
                      s,
                      currentPosition,
                      showLoadClass,
                      false,
                      currentPriceAdjustment,
                      currentSelectedArticle,
                      () => handleSelectArticle(s.artikel_id),
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Manual search button */}
          {!isServiceView && topSuggestion && (
            <button className="btn btn-ghost assignment-search-btn" onClick={() => setSearchOpen(true)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              Manuell suchen
            </button>
          )}
        </div>
      )}

      {/* Navigation — single row, no duplicate skip */}
      {totalCount > 0 && (
        <div className="assignment-nav">
          <button
            className="btn btn-primary"
            onClick={handleContinue}
            disabled={!currentSelectedArticle || isServiceView}
          >
            Übernehmen & weiter
          </button>

          <button
            className="btn btn-ghost"
            onClick={goPrev}
            disabled={currentIndex === 0}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Zurück
          </button>

          <button className="btn btn-ghost" onClick={handleSkip}>
            Überspringen
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          <button className="btn btn-ghost btn-skip-all" onClick={handleSkipAll}>
            Alle offenen überspringen
          </button>
        </div>
      )}

      {/* Product search modal */}
      {currentPosition && (
        <ProductSearchModal
          isOpen={searchOpen}
          onClose={() => setSearchOpen(false)}
          onSelect={handleManualSearchSelect}
          initialCategory={currentPosition.parameters.product_category}
          initialDn={currentPosition.parameters.nominal_diameter_dn}
        />
      )}
    </div>
  )
}

function renderSuggestionCard(
  suggestion: ProductSuggestion,
  position: LVPosition,
  showLoadClass: boolean,
  isTop: boolean,
  priceAdjustment: PriceAdjustment | undefined,
  currentSelectedArticle: string | undefined,
  onSelect: () => void,
) {
  const stock = stockStatus(suggestion.stock)
  const isSelected = currentSelectedArticle === suggestion.artikel_id
  const adjustedUnitPrice = computeAdjustedUnitPrice(suggestion.price_net, priceAdjustment)
  const adjustedTotal = computeAdjustedTotal(adjustedUnitPrice, position.quantity)
  const showAdjusted = isSelected && isAdjustedPrice(suggestion.price_net, adjustedUnitPrice)
  const hasWarnings = suggestion.warnings.length > 0

  return (
    <div
      className={`assignment-suggestion ${isTop ? 'suggestion-top' : ''} ${isSelected ? 'selected' : ''}`}
      onClick={onSelect}
    >
      <div className="suggestion-header">
        <div className="suggestion-title-group">
          {suggestion.is_manual && <span className="manual-badge">Manuell gewählt</span>}
          {suggestion.is_override && <span className="override-badge">Häufig gewählt von Kollegen</span>}
          {isTop && !suggestion.is_manual && !suggestion.is_override && <span className="best-badge">Bester Treffer</span>}
          <strong className="suggestion-name">{suggestion.artikelname}</strong>
        </div>
        <div className="suggestion-header-actions">
          {!suggestion.is_manual && !suggestion.is_override && suggestion.score_breakdown.length > 0 ? (
            <details className="score-details" onClick={(e) => e.stopPropagation()}>
              <summary
                className="score-badge"
                style={{ '--score-color': scoreColor(suggestion.score) } as React.CSSProperties}
              >
                {suggestion.score.toFixed(0)}
              </summary>
              <div className="score-breakdown">
                {suggestion.score_breakdown.map((b) => (
                  <div key={b.component} className={`breakdown-row ${b.points > 0 ? 'row-positive' : b.points < 0 ? 'row-negative' : 'row-neutral'}`}>
                    <span className="breakdown-component">{b.component}</span>
                    <span className={`breakdown-points ${b.points > 0 ? 'positive' : b.points < 0 ? 'negative' : 'zero'}`}>
                      {b.points > 0 ? '+' : ''}{b.points}
                    </span>
                    <span className="breakdown-detail">{b.detail}</span>
                  </div>
                ))}
              </div>
            </details>
          ) : (
            !suggestion.is_manual && suggestion.score > 0 && (
              <span
                className="score-pill"
                style={{ '--score-color': scoreColor(suggestion.score) } as React.CSSProperties}
              >
                {suggestion.score.toFixed(0)}
              </span>
            )
          )}
        </div>
      </div>

      <div className="suggestion-meta">
        <span>{suggestion.artikel_id}</span>
        <span className="meta-sep" />
        <span>{suggestion.hersteller ?? 'Unbekannt'}</span>
      </div>

      <div className="param-badges">
        {suggestion.dn != null && (() => {
          const text = `${position.description ?? ''} ${position.raw_text ?? ''}`
          const dnMatch = text.match(/DN\s*(\d+)/i)
          const reqDn = position.parameters.nominal_diameter_dn ?? (dnMatch ? parseInt(dnMatch[1], 10) : null)
          return <ParamBadge
            label={`DN ${suggestion.dn}`}
            status={reqDn == null ? 'neutral' : reqDn === suggestion.dn ? 'match' : 'mismatch'}
          />
        })()}
        {suggestion.sn != null && (() => {
          const reqSn = position.parameters.stiffness_class_sn
            ?? extractSnFromText(position.description ?? '')
            ?? extractSnFromText(position.raw_text ?? '')
          return <ParamBadge
            label={`SN${suggestion.sn}`}
            status={reqSn == null ? 'neutral' : suggestion.sn! >= reqSn ? 'match' : 'mismatch'}
          />
        })()}
        {showLoadClass && suggestion.load_class && <ParamBadge
          label={suggestion.load_class}
          status={!position.parameters.load_class ? 'neutral' : position.parameters.load_class.toUpperCase() === suggestion.load_class.toUpperCase() ? 'match' : 'mismatch'}
        />}
        {suggestion.norm && (
          <span className={`param-badge param-${!position.parameters.norm ? 'neutral' : suggestion.norm.toLowerCase().includes(position.parameters.norm.toLowerCase()) ? 'match' : 'mismatch'}`}
            style={{
              ...PARAM_STYLES[!position.parameters.norm ? 'neutral' : suggestion.norm.toLowerCase().includes(position.parameters.norm.toLowerCase()) ? 'match' : 'mismatch'],
              padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
            }}
          >
            <DinBadge norm={suggestion.norm} />
          </span>
        )}
      </div>

      <div className="suggestion-price-stack">
        <div className="suggestion-price-row">
          <div className="price-group">
            <span className="price-main">{formatMoney(suggestion.price_net, suggestion.currency)}</span>
            <span className="price-label">EK / Einheit</span>
          </div>
          <div className="price-group">
            <span className="price-total">{formatMoney(suggestion.total_net, suggestion.currency)}</span>
            <span className="price-label">EK gesamt</span>
          </div>
        </div>
        {showAdjusted && (
          <div className="suggestion-price-row suggestion-price-row-vk">
            <div className="price-group">
              <span className="price-main">{formatMoney(adjustedUnitPrice, suggestion.currency)}</span>
              <span className="price-label">VK / Einheit</span>
            </div>
            <div className="price-group">
              <span className="price-total">{formatMoney(adjustedTotal, suggestion.currency)}</span>
              <span className="price-label">VK gesamt</span>
            </div>
          </div>
        )}
      </div>

      <div className="suggestion-stock-row">
        <span className={`stock-indicator ${stock.className}`}>
          <span className="stock-dot" />
          {stock.label}
        </span>
        {suggestion.delivery_days != null && (
          <span className="delivery-badge">
            {suggestion.delivery_days} Tage Lieferzeit
          </span>
        )}
      </div>

      {hasWarnings && (
        <div className="suggestion-warnings">
          {suggestion.warnings.map(w => (
            <span key={w} className="warning-chip">{w}</span>
          ))}
        </div>
      )}

      {suggestion.reasons.length > 0 && !suggestion.is_manual && (
        <div className="reason-chips">
          {suggestion.reasons.map((reason) => {
            const isNegative = reason.includes('abweichend') || reason.includes('weicht ab') || reason.includes('unter ') || reason.includes('≠')
            return (
              <span key={reason} className={`reason-chip ${isNegative ? 'reason-negative' : ''}`}>{reason}</span>
            )
          })}
        </div>
      )}
    </div>
  )
}
