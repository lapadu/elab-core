// elab_workbench/src/services/DispatcherClient.js
import { io } from 'socket.io-client';
import { SOCKET_EVENTS, APP_EVENTS } from '../utils/EventTypes';

// Generate a cryptographically random session id so client-issued ids cannot
// be guessed or hijacked. Falls back to a high-entropy Math.random combo on
// the very unlikely case that the Web Crypto API is unavailable.
function _generateSessionId() {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      let hex = '';
      for (const b of bytes) hex += b.toString(16).padStart(2, '0');
      return `session_${hex}`;
    }
  } catch {
    // ignore – fall through to non-crypto fallback below.
  }
  let fallback = '';
  for (let i = 0; i < 4; i += 1) {
    fallback += Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, '0');
  }
  return `session_${fallback}`;
}

class DispatcherClient {
  constructor() {
    this.socket = null;
    this.connected = false;
    this.providers = [];
    this.sessionId = _generateSessionId();

    // Initialize the event handler map from APP_EVENTS.
    this.handlers = Object.values(APP_EVENTS).reduce((acc, eventName) => {
      acc[eventName] = [];
      return acc;
    }, {});

    // Task subscriptions: taskId -> Set<callback>
    this.taskSubscriptions = new Map();
    this.pendingSubscriptions = new Set(); // Prevent race conditions.
  }

  connect(url = 'http://localhost:5000') {
    console.log(`🔌 Connecting to Dispatcher: ${url}`);
    this.socket = io(url, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 10000,
      reconnectionAttempts: Infinity,
      randomizationFactor: 0.5
    });

    // --- INCOMING EVENTS (FROM SERVER) ---

    this.socket.on(SOCKET_EVENTS.CONNECTION_ESTABLISHED, (data) => {
      console.log('✅ Connection established', data);
      this.connected = true;
      this.sessionId = data.session_id || this.sessionId;
      this.serverVersion = data.server_version || null;
      // Mirror the server's plugin origin allow-list onto the global the
      // WidgetLoader inspects, so the browser refuses untrusted script URLs
      // even if a build artefact has been tampered with.
      try {
        const list = Array.isArray(data.plugin_origins) ? data.plugin_origins : [];
        if (typeof window !== 'undefined') {
          window.__ELAB_PLUGIN_ORIGINS__ = list.map((o) => String(o).toLowerCase());
          window.__ELAB_SERVER_ORIGIN__ = this.socket?.io?.uri || null;
        }
      } catch { /* ignore */ }
      this.registerClient();
      this._emit(APP_EVENTS.ON_CONNECTION_ESTABLISHED, data);
      this.getAvailableScripts();
      this.getSessions();
    });

    this.socket.on(SOCKET_EVENTS.AVAILABLE_PROVIDERS, (data) => {
      this.providers = data.providers;
      this._emit(APP_EVENTS.ON_PROVIDER_UPDATE, this.providers);
    });

    this.socket.on(SOCKET_EVENTS.PROVIDER_REGISTERED, (data) => {
      if (data.provider?.isUiInstance) return;
      if (!this.providers.find(p => p.id === data.provider.id)) {
        this.providers.push(data.provider);
        this._emit(APP_EVENTS.ON_PROVIDER_UPDATE, this.providers);
      }
    });

    this.socket.on(SOCKET_EVENTS.PROVIDER_DISCONNECTED, (data) => {
      this.providers = this.providers.filter(p => p.id !== data.provider_id);
      this._emit(APP_EVENTS.ON_PROVIDER_UPDATE, this.providers);
    });

    this.socket.on(SOCKET_EVENTS.PROVIDER_OFFLINE, (data) => {
      this._emit(APP_EVENTS.ON_PROVIDER_OFFLINE, data);
      this.providers = this.providers.filter(p => p.id !== data.provider_id);
    });

    this.socket.on(SOCKET_EVENTS.DATA_STREAM, (payload) => {
      this._emit(APP_EVENTS.ON_DATA_STREAM, payload);
    });

