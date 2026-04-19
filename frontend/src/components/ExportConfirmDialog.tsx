import { useEffect, useState } from 'react'
import type { ExportPreviewResponse } from '../types'

type Props = {
  isOpen: boolean
  preview: ExportPreviewResponse | null
  onDownload: () => void
  onSendEmail: (payload: { customerEmail: string; subject: string; body: string }) => Promise<void> | void
  onPreviewPdf: () => Promise<void> | void
  onCancel: () => void
  isExporting: boolean
  isSending: boolean
  isPreviewingPdf: boolean
  sendResultMessage: string | null
  sendResultKind: 'success' | 'error' | null
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(value)
}

export function ExportConfirmDialog({
  isOpen,
  preview,
  onDownload,
  onSendEmail,
  onPreviewPdf,
  onCancel,
  isExporting,
  isSending,
  isPreviewingPdf,
  sendResultMessage,
  sendResultKind,
}: Props) {
  const [customerEmail, setCustomerEmail] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')

  useEffect(() => {
    if (!isOpen || !preview) return
    const defaults = preview.email_defaults
    setCustomerEmail(defaults?.customer_email ?? '')
    setSubject(defaults?.subject ?? '')
    setBody(defaults?.body ?? '')
  }, [isOpen, preview])

  if (!isOpen || !preview) return null

  const busy = isExporting || isSending || isPreviewingPdf
  const emailValid = /.+@.+\..+/.test(customerEmail.trim())
  const canSend = emailValid && subject.trim().length > 0 && body.trim().length > 0 && !busy

  return (
    <div className="dialog-backdrop" onClick={busy ? undefined : onCancel}>
      <div className="dialog-box dialog-box--wide" onClick={(e) => e.stopPropagation()}>
        <h3 className="dialog-title">Angebot exportieren</h3>

        <div className="dialog-summary">
          <div className="dialog-stat">
            <span className="dialog-stat-value">{preview.included_count}</span>
            <span className="dialog-stat-label">von {preview.total_count} Positionen</span>
          </div>
          <div className="dialog-stat">
            <span className="dialog-stat-value">{formatMoney(preview.total_net)}</span>
            <span className="dialog-stat-label">Netto-Gesamtwert</span>
          </div>
          <button
            className="btn btn-ghost dialog-preview-btn"
            onClick={() => void onPreviewPdf()}
            disabled={busy}
            type="button"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
            </svg>
            {isPreviewingPdf ? 'Öffne…' : 'Angebots-PDF ansehen'}
          </button>
        </div>

        <div className="dialog-email-form">
          <label className="dialog-field">
            <span>Empfänger (E-Mail)</span>
            <input
              type="email"
              value={customerEmail}
              onChange={(e) => setCustomerEmail(e.target.value)}
              placeholder="kunde@example.com"
              disabled={busy}
            />
          </label>
          <label className="dialog-field">
            <span>Betreff</span>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="dialog-field">
            <span>Nachricht</span>
            <textarea
              rows={10}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              disabled={busy}
            />
          </label>
          <p className="dialog-info">
            Das generierte Angebots-PDF wird automatisch als Anhang mitgesendet.
          </p>
        </div>

        {sendResultMessage && (
          <p
            className={
              sendResultKind === 'error'
                ? 'dialog-feedback dialog-feedback--error'
                : 'dialog-feedback dialog-feedback--success'
            }
            role="status"
          >
            {sendResultMessage}
          </p>
        )}

        <div className="dialog-actions">
          <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Abbrechen
          </button>
          <button className="btn btn-secondary" onClick={onDownload} disabled={busy}>
            {isExporting ? 'Exportiere…' : 'PDF herunterladen'}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => onSendEmail({ customerEmail: customerEmail.trim(), subject: subject.trim(), body })}
            disabled={!canSend}
          >
            {isSending ? 'Sende…' : 'Per E-Mail senden'}
          </button>
        </div>
      </div>
    </div>
  )
}
