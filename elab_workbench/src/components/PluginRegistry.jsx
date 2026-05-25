// DYNAMIC PLUGIN LOADING (Vite Magic)
const pluginModules = import.meta.glob('../plugins/**/*.jsx', { eager: true });

export const PLUGIN_REGISTRY = {};

for (const path in pluginModules) {
  const mod = pluginModules[path];
  
  Object.values(mod).forEach(item => {
    // A valid plugin needs an id and either a render or createTask entry point.
    if (item && item.id && (item.render || item.createTask)) {
       PLUGIN_REGISTRY[item.id] = item;
    }
  });
}

export const getPlugin = (id) => PLUGIN_REGISTRY[id];