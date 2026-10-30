import { createFileRoute } from '@tanstack/react-router'

async function proxy({ request }: { request: Request }) {
  const source = new URL(request.url)
  const target = new URL(source.pathname + source.search, process.env.BACKEND_URL || 'http://backend:8000')
  const headers = new Headers()
  for (const name of ['cookie', 'content-type', 'origin', 'x-csrf-token', 'last-event-id']) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  const body = request.method === 'GET' ? undefined : await request.arrayBuffer()
  if (body && body.byteLength > 20000) return new Response('Solicitud demasiado grande.', { status: 413 })
  const streaming = request.method === 'GET' && source.pathname.endsWith('/events')
  try {
    const upstream = await fetch(target, {
      method: request.method, headers, body, redirect: 'manual',
      // SSE: vive mientras el navegador siga conectado; el resto conserva el timeout.
      signal: streaming ? request.signal : AbortSignal.timeout(20000),
    })
    const isStream = streaming && upstream.ok
    const responseHeaders = new Headers({
      'Content-Type': isStream ? 'text/event-stream; charset=utf-8' : 'application/json',
      'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    })
    if (isStream) responseHeaders.set('X-Accel-Buffering', 'no')
    for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append('Set-Cookie', cookie)
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders })
  } catch (error) {
    console.error('Backend proxy unavailable:', error instanceof Error ? error.name : 'UnknownError')
    return Response.json({ detail: 'El backend no esta disponible.' }, { status: 503 })
  }
}

export const Route = createFileRoute('/api/$')({
  server: { handlers: { GET: proxy, POST: proxy } },
})
