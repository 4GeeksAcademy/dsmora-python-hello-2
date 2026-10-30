import { defineWebSocketHandler } from 'nitro'

type ProxyConnection = {
  socket: WebSocket
  queued: string[]
  closed: boolean
}

const connections = new Map<string, ProxyConnection>()

export default defineWebSocketHandler({
  upgrade(request) {
    const origin = request.headers.get('origin')
    if (!origin) throw new Response('Origin required.', { status: 403 })
    return { context: { origin } }
  },
  open(peer) {
    const target = new URL('/api/ws/chat', process.env.BACKEND_URL || 'http://backend:8000')
    target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:'
    if (typeof peer.context.origin === 'string') {
      target.searchParams.set('origin', peer.context.origin)
    }
    const socket = new WebSocket(target)
    const connection: ProxyConnection = { socket, queued: [], closed: false }
    connections.set(peer.id, connection)

    socket.addEventListener('open', () => {
      if (connection.closed) {
        socket.close()
        return
      }
      for (const frame of connection.queued) socket.send(frame)
      connection.queued = []
    })
    socket.addEventListener('message', event => {
      try {
        peer.send(typeof event.data === 'string' ? event.data : String(event.data))
      } catch (error) {
        console.error('WebSocket client relay failed:', error instanceof Error ? error.name : 'UnknownError')
      }
    })
    socket.addEventListener('close', event => {
      connections.delete(peer.id)
      peer.close(event.code || 1011, event.reason || 'Backend disconnected.')
    })
    socket.addEventListener('error', () => {
      console.error('WebSocket backend connection failed.')
      peer.close(1011, 'Backend unavailable.')
    })
  },
  message(peer, message) {
    const connection = connections.get(peer.id)
    if (!connection || connection.closed) return
    const frame = message.text()
    if (frame.length > 20000) {
      peer.close(1009, 'Message too large.')
      connection.closed = true
      connection.socket.close()
      return
    }
    if (connection.socket.readyState === WebSocket.OPEN) {
      connection.socket.send(frame)
    } else if (connection.socket.readyState === WebSocket.CONNECTING && connection.queued.length < 5) {
      connection.queued.push(frame)
    } else {
      peer.close(1013, 'Backend is not ready.')
      connection.closed = true
      if (connection.socket.readyState === WebSocket.OPEN) connection.socket.close()
    }
  },
  close(peer) {
    const connection = connections.get(peer.id)
    if (!connection) return
    connection.closed = true
    connections.delete(peer.id)
    if (connection.socket.readyState === WebSocket.OPEN) connection.socket.close()
  },
  error(_peer, error) {
    console.error('WebSocket proxy failed:', error instanceof Error ? error.name : 'UnknownError')
  },
})
