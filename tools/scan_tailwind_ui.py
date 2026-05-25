#!/usr/bin/env python3
"""
Generate Tailwind CSS class documentation by scanning source files.

This script scans elab_workbench/src plus core/premium client assets for Tailwind classes
and generates a markdown documentation file with all available classes.
Includes custom plugin classes defined in tailwind.config.js.

Usage:
    python tools/scan_tailwind_ui.py
    python tools/scan_tailwind_ui.py --output doc/custom-output.md
"""

import re
import sys
import html
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set
import argparse


class TailwindDocGenerator:
    """Generate Tailwind CSS documentation from source files."""

    # Custom plugin classes from tailwind.config.js
    CUSTOM_CLASSES = [
        {
            "name": ".transform-style-3d",
            "description": "CSS `transformStyle: preserve-3d`"
        },
        {
            "name": ".perspective-1000",
            "description": "CSS `perspective: 1000px`"
        },
        {
            "name": ".rotate-y-180",
            "description": "CSS `transform: rotateY(180deg)`"
        },
        {
            "name": ".backface-hidden",
            "description": "CSS `backfaceVisibility: hidden`"
        },
    ]

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.shared_file = (
            self.project_root / "elab_workbench" / "src" / "utils" / "Shared.jsx"
        )
        self.generated_icon_dir = self.project_root / "doc" / "assets" / "icons"
        self.public_dir = self.project_root / "elab_workbench" / "public"
        self.preview_html = self.project_root / "doc" / "ui_reference_preview.html"
        self.found_classes: Dict[str, Dict] = {}
        self.icons: List[Dict[str, str]] = []
        self.color_palette: List[str] = []
        self.system_colors: List[str] = []
        self.system_color_tokens: List[Dict[str, str]] = []
        self.highlight_hex: Dict[str, Dict] = {}
        self.source_paths = [
            self.project_root / "elab_workbench" / "src",
            self.project_root / "elab_clients_core" / "python" / "assets",
            self.project_root / "elab_clients_premium" / "python" / "assets",
        ]

        # Initialize custom classes
        for custom_class in self.CUSTOM_CLASSES:
            self.found_classes[custom_class["name"]] = {
                "name": custom_class["name"],
                "description": custom_class["description"],
                "type": "Custom Plugin",
                "count": 0,
                "files": set(),
            }

    def scan_sources(self) -> None:
        """Scan source directories for Tailwind classes."""
        print("Scanning for Tailwind CSS classes...")

        for source_path in self.source_paths:
            if not source_path.exists():
                print(f"Warning: source path not found: {source_path}")
                continue

            print(f"   Scanning: {source_path}")
            self._scan_directory(source_path)

    def _scan_directory(self, directory: Path) -> None:
        """Recursively scan directory for class usage."""
        # File extensions to scan
        extensions = {".jsx", ".tsx", ".js", ".ts"}

        for file_path in directory.rglob("*"):
            # Skip test files and non-matching extensions
            if file_path.suffix not in extensions or file_path.stem.endswith(
                (".spec", ".test")
            ):
                continue

            self._scan_file(file_path)

    def _scan_file(self, file_path: Path) -> None:
        """Extract Tailwind classes from a single file."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"   Warning: error reading {file_path}: {e}")
            return

        class_strings: List[str] = []

        # Simple string attributes: className="..." and class="..."
        class_strings.extend(
            match.group(1)
            for match in re.finditer(r'className\s*=\s*"([^"]+)"', content)
        )
        class_strings.extend(
            match.group(1)
            for match in re.finditer(r"className\s*=\s*'([^']+)'", content)
        )
        class_strings.extend(
            match.group(1)
            for match in re.finditer(r'class\s*=\s*"([^"]+)"', content)
        )
        class_strings.extend(
            match.group(1)
            for match in re.finditer(r"class\s*=\s*'([^']+)'", content)
        )

        # Template literal direct usage: className={`...`}
        class_strings.extend(
            match.group(1)
            for match in re.finditer(r'className\s*=\s*\{`([^`]+)`\}', content)
        )

        # Expression usage: className={condition ? 'a b' : 'c d'}
        # Only collect quoted parts from inside the expression.
        for expr_match in re.finditer(r'className\s*=\s*\{([^\n]+)\}', content):
            expression = expr_match.group(1)
            for quoted in re.finditer(r'"([^"]+)"|\'([^\']+)\'|`([^`]+)`', expression):
                class_value = next(group for group in quoted.groups() if group is not None)
                class_strings.append(class_value)

        for class_string in class_strings:
            class_string = re.sub(r"\$\{[^}]*\}", "", class_string)
            classes = re.split(r"\s+", class_string)

            for cls in classes:
                cls = cls.strip().strip("`'\",;{}")
                if not cls:
                    continue
                if any(char in cls for char in ["$", "?", "=", "&", "(", ")"]):
                    continue
                if cls in {":", "}"}:
                    continue

                class_name = f".{cls}" if not cls.startswith(".") else cls
                if class_name not in self.found_classes:
                    self.found_classes[class_name] = {
                        "name": class_name,
                        "description": "",
                        "type": "Tailwind Built-in",
                        "count": 0,
                        "files": set(),
                    }

                self.found_classes[class_name]["count"] += 1
                self.found_classes[class_name]["files"].add(file_path.name)

    @staticmethod
    def _pascal_to_kebab(name: str) -> str:
        """Convert icon name from PascalCase to kebab-case for lucide-static URLs."""
        value = re.sub(r"(?<!^)(?=[A-Z])", "-", name)
        value = re.sub(r"(?<=[A-WY-Za-wy-z])(?=[0-9])", "-", value)
        return value.replace("--", "-").lower()

    @staticmethod
    def _img_preview(src: str, alt: str, bg_color: str = "#ffffff") -> str:
        """Return a markdown-friendly image preview that is visible in dark themes."""
        safe_alt = html.escape(alt)
        safe_src = html.escape(src)
        return (
            f'<img src="{safe_src}" alt="{safe_alt}" width="22" height="22" '
            f'style="background:{bg_color};border:1px solid #cbd5e1;border-radius:4px;padding:2px;" />'
        )

    def _extract_local_svg_icons(self, content: str) -> Dict[str, str]:
        """Extract SVG markup from local icon components in Shared.jsx."""
        extracted: Dict[str, str] = {}
        pattern = re.compile(
            r"export const\s+([A-Za-z_][A-Za-z0-9_]*Icon[A-Za-z0-9_]*)\s*=\s*\([^)]*\)\s*=>\s*\((.*?)\);",
            re.S,
        )

        for match in pattern.finditer(content):
            icon_name = match.group(1)
            svg_block = match.group(2).strip()
            svg_match = re.search(r"(<svg[\s\S]*?</svg>)", svg_block)
            if not svg_match:
                continue

            svg_markup = svg_match.group(1)
            svg_markup = re.sub(r"\{\/\*[\s\S]*?\*\/\}", "", svg_markup)
            svg_markup = re.sub(r"/\*[\s\S]*?\*/", "", svg_markup)
            svg_markup = svg_markup.replace("{size}", '"24"')
            svg_markup = svg_markup.replace("{className}", '""')
            svg_markup = svg_markup.replace("className=\"\"", "")
            svg_markup = svg_markup.replace("strokeWidth", "stroke-width")
            svg_markup = svg_markup.replace("strokeLinecap", "stroke-linecap")
            svg_markup = svg_markup.replace("strokeLinejoin", "stroke-linejoin")
            svg_markup = svg_markup.replace('stroke="currentColor"', 'stroke="#e2e8f0"')
            svg_markup = re.sub(r"\s+", " ", svg_markup).strip()

            extracted[icon_name] = svg_markup

        return extracted

    def _write_local_svg_icons(self, svg_icons: Dict[str, str]) -> Dict[str, str]:
        """Write extracted local icons into doc/assets/icons and return relative paths."""
        paths: Dict[str, str] = {}
        if not svg_icons:
            return paths

        self.generated_icon_dir.mkdir(parents=True, exist_ok=True)
        for icon_name, svg_markup in svg_icons.items():
            file_name = f"{self._pascal_to_kebab(icon_name)}.svg"
            file_path = self.generated_icon_dir / file_name
            file_path.write_text(svg_markup + "\n", encoding="utf-8")
            relative = file_path.relative_to(self.project_root / "doc").as_posix()
            paths[icon_name] = relative

        return paths

    def extract_icons(self) -> None:
        """Extract icon names from Shared.jsx Icons export."""
        if not self.shared_file.exists():
            return

        content = self.shared_file.read_text(encoding="utf-8")
        icons_block = re.search(r"export const Icons\s*=\s*\{(.*?)\};", content, re.S)
        lucide_icons: Set[str] = set()
        if icons_block:
            lucide_icons = set(
                re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", icons_block.group(1))
            )

        local_svg_icons = self._extract_local_svg_icons(content)
        local_icon_paths = self._write_local_svg_icons(local_svg_icons)

        icons: List[Dict[str, str]] = []
        for icon_name in sorted(lucide_icons):
            icon_slug = self._pascal_to_kebab(icon_name)
            preview_url = f"https://unpkg.com/lucide-static@1.16.0/icons/{icon_slug}.svg"
            icons.append(
                {
                    "name": icon_name,
                    "package": "lucide-react",
                    "preview": self._img_preview(preview_url, icon_name),
                }
            )

        for icon_name in sorted(local_icon_paths):
            if icon_name in lucide_icons:
                continue
            icons.append(
                {
                    "name": icon_name,
                    "package": "local Shared.jsx",
                    "preview": self._img_preview(
                        local_icon_paths[icon_name], icon_name, bg_color="#0f172a"
                    ),
                }
            )

        self.icons = sorted(icons, key=lambda item: item["name"])

    def extract_public_logos(self) -> None:
        """Add logos from elab_workbench/public to icon list."""
        if not self.public_dir.exists():
            return

        logo_extensions = {".svg", ".png", ".jpg", ".jpeg", ".webp"}
        public_logos: List[Dict[str, str]] = []

        for file_path in sorted(self.public_dir.iterdir(), key=lambda item: item.name.lower()):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in logo_extensions:
                continue
            if "logo" not in file_path.stem.lower():
                continue

            rel_from_doc = file_path.relative_to(self.project_root).as_posix()
            preview_src = f"../{rel_from_doc}"
            public_logos.append(
                {
                    "name": file_path.name,
                    "package": "elab_workbench/public",
                    "preview": self._img_preview(preview_src, file_path.name, bg_color="#0f172a"),
                }
            )

        if public_logos:
            self.icons.extend(public_logos)
            self.icons = sorted(self.icons, key=lambda item: item["name"].lower())

    def extract_color_palette(self) -> None:
        """Extract COLOR_PALETTE values from Shared.jsx."""
        if not self.shared_file.exists():
            return

        content = self.shared_file.read_text(encoding="utf-8")
        palette_block = re.search(
            r"export const COLOR_PALETTE\s*=\s*\[(.*?)\];", content, re.S
        )
        if not palette_block:
            return

        palette_values = re.findall(r"#[0-9a-fA-F]{3,8}", palette_block.group(1))
        self.color_palette = sorted(set(color.lower() for color in palette_values))

    def extract_system_colors(self) -> None:
        """Extract SYSTEM_COLORS values from Shared.jsx."""
        if not self.shared_file.exists():
            return

        content = self.shared_file.read_text(encoding="utf-8")
        system_block = re.search(
            r"export const SYSTEM_COLORS\s*=\s*\{(.*?)\};", content, re.S
        )
        if not system_block:
            return

        tokens: List[Dict[str, str]] = []
        for section_match in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\{(.*?)\}",
            system_block.group(1),
            re.S,
        ):
            section_name = section_match.group(1)
            section_content = section_match.group(2)
            for key_match in re.finditer(
                r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*['\"](#[0-9a-fA-F]{3,8})['\"]",
                section_content,
            ):
                token = f"{section_name}.{key_match.group(1)}"
                tokens.append({"token": token, "value": key_match.group(2).lower()})

        self.system_color_tokens = sorted(tokens, key=lambda item: item["token"].lower())
        self.system_colors = sorted({item["value"] for item in self.system_color_tokens})

    def scan_highlight_hex_values(self) -> None:
        """Scan source files for hex color values used as highlights/styles."""
        hex_values: Dict[str, Dict] = {}
        extensions = {".jsx", ".tsx", ".js", ".ts", ".css"}

        for source_path in self.source_paths:
            if not source_path.exists():
                continue

            for file_path in source_path.rglob("*"):
                if file_path.suffix not in extensions:
                    continue
                if file_path.stem.endswith((".spec", ".test")):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                for value in re.findall(r"#[0-9a-fA-F]{3,8}\b", content):
                    normalized = value.lower()
                    if normalized not in hex_values:
                        hex_values[normalized] = {"count": 0, "files": set()}
                    hex_values[normalized]["count"] += 1
                    hex_values[normalized]["files"].add(file_path.name)

        self.highlight_hex = hex_values

    @staticmethod
    def _color_swatch(color: str) -> str:
        """Return a small HTML swatch suitable for markdown tables."""
        return (
            f"<span style=\"display:inline-block;width:20px;height:12px;"
            f"background:{color};border:1px solid #999;\"></span>"
        )

    @staticmethod
    def _class_anchor(class_name: str) -> str:
        """Create a stable HTML anchor ID for a class entry."""
        clean = class_name.lstrip(".")
        clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean)
        clean = re.sub(r"-+", "-", clean).strip("-")
        if not clean:
            clean = "class"
        return f"cls-{clean.lower()}"

    def generate_preview_html(self, sorted_classes: List[Dict]) -> None:
        """Generate a standalone HTML page with rendered class previews."""
        rows: List[str] = []
        for cls in sorted_classes:
            class_value = cls["name"].lstrip(".")
            anchor = self._class_anchor(cls["name"])
            escaped_class = html.escape(class_value)
            escaped_name = html.escape(cls["name"])
            escaped_type = html.escape(cls["type"])
            sample = (
                f'<div class="demo-target {escaped_class}">'
                f"{escaped_name} sample"
                "</div>"
            )
            rows.append(
                "<tr>"
                f"<td id=\"{anchor}\"><code>{escaped_name}</code></td>"
                f"<td>{escaped_type}</td>"
                f"<td><div class=\"demo-wrap\">{sample}</div></td>"
                "</tr>"
            )

        # Custom plugin fallback styles so these classes are visible without local Tailwind build.
        custom_fallback = """
        .transform-style-3d { transform-style: preserve-3d; }
        .perspective-1000 { perspective: 1000px; }
        .rotate-y-180 { transform: rotateY(180deg); }
        .backface-hidden { backface-visibility: hidden; }
        """

        html_content = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>E-Lab UI Class Preview</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        :root {{ color-scheme: dark; }}
        body {{ background:#0b1220; color:#dbe5f3; font-family: Segoe UI, Arial, sans-serif; margin:0; padding:24px; }}
        .panel {{ background:#111b2e; border:1px solid #2b3a55; border-radius:10px; padding:16px; }}
        table {{ width:100%; border-collapse:collapse; }}
        th, td {{ border-bottom:1px solid #24324a; text-align:left; padding:10px; vertical-align:top; }}
        th {{ position:sticky; top:0; background:#111b2e; }}
        .demo-wrap {{ min-height:44px; display:flex; align-items:center; gap:8px; }}
        .demo-target {{ border:1px dashed #40577a; padding:6px 10px; border-radius:6px; }}
        code {{ background:#0a1324; border:1px solid #2a3852; padding:2px 6px; border-radius:5px; }}
        {custom_fallback}
    </style>
</head>
<body>
    <h1 style="margin:0 0 12px 0;">E-Lab Class Preview</h1>
    <p style="margin:0 0 18px 0; color:#9fb3cf;">Rendered preview for classes found in the project. Hover/variant classes may require interaction.</p>
    <div class="panel">
        <table>
            <thead>
                <tr><th>Class</th><th>Type</th><th>Rendered Preview</th></tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

        self.preview_html.parent.mkdir(parents=True, exist_ok=True)
        self.preview_html.write_text(html_content, encoding="utf-8")

    def generate_markdown(self) -> str:
        """Generate markdown documentation."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Sort classes
        non_palette_highlight_hex = {
            color: data
            for color, data in self.highlight_hex.items()
            if color not in self.color_palette and color not in self.system_colors
        }

        sorted_classes = sorted(
            self.found_classes.values(),
            key=lambda x: (x["type"], -x["count"], x["name"]),
        )
        class_names = {entry["name"].lstrip(".") for entry in self.found_classes.values()}

        def pick(*candidates: str, fallback: str = "") -> str:
            for candidate in candidates:
                if candidate in class_names:
                    return candidate
            return fallback

        # Build markdown
        markdown = f"""# Tailwind CSS Classes Documentation

> Autogenerated documentation of Tailwind CSS classes used in E-Lab.
> This file is auto-generated by `tools/scan_tailwind_ui.py`

## Overview

This document lists all Tailwind CSS classes available in the E-Lab project.
External plugin developers can use these classes in custom UI plugins without
needing to modify the core Tailwind configuration.

**Total Classes Found:** {len(self.found_classes)}
**Total Icons Found:** {len(self.icons)}
**Palette Colors Found:** {len(self.color_palette)}
**System Colors Found:** {len(self.system_colors)}
**Hex Colors in Source (without COLOR_PALETTE and SYSTEM_COLORS):** {len(non_palette_highlight_hex)}
**Custom Plugin Classes:** {len(self.CUSTOM_CLASSES)}
**Generated:** {timestamp}

## Usage

```jsx
// In your custom plugin UI
import {{ useContext }} from 'react';

export function MyCustomWidget() {{
  return (
    <div className="p-4 bg-white rounded-lg shadow">
      <h2 className="text-lg font-bold text-gray-900">
        My Widget
      </h2>
      <p className="text-sm text-gray-600 mt-2">
        You can use any of the classes listed below
      </p>
    </div>
  );
}}
```

## Available Classes

| Class | Type | Usage Count | Description | Demo |
|-------|------|-------------|-------------|------|"""
        
        # Add classes to table
        for cls in sorted_classes:
            usage_count = cls["count"] if cls["count"] > 0 else "-"
            description = cls["description"] if cls["description"] else "-"
            anchor = self._class_anchor(cls["name"])
            demo_link = f"[Preview](ui_reference_preview.html#{anchor})"
            markdown += (
                f"\n| `{cls['name']}` | {cls['type']} | {usage_count} | {description} | {demo_link} |"
            )

        self.generate_preview_html(sorted_classes)

        # Place custom plugin classes directly after available classes for discoverability.
        markdown += "\n\n## Custom Plugin Classes\n\n"
        markdown += "These classes are defined via Tailwind plugins in `tailwind.config.js`:\n"

        for custom_class in self.CUSTOM_CLASSES:
            markdown += f"\n### {custom_class['name']}\n"
            markdown += f"\nImplementation: {custom_class['description']}\n"

        card_example = " ".join(
            filter(
                None,
                [
                    pick("p-4", "p-3", fallback="p-2"),
                    pick("rounded-lg", "rounded-md", fallback="rounded"),
                    pick("border", fallback=""),
                    pick("border-slate-800", "border-slate-700", fallback=""),
                    pick("bg-slate-900", "bg-slate-800", fallback=""),
                    pick("text-slate-200", "text-white", fallback=""),
                    pick("shadow-lg", "shadow-sm", fallback=""),
                ],
            )
        )

        button_example = " ".join(
            filter(
                None,
                [
                    pick("px-3", "px-2", fallback=""),
                    pick("py-1.5", "py-1", fallback=""),
                    pick("rounded", "rounded-md", fallback=""),
                    pick("bg-blue-600", "bg-slate-700", fallback=""),
                    pick("text-white", "text-slate-200", fallback=""),
                    pick("hover:bg-blue-500", "hover:bg-slate-600", fallback=""),
                    pick("transition-colors", fallback=""),
                ],
            )
        )

        layout_example = " ".join(
            filter(
                None,
                [
                    pick("flex", fallback=""),
                    pick("items-center", fallback=""),
                    pick("justify-between", "justify-center", fallback=""),
                    pick("gap-2", "gap-1", fallback=""),
                    pick("w-full", fallback=""),
                ],
            )
        )

        markdown += "\n\n## Class Examples\n\n"
        markdown += "Auto-generated examples based on classes already used in this project.\n\n"
        markdown += "### Card Example\n\n"
        markdown += "```html\n"
        markdown += f'<div class="{card_example}">\n'
        markdown += "  <h3 class=\"text-sm font-bold\">Instrument Panel</h3>\n"
        markdown += "  <p class=\"text-xs\">Shows live values and status.</p>\n"
        markdown += "</div>\n"
        markdown += "```\n\n"

        markdown += "### Button Example\n\n"
        markdown += "```html\n"
        markdown += f'<button class="{button_example}">Save Configuration</button>\n'
        markdown += "```\n\n"

        markdown += "### Layout Example\n\n"
        markdown += "```html\n"
        markdown += f'<div class="{layout_example}">\n'
        markdown += "  <span class=\"text-xs uppercase\">Channel A</span>\n"
        markdown += "  <span class=\"text-sm font-mono\">12.34 V</span>\n"
        markdown += "</div>\n"
        markdown += "```\n"

        markdown += "\n\n## Available Icons\n\n"
        markdown += "Icons are extracted from `elab_workbench/src/utils/Shared.jsx` (`Icons` export).\n\n"
        markdown += "| Icon | Preview | Package |\n"
        markdown += "|------|---------|---------|\n"
        for icon in self.icons:
            markdown += (
                f"| `{icon['name']}` | {icon['preview']} | {icon['package']} |\n"
            )

        markdown += "\n\n## Color Palette\n\n"
        markdown += "Colors from `COLOR_PALETTE` in `elab_workbench/src/utils/Shared.jsx`.\n\n"
        markdown += "| Hex | Preview | Source |\n"
        markdown += "|-----|---------|--------|\n"

        for color in self.color_palette:
            markdown += (
                f"| `{color}` | {self._color_swatch(color)} | COLOR_PALETTE |\n"
            )

        markdown += "\n\n## System Colors\n\n"
        markdown += "Colors from `SYSTEM_COLORS` in `elab_workbench/src/utils/Shared.jsx`.\n\n"
        markdown += "| Hex | Preview | Source |\n"
        markdown += "|-----|---------|--------|\n"

        for color_item in self.system_color_tokens:
            markdown += (
                f"| `{color_item['value']}` | {self._color_swatch(color_item['value'])} | {color_item['token']} |\n"
            )

        markdown += "\n\n## Highlight Hex Values In Source\n\n"
        markdown += "Hex values found in scanned source files, excluding colors from `COLOR_PALETTE` and `SYSTEM_COLORS`.\n\n"
        markdown += "| Hex | Preview | Usage Count | In COLOR_PALETTE | In SYSTEM_COLORS | Example Files |\n"
        markdown += "|-----|---------|-------------|------------------|------------------|---------------|\n"

        sorted_hex = sorted(
            non_palette_highlight_hex.items(),
            key=lambda item: (-item[1]["count"], item[0]),
        )
        for color, data in sorted_hex:
            in_palette = "Yes" if color in self.color_palette else "No"
            in_system = "Yes" if color in self.system_colors else "No"
            files = sorted(data["files"])
            example_files = ", ".join(files[:3])
            if len(files) > 3:
                example_files += f" (+{len(files) - 3} more)"
            markdown += (
                f"| `{color}` | {self._color_swatch(color)} | {data['count']} | "
                f"{in_palette} | {in_system} | {example_files} |\n"
            )

        # Add scanned directories
        markdown += "\n## Scanned Directories\n\n"
        markdown += "The following directories were scanned for class usage:\n\n"

        for source_path in self.source_paths:
            relative_path = source_path.relative_to(self.project_root)
            exists = "[ok]" if source_path.exists() else "[missing]"
            markdown += f"- `{relative_path}` {exists}\n"

        return markdown

    def save_markdown(self, output_path: Path) -> None:
        """Save markdown documentation to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        markdown = self.generate_markdown()
        output_path.write_text(markdown, encoding="utf-8")

        print("\nDocumentation generated successfully.")
        print(f"   Output: {output_path.relative_to(self.project_root)}")
        print(f"   Size: {output_path.stat().st_size} bytes")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate Tailwind CSS class documentation"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("doc/ui_reference.md"),
        help="Output path for markdown documentation (default: doc/ui_reference.md)",
    )

    args = parser.parse_args()

    # Find project root (where setup.cfg or GEMINI.md exists)
    project_root = Path(__file__).parent.parent

    if not project_root.exists():
        print("❌ Project root not found")
        sys.exit(1)

    generator = TailwindDocGenerator(project_root)
    generator.scan_sources()
    generator.extract_icons()
    generator.extract_public_logos()
    generator.extract_color_palette()
    generator.extract_system_colors()
    generator.scan_highlight_hex_values()

    print(f"Found {len(generator.found_classes)} unique classes")
    print(f"Found {len(generator.icons)} icons from Shared.jsx")
    print(f"Found {len(generator.color_palette)} palette colors")
    print(f"Found {len(generator.system_colors)} system colors")
    print(f"Found {len(generator.highlight_hex)} hex colors in source")

    # Determine output path
    output_path = args.output
    if not output_path.is_absolute():
        output_path = project_root / output_path

    generator.save_markdown(output_path)


if __name__ == "__main__":
    main()
