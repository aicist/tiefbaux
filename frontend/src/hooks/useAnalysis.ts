import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, cleanupOpenInquiriesForPosition, exportOffer, fetchExportPreview, fetchInquiries, fetchOfferPdfPreview, fetchProject, fetchSingleSuggestions, fetchSuggestions, parseLV, recordOverride, saveSelections, saveWorkstate, sendOfferEmail } from '../api'
import type {
  AssignmentUiState,
  AnalysisStep,
  DuplicateInfo,
  ExportPreviewResponse,
  LVPosition,
  PriceAdjustment,
  PositionSuggestions,
  ProductSearchResult,
  ProductSuggestion,
  ProjectMetadata,
  SupplierInquiry,
  ScoreBreakdown,
  TechnicalParameters,
  UndoAction,
} from '../types'
import { computeAdjustedTotal, computeAdjustedUnitPrice, isAdjustedPrice, resolveEffectivePriceAdjustment } from '../utils/pricing'
import { additionalAssignmentKey, componentAssignmentKey, componentSelectionKey, primaryAssignmentKey } from '../utils/assignmentKeys'

function normalizeText(value?: string | null): string {
  return (value ?? '').trim().toLowerCase()
}

const DEFAULT_ASSIGNMENT_UI_STATE: AssignmentUiState = {
  active_filter: 'alle',
  current_position_id: null,
  is_finished: false,
}

function buildManualComparison(
  position: LVPosition | undefined,
  product: ProductSearchResult,
  mode: 'manual' | 'additional',
): {
  reasons: string[]
  warnings: string[]
  scoreBreakdown: ScoreBreakdown[]
} {
  const reasons: string[] = [mode === 'manual' ? 'Manuell gewählt' : 'Zusatzartikel']
  const warnings: string[] = []
  const scoreBreakdown: ScoreBreakdown[] = []

  if (!position) return { reasons, warnings, scoreBreakdown }

  const params = position.parameters
  const productCategory = normalizeText(product.kategorie)
  const requiredCategory = normalizeText(params.product_category)
  if (requiredCategory && productCategory) {
    const match = productCategory === requiredCategory || productCategory.includes(requiredCategory) || requiredCategory.includes(productCategory)
    reasons.push(match ? `Kategorie passt (${product.kategorie})` : `Kategorie abweichend (${product.kategorie} ≠ ${params.product_category})`)
    scoreBreakdown.push({
      component: 'Kategorie',
      points: match ? 10 : -10,
      detail: match ? 'Kategorie entspricht der LV-Position' : 'Kategorie weicht von der LV-Position ab',
    })
  }

  if (params.nominal_diameter_dn != null && product.nennweite_dn != null) {
    const match = params.nominal_diameter_dn === product.nennweite_dn
    reasons.push(match ? `DN ${product.nennweite_dn} passt` : `DN abweichend (${product.nennweite_dn} ≠ ${params.nominal_diameter_dn})`)
    scoreBreakdown.push({
      component: 'DN',
      points: match ? 12 : -15,
      detail: match ? 'Nennweite stimmt überein' : 'Nennweite weicht ab',
    })
  }

  if (params.load_class && product.belastungsklasse) {
    const match = normalizeText(params.load_class) === normalizeText(product.belastungsklasse)
    reasons.push(match ? `Belastungsklasse passt (${product.belastungsklasse})` : `Belastungsklasse abweichend (${product.belastungsklasse} ≠ ${params.load_class})`)
    scoreBreakdown.push({
      component: 'Belastung',
      points: match ? 10 : -12,
      detail: match ? 'Belastungsklasse stimmt überein' : 'Belastungsklasse weicht ab',
    })
  }

  if (params.material && product.werkstoff) {
    const requiredMaterial = normalizeText(params.material)
    const actualMaterial = normalizeText(product.werkstoff)
    const match = actualMaterial.includes(requiredMaterial) || requiredMaterial.includes(actualMaterial)
    reasons.push(match ? `Werkstoff passt (${product.werkstoff})` : `Werkstoff abweichend (${product.werkstoff} ≠ ${params.material})`)
    scoreBreakdown.push({
      component: 'Werkstoff',
      points: match ? 8 : -10,
      detail: match ? 'Werkstoff entspricht der LV-Position' : 'Werkstoff weicht ab',
    })
  }

  if (params.norm && product.norm_primaer) {
    const match = normalizeText(product.norm_primaer).includes(normalizeText(params.norm))
    reasons.push(match ? `Norm passt (${product.norm_primaer})` : `Norm abweichend (${product.norm_primaer} ≠ ${params.norm})`)
    scoreBreakdown.push({
      component: 'Norm',
      points: match ? 8 : -10,
      detail: match ? 'Norm stimmt überein' : 'Norm weicht ab',
    })
  }

  if (params.stiffness_class_sn != null) {
    const productSn = product.steifigkeitsklasse_sn != null ? parseFloat(String(product.steifigkeitsklasse_sn)) : null
    if (productSn == null) {
      warnings.push(`Keine SN-Angabe (SN${params.stiffness_class_sn} gefordert)`)
      scoreBreakdown.push({
        component: 'SN',
        points: -8,
        detail: 'Produkt hat keine auswertbare SN-Angabe',
      })
    } else {
      const match = productSn >= params.stiffness_class_sn
      reasons.push(match ? `SN${productSn} erfüllt SN${params.stiffness_class_sn}` : `SN${productSn} unter SN${params.stiffness_class_sn}`)
      scoreBreakdown.push({
        component: 'SN',
        points: match ? 10 : -15,
        detail: match ? 'Ringsteifigkeit erfüllt die Anforderung' : 'Ringsteifigkeit liegt unter der Anforderung',
      })
    }
  }

  return { reasons, warnings, scoreBreakdown }
}

