import { useEffect, useState } from 'react'
import type { BundledEmailPreview, SupplierInquiry } from '../types'
import { previewBundledInquiries, sendBatchInquiries } from '../api'

type Props = {
  projectId: number
  pendingInquiries?: SupplierInquiry[]
  onBack: () => void
  onSent: (result: { sent: number; failed: number }) => void
}

function buildFallbackBundledPreviews(inquiries: SupplierInquiry[]): BundledEmailPreview[] {
  const grouped = new Map<number, SupplierInquiry[]>()
  for (const inquiry of inquiries) {
    const existing = grouped.get(inquiry.supplier_id) ?? []
    existing.push(inquiry)
    grouped.set(inquiry.supplier_id, existing)
  }

  return Array.from(grouped.entries()).map(([supplierId, supplierInquiries]) => {
    const first = supplierInquiries[0]
    const positions = supplierInquiries.map((inquiry) => ({
      ordnungszahl: inquiry.ordnungszahl,
      product_description: inquiry.product_description,
      quantity: inquiry.quantity,
      unit: inquiry.unit,
    }))
    const subject = supplierInquiries.length === 1 && first.email_subject
      ? first.email_subject
      : `Anfrage zu ${positions.length} Position${positions.length !== 1 ? 'en' : ''}`
    const body = supplierInquiries.length === 1 && first.email_body
      ? first.email_body
      : [
          'Guten Tag,',
          '',
          'bitte senden Sie uns ein Angebot zu den folgenden Positionen:',
          '',
          ...positions.map((position) => {
            const qty = position.quantity != null ? `, ${position.quantity} ${position.unit ?? ''}`.trim() : ''
            return `- ${position.ordnungszahl ? `OZ ${position.ordnungszahl}: ` : ''}${position.product_description}${qty ? ` ${qty}` : ''}`
          }),
          '',
          'Vielen Dank.',
        ].join('\n')

    return {
      supplier_id: supplierId,
      supplier_name: first.supplier_name,
      supplier_email: first.supplier_email,
      subject,
      body,
      inquiry_ids: supplierInquiries.map((inquiry) => inquiry.id),
      positions,
    }
  })
}

