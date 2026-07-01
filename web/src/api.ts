export interface Pm3DocumentRecord {
  readonly id: string
  readonly fileName: string
  readonly mimeType: string
  readonly fileHash: string
  readonly s3Key: string
  readonly status: string
  readonly parsedResult: unknown
  readonly errorMessage?: string | null
  readonly createdAt: string
  readonly updatedAt: string
}

interface ApiResponse<T> {
  readonly success: boolean
  readonly data?: T
  readonly error?: string
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text()
  if (!text.trim()) {
    throw new Error(response.ok ? 'API returned an empty response' : `API request failed: ${response.status} ${response.statusText || ''}`.trim())
  }

  let payload: ApiResponse<T>
  try {
    payload = JSON.parse(text) as ApiResponse<T>
  } catch {
    throw new Error(response.ok ? 'API returned invalid JSON' : `API request failed: ${response.status} ${response.statusText || ''}`.trim())
  }

  if (!response.ok || !payload.success || payload.data === undefined) {
    throw new Error(payload.error || `API request failed: ${response.status}`)
  }
  return payload.data
}

export async function listPm3Documents(): Promise<Pm3DocumentRecord[]> {
  const response = await fetch('/api/pm3/documents')
  return readJson<Pm3DocumentRecord[]>(response)
}

export async function getPm3Document(id: string): Promise<Pm3DocumentRecord> {
  const response = await fetch(`/api/pm3/documents/${encodeURIComponent(id)}`)
  return readJson<Pm3DocumentRecord>(response)
}

export async function getPm3DocumentDownloadUrl(id: string): Promise<string> {
  const response = await fetch(`/api/pm3/documents/${encodeURIComponent(id)}/download`)
  const payload = await readJson<{ readonly url: string }>(response)
  return payload.url
}

export async function deletePm3Document(id: string): Promise<Pm3DocumentRecord> {
  const response = await fetch(`/api/pm3/documents/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  return readJson<Pm3DocumentRecord>(response)
}

export async function uploadPm3Document(input: {
  readonly file: File
  readonly modelSettings: {
    readonly apiUrl: string
    readonly modelName: string
    readonly apiKey: string
  }
  readonly parsedResult?: unknown
}): Promise<Pm3DocumentRecord> {
  const bytes = new Uint8Array(await input.file.arrayBuffer())
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  const hash = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  const data = btoa(binary)

  const response = await fetch('/api/pm3/documents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fileName: input.file.name,
      mimeType: input.file.type || 'application/octet-stream',
      data,
      hash,
      modelSettings: input.modelSettings,
      ...(input.parsedResult ? { parsedResult: input.parsedResult } : {}),
    }),
  })
  return readJson<Pm3DocumentRecord>(response)
}
