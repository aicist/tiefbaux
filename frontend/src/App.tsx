import { Component, useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { getProjectPdfUrl } from './api'
import { AdminPanel } from './components/AdminPanel'
import { AssignmentView } from './components/AssignmentView'
import { ExportConfirmDialog } from './components/ExportConfirmDialog'
import { Header } from './components/Header'
import { InquiryPanel } from './components/InquiryPanel'
import { LoginScreen } from './components/LoginScreen'
import { PositionsList } from './components/PositionsList'
import { ProgressOverlay } from './components/ProgressOverlay'
import { ProjectArchive } from './components/ProjectArchive'
import { ProjectOverview } from './components/ProjectOverview'
import { TenderRadar } from './components/TenderRadar'
import { ProjectHeader } from './components/ProjectHeader'
import { StatsBar } from './components/StatsBar'
import { SuggestionsPanel } from './components/SuggestionsPanel'
import { UploadPanel } from './components/UploadPanel'
import { useAnalysis } from './hooks/useAnalysis'
import { useAuth } from './hooks/useAuth'
import type { AppView, User } from './types'
import { primaryAssignmentKey } from './utils/assignmentKeys'
import { buildEmbeddedPdfViewerUrl } from './utils/pdfViewer'

type ErrorBoundaryProps = { children: React.ReactNode }
type ErrorBoundaryState = { error: Error | null }

class AppErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error): void {
    // Keep console output for debugging runtime crashes in development.
    console.error('Runtime error in app shell:', error)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="app-error-screen">
          <div className="app-error-card">
            <h2>Frontend-Fehler</h2>
            <p>Die Seite konnte nicht korrekt gerendert werden.</p>
            <pre>{this.state.error.message}</pre>
            <button
              className="btn btn-primary"
              onClick={() => window.location.reload()}
            >
              Seite neu laden
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function AuthenticatedApp({ user, isAdmin, onLogout }: { user: User; isAdmin: boolean; onLogout: () => void }) {
  const analysis = useAnalysis()
  const [activeView, setActiveView] = useState<AppView>('analysis')
  const [assignmentMode, setAssignmentMode] = useState(false)
  const prevStepRef = useRef(analysis.step)

  // Auto-enter assignment mode when analysis completes (not for read-only)
  useEffect(() => {
    if (prevStepRef.current !== 'done' && analysis.step === 'done' && !analysis.isReadOnly) {
      setAssignmentMode(true)
    }
    prevStepRef.current = analysis.step
  }, [analysis.step, analysis.isReadOnly])

  const handleLoadFromArchive = useCallback((projectId: number) => {
    setActiveView('analysis')
    analysis.handleLoadProject(projectId)
  }, [analysis.handleLoadProject])

  const handleEditPosition = useCallback((positionId: string) => {
    analysis.handleAssignmentUiStateChange({ ...analysis.assignmentUiState, current_position_id: positionId })
    setAssignmentMode(true)
  }, [analysis.assignmentUiState, analysis.handleAssignmentUiStateChange])

  const hasResults = analysis.step === 'done'
  const projectPdfViewerUrl = analysis.projectId
    ? buildEmbeddedPdfViewerUrl(getProjectPdfUrl(analysis.projectId), { page: 1 })
    : null

  return (
    <main className="app-shell">
      <Header
        activeView={activeView}
        onViewChange={setActiveView}
        user={user}
        onLogout={onLogout}
      />

      {activeView === 'analysis' ? (
        <>
          {/* Read-only mode for completed projects */}
          {analysis.isReadOnly && hasResults && analysis.projectId ? (
            <ProjectOverview
              metadata={analysis.metadata}
              projectId={analysis.projectId}
              projectName={analysis.projectName}
              projectStatus={analysis.projectUserInfo.status}
              offerPdfPath={analysis.projectUserInfo.offer_pdf_path}
              positions={analysis.positions}
              onBack={() => { analysis.handleReset(); setAssignmentMode(false); setActiveView('archive') }}
              lastEditorName={analysis.projectUserInfo.last_editor_name}
              lastEditedAt={analysis.projectUserInfo.last_edited_at}
              assignedUserName={analysis.projectUserInfo.assigned_user_name}
              suggestionMap={analysis.suggestionMap}
              selectedArticleIds={analysis.selectedArticleIds}
              decisions={analysis.positionDecisions}
            />
          ) : assignmentMode && hasResults ? (
            <>
              {analysis.metadata && (
                <ProjectHeader metadata={analysis.metadata} />
              )}
              <AssignmentView
                positions={analysis.positions}
                suggestionMap={analysis.suggestionMap}
                selectedArticleIds={analysis.selectedArticleIds}
                decisions={analysis.positionDecisions}
                onDecisionChange={analysis.handleSetPositionDecision}
                priceAdjustments={analysis.priceAdjustments}
                categoryAdjustments={analysis.categoryAdjustments}
                onAccept={analysis.handleSuggestionSelect}
                onSilentSelect={analysis.handleSilentSelect}
                onReject={analysis.handleRejectSuggestion}
                onManualSelect={analysis.handleManualSelect}
                onAddArticle={analysis.handleAddArticle}
                onRemoveArticle={analysis.handleRemoveArticle}
                onPriceAdjustmentChange={analysis.handlePriceAdjustmentChange}
                onFinish={analysis.handleExportPreview}
                onBackToOverview={() => setAssignmentMode(false)}
                projectId={analysis.projectId}
                projectName={analysis.projectName}
                alternativeFlags={analysis.alternativeFlags}
                onToggleAlternative={analysis.handleToggleAlternative}
                supplierOpenFlags={analysis.supplierOpenFlags}
                onToggleSupplierOpen={analysis.handleToggleSupplierOpen}
                positionSuggestions={analysis.positionSuggestions}
                componentSelections={analysis.componentSelections}
                onComponentSelect={analysis.handleComponentSelect}
                onComponentManualSelect={analysis.handleComponentManualSelect}
                persistedUiState={analysis.assignmentUiState}
                onUiStateChange={analysis.handleAssignmentUiStateChange}
                onRefreshInquiries={analysis.handleRefreshInquiries}
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
                  positionDecisions={analysis.positionDecisions}
                  pendingInquiryPositionIds={analysis.pendingInquiryPositionIds}
                  componentSelections={analysis.componentSelections}
                  suggestionMap={analysis.suggestionMap}
                  positionSuggestions={analysis.positionSuggestions}
                  onEnterAssignment={hasResults ? () => setAssignmentMode(true) : undefined}
                  showAssignmentDetails={hasResults && Boolean(analysis.projectId)}
                  inquiries={analysis.inquiries}
                  onEditPosition={hasResults ? handleEditPosition : undefined}
                />

                {analysis.projectId ? (
                  <InquiryPanel
                    inquiries={analysis.inquiries}
                    positions={analysis.positions}
                    projectId={analysis.projectId}
                    onRefreshInquiries={analysis.handleRefreshInquiries}
                    onEditPosition={handleEditPosition}
                  />
                ) : (
                  <SuggestionsPanel
                    activePosition={analysis.activePosition}
                    suggestions={analysis.activeSuggestions}
                    componentSuggestions={analysis.activePosition ? analysis.positionSuggestions.find((ps) => ps.position_id === analysis.activePosition?.id)?.component_suggestions ?? null : null}
                    selectedArticleIds={analysis.activePosition ? analysis.selectedArticleIds[analysis.activePosition.id] ?? [] : []}
                    priceAdjustment={analysis.activePosition ? analysis.priceAdjustments[primaryAssignmentKey(analysis.activePosition.id)] : undefined}
                    onSelectArticle={analysis.handleSuggestionSelect}
                    onManualSelect={analysis.handleManualSelect}
                    onParameterChange={analysis.handleParameterChange}
                    isRefreshingSuggestions={analysis.isRefreshingSuggestions}
                    onPriceAdjustmentChange={analysis.handlePriceAdjustmentChange}
                    projectId={analysis.projectId}
                    projectName={analysis.projectName}
                  />
                )}
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
                    src={projectPdfViewerUrl ?? getProjectPdfUrl(analysis.projectId)}
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
      ) : activeView === 'radar' ? (
        <TenderRadar />
      ) : activeView === 'admin' && isAdmin ? (
        <AdminPanel />
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

function App() {
  const auth = useAuth()

  return (
    <AppErrorBoundary>
      {auth.isLoading ? (
        <div className="app-loading">
          <div className="spinner" />
          <div className="app-loading-text">Anwendung wird geladen...</div>
        </div>
      ) : !auth.user ? (
        <LoginScreen onLogin={auth.login} />
      ) : (
        <AuthenticatedApp
          key={auth.user.id}
          user={auth.user}
          isAdmin={auth.isAdmin}
          onLogout={auth.logout}
        />
      )}
    </AppErrorBoundary>
  )
}

export default App
