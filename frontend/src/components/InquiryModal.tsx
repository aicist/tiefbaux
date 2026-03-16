import { useEffect, useMemo, useState } from 'react'
import { createInquiry, fetchSuppliers } from '../api'
import type { LVPosition, Supplier } from '../types'

type Props = {
  isOpen: boolean
  onClose: () => void
  position: LVPosition
  projectName?: string | null
  projectId?: number | null
  onSuccess?: () => void
}

export function InquiryModal({ isOpen, onClose, position, projectName, projectId, onSuccess }: Props) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [selectedSupplierId, setSelectedSupplierId] = useState<number | null>(null)
  const [customMessage, setCustomMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setSent(false)
      setError(null)
      setCustomMessage('')
      fetchSuppliers()
        .then((s) => {
          setSuppliers(s)
          // Auto-select supplier matching position category
          const cat = position.parameters.product_category
          if (cat) {
            const match = s.find((sup) =>
              sup.categories.some((c) => c.toLowerCase() === cat.toLowerCase()),
            )
            if (match) setSelectedSupplierId(match.id)
            else if (s.length > 0) setSelectedSupplierId(s[0].id)
          } else if (s.length > 0) {
            setSelectedSupplierId(s[0].id)
          }
        })
        .catch(() => setError('Lieferanten konnten nicht geladen werden'))
    }
  }, [isOpen, position.parameters.product_category])

  const selectedSupplier = useMemo(
    () => suppliers.find((s) => s.id === selectedSupplierId),
    [suppliers, selectedSupplierId],
  )

  // Build preview of technical params
  const paramLines = useMemo(() => {
    const lines: string[] = []
    const p = position.parameters
    if (p.nominal_diameter_dn != null) lines.push(`Nennweite: DN ${p.nominal_diameter_dn}`)
    if (p.material) lines.push(`Werkstoff: ${p.material}`)
    if (p.load_class) lines.push(`Belastungsklasse: ${p.load_class}`)
    if (p.dimensions) lines.push(`Abmessungen: ${p.dimensions}`)
    if (p.norm) lines.push(`Norm: ${p.norm}`)
    if (p.stiffness_class_sn != null) lines.push(`Steifigkeitsklasse: SN${p.stiffness_class_sn}`)
    if (p.reference_product) lines.push(`Referenzprodukt: ${p.reference_product}`)
    if (p.installation_area) lines.push(`Einbaubereich: ${p.installation_area}`)
    if (p.product_category) lines.push(`Produktkategorie: ${p.product_category}`)
    return lines
  }, [position.parameters])

  async function handleSend() {
    if (!selectedSupplierId) return
    setSending(true)
    setError(null)
    try {
      await createInquiry({
        supplier_id: selectedSupplierId,
        project_id: projectId,
        position_id: position.id,
        ordnungszahl: position.ordnungszahl,
        product_description: position.description,
        technical_params: position.parameters,
        quantity: position.quantity,
        unit: position.unit,
        custom_message: customMessage || undefined,
        send_email: true,
      })
      setSent(true)
      onSuccess?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Fehler beim Senden')
    } finally {
      setSending(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="inquiry-modal" onClick={(e) => e.stopPropagation()}>
        <div className="inquiry-modal-header">
          <h3>Lieferantenanfrage</h3>
          <button className="modal-close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {sent ? (
          <div className="inquiry-success">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="#16a34a" strokeWidth="1.5" />
              <path d="M8 12l3 3 5-5" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <h4>Anfrage gesendet</h4>
            <p>
              Die Anfrage wurde an <strong>{selectedSupplier?.name}</strong> ({selectedSupplier?.email}) gesendet.
            </p>
            <button className="btn btn-primary inquiry-btn" onClick={onClose}>
              Schließen
            </button>
          </div>
        ) : (
          <>
            <div className="inquiry-modal-body">
              {/* Position info */}
              <div className="inquiry-section">
                <label className="inquiry-label">Position</label>
                <div className="inquiry-position-info">
                  <span className="inquiry-oz">{position.ordnungszahl}</span>
                  <span>{position.description}</span>
                </div>
              </div>

              {/* Technical params */}
              {paramLines.length > 0 && (
                <div className="inquiry-section">
                  <label className="inquiry-label">Technische Parameter</label>
                  <div className="inquiry-params">
                    {paramLines.map((line) => (
                      <span key={line} className="inquiry-param-chip">{line}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Quantity */}
              {position.quantity != null && (
                <div className="inquiry-section">
                  <label className="inquiry-label">Menge</label>
                  <span>{position.quantity} {position.unit ?? 'Stück'}</span>
                </div>
              )}

              {/* Supplier selection */}
              <div className="inquiry-section">
                <label className="inquiry-label">Lieferant</label>
                <select
                  className="inquiry-select"
                  value={selectedSupplierId ?? ''}
                  onChange={(e) => setSelectedSupplierId(Number(e.target.value))}
                >
                  {suppliers.map((s) => {
                    const isMatch = position.parameters.product_category
                      ? s.categories.some(
                          (c) => c.toLowerCase() === position.parameters.product_category!.toLowerCase(),
                        )
                      : false
                    return (
                      <option key={s.id} value={s.id}>
                        {s.name} ({s.email}){isMatch ? ' — passend' : ''}
                      </option>
                    )
                  })}
                </select>
                {selectedSupplier && (
                  <div className="inquiry-supplier-info">
                    <span>{selectedSupplier.email}</span>
                    {selectedSupplier.phone && <span> | {selectedSupplier.phone}</span>}
                  </div>
                )}
              </div>

              {/* Custom message */}
              <div className="inquiry-section">
                <label className="inquiry-label">Anmerkung (optional)</label>
                <textarea
                  className="inquiry-textarea"
                  placeholder="Zusätzliche Hinweise oder Anforderungen..."
                  value={customMessage}
                  onChange={(e) => setCustomMessage(e.target.value)}
                  rows={3}
                />
              </div>

              {/* Project reference */}
              {projectName && (
                <div className="inquiry-section">
                  <label className="inquiry-label">Projekt</label>
                  <span className="inquiry-project-ref">{projectName}</span>
                </div>
              )}

              {error && <div className="inquiry-error">{error}</div>}
            </div>

            <div className="inquiry-modal-footer">
              <button className="btn btn-ghost inquiry-btn" onClick={onClose}>
                Abbrechen
              </button>
              <button
                className="btn btn-primary inquiry-btn btn-send"
                onClick={handleSend}
                disabled={!selectedSupplierId || sending}
              >
                {sending ? (
                  <>
                    <span className="spinner-small" />
                    Wird gesendet...
                  </>
                ) : (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Anfrage senden
                  </>
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
