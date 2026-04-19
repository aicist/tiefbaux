export type ComponentRequirement = {
  component_name: string
  description?: string | null
  product_category?: string | null
  product_subcategory?: string | null
  nominal_diameter_dn?: number | null
  secondary_nominal_diameter_dn?: number | null
  quantity?: number | null
  unit?: string | null
  material?: string | null
  system_family?: string | null
  load_class?: string | null
  dimensions?: string | null
  connection_type?: string | null
  installation_area?: string | null
  compressive_strength?: string | null
  exposition_class?: string | null
  additional_specs?: string[] | null
}

export type TechnicalParameters = {
  article_type?: string | null
  product_category?: string | null
  product_subcategory?: string | null
  material?: string | null
  nominal_diameter_dn?: number | null
  secondary_nominal_diameter_dn?: number | null
  load_class?: string | null
  norm?: string | null
  dimensions?: string | null
  color?: string | null
  quantity?: number | null
  unit?: string | null
  reference_product?: string | null
  installation_area?: string | null
  stiffness_class_sn?: number | null
  sortiment_relevant?: boolean | null
  pipe_length_mm?: number | null
  angle_deg?: number | null
  application_area?: string | null
  system_family?: string | null
  connection_type?: string | null
  seal_type?: string | null
  compatible_systems?: string[] | null
  components?: ComponentRequirement[] | null
  variants?: string[] | null
  features?: string[] | null
  installation_notes?: string | null
  compressive_strength?: string | null
  exposition_class?: string | null
  additional_specs?: string[] | null
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
  source_page?: number | null
  source_y?: number | null
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
  sn?: number | null
  load_class?: string | null
  norm?: string | null
  material?: string | null
  angle_deg?: number | null
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
  is_override?: boolean
  is_supplier_offer?: boolean
  is_bogen_fallback?: boolean
  supplier_offer_id?: number | null
  supplier_name?: string | null
}

export type ComponentSuggestions = {
  component_name: string
  quantity: number
  suggestions: ProductSuggestion[]
}

export type PositionSuggestions = {
  position_id: string
  ordnungszahl: string
  description: string
  suggestions: ProductSuggestion[]
  component_suggestions?: ComponentSuggestions[] | null
}

export type ProjectMetadata = {
  bauvorhaben?: string | null
  objekt_nr?: string | null
  submission_date?: string | null
  auftraggeber?: string | null
  kunde_name?: string | null
  kunde_adresse?: string | null
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
  metadata?: ProjectMetadata | null
}

export type SuggestionResponse = {
  suggestions: PositionSuggestions[]
}

export type ExportWarning = {
  position_id: string
  ordnungszahl: string
  reason: string
}

export type OfferEmailDefaults = {
  customer_email?: string | null
  subject: string
  body: string
}

export type ExportPreviewResponse = {
  included_count: number
  total_count: number
  skipped_positions: ExportWarning[]
  total_net: number
  email_defaults?: OfferEmailDefaults | null
}

export type SendOfferEmailResponse = {
  sent: boolean
  saved: boolean
  detail?: string | null
}

export type PriceAdjustmentMode = 'percent' | 'absolute'

export type PriceAdjustment = {
  mode: PriceAdjustmentMode
  value: string
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
  steifigkeitsklasse_sn?: string | null
  norm_primaer?: string | null
  werkstoff?: string | null
}

export type ProductSearchResponse = {
  items: ProductSearchResult[]
  has_more: boolean
}

export type AnalysisStep = 'idle' | 'uploading' | 'parsing' | 'enriching' | 'matching' | 'done' | 'error'

export type AppView = 'analysis' | 'archive' | 'radar' | 'admin'

export type User = {
  id: number
  email: string
  name: string
  role: 'admin' | 'mitarbeiter'
  active: boolean
}

export type ProjectSummary = {
  id: number
  filename: string | null
  project_name: string | null
  projekt_nr?: string | null
  total_positions: number
  billable_positions: number
  service_positions: number
  created_at: string
  bauvorhaben?: string | null
  objekt_nr?: string | null
  submission_date?: string | null
  kunde_name?: string | null
  status?: 'neu' | 'offen' | 'anfrage_offen' | 'gerechnet' | string
  anfrage_art?: 'submission' | 'bedarf' | string
  offer_pdf_path?: string | null
  assigned_user_name?: string | null
  last_editor_name?: string | null
  last_edited_at?: string | null
}

