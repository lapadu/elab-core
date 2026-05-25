import PluginBuilder from "./core/PluginBuilder";

export const ScopePlugin = new PluginBuilder("plugin_scope_v1", "Virtual Scope", "MEASURE")
    .setCreateTask(() => ({
        id: `scope_${Date.now()}`,
        groupId: "plugin_scope_v1",
        type: "MEASURE",
        name: "Scope (Pro)",
        color: "#10b981",
        virtual: true,
        inputs: { source: null },
        extraChannels: [],
        config: {
            range: [-5, 5],
            yMin: -5,
            yMax: 5,
            timeWindow: 10,
            unit: "V",
            factor: 1.0,
            triggerLevel: 0.0,
            triggerActive: true,
            isPaused: false,
            showUncertaintyBand: false,
            singleShotWaiting: false,
        },
        ui: {
            mode: "generic",
            defaultTemplate: "tpl_scope",
            views: [
                {
                    id: "graph",
                    label: "Scope",
                    icon: "Activity",
                    template: "tpl_scope",
                },
            ],
        },
    }))
    .build();

