import { useEffect, useRef } from "react";
import PluginAdapter from "../PluginAdapter";
import { useDispatcher } from "../../../contexts/DispatcherContext";

/**
 * Global factory registry.
 * Prevents duplicate factory instances for the same task.
 */
const activeFactories = new Map();

/**
 * Custom hook for factory management.
 * Starts and manages the adapter and factory for virtual tasks.
 */
export const useAdapter = (task, adapterRef, sourcePlugin, options = {}) => {
  const dispatcher = useDispatcher();
  const taskRef = useRef(task);
  const optionsRef = useRef(options);
  const sourcePluginRef = useRef(sourcePlugin);
  const cleanupExecutedRef = useRef(false);

  // Keep refs in sync with the latest arguments.
  useEffect(() => {
    taskRef.current = task;
    optionsRef.current = options;
    sourcePluginRef.current = sourcePlugin;
  }, [task, options, sourcePlugin]);

  // Manage the factory lifecycle.
  useEffect(() => {
    const currentPlugin = sourcePluginRef.current;
    if (!currentPlugin) return;

    const currentTask = taskRef.current;
    const isSimulationPlugin = currentPlugin.simulation?.alwaysRun;
    const isVirtualTask = currentTask.virtual === true;

    if (!isVirtualTask && !isSimulationPlugin) return;

    const factoryKey = currentTask.originalId || currentTask.id;

    // Skip duplicate factory starts.
    if (activeFactories.has(factoryKey)) {
      console.log(`⚠️ Factory already running: ${factoryKey}`);
      return;
    }

    if (adapterRef.current) {
      console.log(`⚠️ Adapter already exists: ${factoryKey}`);
      return;
    }

    console.log(`▶ Starting factory:${factoryKey}`);
    cleanupExecutedRef.current = false;

    // Create and register the adapter.
    const adapter = new PluginAdapter(
      {
        id: currentTask.groupId,
        type: currentTask.type || optionsRef.current.defaultType || "SENSOR",
        name: currentTask.name,
        capabilities: currentPlugin.capabilities || [],
        simulation: currentPlugin.simulation,
      },
      currentTask,
    );

    adapterRef.current = adapter;
    adapter.register();

    // Start the simulation factory if available.
    let factoryCleanup = null;
    if (currentPlugin.simulation?.factory) {
      factoryCleanup = currentPlugin.simulation.factory(currentTask, dispatcher);
    }

    activeFactories.set(factoryKey, {
      adapter,
      cleanup: factoryCleanup,
      taskId: currentTask.id,
    });

    // Clean up the adapter and factory on unmount.
    return () => {
      if (cleanupExecutedRef.current) return;
      cleanupExecutedRef.current = true;

      console.log(`■ Stopping factory:${factoryKey}`);

      if (factoryCleanup) factoryCleanup();
      if (adapterRef.current) {
        adapterRef.current.unregister();
        adapterRef.current = null;
      }

      activeFactories.delete(factoryKey);
    };
  }, [adapterRef, dispatcher]);
};
