export type TechnicalParameters = {
  product_category?: string | null
  product_subcategory?: string | null
  material?: string | null
  nominal_diameter_dn?: number | null
  load_class?: string | null
  norm?: string | null
  dimensions?: string | null
  color?: string | null
  quantity?: number | null
  unit?: string | null
  reference_product?: string | null
  installation_area?: string | null
  sortiment_relevant?: boolean | null
}

export type LVPosition = {
  id: string
  ordnungszahl: string
  description: string
  raw_text: string
  quantity?: number | null
  unit?: string | null
  billable: boolean
  position_type?: 'material' | 'dienstleistung' | null
  parameters: TechnicalParameters
}

export type ScoreBreakdown = {
  component: string
  points: number
  detail: string
}

export type ProductSuggestion = {
  artikel_id: string
  artikelname: string
  hersteller?: string | null
  category?: string | null
  subcategory?: string | null
  dn?: number | null
  load_class?: string | null
  norm?: string | null
  stock?: number | null
  delivery_days?: number | null
  price_net?: number | null
  total_net?: number | null
  currency: string
  score: number
  confidence?: 'high' | 'medium' | 'low' | null
  reasons: string[]
  warnings: string[]
  score_breakdown: ScoreBreakdown[]
  is_manual?: boolean
}

export type PositionSuggestions = {
  position_id: string
  ordnungszahl: string
  description: string
  suggestions: ProductSuggestion[]
}

export type CompatibilityIssue = {
  severity: string
  rule: string
  message: string
  positions: string[]
}

export type DuplicateInfo = {
  is_duplicate: boolean
  project_id?: number | null
  project_name?: string | null
  created_at?: string | null
  total_positions?: number | null
}

export type ParseResponse = {
  positions: LVPosition[]
  total_positions: number
  billable_positions: number
  service_positions: number
  duplicate?: DuplicateInfo | null
}

export type SuggestionResponse = {
  suggestions: PositionSuggestions[]
  compatibility_issues: CompatibilityIssue[]
}

export type ExportWarning = {
  position_id: string
  ordnungszahl: string
  reason: string
}

export type ExportPreviewResponse = {
  included_count: number
  total_count: number
  skipped_positions: ExportWarning[]
  total_net: number
}

export type ProductSearchResult = {
  artikel_id: string
  artikelname: string
  hersteller?: string | null
  kategorie?: string | null
  nennweite_dn?: number | null
  belastungsklasse?: string | null
  vk_listenpreis_netto?: number | null
  lager_gesamt?: number | null
  waehrung?: string | null
}

export type AnalysisStep = 'idle' | 'uploading' | 'parsing' | 'enriching' | 'matching' | 'done' | 'error'

export type AppView = 'analysis' | 'archive'

export type ProjectSummary = {
  id: number
  filename: string | null
  project_name: string | null
  total_positions: number
  billable_positions: number
  service_positions: number
  created_at: string
}

export type ProjectDetailResponse = {
  project: ProjectSummary
  positions: LVPosition[]
}
