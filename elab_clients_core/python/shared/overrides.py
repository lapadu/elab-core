"""Persistence layer for user overrides (color, name, config) as a lightweight cache."""
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def load_overrides(manifest: Dict[str, Any], overrides_file: str) -> None:
    """Loads saved user overrides and applies them to the manifest."""
    try:
        with open(overrides_file, 'r', encoding='utf-8') as f:
            overrides = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info("No saved overrides found (%s), using defaults.", overrides_file)
        return

    for task in manifest.get('tasks', []):
        task_overrides = overrides.get(task['id'], {})
        if 'color' in task_overrides:
            task['color'] = task_overrides['color']
        if 'name' in task_overrides:
            task['name'] = task_overrides['name']
        if 'config' in task_overrides and task.get('config'):
            task['config'].update(task_overrides['config'])
    logger.info("Overrides from '%s' applied.", overrides_file)


def save_overrides(manifest: Dict[str, Any], overrides_file: str) -> None:
    """Stores only user-editable fields (color, name, config) in the cache."""
    overrides: Dict[str, Any] = {}
    for task in manifest.get('tasks', []):
        overrides[task['id']] = {
            'color': task.get('color'),
            'name': task.get('name'),
            'config': task.get('config', {})
        }
    with open(overrides_file, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, indent=2)
    logger.info("Overrides saved to '%s'.", overrides_file)


def apply_task_meta_update(
    manifest: Dict[str, Any],
    target_id: str,
    payload: Dict[str, Any],
) -> bool:
    """Apply mutable UI metadata updates to one task in a manifest."""
    for task in manifest.get('tasks', []):
        if task.get('id') != target_id:
            continue
        if 'color' in payload:
            task['color'] = payload['color']
        if 'name' in payload:
            task['name'] = payload['name']
        return True
    return False
