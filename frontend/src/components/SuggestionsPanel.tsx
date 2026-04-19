import { useState } from 'react'
import type { ComponentSuggestions, LVPosition, PriceAdjustment, ProductSearchResult, ProductSuggestion, TechnicalParameters } from '../types'
import { DinBadge } from './DinBadge'
import { InquiryModal } from './InquiryModal'
import { ParameterEditor } from './ParameterEditor'
import { PriceAdjustmentControl } from './PriceAdjustmentControl'
import { ProductSearchModal } from './ProductSearchModal'
import { computeAdjustedTotal, computeAdjustedUnitPrice, isAdjustedPrice } from '../utils/pricing'
import { primaryAssignmentKey } from '../utils/assignmentKeys'

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
      style={{ ...PARAM_STYLES[status], padding: '1px 7px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600 }}
    >
      {label}
    </span>
  )
}

function extractSnFromText(text: string): number | null {
  const match = text.match(/SN\s*(\d+)/i)
  return match ? parseInt(match[1], 10) : null
}

function shouldShowNormBadge(_position: LVPosition | null, suggestion: ProductSuggestion): boolean {
  if (!suggestion.norm) return false
  return true
}

function filterSuggestionWarnings(warnings: string[]): string[] {
  return warnings.filter((warning) => {
    const lower = warning.toLowerCase()
    return lower.includes('menge nicht erkannt')
      || lower.includes('listenpreis ist 0')
      || lower.includes('kein preis verfügbar')
  })
}

function filterSuggestionReasons(reasons: string[]): string[] {
  return reasons.filter((reason) => {
    const lower = reason.toLowerCase()
    if (lower.includes('norm abweichend')) return false
    if (lower.includes('lager')) return false
    if (/^(dn|od|anschluss-dn)\b/i.test(reason)) return false
    return true
  })
}

