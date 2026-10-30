import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, type Identity, type Job, type Plan } from '../api'

export const Route = createFileRoute('/')({ component: Agent })
type Message = { role: 'user' | 'assistant'; text: string; interrupted?: boolean }
type SocketEvent = {
  type: string
  job_id?: string
  status?: Job['status']
  code?: string
  message?: string
}

function Agent() {
  const [identity, setIdentity] = useState<Identity>()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [jobId, setJobId] = useState<string>()
  const [job, setJob] = useState<Job>()
  const [plans, setPlans] = useState<Plan[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [interrupting, setInterrupting] = useState(false)
  const [socketReady, setSocketReady] = useState(false)
  const [controlJobId, setControlJobId] = useState<string>()
  const [draft, setDraft] = useState<{ id: string; text: string }>()
  const conversation = useRef('')
  const bottom = useRef<HTMLDivElement>(null)
  const socket = useRef<WebSocket | undefined>(undefined)
  const streamedDraft = useRef<{ id: string; text: string } | undefined>(undefined)
  const busy = Boolean(jobId) || submitting
  const phase = job?.status === 'awaiting_approval' ? 'awaiting_approval' : 'live'

  useEffect(() => {
    conversation.current = crypto.randomUUID()
    api<Identity>('/auth/me').then(value => {
      setIdentity(value)
      const savedJobId = value.authenticated ? localStorage.getItem('active_job_id') : null
      if (savedJobId) {
        setJobId(savedJobId)
      }
    }).catch(error => setError(errorMessage(error)))
  }, [])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, job?.pending, draft?.text])

  function sendControl(payload: Record<string, unknown>) {
    const currentSocket = socket.current
    if (currentSocket?.readyState === WebSocket.OPEN) {
      currentSocket.send(JSON.stringify(payload))
      return true
    }
    return false
  }

  function finish(next: Job, finishedJobId?: string) {
    if (finishedJobId) sendControl({ type: 'release_job', job_id: finishedJobId })
    if (next.status === 'interrupted') {
      const partial = streamedDraft.current?.text || ''
      setMessages(previous => [...previous, {
        role: 'assistant',
        text: partial || 'Generacion detenida.',
        interrupted: true,
      }])
    }
    setJobId(undefined); setDraft(undefined); setJob(next)
    streamedDraft.current = undefined
    setControlJobId(undefined)
    setInterrupting(false)
    if (!finishedJobId || localStorage.getItem('active_job_id') === finishedJobId) {
      localStorage.removeItem('active_job_id')
    }
    if (next.status === 'failed') setError(next.error || 'El trabajo ha fallado.')
    else if (typeof next.result === 'string') {
      const text = next.result
      setMessages(previous => [...previous, { role: 'assistant', text }])
    } else if (next.result) {
      if (next.result.plans) setPlans(next.result.plans)
      if (next.result.status === 'saved' || next.result.status === 'already_saved') {
        setMessages(previous => [...previous, { role: 'assistant', text: 'Plan guardado. Puedes verlo en Mis planes.' }])
      } else if (next.result.status === 'deleted') {
        setPlans(previous => previous.filter(plan => plan.id !== (typeof next.result === 'object' ? next.result?.id : undefined)))
      } else if (next.result.status === 'cancelled') {
        setMessages(previous => [...previous, { role: 'assistant', text: 'Operacion cancelada. No se ha realizado ningun cambio.' }])
      }
    }
  }

  useEffect(() => {
    if (!jobId || phase === 'awaiting_approval') return
    const source = new EventSource(`/api/jobs/${jobId}/events`)
    source.addEventListener('token', event => {
      try {
        const payload = JSON.parse((event as MessageEvent<string>).data) as { id: string; text: string }
        streamedDraft.current = streamedDraft.current?.id === payload.id
          ? { id: payload.id, text: streamedDraft.current.text + payload.text }
          : { id: payload.id, text: payload.text }
        setDraft(streamedDraft.current)
      } catch {
        source.close()
        setError('El servidor envio un evento SSE invalido.')
      }
    })
    source.addEventListener('status', event => {
      try {
        const next = JSON.parse((event as MessageEvent<string>).data) as Job
        setJob(next)
        if (next.status === 'awaiting_approval') {
          source.close()
        } else if (['done', 'failed', 'interrupted'].includes(next.status)) {
          source.close()
          finish(next, jobId)
        }
      } catch {
        source.close()
        setError('El servidor envio un estado SSE invalido.')
      }
    })
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        setError('Se interrumpio el flujo de respuestas del agente.')
      }
    }
    return () => source.close()
  }, [jobId, phase])

  useEffect(() => {
    if (!identity) return
    let closed = false
    let connection: WebSocket | undefined

    async function connect(session: Identity) {
      try {
        const { token } = await api<{ token: string }>('/auth/ws-ticket', session, {})
        if (closed) return
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        connection = new WebSocket(`${protocol}//${window.location.host}/socket/chat`)
        socket.current = connection
        connection.onopen = () => connection?.send(JSON.stringify({ type: 'auth', token }))
        connection.onmessage = event => {
          let data: SocketEvent
          try { data = JSON.parse(event.data as string) as SocketEvent }
          catch {
            setError('El servidor envio un evento invalido.')
            return
          }
          switch (data.type) {
            case 'ready': {
              setSocketReady(true)
              const savedJobId = session.authenticated ? localStorage.getItem('active_job_id') : null
              if (savedJobId) {
                connection?.send(JSON.stringify({ type: 'attach_job', job_id: savedJobId }))
              }
              break
            }
            case 'control_ready':
              if (data.job_id) {
                setControlJobId(data.job_id)
                setSubmitting(false)
              }
              break
            case 'approval_received':
              setJob(current => current && data.status !== 'done' && data.status !== 'failed'
                ? { ...current, status: 'running', pending: null }
                : current)
              setConfirming(false)
              break
            case 'interrupt_ack':
              break
            case 'error':
              setError(data.message || 'No se pudo completar la solicitud.')
              setSubmitting(false)
              if (data.code === 'INTERRUPT_REJECTED') setInterrupting(false)
              if (data.code === 'APPROVAL_REJECTED') setConfirming(false)
              break
          }
        }
        connection.onclose = () => {
          if (closed) return
          setSocketReady(false)
          setError('Se perdio la conexion con el agente. Recarga la sesion para reconectar.')
          setSubmitting(false)
        }
        connection.onerror = () => setError('No se pudo conectar con el agente.')
      } catch (error) {
        if (!closed) setError(errorMessage(error))
      }
    }

    void connect(identity)
    return () => {
      closed = true
      setSocketReady(false)
      connection?.close()
      if (socket.current === connection) socket.current = undefined
    }
  }, [identity])

  async function start(path: '/chat' | '/tools', body: Record<string, unknown>) {
    if (!socketReady) {
      setError('El canal de control con el agente no esta disponible.')
      return
    }
    setError('')
    setSubmitting(true)
    setJob(undefined)
    setDraft(undefined)
    setControlJobId(undefined)
    streamedDraft.current = undefined
    try {
      const result = await api<{ job_id: string }>(path, identity, body)
      setJobId(result.job_id)
      setJob({ status: 'running', progress: 'Generando tu respuesta.' })
      setInterrupting(false)
      if (identity?.authenticated) localStorage.setItem('active_job_id', result.job_id)
      if (!sendControl({ type: 'attach_job', job_id: result.job_id })) {
        throw new Error('El canal de control con el agente no esta disponible.')
      }
    } catch (error) {
      setSubmitting(false)
      setError(errorMessage(error))
    }
  }

  function confirm(accept: boolean) {
    if (!jobId || controlJobId !== jobId || !job?.pending) return
    setConfirming(true)
    try {
      const pending = job.pending
      const currentSocket = socket.current
      if (!currentSocket || currentSocket.readyState !== WebSocket.OPEN) {
        throw new Error('El canal con el agente no esta disponible.')
      }
      if (pending.version !== undefined && pending.digest) {
        currentSocket.send(JSON.stringify({
          type: 'approve',
          job_id: jobId,
            request_id: pending.id,
            version: pending.version,
            digest: pending.digest,
            action: accept ? 'approve' : 'deny',
        }))
      } else {
        currentSocket.send(JSON.stringify({
          type: 'confirm',
          job_id: jobId,
          confirmation_id: pending.id,
          accept,
        }))
      }
    } catch (error) {
      setConfirming(false)
      setError(errorMessage(error))
    }
  }

  function interrupt() {
    if (!jobId || controlJobId !== jobId || !socket.current || socket.current.readyState !== WebSocket.OPEN) {
      setError('El canal con el agente no esta disponible.')
      return
    }
    setInterrupting(true)
    if (!sendControl({ type: 'interrupt', job_id: jobId })) {
      setInterrupting(false)
      setError('El canal con el agente no esta disponible.')
    }
  }

  return (
    <div className="app">
      <header>
        <Link className="brand" to="/">MEXICO LINDO<span>Una idea. Muchos caminos.</span></Link>
        <nav aria-label="Cuenta">
          {identity?.authenticated ? <>
            <span className="account">{identity.email}</span>
            <button className="secondary" onClick={async () => {
              try { await api('/auth/logout', identity, {}); window.location.assign('/') }
              catch (error) { setError(errorMessage(error)) }
            }}>Salir</button>
          </> : <Link className="button secondary" to="/login">Iniciar sesion</Link>}
        </nav>
      </header>
      <main className="workspace">
        <aside>
          <p className="eyebrow">DESCUBRE MEXICO</p>
          <h1>Tu proximo viaje empieza con una charla.</h1>
          <p>Itinerarios a tu ritmo, ideas locales y presupuestos orientativos.</p>
          <div className="notice">
            {identity?.authenticated
              ? 'Puedes guardar planes y consultar el clima. Siempre te pediremos confirmar las acciones.'
              : 'Modo invitado: planificacion sin herramientas externas. Entra para guardar planes y consultar el clima.'}
          </div>
          <button className="secondary" disabled={busy} onClick={() => {
            conversation.current = crypto.randomUUID(); setMessages([]); setJob(undefined); setError('')
          }}>Nueva conversacion</button>
          {identity?.authenticated && <>
            <button disabled={busy} className="secondary" onClick={() => void start('/tools', { name: 'list_trip_plans' })}>Mis planes</button>
            <section aria-label="Planes guardados">
              {plans.map(plan => <article key={plan.id} className="saved-plan">
                <h3>{plan.title}</h3><p>{plan.content}</p>
                <button className="danger" disabled={busy} onClick={() => void start('/tools', { name: 'delete_trip_plan', arguments: { plan_id: plan.id } })}>Eliminar</button>
              </article>)}
            </section>
          </>}
          <p className="muted">Solo viajes por Mexico. No hacemos reservas ni pagos. Las propuestas no verifican disponibilidad.</p>
        </aside>
        <section className="chat" aria-label="Agent de viajes">
          <div className="chat-heading"><span className="status-dot" />Agent <small>{identity?.authenticated ? 'Cuenta conectada' : 'Planificacion libre'}</small></div>
          <div className="messages" aria-live="polite">
            {!messages.length && <div className="welcome">
              <span className="sun" aria-hidden="true">☀</span>
              <h2>¿A donde vamos?</h2>
              <p>Cuentame destino, dias y presupuesto. Lo planeamos juntos.</p>
              {['Tres dias en Oaxaca con presupuesto moderado', 'Un fin de semana cultural en Puebla'].map(text =>
                <button className="suggestion" key={text} disabled={busy} onClick={() => setInput(text)}>{text}</button>
              )}
            </div>}
            {messages.map((message, index) => <article className={`message ${message.role}${message.interrupted ? ' interrupted' : ''}`} key={index}>
              <strong>{message.role === 'user' ? 'Tu' : 'Agent'}</strong>
              <p>{message.text}</p>
              {message.interrupted && <small>Respuesta detenida</small>}
              {message.role === 'assistant' && identity?.authenticated && <button className="secondary small" disabled={busy} onClick={() => void start('/tools', {
                name: 'save_trip_plan', arguments: { title: 'Mi itinerario por Mexico', content: message.text },
              })}>Guardar como plan</button>}
            </article>)}
            {draft && <article className="message assistant streaming">
              <strong>Agent</strong>
              <p>{draft.text}</p>
            </article>}
            {busy && !draft && <p className="progress" role="status">{job?.progress || 'Conectando con Agent...'}</p>}
            <div ref={bottom} />
          </div>
          {error && <div role="alert" className="error">{error} <button className="secondary small" onClick={() => window.location.reload()}>Recargar sesion</button></div>}
          <form className="composer" onSubmit={event => {
            event.preventDefault()
            const message = input.trim()
            if (!message || busy || !identity || !socketReady) return
            setMessages(previous => [...previous, { role: 'user', text: message }]); setInput('')
            void start('/chat', { message, conversation_id: conversation.current })
          }}>
            <label className="sr-only" htmlFor="message">Tu mensaje</label>
            <textarea id="message" placeholder="¿Que viaje tienes en mente?" maxLength={4000} rows={2} value={input} onChange={event => setInput(event.target.value)} disabled={busy || !identity || !socketReady} />
            {jobId && job?.status === 'running' && <button className="danger" type="button" disabled={interrupting || controlJobId !== jobId} onClick={interrupt}>
              {interrupting ? 'Deteniendo…' : 'Detener'}
            </button>}
            <button disabled={busy || !identity || !socketReady || !input.trim()}>Enviar</button>
          </form>
          <p className="chat-footnote">{socketReady ? 'Canal conectado. ' : 'Conectando con el agente… ' }Las conversaciones caducan. No compartas informacion sensible.</p>
        </section>
      </main>
      {job?.pending && <div className="modal-backdrop">
        <section role="dialog" aria-modal="true" aria-labelledby="consent-title" className="consent card">
          <h2 id="consent-title">{job.pending.version !== undefined ? 'Aprobar guardado del plan' : 'Tu autorizacion es necesaria'}</h2>
          <p>{job.pending.message}</p>
          {job.pending.title && <h3>{job.pending.title}</h3>}
          {job.pending.content && <pre>{job.pending.content}</pre>}
          {job.pending.expires && <p className="muted">Esta confirmacion temporal caduca en 90 segundos.</p>}
          <div className="actions">
            <button className="secondary" disabled={confirming || controlJobId !== jobId} onClick={() => void confirm(false)}>Rechazar</button>
            <button disabled={confirming || controlJobId !== jobId} onClick={() => void confirm(true)}>
              {job.pending.version !== undefined ? 'Aprobar y guardar' : 'Autorizar esta accion'}
            </button>
          </div>
        </section>
      </div>}
    </div>
  )
}
