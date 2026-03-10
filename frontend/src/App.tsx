import { useCallback, useMemo, useState } from 'react'
import './App.css'
import { ExportConfirmDialog } from './components/ExportConfirmDialog'
import { Header } from './components/Header'
import { PositionsList } from './components/PositionsList'
import { ProgressOverlay } from './components/ProgressOverlay'
import { ProjectArchive } from './components/ProjectArchive'
import { StatsBar } from './components/StatsBar'
import { SuggestionsPanel } from './components/SuggestionsPanel'
import { UploadPanel } from './components/UploadPanel'
import { useAnalysis } from './hooks/useAnalysis'
import type { AppView } from './types'

function App() {
  const analysis = useAnalysis()
  const [activeView, setActiveView] = useState<AppView>('analysis')

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

  return (
    <main className="app-shell">
      <Header activeView={activeView} onViewChange={setActiveView} />

      {activeView === 'analysis' ? (
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
              onReset={analysis.handleReset}
              customerName={analysis.customerName}
              onCustomerNameChange={analysis.setCustomerName}
              projectName={analysis.projectName}
              onProjectNameChange={analysis.setProjectName}
              step={analysis.step}
              isExporting={analysis.isExporting}
              selectedCount={analysis.selectedCount}
              errorText={analysis.errorText}
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
            />

            <SuggestionsPanel
              activePosition={analysis.activePosition}
              suggestions={analysis.activeSuggestions}
              selectedArticleId={analysis.activePosition ? analysis.selectedArticleIds[analysis.activePosition.id] : undefined}
              onSelectArticle={analysis.handleSuggestionSelect}
              onManualSelect={analysis.handleManualSelect}
              compatibilityIssues={analysis.compatibilityIssues}
              onParameterChange={analysis.handleParameterChange}
              isRefreshingSuggestions={analysis.isRefreshingSuggestions}
            />
          </section>

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
    </main>
  )
}

export default App
