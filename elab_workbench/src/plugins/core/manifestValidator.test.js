import { describe, it, expect } from 'vitest'
import { validateManifest, formatManifestErrors } from './manifestValidator.js'

const validManifest = {
  id: 'demo-1',
  name: 'Demo',
  category: 'HARDWARE',
  tasks: [
    {
      id: 'task-1',
      name: 'Demo Task',
      type: 'SENSOR',
      ui: { mode: 'generic' },
    },
  ],
}

describe('validateManifest', () => {
  it('accepts a minimal valid manifest', () => {
    const r = validateManifest(validManifest)
    expect(r.ok).toBe(true)
    expect(r.errors).toBeNull()
  })

  it('rejects a manifest missing required fields', () => {
    const r = validateManifest({ name: 'no id' })
    expect(r.ok).toBe(false)
    expect(r.errors?.length ?? 0).toBeGreaterThan(0)
  })

  it('rejects an invalid task type enum value', () => {
    const r = validateManifest({
      ...validManifest,
      tasks: [{ id: 't', name: 'x', type: 'BOGUS', ui: { mode: 'generic' } }],
    })
    expect(r.ok).toBe(false)
  })

  it('formats errors into a short string', () => {
    const r = validateManifest({})
    const msg = formatManifestErrors(r.errors)
    expect(typeof msg).toBe('string')
    expect(msg.length).toBeGreaterThan(0)
  })
})
