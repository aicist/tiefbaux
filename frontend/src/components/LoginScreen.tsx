import { useState } from 'react'

type Props = {
  onLogin: (email: string, password: string) => Promise<void>
}

export function LoginScreen({ onLogin }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) return
    setLoading(true)
    setError(null)
    try {
      await onLogin(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-header">
          <h1 className="login-title">TiefbauX</h1>
          <p className="login-subtitle">Anmelden</p>
        </div>

        {error && <div className="login-error">{error}</div>}

        <div className="login-field">
          <label htmlFor="email">E-Mail</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@fassbender-tenten.de"
            autoComplete="email"
            autoFocus
            required
          />
        </div>

        <div className="login-field">
          <label htmlFor="password">Passwort</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Passwort eingeben"
            autoComplete="current-password"
            required
          />
        </div>

        <button
          type="submit"
          className="login-submit"
          disabled={loading || !email || !password}
        >
          {loading ? 'Wird angemeldet...' : 'Anmelden'}
        </button>
      </form>
    </div>
  )
}