    this.socket.on(SOCKET_EVENTS.SESSION_STATUS, (data) => {
      this._emit(APP_EVENTS.ON_SESSION_STATUS, data);
    });

    this.socket.on(SOCKET_EVENTS.AVAILABLE_SCRIPTS, (scripts) => {
      this._emit(APP_EVENTS.ON_SCRIPTS_UPDATE, scripts);
    });

    // --- Replay events ---
    this.socket.on(SOCKET_EVENTS.REPLAY_STATUS, (data) => {
        this._emit(APP_EVENTS.ON_REPLAY_STATUS, data);
    });

    this.socket.on(SOCKET_EVENTS.REPLAY_PROGRESS, (data) => {
        this._emit(APP_EVENTS.ON_REPLAY_PROGRESS, data);
    });

    this.socket.on(SOCKET_EVENTS.REPLAY_LOADED, (data) => {
        this._emit(APP_EVENTS.ON_REPLAY_LOADED, data);
    });

    this.socket.on(SOCKET_EVENTS.REPLAY_RESET, (data) => {
        this._emit(APP_EVENTS.ON_REPLAY_RESET, data);
    });

    this.socket.on(SOCKET_EVENTS.SESSION_LIST, (data) => {
        this._emit(APP_EVENTS.ON_SESSION_LIST, data);
    });

    this.socket.on(SOCKET_EVENTS.RECORDED_PROVIDERS, (data) => {
        this._emit(APP_EVENTS.ON_RECORDED_PROVIDERS, data);
    });

    this.socket.on(SOCKET_EVENTS.PROVIDER_META_CHANGED, (data) => {
      this._emit(APP_EVENTS.ON_PROVIDER_META_CHANGED, data);
    });

    this.socket.on(SOCKET_EVENTS.TASK_REJECTED, (data) => {
      console.warn('⛔ Task assignment rejected:', data);
      this._emit(APP_EVENTS.ON_TASK_REJECTED, data);
    });

    this.socket.on(SOCKET_EVENTS.ACTIVE_TASKS_SNAPSHOT, (data) => {
      // Server tells a freshly registered UI which slots are still occupied
      // (e.g. from a previous tab on the same dispatcher).
      this._emit(APP_EVENTS.ON_ACTIVE_TASKS_SNAPSHOT, data);
    });

    this.socket.on(SOCKET_EVENTS.PENDING_DEVICES, (data) => {
      // List of unknown / un-approved providers awaiting operator decision.
      this._emit(APP_EVENTS.ON_PENDING_DEVICES, data?.devices || data);
    });

    this.socket.on(SOCKET_EVENTS.TASK_CONFIG_CHANGED, (data) => {
      this._emit(APP_EVENTS.ON_TASK_CONFIG_CHANGED, data);
    });



    // --- System events ---

    this.socket.on(SOCKET_EVENTS.DISCONNECT, (reason) => {
      console.error('❌ Disconnected from Dispatcher:', reason);
      this.connected = false;
      this._emit(APP_EVENTS.ON_DISCONNECT, { reason });
      // Socket.IO auto-reconnects with exponential backoff (configured above).
      // 'io server disconnect' would normally NOT trigger auto-reconnect; ask
      // the Manager to retry once so a server restart still recovers cleanly.
      if (reason === 'io server disconnect') {
        try {
          this.socket.io?.reconnection(true);
          this.socket.io?.open?.();
        } catch (e) {
          console.warn('🔄 Reconnect kick failed (will retry on next attempt):', e?.message);
        }
      }
    });

    this.socket.on(SOCKET_EVENTS.CONNECT_ERROR, (error) => {
      console.error('⚠️ Connection error:', error.message);
      this._emit(APP_EVENTS.ON_CONNECTION_ERROR, { error: error.message });

      // Socket.IO already applies exponential backoff for reconnects.
    });

