import { useMemo, useState } from 'react'
import { createSupplierOffer, syncDemoInbox, updateInquiryStatus } from '../api'
import { InquiryReviewScreen } from './InquiryReviewScreen'
import type { InboxSyncResult, LVPosition, SupplierInquiry } from '../types'

type Props = {
  inquiries: SupplierInquiry[]
  positions: LVPosition[]
  projectId?: number | null
  onRefreshInquiries?: (projectId?: number | null) => Promise<void> | void
  onEditPosition?: (positionId: string) => void
}

function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

const STATUS_LABELS: Record<string, string> = {
  offen: 'Vorgemerkt',
  angefragt: 'Angefragt',
  angebot_erhalten: 'Angebot erhalten',
}

export function InquiryPanel({ inquiries, positions, projectId, onRefreshInquiries, onEditPosition }: Props) {
  const [showReview, setShowReview] = useState(false)
  const [sendResult, setSendResult] = useState<{ sent: number; failed: number } | null>(null)
  const [editingInquiry, setEditingInquiry] = useState<SupplierInquiry | null>(null)
  const [offerProductDescription, setOfferProductDescription] = useState('')
  const [offerUnitPrice, setOfferUnitPrice] = useState('')
  const [offerDeliveryDays, setOfferDeliveryDays] = useState('')
  const [offerNote, setOfferNote] = useState('')
  const [isSavingOffer, setIsSavingOffer] = useState(false)
  const [offerSaveError, setOfferSaveError] = useState<string | null>(null)
  const [isSyncingInbox, setIsSyncingInbox] = useState(false)
  const [inboxSyncResult, setInboxSyncResult] = useState<InboxSyncResult | null>(null)

  const positionMap = useMemo(() => {
    const map: Record<string, LVPosition> = {}
    for (const p of positions) map[p.id] = p
    return map
  }, [positions])

  // Group by supplier
  const groupedBySupplier = useMemo(() => {
    const map: Record<number, { supplier_name: string; supplier_email: string; items: SupplierInquiry[] }> = {}
    for (const inq of inquiries) {
      if (!map[inq.supplier_id]) {
        map[inq.supplier_id] = { supplier_name: inq.supplier_name, supplier_email: inq.supplier_email, items: [] }
      }
      map[inq.supplier_id].items.push(inq)
    }
    return Object.values(map)
  }, [inquiries])

  const openCount = inquiries.filter(i => i.status === 'offen').length
  const sentCount = inquiries.filter(i => i.status === 'angefragt').length
  const receivedCount = inquiries.filter(i => i.status === 'angebot_erhalten').length
  const pendingInquiries = inquiries.filter((inq) => inq.status === 'offen')

  const openOfferCapture = (inquiry: SupplierInquiry) => {
    setEditingInquiry(inquiry)
    setOfferProductDescription(inquiry.product_description)
    setOfferUnitPrice('')
    setOfferDeliveryDays('')
    setOfferNote(inquiry.notes ?? '')
    setOfferSaveError(null)
  }

  const closeOfferCapture = () => {
    if (isSavingOffer) return
    setEditingInquiry(null)
    setOfferProductDescription('')
    setOfferUnitPrice('')
    setOfferDeliveryDays('')
    setOfferNote('')
    setOfferSaveError(null)
  }

  const handleSyncInbox = async () => {
    setIsSyncingInbox(true)
    try {
      const result = await syncDemoInbox(30)
      setInboxSyncResult(result)
      await onRefreshInquiries?.(projectId)
    } catch (error) {
      setInboxSyncResult({
        status: 'error',
        detail: error instanceof Error ? error.message : 'Inbox-Sync fehlgeschlagen',
      })
    } finally {
      setIsSyncingInbox(false)
    }
  }

  const handleSaveOfferCapture = async () => {
    if (!editingInquiry) return
    setIsSavingOffer(true)
    setOfferSaveError(null)
    try {
      const articleName = offerProductDescription.trim() || editingInquiry.product_description
      const parsedPrice = offerUnitPrice.trim() ? parseFloat(offerUnitPrice.trim().replace(',', '.')) : undefined
      const parsedDays = offerDeliveryDays.trim() ? parseInt(offerDeliveryDays.trim(), 10) : undefined

      // Create structured SupplierOffer
      await createSupplierOffer({
        inquiry_id: editingInquiry.id,
        supplier_id: editingInquiry.supplier_id,
        project_id: editingInquiry.project_id,
        position_id: editingInquiry.position_id,
        ordnungszahl: editingInquiry.ordnungszahl,
        article_name: articleName,
        unit_price: parsedPrice && !isNaN(parsedPrice) ? parsedPrice : undefined,
        delivery_days: parsedDays && !isNaN(parsedDays) ? parsedDays : undefined,
        quantity: editingInquiry.quantity,
        unit: editingInquiry.unit,
        notes: offerNote.trim() || undefined,
        source: 'manual',
      })

      // Inquiry status is updated automatically by the backend (inquiry_id linked)
      await onRefreshInquiries?.(projectId)
      closeOfferCapture()
    } catch (error) {
      setOfferSaveError(error instanceof Error ? error.message : 'Angebot konnte nicht gespeichert werden.')
    } finally {
      setIsSavingOffer(false)
    }
  }

  if (showReview && projectId) {
    return (
      <section className="panel inquiry-panel">
        <div className="panel-header">
          <div className="panel-number">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" stroke="currentColor" strokeWidth="1.5" />
              <polyline points="22,6 12,13 2,6" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </div>
          <div>
            <h2>Lieferantenanfragen prüfen</h2>
            <p className="panel-copy">{pendingInquiries.length} vorgemerkt</p>
          </div>
        </div>
        <InquiryReviewScreen
          projectId={projectId}
          pendingInquiries={pendingInquiries}
          onBack={() => setShowReview(false)}
          onSent={(result) => {
            setSendResult(result)
            setShowReview(false)
            void onRefreshInquiries?.(projectId)
          }}
        />
      </section>
    )
  }

  if (inquiries.length === 0) {
    return (
      <section className="panel inquiry-panel">
        <div className="panel-header">
          <div className="panel-number">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" stroke="currentColor" strokeWidth="1.5" />
              <polyline points="22,6 12,13 2,6" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </div>
          <div>
            <h2>Lieferantenanfragen</h2>
            <p className="panel-copy">Keine offenen Anfragen für dieses Projekt.</p>
          </div>
        </div>
        <div className="inquiry-empty">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" className="empty-icon">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <polyline points="22,4 12,14.01 9,11.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p>Alle Anfragen bearbeitet</p>
        </div>
      </section>
    )
  }

  return (
    <section className="panel inquiry-panel">
      <div className="panel-header">
        <div className="panel-number">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" stroke="currentColor" strokeWidth="1.5" />
            <polyline points="22,6 12,13 2,6" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </div>
        <div>
          <h2>Lieferantenanfragen</h2>
          <p className="panel-copy">{inquiries.length} Anfragen an {groupedBySupplier.length} Lieferanten</p>
        </div>
      </div>

      <div className="inquiry-stats">
        {openCount > 0 && <span className="inquiry-stat inquiry-stat--offen">{openCount} vorgemerkt</span>}
        {sentCount > 0 && <span className="inquiry-stat inquiry-stat--angefragt">{sentCount} angefragt</span>}
        {receivedCount > 0 && <span className="inquiry-stat inquiry-stat--erhalten">{receivedCount} Angebot erhalten</span>}
      </div>

      {sendResult && (
        <div className="inquiry-panel-result">
          {sendResult.sent} gesendet{sendResult.failed > 0 ? `, ${sendResult.failed} fehlgeschlagen` : ''}
        </div>
      )}
      {inboxSyncResult && (
        <div className="inquiry-panel-result">
          {inboxSyncResult.status === 'ok'
            ? `Postfach aktualisiert: ${inboxSyncResult.offers_matched ?? 0} Angebot(e) zugeordnet, ${inboxSyncResult.new_lv_created ?? 0} neues LV`
            : `Postfach-Update: ${inboxSyncResult.detail ?? inboxSyncResult.status}`}
        </div>
      )}

      <div className="inquiry-list">
        {groupedBySupplier.map((group) => (
          <div key={group.supplier_name} className="inquiry-supplier-group">
            <div className="inquiry-supplier-header">
              <span className="inquiry-supplier-name">{group.supplier_name}</span>
              <span className="inquiry-supplier-email">{group.supplier_email}</span>
            </div>
            {group.items.map((inq) => {
              const pos = inq.position_id ? positionMap[inq.position_id] : null
              return (
                <div key={inq.id} className="inquiry-item">
                  <div className="inquiry-item-head">
                    {pos && <span className="inquiry-item-oz">{pos.ordnungszahl}</span>}
                    <span className={`inquiry-item-status inquiry-item-status--${inq.status}`}>
                      {STATUS_LABELS[inq.status] ?? inq.status}
                    </span>
                    {inq.sent_at && <span className="inquiry-item-date">{formatDate(inq.sent_at)}</span>}
                  </div>
                  <p className="inquiry-item-desc">{inq.product_description}</p>
                  {inq.quantity != null && (
                    <span className="inquiry-item-qty">
                      Menge: {inq.quantity} {inq.unit ?? ''}
                    </span>
                  )}
                  <div className="inquiry-item-actions">
                    {inq.status === 'angefragt' && (
                      <button
                        type="button"
                        className="inquiry-item-capture"
                        onClick={() => openOfferCapture(inq)}
                      >
                        Angebot erfassen
                      </button>
                    )}
                    {pos && onEditPosition && (
                      <button
                        type="button"
                        className="inquiry-item-edit"
                        onClick={() => onEditPosition(pos.id)}
                      >
                        Zur Position
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {projectId && inquiries.length > 0 && (
        <div className="inquiry-panel-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => { void handleSyncInbox() }}
            disabled={isSyncingInbox}
          >
            {isSyncingInbox ? 'Postfach wird geprüft…' : 'Antworten aus Postfach laden'}
          </button>
          {pendingInquiries.length > 0 && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setShowReview(true)}
            >
              Anfragen prüfen & senden ({pendingInquiries.length})
            </button>
          )}
        </div>
      )}

      {editingInquiry && (
        <div className="modal-backdrop" onClick={closeOfferCapture}>
          <div className="modal-box inquiry-offer-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>Angebot erfassen</h3>
              <button className="modal-close" onClick={closeOfferCapture}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <div className="inquiry-offer-body">
              <div className="inquiry-field">
                <label>Lieferant</label>
                <div className="inquiry-offer-readonly">{editingInquiry.supplier_name}</div>
              </div>
              <div className="inquiry-field">
                <label>Position</label>
                <div className="inquiry-offer-readonly">{editingInquiry.ordnungszahl ?? '—'}</div>
              </div>
              <div className="inquiry-field">
                <label>Produktbeschreibung</label>
                <textarea
                  className="inquiry-textarea"
                  value={offerProductDescription}
                  onChange={(event) => setOfferProductDescription(event.target.value)}
                  rows={3}
                />
              </div>
              <div className="inquiry-offer-row">
                <div className="inquiry-field">
                  <label>Preis (netto)</label>
                  <input
                    type="text"
                    className="inquiry-input"
                    value={offerUnitPrice}
                    onChange={(event) => setOfferUnitPrice(event.target.value)}
                    placeholder="z.B. 128,50"
                  />
                </div>
                <div className="inquiry-field">
                  <label>Lieferzeit (Tage)</label>
                  <input
                    type="text"
                    className="inquiry-input"
                    value={offerDeliveryDays}
                    onChange={(event) => setOfferDeliveryDays(event.target.value)}
                    placeholder="z.B. 7"
                  />
                </div>
              </div>
              <div className="inquiry-field">
                <label>Notiz</label>
                <textarea
                  className="inquiry-textarea"
                  value={offerNote}
                  onChange={(event) => setOfferNote(event.target.value)}
                  rows={4}
                  placeholder="Zusätzliche Infos aus der Lieferantenmail…"
                />
              </div>
              {offerSaveError && <div className="inquiry-error">{offerSaveError}</div>}
            </div>
            <div className="inquiry-offer-actions">
              <button className="btn btn-ghost" onClick={closeOfferCapture} disabled={isSavingOffer}>
                Abbrechen
              </button>
              {editingInquiry.position_id && onEditPosition && (
                <button
                  className="btn btn-ghost"
                  onClick={() => {
                    onEditPosition(editingInquiry.position_id as string)
                    closeOfferCapture()
                  }}
                  disabled={isSavingOffer}
                >
                  Zur Position
                </button>
              )}
              <button
                className="btn btn-primary"
                onClick={() => { void handleSaveOfferCapture() }}
                disabled={isSavingOffer}
              >
                {isSavingOffer ? 'Speichere…' : 'Als Angebot erhalten speichern'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