export type ObjektSummary = {
  id: number
  slug: string
  bauvorhaben: string | null
  objekt_nr: string | null
  auftraggeber: string | null
  submission_date: string | null
  created_at: string
  kunden_count: number
  project_count: number
  latest_project_created_at: string | null
}

export type KundenOrdnerSummary = {
  kunde_id: number
  slug: string
  name: string
  display_name: string | null
  email_domain: string | null
  project_count: number
  latest_project_created_at: string | null
}

export type ObjektDetailResponse = {
  objekt: ObjektSummary
  kunden: KundenOrdnerSummary[]
}

export type KundenProjektListResponse = {
  objekt: ObjektSummary
  kunde: KundenOrdnerSummary
  projects: ProjectSummary[]
}

export type AssignmentUiState = {
  active_filter: 'alle' | 'zugeordnet' | 'offen' | 'dienstleistung'
  current_position_id?: string | null
  is_finished?: boolean
}

export type ProjectDetailResponse = {
  project: ProjectSummary
  positions: LVPosition[]
  metadata?: ProjectMetadata | null
  selections?: Record<string, string[]> | null
  decisions?: Record<string, 'accepted' | 'rejected' | 'inquiry_pending'> | null
  component_selections?: Record<string, string> | null
  ui_state?: AssignmentUiState | null
}

export type UndoAction =
  | { type: 'select'; positionId: string; previousArticleIds: string[] | undefined }
  | { type: 'deselect'; positionId: string; previousArticleIds: string[] }

export type Supplier = {
  id: number
  name: string
  email: string
  phone?: string | null
  categories: string[]
  notes?: string | null
  active: boolean
}

export type Tender = {
  id: number
  external_id: string
  title: string
  description?: string | null
  auftraggeber?: string | null
  ort?: string | null
  cpv_codes: string[]
  submission_deadline?: string | null
  publication_date?: string | null
  url?: string | null
  status: 'neu' | 'relevant' | 'irrelevant' | 'analysiert'
  relevance_score: number
  lat?: number | null
  lng?: number | null
  created_at?: string | null
  project_id?: number | null
}

export type SupplierInquiry = {
  id: number
  supplier_id: number
  supplier_name: string
  supplier_email: string
  project_id?: number | null
  position_id?: string | null
  ordnungszahl?: string | null
  product_description: string
  quantity?: number | null
  unit?: string | null
  status: 'offen' | 'angefragt' | 'angebot_erhalten'
  sent_at?: string | null
  email_subject?: string | null
  email_body?: string | null
  notes?: string | null
  created_at: string
}

export type SupplierOffer = {
  id: number
  inquiry_id?: number | null
  supplier_id: number
  supplier_name: string
  project_id?: number | null
  position_id?: string | null
  ordnungszahl?: string | null
  article_name: string
  article_number?: string | null
  unit_price?: number | null
  total_price?: number | null
  delivery_days?: number | null
  quantity?: number | null
  unit?: string | null
  notes?: string | null
  source: 'manual' | 'email_auto' | 'pdf_import'
  status: 'neu' | 'zugeordnet' | 'abgelehnt'
  created_at: string
}

export type BundledEmailPreview = {
  supplier_id: number
  supplier_name: string
  supplier_email: string
  subject: string
  body: string
  inquiry_ids: number[]
  positions: Array<{
    ordnungszahl?: string | null
    product_description: string
    quantity?: number | null
    unit?: string | null
  }>
}

export type InboxSyncResult = {
  status: string
  mailbox?: string
  processed_count?: number
  ignored_count?: number
  new_lv_created?: number
  new_lv_skipped?: number
  offers_matched?: number
  offers_unmatched?: number
  detail?: string
  errors?: string[]
}

export type InboxSyncStatus = {
  running: boolean
  last_started_at?: string | null
  last_finished_at?: string | null
  last_result?: InboxSyncResult | null
}
