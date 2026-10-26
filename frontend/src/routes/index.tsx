import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, type Identity, type Job, type Plan } from '../api'

export const Route = createFileRoute('/')({ component: Agent })
type Message = { role: 'user' | 'assistant'; text: string }

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
  const conversation = useRef('')
  const bottom = useRef<HTMLDivElement>(null)
  const busy = Boolean(jobId) || submitting

  useEffect(() => {
    conversation.current = crypto.randomUUID()
    api<Identity>('/auth/me').then(value => {
      setIdentity(value)
      const savedJobId = value.authenticated ? localStorage.getItem('active_job_id') : null
      if (savedJobId) setJobId(savedJobId)
    }).catch(error => setError(errorMessage(error)))
  }, [])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, job?.pending])

  useEffect(() => {
    if (!jobId) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const next = await api<Job>(`/jobs/${jobId}`, undefined, undefined, controller.signal)
        setJob(next)
        if (next.status === 'running') timer = setTimeout(poll, 800)
        else if (next.status === 'awaiting_approval') {
          return
        } else if (next.status === 'approved' || next.status === 'denied') {
          await api(`/jobs/${jobId}/resume`, identity, {})
          setJob(current => current ? { ...current, status: 'running', pending: null } : current)
        } else {
          setJobId(undefined)
          if (localStorage.getItem('active_job_id') === jobId) localStorage.removeItem('active_job_id')
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
      } catch (error) {
        if (!controller.signal.aborted) { setError(errorMessage(error)); setJobId(undefined) }
      }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [jobId, job?.status])

  async function start(path: string, body: unknown) {
    setError(''); setSubmitting(true); setJob(undefined)
    try {
      const result = await api<{ job_id: string }>(path, identity, body)
      if (identity?.authenticated) localStorage.setItem('active_job_id', result.job_id)
      setJobId(result.job_id)
    } catch (error) { setError(errorMessage(error)) }
    finally { setSubmitting(false) }
  }

  async function confirm(accept: boolean) {
    if (!jobId || !job?.pending) return
    setConfirming(true)
    try {
      const pending = job.pending
      if (pending.version !== undefined && pending.digest) {
        const result = await api<{ status: 'approved' | 'denied' }>(
          `/jobs/${jobId}/approve`,
          identity,
          {
            request_id: pending.id,
            version: pending.version,
            digest: pending.digest,
            action: accept ? 'approve' : 'deny',
          },
        )
        setJob(current => current ? { ...current, status: result.status, pending: null } : current)
      } else {
        await api(`/jobs/${jobId}/confirm`, identity, { confirmation_id: pending.id, accept })
        setJob(current => current ? { ...current, pending: null } : current)
      }
    } catch (error) { setError(errorMessage(error)) }
    finally { setConfirming(false) }
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
            {messages.map((message, index) => <article className={`message ${message.role}`} key={index}>
              <strong>{message.role === 'user' ? 'Tu' : 'Agent'}</strong>
              <p>{message.text}</p>
              {message.role === 'assistant' && identity?.authenticated && <button className="secondary small" disabled={busy} onClick={() => void start('/tools', {
                name: 'save_trip_plan', arguments: { title: 'Mi itinerario por Mexico', content: message.text },
              })}>Guardar como plan</button>}
            </article>)}
            {busy && <p className="progress" role="status">{job?.progress || 'Conectando con Agent...'}</p>}
            <div ref={bottom} />
          </div>
          {error && <div role="alert" className="error">{error} <button className="secondary small" onClick={() => window.location.reload()}>Recargar sesion</button></div>}
          <form className="composer" onSubmit={event => {
            event.preventDefault()
            const message = input.trim()
            if (!message || busy || !identity) return
            setMessages(previous => [...previous, { role: 'user', text: message }]); setInput('')
            void start('/chat', { message, conversation_id: conversation.current })
          }}>
            <label className="sr-only" htmlFor="message">Tu mensaje</label>
            <textarea id="message" placeholder="¿Que viaje tienes en mente?" maxLength={4000} rows={2} value={input} onChange={event => setInput(event.target.value)} disabled={busy || !identity} />
            <button disabled={busy || !identity || !input.trim()}>Enviar</button>
          </form>
          <p className="chat-footnote">Las conversaciones caducan. No compartas informacion sensible.</p>
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
            <button className="secondary" disabled={confirming} onClick={() => void confirm(false)}>Rechazar</button>
            <button disabled={confirming} onClick={() => void confirm(true)}>
              {job.pending.version !== undefined ? 'Aprobar y guardar' : 'Autorizar esta accion'}
            </button>
          </div>
        </section>
      </div>}
    </div>
  )
}
