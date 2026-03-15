import type { ExportPreviewResponse } from '../types'

type Props = {
  isOpen: boolean
  preview: ExportPreviewResponse | null
  onConfirm: () => void
  onCancel: () => void
  isExporting: boolean
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(value)
}

export function ExportConfirmDialog({ isOpen, preview, onConfirm, onCancel, isExporting }: Props) {
  if (!isOpen || !preview) return null

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <div className="dialog-box" onClick={(e) => e.stopPropagation()}>
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
        </div>

        <div className="dialog-actions">
          <button className="btn btn-ghost" onClick={onCancel} disabled={isExporting}>
            Abbrechen
          </button>
          <button className="btn btn-primary" onClick={onConfirm} disabled={isExporting}>
            {isExporting ? 'Exportiere…' : 'PDF herunterladen'}
          </button>
        </div>
      </div>
    </div>
  )
}
