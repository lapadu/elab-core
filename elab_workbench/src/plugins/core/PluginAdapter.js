import dispatcher from '../../services/DispatcherClient.js';
import { APP_EVENTS } from '../../utils/EventTypes.js';

// Global registry guard.
const globalRegistry = new Map();

class PluginAdapter {
    constructor(plugin, taskInstance) {
        this.plugin = plugin;
        this.task = taskInstance;
        this.registered = false;
        this.streamInterval = null;
        // Stable provider ID derived from the original task ID.
        this.providerId = `prov_${this.task.originalId || this.task.id}`;
        
        // Re-register on connect events so virtual providers survive reconnects.
        this._onConnect = () => {
            if (this.registered) this._doRegister();
        };
        // Subscribe through the internal dispatcher event bus.
        dispatcher.on(APP_EVENTS.ON_CONNECTION_ESTABLISHED, this._onConnect);
    }

    /**
     * @returns {import('./ManifestTypes.js').Manifest}
     */
    _createManifest() {
        return {
            id: this.providerId,
            name: this.task.name || 'Virtual Device',
            type: 'VIRTUAL',
            category: 'VIRTUAL_INTERNAL',
            virtual: true,
            isUiInstance: true,
            capabilities: this.plugin.capabilities || [],
            tasks: [{
                id: this.task.originalId || this.task.id,
                name: this.task.name,
                type: this.task.type,
                groupId: this.task.groupId,
                virtual: true,
                ui: this.task.ui,
                config: this.task.config || {},
                inputs: this.task.inputs || {},
                color: this.task.color,
                extraChannels: this.task.extraChannels || []
            }]
        };
    }

    _doRegister() {
        if (dispatcher.socket && dispatcher.connected) {
            dispatcher.socket.emit('register_provider', this._createManifest());
            console.log(`📡 Adapter registered with backend: ${this.providerId}`);
        }
    }

    register() {
        // Prevent duplicate registration.
        if (globalRegistry.has(this.providerId)) return;
        
        globalRegistry.set(this.providerId, true);
        this.registered = true;
        
        // Try immediately; if the socket is not ready yet, the connect listener
        // will retry shortly after.
        this._doRegister();
    }

    startStreaming(getValue, intervalMs = 50) {
        if (this.streamInterval) return;

        this.streamInterval = setInterval(() => {
            const value = getValue();
            
            // Payload format expected by the server.
            const payload = {
                sourceId: this.task.originalId || this.task.id,
                value: value,
                timestamp: Date.now(),
                // Optional batch support for high-frequency streams.
                values: [value] 
            };

            // Send only to the server; it will broadcast the stream back to all clients.
            if (dispatcher.socket?.connected) {
                dispatcher.socket.emit('data_stream', payload);
            }
        }, intervalMs);
    }

    stopStreaming() {
        if (this.streamInterval) {
            clearInterval(this.streamInterval);
            this.streamInterval = null;
        }
    }
    sendControl(action, params = {}) {
        // Route control commands through the server as well.
        dispatcher.sendControlCommand(this.providerId, {
            providerId: this.providerId,
            action,
            payload: params
        });
    }

    unregister() {
        this.stopStreaming();
        dispatcher.off(APP_EVENTS.ON_CONNECTION_ESTABLISHED, this._onConnect);
        
        if (globalRegistry.has(this.providerId)) {
            // The server-side disconnect notification is intentionally omitted here.
            // dispatcher.socket.emit('provider_disconnect', { provider_id: this.providerId });
            
            globalRegistry.delete(this.providerId);
            this.registered = false;
            console.log(`🛑 Adapter unregistered: ${this.providerId}`);
        }
    }
}

export default PluginAdapter;