type Props = {
  activePosition: LVPosition | null
  suggestions: ProductSuggestion[]
  componentSuggestions?: ComponentSuggestions[] | null
  selectedArticleIds: string[]
  priceAdjustment?: PriceAdjustment
  onSelectArticle: (positionId: string, artikelId: string) => void
  onManualSelect: (positionId: string, product: ProductSearchResult) => void
  onParameterChange: (positionId: string, params: Partial<TechnicalParameters>) => void
  isRefreshingSuggestions: boolean
  onPriceAdjustmentChange: (positionId: string, adjustment: PriceAdjustment) => void
  projectId?: number | null
  projectName?: string | null
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
  componentSuggestions = null,
  selectedArticleIds,
  priceAdjustment,
  onSelectArticle,
  onManualSelect,
  onParameterChange,
  isRefreshingSuggestions,
  projectId,
  projectName,
  onPriceAdjustmentChange,
}: Props) {
  const [dismissedIds, setDismissedIds] = useState<Record<string, Set<string>>>({})
  const [searchOpen, setSearchOpen] = useState(false)
  const [inquiryOpen, setInquiryOpen] = useState(false)

  const posId = activePosition?.id ?? ''
  const dismissed = dismissedIds[posId] ?? new Set()
  const visibleSuggestions = suggestions.filter(s => !dismissed.has(s.artikel_id))
  const selectedArticleId = selectedArticleIds[0]
  const selectedSuggestion = suggestions.find((s) => s.artikel_id === selectedArticleId) ?? visibleSuggestions[0] ?? null
  const adjustedSelectedUnitPrice = computeAdjustedUnitPrice(selectedSuggestion?.price_net, priceAdjustment)
  const adjustedSelectedTotal = computeAdjustedTotal(adjustedSelectedUnitPrice, activePosition?.quantity)
  const showLoadClass = activePosition?.parameters.product_category
    ? LOAD_CLASS_CATEGORIES.has(activePosition.parameters.product_category)
    : false

  function handleDismiss(artikelId: string) {
    if (!activePosition) return
    setDismissedIds(prev => {
      const current = new Set(prev[posId] ?? [])
      current.add(artikelId)
      return { ...prev, [posId]: current }
    })
    if (selectedArticleIds.includes(artikelId)) {
      const next = visibleSuggestions.find(s => s.artikel_id !== artikelId)
      if (next) onSelectArticle(activePosition.id, next.artikel_id)
    }
  }

  return (
    <aside className="panel suggestions-panel">
      <div className="panel-header">
        <div className="panel-number">3</div>
        <div>
          <h2>Lieferantenanfragen</h2>
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
          <p>Lieferantenanfragen sind verfügbar, sobald ein Projekt geladen ist.</p>
        </div>
      )}

      {activePosition && (
        <ParameterEditor
          position={activePosition}
          onParameterChange={onParameterChange}
          isRefreshing={isRefreshingSuggestions}
        />
      )}

      {activePosition && selectedSuggestion && (
        <PriceAdjustmentControl
          adjustment={priceAdjustment}
          baseUnitPrice={selectedSuggestion.price_net}
          quantity={activePosition.quantity}
          currency={selectedSuggestion.currency}
          onChange={(next) => onPriceAdjustmentChange(primaryAssignmentKey(activePosition.id), next)}
        />
      )}

      {activePosition && componentSuggestions && componentSuggestions.length > 0 && (
        <div className="multi-component-section">
          <div className="multi-component-badge">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Mehrkomponenten-Position ({componentSuggestions.length} Teile)
          </div>
          <div className="component-list">
            {componentSuggestions.map((component) => {
              const topSuggestion = component.suggestions[0]
              return (
                <div key={component.component_name} className="component-card">
                  <div className="component-card-header">
                    <span className="component-name">{component.component_name}</span>
                    <span className="component-qty">{component.quantity}x</span>
                  </div>
                  {topSuggestion ? (
                    <div className="component-match">
                      <div className="component-match-info">
                        <span className="component-article-name">{topSuggestion.artikelname}</span>
                        <span className="component-article-meta">
                          {topSuggestion.artikel_id}
                          {topSuggestion.hersteller && <> &middot; {topSuggestion.hersteller}</>}
                          {topSuggestion.dn != null && <> &middot; DN{topSuggestion.dn}</>}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="component-no-match">Kein passender Artikel</div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {activePosition && visibleSuggestions.length === 0 && !componentSuggestions?.length && !isRefreshingSuggestions && (
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
            <p>
              <button className="link-btn btn-inquiry" onClick={() => setInquiryOpen(true)}>
                Lieferantenanfrage senden
              </button>
            </p>
          </div>
        </div>
      )}

      <div className="suggestions-list">
        {activePosition &&
          visibleSuggestions.map((suggestion, idx) => {
            const isSelected = selectedArticleIds.includes(suggestion.artikel_id)
            const stock = stockStatus(suggestion.stock)
            const isBest = idx === 0 && !suggestion.is_manual && !suggestion.is_override
            const filteredWarnings = filterSuggestionWarnings(suggestion.warnings)
            const filteredReasons = filterSuggestionReasons(suggestion.reasons)
            const hasWarnings = filteredWarnings.length > 0
            const isSelectedAdjusted = isSelected && isAdjustedPrice(suggestion.price_net, adjustedSelectedUnitPrice)
            const displayUnitPrice = isSelectedAdjusted ? adjustedSelectedUnitPrice : suggestion.price_net
            const displayTotal = isSelectedAdjusted ? adjustedSelectedTotal : suggestion.total_net

            return (
              <div
                key={suggestion.artikel_id}
                className={`suggestion-card ${isSelected ? 'selected' : ''} ${suggestion.is_manual ? 'manual' : ''} ${suggestion.is_override ? 'override' : ''}`}
              >
                <div className="suggestion-body" onClick={() => {
                  if (!isSelected) onSelectArticle(activePosition.id, suggestion.artikel_id)
                }}>
                  <div className="suggestion-header">
                    <div className="suggestion-title-group">
                      {suggestion.is_manual && <span className="manual-badge">Manuell gewählt</span>}
                      {suggestion.is_override && <span className="override-badge">Häufig gewählt von Kollegen</span>}
                      {isBest && <span className="best-badge">Bester Treffer</span>}
                      <strong className="suggestion-name">{suggestion.artikelname}</strong>
                    </div>
                    <div className="suggestion-header-actions">
                      {!suggestion.is_manual && !suggestion.is_override && suggestion.score_breakdown.length > 0 && (
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
                                <span className={`breakdown-points ${b.points > 0 ? 'positive' : b.points < 0 ? 'negative' : 'zero'}`}>
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
                  </div>

                  <div className="param-badges">
                    {suggestion.dn != null && (() => {
                      const text = `${activePosition?.description ?? ''} ${activePosition?.raw_text ?? ''}`
                      const dnMatch = text.match(/DN\s*(\d+)/i)
                      const reqDn = activePosition?.parameters.nominal_diameter_dn ?? (dnMatch ? parseInt(dnMatch[1], 10) : null)
                      return <ParamBadge
                        label={`DN ${suggestion.dn}`}
                        status={reqDn == null ? 'neutral' : reqDn === suggestion.dn ? 'match' : 'mismatch'}
                      />
                    })()}
                    {suggestion.sn != null && (() => {
                      const reqSn = activePosition?.parameters.stiffness_class_sn
                        ?? extractSnFromText(activePosition?.description ?? '')
                        ?? extractSnFromText(activePosition?.raw_text ?? '')
                      return <ParamBadge
                        label={`SN${suggestion.sn}`}
                        status={reqSn == null ? 'neutral' : suggestion.sn! >= reqSn ? 'match' : 'mismatch'}
                      />
                    })()}
                    {showLoadClass && suggestion.load_class && <ParamBadge
                      label={suggestion.load_class}
                      status={!activePosition?.parameters.load_class ? 'neutral' : activePosition.parameters.load_class.toUpperCase() === suggestion.load_class.toUpperCase() ? 'match' : 'mismatch'}
                    />}
                    {shouldShowNormBadge(activePosition, suggestion) && suggestion.norm && (
                      <span className={`param-badge param-${!activePosition?.parameters.norm ? 'neutral' : suggestion.norm.toLowerCase().includes(activePosition.parameters.norm.toLowerCase()) ? 'match' : 'mismatch'}`}
                        style={{
                          ...PARAM_STYLES[!activePosition?.parameters.norm ? 'neutral' : suggestion.norm.toLowerCase().includes(activePosition.parameters.norm.toLowerCase()) ? 'match' : 'mismatch'],
                          padding: '1px 7px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600,
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
                    {isSelectedAdjusted && (
                      <div className="suggestion-price-row suggestion-price-row-vk">
                        <div className="price-group">
                          <span className="price-main">{formatMoney(displayUnitPrice, suggestion.currency)}</span>
                          <span className="price-label">VK / Einheit</span>
                        </div>
                        <div className="price-group">
                          <span className="price-total">{formatMoney(displayTotal, suggestion.currency)}</span>
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
                      {filteredWarnings.map((warning) => (
                        <span key={warning} className="warning-chip">{warning}</span>
                      ))}
                    </div>
                  )}

                  {filteredReasons.length > 0 && (
                    <details className="reason-details" onClick={e => e.stopPropagation()}>
                      <summary className="reason-details-summary">Matching-Details</summary>
                      <div className="reason-chips">
                        {filteredReasons.map((reason) => {
                          const isNegative = reason.includes('abweichend') || reason.includes('weicht ab') || reason.includes('unter ') || reason.includes('≠')
                          return (
                            <span key={reason} className={`reason-chip ${isNegative ? 'reason-negative' : ''}`}>{reason}</span>
                          )
                        })}
                      </div>
                    </details>
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

      {activePosition && (
        <>
          <ProductSearchModal
            isOpen={searchOpen}
            onClose={() => setSearchOpen(false)}
            onSelect={(product) => onManualSelect(activePosition.id, product)}
            initialCategory={activePosition.parameters.product_category}
            initialDn={activePosition.parameters.nominal_diameter_dn}
          />
          <InquiryModal
            isOpen={inquiryOpen}
            onClose={() => setInquiryOpen(false)}
            position={activePosition}
            projectId={projectId}
            projectName={projectName}
          />
        </>
      )}
    </aside>
  )
}
