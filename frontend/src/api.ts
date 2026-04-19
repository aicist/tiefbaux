import type { AssignmentUiState, ExportPreviewResponse, InboxSyncResult, InboxSyncStatus, KundenProjektListResponse, LVPosition, ObjektDetailResponse, ObjektSummary, ParseResponse, PositionSuggestions, ProductSearchResponse, ProjectDetailResponse, ProjectSummary, Supplier, SupplierInquiry, SupplierOffer, SuggestionResponse, TechnicalParameters, Tender, User } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const AUTH_BASE = API_BASE.replace(/\/api$/, '/api/auth')

// --- Auth token management ---

const TOKEN_KEY = 'tiefbaux_token'

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setAuthToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function jsonAuthHeaders(): Record<string, string> {
  return { 'Content-Type': 'application/json', ...authHeaders() }
}

export class ApiError extends Error {
  type: 'network' | 'api' | 'validation' | 'timeout'
  status?: number

  constructor(
    message: string,
    type: 'network' | 'api' | 'validation' | 'timeout',
    status?: number,
  ) {
    super(message)
    this.type = type
    this.status = status
  }
}

async function handleResponse<T>(response: Response, opts?: { skipAuthExpired?: boolean }): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) {
      if (!opts?.skipAuthExpired && getAuthToken()) {
        // Only fire auth-expired if we actually had a token (real session expiry)
        clearAuthToken()
        window.dispatchEvent(new Event('auth-expired'))
      }
      let detail = opts?.skipAuthExpired ? 'Anmeldung fehlgeschlagen' : 'Sitzung abgelaufen'
      try { const b = await response.json(); detail = b.detail ?? detail } catch {}
      throw new ApiError(detail, 'api', 401)
    }
    let detail = ''
    try {
      const body = await response.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      detail = await response.text()
    }
    if (response.status === 400 || response.status === 422) {
      throw new ApiError(detail || 'Ungültige Eingabedaten', 'validation', response.status)
    }
    throw new ApiError(
      detail || `Serverfehler (${response.status})`,
      'api',
      response.status,
    )
  }
  return (await response.json()) as T
}

function wrapFetch(promise: Promise<Response>): Promise<Response> {
  return promise.catch((err) => {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    throw new ApiError('Server nicht erreichbar. Bitte prüfen Sie die Verbindung.', 'network')
  })
}

export async function parseLV(file: File, signal?: AbortSignal): Promise<ParseResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await wrapFetch(
    fetch(`${API_BASE}/parse-lv`, { method: 'POST', body: formData, signal, headers: authHeaders() }),
  )
  return handleResponse<ParseResponse>(response)
}

export async function fetchSuggestions(positions: LVPosition[], signal?: AbortSignal, projectId?: number | null): Promise<SuggestionResponse> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/suggestions`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ positions, project_id: projectId ?? undefined }),
      signal,
    }),
  )
  return handleResponse<SuggestionResponse>(response)
}

export async function fetchSingleSuggestions(position: LVPosition): Promise<PositionSuggestions> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/suggestions/single`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(position),
    }),
  )
  return handleResponse<PositionSuggestions>(response)
}

export async function fetchExportPreview(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string[]>,
  customerName: string,
  projectName: string,
  customUnitPrices?: Record<string, number>,
  alternativeFlags?: Record<string, boolean>,
  supplierOpenFlags?: Record<string, boolean>,
  assignmentKeysByPosition?: Record<string, string[]>,
  rejectedPositionIds?: string[],
): Promise<ExportPreviewResponse> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/export-preview`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
        customer_name: customerName,
        project_name: projectName,
        custom_unit_prices: customUnitPrices,
        alternative_flags: alternativeFlags,
        supplier_open_flags: supplierOpenFlags,
        assignment_keys_by_position: assignmentKeysByPosition,
        rejected_position_ids: rejectedPositionIds,
      }),
    }),
  )
  return handleResponse<ExportPreviewResponse>(response)
}

export async function exportOffer(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string[]>,
  customerName: string,
  projectName: string,
  customUnitPrices?: Record<string, number>,
  alternativeFlags?: Record<string, boolean>,
  supplierOpenFlags?: Record<string, boolean>,
  assignmentKeysByPosition?: Record<string, string[]>,
  projectId?: number | null,
  rejectedPositionIds?: string[],
): Promise<Blob> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/export-offer`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
        customer_name: customerName,
        project_name: projectName,
        custom_unit_prices: customUnitPrices,
        alternative_flags: alternativeFlags,
        supplier_open_flags: supplierOpenFlags,
        assignment_keys_by_position: assignmentKeysByPosition,
        project_id: projectId ?? undefined,
        rejected_position_ids: rejectedPositionIds,
      }),
    }),
  )

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = body.detail ?? ''
    } catch {
      detail = await response.text()
    }
    throw new ApiError(detail || 'Export fehlgeschlagen', 'api', response.status)
  }

  return await response.blob()
}

