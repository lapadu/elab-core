// elab_workbench/src/utils/EventTypes.js

// Events exchanged verbatim with the Python backend.
export const SOCKET_EVENTS = {
  // --- Incoming (Server -> Client) ---
  CONNECTION_ESTABLISHED: 'connection_established',
  AVAILABLE_PROVIDERS: 'available_providers',
  PROVIDER_REGISTERED: 'provider_registered',
  PROVIDER_DISCONNECTED: 'provider_disconnected',
  PROVIDER_OFFLINE: 'provider_offline',
  DATA_STREAM: 'data_stream',
  SESSION_STATUS: 'session_status',
  AVAILABLE_SCRIPTS: 'available_scripts',
  DISCONNECT: 'disconnect',
  CONNECT_ERROR: 'connect_error',
  
  // Replay-specific events.
  REPLAY_STATUS: 'replay_status',
  REPLAY_PROGRESS: 'replay_progress',
  REPLAY_LOADED: 'replay_loaded',
  SESSION_LIST: 'session_list',
  RECORDED_PROVIDERS: 'recorded_providers',
  PROVIDER_META_CHANGED: 'provider_meta_changed',
  TASK_REJECTED: 'task_rejected',
  ACTIVE_TASKS_SNAPSHOT: 'active_tasks_snapshot',

  // --- Outgoing (Client -> Server) ---
  REGISTER_CLIENT: 'register_client',
  TASK_REQUEST: 'task_request',
  TASK_ASSIGNED: 'task_assigned',
  TASK_UNASSIGNED: 'task_unassigned',
  CMD_CONTROL: 'cmd_control',
  
  // Recording control
  SESSION_START: 'session_start',
  SESSION_STOP: 'session_stop',
  
  // Replay control
  GET_SESSIONS: 'get_sessions',
  GET_RECORDED_PROVIDERS: 'get_recorded_providers',
  REPLAY_LOAD: 'replay_load',
  REPLAY_ACTION: 'replay_action',
  DELETE_SESSION: 'delete_session',

  // Script Management
  GET_AVAILABLE_SCRIPTS: 'get_available_scripts',
  START_CLIENT_SCRIPT: 'start_client_script',
  STOP_CLIENT_SCRIPT: 'stop_client_script',

  // Task Subscriptions
  SUBSCRIBE_TASK: 'subscribe_task',
  UNSUBSCRIBE_TASK: 'unsubscribe_task'
};

// Internal app events forwarded by the dispatcher to React hooks.
export const APP_EVENTS = {
  ON_CONNECTION_ESTABLISHED: 'onConnectionEstablished',
  ON_DISCONNECT: 'onDisconnect',
  ON_CONNECTION_ERROR: 'onConnectionError',
  ON_RECONNECT: 'onReconnect',
  ON_RECONNECT_ERROR: 'onReconnectError',
  ON_RECONNECT_FAILED: 'onReconnectFailed',
  
  // Hardware and data
  ON_PROVIDER_UPDATE: 'onProviderUpdate',
  ON_PROVIDER_OFFLINE: 'onProviderOffline',
  ON_PROVIDER_META_CHANGED: 'onProviderMetaChanged',
  ON_DATA_STREAM: 'onDataStream',
  
  // Scripts and recording
  ON_SESSION_STATUS: 'onSessionStatus',
  ON_SCRIPTS_UPDATE: 'onScriptsUpdate',

  // Replay
  ON_REPLAY_STATUS: 'onReplayStatus',
  ON_REPLAY_PROGRESS: 'onReplayProgress',
  ON_REPLAY_LOADED: 'onReplayLoaded',
  ON_SESSION_LIST: 'onSessionList',
  ON_RECORDED_PROVIDERS: 'onRecordedProviders',
  ON_TASK_REJECTED: 'onTaskRejected',
  ON_ACTIVE_TASKS_SNAPSHOT: 'onActiveTasksSnapshot'
};