import { useCallback, useEffect, useRef, useState } from 'react'
import { searchProducts } from '../api'
import type { ProductSearchResult } from '../types'

const CATEGORIES = [
  '', 'Kanalrohre', 'Formstücke', 'Schachtbauteile', 'Schachtabdeckungen',
  'Straßenentwässerung', 'Rinnen', 'Dichtungen & Zubehör', 'Geotextilien',
  'Kabelschutz', 'Regenwasser', 'Versickerung', 'Hausanschlüsse',
]

// Which extra filters are available per category
const CATEGORY_FILTERS: Record<string, string[]> = {
  Kanalrohre: ['dn', 'sn', 'material'],
  Formstücke: ['dn', 'angle', 'material'],
  Schachtbauteile: ['dn', 'load_class'],
  Schachtabdeckungen: ['load_class', 'material'],
  Straßenentwässerung: ['load_class', 'dn'],
  Hausanschlüsse: ['dn', 'material'],
  Rinnen: ['load_class'],
  'Dichtungen & Zubehör': ['dn', 'material'],
}

const SN_OPTIONS = ['', '2', '4', '8', '10', '12', '16']
const LOAD_CLASS_OPTIONS = ['', 'A15', 'B125', 'C250', 'D400', 'E600', 'F900']

type Props = {
  isOpen: boolean
  onClose: () => void
  onSelect: (product: ProductSearchResult) => void
  initialCategory?: string | null
  initialDn?: number | null
}

function formatPrice(value?: number | null): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(value)
}

