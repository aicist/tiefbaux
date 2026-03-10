import { useState } from 'react'
import type { CompatibilityIssue, LVPosition, ProductSearchResult, ProductSuggestion, TechnicalParameters } from '../types'
import { ParameterEditor } from './ParameterEditor'
import { ProductSearchModal } from './ProductSearchModal'

type Props = {
  activePosition: LVPosition | null
  suggestions: ProductSuggestion[]
  selectedArticleId: string | undefined
  onSelectArticle: (positionId: string, artikelId: string) => void
  onManualSelect: (positionId: string, product: ProductSearchResult) => void
  compatibilityIssues: CompatibilityIssue[]
  onParameterChange: (positionId: string, params: Partial<TechnicalParameters>) => void
  isRefreshingSuggestions: boolean
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

export function SuggestionsPanel({
  activePosition,
  suggestions,
  selectedArticleId,
  onSelectArticle,
  onManualSelect,
  compatibilityIssues,
  onParameterChange,
  isRefreshingSuggestions,
}: Props) {
  const [dismissedIds, setDismissedIds] = useState<Record<string, Set<string>>>({})
  const [searchOpen, setSearchOpen] = useState(false)

  const posId = activePosition?.id ?? ''
  const dismissed = dismissedIds[posId] ?? new Set()
  const visibleSuggestions = suggestions.filter(s => !dismissed.has(s.artikel_id))

  function handleDismiss(artikelId: string) {
    if (!activePosition) return
    setDismissedIds(prev => {
      const current = new Set(prev[posId] ?? [])
      current.add(artikelId)
      return { ...prev, [posId]: current }
    })
    // If dismissed article was selected, auto-select next
    if (selectedArticleId === artikelId) {
      const next = visibleSuggestions.find(s => s.artikel_id !== artikelId)
      if (next) onSelectArticle(activePosition.id, next.artikel_id)
    }
  }

  return (
    <aside className="panel suggestions-panel">
      <div className="panel-header">
        <div className="panel-number">3</div>
        <div>
          <h2>Artikelvorschläge</h2>
          <p className="panel-copy">
            {activePosition
              ? `Vorschläge für Position ${activePosition.ordnungszahl}`
              : 'Position aus der Mitte auswählen'}
          </p>
        </div>
      </div>

      {!activePosition && (
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" className="empty-icon">
            <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" stroke="currentColor" strokeWidth="1.5" />
            <rect x="9" y="3" width="6" height="4" rx="1" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <p>Wählen Sie eine Position, um passende Artikel zu sehen.</p>
        </div>
      )}

      {activePosition && (
        <ParameterEditor
          position={activePosition}
          onParameterChange={onParameterChange}
          isRefreshing={isRefreshingSuggestions}
        />
      )}

      {activePosition && visibleSuggestions.length === 0 && !isRefreshingSuggestions && (
        <div className="no-match-info">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
            <path d="M8 12h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <div>
            <strong>Kein passender Artikel gefunden</strong>
            <p>
              <button className="link-btn" onClick={() => setSearchOpen(true)}>
                Katalog manuell durchsuchen
              </button>
            </p>
          </div>
        </div>
      )}

      <div className="suggestions-list">
        {activePosition &&
          visibleSuggestions.map((suggestion, idx) => {
            const isSelected = selectedArticleId === suggestion.artikel_id
            const stock = stockStatus(suggestion.stock)
            const isBest = idx === 0 && !suggestion.is_manual
            const hasWarnings = suggestion.warnings.length > 0

            return (
              <div
                key={suggestion.artikel_id}
                className={`suggestion-card ${isSelected ? 'selected' : ''} ${suggestion.is_manual ? 'manual' : ''}`}
              >
                <div className="suggestion-body" onClick={() => {
                  if (!isSelected) onSelectArticle(activePosition.id, suggestion.artikel_id)
                }}>
                  <div className="suggestion-header">
                    <div className="suggestion-title-group">
                      {suggestion.is_manual && <span className="manual-badge">Manuell gewählt</span>}
                      {isBest && <span className="best-badge">Bester Treffer</span>}
                      <strong className="suggestion-name">{suggestion.artikelname}</strong>
                    </div>
                    <div className="suggestion-header-actions">
                      {!suggestion.is_manual && suggestion.score_breakdown.length > 0 && (
                        <details className="score-details" onClick={e => e.stopPropagation()}>
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
                                <span className={`breakdown-points ${b.points >= 0 ? 'positive' : 'negative'}`}>
                                  {b.points > 0 ? '+' : ''}{b.points}
                                </span>
                                <span className="breakdown-detail">{b.detail}</span>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  </div>

                  <div className="suggestion-meta">
                    <span>{suggestion.artikel_id}</span>
                    <span className="meta-sep" />
                    <span>{suggestion.hersteller ?? 'Unbekannt'}</span>
                    {suggestion.dn && (
                      <>
                        <span className="meta-sep" />
                        <span>DN {suggestion.dn}</span>
                      </>
                    )}
                  </div>

                  <div className="suggestion-price-row">
                    <div className="price-group">
                      <span className="price-main">{formatMoney(suggestion.price_net, suggestion.currency)}</span>
                      <span className="price-label">/ Einheit</span>
                    </div>
                    <div className="price-group">
                      <span className="price-total">{formatMoney(suggestion.total_net, suggestion.currency)}</span>
                      <span className="price-label">Gesamt</span>
                    </div>
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
                      {suggestion.warnings.map((warning) => (
                        <span key={warning} className="warning-chip">{warning}</span>
                      ))}
                    </div>
                  )}

                  {suggestion.reasons.length > 0 && !suggestion.is_manual && (
                    <div className="reason-chips">
                      {suggestion.reasons.map((reason) => (
                        <span key={reason} className="reason-chip">{reason}</span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="suggestion-actions">
                  {isSelected ? (
                    <div className="action-confirmed" title="Ausgewählt">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                  ) : (
                    <button
                      className="action-btn accept"
                      title="Auswählen"
                      onClick={(e) => { e.stopPropagation(); onSelectArticle(activePosition.id, suggestion.artikel_id) }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                  )}
                  <button
                    className="action-btn reject"
                    title="Ablehnen"
                    onClick={(e) => { e.stopPropagation(); handleDismiss(suggestion.artikel_id) }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                    </svg>
                  </button>
                  <button
                    className="action-btn search"
                    title="Ersetzen (Katalog durchsuchen)"
                    onClick={(e) => { e.stopPropagation(); setSearchOpen(true) }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                      <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </button>
                </div>
              </div>
            )
          })}
      </div>

      <div className="compatibility-box">
        <h3>Regelengine</h3>
        {compatibilityIssues.length === 0 && <p className="compat-ok">Keine Konflikte erkannt.</p>}
        {compatibilityIssues.map((issue) => (
          <div
            key={`${issue.rule}-${issue.message}`}
            className={`issue-item ${issue.severity === 'KRITISCH' ? 'critical' : 'warning'} ${
              activePosition && issue.positions.includes(activePosition.id) ? 'issue-active' : ''
            }`}
          >
            <div className="issue-header">
              <span className={`issue-severity ${issue.severity === 'KRITISCH' ? 'sev-critical' : 'sev-warning'}`}>
                {issue.severity}
              </span>
              <span className="issue-rule">{issue.rule}</span>
            </div>
            <p>{issue.message}</p>
          </div>
        ))}
      </div>

      {activePosition && (
        <ProductSearchModal
          isOpen={searchOpen}
          onClose={() => setSearchOpen(false)}
          onSelect={(product) => onManualSelect(activePosition.id, product)}
          initialCategory={activePosition.parameters.product_category}
          initialDn={activePosition.parameters.nominal_diameter_dn}
        />
      )}
    </aside>
  )
}
