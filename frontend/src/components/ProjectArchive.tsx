import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  deleteKunde,
  deleteObjekt,
  deleteProject,
  fetchKundeProjects,
  fetchObjekt,
  fetchObjekte,
  updateKunde,
  updateObjekt,
  updateProject,
} from '../api'
import type { KundenOrdnerSummary, ObjektSummary, ProjectSummary } from '../types'

type ArchiveEntity =
  | { kind: 'objekt'; data: ObjektSummary }
  | { kind: 'kunde'; data: KundenOrdnerSummary }
  | { kind: 'projekt'; data: ProjectSummary }

type ContextMenuState = { x: number; y: number; entity: ArchiveEntity }

type Props = {
  onLoadProject: (projectId: number) => void
}

type NavState =
  | { level: 'objekte' }
  | { level: 'kunden'; objekt: ObjektSummary }
  | { level: 'projekte'; objekt: ObjektSummary; kunde: KundenOrdnerSummary }

type AnfrageFilter = 'alle' | 'submission' | 'bedarf'

function anfrageArtLabel(art: string | undefined): string {
  return art === 'bedarf' ? 'Bedarf' : 'Submission'
}

const OBJEKT_CACHE_TTL_MS = 60_000
let objektListCache: { items: ObjektSummary[]; ts: number } | null = null

