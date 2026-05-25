#!/usr/bin/env python3
"""
Scan UI templates and generate markdown documentation.

This script scans template definitions and template usage references in the
frontend source and creates a markdown reference for developers.

Usage:
    python tools/scan_templates.py
    python tools/scan_templates.py --output doc/template_reference.md
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class TemplateDefinition:
    template_id: str
    name: str
    export_name: str
    source_file: Path
    definition_kind: str


@dataclass
class TemplateReference:
    key: str
    template_id: str
    source_file: Path


class TemplateScanner:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.frontend_src = self.repo_root / "elab_workbench" / "src"
        self.plugins_dir = self.frontend_src / "plugins"
        self.core_templates_dir = self.plugins_dir / "core" / "templates"

    @staticmethod
    def _read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _rel(path: Path, root: Path) -> str:
        return path.relative_to(root).as_posix()

    def _source_files(self) -> List[Path]:
        exts = {".js", ".jsx", ".ts", ".tsx"}
        files: List[Path] = []
        for p in self.frontend_src.rglob("*"):
            if p.is_file() and p.suffix in exts:
                files.append(p)
        return sorted(files)

    def scan_template_definitions(self) -> List[TemplateDefinition]:
        definitions: List[TemplateDefinition] = []
        files = self._source_files()

        # Pattern 1: export const X = new PluginBuilder("id", "name", "UI_TEMPLATE")
        builder_re = re.compile(
            r'export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*new\s+PluginBuilder\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"UI_TEMPLATE"\s*\)',
            re.S,
        )

        # Pattern 2: export const X = { id: "...", name: "...", type: "UI_TEMPLATE" }
        object_re = re.compile(
            r'export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{([\s\S]*?)\};',
            re.S,
        )

        id_re = re.compile(r'id\s*:\s*"([^"]+)"')
        name_re = re.compile(r'name\s*:\s*"([^"]+)"')
        type_re = re.compile(r'type\s*:\s*"UI_TEMPLATE"')

        seen: set[Tuple[str, str]] = set()

        for file_path in files:
            content = self._read_text(file_path)

            for m in builder_re.finditer(content):
                export_name, template_id, name = m.groups()
                key = (template_id, str(file_path))
                if key in seen:
                    continue
                seen.add(key)
                definitions.append(
                    TemplateDefinition(
                        template_id=template_id,
                        name=name,
                        export_name=export_name,
                        source_file=file_path,
                        definition_kind="PluginBuilder",
                    )
                )

            for m in object_re.finditer(content):
                export_name, obj_body = m.groups()
                if not type_re.search(obj_body):
                    continue
                id_match = id_re.search(obj_body)
                name_match = name_re.search(obj_body)
                if not id_match:
                    continue

                template_id = id_match.group(1)
                name = name_match.group(1) if name_match else export_name
                key = (template_id, str(file_path))
                if key in seen:
                    continue
                seen.add(key)

                definitions.append(
                    TemplateDefinition(
                        template_id=template_id,
                        name=name,
                        export_name=export_name,
                        source_file=file_path,
                        definition_kind="Object",
                    )
                )

        return sorted(definitions, key=lambda d: (d.template_id, d.name, d.export_name))

    def scan_template_references(self) -> List[TemplateReference]:
        references: List[TemplateReference] = []
        files = self._source_files()
        ref_re = re.compile(r'\b(defaultTemplate|template)\s*:\s*"([^"]+)"')

        for file_path in files:
            content = self._read_text(file_path)
            for m in ref_re.finditer(content):
                references.append(
                    TemplateReference(
                        key=m.group(1),
                        template_id=m.group(2),
                        source_file=file_path,
                    )
                )

        return references

    def generate_markdown(self) -> str:
        definitions = self.scan_template_definitions()
        references = self.scan_template_references()

        refs_by_id: Dict[str, List[TemplateReference]] = {}
        for ref in references:
            refs_by_id.setdefault(ref.template_id, []).append(ref)

        known_ids = {d.template_id for d in definitions}
        unknown_ref_ids = sorted(set(refs_by_id.keys()) - known_ids)

        lines: List[str] = []
        lines.append("# Template Reference")
        lines.append("")
        lines.append("> Auto-generated by tools/scan_templates.py")
        lines.append("")
        lines.append("## Naming Convention")
        lines.append("")
        lines.append("| Prefix | Role | Externally referenceable? |")
        lines.append("|--------|------|--------------------------|")
        lines.append("| `tpl_generic_<type>` | Fallback template per task type (SENSOR, MATH, ACTUATOR, CONTROL, GENERATOR). Used automatically when no specific view is configured. | Yes (automatic fallback) |")
        lines.append("| `tpl_<name>` | Reusable view components, **task-type independent**. These are the building blocks for `views[]` arrays. A `tpl_scope` can appear in a SENSOR, MEASURE, or GENERATOR task. | **Yes** — use freely in any manifest |")
        lines.append("| `system_<name>` | Self-contained plugin UIs that manage their own rendering. Tightly coupled to a specific plugin. Not intended to be referenced by external tasks. | No — internal only |")
        lines.append("")
        lines.append("### Quick Reference for Plugin Developers")
        lines.append("")
        lines.append("```")
        lines.append("\"Which views can I assign to my task?\"")
        lines.append("")
        lines.append("→ Use any tpl_* template in your views[] array:")
        lines.append("  tpl_scope              Time-domain graph")
        lines.append("  tpl_metric             SI auto-range metric display")
        lines.append("  tpl_spectrum           FFT frequency-domain graph")
        lines.append("  tpl_spectrum_config    Spectrum settings panel")
        lines.append("  tpl_device_config      Generic configuration panel")
        lines.append("")
        lines.append("→ If you don't specify views, the system uses tpl_generic_<your_task_type>")
        lines.append("```")
        lines.append("")
        lines.append("### Registering a `system_*` Template")
        lines.append("")
        lines.append("Plugins that provide their own UI (e.g. FIR Filter, Mean) need a **separate")
        lines.append("template export** so the `PluginRegistry` can resolve the template ID.")
        lines.append("The plugin ID (`system_*_v1`) and the template ID (`system_*`) are intentionally")
        lines.append("different — the plugin owns the task lifecycle, the template owns the rendering.")
        lines.append("")
        lines.append("```jsx")
        lines.append("// 1. Plugin with createTask + simulation (plugin ID = system_example_v1)")
        lines.append('export const ExamplePlugin = new PluginBuilder("system_example_v1", "Example", "MATH")')
        lines.append("    .setRender(ExampleWidget)")
        lines.append("    .setCreateTask(() => ({")
        lines.append('        id: `example_${Date.now()}`,')
        lines.append('        groupId: "system_example_v1",')
        lines.append('        type: "MATH",')
        lines.append('        name: "Example",')
        lines.append("        ui: {")
        lines.append('            mode: "generic",')
        lines.append('            defaultTemplate: "system_example",  // ← references the template below')
        lines.append("            views: [")
        lines.append('                { id: "config", label: "Config", icon: "Settings", template: "system_example" },')
        lines.append("            ],")
        lines.append("        },")
        lines.append("    }))")
        lines.append("    .build();")
        lines.append("")
        lines.append("// 2. Separate template export (template ID = system_example)")
        lines.append("export const ExampleTemplate = {")
        lines.append('    id: "system_example",')
        lines.append('    name: "Example Config",')
        lines.append('    type: "UI_TEMPLATE",')
        lines.append("    render: ExampleWidget,")
        lines.append("};")
        lines.append("```")
        lines.append("")
        lines.append("> **Note:** `system_*` views can also reference `tpl_*` templates in their")
        lines.append("> `views[]` array (e.g. `tpl_metric` for a numeric display alongside a custom config view).")
        lines.append("")
        lines.append("## Overview")
        lines.append("")
        lines.append(f"- Defined templates: {len(definitions)}")
        lines.append(f"- Template references: {len(references)}")
        lines.append(f"- Unknown references: {len(unknown_ref_ids)}")
        lines.append("")

        lines.append("## Template Definitions")
        lines.append("")
        lines.append("| Template ID | Name | Export | Kind | Source | References |")
        lines.append("|-------------|------|--------|------|--------|------------|")

        for d in definitions:
            source = self._rel(d.source_file, self.repo_root)
            ref_count = len(refs_by_id.get(d.template_id, []))
            lines.append(
                f"| `{d.template_id}` | {d.name} | `{d.export_name}` | {d.definition_kind} | `{source}` | {ref_count} |"
            )

        lines.append("")
        lines.append("## Template Usage")
        lines.append("")
        lines.append("| Template ID | Key | Source |")
        lines.append("|-------------|-----|--------|")

        for template_id in sorted(refs_by_id):
            for ref in sorted(refs_by_id[template_id], key=lambda r: (str(r.source_file), r.key)):
                source = self._rel(ref.source_file, self.repo_root)
                lines.append(f"| `{template_id}` | `{ref.key}` | `{source}` |")

        if unknown_ref_ids:
            lines.append("")
            lines.append("## Unknown Template References")
            lines.append("")
            lines.append(
                "These IDs are referenced in code but not defined as UI_TEMPLATE in scanned files."
            )
            lines.append("")
            for unknown_id in unknown_ref_ids:
                lines.append(f"- `{unknown_id}`")

        if self.core_templates_dir.exists():
            lines.append("")
            lines.append("## Core Template Files")
            lines.append("")
            for p in sorted(self.core_templates_dir.glob("*.jsx")):
                lines.append(f"- `{self._rel(p, self.repo_root)}`")

        lines.append("")
        return "\n".join(lines)

    def save(self, output_path: Path) -> None:
        content = self.generate_markdown()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan templates and generate markdown reference")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("doc/template_reference.md"),
        help="Output markdown path (default: doc/template_reference.md)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    scanner = TemplateScanner(repo_root)

    output = args.output if args.output.is_absolute() else repo_root / args.output
    scanner.save(output)

    print("Template reference generated.")
    print(f"Output: {output.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