    this.socket.on('reconnect', (attemptNumber) => {
      console.log(`🔄 Reconnected after ${attemptNumber} attempts`);
      this.connected = true;
      // Restore task subscriptions after reconnect.
      this._resubscribeAllTasks();
      this._emit(APP_EVENTS.ON_RECONNECT, { attemptNumber });
    });

    this.socket.on('reconnect_error', (error) => {
      console.error('❌ Reconnect failed:', error.message);
      this._emit(APP_EVENTS.ON_RECONNECT_ERROR, { error: error.message });
    });

    this.socket.on('reconnect_failed', () => {
      console.error('💀 Reconnect failed permanently');
      this._emit(APP_EVENTS.ON_RECONNECT_FAILED);
    });

    return this;
  }

  // --- OUTGOING COMMANDS (TO SERVER) ---

  registerClient() {
    if (!this.socket || !this.connected) return;
    this.socket.emit(SOCKET_EVENTS.REGISTER_CLIENT, {
      session_id: this.sessionId,
      client_type: 'ui',
      timestamp: Date.now()
    });
  }

  sendTaskRequest(providerId, task) {
    if (!this.socket) return;
    this.socket.emit(SOCKET_EVENTS.TASK_REQUEST, {
      provider_id: providerId,
      task: task,
      session_id: this.sessionId,
      timestamp: Date.now()
    });
  }

  sendControlCommand(providerId, command) {
    if (!this.socket) return;
    this.socket.emit(SOCKET_EVENTS.CMD_CONTROL, {
      provider_id: providerId,
      command: command,
      session_id: this.sessionId,
      timestamp: Date.now()
    });
  }

  linkSource(sourceId, actuatorProviderId) {
    if (!this.socket) return;
    this.socket.emit(SOCKET_EVENTS.LINK_SOURCE, {
      source_id: sourceId,
      actuator_id: actuatorProviderId,
    });
  }

  unlinkSource(sourceId, actuatorProviderId) {
    if (!this.socket) return;
    this.socket.emit(SOCKET_EVENTS.UNLINK_SOURCE, {
      source_id: sourceId,
      actuator_id: actuatorProviderId,
    });
  }

  assignTaskToSlot(slot, taskId) {
    this.socket?.emit(SOCKET_EVENTS.TASK_ASSIGNED, {
      slot: slot,
      taskId: taskId
    });
  }

  unassignTaskFromSlot(slot, taskId) {
    this.socket?.emit(SOCKET_EVENTS.TASK_UNASSIGNED, {
      slot: slot,
      taskId: taskId
    });
  }

  // --- Session management ---
  
  startSession(sessionId = null) {
    this.socket?.emit(SOCKET_EVENTS.SESSION_START, { session_id: sessionId });
  }

  stopSession() {
    this.socket?.emit(SOCKET_EVENTS.SESSION_STOP, {});
  }

  // --- Script management ---

  getAvailableScripts() {
    this.socket?.emit(SOCKET_EVENTS.GET_AVAILABLE_SCRIPTS);
  }

  startClientScript(filename) {
    this.socket?.emit(SOCKET_EVENTS.START_CLIENT_SCRIPT, { filename });
  }

  // --- Pairing / Trust-on-First-Use management ---

  /** Request the current list of pending (un-approved) providers. */
  getPendingDevices() {
    this.socket?.emit(SOCKET_EVENTS.GET_PENDING_DEVICES);
  }

  /**
   * Approve a pending device. The dispatcher will hand back a one-shot
   * shared secret to the device and start accepting its data_stream.
   * @param {string} deviceId
   * @param {string} manifestHash  Hash echoed in the pending_devices entry;
   *   must match to prevent racing against a manifest change.
   */
  approvePendingDevice(deviceId, manifestHash) {
    this.socket?.emit(SOCKET_EVENTS.APPROVE_PENDING_DEVICE, {
      deviceId,
      manifestHash,
    });
  }

  /** Revoke an approved device (disconnects it; future connects re-pending). */
  revokeDevice(deviceId) {
    this.socket?.emit(SOCKET_EVENTS.REVOKE_DEVICE, { deviceId });
  }

  /** Delete a stored credential entirely (admin / cleanup). */
  deleteDeviceCredential(deviceId) {
    this.socket?.emit(SOCKET_EVENTS.DELETE_DEVICE_CREDENTIAL, { deviceId });
  }

  stopClientScript(filename) {
    this.socket?.emit(SOCKET_EVENTS.STOP_CLIENT_SCRIPT, { filename });
  }

  // --- Replay management ---

  getSessions() {
      this.socket?.emit(SOCKET_EVENTS.GET_SESSIONS);
  }

  loadSession(sessionId) {
      this.socket?.emit(SOCKET_EVENTS.REPLAY_LOAD, { session_id: sessionId });
  }

  getRecordedProviders(sessionId) {
    this.socket?.emit(SOCKET_EVENTS.GET_RECORDED_PROVIDERS, { session_id: sessionId });
  }

  /**
  * Controls the replayer.
  * @param {string} action - 'play', 'pause', 'stop', 'seek', or 'speed'
  * @param {any} value - Time in ms for seek or a playback factor for speed.
   */
  sendReplayAction(action, value = null) {
      this.socket?.emit(SOCKET_EVENTS.REPLAY_ACTION, { action, value });
  }

  deleteSession(sessionId) {
    this.socket?.emit(SOCKET_EVENTS.DELETE_SESSION, { session_id: sessionId });
  }


  // --- EVENT BUS LOGIC ---

  on(event, handler) {
    if (Array.isArray(this.handlers[event])) {
      this.handlers[event].push(handler);
    } else {
      // Warn if a non-predefined or overwritten event is subscribed to.
      if (this.handlers[event] !== undefined) {
        console.warn(`Event "${event}" was subscribed to, but its handler list was not an array. Overwriting.`);
      }
      this.handlers[event] = [handler];
    }
    return this;
  }

  off(event, handler) {
    if (Array.isArray(this.handlers[event])) {
      this.handlers[event] = this.handlers[event].filter(h => h !== handler);
    }
  }

  _emit(event, data) {
    if (Array.isArray(this.handlers[event])) {
      this.handlers[event].forEach(handler => handler(data));
    }
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
      this.connected = false;
    }
  }

  // --- TASK SUBSCRIPTION MANAGEMENT ---

  subscribe(taskId, callback) {
    if (!this.taskSubscriptions.has(taskId)) {
      this.taskSubscriptions.set(taskId, new Set());
      // Notify the server only once unless a request is already pending.
      if (!this.pendingSubscriptions.has(taskId) && this.socket?.connected) {
        this.pendingSubscriptions.add(taskId);
        this.socket.emit(SOCKET_EVENTS.SUBSCRIBE_TASK, { taskId });
        this.pendingSubscriptions.delete(taskId);
      }
    }
    this.taskSubscriptions.get(taskId).add(callback);
  }

  unsubscribe(taskId, callback) {
    const subs = this.taskSubscriptions.get(taskId);
    if (subs) {
      subs.delete(callback);
      if (subs.size === 0) {
        // Inform the server when the last subscriber disappears.
        if (this.socket?.connected) {
          this.socket.emit(SOCKET_EVENTS.UNSUBSCRIBE_TASK, { taskId });
        }
        this.taskSubscriptions.delete(taskId);
      }
    }
  }

  // Re-subscribe all tasks after reconnect.
  _resubscribeAllTasks() {
    if (this.socket?.connected) {
      for (const taskId of this.taskSubscriptions.keys()) {
        if (!this.pendingSubscriptions.has(taskId)) {
          this.pendingSubscriptions.add(taskId);
          this.socket.emit(SOCKET_EVENTS.SUBSCRIBE_TASK, { taskId });
          this.pendingSubscriptions.delete(taskId);
        }
      }
    }
  }
}

export const dispatcher = new DispatcherClient();
export default dispatcher;