# Python API Reference

_Auto-generated file. Do not edit manually._

Generated: 2026-05-25 08:30:18 UTC

## elab_api/__init__.py

elab_api – Local API Bridge client library for E-Lab.

## elab_api/local_node.py

LocalNode – the primary user-facing class for external scripts.

### Classes in elab_api/local_node.py

#### LocalNode

Lightweight client that connects an external script to the E-Lab Bridge.

Methods:

- `register_task(self, task_id: str, task_type: str = 'SENSOR', template: str = 'tpl_generic_sensor', config: Optional[List[Dict[str, Any]]] = None, name: Optional[str] = None, color: Optional[str] = None, tags: Optional[List[str]] = None, unit: Optional[str] = None, sample_rate: Optional[int] = None, ui_mode: str = 'generic', ui_url: Optional[str] = None, ui_component_name: Optional[str] = None, ui_integrity: Optional[str] = None) -> None`
  - Register a task with the E-Lab dispatcher via the Bridge.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|task_id|str|-|Unique identifier for this task.|
|task_type|str|'SENSOR'|E-Lab task type (SENSOR, ACTUATOR, MATH, MEASURE, CONTROL, GENERATOR).|
|template|str|'tpl_generic_sensor'|Frontend template ID (e.g. ``tpl_generic_sensor``, ``tpl_metric``). See [template_reference.md](template_reference.md).|
|config|Optional[List[Dict[str, Any]]]|None|Array of configFields conforming to the E-Lab schema. These are passed verbatim to generate the DeviceConfigWidget in the UI. Schema details in [schema_reference.md](schema_reference.md).|
|name|Optional[str]|None|Display name. Defaults to _task_id_.|
|color|Optional[str]|None|Default hex color (e.g. ``#ef4444``).|
|tags|Optional[List[str]]|None|Freeform tags for UI filtering.|
|unit|Optional[str]|None|Measurement unit.|
|sample_rate|Optional[int]|None|Expected sample rate in samples/s.|
|ui_mode|str|'generic'|``generic`` or ``custom``.|
|ui_url|Optional[str]|None|URL to custom JS plugin (mode=custom).|
|ui_component_name|Optional[str]|None|React component name (mode=custom).|
|ui_integrity|Optional[str]|None|SRI hash for the plugin script.|

- `register_math_task(self, task_id: str, template: str = 'system_mean_v1', config: Optional[List[Dict[str, Any]]] = None, name: Optional[str] = None, color: Optional[str] = None, tags: Optional[List[str]] = None, unit: Optional[str] = None) -> None`
  - Register a MATH task with an input slot (like Mean).
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|task_id|str|-|Unique identifier for this task.|
|template|str|'system_mean_v1'|Frontend template ID (default: ``system_mean_v1``). See [template_reference.md](template_reference.md).|
|config|Optional[List[Dict[str, Any]]]|None|Array of configFields for the DeviceConfigWidget. Schema details in [schema_reference.md](schema_reference.md).|
|name|Optional[str]|None|Display name. Defaults to _task_id_.|
|color|Optional[str]|None|Default hex color.|
|tags|Optional[List[str]]|None|Freeform tags.|
|unit|Optional[str]|None|Measurement unit.|

- `on_config_update(self, task_id: str) -> Callable`
  - Decorator to register a callback for config changes from the UI.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|task_id|str|-|-|

- `on_input_update(self, task_id: str) -> Callable`
  - Decorator for when the user assigns/removes an input source in the UI.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|task_id|str|-|-|

- `on_stream(self, source_id: str) -> Callable`
  - Decorator to register a callback for data from a fixed source.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|source_id|str|-|-|

- `on_dynamic_stream(self) -> Callable`
  - Decorator for data from whichever source the UI currently assigns.
Parameters: none

- `publish(self, task_id: str, data: np.ndarray) -> None`
  - Publish data for a task via shared memory.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|task_id|str|-|The task whose data channel to write to.|
|data|np.ndarray|-|Samples to publish.|

- `send_command(self, target_task_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`
  - Send an actor command through the bridge to another task.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|target_task_id|str|-|The task to command.|
|action|str|-|Command action key. Command/event details in [api.md](api.md#execute_command).|
|payload|Optional[Dict[str, Any]]|None|Additional command data.|

- `fetch_history(self, session_id: str, source_id: str, start_time: Optional[float] = None, end_time: Optional[float] = None) -> np.ndarray`
  - Fetch historical session data as a NumPy array.
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|session_id|str|-|Recorded session identifier.|
|source_id|str|-|The source/task to retrieve data for.|
|start_time|Optional[float]|None|Start timestamp filter.|
|end_time|Optional[float]|None|End timestamp filter.|

- `run(self) -> None`
  - Start the node, connect to the bridge, and enter the event loop.
Parameters: none

- `stop(self) -> None`
  - Gracefully disconnect and release resources.
Parameters: none

## elab_api/shared_memory_channel.py

Shared memory channel for zero-copy data transfer between bridge and scripts.

### Classes in elab_api/shared_memory_channel.py

#### SharedMemoryChannel

A ring-buffer backed by OS shared memory for zero-copy NumPy transfers.

Methods:

- `write_index(self) -> int`
  - Current writer position in the ring buffer.
Parameters: none

- `timestamp_ns(self) -> int`
  - Timestamp (nanoseconds) of the last write.
Parameters: none

- `write(self, data: np.ndarray) -> None`
  - Write a chunk of data into the ring buffer (producer side).
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|data|np.ndarray|-|-|

- `read_latest(self, count: int) -> np.ndarray`
  - Read the latest _count_ samples from the ring buffer (consumer side).
Parameters:

|Parameter|Type|Default|Description|
|---|---|---|---|
|count|int|-|-|

- `close(self) -> None`
  - Detach from the shared memory block.
Parameters: none

- `unlink(self) -> None`
  - Remove the shared memory block from the OS (creator only).
Parameters: none

## elab_bridge/bridge_daemon.py

E-Lab Local API Bridge Daemon.

### Classes in elab_bridge/bridge_daemon.py

#### ConnectedNode

Represents a single connected external script.

Methods:

- `is_alive(self) -> bool`
  - No documentation.
Parameters: none

- `touch(self) -> None`
  - No documentation.
Parameters: none

#### BridgeDaemon

The Local API Bridge Daemon.

Methods:

- `start(self) -> None`
  - Start the Bridge Daemon.
Parameters: none

- `stop(self) -> None`
  - Gracefully stop the Bridge Daemon.
Parameters: none

- `run_forever(self) -> None`
  - Start and block until interrupted.
Parameters: none

### Functions in elab_bridge/bridge_daemon.py

- `main() -> None`
  - Run the Bridge Daemon as a standalone process.
Parameters: none
