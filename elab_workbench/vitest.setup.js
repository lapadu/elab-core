// Vitest setup: silence noisy console.log inside the unit-test environment
// while keeping warnings/errors visible.
import { vi, beforeAll } from 'vitest'

beforeAll(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {})
})
