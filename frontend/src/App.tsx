import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { getProjectPdfUrl } from './api'
import { AssignmentView } from './components/AssignmentView'
import { ExportConfirmDialog } from './components/ExportConfirmDialog'
import { Header } from './components/Header'
import { PositionsList } from './components/PositionsList'
import { ProgressOverlay } from './components/ProgressOverlay'
import { ProjectArchive } from './components/ProjectArchive'
import { ProjectHeader } from './components/ProjectHeader'
import { StatsBar } from './components/StatsBar'
import { SuggestionsPanel } from './components/SuggestionsPanel'
import { UploadPanel } from './components/UploadPanel'
import { useAnalysis } from './hooks/useAnalysis'
import type { AppView } from './types'

function App() {
  const analysis = useAnalysis()
  const [activeView, setActiveView] = useState<AppView>('analysis')
  const [assignmentMode, setAssignmentMode] = useState(false)
  const prevStepRef = useRef(analysis.step)

  // Auto-enter assignment mode when analysis completes
  useEffect(() => {
    if (prevStepRef.current !== 'done' && analysis.step === 'done') {
      setAssignmentMode(true)
    }
    prevStepRef.current = analysis.step
  }, [analysis.step])

  const compatibilityIssuePositionIds = useMemo(() => {
    const ids = new Set<string>()
    analysis.compatibilityIssues.forEach(issue => {
      issue.positions.forEach(id => ids.add(id))
    })
    return ids
  }, [analysis.compatibilityIssues])

  const handleLoadFromArchive = useCallback((projectId: number) => {
    setActiveView('analysis')
    analysis.handleLoadProject(projectId)
  }, [analysis.handleLoadProject])

  const hasResults = analysis.step === 'done'

  return (
    <main className="app-shell">
      <Header activeView={activeView} onViewChange={setActiveView} />

      {activeView === 'analysis' ? (
        <>
          {/* Assignment mode: focused widget-based workflow */}
          {assignmentMode && hasResults ? (
            <>
              {analysis.metadata && (
                <ProjectHeader metadata={analysis.metadata} />
              )}
              <AssignmentView
                positions={analysis.positions}
                suggestionMap={analysis.suggestionMap}
                selectedArticleIds={analysis.selectedArticleIds}
                skippedPositionIds={analysis.skippedPositionIds}
                priceAdjustments={analysis.priceAdjustments}
                onAccept={analysis.handleSuggestionSelect}
                onReject={analysis.handleRejectSuggestion}
                onManualSelect={analysis.handleManualSelect}
                onPriceAdjustmentChange={analysis.handlePriceAdjustmentChange}
                onFinish={analysis.handleExportPreview}
                onBackToOverview={() => setAssignmentMode(false)}
              />
            </>
          ) : (
            <>
              {analysis.duplicateInfo?.is_duplicate && (
                <div className="duplicate-banner">
                  Dieses LV wurde bereits
                  {analysis.duplicateInfo.created_at
                    ? ` am ${new Date(analysis.duplicateInfo.created_at).toLocaleDateString('de-DE')} `
                    : ' '}
                  analysiert. Gespeicherte Ergebnisse wurden geladen.
                </div>
              )}

              {hasResults && analysis.metadata && (
                <ProjectHeader metadata={analysis.metadata} />
              )}

              <StatsBar
                totalPositions={analysis.positions.length}
                matchedCount={analysis.matchedCount}
                selectedCount={analysis.selectedCount}
                serviceCount={analysis.serviceCount}
                estimatedTotal={analysis.estimatedTotal}
                compatibilityIssues={analysis.compatibilityIssues}
                step={analysis.step}
                onAcceptAllTop={analysis.handleAcceptAllTop}
              />

              <section className="workspace">
                <UploadPanel
                  file={analysis.file}
                  onFileChange={analysis.setFile}
                  onAnalyze={analysis.handleAnalyze}
                  onExport={analysis.handleExportPreview}
                  onReset={() => { analysis.handleReset(); setAssignmentMode(false) }}
                  onTogglePdfViewer={() => analysis.setShowPdfViewer(!analysis.showPdfViewer)}
                  customerName={analysis.customerName}
                  onCustomerNameChange={analysis.setCustomerName}
                  projectName={analysis.projectName}
                  onProjectNameChange={analysis.setProjectName}
                  step={analysis.step}
                  isExporting={analysis.isExporting}
                  selectedCount={analysis.selectedCount}
                  errorText={analysis.errorText}
                  canShowPdf={Boolean(analysis.projectId)}
                  isPdfViewerOpen={analysis.showPdfViewer}
                  metadataCustomerName={analysis.metadata?.kunde_name}
                  metadataProjectName={analysis.metadata?.bauvorhaben}
                />

                <PositionsList
                  positions={analysis.positions}
                  activePositionId={analysis.activePositionId}
                  onSelectPosition={analysis.setActivePositionId}
                  selectedArticleIds={analysis.selectedArticleIds}
                  suggestionMap={analysis.suggestionMap}
                  skippedPositionIds={analysis.skippedPositionIds}
                  onToggleSkip={analysis.handleToggleSkip}
                  compatibilityIssuePositionIds={compatibilityIssuePositionIds}
                  onEnterAssignment={hasResults ? () => setAssignmentMode(true) : undefined}
                />

                <SuggestionsPanel
                  activePosition={analysis.activePosition}
                  suggestions={analysis.activeSuggestions}
                  selectedArticleId={analysis.activePosition ? analysis.selectedArticleIds[analysis.activePosition.id] : undefined}
                  priceAdjustment={analysis.activePosition ? analysis.priceAdjustments[analysis.activePosition.id] : undefined}
                  onSelectArticle={analysis.handleSuggestionSelect}
                  onManualSelect={analysis.handleManualSelect}
                  compatibilityIssues={analysis.compatibilityIssues}
                  onParameterChange={analysis.handleParameterChange}
                  isRefreshingSuggestions={analysis.isRefreshingSuggestions}
                  onPriceAdjustmentChange={analysis.handlePriceAdjustmentChange}
                />
              </section>

              {analysis.showPdfViewer && analysis.projectId && (
                <div className="pdf-viewer-overlay">
                  <div className="pdf-viewer-header">
                    <h3>Original-LV</h3>
                    <button
                      className="modal-close"
                      onClick={() => analysis.setShowPdfViewer(false)}
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                        <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                    </button>
                  </div>
                  <iframe
                    src={getProjectPdfUrl(analysis.projectId)}
                    className="pdf-viewer-frame"
                    title="Original LV PDF"
                  />
                </div>
              )}
            </>
          )}

          <ProgressOverlay step={analysis.step} onCancel={analysis.handleCancel} />

          <ExportConfirmDialog
            isOpen={analysis.showExportDialog}
            preview={analysis.exportPreview}
            onConfirm={analysis.handleExportConfirm}
            onCancel={analysis.handleExportCancel}
            isExporting={analysis.isExporting}
          />
        </>
      ) : (
        <ProjectArchive onLoadProject={handleLoadFromArchive} />
      )}

      {analysis.toastMessage && (
        <div className="toast">
          {analysis.toastMessage}
          {analysis.undoStack.length > 0 && (
            <button className="toast-undo" onClick={analysis.handleUndo}>
              Rückgängig
            </button>
          )}
        </div>
      )}
    </main>
  )
}

export default App
