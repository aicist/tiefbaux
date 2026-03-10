import { useCallback, useEffect, useState } from 'react'
import { deleteProject, fetchProjects } from '../api'
import type { ProjectSummary } from '../types'

type Props = {
  onLoadProject: (projectId: number) => void
}

export function ProjectArchive({ onLoadProject }: Props) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setLoading(false))
  }, [])

  const handleDelete = useCallback(async (project: ProjectSummary) => {
    const name = project.filename ?? project.project_name ?? `Projekt #${project.id}`
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

      {projects.length === 0 ? (
        <p className="archive-empty">Noch keine Projekte im Archiv.</p>
      ) : (
        <div className="archive-list">
          {projects.map((project) => (
            <div key={project.id} className="archive-row">
              <div className="archive-filename">
                {project.filename ?? 'Unbenannt'}
              </div>
              <div className="archive-date">
                {new Date(project.created_at).toLocaleDateString('de-DE', {
                  day: '2-digit',
                  month: '2-digit',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
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
                  Laden
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
