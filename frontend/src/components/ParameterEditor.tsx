import { useCallback, useEffect, useState } from 'react'
import type { LVPosition, TechnicalParameters } from '../types'

const CATEGORIES = [
  'Kanalrohre',
  'Formstücke',
  'Schachtbauteile',
  'Schachtabdeckungen',
  'Straßenentwässerung',
  'Rinnen',
  'Dichtungen & Zubehör',
  'Geotextilien',
]

const LOAD_CLASSES = ['', 'A15', 'B125', 'C250', 'D400', 'E600', 'F900']
const LOAD_CLASS_CATEGORIES = new Set(['Schachtabdeckungen', 'Straßenentwässerung'])

type Props = {
  position: LVPosition
  onParameterChange: (positionId: string, params: Partial<TechnicalParameters>) => void
  isRefreshing: boolean
}

function buildSummary(params: LVPosition['parameters']): string {
  const parts: string[] = []
  if (params.product_category) parts.push(params.product_category)
  if (params.nominal_diameter_dn) parts.push(`DN ${params.nominal_diameter_dn}`)
  if (params.material) parts.push(params.material)
  if (params.load_class) parts.push(params.load_class)
  return parts.length > 0 ? parts.join(' · ') : 'Keine Parameter erkannt'
}

export function ParameterEditor({ position, onParameterChange, isRefreshing }: Props) {
  const params = position.parameters
  const [dn, setDn] = useState(params.nominal_diameter_dn?.toString() ?? '')
  const [category, setCategory] = useState(params.product_category ?? '')
  const [material, setMaterial] = useState(params.material ?? '')
  const [loadClass, setLoadClass] = useState(params.load_class ?? '')
  const [isCollapsed, setIsCollapsed] = useState(true)

  const showLoadClass = LOAD_CLASS_CATEGORIES.has(category)

  // Sync when position changes
  useEffect(() => {
    setDn(position.parameters.nominal_diameter_dn?.toString() ?? '')
    setCategory(position.parameters.product_category ?? '')
    setMaterial(position.parameters.material ?? '')
    setLoadClass(position.parameters.load_class ?? '')
  }, [position.id, position.parameters])

  const commitChanges = useCallback(
    (overrides: Partial<{ dn: string; category: string; material: string; loadClass: string }> = {}) => {
      const finalDn = overrides.dn ?? dn
      const finalCategory = overrides.category ?? category
      const finalMaterial = overrides.material ?? material
      const finalLoadClass = overrides.loadClass ?? loadClass

      const parsedDn = finalDn ? parseInt(finalDn, 10) : null
      const updates: Partial<TechnicalParameters> = {
        nominal_diameter_dn: parsedDn && !isNaN(parsedDn) ? parsedDn : null,
        product_category: finalCategory || null,
        material: finalMaterial || null,
        load_class: finalLoadClass || null,
      }
      onParameterChange(position.id, updates)
    },
    [position.id, dn, category, material, loadClass, onParameterChange],
  )

  const handleDnBlur = () => commitChanges()
  const handleDnKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') commitChanges()
  }
  const handleCategoryChange = (value: string) => {
    setCategory(value)
    // Clear load class if switching to a non-relevant category
    if (!LOAD_CLASS_CATEGORIES.has(value)) {
      setLoadClass('')
      commitChanges({ category: value, loadClass: '' })
    } else {
      commitChanges({ category: value })
    }
  }
  const handleLoadClassChange = (value: string) => {
    setLoadClass(value)
    commitChanges({ loadClass: value })
  }
  const handleMaterialBlur = () => commitChanges()
  const handleMaterialKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') commitChanges()
  }

  return (
    <div className={`parameter-editor ${isRefreshing ? 'refreshing' : ''}`}>
      <button
        type="button"
        className="param-editor-toggle"
        aria-expanded={!isCollapsed}
        onClick={() => setIsCollapsed(!isCollapsed)}
      >
        <svg
          className={`chevron ${isCollapsed ? '' : 'open'}`}
          width="14" height="14" viewBox="0 0 24 24" fill="none"
        >
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="param-toggle-title">
          Erkannte Parameter
          {isRefreshing && <span className="param-spinner" />}
        </span>
        {isCollapsed && (
          <span className="param-summary">{buildSummary(params)}</span>
        )}
      </button>

      <div className={`param-grid-wrapper ${isCollapsed ? 'collapsed' : 'expanded'}`}>
        <div className="param-grid">
          <label className="param-field">
            <span className="param-label">Kategorie</span>
            <select
              value={category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="param-input"
            >
              <option value="">— nicht erkannt —</option>
              {CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          </label>
          <label className="param-field">
            <span className="param-label">DN (Nennweite)</span>
            <input
              type="number"
              value={dn}
              onChange={(e) => setDn(e.target.value)}
              onBlur={handleDnBlur}
              onKeyDown={handleDnKeyDown}
              placeholder="z.B. 200"
              className="param-input"
            />
          </label>
          <label className="param-field">
            <span className="param-label">Material</span>
            <input
              type="text"
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
              onBlur={handleMaterialBlur}
              onKeyDown={handleMaterialKeyDown}
              placeholder="z.B. PVC-U"
              className="param-input"
            />
          </label>
          {showLoadClass && (
            <label className="param-field">
              <span className="param-label">Belastungsklasse</span>
              <select
                value={loadClass}
                onChange={(e) => handleLoadClassChange(e.target.value)}
                className="param-input"
              >
                {LOAD_CLASSES.map((lc) => (
                  <option key={lc} value={lc}>{lc || '— nicht relevant —'}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>
    </div>
  )
}
