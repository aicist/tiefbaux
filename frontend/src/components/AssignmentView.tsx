import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchInquiries, getProjectPdfUrl } from '../api'
import { InquiryReviewScreen } from './InquiryReviewScreen'
import type { AssignmentUiState, LVPosition, PositionSuggestions, PriceAdjustment, ProductSearchResult, ProductSuggestion, SupplierInquiry } from '../types'
import { DinBadge } from './DinBadge'
import { InquiryModal } from './InquiryModal'
import { PriceAdjustmentControl } from './PriceAdjustmentControl'
import { ProductSearchModal } from './ProductSearchModal'
import { computeAdjustedTotal, computeAdjustedUnitPrice, isAdjustedPrice } from '../utils/pricing'
import { additionalAssignmentKey, componentAssignmentKey, primaryAssignmentKey } from '../utils/assignmentKeys'
import { buildEmbeddedPdfViewerUrl } from '../utils/pdfViewer'

const LOAD_CLASS_CATEGORIES = new Set(['Schachtabdeckungen', 'Straßenentwässerung'])

function ParamBadge({ label, status }: { label: string; status: 'match' | 'mismatch' | 'neutral' }) {
  return (
    <span className={`param-badge param-${status}`}>
      {label}
    </span>
  )
}

function extractSnFromText(text: string): number | null {
  const match = text.match(/SN\s*(\d+)/i)
  return match ? parseInt(match[1], 10) : null
}

function normalizeOZForSearch(oz: string): string {
  return oz
    .split('.')
    .map((part) => {
      const normalized = part.replace(/^0+/, '')
      return normalized.length > 0 ? normalized : '0'
    })
    .join('.')
}

function buildOriginalPdfViewerUrl(projectId: number, position: LVPosition): string {
  const page = Math.max(1, position.source_page ?? 1)
  const top = Math.max(0, Math.trunc(position.source_y ?? 0))
  const normalizedOz = normalizeOZForSearch(position.ordnungszahl)
  const basePdfUrl = getProjectPdfUrl(projectId)
  // Ensure the iframe reloads on every OZ change.
  const joiner = basePdfUrl.includes('?') ? '&' : '?'
  const cacheBusted = `${basePdfUrl}${joiner}oz_anchor=${encodeURIComponent(normalizedOz)}`
  return buildEmbeddedPdfViewerUrl(cacheBusted, {
    page,
    top,
    search: normalizedOz,
  })
}

function shouldShowNormBadge(_position: LVPosition, suggestion: ProductSuggestion): boolean {
  if (!suggestion.norm) return false
  return true
}

function filterSuggestionWarnings(warnings: string[]): string[] {
  return warnings.filter((warning) => {
    const lower = warning.toLowerCase()
    return lower.includes('menge nicht erkannt')
      || lower.includes('listenpreis ist 0')
      || lower.includes('kein preis verfügbar')
  })
}

function filterSuggestionReasons(reasons: string[]): string[] {
  return reasons.filter((reason) => {
    const lower = reason.toLowerCase()
    if (lower.includes('norm abweichend')) return false
    if (lower.includes('lager')) return false
    if (/^(dn|od|anschluss-dn)\b/i.test(reason)) return false
    return true
  })
}

function formatMoney(value?: number | null, currency = 'EUR'): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value)
}

function scoreColor(score: number): string {
  if (score >= 50) return 'var(--accent)'
  if (score >= 30) return 'var(--warn)'
  return 'var(--danger)'
}

function stockStatus(stock?: number | null): { label: string; className: string } {
  if (stock == null || stock <= 0) return { label: 'Nicht auf Lager', className: 'stock-red' }
  if (stock < 10) return { label: `${stock} auf Lager`, className: 'stock-amber' }
  return { label: `${stock} auf Lager`, className: 'stock-green' }
}

function tokenizeOfferText(text: string): Set<string> {
  const parts = (text.toLowerCase().match(/[a-z0-9äöüß]{3,}/g) ?? [])
  return new Set(parts)
}

function offerMatchScore(suggestion: ProductSuggestion, inquiry: SupplierInquiry): number {
  const offerText = inquiry.product_description ?? ''
  const offerTokens = tokenizeOfferText(offerText)
  if (offerTokens.size === 0) return 0

  const suggestionText = [
    suggestion.artikel_id,
    suggestion.artikelname,
    suggestion.hersteller ?? '',
    suggestion.category ?? '',
    suggestion.subcategory ?? '',
  ].join(' ')
  const suggestionTokens = tokenizeOfferText(suggestionText)
  if (suggestionTokens.size === 0) return 0

  let score = 0
  for (const token of suggestionTokens) {
    if (offerTokens.has(token)) score += 2
  }

  const normalizedOffer = offerText.toLowerCase()
  if (suggestion.artikel_id && normalizedOffer.includes(suggestion.artikel_id.toLowerCase())) score += 8
  if (suggestion.dn != null && new RegExp(`\\bdn\\s*${suggestion.dn}\\b`, 'i').test(offerText)) score += 4
  if (suggestion.hersteller && inquiry.supplier_name) {
    const supplierToken = inquiry.supplier_name.toLowerCase().split(/\s+/)[0]
    if (supplierToken && suggestion.hersteller.toLowerCase().includes(supplierToken)) score += 3
  }
  return score
}

function mapOfferSuggestionSources(
  suggestions: ProductSuggestion[],
  receivedInquiries: SupplierInquiry[],
): Record<string, string> {
  // If real supplier offer suggestions (SO-*) are already present, skip fuzzy
  // matching to avoid showing misleading "Aus Lieferantenangebot" badges on
  // catalog articles with different prices.
  const hasRealOfferSuggestions = suggestions.some((s) => s.is_supplier_offer)
  if (hasRealOfferSuggestions) return {}

  const byArtikelId: Record<string, string> = {}
  for (const inquiry of receivedInquiries) {
    let best: ProductSuggestion | null = null
    let bestScore = 0
    for (const suggestion of suggestions) {
      const score = offerMatchScore(suggestion, inquiry)
      if (score > bestScore) {
        best = suggestion
        bestScore = score
      }
    }
    if (best && bestScore >= 2 && !byArtikelId[best.artikel_id]) {
      byArtikelId[best.artikel_id] = inquiry.supplier_name
    }
  }
  return byArtikelId
}

function prioritizeOfferSuggestions(
  suggestions: ProductSuggestion[],
  offerSourcesByArtikelId: Record<string, string>,
): ProductSuggestion[] {
  const offerIds = new Set(Object.keys(offerSourcesByArtikelId))
  if (offerIds.size === 0) return suggestions
  const matched = suggestions.filter((s) => offerIds.has(s.artikel_id))
  const rest = suggestions.filter((s) => !offerIds.has(s.artikel_id))
  return [...matched, ...rest]
}

export type AssignmentDecision = 'accepted' | 'rejected' | 'inquiry_pending'

type FilterTab = 'alle' | 'zugeordnet' | 'offen' | 'dienstleistung'

type Props = {
  positions: LVPosition[]
  suggestionMap: Record<string, ProductSuggestion[]>
  selectedArticleIds: Record<string, string[]>
  decisions?: Record<string, AssignmentDecision>
  onDecisionChange?: (positionId: string, decision?: AssignmentDecision) => void
  priceAdjustments: Record<string, PriceAdjustment>
  categoryAdjustments: Record<string, PriceAdjustment>
  onAccept: (positionId: string, artikelId: string) => void
  onSilentSelect?: (positionId: string, artikelId: string) => void
  onReject: (positionId: string) => void
  onManualSelect: (positionId: string, product: ProductSearchResult) => void
  onAddArticle: (positionId: string, product: ProductSearchResult) => void
  onRemoveArticle: (positionId: string, artikelId: string) => void
  onPriceAdjustmentChange: (assignmentKey: string, adjustment: PriceAdjustment) => void
  onFinish: () => void
  onBackToOverview: () => void
  projectId?: number | null
  projectName?: string | null
  alternativeFlags?: Record<string, boolean>
  onToggleAlternative?: (assignmentKey: string) => void
  supplierOpenFlags?: Record<string, boolean>
  onToggleSupplierOpen?: (assignmentKey: string) => void
  positionSuggestions?: PositionSuggestions[]
  componentSelections?: Record<string, string>
  onComponentSelect?: (positionId: string, componentName: string, artikelId: string) => void
  onComponentManualSelect?: (positionId: string, componentName: string, product: ProductSearchResult) => void
  persistedUiState?: AssignmentUiState | null
  onUiStateChange?: (state: AssignmentUiState) => void
  onRefreshInquiries?: (projectId?: number | null) => Promise<void> | void
}

