import { useEffect, useState } from 'react'
import { assignProject, createUser, fetchProjects, fetchUsers, updateUser } from '../api'
import type { ProjectSummary, User } from '../types'

export function AdminPanel() {
  const [users, setUsers] = useState<User[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)

  // Create form state
  const [newName, setNewName] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<'mitarbeiter' | 'admin'>('mitarbeiter')
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchUsers(), fetchProjects()])
      .then(([u, p]) => { setUsers(u); setProjects(p) })
      .finally(() => setLoading(false))
  }, [])

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    try {
      const user = await createUser({ name: newName, email: newEmail, password: newPassword, role: newRole })
      setUsers(prev => [...prev, user])
      setShowCreateForm(false)
      setNewName(''); setNewEmail(''); setNewPassword(''); setNewRole('mitarbeiter')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Fehler beim Anlegen')
    }
  }

  const handleToggleActive = async (user: User) => {
    const updated = await updateUser(user.id, { active: !user.active })
    setUsers(prev => prev.map(u => u.id === user.id ? updated : u))
  }

  const handleSaveEdit = async () => {
    if (!editingUser) return
    const updated = await updateUser(editingUser.id, {
      name: editingUser.name,
      role: editingUser.role,
    })
    setUsers(prev => prev.map(u => u.id === editingUser.id ? updated : u))
    setEditingUser(null)
  }

  const handleAssign = async (projectId: number, userId: number | null) => {
    await assignProject(projectId, userId)
    setProjects(prev => prev.map(p =>
      p.id === projectId
        ? { ...p, assigned_user_name: userId ? users.find(u => u.id === userId)?.name ?? null : null }
        : p
    ))
  }

  if (loading) return <div className="admin-loading">Lade Verwaltung...</div>

  const activeUsers = users.filter(u => u.active)
  const openProjects = projects.filter(p => p.status !== 'gerechnet')

  return (
    <div className="admin-panel">
      {/* User Management */}
      <section className="admin-section">
        <div className="admin-section-header">
          <h2>Benutzerverwaltung</h2>
          <button className="btn btn-primary btn-sm" onClick={() => setShowCreateForm(true)}>
            Neuer Benutzer
          </button>
        </div>

        {showCreateForm && (
          <form className="admin-create-form" onSubmit={handleCreateUser}>
            <div className="admin-form-row">
              <input placeholder="Name" value={newName} onChange={e => setNewName(e.target.value)} required />
              <input placeholder="E-Mail" type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} required />
              <input placeholder="Passwort" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={4} />
              <select value={newRole} onChange={e => setNewRole(e.target.value as 'admin' | 'mitarbeiter')}>
                <option value="mitarbeiter">Mitarbeiter</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            {formError && <div className="admin-form-error">{formError}</div>}
            <div className="admin-form-actions">
              <button type="submit" className="btn btn-primary btn-sm">Anlegen</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowCreateForm(false)}>Abbrechen</button>
            </div>
          </form>
        )}

        <table className="admin-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>E-Mail</th>
              <th>Rolle</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map(user => (
              <tr key={user.id} className={user.active ? '' : 'admin-inactive'}>
                <td>
                  {editingUser?.id === user.id ? (
                    <input
                      value={editingUser.name}
                      onChange={e => setEditingUser({ ...editingUser, name: e.target.value })}
                      className="admin-inline-input"
                    />
                  ) : user.name}
                </td>
                <td>{user.email}</td>
                <td>
                  {editingUser?.id === user.id ? (
                    <select
                      value={editingUser.role}
                      onChange={e => setEditingUser({ ...editingUser, role: e.target.value as 'admin' | 'mitarbeiter' })}
                      className="admin-inline-select"
                    >
                      <option value="mitarbeiter">Mitarbeiter</option>
                      <option value="admin">Admin</option>
                    </select>
                  ) : (
                    <span className={`admin-role admin-role--${user.role}`}>
                      {user.role === 'admin' ? 'Admin' : 'Mitarbeiter'}
                    </span>

                  )}
                </td>
                <td>
                  <span className={`admin-status admin-status--${user.active ? 'active' : 'inactive'}`}>
                    {user.active ? 'Aktiv' : 'Inaktiv'}
                  </span>
                </td>
                <td className="admin-actions-cell">
                  {editingUser?.id === user.id ? (
                    <>
                      <button className="btn btn-ghost btn-xs" onClick={handleSaveEdit}>Speichern</button>
                      <button className="btn btn-ghost btn-xs" onClick={() => setEditingUser(null)}>Abbrechen</button>
                    </>
                  ) : (
                    <>
                      <button className="btn btn-ghost btn-xs" onClick={() => setEditingUser({ ...user })}>Bearbeiten</button>
                      <button className="btn btn-ghost btn-xs" onClick={() => handleToggleActive(user)}>
                        {user.active ? 'Deaktivieren' : 'Aktivieren'}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Project Assignment */}
      <section className="admin-section">
        <div className="admin-section-header">
          <h2>Projektzuweisung</h2>
        </div>

        <table className="admin-table">
          <thead>
            <tr>
              <th>Projekt</th>
              <th>Status</th>
              <th>Zuletzt bearbeitet</th>
              <th>Zugewiesen an</th>
            </tr>
          </thead>
          <tbody>
            {openProjects.map(p => (
              <tr key={p.id}>
                <td>
                  <div className="admin-project-name">{p.bauvorhaben ?? p.project_name ?? p.filename ?? `Projekt #${p.id}`}</div>
                  {p.projekt_nr && <span className="admin-project-nr">{p.projekt_nr}</span>}
                </td>
                <td>
                  <span className={`archive-status archive-status-${p.status}`}>
                    {p.status === 'neu'
                      ? 'Neu'
                      : p.status === 'offen'
                        ? 'Offen'
                        : p.status === 'anfrage_offen'
                          ? 'Anfrage offen'
                          : 'Gerechnet'}
                  </span>
                </td>
                <td>
                  {p.last_editor_name ? (
                    <span className="admin-editor">
                      {p.last_editor_name}
                      {p.last_edited_at && (
                        <span className="admin-editor-date">
                          {new Date(p.last_edited_at).toLocaleDateString('de-DE')}
                        </span>
                      )}
                    </span>
                  ) : '—'}
                </td>
                <td>
                  <select
                    value={p.assigned_user_name ? activeUsers.find(u => u.name === p.assigned_user_name)?.id ?? '' : ''}
                    onChange={e => handleAssign(p.id, e.target.value ? parseInt(e.target.value) : null)}
                    className="admin-assign-select"
                  >
                    <option value="">— Nicht zugewiesen —</option>
                    {activeUsers.map(u => (
                      <option key={u.id} value={u.id}>{u.name}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
            {openProjects.length === 0 && (
              <tr><td colSpan={4} className="admin-empty">Keine offenen Projekte</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  )
}
