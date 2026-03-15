import { useCallback, useEffect, useState } from 'react'
import { deleteProject, fetchProjects, getProjectPdfUrl } from '../api'
import type { ProjectSummary } from '../types'

type Props = {
  onLoadProject: (projectId: number) => void
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
                  {project.objekt_nr && (
                    <span className="archive-objnr">{project.objekt_nr}</span>
                  )}
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
                  Analyse laden
                </button>
                <a
                  className="btn-archive-pdf"
                  href={getProjectPdfUrl(project.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Original-LV anzeigen"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="1.5" />
                    <polyline points="14,2 14,8 20,8" stroke="currentColor" strokeWidth="1.5" />
                  </svg>
                  LV
                </a>
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