export function AssignmentView({
  positions,
  suggestionMap,
  selectedArticleIds,
  decisions: externalDecisions,
  onDecisionChange,
  priceAdjustments,
  categoryAdjustments,
  onAccept,
  onSilentSelect,
  onReject,
  onManualSelect,
  onAddArticle,
  onRemoveArticle,
  onPriceAdjustmentChange,
  onFinish,
  onBackToOverview,
  projectId,
  projectName,
  alternativeFlags = {},
  onToggleAlternative,
  supplierOpenFlags = {},
  onToggleSupplierOpen,
  positionSuggestions = [],
  componentSelections = {},
  onComponentManualSelect,
  persistedUiState,
  onUiStateChange,
  onRefreshInquiries,
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(0)
  const [decisions, setDecisions] = useState<Record<string, AssignmentDecision>>(externalDecisions ?? {})
  const [searchOpen, setSearchOpen] = useState(false)
  const [inquiryOpen, setInquiryOpen] = useState(false)
  const [inquiryProductName, setInquiryProductName] = useState<string | null>(null)
  const [slideDirection, setSlideDirection] = useState<'left' | 'right' | null>(null)
  const [activeFilter, setActiveFilter] = useState<FilterTab>(persistedUiState?.active_filter ?? 'alle')
  const [pendingInquiries, setPendingInquiries] = useState<SupplierInquiry[]>([])
  const [projectInquiries, setProjectInquiries] = useState<SupplierInquiry[]>([])
  const [inquiriesLoading, setInquiriesLoading] = useState(false)
  const [inquiriesSentResult, setInquiriesSentResult] = useState<{ sent: number; failed: number } | null>(null)
  const [showInquiryReview, setShowInquiryReview] = useState(false)
  const [decisionHistory, setDecisionHistory] = useState<Array<{
    positionId: string
    previousDecision: AssignmentDecision | undefined
    previousArticleIds: string[] | undefined
    previousIndex: number
  }>>([])

  useEffect(() => {
    setDecisions(externalDecisions ?? {})
  }, [externalDecisions])

  useEffect(() => {
    progressHydratedRef.current = false
  }, [projectId])

  // Categorize positions
  const materialPositions = useMemo(
    () => positions.filter(p => p.position_type !== 'dienstleistung'),
    [positions],
  )

  const servicePositions = useMemo(
    () => positions.filter(p => p.position_type === 'dienstleistung'),
    [positions],
  )

  // Count component selections per position
  const componentSelectionCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    Object.keys(componentSelections).forEach((key) => {
      const [positionId] = key.split('::')
      counts[positionId] = (counts[positionId] ?? 0) + 1
    })
    return counts
  }, [componentSelections])

  const hasAssignment = useCallback((posId: string) => {
    return (selectedArticleIds[posId]?.length ?? 0) > 0 || (componentSelectionCounts[posId] ?? 0) > 0
  }, [selectedArticleIds, componentSelectionCounts])

  // Filtered positions based on active tab
  const filteredPositions = useMemo(() => {
    switch (activeFilter) {
      case 'zugeordnet':
        return materialPositions.filter(p => hasAssignment(p.id))
      case 'offen':
        return materialPositions.filter(p => !hasAssignment(p.id))
      case 'dienstleistung':
        return servicePositions
      default:
        return materialPositions
    }
  }, [activeFilter, materialPositions, servicePositions, hasAssignment])

  // Tab counts
  const assignedCount = useMemo(
    () => materialPositions.filter(p => hasAssignment(p.id)).length,
    [materialPositions, hasAssignment],
  )
  const openCount = useMemo(
    () => materialPositions.filter(p => !hasAssignment(p.id)).length,
    [materialPositions, hasAssignment],
  )

  const currentPosition = filteredPositions[currentIndex] ?? null
  const currentSuggestions = currentPosition ? suggestionMap[currentPosition.id] ?? [] : []
  const currentSelectedArticles = currentPosition ? selectedArticleIds[currentPosition.id] ?? [] : []
  const currentPositionInquiries = useMemo(
    () => currentPosition ? projectInquiries.filter((inquiry) => inquiry.position_id === currentPosition.id) : [],
    [projectInquiries, currentPosition],
  )
  const currentReceivedInquiries = useMemo(
    () => currentPositionInquiries.filter((inquiry) => inquiry.status === 'angebot_erhalten'),
    [currentPositionInquiries],
  )
  const currentSelectedArticle = currentSelectedArticles[0]
  const additionalArticleIds = useMemo(() => new Set(currentSelectedArticles.slice(1)), [currentSelectedArticles])
  const offerSourcesByArtikelId = useMemo(
    () => mapOfferSuggestionSources(currentSuggestions, currentReceivedInquiries),
    [currentSuggestions, currentReceivedInquiries],
  )
  // Carousel shows only matching suggestions, not manually added additional articles
  const carouselSuggestions = useMemo(
    () => prioritizeOfferSuggestions(
      currentSuggestions.filter((s) => !additionalArticleIds.has(s.artikel_id)),
      offerSourcesByArtikelId,
    ),
    [currentSuggestions, additionalArticleIds, offerSourcesByArtikelId],
  )
  const [addArticleSearchOpen, setAddArticleSearchOpen] = useState(false)
  const [componentSearchTarget, setComponentSearchTarget] = useState<{ positionId: string; componentName: string } | null>(null)
  const [showRejectConfirm, setShowRejectConfirm] = useState(false)
  const [showOriginalPdf, setShowOriginalPdf] = useState(false)
  const [carouselIndex, setCarouselIndex] = useState(0)
  const [swipeDir, setSwipeDir] = useState<'up' | 'down' | null>(null)
  const [pendingJumpPositionId, setPendingJumpPositionId] = useState<string | null>(null)
  const progressHydratedRef = useRef(false)
  const totalCount = filteredPositions.length
  const decidedCount = Object.keys(decisions).length

  const isFinished = currentIndex >= totalCount

  // Reset index when filter changes
  useEffect(() => {
    setCurrentIndex(0)
  }, [activeFilter])

  useEffect(() => {
    if (!pendingJumpPositionId) return
    const jumpIndex = filteredPositions.findIndex((position) => position.id === pendingJumpPositionId)
    if (jumpIndex < 0) return
    setCurrentIndex(jumpIndex)
    setPendingJumpPositionId(null)
  }, [pendingJumpPositionId, filteredPositions])

  useEffect(() => {
    if (progressHydratedRef.current) return
    const targetState = persistedUiState ?? { active_filter: 'alle', current_position_id: null, is_finished: false }
    const targetFilter = targetState.active_filter ?? 'alle'

    if (activeFilter !== targetFilter) {
      setActiveFilter(targetFilter)
      return
    }

    if (targetState.is_finished) {
      setCurrentIndex(totalCount)
      progressHydratedRef.current = true
      return
    }

    if (targetState.current_position_id) {
      const targetIndex = filteredPositions.findIndex((position) => position.id === targetState.current_position_id)
      if (targetIndex >= 0) setCurrentIndex(targetIndex)
    }
    progressHydratedRef.current = true
  }, [persistedUiState, activeFilter, filteredPositions, totalCount])

  useEffect(() => {
    if (!onUiStateChange) return
    if (!progressHydratedRef.current) return
    onUiStateChange({
      active_filter: activeFilter,
      current_position_id: isFinished ? null : (currentPosition?.id ?? null),
      is_finished: isFinished,
    })
  }, [activeFilter, isFinished, currentPosition?.id, onUiStateChange])

  // Reset raw text toggle and carousel on position change, auto-select top suggestion
  useEffect(() => {
    setShowOriginalPdf(false)
    setCarouselIndex(0)
    setSwipeDir(null)
    // Auto-select top suggestion if nothing selected yet
    const pos = filteredPositions[currentIndex]
    if (pos && !selectedArticleIds[pos.id]?.length) {
      const suggestions = suggestionMap[pos.id] ?? []
      const receivedForPosition = projectInquiries.filter(
        (inquiry) => inquiry.position_id === pos.id && inquiry.status === 'angebot_erhalten',
      )
      const prioritized = prioritizeOfferSuggestions(suggestions, mapOfferSuggestionSources(suggestions, receivedForPosition))
      const topSuggestion = prioritized[0]
      if (topSuggestion) {
        const select = onSilentSelect ?? onAccept
        select(pos.id, topSuggestion.artikel_id)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentIndex, projectInquiries])

  // Clear swipe animation direction after animation completes
  useEffect(() => {
    if (swipeDir) {
      const timer = setTimeout(() => setSwipeDir(null), 250)
      return () => clearTimeout(timer)
    }
  }, [swipeDir, carouselIndex])

  // Sync carousel to selected article when selection changes (not on every carousel move)
  useEffect(() => {
    if (!currentSelectedArticle) return
    const selectedIndex = carouselSuggestions.findIndex((s) => s.artikel_id === currentSelectedArticle)
    if (selectedIndex >= 0) {
      setCarouselIndex(selectedIndex)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSelectedArticle, carouselSuggestions])

  // Slide animation
  useEffect(() => {
    if (slideDirection) {
      const timer = setTimeout(() => setSlideDirection(null), 300)
      return () => clearTimeout(timer)
    }
  }, [slideDirection])

  const goNext = useCallback(() => {
    setSlideDirection('left')
    setCurrentIndex(prev => Math.min(prev + 1, totalCount))
  }, [totalCount])

  const goPrev = useCallback(() => {
    if (currentIndex > 0) {
      setSlideDirection('right')
      setCurrentIndex(prev => prev - 1)
    }
  }, [currentIndex])

  const handleSelectArticle = useCallback((artikelId: string) => {
    if (!currentPosition) return
    const select = onSilentSelect ?? onAccept
    select(currentPosition.id, artikelId)
  }, [currentPosition, onAccept, onSilentSelect])

  const jumpToPosition = useCallback((positionId: string, targetFilter: FilterTab = 'alle') => {
    if (activeFilter !== targetFilter) {
      setActiveFilter(targetFilter)
    }
    setPendingJumpPositionId(positionId)
  }, [activeFilter])

  const suggestionCoverageByPosition = useMemo(() => {
    const coverage: Record<string, boolean> = {}
    for (const position of materialPositions) {
      const hasPrimary = (suggestionMap[position.id]?.length ?? 0) > 0
      const entry = positionSuggestions.find((ps) => ps.position_id === position.id)
      const hasComponentSuggestion = (entry?.component_suggestions?.some((cs) => cs.suggestions.length > 0) ?? false)
      coverage[position.id] = hasPrimary || hasComponentSuggestion
    }
    return coverage
  }, [materialPositions, suggestionMap, positionSuggestions])

  const advanceAfterDecision = useCallback((newDecisions: Record<string, AssignmentDecision>) => {
    // If on last position or near end, check if there are undecided positions
    const nextIndex = currentIndex + 1
    if (nextIndex >= totalCount) {
      // Check if all material positions decided
      const hasUndecided = materialPositions.some(p => !newDecisions[p.id])
      if (hasUndecided) {
        const firstUndecidedIdx = filteredPositions.findIndex(p => !newDecisions[p.id])
        if (firstUndecidedIdx >= 0) {
          setSlideDirection('left')
          setCurrentIndex(firstUndecidedIdx)
          return
        }
        const firstUndecidedPosition = materialPositions.find((position) => !newDecisions[position.id])
        if (firstUndecidedPosition) {
          jumpToPosition(firstUndecidedPosition.id, 'alle')
          return
        }
      }
    }
    goNext()
  }, [currentIndex, totalCount, materialPositions, filteredPositions, goNext, jumpToPosition])

  const handleContinue = useCallback(() => {
    if (!currentPosition) return
    if (!currentSelectedArticle && !hasAssignment(currentPosition.id)) return
    setDecisionHistory(prev => [...prev, {
      positionId: currentPosition.id,
      previousDecision: decisions[currentPosition.id],
      previousArticleIds: selectedArticleIds[currentPosition.id] ? [...selectedArticleIds[currentPosition.id]] : undefined,
      previousIndex: currentIndex,
    }])
    const newDecisions = { ...decisions, [currentPosition.id]: 'accepted' as const }
    setDecisions(newDecisions)
    onDecisionChange?.(currentPosition.id, 'accepted')
    setPendingInquiries((prev) => prev.filter((inquiry) => inquiry.position_id !== currentPosition.id))
    advanceAfterDecision(newDecisions)
  }, [currentPosition, currentSelectedArticle, hasAssignment, advanceAfterDecision, decisions, selectedArticleIds, currentIndex, onDecisionChange])

  const handleRejectRequest = useCallback(() => {
    if (!currentPosition) return
    setShowRejectConfirm(true)
  }, [currentPosition])

  const handleRejectConfirm = useCallback(() => {
    if (!currentPosition) return
    setShowRejectConfirm(false)
    setDecisionHistory(prev => [...prev, {
      positionId: currentPosition.id,
      previousDecision: decisions[currentPosition.id],
      previousArticleIds: selectedArticleIds[currentPosition.id] ? [...selectedArticleIds[currentPosition.id]] : undefined,
      previousIndex: currentIndex,
    }])
    onReject(currentPosition.id)
    const newDecisions = { ...decisions, [currentPosition.id]: 'rejected' as const }
    setDecisions(newDecisions)
    onDecisionChange?.(currentPosition.id, 'rejected')
    setPendingInquiries((prev) => prev.filter((inquiry) => inquiry.position_id !== currentPosition.id))
    advanceAfterDecision(newDecisions)
  }, [currentPosition, onReject, advanceAfterDecision, decisions, selectedArticleIds, currentIndex, onDecisionChange])

  const handleRejectCancel = useCallback(() => {
    setShowRejectConfirm(false)
  }, [])

  const handleUndo = useCallback(() => {
    if (decisionHistory.length === 0) return
    const last = decisionHistory[decisionHistory.length - 1]
    setDecisionHistory(prev => prev.slice(0, -1))
    if (last.previousDecision) {
      setDecisions(prev => ({ ...prev, [last.positionId]: last.previousDecision! }))
      onDecisionChange?.(last.positionId, last.previousDecision)
    } else {
      setDecisions(prev => {
        const next = { ...prev }
        delete next[last.positionId]
        return next
      })
      onDecisionChange?.(last.positionId, undefined)
    }
    // Restore previous article selection if it was a reject that cleared it
    if (last.previousArticleIds && last.previousArticleIds.length > 0) {
      onAccept(last.positionId, last.previousArticleIds[0])
    }
    setCurrentIndex(last.previousIndex)
  }, [decisionHistory, onAccept, onDecisionChange])

  const handleManualSearchSelect = useCallback((product: ProductSearchResult) => {
    if (!currentPosition) return
    onManualSelect(currentPosition.id, product)
    setSearchOpen(false)
  }, [currentPosition, onManualSelect])

  const handleAddArticleSelect = useCallback((product: ProductSearchResult) => {
    if (!currentPosition) return
    onAddArticle(currentPosition.id, product)
    setAddArticleSearchOpen(false)
  }, [currentPosition, onAddArticle])

  const handleComponentSearchSelect = useCallback((product: ProductSearchResult) => {
    if (!componentSearchTarget || !onComponentManualSelect) return
    onComponentManualSelect(componentSearchTarget.positionId, componentSearchTarget.componentName, product)
    setComponentSearchTarget(null)
  }, [componentSearchTarget, onComponentManualSelect])

  const handleInquirySuccess = useCallback(() => {
    if (!currentPosition) return
    const nextDecision: AssignmentDecision = 'inquiry_pending'
    setDecisionHistory(prev => [...prev, {
      positionId: currentPosition.id,
      previousDecision: decisions[currentPosition.id],
      previousArticleIds: selectedArticleIds[currentPosition.id] ? [...selectedArticleIds[currentPosition.id]] : undefined,
      previousIndex: currentIndex,
    }])
    const newDecisions = { ...decisions, [currentPosition.id]: nextDecision }
    setDecisions(newDecisions)
    onDecisionChange?.(currentPosition.id, nextDecision)
    setInquiryOpen(false)
    setInquiryProductName(null)
    if (projectId) {
      setInquiriesLoading(true)
      setInquiriesSentResult(null)
      fetchInquiries(projectId)
        .then((data) => {
          setProjectInquiries(data)
          setPendingInquiries(data.filter((inq) => inq.status === 'offen'))
        })
        .catch(() => {
          setProjectInquiries([])
          setPendingInquiries([])
        })
        .finally(() => setInquiriesLoading(false))
    }
    advanceAfterDecision(newDecisions)
  }, [currentPosition, decisions, selectedArticleIds, currentIndex, onDecisionChange, advanceAfterDecision, projectId])

  const refreshPendingInquiries = useCallback(() => {
    if (!projectId) {
      setPendingInquiries([])
      setProjectInquiries([])
      return Promise.resolve()
    }
    setInquiriesLoading(true)
    setInquiriesSentResult(null)
    return fetchInquiries(projectId)
      .then((data) => {
        setProjectInquiries(data)
        setPendingInquiries(data.filter((inq) => inq.status === 'offen'))
        void onRefreshInquiries?.(projectId)
      })
      .catch(() => {
        setProjectInquiries([])
        setPendingInquiries([])
        void onRefreshInquiries?.(projectId)
      })
      .finally(() => setInquiriesLoading(false))
  }, [projectId, onRefreshInquiries])

  useEffect(() => {
    if (!projectId) return
    void refreshPendingInquiries()
  }, [projectId, refreshPendingInquiries])

  // Keyboard shortcuts
  useEffect(() => {
    if (isFinished || searchOpen || showRejectConfirm) return
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

      switch (e.key) {
        case 'Enter':
          e.preventDefault()
          if (currentSelectedArticle || carouselSuggestions[0]?.artikel_id || (currentPosition && hasAssignment(currentPosition.id))) {
            handleContinue()
          }
          break
        case 'Escape':
          e.preventDefault()
          handleRejectRequest()
          break
        case 'ArrowRight':
          e.preventDefault()
          if (currentPosition && decisions[currentPosition.id]) goNext()
          break
        case 'ArrowLeft':
          e.preventDefault()
          goPrev()
          break
        case 'ArrowUp':
          e.preventDefault()
          if (carouselIndex > 0) {
            const newIdx = carouselIndex - 1
            setSwipeDir('up')
            setCarouselIndex(newIdx)
            if (currentPosition && carouselSuggestions[newIdx]) {
              handleSelectArticle(carouselSuggestions[newIdx].artikel_id)
            }
          }
          break
        case 'ArrowDown':
          e.preventDefault()
          if (carouselIndex < carouselSuggestions.length - 1) {
            const newIdx = carouselIndex + 1
            setSwipeDir('down')
            setCarouselIndex(newIdx)
            if (currentPosition && carouselSuggestions[newIdx]) {
              handleSelectArticle(carouselSuggestions[newIdx].artikel_id)
            }
          }
          break
        case 'z':
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault()
            handleUndo()
          }
          break
        case 's':
        case 'S':
          e.preventDefault()
          setSearchOpen(true)
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isFinished, searchOpen, showRejectConfirm, carouselSuggestions, currentSelectedArticle, carouselIndex, handleContinue, handleRejectRequest, handleUndo, handleSelectArticle, hasAssignment, goPrev, currentPosition, decisions])

  // Fetch pending inquiries when assignment is finished
  useEffect(() => {
    if (isFinished && projectId) {
      refreshPendingInquiries()
    }
  }, [isFinished, projectId, refreshPendingInquiries])

  // Summary screen
  if (isFinished) {
    const acceptedCount = Object.values(decisions).filter(d => d === 'accepted').length
    const rejectedCount = Object.values(decisions).filter(d => d === 'rejected').length
    const inquiryPendingCount = Object.values(decisions).filter(d => d === 'inquiry_pending').length
    const undecidedPositions = materialPositions.filter((position) => !decisions[position.id])
    const undecidedCount = undecidedPositions.length
    const undecidedWithSuggestions = undecidedPositions.filter((position) => suggestionCoverageByPosition[position.id])
    const undecidedWithoutSuggestions = undecidedPositions.filter((position) => !suggestionCoverageByPosition[position.id])
    const undecidedWithSuggestionsCount = undecidedWithSuggestions.length
    const undecidedWithoutSuggestionsCount = undecidedWithoutSuggestions.length
    const svcCount = positions.length - materialPositions.length
    const supplierOpenCount = Object.values(supplierOpenFlags).filter(Boolean).length
    const sentInquiries = projectInquiries.filter((inq) => inq.status === 'angefragt')
    const receivedInquiries = projectInquiries.filter((inq) => inq.status === 'angebot_erhalten')
    const hasBlockingInquiries = inquiryPendingCount > 0 || pendingInquiries.length > 0 || sentInquiries.length > 0 || inquiriesLoading
    const shouldShowInquiryOverview = Boolean(projectId)
      && (inquiriesLoading || pendingInquiries.length > 0 || sentInquiries.length > 0 || receivedInquiries.length > 0 || inquiryPendingCount > 0)

    // Calculate total value
    let totalValue = 0
    for (const [posId, artIds] of Object.entries(selectedArticleIds)) {
      const suggestions = suggestionMap[posId]
      if (!suggestions) continue
      const position = positions.find(p => p.id === posId)
      for (let i = 0; i < artIds.length; i++) {
        const match = suggestions.find(s => s.artikel_id === artIds[i])
        const assignmentKey = i === 0 ? primaryAssignmentKey(posId) : additionalAssignmentKey(posId, artIds[i])
        const unitPrice = computeAdjustedUnitPrice(match?.price_net, priceAdjustments[assignmentKey])
        const adjustedTotal = computeAdjustedTotal(unitPrice, position?.quantity)
        if (adjustedTotal != null) totalValue += adjustedTotal
      }
    }
    for (const [selectionKey, artikelId] of Object.entries(componentSelections)) {
      const [positionId, componentName] = selectionKey.split('::')
      const position = positions.find((p) => p.id === positionId)
      const entry = positionSuggestions.find((ps) => ps.position_id === positionId)
      const component = entry?.component_suggestions?.find((cs) => cs.component_name === componentName)
      const suggestion = component?.suggestions.find((s) => s.artikel_id === artikelId)
      const unitPrice = computeAdjustedUnitPrice(
        suggestion?.price_net,
        priceAdjustments[componentAssignmentKey(positionId, componentName)],
      )
      const adjustedTotal = computeAdjustedTotal(unitPrice, position?.quantity)
      if (adjustedTotal != null) totalValue += adjustedTotal
    }

    return (
      <div className="assignment-view">
        <div className="assignment-summary">
          <div className="summary-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="var(--accent)" strokeWidth="1.5" />
              <path d="M8 12l3 3 5-5" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h2>{undecidedCount > 0 ? 'Zuordnung noch offen' : 'Zuordnung abgeschlossen'}</h2>

          <div className="summary-stats">
            <div className="summary-stat stat-accepted">
              <span className="stat-number">{acceptedCount}</span>
              <span className="stat-label">Zugeordnet</span>
            </div>
            <div className="summary-stat stat-rejected">
              <span className="stat-number">{rejectedCount}</span>
              <span className="stat-label">Ohne Zuordnung</span>
            </div>
            {inquiryPendingCount > 0 && (
              <div className="summary-stat stat-supplier-open">
                <span className="stat-number">{inquiryPendingCount}</span>
                <span className="stat-label">Anfrage offen</span>
              </div>
            )}
            {svcCount > 0 && (
              <div className="summary-stat stat-service">
                <span className="stat-number">{svcCount}</span>
                <span className="stat-label">Dienstleistungen</span>
              </div>
            )}
            {supplierOpenCount > 0 && (
              <div className="summary-stat stat-supplier-open">
                <span className="stat-number">{supplierOpenCount}</span>
                <span className="stat-label">Lieferant offen</span>
              </div>
            )}
          </div>

          {totalValue > 0 && (
            <div className="summary-total">
              <span className="summary-total-label">Geschätzter Gesamtwert</span>
              <span className="summary-total-value">{formatMoney(totalValue)}</span>
            </div>
          )}

          {undecidedCount > 0 && (
            <div className="summary-undecided-warning">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>{undecidedCount} Position{undecidedCount !== 1 ? 'en' : ''} noch nicht abgeschlossen</span>
              {undecidedWithSuggestionsCount > 0 && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    const first = undecidedWithSuggestions[0]
                    if (first) jumpToPosition(first.id, 'alle')
                  }}
                >
                  Zu Positionen mit Vorschlag ({undecidedWithSuggestionsCount})
                </button>
              )}
              {undecidedWithoutSuggestionsCount > 0 && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    const first = undecidedWithoutSuggestions[0]
                    if (first) jumpToPosition(first.id, 'offen')
                  }}
                >
                  Zu offenen ohne Treffer ({undecidedWithoutSuggestionsCount})
                </button>
              )}
            </div>
          )}

          <div className="summary-actions">
            <button className="btn btn-primary" onClick={onFinish} disabled={undecidedCount > 0 || hasBlockingInquiries}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Angebot exportieren
            </button>
            {hasBlockingInquiries && (
              <p className="summary-export-hint">
                Angebot erst möglich, solange Lieferantenanfragen offen oder ausstehend sind.
              </p>
            )}
            <div className="summary-actions-secondary">
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setActiveFilter('alle')
                  setCurrentIndex(0)
                  setShowInquiryReview(false)
                }}
              >
                Nochmal durchgehen
              </button>
              <button className="btn btn-secondary" onClick={onBackToOverview}>
                Zur Übersicht
              </button>
            </div>
          </div>

          {/* Inquiry overview */}
          {shouldShowInquiryOverview && !showInquiryReview && (
            <div className="summary-inquiries">
              <h3>Lieferantenanfragen</h3>
              {inquiriesLoading ? (
                <p className="inquiry-sent-result">Anfragen werden geladen…</p>
              ) : pendingInquiries.length > 0 ? (
                <>
                  <div className="inquiry-summary-list">
                    {Object.entries(
                      pendingInquiries.reduce<Record<string, SupplierInquiry[]>>((acc, inq) => {
                        const key = inq.supplier_name
                        if (!acc[key]) acc[key] = []
                        acc[key].push(inq)
                        return acc
                      }, {})
                    ).map(([supplierName, inquiries]) => (
                      <div key={supplierName} className="inquiry-supplier-group">
                        <span className="inquiry-supplier-name">{supplierName}</span>
                        <span className="inquiry-count">{inquiries.length} Anfrage{inquiries.length !== 1 ? 'n' : ''}</span>
                      </div>
                    ))}
                  </div>
                  {inquiriesSentResult ? (
                    <p className="inquiry-sent-result">
                      {inquiriesSentResult.sent} gesendet{inquiriesSentResult.failed > 0 ? `, ${inquiriesSentResult.failed} fehlgeschlagen` : ''}
                    </p>
                  ) : (
                    <button
                      className="btn btn-primary"
                      onClick={() => setShowInquiryReview(true)}
                    >
                      Anfragen prüfen & senden ({pendingInquiries.length})
                    </button>
                  )}
                </>
              ) : sentInquiries.length > 0 || receivedInquiries.length > 0 ? (
                <>
                  <p className="inquiry-sent-result">
                    {sentInquiries.length} Anfrage{sentInquiries.length !== 1 ? 'n' : ''} wurde{sentInquiries.length !== 1 ? 'n' : ''} versendet.
                  </p>
                  {receivedInquiries.length > 0 && (
                    <p className="inquiry-sent-result">
                      {receivedInquiries.length} Angebot{receivedInquiries.length !== 1 ? 'e' : ''} bereits erhalten.
                    </p>
                  )}
                </>
              ) : (
                <p className="inquiry-sent-result">
                  Für {inquiryPendingCount} Position{inquiryPendingCount !== 1 ? 'en' : ''} sind Anfragen markiert, aktuell aber ohne offenen Status.
                </p>
              )}
            </div>
          )}

          {showInquiryReview && projectId && (
            <InquiryReviewScreen
              projectId={projectId}
              pendingInquiries={pendingInquiries}
              onBack={() => setShowInquiryReview(false)}
              onSent={(result) => {
                setInquiriesSentResult(result)
                setShowInquiryReview(false)
                void refreshPendingInquiries()
              }}
            />
          )}
        </div>
      </div>
    )
  }

  const isServiceView = activeFilter === 'dienstleistung'
  const topSuggestion = currentSuggestions[0] ?? null
  const showLoadClass = currentPosition ? LOAD_CLASS_CATEGORIES.has(currentPosition.parameters.product_category ?? '') : false
  const currentPrimaryAssignmentKey = currentPosition ? primaryAssignmentKey(currentPosition.id) : null
  const currentPriceAdjustment = currentPosition
    ? priceAdjustments[currentPrimaryAssignmentKey ?? ''] ?? categoryAdjustments[topSuggestion?.category ?? '']
    : undefined
  const pricingReferenceSuggestion = currentSuggestions.find((s) => s.artikel_id === currentSelectedArticles[0]) ?? topSuggestion
  const progressPercent = totalCount > 0 ? (currentIndex / totalCount) * 100 : 0

  const originalPdfUrl = projectId && currentPosition
    ? buildOriginalPdfViewerUrl(projectId, currentPosition)
    : null

  return (
    <div className="assignment-view">
      {/* Filter tabs */}
      <div className="assignment-tabs">
        <button
          className={`tab-btn ${activeFilter === 'alle' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('alle')}
        >
          Alle ({materialPositions.length})
        </button>
        <button
          className={`tab-btn ${activeFilter === 'zugeordnet' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('zugeordnet')}
        >
          Zugeordnet ({assignedCount})
        </button>
        <button
          className={`tab-btn ${activeFilter === 'offen' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('offen')}
        >
          Offen ({openCount})
        </button>
        <button
          className={`tab-btn ${activeFilter === 'dienstleistung' ? 'tab-active' : ''}`}
          onClick={() => setActiveFilter('dienstleistung')}
        >
          Dienstleistung ({servicePositions.length})
        </button>
        <div className="tab-spacer" />
        <button className="btn btn-ghost btn-overview" onClick={onBackToOverview}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="14" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Übersicht
        </button>
      </div>

      {/* Progress bar */}
      <div className="assignment-progress">
        <div className="progress-text">
          <span>{totalCount > 0 ? currentIndex + 1 : 0} / {totalCount} Positionen</span>
          <span className="progress-decided">{decidedCount} bearbeitet</span>
        </div>
        <div className="progress-bar-track">
          <div className="progress-bar-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="progress-shortcuts">
          <span><kbd>Enter</kbd> Übernehmen</span>
          <span><kbd>Esc</kbd> Ablehnen</span>
          <span><kbd>←→</kbd> Navigation</span>
          <span><kbd>↑↓</kbd> Vorschläge</span>
          <span><kbd>S</kbd> Suchen</span>
        </div>
      </div>

      {/* Empty state when no positions in filter */}
      {totalCount === 0 && (
        <div className="assignment-card">
          <div className="assignment-no-match">
            <p>Keine Positionen in dieser Kategorie.</p>
          </div>
        </div>
      )}

      {/* Position card */}
      {currentPosition && (
        <div className={`assignment-card ${slideDirection === 'left' ? 'slide-out-left' : slideDirection === 'right' ? 'slide-out-right' : 'slide-in'}`}>
          <div className="assignment-position">
            <div className="position-headline">
              <div className="position-oz">OZ {currentPosition.ordnungszahl}</div>
              {decisions[currentPosition.id] && (
                <span className={`position-decision-badge position-decision-badge--${decisions[currentPosition.id]}`}>
                  {decisions[currentPosition.id] === 'accepted'
                    ? 'Bestätigt'
                    : decisions[currentPosition.id] === 'rejected'
                      ? 'Abgelehnt'
                      : 'Anfrage'}
                </span>
              )}
            </div>
            {(() => {
              const p = currentPosition.parameters
              const isService = currentPosition.position_type === 'dienstleistung'
              const productTitle =
                p.article_type
                || p.product_category
                || (isService ? 'Dienstleistung' : null)
              const productSubtitle = p.product_subcategory || null
              const specRows: Array<{ label: string; value: string }> = []
              const push = (label: string, value: unknown, fmt?: (v: string) => string) => {
                if (value === null || value === undefined || value === '' || value === false) return
                const s = fmt ? fmt(String(value)) : String(value)
                if (!s.trim()) return
                specRows.push({ label, value: s })
              }
              push('Nennweite', p.nominal_diameter_dn, v => `DN ${v}`)
              push('Zweite Nennweite', p.secondary_nominal_diameter_dn, v => `DN ${v}`)
              push('Material', p.material)
              push('Druckfestigkeit', p.compressive_strength)
              push('Expositionsklasse', p.exposition_class)
              push('Lastklasse', p.load_class)
              push('Ringsteifigkeit', p.stiffness_class_sn, v => `SN ${v}`)
              push('Norm', p.norm)
              push('Dimensionen', p.dimensions)
              push('Farbe', p.color)
              push('Einbauort', p.installation_area)
              push('Anwendungsbereich', p.application_area)
              push('Systemfamilie', p.system_family)
              push('Verbindung', p.connection_type)
              push('Dichtung', p.seal_type)
              push('Rohrlänge', p.pipe_length_mm, v => `${v} mm`)
              push('Winkel', p.angle_deg, v => `${v}°`)
              if (p.reference_product) {
                const ref = p.reference_product.trim()
                const isPassendZu = /^(passend\s+zu|formgleich|abgestimmt|gem\.|gemäß|gemaess)/i.test(ref)
                const isZb = /^(z\.?\s*b\.|wie\b|typ\b)/i.test(ref)
                const label = isPassendZu ? 'Passend zu' : (isZb ? 'Richtprodukt' : 'Referenzprodukt')
                const stripPrefix = isPassendZu
                  ? /^(passend\s+zu|formgleich|abgestimmt|gem\.|gemäß|gemaess)\s*/i
                  : (isZb ? /^(z\.?\s*b\.|wie|typ)\s*/i : null)
                const value = stripPrefix ? ref.replace(stripPrefix, '').trim() : ref
                push(label, value || ref)
              }
              if (p.compatible_systems && p.compatible_systems.length > 0) {
                push('Kompatibel mit', p.compatible_systems.join(', '))
              }
              if (p.variants && p.variants.length > 0) {
                push('Zulässige Varianten', p.variants.join(' / '))
              }
              const featureItems = p.features?.filter(f => f && f.trim()) ?? []
              const specItems = p.additional_specs?.filter(s => s && s.trim()) ?? []
              const installationItems = (p.installation_notes ?? '')
                .split(/[\n;]+/)
                .map(s => s.trim())
                .filter(Boolean)
              const isMaterial = currentPosition.position_type === 'material'
              const hasIdentifyingSpec =
                p.nominal_diameter_dn != null
                || !!p.material
                || !!p.dimensions
                || !!p.load_class
                || !!p.norm
                || !!p.compressive_strength
                || !!p.exposition_class
                || (p.features?.length ?? 0) > 0
                || (p.variants?.length ?? 0) > 0
                || (p.additional_specs?.length ?? 0) > 0
              const showIncompleteWarning = isMaterial && !hasIdentifyingSpec
              return (
                <>
                  <div className="position-head-row">
                    {productTitle && (
                      <div className="position-product-title">
                        <div className="position-product-main">{productTitle}</div>
                        {productSubtitle && (
                          <div className="position-product-sub">{productSubtitle}</div>
                        )}
                      </div>
                    )}
                    {currentPosition.quantity != null && currentPosition.unit && (
                      <div className="position-quantity-pill">
                        <span className="qty-value">{currentPosition.quantity.toLocaleString('de-DE')}</span>
                        <span className="qty-unit">{currentPosition.unit}</span>
                      </div>
                    )}
                  </div>
                  {showIncompleteWarning && (
                    <div className="position-incomplete-warning" role="alert">
                      ⚠ Parsing unvollständig — Original-LV pruefen (Material, DN, Dimensionen oder Klasse fehlen).
                    </div>
                  )}
                  {specRows.length > 0 && (
                    <div className="position-section">
                      <div className="position-section-label">Technische Daten</div>
                      <dl className="position-spec-grid">
                        {specRows.map(row => (
                          <div key={row.label} className="position-spec-row">
                            <dt>{row.label}</dt>
                            <dd>{row.value}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}
                  {(specItems.length > 0 || featureItems.length > 0 || installationItems.length > 0) && (
                    <div className="position-sections-row">
                      {specItems.length > 0 && (
                        <div className="position-section position-section--col">
                          <div className="position-section-label">Gütewerte &amp; Prüfanforderungen</div>
                          <ul className="position-features-list">
                            {specItems.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {featureItems.length > 0 && (
                        <div className="position-section position-section--col">
                          <div className="position-section-label">Ausführung</div>
                          <ul className="position-features-list">
                            {featureItems.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {installationItems.length > 0 && (
                        <div className="position-section position-section--col">
                          <div className="position-section-label">Einbauhinweise</div>
                          <ul className="position-features-list">
                            {installationItems.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                  {isService && currentPosition.description && (
                    <div className="position-section">
                      <div className="position-section-label">Beschreibung</div>
                      <div className="position-desc-text">{currentPosition.description}</div>
                    </div>
                  )}
                </>
              )
            })()}
            {projectId && (
              <span
                className={`original-lv-toggle ${showOriginalPdf ? 'open' : ''}`}
                onClick={() => setShowOriginalPdf(v => !v)}
                title="Original-LV Position anzeigen"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                  <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Original-LV
              </span>
            )}
            {currentSelectedArticles.length > 0 && (() => {
              const badges = currentSelectedArticles.map((artId, idx) => {
                const sug = currentSuggestions.find(s => s.artikel_id === artId)
                if (!sug) return null
                const isPrimary = idx === 0
                return (
                  <div key={artId} className="assigned-article-badge">
                    {isPrimary ? (
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                        <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    ) : (
                      <span className="badge-plus">+</span>
                    )}
                    <span className="badge-name">{sug.artikelname}</span>
                    <span className="badge-id">{sug.artikel_id}</span>
                    {!isPrimary && (
                      <button
                        className="badge-remove"
                        title="Zusatzartikel entfernen"
                        onClick={(e) => { e.stopPropagation(); onRemoveArticle(currentPosition!.id, artId) }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                          <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                        </svg>
                      </button>
                    )}
                  </div>
                )
              }).filter(Boolean)
              return badges.length > 0 ? (
                <>
                  <hr className="selected-article-divider" />
                  <div className="assigned-articles-badges">{badges}</div>
                </>
              ) : null
            })()}
            {isServiceView && (
              <div className="service-badge-info">Dienstleistung — nicht im Angebot enthalten</div>
            )}
          </div>

          {showOriginalPdf && projectId && (
            <div className="original-lv-panel">
              <iframe
                key={originalPdfUrl ?? `${currentPosition.ordnungszahl}-${currentPosition.source_page ?? 1}`}
                src={originalPdfUrl ?? ''}
                className="original-lv-iframe"
                title="Original LV"
              />
            </div>
          )}

          {/* Unified suggestion carousel — all suggestions in one swipeable view */}
          {!isServiceView && carouselSuggestions.length > 0 && (
            <div className="assignment-carousel-unified">
              {currentPrimaryAssignmentKey && currentSelectedArticle && pricingReferenceSuggestion && (
                <PriceAdjustmentControl
                  adjustment={currentPriceAdjustment}
                  baseUnitPrice={pricingReferenceSuggestion.price_net}
                  quantity={currentPosition.quantity}
                  currency={pricingReferenceSuggestion.currency}
                  onChange={(next) => onPriceAdjustmentChange(currentPrimaryAssignmentKey, next)}
                />
              )}
              <div className="carousel-header">
                <span className="carousel-title">
                  {carouselIndex === 0 ? 'Bester Vorschlag' : `Vorschlag ${carouselIndex + 1}`}
                </span>
                <div className="carousel-nav-compact">
                  <button
                    className="carousel-arrow-sm"
                    disabled={carouselIndex === 0}
                    onClick={() => { const i = carouselIndex - 1; setSwipeDir('up'); setCarouselIndex(i); if (carouselSuggestions[i]) handleSelectArticle(carouselSuggestions[i].artikel_id) }}
                    title="Vorheriger Vorschlag (↑)"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path d="M18 15l-6-6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <span className="carousel-indicator">{carouselIndex + 1} / {carouselSuggestions.length}</span>
                  <button
                    className="carousel-arrow-sm"
                    disabled={carouselIndex >= carouselSuggestions.length - 1}
                    onClick={() => { const i = carouselIndex + 1; setSwipeDir('down'); setCarouselIndex(i); if (carouselSuggestions[i]) handleSelectArticle(carouselSuggestions[i].artikel_id) }}
                    title="Nächster Vorschlag (↓)"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </div>
              </div>
              <div
                key={carouselIndex}
                className={`carousel-card-animated ${swipeDir === 'down' ? 'swipe-up-enter' : swipeDir === 'up' ? 'swipe-down-enter' : ''}`}
              >
                {renderSuggestionCard(
                  carouselSuggestions[carouselIndex],
                  currentPosition,
                  showLoadClass,
                  carouselIndex === 0,
                  undefined,
                  currentSelectedArticles,
                  () => handleSelectArticle(carouselSuggestions[carouselIndex].artikel_id),
                  () => {
                    setInquiryProductName(carouselSuggestions[carouselIndex].artikelname)
                    setInquiryOpen(true)
                  },
                  offerSourcesByArtikelId[carouselSuggestions[carouselIndex].artikel_id],
                )}
              </div>
              {currentPrimaryAssignmentKey && currentSelectedArticle && (
                <div className="card-flags">
                  {onToggleAlternative && (
                    <label className={`flag-toggle ${alternativeFlags[currentPrimaryAssignmentKey] ? 'flag-active flag-warn' : ''}`}>
                      <input
                        type="checkbox"
                        checked={alternativeFlags[currentPrimaryAssignmentKey] ?? false}
                        onChange={() => onToggleAlternative(currentPrimaryAssignmentKey)}
                      />
                      Alt. z. baus. Prüfung
                      {alternativeFlags[currentPrimaryAssignmentKey] && <span className="flag-badge flag-badge-warn">ALT</span>}
                    </label>
                  )}
                  {onToggleSupplierOpen && (
                    <label className={`flag-toggle ${supplierOpenFlags[currentPrimaryAssignmentKey] ? 'flag-active flag-blue' : ''}`}>
                      <input
                        type="checkbox"
                        checked={supplierOpenFlags[currentPrimaryAssignmentKey] ?? false}
                        onChange={() => onToggleSupplierOpen(currentPrimaryAssignmentKey)}
                      />
                      Lieferant offen
                      {supplierOpenFlags[currentPrimaryAssignmentKey] && <span className="flag-badge flag-badge-blue">OFFEN</span>}
                    </label>
                  )}
                </div>
              )}
              {carouselSuggestions.length > 1 && (
                <div className="carousel-dots">
                  {carouselSuggestions.map((_, i) => (
                    <button
                      key={i}
                      className={`carousel-dot ${i === carouselIndex ? 'active' : ''}`}
                      onClick={() => { setSwipeDir(i > carouselIndex ? 'down' : 'up'); setCarouselIndex(i); if (carouselSuggestions[i]) handleSelectArticle(carouselSuggestions[i].artikel_id) }}
                    />
                  ))}
                </div>
              )}
              <div className="assignment-card-tools">
                <button className="btn btn-ghost assignment-search-btn" onClick={() => setSearchOpen(true)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                    <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Manuell suchen
                </button>
                <button className="btn btn-ghost assignment-search-btn" onClick={() => setInquiryOpen(true)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Lieferantenanfrage
                </button>
              </div>
            </div>
          )}

          {!isServiceView && carouselSuggestions.length === 0 && (
            <div className="assignment-no-match">
              <div className="no-match-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                  <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <path d="M8 11h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </div>
              <p>Kein passender Artikel gefunden</p>
              <div className="no-match-actions">
                <button className="btn btn-ghost assignment-search-btn" onClick={() => setSearchOpen(true)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                    <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Manuell suchen
                </button>
                <button className="btn btn-ghost assignment-search-btn" onClick={() => setInquiryOpen(true)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Lieferantenanfrage
                </button>
              </div>
            </div>
          )}

          {/* Additional articles section */}
          {!isServiceView && currentSelectedArticles.length > 1 && (() => {
            const additionalArts = currentSelectedArticles.slice(1)
              .map(id => currentSuggestions.find(s => s.artikel_id === id))
              .filter(Boolean) as ProductSuggestion[]
            return additionalArts.length > 0 ? (
              <div className="additional-articles-section">
                <div className="additional-articles-header">Zusatzartikel</div>
                {additionalArts.map(art => {
                  const assignmentKey = additionalAssignmentKey(currentPosition.id, art.artikel_id)
                  return (
                  <div key={art.artikel_id} className="additional-article-card">
                    <div className="additional-article-info">
                      <span className="additional-article-plus">+</span>
                      <div className="additional-article-detail">
                        <strong>{art.artikelname}</strong>
                        <span className="additional-article-meta">
                          {art.artikel_id}
                          {art.hersteller && <> &middot; {art.hersteller}</>}
                          {art.price_net != null && <> &middot; {new Intl.NumberFormat('de-DE', { style: 'currency', currency: art.currency ?? 'EUR' }).format(art.price_net)} / Einheit</>}
                        </span>
                      </div>
                      <button
                        className="additional-article-remove"
                        title="Zusatzartikel entfernen"
                        onClick={() => onRemoveArticle(currentPosition!.id, art.artikel_id)}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                        </svg>
                      </button>
                    </div>
                    <div className="card-flags">
                      {onToggleAlternative && (
                        <label className={`flag-toggle ${alternativeFlags[assignmentKey] ? 'flag-active flag-warn' : ''}`}>
                          <input
                            type="checkbox"
                            checked={alternativeFlags[assignmentKey] ?? false}
                            onChange={() => onToggleAlternative(assignmentKey)}
                          />
                          Alt. z. baus. Prüfung
                          {alternativeFlags[assignmentKey] && <span className="flag-badge flag-badge-warn">ALT</span>}
                        </label>
                      )}
                      {onToggleSupplierOpen && (
                        <label className={`flag-toggle ${supplierOpenFlags[assignmentKey] ? 'flag-active flag-blue' : ''}`}>
                          <input
                            type="checkbox"
                            checked={supplierOpenFlags[assignmentKey] ?? false}
                            onChange={() => onToggleSupplierOpen(assignmentKey)}
                          />
                          Lieferant offen
                          {supplierOpenFlags[assignmentKey] && <span className="flag-badge flag-badge-blue">OFFEN</span>}
                        </label>
                      )}
                    </div>
                    <PriceAdjustmentControl
                      adjustment={priceAdjustments[assignmentKey]}
                      baseUnitPrice={art.price_net}
                      quantity={currentPosition.quantity}
                      currency={art.currency}
                      onChange={(next) => onPriceAdjustmentChange(assignmentKey, next)}
                    />
                  </div>
                )})}
              </div>
            ) : null
          })()}

          {/* Accept / Reject — always at the bottom */}
          {!isServiceView && currentPosition && (
            <div className="assignment-action-bar">
              {(currentSelectedArticle || hasAssignment(currentPosition.id)) && (
                <div className="assignment-card-tools">
                  <button className="btn btn-ghost assignment-search-btn" onClick={() => setAddArticleSearchOpen(true)}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Artikel hinzufügen
                  </button>
                </div>
              )}
              <div className="action-bar-main">
                <button className="btn btn-accept" onClick={handleContinue} disabled={!currentSelectedArticle && !hasAssignment(currentPosition.id)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Übernehmen & weiter
                </button>
                <button className="btn btn-reject" onClick={handleRejectRequest}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                  </svg>
                  Ablehnen
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Navigation — back, forward (if decided), undo */}
      {totalCount > 0 && (
        <div className="assignment-nav">
          <button
            className="btn btn-ghost"
            onClick={goPrev}
            disabled={currentIndex === 0}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Zurück
          </button>

          {currentPosition && decisions[currentPosition.id] && (
            <button className="btn btn-ghost" onClick={goNext} disabled={currentIndex >= totalCount - 1}>
              Weiter
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}

          {decisionHistory.length > 0 && (
            <button className="btn btn-ghost btn-undo" onClick={handleUndo} title="Letzte Entscheidung rückgängig machen (Strg+Z)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M3 10h10a5 5 0 015 5v0a5 5 0 01-5 5H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M7 14l-4-4 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Rückgängig
            </button>
          )}
        </div>
      )}

      {/* Rejection confirmation dialog */}
      {showRejectConfirm && currentPosition && (
        <div className="modal-backdrop" onClick={handleRejectCancel}>
          <div className="modal-box reject-confirm-modal" onClick={e => e.stopPropagation()}>
            <h3>Position ohne Zuordnung lassen?</h3>
            <p className="reject-confirm-oz">OZ {currentPosition.ordnungszahl}</p>
            <p className="reject-confirm-desc">Für diese Position wird kein Artikel im Angebot enthalten sein.</p>
            <div className="reject-confirm-actions">
              <button className="btn btn-ghost" onClick={handleRejectCancel}>Abbrechen</button>
              <button className="btn btn-reject" onClick={handleRejectConfirm}>
                Ja, ohne Zuordnung
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Product search modal */}
      {currentPosition && (
        <>
          <ProductSearchModal
            isOpen={searchOpen}
            onClose={() => setSearchOpen(false)}
            onSelect={handleManualSearchSelect}
            initialCategory={currentPosition.parameters.product_category}
            initialDn={currentPosition.parameters.nominal_diameter_dn}
          />
          <ProductSearchModal
            isOpen={addArticleSearchOpen}
            onClose={() => setAddArticleSearchOpen(false)}
            onSelect={handleAddArticleSelect}
          />
          <ProductSearchModal
            isOpen={componentSearchTarget != null}
            onClose={() => setComponentSearchTarget(null)}
            onSelect={handleComponentSearchSelect}
            initialCategory={currentPosition.parameters.product_category}
            initialDn={currentPosition.parameters.nominal_diameter_dn}
          />
          <InquiryModal
            isOpen={inquiryOpen}
            onClose={() => { setInquiryOpen(false); setInquiryProductName(null) }}
            position={currentPosition}
            projectId={projectId}
            projectName={projectName}
            productDescription={inquiryProductName}
            onSuccess={handleInquirySuccess}
          />
        </>
      )}
    </div>
  )
}

function renderSuggestionCard(
  suggestion: ProductSuggestion,
  position: LVPosition,
  showLoadClass: boolean,
  isTop: boolean,
  priceAdjustment: PriceAdjustment | undefined,
  currentSelectedArticles: string[],
  onSelect: () => void,
  onInquiry?: () => void,
  offerSourceSupplier?: string,
) {
  const stock = stockStatus(suggestion.stock)
  const isSelected = currentSelectedArticles.includes(suggestion.artikel_id)
  const adjustedUnitPrice = computeAdjustedUnitPrice(suggestion.price_net, priceAdjustment)
  const adjustedTotal = computeAdjustedTotal(adjustedUnitPrice, position.quantity)
  const isPrimary = currentSelectedArticles[0] === suggestion.artikel_id
  const showAdjusted = isPrimary && isAdjustedPrice(suggestion.price_net, adjustedUnitPrice)
  const filteredWarnings = filterSuggestionWarnings(suggestion.warnings)
  const filteredReasons = filterSuggestionReasons(suggestion.reasons)
  const hasWarnings = filteredWarnings.length > 0

  return (
    <div
      className={`assignment-suggestion ${isTop ? 'suggestion-top' : ''} ${isSelected ? 'selected' : ''}`}
      onClick={onSelect}
    >
      <div className="suggestion-header">
        <div className="suggestion-title-group">
          {suggestion.is_manual && <span className="manual-badge">Manuell gewählt</span>}
          {suggestion.is_override && <span className="override-badge">Häufig gewählt von Kollegen</span>}
          {suggestion.is_supplier_offer && <span className="offer-source-badge">Lieferantenangebot{suggestion.supplier_name ? ` · ${suggestion.supplier_name}` : ''}</span>}
          {!suggestion.is_supplier_offer && offerSourceSupplier && <span className="offer-source-badge">Aus Lieferantenangebot{offerSourceSupplier ? ` · ${offerSourceSupplier}` : ''}</span>}
          {isTop && !suggestion.is_manual && !suggestion.is_override && !suggestion.is_supplier_offer && <span className="best-badge">Bester Treffer</span>}
          <strong className="suggestion-name">{suggestion.artikelname}</strong>
        </div>
        <div className="suggestion-header-actions">
          {!suggestion.is_manual && !suggestion.is_override && !suggestion.is_supplier_offer && suggestion.score_breakdown.length > 0 ? (
            <details className="score-details" onClick={(e) => e.stopPropagation()}>
              <summary
                className="score-badge"
                style={{ '--score-color': scoreColor(suggestion.score) } as React.CSSProperties}
              >
                {suggestion.score.toFixed(0)}
              </summary>
              <div className="score-breakdown">
                {suggestion.score_breakdown.map((b) => (
                  <div key={b.component} className={`breakdown-row ${b.points > 0 ? 'row-positive' : b.points < 0 ? 'row-negative' : 'row-neutral'}`}>
                    <span className="breakdown-component">{b.component}</span>
                    <span className={`breakdown-points ${b.points > 0 ? 'positive' : b.points < 0 ? 'negative' : 'zero'}`}>
                      {b.points > 0 ? '+' : ''}{b.points}
                    </span>
                    <span className="breakdown-detail">{b.detail}</span>
                  </div>
                ))}
              </div>
            </details>
          ) : (
            !suggestion.is_manual && suggestion.score > 0 && (
              <span
                className="score-pill"
                style={{ '--score-color': scoreColor(suggestion.score) } as React.CSSProperties}
              >
                {suggestion.score.toFixed(0)}
              </span>
            )
          )}
        </div>
      </div>

      <div className="suggestion-meta">
        {suggestion.is_supplier_offer ? (
          <>
            <span>{suggestion.hersteller ?? 'Lieferant'}</span>
            {suggestion.supplier_offer_id && <><span className="meta-sep" /><span>Angebot #{suggestion.supplier_offer_id}</span></>}
          </>
        ) : (
          <>
            <span>{suggestion.artikel_id}</span>
            <span className="meta-sep" />
            <span>{suggestion.hersteller ?? 'Unbekannt'}</span>
          </>
        )}
      </div>

      <div className="param-badges">
        {suggestion.dn != null && (() => {
          const text = `${position.description ?? ''} ${position.raw_text ?? ''}`
          const dnMatch = text.match(/DN\s*(\d+)/i)
          const reqDn = position.parameters.nominal_diameter_dn ?? (dnMatch ? parseInt(dnMatch[1], 10) : null)
          return <ParamBadge
            label={`DN ${suggestion.dn}`}
            status={reqDn == null ? 'neutral' : reqDn === suggestion.dn ? 'match' : 'mismatch'}
          />
        })()}
        {suggestion.sn != null && (() => {
          const reqSn = position.parameters.stiffness_class_sn
            ?? extractSnFromText(position.description ?? '')
            ?? extractSnFromText(position.raw_text ?? '')
          return <ParamBadge
            label={`SN${suggestion.sn}`}
            status={reqSn == null ? 'neutral' : suggestion.sn! >= reqSn ? 'match' : 'mismatch'}
          />
        })()}
        {showLoadClass && suggestion.load_class && <ParamBadge
          label={suggestion.load_class}
          status={!position.parameters.load_class ? 'neutral' : position.parameters.load_class.toUpperCase() === suggestion.load_class.toUpperCase() ? 'match' : 'mismatch'}
        />}
        {shouldShowNormBadge(position, suggestion) && suggestion.norm && (
          <span className={`param-badge param-${!position.parameters.norm ? 'neutral' : suggestion.norm.toLowerCase().includes(position.parameters.norm.toLowerCase()) ? 'match' : 'mismatch'}`}>
            <DinBadge norm={suggestion.norm} />
          </span>
        )}
      </div>

      <div className="suggestion-price-stack">
        <div className="suggestion-price-row">
          <div className="price-group">
            <span className="price-main">{formatMoney(suggestion.price_net, suggestion.currency)}</span>
            <span className="price-label">EK / Einheit</span>
          </div>
          <div className="price-group">
            <span className="price-total">{formatMoney(suggestion.total_net, suggestion.currency)}</span>
            <span className="price-label">EK gesamt</span>
          </div>
        </div>
        {showAdjusted && (
          <div className="suggestion-price-row suggestion-price-row-vk">
            <div className="price-group">
              <span className="price-main">{formatMoney(adjustedUnitPrice, suggestion.currency)}</span>
              <span className="price-label">VK / Einheit</span>
            </div>
            <div className="price-group">
              <span className="price-total">{formatMoney(adjustedTotal, suggestion.currency)}</span>
              <span className="price-label">VK gesamt</span>
            </div>
          </div>
        )}
      </div>

      <div className="suggestion-stock-row">
        <span className={`stock-indicator ${stock.className}`}>
          <span className="stock-dot" />
          {stock.label}
          {suggestion.stock != null && suggestion.stock > 0 && position.quantity != null && suggestion.stock < position.quantity && (
            <span className="stock-needed"> (benötigt: {position.quantity})</span>
          )}
        </span>
        {suggestion.delivery_days != null && (
          <span className="delivery-badge">
            {suggestion.delivery_days} Tage Lieferzeit
          </span>
        )}
        {onInquiry && (suggestion.stock == null || suggestion.stock <= 0 || (position.quantity != null && suggestion.stock < position.quantity)) && (
          <button className="btn-inquiry-inline" onClick={(e) => { e.stopPropagation(); onInquiry() }} title="Lieferantenanfrage stellen">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Anfragen
          </button>
        )}
      </div>

      {hasWarnings && (
        <div className="suggestion-warnings">
          {filteredWarnings.map(w => (
            <span key={w} className="warning-chip">{w}</span>
          ))}
        </div>
      )}

      {filteredReasons.length > 0 && (() => {
        return filteredReasons.length > 0 ? (
          <div className="reason-chips">
            {filteredReasons.map((reason) => {
              const lower = reason.toLowerCase()
              const isNegative = lower.includes('abweichend') || lower.includes('weicht ab') || lower.includes('unter ') || lower.includes('≠') || lower.includes('kein') || lower.includes('nicht') || lower.includes('ohne') || lower.includes('fehlt')
              return (
                <span key={reason} className={`reason-chip ${isNegative ? 'reason-negative' : ''}`}>{reason}</span>
              )
            })}
          </div>
        ) : null
      })()}
    </div>
  )
}
