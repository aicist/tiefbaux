import { useEffect, useState } from 'react'
import { fetchInquiries, getProjectOfferPdfUrl } from '../api'
import type { LVPosition, ProductSuggestion, ProjectMetadata, SupplierInquiry } from '../types'

type AssignmentDecision = 'accepted' | 'rejected' | 'inquiry_pending'

type Props = {
  metadata: ProjectMetadata | null
  projectId: number
  projectName: string
  projectStatus?: string | null
  offerPdfPath?: string | null
  positions: LVPosition[]
  onBack: () => void
  lastEditorName?: string | null
  lastEditedAt?: string | null
  assignedUserName?: string | null
  suggestionMap?: Record<string, ProductSuggestion[]>
  selectedArticleIds?: Record<string, string[]>
  decisions?: Record<string, AssignmentDecision>
  componentSelections?: Record<string, string>
  onStartAssignment?: () => void
  onEditPosition?: (positionId: string) => void
  onFinish?: () => void
}

function statusLabel(status?: string | null): string {
  if (status === 'gerechnet') return 'Gerechnet'
  if (status === 'anfrage_offen') return 'Anfrage offen'
  if (status === 'offen') return 'Offen'
  return 'Neu'
}

function formatMoney(value?: number | null): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(value)
}

export function ProjectOverview({
  metadata,
  projectId,
  projectName,
  projectStatus,
  offerPdfPath,
  positions,
  onBack,
  lastEditorName,
  lastEditedAt,
  assignedUserName,
  suggestionMap = {},
  selectedArticleIds = {},
  decisions = {},
  componentSelections = {},
  onStartAssignment,
  onEditPosition,
  onFinish,
}: Props) {
  const [inquiries, setInquiries] = useState<SupplierInquiry[]>([])

  useEffect(() => {
    fetchInquiries(projectId).then(setInquiries).catch(() => {})
  }, [projectId])

  const openInquiries = inquiries.filter((i) => i.status === 'offen')
  const sentInquiries = inquiries.filter((i) => i.status !== 'offen')
  const inquiriesByPosition = inquiries.reduce<Record<string, SupplierInquiry[]>>((acc, inquiry) => {
    if (!inquiry.position_id) return acc
    ;(acc[inquiry.position_id] ??= []).push(inquiry)
    return acc
  }, {})
  const offerPdfUrl = offerPdfPath ? getProjectOfferPdfUrl(projectId) : null
  const isInquiryPending = projectStatus === 'anfrage_offen'
  const isGerechnet = projectStatus === 'gerechnet'

  const materialPositions = positions.filter(p => p.position_type !== 'dienstleistung')
  const serviceCount = positions.length - materialPositions.length

  // Compute component selection counts
  const componentSelectionCounts: Record<string, number> = {}
  Object.keys(componentSelections).forEach(key => {
    const [posId] = key.split('::')
    componentSelectionCounts[posId] = (componentSelectionCounts[posId] ?? 0) + 1
  })
  const hasAssignment = (posId: string) =>
    (selectedArticleIds[posId]?.length ?? 0) > 0 || (componentSelectionCounts[posId] ?? 0) > 0

  const acceptedCount = Object.values(decisions).filter(d => d === 'accepted').length
  const rejectedCount = Object.values(decisions).filter(d => d === 'rejected').length
  const assignedCount = materialPositions.filter(p => hasAssignment(p.id)).length
  const openCount = materialPositions.filter(p => !hasAssignment(p.id) && !decisions[p.id]).length

  return (
    <div className="project-overview">
      <div className="project-overview-topbar">
        <button className="btn btn-ghost" onClick={onBack}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Zurück zum Archiv
        </button>
        <span className={`archive-status archive-status-${projectStatus ?? 'neu'}`}>{statusLabel(projectStatus)}</span>
        <div className="po-topbar-spacer" />
        {!isGerechnet && onStartAssignment && (
          <button className="btn btn-primary btn-sm" onClick={onStartAssignment}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Zuordnung starten
          </button>
        )}
        {!isGerechnet && onFinish && (
          <button className="btn btn-primary btn-sm" onClick={onFinish}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Angebot exportieren
          </button>
        )}
      </div>

      <div className="project-overview-columns">
        {/* Left column: Project data + stats */}
        <div className="project-overview-left">
          <div className="po-section">
            <h3 className="po-section-title">Projektdaten</h3>
            <div className="po-data-list">
              <div className="po-data-item">
                <span className="po-data-label">Bauvorhaben</span>
                <span className="po-data-value">{metadata?.bauvorhaben ?? projectName ?? '—'}</span>
              </div>
              {metadata?.objekt_nr && (
                <div className="po-data-item">
                  <span className="po-data-label">Objekt-Nr.</span>
                  <span className="po-data-value">{metadata.objekt_nr}</span>
                </div>
              )}
              {metadata?.auftraggeber && (
                <div className="po-data-item">
                  <span className="po-data-label">Auftraggeber</span>
                  <span className="po-data-value">{metadata.auftraggeber}</span>
                </div>
              )}
              {metadata?.submission_date && (
                <div className="po-data-item">
                  <span className="po-data-label">Abgabetermin</span>
                  <span className="po-data-value">{metadata.submission_date}</span>
                </div>
              )}
            </div>
          </div>

          {metadata?.kunde_name && (
            <div className="po-section">
              <h3 className="po-section-title">Kundendaten</h3>
              <div className="po-data-list">
                <div className="po-data-item">
                  <span className="po-data-label">Kunde</span>
                  <span className="po-data-value">{metadata.kunde_name}</span>
                </div>
                {metadata.kunde_adresse && (
                  <div className="po-data-item">
                    <span className="po-data-label">Adresse</span>
                    <span className="po-data-value">{metadata.kunde_adresse}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="po-section">
            <h3 className="po-section-title">Bearbeitung</h3>
            <div className="po-data-list">
              {assignedUserName && (
                <div className="po-data-item">
                  <span className="po-data-label">Zugewiesen</span>
                  <span className="po-data-value">{assignedUserName}</span>
                </div>
              )}
              {lastEditorName && (
                <div className="po-data-item">
                  <span className="po-data-label">Zuletzt bearbeitet</span>
                  <span className="po-data-value">
                    {lastEditorName}
                    {lastEditedAt && (
                      <span className="po-data-date">
                        {new Date(lastEditedAt).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })}
                      </span>
                    )}
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="po-section">
            <h3 className="po-section-title">Fortschritt</h3>
            <div className="po-stats-grid">
              <div className="po-stat">
                <span className="po-stat-number">{materialPositions.length}</span>
                <span className="po-stat-label">Positionen</span>
              </div>
              <div className="po-stat">
                <span className="po-stat-number po-stat-accent">{assignedCount}</span>
                <span className="po-stat-label">Zugeordnet</span>
              </div>
              {acceptedCount > 0 && (
                <div className="po-stat">
                  <span className="po-stat-number po-stat-accent">{acceptedCount}</span>
                  <span className="po-stat-label">Bestätigt</span>
                </div>
              )}
              {rejectedCount > 0 && (
                <div className="po-stat">
                  <span className="po-stat-number po-stat-danger">{rejectedCount}</span>
                  <span className="po-stat-label">Abgelehnt</span>
                </div>
              )}
              {openCount > 0 && (
                <div className="po-stat">
                  <span className="po-stat-number">{openCount}</span>
                  <span className="po-stat-label">Offen</span>
                </div>
              )}
              {serviceCount > 0 && (
                <div className="po-stat">
                  <span className="po-stat-number">{serviceCount}</span>
                  <span className="po-stat-label">DL</span>
                </div>
              )}
            </div>
          </div>

          {/* Inquiries in left column for non-gerechnet */}
          {!isGerechnet && inquiries.length > 0 && (
            <div className="po-section">
              <h3 className="po-section-title">
                Anfragen
                <span className="po-inquiry-count">{inquiries.length}</span>
              </h3>
              <div className="po-inquiry-list">
                {openInquiries.map((inq) => (
                  <div key={inq.id} className="po-inquiry-card po-inquiry-open">
                    <div className="po-inquiry-supplier">{inq.supplier_name}</div>
                    <div className="po-inquiry-product">{inq.product_description}</div>
                  </div>
                ))}
                {sentInquiries.map((inq) => (
                  <div key={inq.id} className={`po-inquiry-card po-inquiry-${inq.status}`}>
                    <div className="po-inquiry-supplier">{inq.supplier_name}</div>
                    <div className="po-inquiry-status-badge">
                      {inq.status === 'angefragt' ? 'Angefragt' : 'Angebot erhalten'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Center/Right: Position table (non-gerechnet) or PDF + inquiries (gerechnet) */}
        {isGerechnet ? (
          <>
            <div className="project-overview-center">
              <div className="po-pdf-header">
                <h3 className="po-section-title">Angebot</h3>
              </div>
              {isInquiryPending ? (
                <div className="po-section po-no-inquiries">
                  <p>Angebot gesperrt: offene Lieferantenanfragen.</p>
                </div>
              ) : offerPdfUrl ? (
                <iframe src={offerPdfUrl} className="po-pdf-viewer" title="Angebot PDF" />
              ) : (
                <div className="po-section po-no-inquiries">
                  <p>Noch kein Angebot vorhanden.</p>
                </div>
              )}
            </div>

            <div className="project-overview-right">
              {openInquiries.length > 0 && (
                <div className="po-section">
                  <h3 className="po-section-title">
                    Offene Anfragen
                    <span className="po-inquiry-count">{openInquiries.length}</span>
                  </h3>
                  <div className="po-inquiry-list">
                    {openInquiries.map((inq) => (
                      <div key={inq.id} className="po-inquiry-card po-inquiry-open">
                        <div className="po-inquiry-supplier">{inq.supplier_name}</div>
                        <div className="po-inquiry-product">{inq.product_description}</div>
                        {inq.quantity && <div className="po-inquiry-qty">{inq.quantity} {inq.unit ?? 'Stk.'}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {sentInquiries.length > 0 && (
                <div className="po-section">
                  <h3 className="po-section-title">
                    Gesendete Anfragen
                    <span className="po-inquiry-count">{sentInquiries.length}</span>
                  </h3>
                  <div className="po-inquiry-list">
                    {sentInquiries.map((inq) => (
                      <div key={inq.id} className={`po-inquiry-card po-inquiry-${inq.status}`}>
                        <div className="po-inquiry-supplier">{inq.supplier_name}</div>
                        <div className="po-inquiry-product">{inq.product_description}</div>
                        <div className="po-inquiry-status-badge">
                          {inq.status === 'angefragt' ? 'Angefragt' : 'Angebot erhalten'}
                        </div>
                        {inq.sent_at && <div className="po-inquiry-date">{new Date(inq.sent_at).toLocaleDateString('de-DE')}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {inquiries.length === 0 && (
                <div className="po-section po-no-inquiries">
                  <p>Keine Lieferantenanfragen.</p>
                </div>
              )}
            </div>
          </>
        ) : (
          /* Non-gerechnet: position overview table spanning center + right */
          <div className="project-overview-positions">
            <div className="po-section">
              <h3 className="po-section-title">Positionsübersicht</h3>
              <table className="po-positions-table">
                <thead>
                  <tr>
                    <th>OZ</th>
                    <th>Beschreibung</th>
                    <th>Status</th>
                    <th>Artikel</th>
                    <th>EP (EK)</th>
                    <th>GP (EK)</th>
                    {onEditPosition && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {materialPositions.map(pos => {
                    const artIds = selectedArticleIds[pos.id] ?? []
                    const topArtId = artIds[0]
                    const topSugg = topArtId ? (suggestionMap[pos.id] ?? []).find(s => s.artikel_id === topArtId) : null
                    const decision = decisions[pos.id]
                    const suggCount = suggestionMap[pos.id]?.length ?? 0
                    const posInquiries = inquiriesByPosition[pos.id] ?? []
                    const inquiryStatus = posInquiries.some((inquiry) => inquiry.status === 'offen')
                      ? 'offen'
                      : posInquiries.some((inquiry) => inquiry.status === 'angefragt')
                        ? 'angefragt'
                        : posInquiries.some((inquiry) => inquiry.status === 'angebot_erhalten')
                          ? 'angebot_erhalten'
                          : null

                    return (
                      <tr key={pos.id} className={decision === 'rejected' ? 'po-row-rejected' : ''}>
                        <td className="po-td-oz">{pos.ordnungszahl}</td>
                        <td className="po-td-desc">{pos.description}</td>
                        <td>
                          {decision === 'rejected' ? (
                            <span className="po-decision-pill po-pill-rejected">Abgelehnt</span>
                          ) : inquiryStatus ? (
                            <span className={`po-decision-pill ${inquiryStatus === 'angebot_erhalten' ? 'po-pill-accepted' : 'po-pill-inquiry'}`}>
                              {inquiryStatus === 'offen'
                                ? 'Anfrage offen'
                                : inquiryStatus === 'angefragt'
                                  ? 'Angefragt'
                                  : 'Angebot erhalten'}
                            </span>
                          ) : decision === 'accepted' ? (
                            <span className="po-decision-pill po-pill-accepted">Bestätigt</span>
                          ) : decision === 'inquiry_pending' ? (
                            <span className="po-decision-pill po-pill-inquiry">Anfrage</span>
                          ) : hasAssignment(pos.id) ? (
                            <span className="po-decision-pill po-pill-assigned">Zugeordnet</span>
                          ) : suggCount > 0 ? (
                            <span className="po-decision-pill po-pill-open">{suggCount} Vorschl.</span>
                          ) : (
                            <span className="po-decision-pill po-pill-none">Offen</span>
                          )}
                        </td>
                        <td className="po-td-article">
                          {decision === 'rejected' ? (
                            <span className="po-rejected-label">—</span>
                          ) : topSugg ? (
                            <span title={topSugg.artikel_id}>{topSugg.artikelname}</span>
                          ) : '—'}
                        </td>
                        <td className="po-td-price">{topSugg ? formatMoney(topSugg.price_net) : '—'}</td>
                        <td className="po-td-price">{topSugg ? formatMoney(topSugg.total_net) : '—'}</td>
                        {onEditPosition && (
                          <td className="po-td-edit">
                            <button
                              className="btn btn-ghost btn-xs po-edit-btn"
                              onClick={() => onEditPosition(pos.id)}
                              title="Position in Zuordnung bearbeiten"
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </button>
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Position summary table at bottom for gerechnet */}
      {isGerechnet && positions.length > 0 && (
        <div className="po-section po-positions-summary">
          <h3 className="po-section-title">Positionsübersicht</h3>
          <table className="po-positions-table">
            <thead>
              <tr>
                <th>OZ</th>
                <th>Beschreibung</th>
                <th>Artikel</th>
                <th>Menge</th>
                <th>EP (EK)</th>
                <th>GP (EK)</th>
              </tr>
            </thead>
            <tbody>
              {materialPositions.map(pos => {
                const artIds = selectedArticleIds[pos.id] ?? []
                const topArtId = artIds[0]
                const topSugg = topArtId ? (suggestionMap[pos.id] ?? []).find(s => s.artikel_id === topArtId) : null
                const decision = decisions[pos.id]
                return (
                  <tr key={pos.id} className={decision === 'rejected' ? 'po-row-rejected' : ''}>
                    <td className="po-td-oz">{pos.ordnungszahl}</td>
                    <td className="po-td-desc">{pos.description}</td>
                    <td className="po-td-article">
                      {decision === 'rejected' ? (
                        <span className="po-rejected-label">Ohne Zuordnung</span>
                      ) : topSugg ? (
                        <span>{topSugg.artikelname}</span>
                      ) : '—'}
                    </td>
                    <td className="po-td-qty">{pos.quantity ?? '—'} {pos.unit ?? ''}</td>
                    <td className="po-td-price">{topSugg ? formatMoney(topSugg.price_net) : '—'}</td>
                    <td className="po-td-price">{topSugg ? formatMoney(topSugg.total_net) : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
