import { useCallback, useState } from 'react'
import type { AnalysisStep } from '../types'

type Props = {
  file: File | null
  onFileChange: (file: File | null) => void
  onAnalyze: () => void
  onExport: () => void
  onReset: () => void
  onTogglePdfViewer: () => void
  customerName: string
  onCustomerNameChange: (value: string) => void
  projectName: string
  onProjectNameChange: (value: string) => void
  step: AnalysisStep
  isExporting: boolean
  selectedCount: number
  errorText: string | null
  canShowPdf: boolean
  isPdfViewerOpen: boolean
  metadataCustomerName?: string | null
  metadataProjectName?: string | null
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function UploadPanel({
  file,
  onFileChange,
  onAnalyze,
  onExport,
  onReset,
  onTogglePdfViewer,
  customerName,
  onCustomerNameChange,
  projectName,
  onProjectNameChange,
  step,
  isExporting,
  selectedCount,
  errorText,
  canShowPdf,
  isPdfViewerOpen,
  metadataCustomerName,
  metadataProjectName,
}: Props) {
  const [isDragOver, setIsDragOver] = useState(false)
  const isAnalyzing = step !== 'idle' && step !== 'done' && step !== 'error'
  const hasResults = step === 'done'

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragOver(false)
      const droppedFile = e.dataTransfer.files[0]
      if (droppedFile?.type === 'application/pdf') {
        onFileChange(droppedFile)
      }
    },
    [onFileChange],
  )

  return (
    <aside className="panel upload-panel">
      <div className="panel-header">
        <div className="panel-number">1</div>
        <div>
          <h2>Upload & Steuerung</h2>
          <p className="panel-copy">LV-PDF hochladen und Analyse starten.</p>
        </div>
      </div>

      <div
        className={`file-drop-zone ${isDragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
          className="file-input-hidden"
        />
        {file ? (
          <div className="file-info">
            <div className="file-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="1.5" />
                <polyline points="14,2 14,8 20,8" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </div>
            <div>
              <span className="file-name">{file.name}</span>
              <span className="file-size">{formatSize(file.size)}</span>
            </div>
          </div>
        ) : (
          <div className="drop-placeholder">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" className="upload-icon">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>PDF hierher ziehen oder klicken</span>
          </div>
        )}
      </div>

      <button type="button" className="btn btn-primary" onClick={onAnalyze} disabled={isAnalyzing || !file}>
        {isAnalyzing ? (
          <>
            <span className="btn-spinner" />
            Analyse läuft...
          </>
        ) : (
          'LV analysieren'
        )}
      </button>

      {hasResults && (
        <button type="button" className="btn btn-ghost" onClick={onReset}>
          Neue Analyse
        </button>
      )}

      {canShowPdf && (
        <button type="button" className="btn btn-ghost" onClick={onTogglePdfViewer}>
          {isPdfViewerOpen ? 'Original schließen' : 'Original anzeigen'}
        </button>
      )}

      <div className="form-section">
        <h3>Angebotsdaten</h3>
        <label className="form-field">
          <span>
            Kunde
            {metadataCustomerName && customerName === metadataCustomerName && (
              <span className="auto-detected-hint">(automatisch erkannt)</span>
            )}
          </span>
          <input type="text" value={customerName} onChange={(e) => onCustomerNameChange(e.target.value)} placeholder="Kundenname" />
        </label>
        <label className="form-field">
          <span>
            Projekt
            {metadataProjectName && projectName === metadataProjectName && (
              <span className="auto-detected-hint">(automatisch erkannt)</span>
            )}
          </span>
          <input type="text" value={projectName} onChange={(e) => onProjectNameChange(e.target.value)} placeholder="Projektname" />
        </label>
      </div>

      <button
        type="button"
        className="btn btn-secondary"
        onClick={onExport}
        disabled={isExporting || selectedCount === 0}
      >
        {isExporting ? (
          <>
            <span className="btn-spinner" />
            Exportiere...
          </>
        ) : (
          <>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ marginRight: 6 }}>
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Angebot exportieren ({selectedCount})
          </>
        )}
      </button>

      {errorText && (
        <div className="error-banner">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
            <line x1="12" y1="8" x2="12" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="16" r="1" fill="currentColor" />
          </svg>
          <span>{errorText}</span>
        </div>
      )}
    </aside>
  )
}
