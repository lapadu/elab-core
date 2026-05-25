// elab_workbench/src/plugins/core/PluginBuilder.js

class PluginBuilder {
    constructor(id, name, type) {
        this.plugin = {
            id,
            name,
            type,
            render: null,
            createTask: null,
            simulation: null,
        };
    }

    setRender(renderComponent) {
        this.plugin.render = renderComponent;
        return this;
    }

    setCreateTask(createTaskFunc) {
        this.plugin.createTask = createTaskFunc;
        return this;
    }

    setSimulation(simulation) {
        this.plugin.simulation = simulation;
        return this;
    }
    
    setCapabilities(capabilities) {
        this.plugin.capabilities = capabilities;
        return this;
    }

    setDescription(description) {
        this.plugin.description = description;
        return this;
    }

    build() {
        // Basic validation
        if (!this.plugin.id || !this.plugin.name || !this.plugin.type) {
            throw new Error("Plugin ID, Name, and Type are required.");
        }
        return this.plugin;
    }
}

export default PluginBuilder;