export function InquiryReviewScreen({ projectId, pendingInquiries = [], onBack, onSent }: Props) {
  const [previews, setPreviews] = useState<BundledEmailPreview[]>([])
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [expandedSupplier, setExpandedSupplier] = useState<number | null>(null)
  const [edits, setEdits] = useState<Record<number, { subject: string; body: string }>>({})

  useEffect(() => {
    setLoading(true)
    previewBundledInquiries(projectId)
      .then(data => {
        const nextPreviews = data.length > 0 ? data : buildFallbackBundledPreviews(pendingInquiries)
        setPreviews(nextPreviews)
        // Auto-expand the first supplier
        if (nextPreviews.length === 1) {
          setExpandedSupplier(nextPreviews[0].supplier_id)
        }
      })
      .catch(() => {
        const fallbackPreviews = buildFallbackBundledPreviews(pendingInquiries)
        setPreviews(fallbackPreviews)
        if (fallbackPreviews.length === 1) {
          setExpandedSupplier(fallbackPreviews[0].supplier_id)
        }
      })
      .finally(() => setLoading(false))
  }, [projectId, pendingInquiries])

  const getSubject = (preview: BundledEmailPreview) =>
    edits[preview.supplier_id]?.subject ?? preview.subject

  const getBody = (preview: BundledEmailPreview) =>
    edits[preview.supplier_id]?.body ?? preview.body

  const setEdit = (supplierId: number, field: 'subject' | 'body', value: string) => {
    setEdits(prev => {
      const existing = prev[supplierId]
      const preview = previews.find(p => p.supplier_id === supplierId)
      if (!preview) return prev
      return {
        ...prev,
        [supplierId]: {
          subject: existing?.subject ?? preview.subject,
          body: existing?.body ?? preview.body,
          [field]: value,
        },
      }
    })
  }

  const handleSend = async () => {
    setSending(true)
    try {
      // Only send overrides for actually edited suppliers
      const overrides: Record<number, { subject: string; body: string }> = {}
      for (const [idStr, edit] of Object.entries(edits)) {
        overrides[parseInt(idStr, 10)] = edit
      }
      const result = await sendBatchInquiries(projectId, overrides, false)
      onSent({ sent: result.sent_count, failed: result.failed_count })
    } catch {
      const totalInquiries = previews.reduce((sum, p) => sum + p.inquiry_ids.length, 0)
      onSent({ sent: 0, failed: totalInquiries })
    } finally {
      setSending(false)
    }
  }

  const supplierCount = previews.length
  const totalPositions = previews.reduce((sum, p) => sum + p.positions.length, 0)

  if (loading) {
    return (
      <div className="inquiry-review-screen">
        <div className="inquiry-review-loading">E-Mail-Vorschauen werden generiert...</div>
      </div>
    )
  }

  if (previews.length === 0) {
    return (
      <div className="inquiry-review-screen">
        <div className="inquiry-review-empty">
          <p>Keine offenen Anfragen vorhanden.</p>
          <button className="btn btn-ghost" onClick={onBack}>Zurück</button>
        </div>
      </div>
    )
  }

  return (
    <div className="inquiry-review-screen">
      <div className="inquiry-review-header">
        <button className="btn btn-ghost" onClick={onBack}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Zurück
        </button>
        <h2>Lieferantenanfragen prüfen</h2>
        <p className="inquiry-review-subtitle">
          {totalPositions} Position{totalPositions !== 1 ? 'en' : ''} an {supplierCount} Lieferant{supplierCount !== 1 ? 'en' : ''}
          {' '}— <strong>{supplierCount} gebündelte E-Mail{supplierCount !== 1 ? 's' : ''}</strong>
        </p>
      </div>

      <div className="inquiry-review-list">
        {previews.map(preview => {
          const isExpanded = expandedSupplier === preview.supplier_id

          return (
            <div key={preview.supplier_id} className="inquiry-supplier-section">
              <button
                className="inquiry-supplier-header"
                onClick={() => setExpandedSupplier(isExpanded ? null : preview.supplier_id)}
              >
                <div className="inquiry-supplier-info">
                  <strong>{preview.supplier_name}</strong>
                  <span className="inquiry-supplier-email">{preview.supplier_email}</span>
                </div>
                <div className="inquiry-supplier-meta">
                  <span className="inquiry-count-badge">
                    {preview.positions.length} Position{preview.positions.length !== 1 ? 'en' : ''}
                  </span>
                  <span className="inquiry-mail-badge">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M22 6l-10 7L2 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    1 E-Mail
                  </span>
                  {edits[preview.supplier_id] && (
                    <span className="inquiry-edited-badge">bearbeitet</span>
                  )}
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className={`expand-icon ${isExpanded ? 'expanded' : ''}`}>
                    <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              </button>

              {isExpanded && (
                <div className="inquiry-supplier-details">
                  {/* Position list */}
                  <div className="inquiry-positions-summary">
                    <span className="inquiry-positions-label">Enthaltene Positionen:</span>
                    {preview.positions.map((pos, i) => (
                      <div key={i} className="inquiry-position-row">
                        <span className="inquiry-position-oz">OZ {pos.ordnungszahl ?? '—'}</span>
                        <span className="inquiry-position-desc">{pos.product_description}</span>
                        {pos.quantity != null && (
                          <span className="inquiry-position-qty">
                            {pos.quantity} {pos.unit ?? ''}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Editable email */}
                  <div className="inquiry-email-preview">
                    <div className="inquiry-field">
                      <label>E-Mail-Betreff</label>
                      <input
                        type="text"
                        className="inquiry-input"
                        value={getSubject(preview)}
                        onChange={e => setEdit(preview.supplier_id, 'subject', e.target.value)}
                      />
                    </div>
                    <div className="inquiry-field">
                      <label>E-Mail-Text</label>
                      <textarea
                        className="inquiry-textarea"
                        value={getBody(preview)}
                        onChange={e => setEdit(preview.supplier_id, 'body', e.target.value)}
                        rows={Math.max(8, getBody(preview).split('\n').length + 2)}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="inquiry-review-actions">
        <button className="btn btn-ghost" onClick={onBack}>
          Abbrechen
        </button>
        <button
          className="btn btn-primary"
          onClick={() => { void handleSend() }}
          disabled={sending}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {sending ? 'Sende...' : `${supplierCount} E-Mail${supplierCount !== 1 ? 's' : ''} senden`}
        </button>
      </div>
    </div>
  )
}