export async function fetchOfferPdfPreview(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string[]>,
  customerName: string,
  projectName: string,
  customUnitPrices?: Record<string, number>,
  alternativeFlags?: Record<string, boolean>,
  supplierOpenFlags?: Record<string, boolean>,
  assignmentKeysByPosition?: Record<string, string[]>,
  projectId?: number | null,
  rejectedPositionIds?: string[],
): Promise<Blob> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/export-offer/preview-pdf`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
        customer_name: customerName,
        project_name: projectName,
        custom_unit_prices: customUnitPrices,
        alternative_flags: alternativeFlags,
        supplier_open_flags: supplierOpenFlags,
        assignment_keys_by_position: assignmentKeysByPosition,
        project_id: projectId ?? undefined,
        rejected_position_ids: rejectedPositionIds,
      }),
    }),
  )
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = body.detail ?? ''
    } catch {
      detail = await response.text()
    }
    throw new ApiError(detail || 'PDF-Vorschau fehlgeschlagen', 'api', response.status)
  }
  return await response.blob()
}

export async function sendOfferEmail(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string[]>,
  customerName: string,
  projectName: string,
  customerEmail: string,
  emailSubject: string,
  emailBody: string,
  customUnitPrices?: Record<string, number>,
  alternativeFlags?: Record<string, boolean>,
  supplierOpenFlags?: Record<string, boolean>,
  assignmentKeysByPosition?: Record<string, string[]>,
  projectId?: number | null,
  rejectedPositionIds?: string[],
): Promise<import('./types').SendOfferEmailResponse> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/export-offer/send-email`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
        customer_name: customerName,
        project_name: projectName,
        customer_email: customerEmail,
        email_subject: emailSubject,
        email_body: emailBody,
        custom_unit_prices: customUnitPrices,
        alternative_flags: alternativeFlags,
        supplier_open_flags: supplierOpenFlags,
        assignment_keys_by_position: assignmentKeysByPosition,
        project_id: projectId ?? undefined,
        rejected_position_ids: rejectedPositionIds,
      }),
    }),
  )
  return handleResponse<import('./types').SendOfferEmailResponse>(response)
}

export async function searchProducts(params: {
  q?: string
  category?: string
  dn?: number
  sn?: string
  load_class?: string
  material?: string
  angle?: number
  limit?: number
  offset?: number
}): Promise<ProductSearchResponse> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.category) query.set('category', params.category)
  if (params.dn != null) query.set('dn', String(params.dn))
  if (params.sn) query.set('sn', params.sn)
  if (params.load_class) query.set('load_class', params.load_class)
  if (params.material) query.set('material', params.material)
  if (params.angle != null) query.set('angle', String(params.angle))
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.offset != null) query.set('offset', String(params.offset))

  const response = await wrapFetch(
    fetch(`${API_BASE}/products/search?${query.toString()}`, { headers: authHeaders() }),
  )
  return handleResponse<ProductSearchResponse>(response)
}


export async function fetchProjects(q?: string): Promise<ProjectSummary[]> {
  const params = q ? `?q=${encodeURIComponent(q)}` : ''
  const response = await wrapFetch(fetch(`${API_BASE}/projects${params}`, { headers: authHeaders() }))
  return handleResponse<ProjectSummary[]>(response)
}

