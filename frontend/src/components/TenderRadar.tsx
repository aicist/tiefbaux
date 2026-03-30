import { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { fetchTenders, refreshTenders, getRefreshStatus, updateTenderStatus } from '../api'
import type { Tender } from '../types'

// Fix default marker icons (Leaflet + bundler issue)
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

// Custom colored markers
function createColoredIcon(color: string) {
  return L.divIcon({
    className: 'radar-marker',
    html: `<div style="
      width: 14px; height: 14px; border-radius: 50%;
      background: ${color}; border: 2.5px solid #fff;
      box-shadow: 0 1px 4px rgba(0,0,0,0.3);
    "></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    popupAnchor: [0, -10],
  })
}

const ICON_HIGH = createColoredIcon('#16a34a')
const ICON_MEDIUM = createColoredIcon('#eab308')
const ICON_LOW = createColoredIcon('#9ca3af')

function getMarkerIcon(score: number) {
  if (score >= 40) return ICON_HIGH
  if (score >= 20) return ICON_MEDIUM
  return ICON_LOW
}

// Bonn center
const BONN_CENTER: [number, number] = [50.7374, 7.0982]
const DEFAULT_ZOOM = 10

type StatusFilter = 'alle' | 'neu' | 'relevant' | 'irrelevant' | 'analysiert'

function FlyToTender({ lat, lng }: { lat: number; lng: number }) {
  const map = useMap()
  useEffect(() => {
    map.flyTo([lat, lng], 13, { duration: 0.8 })
  }, [lat, lng, map])
  return null
}

class RadarMapBoundary extends Component<{ children: React.ReactNode }, { hasError: boolean }> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="radar-map-fallback">
          Kartenansicht konnte nicht geladen werden. Die Ausschreibungsliste steht weiterhin zur Verfügung.
        </div>
      )
    }
    return this.props.children
  }
}

export function TenderRadar() {
  const [tenders, setTenders] = useState<Tender[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('alle')
  const [selectedTender, setSelectedTender] = useState<Tender | null>(null)
  const [flyTo, setFlyTo] = useState<{ lat: number; lng: number } | null>(null)
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const markerRefs = useRef<Record<number, L.Marker>>({})

  const loadTenders = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    try {
      const data = await fetchTenders()
      setTenders(data)
    } catch (e) {
      console.error('Failed to load tenders:', e)
      setErrorMessage('Objektradar konnte nicht geladen werden. Bitte Seite neu laden oder später erneut versuchen.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTenders()
  }, [loadTenders])

  const handleRefresh = async () => {
    setRefreshing(true)
    setErrorMessage(null)
    try {
      await refreshTenders()
      // Poll until done
      const poll = async () => {
        const status = await getRefreshStatus()
        if (status.running) {
          setTimeout(poll, 2000)
        } else {
          setRefreshing(false)
          if (status.last_result?.error) {
            setErrorMessage(`Aktualisierung fehlgeschlagen: ${status.last_result.error}`)
            return
          }
          await loadTenders()
          if (status.last_result?.new != null) {
            setRefreshMessage(`${status.last_result.new} neue Ausschreibungen gefunden`)
            setTimeout(() => setRefreshMessage(null), 5000)
          }
        }
      }
      setTimeout(poll, 2000)
    } catch (e) {
      console.error('Refresh failed:', e)
      setErrorMessage('Aktualisierung des Objektradars fehlgeschlagen.')
      setRefreshing(false)
    }
  }

  const handleStatusChange = async (tender: Tender, newStatus: string) => {
    try {
      await updateTenderStatus(tender.id, newStatus)
      setTenders(prev => prev.map(t =>
        t.id === tender.id ? { ...t, status: newStatus as Tender['status'] } : t
      ))
    } catch (e) {
      console.error('Status update failed:', e)
    }
  }

  const handleTenderClick = (tender: Tender) => {
    setSelectedTender(tender)
    if (tender.lat && tender.lng) {
      setFlyTo({ lat: tender.lat, lng: tender.lng })
      // Open popup on the marker
      setTimeout(() => {
        const marker = markerRefs.current[tender.id]
        if (marker) marker.openPopup()
      }, 900)
    }
  }

  const filteredTenders = useMemo(() => {
    if (statusFilter === 'alle') return tenders
    return tenders.filter(t => t.status === statusFilter)
  }, [tenders, statusFilter])

  const tendersWithCoords = useMemo(() =>
    filteredTenders.filter(t => t.lat != null && t.lng != null),
    [filteredTenders]
  )

  const statusCounts = useMemo(() => {
    const counts = { alle: tenders.length, neu: 0, relevant: 0, irrelevant: 0, analysiert: 0 }
    for (const t of tenders) {
      if (t.status in counts) counts[t.status as keyof typeof counts]++
    }
    return counts
  }, [tenders])

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return '–'
    try {
      const d = new Date(dateStr)
      return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })
    } catch {
      return dateStr
    }
  }

  const relevanceBadge = (score: number) => {
    if (score >= 40) return <span className="radar-badge radar-badge--high">Hoch</span>
    if (score >= 20) return <span className="radar-badge radar-badge--medium">Mittel</span>
    return <span className="radar-badge radar-badge--low">Niedrig</span>
  }

  const statusBadge = (status: string) => {
    const cls = {
      neu: 'radar-status--neu',
      relevant: 'radar-status--relevant',
      irrelevant: 'radar-status--irrelevant',
      analysiert: 'radar-status--analysiert',
    }[status] || ''
    return <span className={`radar-status ${cls}`}>{status}</span>
  }

  return (
    <div className="radar-container">
      {/* Header */}
      <div className="radar-header">
        <div className="radar-header-left">
          <h2>Objektradar</h2>
          <span className="radar-count">{filteredTenders.length} Ausschreibungen</span>
          {refreshMessage && <span className="radar-refresh-msg">{refreshMessage}</span>}
        </div>
        <button
          className="radar-refresh-btn"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? (
            <><span className="radar-spinner" /> Suche läuft...</>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M21 12a9 9 0 11-2.636-6.364" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <path d="M21 3v6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Jetzt aktualisieren
            </>
          )}
        </button>
      </div>

      {errorMessage && (
        <div className="radar-error">
          {errorMessage}
        </div>
      )}

      {/* Status filter tabs */}
      <div className="radar-filters">
        {(['alle', 'neu', 'relevant', 'irrelevant', 'analysiert'] as StatusFilter[]).map(s => (
          <button
            key={s}
            className={`radar-filter-tab ${statusFilter === s ? 'radar-filter-tab--active' : ''}`}
            onClick={() => setStatusFilter(s)}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
            <span className="radar-filter-count">{statusCounts[s]}</span>
          </button>
        ))}
      </div>

      {/* Main content: Map + Table */}
      <div className="radar-content">
        {/* Map */}
        <div className="radar-map">
          <RadarMapBoundary>
            <MapContainer
              center={BONN_CENTER}
              zoom={DEFAULT_ZOOM}
              style={{ height: '100%', width: '100%', borderRadius: '8px' }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {flyTo && <FlyToTender lat={flyTo.lat} lng={flyTo.lng} />}
              {tendersWithCoords.map(t => (
                <Marker
                  key={t.id}
                  position={[t.lat!, t.lng!]}
                  icon={getMarkerIcon(t.relevance_score)}
                  ref={(ref) => { if (ref) markerRefs.current[t.id] = ref }}
                  eventHandlers={{
                    click: () => setSelectedTender(t),
                  }}
                >
                  <Popup>
                    <div className="radar-popup">
                      <strong>{t.title}</strong>
                      {t.auftraggeber && <p className="radar-popup-buyer">{t.auftraggeber}</p>}
                      <p className="radar-popup-meta">
                        {t.ort && <span>{t.ort}</span>}
                        {t.submission_deadline && <span>Frist: {formatDate(t.submission_deadline)}</span>}
                      </p>
                      <div className="radar-popup-actions">
                        {relevanceBadge(t.relevance_score)}
                        {t.url && (
                          <a href={t.url} target="_blank" rel="noopener noreferrer" className="radar-popup-link">
                            Zur Ausschreibung
                          </a>
                        )}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </RadarMapBoundary>
        </div>

        {/* Table */}
        <div className="radar-table-wrapper">
          {loading ? (
            <div className="radar-loading">Lade Ausschreibungen...</div>
          ) : filteredTenders.length === 0 ? (
            <div className="radar-empty">
              <p>Keine Ausschreibungen gefunden.</p>
              <p className="radar-empty-hint">Klicke "Jetzt aktualisieren" um neue Ausschreibungen zu suchen.</p>
            </div>
          ) : (
            <div className="radar-table-scroll">
              {filteredTenders.map(t => (
                <div
                  key={t.id}
                  className={`radar-row ${selectedTender?.id === t.id ? 'radar-row--selected' : ''}`}
                  onClick={() => handleTenderClick(t)}
                >
                  <div className="radar-row-header">
                    <div className="radar-row-title">{t.title}</div>
                    <div className="radar-row-badges">
                      {relevanceBadge(t.relevance_score)}
                      {statusBadge(t.status)}
                    </div>
                  </div>
                  <div className="radar-row-meta">
                    {t.auftraggeber && <span className="radar-meta-buyer">{t.auftraggeber}</span>}
                    {t.ort && <span className="radar-meta-ort">{t.ort}</span>}
                    {t.submission_deadline && (
                      <span className="radar-meta-deadline">Frist: {formatDate(t.submission_deadline)}</span>
                    )}
                  </div>
                  {t.description && (
                    <div className="radar-row-desc">{t.description}</div>
                  )}
                  <div className="radar-row-actions">
                    <select
                      className="radar-status-select"
                      value={t.status}
                      onChange={(e) => {
                        e.stopPropagation()
                        handleStatusChange(t, e.target.value)
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <option value="neu">Neu</option>
                      <option value="relevant">Relevant</option>
                      <option value="irrelevant">Irrelevant</option>
                      <option value="analysiert">Analysiert</option>
                    </select>
                    {t.url && (
                      <a
                        href={t.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="radar-link-btn"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                          <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        Öffnen
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
