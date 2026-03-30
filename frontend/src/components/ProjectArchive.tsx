import { useCallback, useEffect, useState } from 'react'
import { deleteProject, fetchProjects } from '../api'
import type { ProjectSummary } from '../types'

type Props = {
  onLoadProject: (projectId: number) => void
}

function statusLabel(status?: string): string {
  if (status === 'gerechnet') return 'Gerechnet'
  if (status === 'anfrage_offen') return 'Anfrage offen'
  if (status === 'offen') return 'Offen'
  return 'Neu'
}

export function ProjectArchive({ onLoadProject }: Props) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [searchTerm, setSearchTerm] = useState('')

  const loadProjects = useCallback(async (q?: string) => {
    try {
      const data = await fetchProjects(q || undefined)
      setProjects(data)
    } catch {
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProjects()
  }, [loadProjects])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjects(searchTerm)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchTerm, loadProjects])

  const handleDelete = useCallback(async (project: ProjectSummary) => {
    const name = project.bauvorhaben ?? project.filename ?? project.project_name ?? `Projekt #${project.id}`
    if (!window.confirm(`"${name}" wirklich löschen?`)) return

    setDeletingId(project.id)
    try {
      await deleteProject(project.id)
      setProjects((prev) => prev.filter((p) => p.id !== project.id))
    } catch {
      // keep in list on error
    } finally {
      setDeletingId(null)
    }
  }, [])

  if (loading) {
    return (
      <div className="archive-container">
        <p className="archive-empty">Projekte werden geladen...</p>
      </div>
    )
  }

  return (
    <div className="archive-container">
      <div className="archive-header">
        <h2>Projektarchiv</h2>
        <span className="archive-count">{projects.length} Projekt{projects.length !== 1 ? 'e' : ''}</span>
      </div>

      <div className="archive-search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="search-icon">
          <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
          <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <input
          type="text"
          placeholder="Projekte suchen (Name, Bauvorhaben, Kunde, Objektnr.)..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      {projects.length === 0 ? (
        <p className="archive-empty">
          {searchTerm ? 'Keine Projekte gefunden.' : 'Noch keine Projekte im Archiv.'}
        </p>
      ) : (
        <div className="archive-list">
          {projects.map((project) => (
            <div key={project.id} className="archive-row">
              <div className="archive-main">
                <div className="archive-title-row">
                  {project.projekt_nr && (
                    <span className="archive-objnr">{project.projekt_nr}</span>
                  )}
                  <span className={`archive-status archive-status-${project.status ?? 'neu'}`}>
                    {statusLabel(project.status)}
                  </span>
                  <span className="archive-filename">
                    {project.bauvorhaben ?? project.filename ?? 'Unbenannt'}
                  </span>
                </div>
                <div className="archive-meta-row">
                  {project.kunde_name && (
                    <span className="archive-kunde">{project.kunde_name}</span>
                  )}
                  {project.submission_date && (
                    <span className="archive-submission">Submission: {project.submission_date}</span>
                  )}
                  <span className="archive-date">
                    {new Date(project.created_at).toLocaleDateString('de-DE', {
                      day: '2-digit',
                      month: '2-digit',
                      year: 'numeric',
                    })}
                  </span>
                </div>
                {(project.assigned_user_name || project.last_editor_name) && (
                  <div className="archive-user-row">
                    {project.assigned_user_name && (
                      <span className="archive-assigned">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" stroke="currentColor" strokeWidth="2" />
                          <circle cx="12" cy="7" r="4" stroke="currentColor" strokeWidth="2" />
                        </svg>
                        Zugewiesen: {project.assigned_user_name}
                      </span>
                    )}
                    {project.last_editor_name && (
                      <span className="archive-editor">
                        Zuletzt: {project.last_editor_name}
                        {project.last_edited_at && (
                          <>, {new Date(project.last_edited_at).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' })}</>
                        )}
                      </span>
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
                <button
                  className="btn-archive-load"
                  onClick={() => onLoadProject(project.id)}
                >
                  {project.status === 'gerechnet' ? 'Projekt ansehen' : 'Analyse laden'}
                </button>
                <button
                  className="btn-archive-delete"
                  onClick={() => handleDelete(project)}
                  disabled={deletingId === project.id}
                >
                  {deletingId === project.id ? '...' : 'Löschen'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