export async function fetchObjekte(q?: string): Promise<ObjektSummary[]> {
  const params = q ? `?q=${encodeURIComponent(q)}` : ''
  const response = await wrapFetch(fetch(`${API_BASE}/objekte${params}`, { headers: authHeaders() }))
  return handleResponse<ObjektSummary[]>(response)
}

export async function fetchObjekt(objektId: number): Promise<ObjektDetailResponse> {
  const response = await wrapFetch(fetch(`${API_BASE}/objekte/${objektId}`, { headers: authHeaders() }))
  return handleResponse<ObjektDetailResponse>(response)
}

export async function fetchKundeProjects(objektId: number, kundeId: number): Promise<KundenProjektListResponse> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/objekte/${objektId}/kunden/${kundeId}/projects`, { headers: authHeaders() }),
  )
  return handleResponse<KundenProjektListResponse>(response)
}

export async function fetchProject(projectId: number): Promise<ProjectDetailResponse> {
  const response = await wrapFetch(fetch(`${API_BASE}/projects/${projectId}`, { headers: authHeaders() }))
  return handleResponse<ProjectDetailResponse>(response)
}

export async function deleteProject(projectId: number): Promise<void> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/projects/${projectId}`, { method: 'DELETE', headers: authHeaders() }),
  )
  if (!response.ok) {
    await handleResponse(response)
  }
}

export async function updateObjekt(
  objektId: number,
  updates: { bauvorhaben?: string | null; objekt_nr?: string | null; auftraggeber?: string | null; submission_date?: string | null },
): Promise<ObjektSummary> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/objekte/${objektId}`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(updates),
    }),
  )
  return handleResponse<ObjektSummary>(response)
}

export async function deleteObjekt(objektId: number): Promise<{ ok: boolean; deleted_projects: number }> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/objekte/${objektId}`, { method: 'DELETE', headers: authHeaders() }),
  )
  return handleResponse<{ ok: boolean; deleted_projects: number }>(response)
}

export async function updateKunde(
  kundeId: number,
  updates: { name?: string; display_name?: string | null; email_domain?: string | null; address?: string | null },
): Promise<import('./types').KundenOrdnerSummary> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/kunden/${kundeId}`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(updates),
    }),
  )
  return handleResponse<import('./types').KundenOrdnerSummary>(response)
}

export async function deleteKunde(kundeId: number): Promise<{ ok: boolean; deleted_projects: number }> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/kunden/${kundeId}`, { method: 'DELETE', headers: authHeaders() }),
  )
  return handleResponse<{ ok: boolean; deleted_projects: number }>(response)
}

export async function updateProject(
  projectId: number,
  updates: { project_name?: string | null; bauvorhaben?: string | null; submission_date?: string | null; anfrage_art?: string | null },
): Promise<ProjectSummary> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/projects/${projectId}`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(updates),
    }),
  )
  return handleResponse<ProjectSummary>(response)
}

export async function saveSelections(projectId: number, selectedArticleIds: Record<string, string[]>): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/projects/save-selections`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ project_id: projectId, selected_article_ids: selectedArticleIds }),
    }),
  )
}

export async function saveWorkstate(data: {
  project_id: number
  selected_article_ids: Record<string, string[]>
  decisions: Record<string, 'accepted' | 'rejected' | 'inquiry_pending'>
  component_selections: Record<string, string>
  ui_state?: AssignmentUiState | null
}): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/projects/save-workstate`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
}

export async function recordOverride(data: {
  position_description: string
  ordnungszahl?: string
  category?: string | null
  dn?: number | null
  material?: string | null
  chosen_artikel_id: string
}): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/overrides`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
}

export function getProjectPdfUrl(projectId: number): string {
  const token = getAuthToken()
  return `${API_BASE}/projects/${projectId}/pdf${token ? `?token=${token}` : ''}`
}

