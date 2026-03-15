import type { ProjectMetadata } from '../types'

type Props = {
  metadata: ProjectMetadata | null
}

export function ProjectHeader({ metadata }: Props) {
  if (!metadata) return null
  const { bauvorhaben, objekt_nr, submission_date, auftraggeber } = metadata
  const hasData = bauvorhaben || objekt_nr || submission_date || auftraggeber
  if (!hasData) return null

  return (
    <div className="project-header">
      {bauvorhaben && (
        <div className="project-header-item project-header-main">
          <span className="project-header-label">Bauvorhaben</span>
          <span className="project-header-value">{bauvorhaben}</span>
        </div>
      )}
      {objekt_nr && (
        <div className="project-header-item">
          <span className="project-header-label">Objekt-Nr.</span>
          <span className="project-header-value">{objekt_nr}</span>
        </div>
      )}
      {submission_date && (
        <div className="project-header-item">
          <span className="project-header-label">Submission</span>
          <span className="project-header-value">{submission_date}</span>
        </div>
      )}
      {auftraggeber && (
        <div className="project-header-item">
          <span className="project-header-label">Auftraggeber</span>
          <span className="project-header-value">{auftraggeber}</span>
        </div>
      )}
    </div>
  )
}
