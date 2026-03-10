import { useCallback, useMemo, useRef, useState } from 'react'
import { ApiError, checkCompatibility, exportOffer, fetchExportPreview, fetchProject, fetchSingleSuggestions, fetchSuggestions, parseLV } from '../api'
import type {
  AnalysisStep,
  CompatibilityIssue,
  DuplicateInfo,
  ExportPreviewResponse,
  LVPosition,
  PositionSuggestions,
  ProductSearchResult,
  ProductSuggestion,
  TechnicalParameters,
} from '../types'

export function useAnalysis() {
  const [file, setFile] = useState<File | null>(null)
  const [positions, setPositions] = useState<LVPosition[]>([])
  const [positionSuggestions, setPositionSuggestions] = useState<PositionSuggestions[]>([])
  const [selectedArticleIds, setSelectedArticleIds] = useState<Record<string, string>>({})
  const [compatibilityIssues, setCompatibilityIssues] = useState<CompatibilityIssue[]>([])
  const [activePositionId, setActivePositionId] = useState<string | null>(null)
  const [customerName, setCustomerName] = useState('')
  const [projectName, setProjectName] = useState('')
  const [step, setStep] = useState<AnalysisStep>('idle')
  const [errorText, setErrorText] = useState<string | null>(null)
  const [isExporting, setIsExporting] = useState(false)
  const [skippedPositionIds, setSkippedPositionIds] = useState<Set<string>>(new Set())
  const [exportPreview, setExportPreview] = useState<ExportPreviewResponse | null>(null)
  const [showExportDialog, setShowExportDialog] = useState(false)
  const [isRefreshingSuggestions, setIsRefreshingSuggestions] = useState(false)
  const [duplicateInfo, setDuplicateInfo] = useState<DuplicateInfo | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const compatTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const suggestionMap = useMemo(() => {
    const map: Record<string, ProductSuggestion[]> = {}
    positionSuggestions.forEach((entry) => {
      map[entry.position_id] = entry.suggestions
    })
    return map
  }, [positionSuggestions])

  const activePosition = useMemo(
    () => positions.find((p) => p.id === activePositionId) ?? null,
    [positions, activePositionId],
  )

  const activeSuggestions = activePosition ? suggestionMap[activePosition.id] ?? [] : []

  const selectedCount = useMemo(() => Object.keys(selectedArticleIds).length, [selectedArticleIds])

  const matchedCount = useMemo(() => {
    return positionSuggestions.filter((ps) => ps.suggestions.length > 0).length
  }, [positionSuggestions])

  const serviceCount = useMemo(() => skippedPositionIds.size, [skippedPositionIds])

  const estimatedTotal = useMemo(() => {
    let total = 0
    for (const [posId, artId] of Object.entries(selectedArticleIds)) {
      if (skippedPositionIds.has(posId)) continue
      const suggestions = suggestionMap[posId]
      if (!suggestions) continue
      const match = suggestions.find((s) => s.artikel_id === artId)
      if (match?.total_net) total += match.total_net
    }
    return total
  }, [selectedArticleIds, suggestionMap, skippedPositionIds])

  const handleAnalyze = useCallback(async () => {
    if (!file) {
      setErrorText('Bitte zuerst ein LV-PDF auswählen.')
      return
    }
    if (step === 'parsing' || step === 'matching' || step === 'uploading') return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const timeoutId = setTimeout(() => controller.abort(), 300_000)

    setErrorText(null)
    setStep('uploading')

    try {
      setStep('parsing')
      const parseData = await parseLV(file, controller.signal)
      setPositions(parseData.positions)
      setActivePositionId(parseData.positions[0]?.id ?? null)
      setDuplicateInfo(parseData.duplicate ?? null)

      // Auto-skip positions the LLM classified as service
      const autoSkipped = new Set(
        parseData.positions
          .filter((p) => p.position_type === 'dienstleistung')
          .map((p) => p.id),
      )
      setSkippedPositionIds(autoSkipped)

      setStep('matching')
      const suggestionData = await fetchSuggestions(parseData.positions, controller.signal)
      setPositionSuggestions(suggestionData.suggestions)
      setCompatibilityIssues(suggestionData.compatibility_issues)

      const defaults: Record<string, string> = {}
      suggestionData.suggestions.forEach((entry) => {
        if (entry.suggestions.length > 0) {
          defaults[entry.position_id] = entry.suggestions[0].artikel_id
        }
      })
      setSelectedArticleIds(defaults)
      setStep('done')
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setErrorText('Analyse wurde abgebrochen.')
      } else if (error instanceof ApiError) {
        setErrorText(error.message)
      } else {
        const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
        setErrorText(message)
      }
      setStep('error')
    } finally {
      clearTimeout(timeoutId)
    }
  }, [file, step])

  const handleCancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const recheckCompatibility = useCallback((
    positionsToCheck: LVPosition[],
    selections: Record<string, string>,
  ) => {
    if (compatTimerRef.current) clearTimeout(compatTimerRef.current)
    compatTimerRef.current = setTimeout(async () => {
      try {
        const issues = await checkCompatibility(positionsToCheck, selections)
        setCompatibilityIssues(issues)
      } catch {
        // keep current issues on error
      }
    }, 500)
  }, [])

  const handleSuggestionSelect = useCallback((positionId: string, artikelId: string) => {
    setSelectedArticleIds((current) => {
      const next = { ...current, [positionId]: artikelId }
      recheckCompatibility(positions, next)
      return next
    })
  }, [positions, recheckCompatibility])

  const handleManualSelect = useCallback((positionId: string, product: ProductSearchResult) => {
    // Find position to calculate total price
    const position = positions.find(p => p.id === positionId)
    const qty = position?.quantity ?? 1
    const unitPrice = product.vk_listenpreis_netto ?? null
    const totalNet = unitPrice != null ? Math.round(unitPrice * qty * 100) / 100 : null

    // Create a synthetic ProductSuggestion from the search result
    const syntheticSuggestion: ProductSuggestion = {
      artikel_id: product.artikel_id,
      artikelname: product.artikelname,
      hersteller: product.hersteller ?? null,
      category: product.kategorie ?? null,
      subcategory: null,
      dn: product.nennweite_dn ?? null,
      load_class: product.belastungsklasse ?? null,
      norm: null,
      stock: product.lager_gesamt ?? null,
      delivery_days: null,
      price_net: unitPrice,
      total_net: totalNet,
      currency: product.waehrung ?? 'EUR',
      score: 0,
      reasons: ['Manuell gewählt'],
      warnings: [],
      score_breakdown: [],
      is_manual: true,
    }

    // Inject into positionSuggestions (prepend so it appears first)
    setPositionSuggestions(prev => prev.map(ps => {
      if (ps.position_id !== positionId) return ps
      // Remove any previous manual selection, then prepend
      const filtered = ps.suggestions.filter(s => !s.is_manual)
      return { ...ps, suggestions: [syntheticSuggestion, ...filtered] }
    }))

    // Select this article
    setSelectedArticleIds(current => {
      const next = { ...current, [positionId]: product.artikel_id }
      recheckCompatibility(positions, next)
      return next
    })
  }, [positions, recheckCompatibility])

  const handleToggleSkip = useCallback((positionId: string) => {
    setSkippedPositionIds((prev) => {
      const next = new Set(prev)
      if (next.has(positionId)) {
        next.delete(positionId)
      } else {
        next.add(positionId)
      }
      return next
    })
  }, [])

  const handleParameterChange = useCallback(async (positionId: string, paramUpdates: Partial<TechnicalParameters>) => {
    const updatedPositions = positions.map((p) => {
      if (p.id !== positionId) return p
      return { ...p, parameters: { ...p.parameters, ...paramUpdates } }
    })
    setPositions(updatedPositions)

    const updatedPosition = updatedPositions.find((p) => p.id === positionId)
    if (!updatedPosition) return

    setIsRefreshingSuggestions(true)
    try {
      const result = await fetchSingleSuggestions(updatedPosition)
      setPositionSuggestions((prev) =>
        prev.map((ps) => (ps.position_id === positionId ? result : ps)),
      )
      if (result.suggestions.length > 0) {
        setSelectedArticleIds((prev) => {
          const next = { ...prev, [positionId]: result.suggestions[0].artikel_id }
          recheckCompatibility(updatedPositions, next)
          return next
        })
      } else {
        setSelectedArticleIds((prev) => {
          const next = { ...prev }
          delete next[positionId]
          recheckCompatibility(updatedPositions, next)
          return next
        })
      }
    } catch {
      // keep edited parameters even if suggestion refresh fails
    } finally {
      setIsRefreshingSuggestions(false)
    }
  }, [positions, recheckCompatibility])

  const handleExportPreview = useCallback(async () => {
    if (positions.length === 0 || selectedCount === 0) {
      setErrorText('Bitte zuerst eine Analyse durchführen und Artikel auswählen.')
      return
    }

    setIsExporting(true)
    setErrorText(null)

    // Filter out skipped positions from selection
    const activeSelections: Record<string, string> = {}
    for (const [posId, artId] of Object.entries(selectedArticleIds)) {
      if (!skippedPositionIds.has(posId)) {
        activeSelections[posId] = artId
      }
    }

    try {
      const preview = await fetchExportPreview(positions, activeSelections, customerName, projectName)
      setExportPreview(preview)
      setShowExportDialog(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setErrorText(message)
    } finally {
      setIsExporting(false)
    }
  }, [positions, selectedArticleIds, selectedCount, customerName, projectName, skippedPositionIds])

  const handleExportConfirm = useCallback(async () => {
    if (isExporting) return
    setShowExportDialog(false)
    setIsExporting(true)
    setErrorText(null)

    const activeSelections: Record<string, string> = {}
    for (const [posId, artId] of Object.entries(selectedArticleIds)) {
      if (!skippedPositionIds.has(posId)) {
        activeSelections[posId] = artId
      }
    }

    try {
      const blob = await exportOffer(positions, activeSelections, customerName, projectName)
      const url = window.URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `tiefbaux-angebot-${Date.now()}.pdf`
      anchor.click()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setErrorText(message)
    } finally {
      setIsExporting(false)
    }
  }, [positions, selectedArticleIds, customerName, projectName, skippedPositionIds, isExporting])

  const handleExportCancel = useCallback(() => {
    setShowExportDialog(false)
  }, [])

  const handleAcceptAllTop = useCallback(() => {
    const defaults: Record<string, string> = {}
    positionSuggestions.forEach((entry) => {
      if (entry.suggestions.length > 0 && !skippedPositionIds.has(entry.position_id)) {
        defaults[entry.position_id] = entry.suggestions[0].artikel_id
      }
    })
    setSelectedArticleIds(defaults)
    recheckCompatibility(positions, defaults)
  }, [positionSuggestions, skippedPositionIds, positions, recheckCompatibility])

  const handleLoadProject = useCallback(async (projectId: number) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const timeoutId = setTimeout(() => controller.abort(), 300_000)

    setErrorText(null)
    setFile(null)
    setDuplicateInfo(null)
    setStep('matching')

    try {
      const { project, positions: loadedPositions } = await fetchProject(projectId)
      setPositions(loadedPositions)
      setActivePositionId(loadedPositions[0]?.id ?? null)
      setProjectName(project.project_name ?? '')

      const autoSkipped = new Set(
        loadedPositions
          .filter((p) => p.position_type === 'dienstleistung')
          .map((p) => p.id),
      )
      setSkippedPositionIds(autoSkipped)

      const suggestionData = await fetchSuggestions(loadedPositions, controller.signal)
      setPositionSuggestions(suggestionData.suggestions)
      setCompatibilityIssues(suggestionData.compatibility_issues)

      const defaults: Record<string, string> = {}
      suggestionData.suggestions.forEach((entry) => {
        if (entry.suggestions.length > 0) {
          defaults[entry.position_id] = entry.suggestions[0].artikel_id
        }
      })
      setSelectedArticleIds(defaults)
      setStep('done')
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setErrorText('Laden wurde abgebrochen.')
      } else if (error instanceof ApiError) {
        setErrorText(error.message)
      } else {
        setErrorText(error instanceof Error ? error.message : 'Unbekannter Fehler')
      }
      setStep('error')
    } finally {
      clearTimeout(timeoutId)
    }
  }, [])

  const handleReset = useCallback(() => {
    abortRef.current?.abort()
    setFile(null)
    setPositions([])
    setPositionSuggestions([])
    setSelectedArticleIds({})
    setCompatibilityIssues([])
    setActivePositionId(null)
    setSkippedPositionIds(new Set())
    setExportPreview(null)
    setShowExportDialog(false)
    setDuplicateInfo(null)
    setStep('idle')
    setErrorText(null)
  }, [])

  return {
    file, setFile,
    positions,
    positionSuggestions,
    selectedArticleIds,
    compatibilityIssues,
    activePositionId, setActivePositionId,
    activePosition,
    activeSuggestions,
    customerName, setCustomerName,
    projectName, setProjectName,
    step,
    errorText,
    isExporting,
    selectedCount,
    matchedCount,
    serviceCount,
    estimatedTotal,
    suggestionMap,
    skippedPositionIds,
    isRefreshingSuggestions,
    duplicateInfo,
    showExportDialog,
    exportPreview,
    handleAnalyze,
    handleCancel,
    handleSuggestionSelect,
    handleManualSelect,
    handleToggleSkip,
    handleParameterChange,
    handleExportPreview,
    handleExportConfirm,
    handleExportCancel,
    handleLoadProject,
    handleReset,
    handleAcceptAllTop,
  }
}