export function getProjectPdfAnchorUrl(
  projectId: number,
  options?: { oz?: string | null; page?: number | null; top?: number | null; window?: number | null },
): string {
  const token = getAuthToken()
  const params = new URLSearchParams()
  if (token) params.set('token', token)
  const oz = options?.oz?.trim()
  if (oz) params.set('oz', oz)
  const page = options?.page
  if (page != null) params.set('page', String(Math.max(1, Math.trunc(page))))
  const top = options?.top
  if (top != null) params.set('top', String(Math.max(0, Math.trunc(top))))
  const win = options?.window
  if (win != null) params.set('window', String(Math.max(120, Math.trunc(win))))
  const query = params.toString()
  return `${API_BASE}/projects/${projectId}/pdf-anchor${query ? `?${query}` : ''}`
}

export function getProjectOfferPdfUrl(projectId: number): string {
  const token = getAuthToken()
  return `${API_BASE}/projects/${projectId}/offer-pdf${token ? `?token=${token}` : ''}`
}

// --- Supplier & Inquiry ---

export async function fetchSuppliers(): Promise<Supplier[]> {
  const response = await wrapFetch(fetch(`${API_BASE}/suppliers`, { headers: authHeaders() }))
  return handleResponse<Supplier[]>(response)
}

export async function createSupplier(data: {
  name: string
  email: string
  phone?: string
  categories?: string[]
  notes?: string
}): Promise<Supplier> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/suppliers`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<Supplier>(response)
}

export async function createInquiry(data: {
  supplier_id: number
  project_id?: number | null
  position_id?: string | null
  ordnungszahl?: string | null
  product_description: string
  technical_params?: TechnicalParameters | null
  quantity?: number | null
  unit?: string | null
  custom_message?: string | null
  send_email?: boolean
}): Promise<SupplierInquiry> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/inquiries`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<SupplierInquiry>(response)
}

export async function createInquiryBatch(data: {
  supplier_ids: number[]
  project_id?: number | null
  position_id?: string | null
  ordnungszahl?: string | null
  product_description: string
  technical_params?: TechnicalParameters | null
  quantity?: number | null
  unit?: string | null
  custom_message?: string | null
}): Promise<SupplierInquiry[]> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/inquiries/batch`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<SupplierInquiry[]>(response)
}

export async function sendBatchInquiries(
  projectId: number,
  emailOverrides?: Record<number, { subject: string; body: string }>,
  simulateOnly?: boolean,
): Promise<{ sent_count: number; failed_count: number }> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/inquiries/send-batch`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        project_id: projectId,
        email_overrides: emailOverrides ?? {},
        simulate_only: Boolean(simulateOnly),
      }),
    }),
  )
  return handleResponse<{ sent_count: number; failed_count: number }>(response)
}

export async function previewBundledInquiries(projectId: number): Promise<import('./types').BundledEmailPreview[]> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/inquiries/preview-bundled`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ project_id: projectId }),
    }),
  )
  return handleResponse<import('./types').BundledEmailPreview[]>(response)
}

export async function fetchInquiries(projectId?: number): Promise<SupplierInquiry[]> {
  const params = projectId != null ? `?project_id=${projectId}` : ''
  const response = await wrapFetch(fetch(`${API_BASE}/inquiries${params}`, { headers: authHeaders() }))
  return handleResponse<SupplierInquiry[]>(response)
}

export async function updateInquiryContent(
  inquiryId: number,
  updates: { email_subject?: string; email_body?: string; product_description?: string },
): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/inquiries/${inquiryId}/content`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(updates),
    }),
  )
}

export async function updateInquiryStatus(
  inquiryId: number,
  status: string,
  notes?: string,
): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/inquiries/${inquiryId}/status`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ status, notes }),
    }),
  )
}

export async function cleanupOpenInquiriesForPosition(
  projectId: number,
  positionId: string,
): Promise<{ ok: boolean; deleted_count: number }> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/inquiries/cleanup-open`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ project_id: projectId, position_id: positionId }),
    }),
  )
  return handleResponse<{ ok: boolean; deleted_count: number }>(response)
}