export function ProductSearchModal({ isOpen, onClose, onSelect, initialCategory, initialDn }: Props) {
  const PAGE_SIZE = 50
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState(initialCategory ?? '')
  const [dn, setDn] = useState(initialDn?.toString() ?? '')
  const [sn, setSn] = useState('')
  const [loadClass, setLoadClass] = useState('')
  const [material, setMaterial] = useState('')
  const [angle, setAngle] = useState('')
  const [results, setResults] = useState<ProductSearchResult[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const inputRef = useRef<HTMLInputElement>(null)
  const currentParams = useRef({
    q: '',
    cat: '',
    dn: '',
    sn: '',
    loadClass: '',
    material: '',
    angle: '',
  })

  const activeFilters = CATEGORY_FILTERS[category] ?? []

  // Reset filters when opening with new position
  useEffect(() => {
    if (isOpen) {
      setCategory(initialCategory ?? '')
      setDn(initialDn?.toString() ?? '')
      setQuery('')
      setSn('')
      setLoadClass('')
      setMaterial('')
      setAngle('')
      setResults([])
      setHasMore(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen, initialCategory, initialDn])

  // Reset category-specific filters when category changes
  useEffect(() => {
    setSn('')
    setLoadClass('')
    setMaterial('')
    setAngle('')
  }, [category])

  const doSearch = useCallback(async (params: {
    q: string; cat: string; dn: string; sn: string; loadClass: string; material: string; angle: string
  }, offset = 0) => {
    const isAppend = offset > 0
    setIsLoading(true)
    try {
      const parsedDn = params.dn ? parseInt(params.dn, 10) : undefined
      const parsedAngle = params.angle ? parseInt(params.angle, 10) : undefined
      const data = await searchProducts({
        q: params.q || undefined,
        category: params.cat || undefined,
        dn: parsedDn && !isNaN(parsedDn) ? parsedDn : undefined,
        sn: params.sn || undefined,
        load_class: params.loadClass || undefined,
        material: params.material || undefined,
        angle: parsedAngle && !isNaN(parsedAngle) ? parsedAngle : undefined,
        limit: PAGE_SIZE,
        offset,
      })
      setResults(prev => isAppend ? [...prev, ...data.items] : data.items)
      setHasMore(data.has_more)
    } catch {
      if (!isAppend) setResults([])
      setHasMore(false)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Debounced search on any filter change
  useEffect(() => {
    if (!isOpen) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const params = { q: query, cat: category, dn, sn, loadClass, material, angle }
      currentParams.current = params
      doSearch(params)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, category, dn, sn, loadClass, material, angle, isOpen, doSearch])

  if (!isOpen) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box product-search-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Katalog durchsuchen</h3>
          <button className="modal-close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="search-filters">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Artikelname suchen..."
            className="search-input"
          />
          <select
            value={category}
            onChange={e => setCategory(e.target.value)}
            className="search-select"
          >
            <option value="">Alle Kategorien</option>
            {CATEGORIES.filter(Boolean).map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <div className="search-extra-filters">
            {activeFilters.includes('dn') && (
              <input
                type="number"
                value={dn}
                onChange={e => setDn(e.target.value)}
                placeholder="DN"
                className="search-dn"
              />
            )}
            {!activeFilters.includes('dn') && !category && (
              <input
                type="number"
                value={dn}
                onChange={e => setDn(e.target.value)}
                placeholder="DN"
                className="search-dn"
              />
            )}
            {activeFilters.includes('sn') && (
              <select value={sn} onChange={e => setSn(e.target.value)} className="search-select-sm">
                <option value="">SN</option>
                {SN_OPTIONS.filter(Boolean).map(v => (
                  <option key={v} value={v}>SN {v}</option>
                ))}
              </select>
            )}
            {activeFilters.includes('load_class') && (
              <select value={loadClass} onChange={e => setLoadClass(e.target.value)} className="search-select-sm">
                <option value="">Belastungsklasse</option>
                {LOAD_CLASS_OPTIONS.filter(Boolean).map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            )}
            {activeFilters.includes('material') && (
              <input
                type="text"
                value={material}
                onChange={e => setMaterial(e.target.value)}
                placeholder="Werkstoff"
                className="search-material"
              />
            )}
            {activeFilters.includes('angle') && (
              <input
                type="number"
                value={angle}
                onChange={e => setAngle(e.target.value)}
                placeholder="Winkel (°)"
                className="search-dn"
              />
            )}
          </div>
        </div>

        <div className="search-results">
          {isLoading && <div className="search-loading">Suche...</div>}
          {!isLoading && results.length === 0 && (
            <div className="search-empty">
              {query || category || dn ? 'Keine Ergebnisse' : 'Suchbegriff eingeben oder Filter setzen'}
            </div>
          )}
          {!isLoading && results.map(product => (
            <div key={product.artikel_id} className="search-result-row">
              <div className="search-result-info">
                <strong className="search-result-name">{product.artikelname}</strong>
                <div className="search-result-meta">
                  <span>{product.artikel_id}</span>
                  {product.hersteller && <span>{product.hersteller}</span>}
                  {product.nennweite_dn != null && <span>DN {product.nennweite_dn}</span>}
                  {product.belastungsklasse && <span>{product.belastungsklasse}</span>}
                  {product.steifigkeitsklasse_sn && <span>SN {product.steifigkeitsklasse_sn}</span>}
                  {product.werkstoff && <span>{product.werkstoff}</span>}
                </div>
                <div className="search-result-details">
                  <span>{formatPrice(product.vk_listenpreis_netto)}</span>
                  <span className={`stock-mini ${(product.lager_gesamt ?? 0) > 0 ? 'in-stock' : 'no-stock'}`}>
                    {(product.lager_gesamt ?? 0) > 0 ? `${product.lager_gesamt} auf Lager` : 'Nicht auf Lager'}
                  </span>
                </div>
              </div>
              <button
                className="search-select-btn"
                onClick={() => { onSelect(product); onClose() }}
              >
                Auswählen
              </button>
            </div>
          ))}
          {!isLoading && hasMore && (
            <button
              className="search-load-more"
              onClick={() => doSearch(currentParams.current, results.length)}
            >
              Mehr Artikel laden
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
