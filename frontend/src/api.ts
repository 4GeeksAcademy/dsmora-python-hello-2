export interface Identity {
  authenticated: boolean
  email: string | null
  csrf: string
}

export interface Plan {
  id: string
  title: string
  content: string
  created_at: number
}

export interface Job {
  status: 'running' | 'done' | 'failed'
  progress?: string
  pending?: { id: string; message: string; expires: number } | null
  result?: string | { plans?: Plan[]; status?: string; plan?: Plan; id?: string }
  error?: string
}

export async function api<T>(
  path: string, identity?: Identity, body?: unknown, signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    credentials: 'same-origin', signal,
    headers: body === undefined ? {} : {
      'Content-Type': 'application/json', 'X-CSRF-Token': identity?.csrf || '',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const value = await response.json()
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Solicitud rechazada.')
  return value
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'No se pudo completar la solicitud.'
}