export async function syncDemoInbox(maxMessages = 20): Promise<InboxSyncResult> {
  const params = new URLSearchParams({ max_messages: String(Math.max(1, Math.min(maxMessages, 100))) })
  const response = await wrapFetch(
    fetch(`${API_BASE}/inbox/sync-demo?${params.toString()}`, {
      method: 'POST',
      headers: authHeaders(),
    }),
  )
  return handleResponse<InboxSyncResult>(response)
}

export async function fetchInboxSyncStatus(): Promise<InboxSyncStatus> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/inbox/sync-status`, { headers: authHeaders() }),
  )
  return handleResponse<InboxSyncStatus>(response)
}


// ── Supplier Offers ──

export async function createSupplierOffer(data: {
  inquiry_id?: number | null
  supplier_id: number
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
  source?: string
}): Promise<SupplierOffer> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/offers`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<SupplierOffer>(response)
}

export async function fetchSupplierOffers(
  projectId?: number,
  positionId?: string,
): Promise<SupplierOffer[]> {
  const params = new URLSearchParams()
  if (projectId != null) params.set('project_id', String(projectId))
  if (positionId != null) params.set('position_id', positionId)
  const response = await wrapFetch(
    fetch(`${API_BASE}/offers?${params.toString()}`, { headers: authHeaders() }),
  )
  return handleResponse<SupplierOffer[]>(response)
}

export async function updateSupplierOfferStatus(
  offerId: number,
  status: 'neu' | 'zugeordnet' | 'abgelehnt',
): Promise<SupplierOffer> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/offers/${offerId}/status`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ status }),
    }),
  )
  return handleResponse<SupplierOffer>(response)
}

// ── Objektradar / Tenders ──

export async function fetchTenders(status?: string, minRelevance?: number): Promise<Tender[]> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (minRelevance && minRelevance > 0) params.set('min_relevance', String(minRelevance))
  const qs = params.toString()
  return handleResponse<Tender[]>(
    await wrapFetch(fetch(`${API_BASE}/tenders${qs ? '?' + qs : ''}`, { headers: authHeaders() })),
  )
}

export async function refreshTenders(): Promise<{ status: string }> {
  return handleResponse(
    await wrapFetch(
      fetch(`${API_BASE}/tenders/refresh`, { method: 'POST', headers: authHeaders() }),
    ),
  )
}

export async function getRefreshStatus(): Promise<{ running: boolean; last_result: any }> {
  return handleResponse(
    await wrapFetch(fetch(`${API_BASE}/tenders/refresh-status`, { headers: authHeaders() })),
  )
}

export async function updateTenderStatus(tenderId: number, status: string): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/tenders/${tenderId}`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ status }),
    }),
  )
}


// ── Auth ──

export async function login(email: string, password: string): Promise<{ access_token: string; user: User }> {
  const body = new URLSearchParams({ username: email, password })
  const response = await wrapFetch(
    fetch(`${AUTH_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    }),
  )
  return handleResponse<{ access_token: string; user: User }>(response, { skipAuthExpired: true })
}

export async function fetchMe(): Promise<User> {
  const response = await wrapFetch(fetch(`${AUTH_BASE}/me`, { headers: authHeaders() }))
  return handleResponse<User>(response)
}

export async function fetchUsers(): Promise<User[]> {
  const response = await wrapFetch(fetch(`${AUTH_BASE}/users`, { headers: authHeaders() }))
  return handleResponse<User[]>(response)
}

export async function createUser(data: { email: string; password: string; name: string; role: string }): Promise<User> {
  const response = await wrapFetch(
    fetch(`${AUTH_BASE}/users`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<User>(response)
}

export async function updateUser(userId: number, data: { name?: string; role?: string; active?: boolean; password?: string }): Promise<User> {
  const response = await wrapFetch(
    fetch(`${AUTH_BASE}/users/${userId}`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<User>(response)
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await wrapFetch(
    fetch(`${AUTH_BASE}/me/password`, {
      method: 'PATCH',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  )
}

export async function assignProject(projectId: number, userId: number | null): Promise<void> {
  await wrapFetch(
    fetch(`${AUTH_BASE}/projects/${projectId}/assign`, {
      method: 'POST',
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ user_id: userId }),
    }),
  )
}
