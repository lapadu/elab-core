"""A utility module for building and validating E-Lab provider manifests."""
import json
import logging
from typing import Dict, Any, Literal, Optional
import os
import jsonschema

from .decoders import DecoderRegistry

logger = logging.getLogger(__name__)

# pylint: disable=C0301

class ManifestBuilder:
    """Builder class for creating valid E-Lab provider manifests."""
    def __init__(self, provider_id: str, name: str, schema_dict: Optional[Dict[str, Any]] = None,
                 category: str = "HARDWARE", persist_config: bool = False):
        self.manifest = {
            "id": provider_id,
            "name": name,
            "category": category,
            "providerVersion": "1.0.0",
            "apiVersion": "2.0.0",
            "persistConfig": persist_config,
            "tasks": []
        }
        if schema_dict:
            self.schema = schema_dict
        else:
            # Fallback: try both schema locations used by the project layouts.
            # 1. In the same directory, for the Raspberry Pi shared layout.
            local_schema_path = os.path.join(os.path.dirname(__file__), 'ManifestSchema.json')
            # 2. In the default development directory.
            dev_schema_path = os.path.join(os.path.dirname(__file__), '..', 'schemas', 'ManifestSchema.json')

            schema_path_to_use = None
            if os.path.exists(local_schema_path):
                schema_path_to_use = local_schema_path
            elif os.path.exists(dev_schema_path):
                schema_path_to_use = dev_schema_path

            if schema_path_to_use:
                with open(schema_path_to_use, 'r', encoding='utf-8') as f:
                    self.schema = json.load(f)
            else:
                raise FileNotFoundError("Could not find 'ManifestSchema.json' in local dir or dev path.")

    _SUPPORTED_TASK_OPTIONS = {
        'group_id',
        'color',
        'virtual',
        'config',
        'ui_template',
        'ui_url',
        'ui_integrity',
        'ui_component_name',
        'ui_views',
        'ui_default_template',
        'decoder',
        'group',
        'actions',
        'tags',
    }

    def add_task(
        self,
        task_id: str,
        name: str,
        task_type: Literal["SENSOR", "ACTUATOR", "MATH", "MEASURE", "CONTROL", "GENERATOR"],
        ui_mode: Literal["generic", "custom"],
        **task_options: Any,
    ) -> 'ManifestBuilder':
        """Adds a new task to the manifest."""
        unknown_options = set(task_options) - self._SUPPORTED_TASK_OPTIONS
        if unknown_options:
            joined = ", ".join(sorted(unknown_options))
            raise TypeError(f"Unknown task option(s): {joined}")

        task = {
            "id": task_id,
            "name": name,
            "type": task_type,
            "ui": {"mode": ui_mode}
        }
        self._apply_task_options(task, task_options)

        decoder = task_options.get('decoder')
        if decoder is not None:
            self._validate_decoder(decoder, task_id)
            task["decoder"] = decoder

        self.manifest["tasks"].append(task)
        return self

    @staticmethod
    def _apply_task_options(task: Dict[str, Any], task_options: Dict[str, Any]) -> None:
        """Apply optional task fields from ``task_options`` to a task dict."""
        direct_mapping = {
            'group_id': 'groupId',
            'color': 'color',
            'config': 'config',
            'group': 'group',
            'actions': 'actions',
            'tags': 'tags',
        }
        for option_key, manifest_key in direct_mapping.items():
            value = task_options.get(option_key)
            if value is not None:
                task[manifest_key] = value

        if task_options.get('virtual'):
            task['virtual'] = True

        ui_mapping = {
            'ui_template': 'template',
            'ui_url': 'url',
            'ui_integrity': 'integrity',
            'ui_component_name': 'componentName',
            'ui_views': 'views',
            'ui_default_template': 'defaultTemplate',
        }
        for option_key, ui_key in ui_mapping.items():
            value = task_options.get(option_key)
            if value is not None:
                task['ui'][ui_key] = value

    @staticmethod
    def _validate_decoder(decoder: Dict[str, Any], task_id: str) -> None:
        """Validate a decoder block against the registry early at build time."""
        if not isinstance(decoder, dict):
            raise ValueError(f"Decoder for task '{task_id}' must be a dict.")
        dec_type = decoder.get("type")
        if not dec_type or not isinstance(dec_type, str):
            raise ValueError(f"Decoder for task '{task_id}' missing 'type'.")
        if DecoderRegistry.get_decoder(dec_type) is None:
            available = ", ".join(DecoderRegistry.list_decoders()) or "<none>"
            raise ValueError(
                f"Unknown decoder type '{dec_type}' for task '{task_id}'. "
                f"Available: {available}"
            )
        params = decoder.get("parameters", {})
        if params is not None and not isinstance(params, dict):
            raise ValueError(
                f"Decoder 'parameters' for task '{task_id}' must be a dict."
            )

    def build(self) -> Dict[str, Any]:
        """Validates the manifest against the JSON schema and returns it."""
        try:
            jsonschema.validate(instance=self.manifest, schema=self.schema)
        except jsonschema.exceptions.ValidationError as err:  # type: ignore[attr-defined]
            print("Manifest validation error:", err)
            raise err
        return self.manifest
