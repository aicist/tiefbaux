type PdfViewerOptions = {
  page?: number
  top?: number | null
  search?: string | null
}

export function buildEmbeddedPdfViewerUrl(baseUrl: string, options: PdfViewerOptions = {}): string {
  const page = options.page != null ? Math.max(1, options.page) : null
  const top = Math.max(0, Math.round(options.top ?? 0))
  // Browser PDF viewers are more reliable with numeric zoom when x/y offsets are provided.
  const zoomValue = top > 0 ? `125,0,${top}` : 'page-width'

  const parts = [
    `zoom=${zoomValue}`,
    'pagemode=none',
    'toolbar=0',
    'navpanes=0',
    'scrollbar=0',
  ]
  if (page != null) {
    parts.unshift(`page=${page}`)
  }

  const search = options.search?.trim()
  if (search) {
    parts.push(`search=${encodeURIComponent(search)}`)
  }

  return `${baseUrl}#${parts.join('&')}`
}
