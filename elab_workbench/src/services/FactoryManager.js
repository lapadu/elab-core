import PluginAdapter from '../plugins/core/PluginAdapter';
import dispatcher from './DispatcherClient';

class FactoryManager {
  constructor() {
    this.factories = new Map(); // Key: taskId
    this.pendingStops = new Map(); // Key: taskId -> timeoutId
  }

  startFactory(task, plugin) {
    const taskId = task.originalId || task.id;

    // 1. Cancel a pending stop if the factory becomes active again.
    if (this.pendingStops.has(taskId)) {
        console.log(`♻️ Cancel stop for ${taskId} (Keep-Alive)`);
        clearTimeout(this.pendingStops.get(taskId));
        this.pendingStops.delete(taskId);
        return;
    }

      // 2. Do nothing if the factory is already running.
    if (this.factories.has(taskId)) {
      return; 
    }

    console.log(`▶️ Starting factory: ${taskId}`);

    const adapter = new PluginAdapter(plugin, task);
    adapter.register();

    let cleanupFn = null;
    if (plugin.simulation?.factory) {
      cleanupFn = plugin.simulation.factory(task, dispatcher);
    }

    this.factories.set(taskId, {
      adapter,
      cleanup: cleanupFn,
      subscribers: new Set()
    });
  }

  /**
  * Schedules a delayed factory stop.
   */
  scheduleStop(taskId) {
      if (this.pendingStops.has(taskId)) return;

      // Give the system 500 ms to remount before stopping the factory.
      const timeoutId = setTimeout(() => {
          this.performStop(taskId);
          this.pendingStops.delete(taskId);
      }, 500);
      
      this.pendingStops.set(taskId, timeoutId);
  }

  performStop(taskId) {
    const factory = this.factories.get(taskId);
    if (!factory) return;

    // Stop only when no subscribers are left.
    if (factory.subscribers.size > 0) {
        return; 
    }

    console.log(`⏹️ Stopping factory: ${taskId}`);
    if (factory.cleanup) factory.cleanup();
    if (factory.adapter) factory.adapter.unregister();
    
    this.factories.delete(taskId);
  }

  subscribe(taskId, subscriberId) {
    // Cancel any pending stop for this factory.
    if (this.pendingStops.has(taskId)) {
        clearTimeout(this.pendingStops.get(taskId));
        this.pendingStops.delete(taskId);
    }

    const factory = this.factories.get(taskId);
    if (!factory) return; 
    
    factory.subscribers.add(subscriberId);
  }

  unsubscribe(taskId, subscriberId) {
    const factory = this.factories.get(taskId);
    if (!factory) return;
    
    factory.subscribers.delete(subscriberId);
    
    if (factory.subscribers.size === 0) {
        // Schedule the stop instead of stopping immediately.
        this.scheduleStop(taskId);
    }
  }
}

export const factoryManager = new FactoryManager();