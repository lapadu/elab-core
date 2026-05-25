import { describe, it, expect } from 'vitest'
import PluginBuilder from './PluginBuilder.js'

describe('PluginBuilder', () => {
  it('builds a minimal plugin with required fields', () => {
    const plugin = new PluginBuilder('test-id', 'Test Plugin', 'SENSOR').build()
    expect(plugin.id).toBe('test-id')
    expect(plugin.name).toBe('Test Plugin')
    expect(plugin.type).toBe('SENSOR')
  })

  it('throws when id is missing', () => {
    expect(() => new PluginBuilder(null, 'Name', 'SENSOR').build()).toThrow()
  })

  it('throws when name is missing', () => {
    expect(() => new PluginBuilder('id', '', 'SENSOR').build()).toThrow()
  })

  it('throws when type is missing', () => {
    expect(() => new PluginBuilder('id', 'Name', null).build()).toThrow()
  })

  it('setRender sets the render component', () => {
    const renderFn = () => 'rendered'
    const plugin = new PluginBuilder('id', 'N', 'SENSOR')
      .setRender(renderFn)
      .build()
    expect(plugin.render).toBe(renderFn)
  })

  it('setCreateTask sets createTask function', () => {
    const fn = () => ({ id: 'new-task' })
    const plugin = new PluginBuilder('id', 'N', 'ACTUATOR')
      .setCreateTask(fn)
      .build()
    expect(plugin.createTask).toBe(fn)
  })

  it('setSimulation sets simulation config', () => {
    const sim = { factory: () => {} }
    const plugin = new PluginBuilder('id', 'N', 'MATH')
      .setSimulation(sim)
      .build()
    expect(plugin.simulation).toBe(sim)
  })

  it('setCapabilities sets capabilities', () => {
    const caps = { rawCapture: true }
    const plugin = new PluginBuilder('id', 'N', 'SENSOR')
      .setCapabilities(caps)
      .build()
    expect(plugin.capabilities).toBe(caps)
  })

  it('setDescription sets description', () => {
    const plugin = new PluginBuilder('id', 'N', 'SENSOR')
      .setDescription('A test plugin')
      .build()
    expect(plugin.description).toBe('A test plugin')
  })

  it('supports fluent chaining', () => {
    const result = new PluginBuilder('id', 'N', 'SENSOR')
      .setRender(() => null)
      .setCreateTask(() => ({}))
      .setSimulation({ factory: () => {} })
      .setCapabilities({})
      .setDescription('desc')
    expect(result).toBeInstanceOf(PluginBuilder)
  })
})