function statusLabel(status?: string): string {
  if (status === 'gerechnet') return 'Gerechnet'
  if (status === 'anfrage_offen') return 'Anfrage offen'
  if (status === 'offen') return 'Offen'
  return 'Neu'
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function ProjectArchive({ onLoadProject }: Props) {
  const [nav, setNav] = useState<NavState>({ level: 'objekte' })
  const [objekte, setObjekte] = useState<ObjektSummary[]>(() => objektListCache?.items ?? [])
  const [kunden, setKunden] = useState<KundenOrdnerSummary[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(() => !objektListCache)
  const [searchTerm, setSearchTerm] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [anfrageFilter, setAnfrageFilter] = useState<AnfrageFilter>('alle')
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [editEntity, setEditEntity] = useState<ArchiveEntity | null>(null)
  const [editFields, setEditFields] = useState<Record<string, string>>({})
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const didInitialLoad = useRef(false)

  const closeContextMenu = useCallback(() => setContextMenu(null), [])

  useEffect(() => {
    if (!contextMenu) return
    const handler = () => closeContextMenu()
    window.addEventListener('click', handler)
    window.addEventListener('scroll', handler, true)
    return () => {
      window.removeEventListener('click', handler)
      window.removeEventListener('scroll', handler, true)
    }
  }, [contextMenu, closeContextMenu])

  const openContextMenu = useCallback((event: React.MouseEvent, entity: ArchiveEntity) => {
    event.preventDefault()
    event.stopPropagation()
    setContextMenu({ x: event.clientX, y: event.clientY, entity })
  }, [])

  const beginEdit = useCallback((entity: ArchiveEntity) => {
    if (entity.kind === 'objekt') {
      setEditFields({
        bauvorhaben: entity.data.bauvorhaben ?? '',
        objekt_nr: entity.data.objekt_nr ?? '',
        auftraggeber: entity.data.auftraggeber ?? '',
        submission_date: entity.data.submission_date ?? '',
      })
    } else if (entity.kind === 'kunde') {
      setEditFields({
        name: entity.data.name,
        display_name: entity.data.display_name ?? '',
        email_domain: entity.data.email_domain ?? '',
      })
    } else {
      setEditFields({
        project_name: entity.data.project_name ?? '',
        bauvorhaben: entity.data.bauvorhaben ?? '',
        submission_date: entity.data.submission_date ?? '',
        anfrage_art: entity.data.anfrage_art ?? 'submission',
      })
    }
    setEditEntity(entity)
    setContextMenu(null)
  }, [])

  const saveEdit = useCallback(async () => {
    if (!editEntity) return
    setIsSavingEdit(true)
    setErrorMsg(null)
    try {
      const toNullable = (v: string) => (v.trim() === '' ? null : v.trim())
      if (editEntity.kind === 'objekt') {
        const updated = await updateObjekt(editEntity.data.id, {
          bauvorhaben: toNullable(editFields.bauvorhaben ?? ''),
          objekt_nr: toNullable(editFields.objekt_nr ?? ''),
          auftraggeber: toNullable(editFields.auftraggeber ?? ''),
          submission_date: toNullable(editFields.submission_date ?? ''),
        })
        setObjekte((prev) => prev.map((o) => (o.id === updated.id ? updated : o)))
        objektListCache = null
        if (nav.level === 'kunden' && nav.objekt.id === updated.id) {
          setNav({ level: 'kunden', objekt: updated })
        } else if (nav.level === 'projekte' && nav.objekt.id === updated.id) {
          setNav({ level: 'projekte', objekt: updated, kunde: nav.kunde })
        }
      } else if (editEntity.kind === 'kunde') {
        const rawDomain = (editFields.email_domain ?? '').trim()
        // Accept full email, "@domain" or "domain" — store only domain.
        const normalizedDomain = rawDomain.includes('@')
          ? rawDomain.split('@').pop()?.trim() ?? ''
          : rawDomain
        const updated = await updateKunde(editEntity.data.kunde_id, {
          name: editFields.name?.trim() || editEntity.data.name,
          display_name: toNullable(editFields.display_name ?? ''),
          email_domain: toNullable(normalizedDomain),
        })
        setKunden((prev) => prev.map((k) => (k.kunde_id === updated.kunde_id ? updated : k)))
        if (nav.level === 'projekte' && nav.kunde.kunde_id === updated.kunde_id) {
          setNav({ level: 'projekte', objekt: nav.objekt, kunde: updated })
        }
      } else {
        const updated = await updateProject(editEntity.data.id, {
          project_name: toNullable(editFields.project_name ?? ''),
          bauvorhaben: toNullable(editFields.bauvorhaben ?? ''),
          submission_date: toNullable(editFields.submission_date ?? ''),
          anfrage_art: editFields.anfrage_art || undefined,
        })
        setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
      }
      setEditEntity(null)
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Speichern fehlgeschlagen.')
    } finally {
      setIsSavingEdit(false)
    }
  }, [editEntity, editFields, nav])

  const confirmDelete = useCallback(async (entity: ArchiveEntity) => {
    setContextMenu(null)
    if (entity.kind === 'projekt') {
      const name = entity.data.bauvorhaben ?? entity.data.filename ?? entity.data.project_name ?? `Projekt #${entity.data.id}`
      if (!window.confirm(`"${name}" wirklich löschen?`)) return
      setDeletingId(entity.data.id)
      setErrorMsg(null)
      try {
        await deleteProject(entity.data.id)
        setProjects((prev) => prev.filter((p) => p.id !== entity.data.id))
        objektListCache = null
      } catch (err) {
        setErrorMsg(err instanceof ApiError ? err.message : 'Projekt konnte nicht gelöscht werden.')
      } finally {
        setDeletingId(null)
      }
      return
    }
    if (entity.kind === 'kunde') {
      const cnt = entity.data.project_count
      const msg = cnt > 0
        ? `"${entity.data.display_name ?? entity.data.name}" und ${cnt} verknüpfte${cnt === 1 ? 's' : ''} Projekt${cnt === 1 ? '' : 'e'} werden unwiderruflich gelöscht. Fortfahren?`
        : `"${entity.data.display_name ?? entity.data.name}" wirklich löschen?`
      if (!window.confirm(msg)) return
      setErrorMsg(null)
      try {
        await deleteKunde(entity.data.kunde_id)
        setKunden((prev) => prev.filter((k) => k.kunde_id !== entity.data.kunde_id))
        objektListCache = null
      } catch (err) {
        setErrorMsg(err instanceof ApiError ? err.message : 'Kunde konnte nicht gelöscht werden.')
      }
      return
    }
    // objekt
    const cnt = entity.data.project_count
    const msg = cnt > 0
      ? `"${entity.data.bauvorhaben ?? 'Objekt'}" und ${cnt} verknüpfte${cnt === 1 ? 's' : ''} Projekt${cnt === 1 ? '' : 'e'} werden unwiderruflich gelöscht. Fortfahren?`
      : `"${entity.data.bauvorhaben ?? 'Objekt'}" wirklich löschen?`
    if (!window.confirm(msg)) return
    setErrorMsg(null)
    try {
      await deleteObjekt(entity.data.id)
      setObjekte((prev) => prev.filter((o) => o.id !== entity.data.id))
      objektListCache = null
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Objekt konnte nicht gelöscht werden.')
    }
  }, [])

  const loadObjekte = useCallback(async (q?: string) => {
    const normalized = q?.trim() ?? ''
    const isDefault = normalized.length === 0
    const hasFreshCache = Boolean(
      isDefault && objektListCache && (Date.now() - objektListCache.ts) < OBJEKT_CACHE_TTL_MS,
    )
    if (!hasFreshCache) setLoading(true)
    try {
      const data = await fetchObjekte(normalized || undefined)
      setObjekte(data)
      if (isDefault) objektListCache = { items: data, ts: Date.now() }
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Objekte konnten nicht geladen werden.')
      setObjekte([])
    } finally {
      setLoading(false)
    }
  }, [])

  const loadKunden = useCallback(async (objekt: ObjektSummary) => {
    setLoading(true)
    setErrorMsg(null)
    try {
      const data = await fetchObjekt(objekt.id)
      setKunden(data.kunden)
      setNav({ level: 'kunden', objekt: data.objekt })
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Kunden konnten nicht geladen werden.')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadProjects = useCallback(async (objekt: ObjektSummary, kunde: KundenOrdnerSummary) => {
    setLoading(true)
    setErrorMsg(null)
    try {
      const data = await fetchKundeProjects(objekt.id, kunde.kunde_id)
      setProjects(data.projects)
      setNav({ level: 'projekte', objekt: data.objekt, kunde: data.kunde })
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Projekte konnten nicht geladen werden.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!didInitialLoad.current) {
      didInitialLoad.current = true
      if (objektListCache && (Date.now() - objektListCache.ts) < OBJEKT_CACHE_TTL_MS) {
        setObjekte(objektListCache.items)
        setLoading(false)
        void loadObjekte()
        return
      }
      void loadObjekte()
      return
    }
    if (nav.level !== 'objekte') return
    if (!searchTerm.trim()) {
      void loadObjekte()
      return
    }
    const timer = setTimeout(() => { void loadObjekte(searchTerm) }, 300)
    return () => clearTimeout(timer)
  }, [searchTerm, loadObjekte, nav.level])

  const backToObjekte = () => {
    setNav({ level: 'objekte' })
    setSearchTerm('')
  }
  const backToKunden = () => {
    if (nav.level === 'projekte') setNav({ level: 'kunden', objekt: nav.objekt })
  }

  if (loading && nav.level === 'objekte' && objekte.length === 0) {
    return (
      <div className="archive-container">
        <p className="archive-empty">Objekte werden geladen...</p>
      </div>
    )
  }

  const breadcrumb = (
    <div className="archive-breadcrumb">
      <button className="crumb-link" onClick={backToObjekte}>Objektarchiv</button>
      {nav.level !== 'objekte' && (
        <>
          <span className="crumb-sep">/</span>
          {nav.level === 'projekte' ? (
            <button className="crumb-link" onClick={backToKunden}>
              {nav.objekt.bauvorhaben ?? nav.objekt.slug}
            </button>
          ) : (
            <span className="crumb-current">{nav.objekt.bauvorhaben ?? nav.objekt.slug}</span>
          )}
        </>
      )}
      {nav.level === 'projekte' && (
        <>
          <span className="crumb-sep">/</span>
          <span className="crumb-current">{nav.kunde.display_name ?? nav.kunde.name}</span>
        </>
      )}
    </div>
  )

  return (
    <div className="archive-container">
      {breadcrumb}

      {nav.level === 'objekte' && (
        <>
          <div className="archive-header">
            <h2>Objektarchiv</h2>
            <span className="archive-count">{objekte.length} Objekt{objekte.length !== 1 ? 'e' : ''}</span>
          </div>
          <div className="archive-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="search-icon">
              <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
              <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              placeholder="Objekte suchen (Bauvorhaben, Auftraggeber, Objektnr.)..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          {errorMsg && <p className="archive-error">{errorMsg}</p>}
          {objekte.length === 0 ? (
            <p className="archive-empty">
              {searchTerm ? 'Keine Objekte gefunden.' : 'Noch keine Objekte im Archiv.'}
            </p>
          ) : (
            <div className="archive-list">
              {objekte.map((objekt) => (
                <div
                  key={objekt.id}
                  className="archive-row archive-row-folder"
                  onClick={() => loadKunden(objekt)}
                  onContextMenu={(e) => openContextMenu(e, { kind: 'objekt', data: objekt })}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') loadKunden(objekt) }}
                >
                  <div className="archive-folder-icon" aria-hidden>
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                      <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
                            stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" fill="#fef3c7" />
                    </svg>
                  </div>
                  <div className="archive-main">
                    <div className="archive-title-row">
                      <span className="archive-filename">
                        {objekt.bauvorhaben ?? 'Unbenanntes Objekt'}
                      </span>
                      {objekt.objekt_nr && <span className="archive-objnr">{objekt.objekt_nr}</span>}
                    </div>
                    <div className="archive-meta-row">
                      {objekt.auftraggeber && (
                        <span className="archive-kunde">Auftraggeber: {objekt.auftraggeber}</span>
                      )}
                      {objekt.submission_date && (
                        <span className="archive-submission">Submission: {objekt.submission_date}</span>
                      )}
                      <span className="archive-date">Zuletzt: {formatDate(objekt.latest_project_created_at ?? objekt.created_at)}</span>
                    </div>
                  </div>
                  <div className="archive-stats">
                    <span>{objekt.kunden_count} Kunde{objekt.kunden_count !== 1 ? 'n' : ''}</span>
                    <span>{objekt.project_count} Projekt{objekt.project_count !== 1 ? 'e' : ''}</span>
                  </div>
                  <button
                    className="archive-row-menu-btn"
                    aria-label="Aktionen"
                    onClick={(e) => { e.stopPropagation(); openContextMenu(e, { kind: 'objekt', data: objekt }) }}
                  >
                    ⋯
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {nav.level === 'kunden' && (
        <>
          <div className="archive-header">
            <h2>{nav.objekt.bauvorhaben ?? 'Objekt'}</h2>
            <span className="archive-count">{kunden.length} Kundenordner</span>
          </div>
          {errorMsg && <p className="archive-error">{errorMsg}</p>}
          {kunden.length === 0 ? (
            <p className="archive-empty">Keine Kunden unter diesem Objekt.</p>
          ) : (
            <div className="archive-list">
              {kunden.map((kunde) => (
                <div
                  key={kunde.kunde_id}
                  className="archive-row archive-row-folder"
                  onClick={() => loadProjects(nav.objekt, kunde)}
                  onContextMenu={(e) => openContextMenu(e, { kind: 'kunde', data: kunde })}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') loadProjects(nav.objekt, kunde) }}
                >
                  <div className="archive-folder-icon" aria-hidden>
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.8" />
                      <path d="M4 20c0-4 4-6 8-6s8 2 8 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                    </svg>
                  </div>
                  <div className="archive-main">
                    <div className="archive-title-row">
                      <span className="archive-filename">{kunde.display_name ?? kunde.name}</span>
                    </div>
                    <div className="archive-meta-row">
                      {kunde.email_domain && (
                        <span className="archive-kunde">
                          @{(kunde.email_domain.includes('@') ? kunde.email_domain.split('@').pop() : kunde.email_domain.replace(/^@/, ''))}
                        </span>
                      )}
                      <span className="archive-date">Zuletzt: {formatDate(kunde.latest_project_created_at)}</span>
                    </div>
                  </div>
                  <div className="archive-stats">
                    <span>{kunde.project_count} Projekt{kunde.project_count !== 1 ? 'e' : ''}</span>
                  </div>
                  <button
                    className="archive-row-menu-btn"
                    aria-label="Aktionen"
                    onClick={(e) => { e.stopPropagation(); openContextMenu(e, { kind: 'kunde', data: kunde }) }}
                  >
                    ⋯
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {nav.level === 'projekte' && (() => {
        const filtered = anfrageFilter === 'alle'
          ? projects
          : projects.filter((p) => (p.anfrage_art ?? 'submission') === anfrageFilter)
        const submissionCount = projects.filter((p) => (p.anfrage_art ?? 'submission') === 'submission').length
        const bedarfCount = projects.filter((p) => p.anfrage_art === 'bedarf').length
        return (
        <>
          <div className="archive-header">
            <h2>{nav.kunde.display_name ?? nav.kunde.name}</h2>
            <span className="archive-count">{filtered.length} Projekt{filtered.length !== 1 ? 'e' : ''}</span>
          </div>
          <div className="archive-filter-tabs">
            <button
              className={`filter-tab ${anfrageFilter === 'alle' ? 'filter-tab--active' : ''}`}
              onClick={() => setAnfrageFilter('alle')}
            >
              Alle ({projects.length})
            </button>
            <button
              className={`filter-tab ${anfrageFilter === 'submission' ? 'filter-tab--active' : ''}`}
              onClick={() => setAnfrageFilter('submission')}
            >
              Submission ({submissionCount})
            </button>
            <button
              className={`filter-tab ${anfrageFilter === 'bedarf' ? 'filter-tab--active' : ''}`}
              onClick={() => setAnfrageFilter('bedarf')}
            >
              Bedarf ({bedarfCount})
            </button>
          </div>
          {errorMsg && <p className="archive-error">{errorMsg}</p>}
          {filtered.length === 0 ? (
            <p className="archive-empty">Keine Projekte für diesen Filter.</p>
          ) : (
            <div className="archive-list">
              {filtered.map((project) => (
                <div
                  key={project.id}
                  className={`archive-row archive-row-${project.anfrage_art ?? 'submission'}`}
                  onContextMenu={(e) => openContextMenu(e, { kind: 'projekt', data: project })}
                >
                  <div className="archive-main">
                    <div className="archive-title-row">
                      {project.projekt_nr && <span className="archive-objnr">{project.projekt_nr}</span>}
                      <span className={`archive-anfrageart archive-anfrageart-${project.anfrage_art ?? 'submission'}`}>
                        {anfrageArtLabel(project.anfrage_art)}
                      </span>
                      <span className={`archive-status archive-status-${project.status ?? 'neu'}`}>
                        {statusLabel(project.status)}
                      </span>
                      <span className="archive-filename">
                        {project.bauvorhaben ?? project.filename ?? 'Unbenannt'}
                      </span>
                    </div>
                    <div className="archive-meta-row">
                      {project.submission_date && (
                        <span className="archive-submission">Submission: {project.submission_date}</span>
                      )}
                      <span className="archive-date">{formatDate(project.created_at)}</span>
                    </div>
                    {(project.assigned_user_name || project.last_editor_name) && (
                      <div className="archive-user-row">
                        {project.assigned_user_name && (
                          <span className="archive-assigned">Zugewiesen: {project.assigned_user_name}</span>
                        )}
                        {project.last_editor_name && (
                          <span className="archive-editor">Zuletzt: {project.last_editor_name}</span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="archive-stats">
                    <span>{project.total_positions} Pos.</span>
                    <span>{project.billable_positions} Material</span>
                    <span>{project.service_positions} DL</span>
                  </div>
                  <div className="archive-actions">
                    <button className="btn-archive-load" onClick={() => onLoadProject(project.id)}>
                      {project.status === 'gerechnet' ? 'Projekt ansehen' : 'Analyse laden'}
                    </button>
                    <button
                      className="archive-row-menu-btn"
                      aria-label="Aktionen"
                      onClick={(e) => { e.stopPropagation(); openContextMenu(e, { kind: 'projekt', data: project }) }}
                      disabled={deletingId === project.id}
                    >
                      {deletingId === project.id ? '…' : '⋯'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
        )
      })()}

      {contextMenu && (
        <div
          className="archive-context-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
          role="menu"
        >
          <button className="archive-context-item" onClick={() => beginEdit(contextMenu.entity)}>
            Bearbeiten
          </button>
          <button
            className="archive-context-item archive-context-item--danger"
            onClick={() => confirmDelete(contextMenu.entity)}
          >
            Löschen
          </button>
        </div>
      )}

      {editEntity && (
        <EditEntityModal
          entity={editEntity}
          fields={editFields}
          onFieldChange={(key, value) => setEditFields((prev) => ({ ...prev, [key]: value }))}
          onCancel={() => setEditEntity(null)}
          onSave={saveEdit}
          isSaving={isSavingEdit}
        />
      )}
    </div>
  )
}

type EditEntityModalProps = {
  entity: ArchiveEntity
  fields: Record<string, string>
  onFieldChange: (key: string, value: string) => void
  onCancel: () => void
  onSave: () => void
  isSaving: boolean
}

function EditEntityModal({ entity, fields, onFieldChange, onCancel, onSave, isSaving }: EditEntityModalProps) {
  const title = entity.kind === 'objekt'
    ? 'Objekt bearbeiten'
    : entity.kind === 'kunde'
      ? 'Kunde bearbeiten'
      : 'Projekt bearbeiten'

  const rows: Array<{ key: string; label: string; type?: string; options?: Array<[string, string]> }> = entity.kind === 'objekt'
    ? [
        { key: 'bauvorhaben', label: 'Bauvorhaben' },
        { key: 'objekt_nr', label: 'Objekt-Nr.' },
        { key: 'auftraggeber', label: 'Auftraggeber' },
        { key: 'submission_date', label: 'Submissionsdatum' },
      ]
    : entity.kind === 'kunde'
      ? [
          { key: 'name', label: 'Name' },
          { key: 'display_name', label: 'Anzeigename' },
          { key: 'email_domain', label: 'E-Mail-Domain (z. B. aicist.de)' },
        ]
      : [
          { key: 'project_name', label: 'Projektname' },
          { key: 'bauvorhaben', label: 'Bauvorhaben' },
          { key: 'submission_date', label: 'Submissionsdatum' },
          {
            key: 'anfrage_art',
            label: 'Anfrageart',
            options: [['submission', 'Submission'], ['bedarf', 'Bedarf']],
          },
        ]

  return (
    <div className="dialog-backdrop" onClick={isSaving ? undefined : onCancel}>
      <div className="dialog-box" onClick={(e) => e.stopPropagation()}>
        <h3 className="dialog-title">{title}</h3>
        <div className="dialog-email-form">
          {rows.map((row) => (
            <label key={row.key} className="dialog-field">
              <span>{row.label}</span>
              {row.options ? (
                <select
                  value={fields[row.key] ?? ''}
                  onChange={(e) => onFieldChange(row.key, e.target.value)}
                  disabled={isSaving}
                >
                  {row.options.map(([val, label]) => (
                    <option key={val} value={val}>{label}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={row.type ?? 'text'}
                  value={fields[row.key] ?? ''}
                  onChange={(e) => onFieldChange(row.key, e.target.value)}
                  disabled={isSaving}
                />
              )}
            </label>
          ))}
        </div>
        <div className="dialog-actions">
          <button className="btn btn-ghost" onClick={onCancel} disabled={isSaving}>Abbrechen</button>
          <button className="btn btn-primary" onClick={onSave} disabled={isSaving}>
            {isSaving ? 'Speichere…' : 'Speichern'}
          </button>
        </div>
      </div>
    </div>
  )
}
