import type { CompatibilityIssue, ExportPreviewResponse, LVPosition, ParseResponse, PositionSuggestions, ProductSearchResult, ProjectDetailResponse, ProjectSummary, Supplier, SupplierInquiry, SuggestionResponse, TechnicalParameters } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'

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

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
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
    fetch(`${API_BASE}/parse-lv`, { method: 'POST', body: formData, signal }),
  )
  return handleResponse<ParseResponse>(response)
}

export async function fetchSuggestions(positions: LVPosition[], signal?: AbortSignal): Promise<SuggestionResponse> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/suggestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions }),
      signal,
    }),
  )
  return handleResponse<SuggestionResponse>(response)
}

export async function fetchSingleSuggestions(position: LVPosition): Promise<PositionSuggestions> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/suggestions/single`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(position),
    }),
  )
  return handleResponse<PositionSuggestions>(response)
}

export async function fetchExportPreview(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string>,
  customerName: string,
  projectName: string,
  customUnitPrices?: Record<string, number>,
): Promise<ExportPreviewResponse> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/export-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
        customer_name: customerName,
        project_name: projectName,
        custom_unit_prices: customUnitPrices,
      }),
    }),
  )
  return handleResponse<ExportPreviewResponse>(response)
}

export async function exportOffer(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string>,
  customerName: string,
  projectName: string,
  customUnitPrices?: Record<string, number>,
): Promise<Blob> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/export-offer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
        customer_name: customerName,
        project_name: projectName,
        custom_unit_prices: customUnitPrices,
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

export async function searchProducts(params: {
  q?: string
  category?: string
  dn?: number
}): Promise<ProductSearchResult[]> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.category) query.set('category', params.category)
  if (params.dn != null) query.set('dn', String(params.dn))

  const response = await wrapFetch(
    fetch(`${API_BASE}/products/search?${query.toString()}`),
  )
  return handleResponse<ProductSearchResult[]>(response)
}

export async function checkCompatibility(
  positions: LVPosition[],
  selectedArticleIds: Record<string, string>,
): Promise<CompatibilityIssue[]> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/compatibility-check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        positions,
        selected_article_ids: selectedArticleIds,
      }),
    }),
  )
  return handleResponse<CompatibilityIssue[]>(response)
}

export async function fetchProjects(q?: string): Promise<ProjectSummary[]> {
  const params = q ? `?q=${encodeURIComponent(q)}` : ''
  const response = await wrapFetch(fetch(`${API_BASE}/projects${params}`))
  return handleResponse<ProjectSummary[]>(response)
}

export async function fetchProject(projectId: number): Promise<ProjectDetailResponse> {
  const response = await wrapFetch(fetch(`${API_BASE}/projects/${projectId}`))
  return handleResponse<ProjectDetailResponse>(response)
}

export async function deleteProject(projectId: number): Promise<void> {
  const response = await wrapFetch(
    fetch(`${API_BASE}/projects/${projectId}`, { method: 'DELETE' }),
  )
  if (!response.ok) {
    await handleResponse(response)
  }
}

export async function saveSelections(projectId: number, selectedArticleIds: Record<string, string>): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/projects/save-selections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, selected_article_ids: selectedArticleIds }),
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  )
}

export function getProjectPdfUrl(projectId: number): string {
  return `${API_BASE}/projects/${projectId}/pdf`
}

// --- Supplier & Inquiry ---

export async function fetchSuppliers(): Promise<Supplier[]> {
  const response = await wrapFetch(fetch(`${API_BASE}/suppliers`))
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
      headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  )
  return handleResponse<SupplierInquiry>(response)
}

export async function fetchInquiries(projectId?: number): Promise<SupplierInquiry[]> {
  const params = projectId != null ? `?project_id=${projectId}` : ''
  const response = await wrapFetch(fetch(`${API_BASE}/inquiries${params}`))
  return handleResponse<SupplierInquiry[]>(response)
}

export async function updateInquiryStatus(
  inquiryId: number,
  status: string,
  notes?: string,
): Promise<void> {
  await wrapFetch(
    fetch(`${API_BASE}/inquiries/${inquiryId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, notes }),
    }),
  )
}
