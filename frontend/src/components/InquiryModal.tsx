import { useEffect, useMemo, useState } from 'react'
import { createInquiryBatch, fetchInquiries, fetchSuppliers } from '../api'
import type { LVPosition, Supplier } from '../types'

type Props = {
  isOpen: boolean
  onClose: () => void
  position: LVPosition
  projectName?: string | null
  projectId?: number | null
  productDescription?: string | null
  onSuccess?: () => void
}

export function InquiryModal({ isOpen, onClose, position, projectName, projectId, productDescription, onSuccess }: Props) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [selectedSupplierIds, setSelectedSupplierIds] = useState<Set<number>>(new Set())
  const [alreadyInquiredSupplierIds, setAlreadyInquiredSupplierIds] = useState<Set<number>>(new Set())
  const [editedDescription, setEditedDescription] = useState('')
  const [customMessage, setCustomMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [sentCount, setSentCount] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setSent(false)
      setSentCount(0)
      setError(null)
      setEditedDescription(productDescription || position.description)
      setCustomMessage('')
      setSelectedSupplierIds(new Set())
      setAlreadyInquiredSupplierIds(new Set())

      const loadSuppliers = fetchSuppliers()
      const loadExisting = projectId
        ? fetchInquiries(projectId)
        : Promise.resolve([])

      Promise.all([loadSuppliers, loadExisting])
        .then(([s, existingInquiries]) => {
          setSuppliers(s)

          // Find suppliers that already have an open inquiry for this position
          const alreadyInquired = new Set(
            existingInquiries
              .filter(inq => inq.position_id === position.id && inq.status === 'offen')
              .map(inq => inq.supplier_id),
          )
          setAlreadyInquiredSupplierIds(alreadyInquired)

          // Auto-select suppliers matching position category (excluding already inquired)
          const cat = position.parameters.product_category
          if (cat) {
            const matching = s.filter((sup) =>
              !alreadyInquired.has(sup.id) &&
              sup.categories.some((c) => c.toLowerCase() === cat.toLowerCase()),
            )
            if (matching.length > 0) {
              setSelectedSupplierIds(new Set(matching.map((m) => m.id)))
            }
          }
        })
        .catch(() => setError('Lieferanten konnten nicht geladen werden'))
    }
  }, [isOpen, position.parameters.product_category, position.id, projectId])

  const toggleSupplier = (id: number) => {
    setSelectedSupplierIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
    if (selectedSupplierIds.size === 0) return
    setSending(true)
    setError(null)
    try {
      const results = await createInquiryBatch({
        supplier_ids: Array.from(selectedSupplierIds),
        project_id: projectId,
        position_id: position.id,
        ordnungszahl: position.ordnungszahl,
        product_description: editedDescription.trim() || position.description,
        technical_params: position.parameters,
        quantity: position.quantity,
        unit: position.unit,
        custom_message: customMessage || undefined,
      })
      setSentCount(results.length)
      setSent(true)
      onSuccess?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Fehler beim Erstellen')
    } finally {
      setSending(false)
    }
  }

  if (!isOpen) return null

  const selectedSupplierNames = suppliers
    .filter((s) => selectedSupplierIds.has(s.id))
    .map((s) => s.name)

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
            <h4>{sentCount} Anfrage{sentCount !== 1 ? 'n' : ''} vorgemerkt</h4>
            <p>
              Anfragen für <strong>{selectedSupplierNames.join(', ')}</strong> wurden erstellt.
              Sie können diese über die Projektübersicht gesammelt versenden.
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
                  <span className="inquiry-position-desc">{position.description}</span>
                </div>
              </div>

              {/* Editable product description */}
              <div className="inquiry-section">
                <label className="inquiry-label">Produktbeschreibung für Anfrage</label>
                <textarea
                  className="inquiry-textarea"
                  value={editedDescription}
                  onChange={(e) => setEditedDescription(e.target.value)}
                  rows={3}
                  placeholder="Beschreibung des angefragten Produkts..."
                />
                <span className="inquiry-hint">
                  Kann frei angepasst werden — wird so an den Lieferanten gesendet.
                </span>
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

              {/* Supplier selection — checkbox list */}
              <div className="inquiry-section">
                <label className="inquiry-label">
                  Lieferanten ({selectedSupplierIds.size} ausgewählt)
                </label>
                <div className="inquiry-supplier-list">
                  {suppliers.map((s) => {
                    const isMatch = position.parameters.product_category
                      ? s.categories.some(
                          (c) => c.toLowerCase() === position.parameters.product_category!.toLowerCase(),
                        )
                      : false
                    const alreadyInquired = alreadyInquiredSupplierIds.has(s.id)
                    const checked = selectedSupplierIds.has(s.id)
                    return (
                      <label key={s.id} className={`inquiry-supplier-item ${checked ? 'checked' : ''} ${isMatch ? 'matching' : ''} ${alreadyInquired ? 'disabled' : ''}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleSupplier(s.id)}
                          disabled={alreadyInquired}
                        />
                        <div className="inquiry-supplier-detail">
                          <span className="inquiry-supplier-name">
                            {s.name}
                            {alreadyInquired && <span className="inquiry-already-badge">bereits angefragt</span>}
                            {!alreadyInquired && isMatch && <span className="inquiry-match-badge">passend</span>}
                          </span>
                          <span className="inquiry-supplier-email">{s.email}</span>
                        </div>
                      </label>
                    )
                  })}
                </div>
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
                disabled={selectedSupplierIds.size === 0 || sending}
              >
                {sending ? (
                  <>
                    <span className="spinner-small" />
                    Wird erstellt...
                  </>
                ) : (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {selectedSupplierIds.size > 1
                      ? `${selectedSupplierIds.size} Anfragen vormerken`
                      : 'Anfrage vormerken'}
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
