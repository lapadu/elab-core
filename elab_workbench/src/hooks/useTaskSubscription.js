import { useEffect, useCallback } from 'react';
import { useDispatcher } from '../contexts/DispatcherContext';

/**
 * Hook for task-specific data subscriptions with automatic cleanup.
 * Prevents memory leaks caused by missing unsubscribe calls.
 */
export const useTaskSubscription = (taskId, callback) => {
  const dispatcher = useDispatcher();

  const stableCallback = useCallback((...args) => callback(...args), [callback]);

  useEffect(() => {
    if (!taskId || !stableCallback) return;

    // Subscribe to task updates.
    dispatcher.subscribe(taskId, stableCallback);

    // Clean up on unmount or when the task changes.
    return () => {
      dispatcher.unsubscribe(taskId, stableCallback);
    };
  }, [dispatcher, taskId, stableCallback]);
};