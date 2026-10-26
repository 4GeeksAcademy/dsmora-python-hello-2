import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { api, errorMessage, type Identity } from '../api'

export const Route = createFileRoute('/login')({ component: Login })

function Login() {
  const [identity, setIdentity] = useState<Identity>()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api<Identity>('/auth/me').then(setIdentity).catch(error => setError(errorMessage(error)))
  }, [])

  return (
    <main className="login-page">
      <Link to="/" className="brand">MEXICO LINDO</Link>
      <section className="card">
        <p className="eyebrow">TU VIAJE, A TU MANERA</p>
        <h1>Vuelve a tus planes</h1>
        <p>Entra para guardar itinerarios y consultar el clima con tu autorizacion.</p>
        <form onSubmit={async event => {
          event.preventDefault()
          setBusy(true); setError('')
          try {
            await api('/auth/login', identity, { email, password })
            window.location.assign('/')
          } catch (error) { setError(errorMessage(error)) }
          finally { setBusy(false) }
        }}>
          <label>Email<input type="email" autoComplete="username" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
          <label>Contrasena<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
          <button disabled={busy || !identity} type="submit">{busy ? 'Entrando...' : 'Iniciar sesion'}</button>
        </form>
        {error && <p role="alert" className="error">{error}</p>}
        <Link to="/">Continuar como invitado</Link>
      </section>
      <p className="muted">No realizamos compras ni reservas.</p>
    </main>
  )
}
