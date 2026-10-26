import { createFileRoute } from '@tanstack/react-router'

async function proxy({ request }: { request: Request }) {
  const source = new URL(request.url)
  const target = new URL(source.pathname + source.search, process.env.BACKEND_URL || 'http://backend:8000')
  const headers = new Headers()
  for (const name of ['cookie', 'content-type', 'origin', 'x-csrf-token']) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  const body = request.method === 'GET' ? undefined : await request.arrayBuffer()
  if (body && body.byteLength > 20000) return new Response('Solicitud demasiado grande.', { status: 413 })
  try {
    const upstream = await fetch(target, {
      method: request.method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(20000),
    })
    const responseHeaders = new Headers({
      'Content-Type': 'application/json', 'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    })
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
