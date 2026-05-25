/**
 * Helper: Config-Werte mit Fallbacks extrahieren
 */
export const getConfig = (task, channel = null) => {
  const config = channel?.config || task.config || {};
  return {
    factor: config.factor !== undefined ? config.factor : 1.0,
    unit: config.unit || config.siUnit || "",
    range: config.range || [-5, 5],
    min: config.min || 0,
    max: config.max || 100,
    step: config.step || 1,
  };
};

/**
 * Helper:Letzten Wert aus Buffer holen
 */
export const getLatestValue = (streamBuffers, taskId, originalId) => {
  const buffer = streamBuffers?.get(taskId) || streamBuffers?.get(originalId);
  if (!buffer) return null;

  const data = buffer.getData();
  return data.length > 0 ? data[data.length - 1].v : null;
};