export function useAnalysis() {
  const [file, setFile] = useState<File | null>(null)
  const [positions, setPositions] = useState<LVPosition[]>([])
  const [positionSuggestions, setPositionSuggestions] = useState<PositionSuggestions[]>([])
  const [selectedArticleIds, setSelectedArticleIds] = useState<Record<string, string[]>>({})
  const [activePositionId, setActivePositionId] = useState<string | null>(null)
  const [customerName, setCustomerName] = useState('')
  const [projectName, setProjectName] = useState('')
  const [step, setStep] = useState<AnalysisStep>('idle')
  const [errorText, setErrorText] = useState<string | null>(null)
  const [isExporting, setIsExporting] = useState(false)
  const [exportPreview, setExportPreview] = useState<ExportPreviewResponse | null>(null)
  const [showExportDialog, setShowExportDialog] = useState(false)
  const [isSendingOfferEmail, setIsSendingOfferEmail] = useState(false)
  const [sendOfferResult, setSendOfferResult] = useState<{ kind: 'success' | 'error'; message: string } | null>(null)
  const [isPreviewingOfferPdf, setIsPreviewingOfferPdf] = useState(false)
  const [isRefreshingSuggestions, setIsRefreshingSuggestions] = useState(false)
  const [duplicateInfo, setDuplicateInfo] = useState<DuplicateInfo | null>(null)
  const [metadata, setMetadata] = useState<ProjectMetadata | null>(null)
  const [undoStack, setUndoStack] = useState<UndoAction[]>([])
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const [projectId, setProjectId] = useState<number | null>(null)
  const [showPdfViewer, setShowPdfViewer] = useState(false)
  const [priceAdjustments, setPriceAdjustments] = useState<Record<string, PriceAdjustment>>({})
  const [categoryAdjustments, setCategoryAdjustments] = useState<Record<string, PriceAdjustment>>({})
  const [alternativeFlags, setAlternativeFlags] = useState<Record<string, boolean>>({})
  const [supplierOpenFlags, setSupplierOpenFlags] = useState<Record<string, boolean>>({})
  // Component selections: key = `${positionId}::${componentName}`, value = artikel_id
  const [componentSelections, setComponentSelections] = useState<Record<string, string>>({})
  const [positionDecisions, setPositionDecisions] = useState<Record<string, 'accepted' | 'rejected' | 'inquiry_pending'>>({})
  const [assignmentUiState, setAssignmentUiState] = useState<AssignmentUiState>(DEFAULT_ASSIGNMENT_UI_STATE)
  const [isReadOnly, setIsReadOnly] = useState(false)
  const [pendingInquiryPositionIds, setPendingInquiryPositionIds] = useState<string[]>([])
  const [inquiries, setInquiries] = useState<SupplierInquiry[]>([])
  const [projectUserInfo, setProjectUserInfo] = useState<{
    assigned_user_name?: string | null
    last_editor_name?: string | null
    last_edited_at?: string | null
    status?: string | null
    offer_pdf_path?: string | null
  }>({})


  const abortRef = useRef<AbortController | null>(null)
  const toastTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const workstateSignatureRef = useRef<string>('')

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

  const handleRefreshInquiries = useCallback(async (targetProjectId?: number | null) => {
    const effectiveProjectId = targetProjectId ?? projectId
    if (!effectiveProjectId) {
      setInquiries([])
      setPendingInquiryPositionIds([])
      return
    }

    try {
      const loadedInquiries = await fetchInquiries(effectiveProjectId)
      setInquiries(loadedInquiries)
      const pendingPositionIds = new Set(
        loadedInquiries
          .filter((inq) => inq.status === 'offen' || inq.status === 'angefragt')
          .map((inq) => inq.position_id)
          .filter((id): id is string => Boolean(id)),
      )
      setPendingInquiryPositionIds(Array.from(pendingPositionIds))
    } catch {
      setInquiries([])
      setPendingInquiryPositionIds([])
    }
  }, [projectId])

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

  const selectedCount = useMemo(() => {
    const regularCount = Object.values(selectedArticleIds).filter(ids => ids.length > 0).length
    // Count positions that have component selections but no regular selection
    const componentPositionIds = new Set<string>()
    for (const key of Object.keys(componentSelections)) {
      const [posId] = key.split('::')
      if (!selectedArticleIds[posId]?.length) componentPositionIds.add(posId)
    }
    return regularCount + componentPositionIds.size
  }, [selectedArticleIds, componentSelections])

  const matchedCount = useMemo(() => {
    return positionSuggestions.filter((ps) =>
      ps.suggestions.length > 0 ||
      (ps.component_suggestions?.some((cs) => cs.suggestions.length > 0) ?? false),
    ).length
  }, [positionSuggestions])

  const serviceCount = useMemo(() =>
    positions.filter(p => p.position_type === 'dienstleistung').length,
    [positions]
  )

  const estimatedTotal = useMemo(() => {
    let total = 0
    for (const [posId, artIds] of Object.entries(selectedArticleIds)) {
      const position = positions.find((p) => p.id === posId)
      if (position?.position_type === 'dienstleistung') continue
      const suggestions = suggestionMap[posId]
      if (!suggestions) continue
      const primaryMatch = suggestions.find((s) => s.artikel_id === artIds[0])
      const primaryAdjustment =
        priceAdjustments[primaryAssignmentKey(posId)] ?? categoryAdjustments[primaryMatch?.category ?? '']
      for (let i = 0; i < artIds.length; i++) {
        const match = suggestions.find((s) => s.artikel_id === artIds[i])
        const assignmentKey = i === 0 ? primaryAssignmentKey(posId) : additionalAssignmentKey(posId, artIds[i])
        const effectiveAdjustment = i === 0
          ? primaryAdjustment
          : resolveEffectivePriceAdjustment(priceAdjustments[assignmentKey], primaryAdjustment, primaryMatch?.price_net)
        const unitPrice = computeAdjustedUnitPrice(match?.price_net, effectiveAdjustment)
        const artTotal = computeAdjustedTotal(unitPrice, position?.quantity)
        if (artTotal != null) total += artTotal
      }
    }
    for (const [selectionKey, artikelId] of Object.entries(componentSelections)) {
      const [positionId, componentName] = selectionKey.split('::')
      const position = positions.find((p) => p.id === positionId)
      if (position?.position_type === 'dienstleistung') continue
      const entry = positionSuggestions.find((ps) => ps.position_id === positionId)
      const component = entry?.component_suggestions?.find((cs) => cs.component_name === componentName)
      const suggestion = component?.suggestions.find((s) => s.artikel_id === artikelId)
      const unitPrice = computeAdjustedUnitPrice(
        suggestion?.price_net,
        priceAdjustments[componentAssignmentKey(positionId, componentName)],
      )
      const componentTotal = computeAdjustedTotal(unitPrice, position?.quantity)
      if (componentTotal != null) total += componentTotal
    }
    return total
  }, [selectedArticleIds, suggestionMap, positions, priceAdjustments, categoryAdjustments, componentSelections, positionSuggestions])

  const customUnitPrices = useMemo(() => {
    const prices: Record<string, number> = {}
    for (const [posId, artIds] of Object.entries(selectedArticleIds)) {
      const position = positions.find(p => p.id === posId)
      if (position?.position_type === 'dienstleistung' || artIds.length === 0) continue
      const suggestions = suggestionMap[posId]
      const primaryKey = primaryAssignmentKey(posId)
      const match = suggestions?.find((s) => s.artikel_id === artIds[0])
      const adjustedUnitPrice = computeAdjustedUnitPrice(
        match?.price_net,
        priceAdjustments[primaryKey] ?? categoryAdjustments[match?.category ?? ''],
      )
      if (isAdjustedPrice(match?.price_net, adjustedUnitPrice) && adjustedUnitPrice != null) {
        prices[primaryKey] = adjustedUnitPrice
      }

      const primaryAdjustment =
        priceAdjustments[primaryKey] ?? categoryAdjustments[match?.category ?? '']
      for (const artikelId of artIds.slice(1)) {
        const assignmentKey = additionalAssignmentKey(posId, artikelId)
        const article = suggestions?.find((s) => s.artikel_id === artikelId)
        const effectiveAdjustment = resolveEffectivePriceAdjustment(
          priceAdjustments[assignmentKey],
          primaryAdjustment,
          match?.price_net,
        )
        const articleAdjustedUnitPrice = computeAdjustedUnitPrice(article?.price_net, effectiveAdjustment)
        if (isAdjustedPrice(article?.price_net, articleAdjustedUnitPrice) && articleAdjustedUnitPrice != null) {
          prices[assignmentKey] = articleAdjustedUnitPrice
        }
      }
    }

    for (const [selectionKey, artikelId] of Object.entries(componentSelections)) {
      const [positionId, componentName] = selectionKey.split('::')
      const position = positions.find((p) => p.id === positionId)
      if (position?.position_type === 'dienstleistung') continue
      const entry = positionSuggestions.find((ps) => ps.position_id === positionId)
      const component = entry?.component_suggestions?.find((cs) => cs.component_name === componentName)
      const suggestion = component?.suggestions.find((s) => s.artikel_id === artikelId)
      const assignmentKey = componentAssignmentKey(positionId, componentName)
      const adjustedUnitPrice = computeAdjustedUnitPrice(suggestion?.price_net, priceAdjustments[assignmentKey])
      if (isAdjustedPrice(suggestion?.price_net, adjustedUnitPrice) && adjustedUnitPrice != null) {
        prices[assignmentKey] = adjustedUnitPrice
      }
    }

    return prices
  }, [selectedArticleIds, suggestionMap, positions, priceAdjustments, categoryAdjustments, componentSelections, positionSuggestions])

  const handlePriceAdjustmentChange = useCallback((assignmentKey: string, adjustment: PriceAdjustment) => {
    setPriceAdjustments((prev) => ({ ...prev, [assignmentKey]: adjustment }))
    // Remember adjustment per product category for auto-fill
    if (assignmentKey.endsWith('::primary')) {
      const positionId = assignmentKey.replace(/::primary$/, '')
      const posSuggestions = positionSuggestions.find(ps => ps.position_id === positionId)
      const primaryCategory = posSuggestions?.suggestions[0]?.category
      if (primaryCategory) {
        setCategoryAdjustments(prev => ({ ...prev, [primaryCategory]: adjustment }))
      }
    }
  }, [positionSuggestions])

  const handleToggleAlternative = useCallback((assignmentKey: string) => {
    setAlternativeFlags(prev => ({
      ...prev,
      [assignmentKey]: !prev[assignmentKey],
    }))
  }, [])

  const handleToggleSupplierOpen = useCallback((assignmentKey: string) => {
    setSupplierOpenFlags(prev => ({
      ...prev,
      [assignmentKey]: !prev[assignmentKey],
    }))
  }, [])

  const handleComponentSelect = useCallback((positionId: string, componentName: string, artikelId: string) => {
    const key = componentSelectionKey(positionId, componentName)
    setComponentSelections(prev => ({ ...prev, [key]: artikelId }))
  }, [])

  /** Auto-detect if a product deviates from position requirements */
  const autoDetectAlternative = useCallback((assignmentKey: string, positionId: string, suggestion: ProductSuggestion) => {
    const position = positions.find(p => p.id === positionId)
    if (!position) return

    const reqDn = position.parameters.nominal_diameter_dn
    const reqSn = position.parameters.stiffness_class_sn

    let isDeviation = false
    if (reqDn != null && suggestion.dn != null && reqDn !== suggestion.dn) isDeviation = true
    if (reqSn != null && suggestion.sn != null && suggestion.sn < reqSn) isDeviation = true

    if (isDeviation) {
      setAlternativeFlags(prev => ({
        ...prev,
        [assignmentKey]: true,
      }))
      showToast('Als Alternative zur bauseitigen Prüfung markiert')
    }
  }, [positions, showToast])

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
    setCategoryAdjustments({})
    setSupplierOpenFlags({})
    setComponentSelections({})
    setPositionDecisions({})
    setAssignmentUiState(DEFAULT_ASSIGNMENT_UI_STATE)
    workstateSignatureRef.current = ''
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

      setStep('matching')
      const suggestionData = await fetchSuggestions(parseData.positions, controller.signal, projectId)
      setPositionSuggestions(suggestionData.suggestions)

      const defaults: Record<string, string[]> = {}
      const compDefaults: Record<string, string> = {}
      suggestionData.suggestions.forEach((entry) => {
        if (entry.suggestions.length > 0) {
          const fallbackIds = entry.suggestions.filter((s) => s.is_bogen_fallback).map((s) => s.artikel_id)
          defaults[entry.position_id] = fallbackIds.length > 0 ? fallbackIds : [entry.suggestions[0].artikel_id]
        }
        if (entry.component_suggestions) {
          for (const cs of entry.component_suggestions) {
            if (cs.suggestions.length > 0) {
              compDefaults[componentSelectionKey(entry.position_id, cs.component_name)] = cs.suggestions[0].artikel_id
            }
          }
        }
      })
      setSelectedArticleIds(defaults)
      setComponentSelections(compDefaults)
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

  // Silent select — used by carousel swiping / auto-select. No undo, no override recording.
  const handleSilentSelect = useCallback((positionId: string, artikelId: string) => {
    setSelectedArticleIds((current) => {
      const prev = current[positionId] ?? []
      if (prev[0] === artikelId) return current
      const additionalArticles = prev.slice(1).filter(id => id !== artikelId)
      return { ...current, [positionId]: [artikelId, ...additionalArticles] }
    })
  }, [])

  const handleSuggestionSelect = useCallback((positionId: string, artikelId: string) => {
    setSelectedArticleIds((current) => {
      const prev = current[positionId]
      pushUndo({ type: 'select', positionId, previousArticleIds: prev })
      // Replace primary article (index 0) but keep additional articles (index 1+)
      const additionalArticles = (prev ?? []).slice(1).filter(id => id !== artikelId)
      const next = { ...current, [positionId]: [artikelId, ...additionalArticles] }

      // Record override if user chose a non-top suggestion
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
  }, [positions, positionSuggestions, pushUndo])

  const handleManualSelect = useCallback((positionId: string, product: ProductSearchResult) => {
    const position = positions.find(p => p.id === positionId)
    const qty = position?.quantity ?? 1
    const unitPrice = product.vk_listenpreis_netto ?? null
    const totalNet = unitPrice != null ? Math.round(unitPrice * qty * 100) / 100 : null
    const manualComparison = buildManualComparison(position, product, 'manual')

    const syntheticSuggestion: ProductSuggestion = {
      artikel_id: product.artikel_id,
      artikelname: product.artikelname,
      hersteller: product.hersteller ?? null,
      category: product.kategorie ?? null,
      subcategory: null,
      dn: product.nennweite_dn ?? null,
      sn: product.steifigkeitsklasse_sn != null ? parseFloat(String(product.steifigkeitsklasse_sn)) || null : null,
      load_class: product.belastungsklasse ?? null,
      norm: product.norm_primaer ?? null,
      stock: product.lager_gesamt ?? null,
      delivery_days: null,
      price_net: unitPrice,
      total_net: totalNet,
      currency: product.waehrung ?? 'EUR',
      score: 0,
      reasons: manualComparison.reasons,
      warnings: manualComparison.warnings,
      score_breakdown: manualComparison.scoreBreakdown,
      is_manual: true,
    }

    setPositionSuggestions(prev => {
      const hasEntry = prev.some(ps => ps.position_id === positionId)
      if (!hasEntry) {
        return [...prev, {
          position_id: positionId,
          ordnungszahl: position?.ordnungszahl ?? '',
          description: position?.description ?? '',
          suggestions: [syntheticSuggestion],
        }]
      }
      return prev.map(ps => {
        if (ps.position_id !== positionId) return ps
        const filtered = ps.suggestions.filter(s => !s.is_manual)
        return { ...ps, suggestions: [syntheticSuggestion, ...filtered] }
      })
    })

    setSelectedArticleIds(current => {
      const prev = current[positionId]
      pushUndo({ type: 'select', positionId, previousArticleIds: prev })
      const next = { ...current, [positionId]: [product.artikel_id] }
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

    // Auto-detect alternative
    autoDetectAlternative(primaryAssignmentKey(positionId), positionId, syntheticSuggestion)
  }, [positions, pushUndo, autoDetectAlternative])

  const handleAddArticle = useCallback((positionId: string, product: ProductSearchResult) => {
    const position = positions.find(p => p.id === positionId)
    const qty = position?.quantity ?? 1
    const unitPrice = product.vk_listenpreis_netto ?? null
    const totalNet = unitPrice != null ? Math.round(unitPrice * qty * 100) / 100 : null
    const manualComparison = buildManualComparison(position, product, 'additional')

    const syntheticSuggestion: ProductSuggestion = {
      artikel_id: product.artikel_id,
      artikelname: product.artikelname,
      hersteller: product.hersteller ?? null,
      category: product.kategorie ?? null,
      subcategory: null,
      dn: product.nennweite_dn ?? null,
      sn: product.steifigkeitsklasse_sn != null ? parseFloat(String(product.steifigkeitsklasse_sn)) || null : null,
      load_class: product.belastungsklasse ?? null,
      norm: product.norm_primaer ?? null,
      stock: product.lager_gesamt ?? null,
      delivery_days: null,
      price_net: unitPrice,
      total_net: totalNet,
      currency: product.waehrung ?? 'EUR',
      score: 0,
      reasons: manualComparison.reasons,
      warnings: manualComparison.warnings,
      score_breakdown: manualComparison.scoreBreakdown,
      is_manual: true,
    }

    setPositionSuggestions(prev => {
      const hasEntry = prev.some(ps => ps.position_id === positionId)
      if (!hasEntry) {
        // Position has no suggestions entry yet — create one
        return [...prev, {
          position_id: positionId,
          ordnungszahl: position?.ordnungszahl ?? '',
          description: position?.description ?? '',
          suggestions: [syntheticSuggestion],
        }]
      }
      return prev.map(ps => {
        if (ps.position_id !== positionId) return ps
        // Only add if not already in suggestions
        if (ps.suggestions.some(s => s.artikel_id === product.artikel_id)) return ps
        return { ...ps, suggestions: [...ps.suggestions, syntheticSuggestion] }
      })
    })

    setSelectedArticleIds(current => {
      const prev = current[positionId] ?? []
      if (prev.includes(product.artikel_id)) return current
      pushUndo({ type: 'select', positionId, previousArticleIds: prev })
      const next = { ...current, [positionId]: [...prev, product.artikel_id] }
      return next
    })

    showToast('Zusatzartikel hinzugefügt')
  }, [positions, pushUndo, showToast])

  const handleRemoveArticle = useCallback((positionId: string, artikelId: string) => {
    setSelectedArticleIds(current => {
      const prev = current[positionId] ?? []
      pushUndo({ type: 'select', positionId, previousArticleIds: prev })
      const next = { ...current, [positionId]: prev.filter(id => id !== artikelId) }
      if (next[positionId].length === 0) delete next[positionId]
      return next
    })
  }, [positions, pushUndo])

  const handleUndo = useCallback(() => {
    setUndoStack(prev => {
      if (prev.length === 0) return prev
      const action = prev[prev.length - 1]
      const rest = prev.slice(0, -1)

      switch (action.type) {
        case 'select':
          setSelectedArticleIds(current => {
            const next = { ...current }
            if (action.previousArticleIds && action.previousArticleIds.length > 0) {
              next[action.positionId] = action.previousArticleIds
            } else {
              delete next[action.positionId]
            }
            return next
          })
          break
        case 'deselect':
          setSelectedArticleIds(current => {
            const next = { ...current, [action.positionId]: action.previousArticleIds }
            return next
          })
          break
      }

      showToast('Rückgängig gemacht')
      return rest
    })
  }, [positions, showToast])

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
          const next = { ...prev, [positionId]: [result.suggestions[0].artikel_id] }
          return next
        })
      } else {
        setSelectedArticleIds((prev) => {
          const next = { ...prev }
          delete next[positionId]
          return next
        })
      }
    } catch {
      // keep edited parameters even if suggestion refresh fails
    } finally {
      setIsRefreshingSuggestions(false)
    }
  }, [positions])

  const handleComponentManualSelect = useCallback((positionId: string, componentName: string, product: ProductSearchResult) => {
    const position = positions.find((p) => p.id === positionId)
    const qty = position?.quantity ?? 1
    const unitPrice = product.vk_listenpreis_netto ?? null
    const totalNet = unitPrice != null ? Math.round(unitPrice * qty * 100) / 100 : null
    const manualComparison = buildManualComparison(position, product, 'manual')

    const syntheticSuggestion: ProductSuggestion = {
      artikel_id: product.artikel_id,
      artikelname: product.artikelname,
      hersteller: product.hersteller ?? null,
      category: product.kategorie ?? null,
      subcategory: null,
      dn: product.nennweite_dn ?? null,
      sn: product.steifigkeitsklasse_sn != null ? parseFloat(String(product.steifigkeitsklasse_sn)) || null : null,
      load_class: product.belastungsklasse ?? null,
      norm: product.norm_primaer ?? null,
      stock: product.lager_gesamt ?? null,
      delivery_days: null,
      price_net: unitPrice,
      total_net: totalNet,
      currency: product.waehrung ?? 'EUR',
      score: 0,
      reasons: manualComparison.reasons,
      warnings: manualComparison.warnings,
      score_breakdown: manualComparison.scoreBreakdown,
      is_manual: true,
    }

    setPositionSuggestions(prev => prev.map((ps) => {
      if (ps.position_id !== positionId || !ps.component_suggestions) return ps
      return {
        ...ps,
        component_suggestions: ps.component_suggestions.map((cs) => {
          if (cs.component_name !== componentName) return cs
          const filtered = cs.suggestions.filter((s) => !s.is_manual || s.artikel_id !== product.artikel_id)
          return { ...cs, suggestions: [syntheticSuggestion, ...filtered] }
        }),
      }
    }))

    setComponentSelections(prev => ({
      ...prev,
      [componentSelectionKey(positionId, componentName)]: product.artikel_id,
    }))
  }, [positions])

  const handleSetPositionDecision = useCallback((positionId: string, decision?: 'accepted' | 'rejected' | 'inquiry_pending') => {
    if ((decision === 'accepted' || decision === 'rejected') && projectId) {
      cleanupOpenInquiriesForPosition(projectId, positionId)
        .then(() => handleRefreshInquiries(projectId))
        .catch(() => {})
    } else if (decision === 'inquiry_pending' && projectId) {
      handleRefreshInquiries(projectId)
        .catch(() => {})
    }

    setPositionDecisions((current) => {
      if (decision) {
        if (current[positionId] === decision) return current
        return { ...current, [positionId]: decision }
      }
      if (!(positionId in current)) return current
      const next = { ...current }
      delete next[positionId]
      return next
    })
  }, [projectId, handleRefreshInquiries])

  const handleAssignmentUiStateChange = useCallback((nextState: AssignmentUiState) => {
    setAssignmentUiState((current) => {
      const normalized: AssignmentUiState = {
        active_filter: nextState.active_filter ?? 'alle',
        current_position_id: nextState.current_position_id ?? null,
        is_finished: Boolean(nextState.is_finished),
      }
      if (
        current.active_filter === normalized.active_filter
        && current.current_position_id === normalized.current_position_id
        && Boolean(current.is_finished) === normalized.is_finished
      ) {
        return current
      }
      return normalized
    })
  }, [])

  /** Build active selections including component selections for multi-component positions */
  const buildActiveSelections = useCallback(() => {
    const dlPositionIds = new Set(positions.filter(p => p.position_type === 'dienstleistung').map(p => p.id))
    const activeSelections: Record<string, string[]> = {}
    const assignmentKeysByPosition: Record<string, string[]> = {}
    for (const [posId, artIds] of Object.entries(selectedArticleIds)) {
      if (!dlPositionIds.has(posId) && artIds.length > 0) {
        activeSelections[posId] = [...artIds]
        assignmentKeysByPosition[posId] = [primaryAssignmentKey(posId), ...artIds.slice(1).map((artikelId) => additionalAssignmentKey(posId, artikelId))]
      }
    }
    // Merge component selections: each component article remains its own assignment entry.
    for (const [key, artikelId] of Object.entries(componentSelections)) {
      const [posId, componentName] = key.split('::')
      if (dlPositionIds.has(posId)) continue
      if (!activeSelections[posId]) activeSelections[posId] = []
      if (!assignmentKeysByPosition[posId]) assignmentKeysByPosition[posId] = []
      activeSelections[posId].push(artikelId)
      assignmentKeysByPosition[posId].push(componentAssignmentKey(posId, componentName))
    }
    return { selectedArticleIds: activeSelections, assignmentKeysByPosition }
  }, [selectedArticleIds, positions, componentSelections])

  const handleExportPreview = useCallback(async () => {
    if (positions.length === 0 || selectedCount === 0) {
      setErrorText('Bitte zuerst eine Analyse durchführen und Artikel auswählen.')
      return
    }

    setIsExporting(true)
    setErrorText(null)

    const activeSelections = buildActiveSelections()
    const rejectedPositionIds = Object.entries(positionDecisions)
      .filter(([, decision]) => decision === 'rejected')
      .map(([posId]) => posId)

    try {
      const preview = await fetchExportPreview(
        positions,
        activeSelections.selectedArticleIds,
        customerName,
        projectName,
        customUnitPrices,
        alternativeFlags,
        supplierOpenFlags,
        activeSelections.assignmentKeysByPosition,
        rejectedPositionIds,
      )
      setExportPreview(preview)
      setSendOfferResult(null)
      setShowExportDialog(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setErrorText(message)
    } finally {
      setIsExporting(false)
    }
  }, [positions, selectedCount, customerName, projectName, customUnitPrices, alternativeFlags, supplierOpenFlags, buildActiveSelections, positionDecisions])

  const handleExportConfirm = useCallback(async () => {
    if (isExporting) return
    setShowExportDialog(false)
    setIsExporting(true)
    setErrorText(null)

    const activeSelections = buildActiveSelections()
    const rejectedPositionIds = Object.entries(positionDecisions)
      .filter(([, decision]) => decision === 'rejected')
      .map(([posId]) => posId)

    try {
      const blob = await exportOffer(
        positions,
        activeSelections.selectedArticleIds,
        customerName,
        projectName,
        customUnitPrices,
        alternativeFlags,
        supplierOpenFlags,
        activeSelections.assignmentKeysByPosition,
        projectId,
        rejectedPositionIds,
      )
      const url = window.URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `tiefbaux-angebot-${Date.now()}.pdf`
      anchor.click()
      window.URL.revokeObjectURL(url)

      // Feature 5: Save selections for future duplicate reuse
      if (projectId) {
        saveSelections(projectId, activeSelections.selectedArticleIds).catch(() => {})
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setErrorText(message)
    } finally {
      setIsExporting(false)
    }
  }, [positions, customerName, projectName, isExporting, projectId, customUnitPrices, alternativeFlags, supplierOpenFlags, buildActiveSelections, positionDecisions])

  const handleExportCancel = useCallback(() => {
    setShowExportDialog(false)
    setSendOfferResult(null)
  }, [])

  const handlePreviewOfferPdf = useCallback(async () => {
    if (isPreviewingOfferPdf) return
    setIsPreviewingOfferPdf(true)
    const activeSelections = buildActiveSelections()
    const rejectedPositionIds = Object.entries(positionDecisions)
      .filter(([, decision]) => decision === 'rejected')
      .map(([posId]) => posId)
    try {
      const blob = await fetchOfferPdfPreview(
        positions,
        activeSelections.selectedArticleIds,
        customerName,
        projectName,
        customUnitPrices,
        alternativeFlags,
        supplierOpenFlags,
        activeSelections.assignmentKeysByPosition,
        projectId,
        rejectedPositionIds,
      )
      const url = window.URL.createObjectURL(blob)
      const newWin = window.open(url, '_blank', 'noopener')
      // Revoke after the new tab has had a chance to load; fall back to 60s.
      window.setTimeout(() => window.URL.revokeObjectURL(url), 60_000)
      if (!newWin) {
        setSendOfferResult({ kind: 'error', message: 'Popup-Blocker hat die Vorschau verhindert. Bitte Pop-ups erlauben.' })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'PDF-Vorschau fehlgeschlagen'
      setSendOfferResult({ kind: 'error', message })
    } finally {
      setIsPreviewingOfferPdf(false)
    }
  }, [
    isPreviewingOfferPdf,
    positions,
    customerName,
    projectName,
    customUnitPrices,
    alternativeFlags,
    supplierOpenFlags,
    projectId,
    buildActiveSelections,
    positionDecisions,
  ])

  const handleSendOfferEmail = useCallback(async (payload: { customerEmail: string; subject: string; body: string }) => {
    if (isSendingOfferEmail) return
    setIsSendingOfferEmail(true)
    setSendOfferResult(null)

    const activeSelections = buildActiveSelections()
    const rejectedPositionIds = Object.entries(positionDecisions)
      .filter(([, decision]) => decision === 'rejected')
      .map(([posId]) => posId)

    try {
      const result = await sendOfferEmail(
        positions,
        activeSelections.selectedArticleIds,
        customerName,
        projectName,
        payload.customerEmail,
        payload.subject,
        payload.body,
        customUnitPrices,
        alternativeFlags,
        supplierOpenFlags,
        activeSelections.assignmentKeysByPosition,
        projectId,
        rejectedPositionIds,
      )
      setSendOfferResult({
        kind: result.sent ? 'success' : 'error',
        message: result.detail ?? (result.sent ? 'E-Mail versendet.' : 'E-Mail konnte nicht versendet werden.'),
      })
      if (projectId && result.saved) {
        saveSelections(projectId, activeSelections.selectedArticleIds).catch(() => {})
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unbekannter Fehler'
      setSendOfferResult({ kind: 'error', message })
    } finally {
      setIsSendingOfferEmail(false)
    }
  }, [
    isSendingOfferEmail,
    positions,
    customerName,
    projectName,
    customUnitPrices,
    alternativeFlags,
    supplierOpenFlags,
    projectId,
    buildActiveSelections,
    positionDecisions,
  ])

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
    setCategoryAdjustments({})
    setSupplierOpenFlags({})
    setComponentSelections({})
    setPositionDecisions({})
    setAssignmentUiState(DEFAULT_ASSIGNMENT_UI_STATE)
    setIsReadOnly(false)
    setPendingInquiryPositionIds([])
    setStep('matching')
    metadataAppliedRef.current = false

    try {
      const {
        project,
        positions: loadedPositions,
        metadata: loadedMetadata,
        selections,
        decisions,
        component_selections: storedComponentSelections,
        ui_state: storedUiState,
      } = await fetchProject(loadProjectId)
      setPositions(loadedPositions)
      setActivePositionId(loadedPositions[0]?.id ?? null)
      setProjectName(project.project_name ?? '')
      setMetadata(loadedMetadata ?? null)
      setProjectId(loadProjectId)

      if (loadedMetadata) {
        if (loadedMetadata.kunde_name) setCustomerName(loadedMetadata.kunde_name)
        if (loadedMetadata.bauvorhaben && !project.project_name) setProjectName(loadedMetadata.bauvorhaben)
      }

      setProjectUserInfo({
        assigned_user_name: project.assigned_user_name,
        last_editor_name: project.last_editor_name,
        last_edited_at: project.last_edited_at,
        status: project.status,
        offer_pdf_path: project.offer_pdf_path,
      })

      if (loadProjectId) {
        handleRefreshInquiries(loadProjectId)
      }

      // Read-only mode only for completed projects.
      if (project.status === 'gerechnet') {
        setIsReadOnly(true)
        const restoredSelections = selections && Object.keys(selections).length > 0 ? selections : {}
        const restoredComponentSelections = storedComponentSelections ?? {}
        const restoredDecisions = decisions ?? {}
        setSelectedArticleIds(restoredSelections)
        setComponentSelections(restoredComponentSelections)
        setPositionDecisions(restoredDecisions)
        setAssignmentUiState({
          active_filter: storedUiState?.active_filter ?? 'alle',
          current_position_id: storedUiState?.current_position_id ?? null,
          is_finished: Boolean(storedUiState?.is_finished),
        })
        workstateSignatureRef.current = JSON.stringify({
          selected_article_ids: restoredSelections,
          decisions: restoredDecisions,
          component_selections: restoredComponentSelections,
          ui_state: {
            active_filter: storedUiState?.active_filter ?? 'alle',
            current_position_id: storedUiState?.current_position_id ?? null,
            is_finished: Boolean(storedUiState?.is_finished),
          },
        })
        setStep('done')
        return
      }

      const suggestionData = await fetchSuggestions(loadedPositions, controller.signal, loadProjectId)
      setPositionSuggestions(suggestionData.suggestions)

      // Auto-default component selections
      const compDefaults: Record<string, string> = {}
      suggestionData.suggestions.forEach((entry) => {
        if (entry.component_suggestions) {
          for (const cs of entry.component_suggestions) {
            if (cs.suggestions.length > 0) {
              compDefaults[componentSelectionKey(entry.position_id, cs.component_name)] = cs.suggestions[0].artikel_id
            }
          }
        }
      })
      const hasStoredSelections = Boolean(selections && Object.keys(selections).length > 0)
      const hasStoredComponentSelections = Boolean(storedComponentSelections && Object.keys(storedComponentSelections).length > 0)

      // Build default selections from suggestions (first suggestion per position)
      const freshDefaults: Record<string, string[]> = {}
      suggestionData.suggestions.forEach((entry) => {
        if (entry.suggestions.length > 0) {
          const fallbackIds = entry.suggestions.filter((s) => s.is_bogen_fallback).map((s) => s.artikel_id)
          freshDefaults[entry.position_id] = fallbackIds.length > 0 ? fallbackIds : [entry.suggestions[0].artikel_id]
        }
      })

      const restoredSelections = hasStoredSelections
        ? (() => {
          const merged = { ...(selections as Record<string, string[]>) }
          // Inject new supplier offer suggestions that weren't in the stored selections.
          // When a supplier offer comes in after the user already saved selections,
          // the offer article (SO-*) replaces the stored catalog selection so the
          // user sees the actual offer with the correct price.
          suggestionData.suggestions.forEach((entry) => {
            const offerSugg = entry.suggestions.find((s) => s.is_supplier_offer)
            if (!offerSugg) return
            const current = merged[entry.position_id]
            if (!current || !current.includes(offerSugg.artikel_id)) {
              merged[entry.position_id] = [offerSugg.artikel_id, ...(current ?? []).filter((id) => id !== offerSugg.artikel_id)]
            }
          })
          // Bogen-Fallback: Wenn für eine Bogen-Position ohne Gradzahl keine
          // explizite Nutzerauswahl außerhalb der Fallback-Gruppe existiert,
          // alle 15°/30°/45°-Varianten als Zusatzartikel vorauswählen. Das
          // deckt leere Auswahlen, Legacy-Defaults und veraltete Auswahlen
          // aus früheren Matcher-Läufen mit ab.
          suggestionData.suggestions.forEach((entry) => {
            const fallbackIds = entry.suggestions.filter((s) => s.is_bogen_fallback).map((s) => s.artikel_id)
            if (fallbackIds.length === 0) return
            const fallbackSet = new Set(fallbackIds)
            const validIds = new Set(entry.suggestions.map((s) => s.artikel_id))
            const current = merged[entry.position_id] ?? []
            const userPickedOutside = current.some((id) => validIds.has(id) && !fallbackSet.has(id))
            if (!userPickedOutside) {
              merged[entry.position_id] = fallbackIds
            }
          })
          // Drop stored selections that are no longer offered by the matcher — they
          // went stale (scoring rule changed, product removed, etc). Fall back to
          // the fresh top suggestion so the UI shows a valid proposal.
          suggestionData.suggestions.forEach((entry) => {
            const current = merged[entry.position_id]
            if (!current || current.length === 0) return
            const validIds = new Set(entry.suggestions.map((s) => s.artikel_id))
            if (validIds.size === 0) return
            const stillValid = current.filter((id) => validIds.has(id))
            if (stillValid.length === 0) {
              merged[entry.position_id] = freshDefaults[entry.position_id] ?? []
            } else if (stillValid.length !== current.length) {
              merged[entry.position_id] = stillValid
            }
          })
          return merged
        })()
        : freshDefaults
      const restoredComponentSelections = hasStoredComponentSelections
        ? (storedComponentSelections as Record<string, string>)
        : compDefaults

      const restoredDecisions = decisions && Object.keys(decisions).length > 0
        ? decisions
        : ((hasStoredSelections || hasStoredComponentSelections) ? (() => {
          const compatibleFallback: Record<string, 'accepted' | 'rejected' | 'inquiry_pending'> = {}
          Object.entries(restoredSelections).forEach(([positionId, ids]) => {
            if (ids.length > 0) compatibleFallback[positionId] = 'accepted'
          })
          Object.keys(restoredComponentSelections).forEach((selectionKey) => {
            const [positionId] = selectionKey.split('::')
            if (!compatibleFallback[positionId]) compatibleFallback[positionId] = 'accepted'
          })
          return compatibleFallback
        })() : {})

      setSelectedArticleIds(restoredSelections)
      setComponentSelections(restoredComponentSelections)
      setPositionDecisions(restoredDecisions)
      const normalizedUiState: AssignmentUiState = {
        active_filter: storedUiState?.active_filter ?? 'alle',
        current_position_id: storedUiState?.current_position_id ?? null,
        is_finished: Boolean(storedUiState?.is_finished),
      }
      setAssignmentUiState(normalizedUiState)
      workstateSignatureRef.current = JSON.stringify({
        selected_article_ids: restoredSelections,
        decisions: restoredDecisions,
        component_selections: restoredComponentSelections,
        ui_state: normalizedUiState,
      })
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
  }, [handleRefreshInquiries])

  const handleRejectSuggestion = useCallback((positionId: string) => {
    setSelectedArticleIds((current) => {
      const prev = current[positionId]
      if (prev && prev.length > 0) {
        pushUndo({ type: 'deselect', positionId, previousArticleIds: prev })
      }
      const next = { ...current }
      delete next[positionId]
      return next
    })
  }, [pushUndo])

  const handleReset = useCallback(() => {
    abortRef.current?.abort()
    setFile(null)
    setPositions([])
    setPositionSuggestions([])
    setSelectedArticleIds({})
    setActivePositionId(null)
    setExportPreview(null)
    setShowExportDialog(false)
    setDuplicateInfo(null)
    setMetadata(null)
    setUndoStack([])
    setProjectId(null)
    setShowPdfViewer(false)
    setPriceAdjustments({})
    setCategoryAdjustments({})
    setSupplierOpenFlags({})
    setComponentSelections({})
    setPositionDecisions({})
    setAssignmentUiState(DEFAULT_ASSIGNMENT_UI_STATE)
    setPendingInquiryPositionIds([])
    setInquiries([])
    setAlternativeFlags({})
    setIsReadOnly(false)
    setProjectUserInfo({})
    workstateSignatureRef.current = ''
    setStep('idle')
    setErrorText(null)
  }, [])

  useEffect(() => {
    if (!projectId || isReadOnly || step !== 'done') return

    const materialPositionIds = new Set(
      positions.filter((position) => position.position_type !== 'dienstleistung').map((position) => position.id),
    )

    const normalizedSelections: Record<string, string[]> = {}
    Object.entries(selectedArticleIds).forEach(([positionId, articleIds]) => {
      if (!materialPositionIds.has(positionId)) return
      if (articleIds.length === 0) return
      normalizedSelections[positionId] = articleIds
    })

    const normalizedComponentSelections: Record<string, string> = {}
    Object.entries(componentSelections).forEach(([selectionKey, artikelId]) => {
      const [positionId] = selectionKey.split('::')
      if (!materialPositionIds.has(positionId)) return
      if (!artikelId) return
      normalizedComponentSelections[selectionKey] = artikelId
    })

    const normalizedDecisions: Record<string, 'accepted' | 'rejected' | 'inquiry_pending'> = {}
    Object.entries(positionDecisions).forEach(([positionId, decision]) => {
      if (!materialPositionIds.has(positionId)) return
      normalizedDecisions[positionId] = decision
    })

    const payload = {
      project_id: projectId,
      selected_article_ids: normalizedSelections,
      decisions: normalizedDecisions,
      component_selections: normalizedComponentSelections,
      ui_state: assignmentUiState,
    }
    const signature = JSON.stringify(payload)
    if (signature === workstateSignatureRef.current) return

    const timer = setTimeout(() => {
      saveWorkstate(payload)
        .then(() => {
          workstateSignatureRef.current = signature
        })
        .catch(() => {})
    }, 700)

    return () => clearTimeout(timer)
  }, [projectId, isReadOnly, step, positions, selectedArticleIds, componentSelections, positionDecisions, assignmentUiState])

  return {
    file, setFile,
    positions,
    positionSuggestions,
    selectedArticleIds,
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
    categoryAdjustments,
    customUnitPrices,
    handleAnalyze,
    handleCancel,
    handleSuggestionSelect,
    handleSilentSelect,
    handleManualSelect,
    handleParameterChange,
    handleExportPreview,
    handleExportConfirm,
    handleExportCancel,
    handleSendOfferEmail,
    isSendingOfferEmail,
    sendOfferResult,
    handlePreviewOfferPdf,
    isPreviewingOfferPdf,
    handleLoadProject,
    handleReset,
    handleUndo,
    handleRejectSuggestion,
    handlePriceAdjustmentChange,
    handleAddArticle,
    handleRemoveArticle,
    alternativeFlags,
    handleToggleAlternative,
    supplierOpenFlags,
    handleToggleSupplierOpen,
    componentSelections,
    handleComponentSelect,
    handleComponentManualSelect,
    positionDecisions,
    handleSetPositionDecision,
    assignmentUiState,
    handleAssignmentUiStateChange,
    pendingInquiryPositionIds,
    inquiries,
    handleRefreshInquiries,
    isReadOnly,
    projectUserInfo,
  }
}
