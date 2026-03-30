import { useCallback, useEffect, useRef, useState } from 'react'
import { clearAuthToken, fetchMe, getAuthToken, login as apiLogin, setAuthToken } from '../api'
import type { User } from '../types'

export function useAuth() {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Guard: ignore auth-expired events while a login is in progress
  const loginInProgressRef = useRef(false)

  // Check token on mount
  useEffect(() => {
    const token = getAuthToken()
    if (!token) {
      setIsLoading(false)
      return
    }
    fetchMe()
      .then(setUser)
      .catch(() => {
        clearAuthToken()
      })
      .finally(() => setIsLoading(false))
  }, [])

  // Listen for auth-expired events (401 from API)
  useEffect(() => {
    const handleExpired = () => {
      if (loginInProgressRef.current) return
      setUser(null)
    }
    window.addEventListener('auth-expired', handleExpired)
    return () => window.removeEventListener('auth-expired', handleExpired)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setError(null)
    loginInProgressRef.current = true
    try {
      const result = await apiLogin(email, password)
      setAuthToken(result.access_token)
      setUser(result.user)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen'
      setError(message)
      throw err
    } finally {
      loginInProgressRef.current = false
    }
  }, [])

  const logout = useCallback(() => {
    clearAuthToken()
    setUser(null)
  }, [])

  return {
    user,
    isLoading,
    isAdmin: user?.role === 'admin',
    error,
    login,
    logout,
  }
}
