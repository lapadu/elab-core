import PluginBuilder from "./core/PluginBuilder";

export const SpectrumPlugin = new PluginBuilder("plugin_spectrum_v1", "Spectrum Analyzer", "MEASURE")
    .setCreateTask(() => ({
        id: `spectrum_${Date.now()}`,
        groupId: "plugin_spectrum_v1",
        type: "MEASURE",
        name: "Spectrum",
        color: "#8b5cf6",
        virtual: true,
        inputs: { source: null },
        extraChannels: [],
        config: {
            fftSize: 4096,
            maxFreq: 0,
            autoscaleY: true,
            isOverlayVisible: true,
        },
        ui: {
            mode: "generic",
            defaultTemplate: "tpl_spectrum",
            views: [
                {
                    id: "spectrum",
                    label: "Spectrum",
                    icon: "BarChart2",
                    template: "tpl_spectrum",
                },
                {
                    id: "config",
                    label: "Config",
                    icon: "Settings",
                    template: "tpl_spectrum_config",
                },
            ],
        },
    }))
    .build();
