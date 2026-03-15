import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, checkCompatibility, exportOffer, fetchExportPreview, fetchProject, fetchSingleSuggestions, fetchSuggestions, parseLV, recordOverride, saveSelections } from '../api'
import type {
  AnalysisStep,
  CompatibilityIssue,
  DuplicateInfo,
  ExportPreviewResponse,
  LVPosition,
  PriceAdjustment,
  PositionSuggestions,
  ProductSearchResult,
  ProductSuggestion,
  ProjectMetadata,
  TechnicalParameters,
  UndoAction,
} from '../types'
import { computeAdjustedTotal, computeAdjustedUnitPrice, isAdjustedPrice } from '../utils/pricing'

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
  const [metadata, setMetadata] = useState<ProjectMetadata | null>(null)
  const [undoStack, setUndoStack] = useState<UndoAction[]>([])
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const [projectId, setProjectId] = useState<number | null>(null)
  const [showPdfViewer, setShowPdfViewer] = useState(false)
  const [priceAdjustments, setPriceAdjustments] = useState<Record<string, PriceAdjustment>>({})

  const abortRef = useRef<AbortController | null>(null)
  const compatTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const toastTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Auto-fill customer/project from metadata
  const metadataAppliedRef = useRef(false)

  const pushUndo = useCallback((action: UndoAction) => {
    setUndoStack(prev => [...prev.slice(-19), action])
  }, [])

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg)
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToastMessage(null), 3000)
  }, [])

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
      const position = positions.find((p) => p.id === posId)
      const adjustedUnitPrice = computeAdjustedUnitPrice(match?.price_net, priceAdjustments[posId])
      const adjustedTotal = computeAdjustedTotal(adjustedUnitPrice, position?.quantity)
      if (adjustedTotal != null) total += adjustedTotal
    }
    return total
  }, [selectedArticleIds, suggestionMap, skippedPositionIds, positions, priceAdjustments])

  const customUnitPrices = useMemo(() => {
    const prices: Record<string, number> = {}
    for (const [posId, artId] of Object.entries(selectedArticleIds)) {
      if (skippedPositionIds.has(posId)) continue
      const suggestions = suggestionMap[posId]
      const match = suggestions?.find((s) => s.artikel_id === artId)
      const adjustedUnitPrice = computeAdjustedUnitPrice(match?.price_net, priceAdjustments[posId])
      if (isAdjustedPrice(match?.price_net, adjustedUnitPrice) && adjustedUnitPrice != null) {
        prices[posId] = adjustedUnitPrice
      }
    }
    return prices
  }, [selectedArticleIds, suggestionMap, skippedPositionIds, priceAdjustments])

  const handlePriceAdjustmentChange = useCallback((positionId: string, adjustment: PriceAdjustment) => {
    setPriceAdjustments((prev) => ({ ...prev, [positionId]: adjustment }))
  }, [])

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
    setUndoStack([])
    setPriceAdjustments({})
    metadataAppliedRef.current = false

    try {
      setStep('parsing')
      const parseData = await parseLV(file, controller.signal)
      setPositions(parseData.positions)
      setActivePositionId(parseData.positions[0]?.id ?? null)
      setDuplicateInfo(parseData.duplicate ?? null)
      setMetadata(parseData.metadata ?? null)
      setProjectId(parseData.duplicate?.project_id ?? null)

      // Auto-fill from metadata
      if (parseData.metadata) {
        const m = parseData.metadata
        if (m.kunde_name && !customerName) setCustomerName(m.kunde_name)
        if (m.bauvorhaben && !projectName) setProjectName(m.bauvorhaben)
        metadataAppliedRef.current = true
      }

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
  }, [file, step, customerName, projectName])

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
      const prev = current[positionId]
      pushUndo({ type: 'select', positionId, previousArticleId: prev })
      const next = { ...current, [positionId]: artikelId }
      recheckCompatibility(positions, next)

      // Feature 6: Record override if user chose a non-top suggestion
      const posSuggestions = positionSuggestions.find(ps => ps.position_id === positionId)
      const topSuggestion = posSuggestions?.suggestions[0]
      if (topSuggestion && topSuggestion.artikel_id !== artikelId && !topSuggestion.is_override) {
        const pos = positions.find(p => p.id === positionId)
        if (pos) {
          recordOverride({
            position_description: pos.description,
            ordnungszahl: pos.ordnungszahl,
            category: pos.parameters.product_category,
            dn: pos.parameters.nominal_diameter_dn,
            material: pos.parameters.material,
            chosen_artikel_id: artikelId,
          }).catch(() => {})
        }
      }

      return next
    })
  }, [positions, positionSuggestions, recheckCompatibility, pushUndo])

  const handleManualSelect = useCallback((positionId: string, product: ProductSearchResult) => {
    const position = positions.find(p => p.id === positionId)
    const qty = position?.quantity ?? 1
    const unitPrice = product.vk_listenpreis_netto ?? null
    const totalNet = unitPrice != null ? Math.round(unitPrice * qty * 100) / 100 : null

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

    setPositionSuggestions(prev => prev.map(ps => {
      if (ps.position_id !== positionId) return ps
      const filtered = ps.suggestions.filter(s => !s.is_manual)
      return { ...ps, suggestions: [syntheticSuggestion, ...filtered] }
    }))

    setSelectedArticleIds(current => {
      const prev = current[positionId]
      pushUndo({ type: 'select', positionId, previousArticleId: prev })
      const next = { ...current, [positionId]: product.artikel_id }
      recheckCompatibility(positions, next)
      return next
    })

    // Record override
    if (position) {
      recordOverride({
        position_description: position.description,
        ordnungszahl: position.ordnungszahl,
        category: position.parameters.product_category,
        dn: position.parameters.nominal_diameter_dn,
        material: position.parameters.material,
        chosen_artikel_id: product.artikel_id,
      }).catch(() => {})
    }
  }, [positions, recheckCompatibility, pushUndo])

  const handleToggleSkip = useCallback((positionId: string) => {
    setSkippedPositionIds((prev) => {
      const next = new Set(prev)
      if (next.has(positionId)) {
        next.delete(positionId)
        pushUndo({ type: 'unskip', positionId })
      } else {
        next.add(positionId)
        pushUndo({ type: 'skip', positionId })
        showToast('Position ausgeschlossen')
      }
      return next
    })
  }, [pushUndo, showToast])

  const handleUndo = useCallback(() => {
    setUndoStack(prev => {
      if (prev.length === 0) return prev
      const action = prev[prev.length - 1]
      const rest = prev.slice(0, -1)

      switch (action.type) {
        case 'select':
          setSelectedArticleIds(current => {
            const next = { ...current }
            if (action.previousArticleId) {
              next[action.positionId] = action.previousArticleId
            } else {
              delete next[action.positionId]
            }
            recheckCompatibility(positions, next)
            return next
          })
          break
        case 'deselect':
          setSelectedArticleIds(current => {
            const next = { ...current, [action.positionId]: action.previousArticleId }
            recheckCompatibility(positions, next)
            return next
          })
          break
        case 'skip':
          setSkippedPositionIds(current => {
            const next = new Set(current)
            next.delete(action.positionId)
            return next
          })
          break
        case 'unskip':
          setSkippedPositionIds(current => {
            const next = new Set(current)
            next.add(action.positionId)
            return next
          })
          break
      }

      showToast('Rückgängig gemacht')
      return rest
    })
  }, [positions, recheckCompatibility, showToast])

  // Ctrl+Z handler
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        if (undoStack.length > 0) {
          e.preventDefault()
          handleUndo()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undoStack.length, handleUndo])

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

    const activeSelections: Record<string, string> = {}
    for (const [posId, artId] of Object.entries(selectedArticleIds)) {
      if (!skippedPositionIds.has(posId)) {
        activeSelections[posId] = artId
      }
    }

    try {
      const preview = await fetchExportPreview(positions, activeSelections, customerName, projectName, customUnitPrices)
      setExportPreview(preview)
      setShowExportDialog(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setErrorText(message)
    } finally {
      setIsExporting(false)
    }
  }, [positions, selectedArticleIds, selectedCount, customerName, projectName, skippedPositionIds, customUnitPrices])

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
      const blob = await exportOffer(positions, activeSelections, customerName, projectName, customUnitPrices)
      const url = window.URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `tiefbaux-angebot-${Date.now()}.pdf`
      anchor.click()
      window.URL.revokeObjectURL(url)

      // Feature 5: Save selections for future duplicate reuse
      if (projectId) {
        saveSelections(projectId, activeSelections).catch(() => {})
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setErrorText(message)
    } finally {
      setIsExporting(false)
    }
  }, [positions, selectedArticleIds, customerName, projectName, skippedPositionIds, isExporting, projectId, customUnitPrices])

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

  const handleLoadProject = useCallback(async (loadProjectId: number) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const timeoutId = setTimeout(() => controller.abort(), 300_000)

    setErrorText(null)
    setFile(null)
    setDuplicateInfo(null)
    setUndoStack([])
    setPriceAdjustments({})
    setStep('matching')
    metadataAppliedRef.current = false

    try {
      const { project, positions: loadedPositions, metadata: loadedMetadata, selections } = await fetchProject(loadProjectId)
      setPositions(loadedPositions)
      setActivePositionId(loadedPositions[0]?.id ?? null)
      setProjectName(project.project_name ?? '')
      setMetadata(loadedMetadata ?? null)
      setProjectId(loadProjectId)

      if (loadedMetadata) {
        if (loadedMetadata.kunde_name) setCustomerName(loadedMetadata.kunde_name)
        if (loadedMetadata.bauvorhaben && !project.project_name) setProjectName(loadedMetadata.bauvorhaben)
      }

      const autoSkipped = new Set(
        loadedPositions
          .filter((p) => p.position_type === 'dienstleistung')
          .map((p) => p.id),
      )
      setSkippedPositionIds(autoSkipped)

      const suggestionData = await fetchSuggestions(loadedPositions, controller.signal)
      setPositionSuggestions(suggestionData.suggestions)
      setCompatibilityIssues(suggestionData.compatibility_issues)

      // Feature 5: Use stored selections if available, otherwise default to top suggestions
      if (selections && Object.keys(selections).length > 0) {
        setSelectedArticleIds(selections)
      } else {
        const defaults: Record<string, string> = {}
        suggestionData.suggestions.forEach((entry) => {
          if (entry.suggestions.length > 0) {
            defaults[entry.position_id] = entry.suggestions[0].artikel_id
          }
        })
        setSelectedArticleIds(defaults)
      }
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

  const handleRejectSuggestion = useCallback((positionId: string) => {
    setSelectedArticleIds((current) => {
      const prev = current[positionId]
      if (prev) {
        pushUndo({ type: 'deselect', positionId, previousArticleId: prev })
      }
      const next = { ...current }
      delete next[positionId]
      recheckCompatibility(positions, next)
      return next
    })
  }, [positions, recheckCompatibility, pushUndo])

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
    setMetadata(null)
    setUndoStack([])
    setProjectId(null)
    setShowPdfViewer(false)
    setPriceAdjustments({})
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
    metadata,
    undoStack,
    toastMessage,
    projectId,
    showPdfViewer, setShowPdfViewer,
    priceAdjustments,
    customUnitPrices,
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
    handleUndo,
    handleRejectSuggestion,
    handlePriceAdjustmentChange,
  }
}
