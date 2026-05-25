"""Generate doc/python_api_reference.md from Python source files.

Scans selected modules, extracts classes/functions/signatures via AST,
and writes a concise API reference markdown document.
"""
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ParamInfo:
    name: str
    type_hint: str
    default: str
    description: str


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    signature: str
    summary: str
    parameters: list[ParamInfo]


@dataclass(frozen=True)
class ClassInfo:
    name: str
    signature: str
    summary: str
    methods: list[FunctionInfo]


@dataclass(frozen=True)
class ModuleInfo:
    module_path: str
    summary: str
    classes: list[ClassInfo]
    functions: list[FunctionInfo]


def _doc_summary(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    summary = doc.strip().splitlines()[0] if doc.strip() else "No documentation."
    return re.sub(r"\*(.+?)\*", r"_\1_", summary)


def _normalize_doc_text(text: str) -> str:
    return re.sub(r"\*(.+?)\*", r"_\1_", text).strip()


def _format_arg(arg: ast.arg, default: ast.expr | None, is_kw_only: bool = False) -> str:
    text = arg.arg
    if arg.annotation:
        text += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        text += f" = {ast.unparse(default)}"
    elif is_kw_only:
        text += ""
    return text


def _signature_from_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []

    positional = list(args.posonlyargs) + list(args.args)
    pos_defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)

    for arg, default in zip(positional, pos_defaults, strict=True):
        parts.append(_format_arg(arg, default))

    if args.vararg:
        vararg_text = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            vararg_text += f": {ast.unparse(args.vararg.annotation)}"
        parts.append(vararg_text)
    elif args.kwonlyargs:
        parts.append("*")

    for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parts.append(_format_arg(kw_arg, kw_default, is_kw_only=True))

    if args.kwarg:
        kwarg_text = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            kwarg_text += f": {ast.unparse(args.kwarg.annotation)}"
        parts.append(kwarg_text)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    return f"({', '.join(parts)}){returns}"


def _parse_numpy_doc_params(doc: str) -> dict[str, str]:
    lines = doc.splitlines()
    i = 0
    in_section = False
    result: dict[str, str] = {}

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if stripped == "Parameters":
            in_section = True
            i += 1
            while i < len(lines) and set(lines[i].strip()) == {"-"}:
                i += 1
            continue

        if in_section:
            if stripped and not line.startswith(" ") and ":" not in stripped:
                break
            if ":" in stripped and not line.startswith(" "):
                name = stripped.split(":", 1)[0].strip()
                i += 1
                desc_parts: list[str] = []
                while i < len(lines):
                    nxt = lines[i]
                    nxt_stripped = nxt.strip()
                    if not nxt_stripped:
                        i += 1
                        if desc_parts:
                            break
                        continue
                    if ":" in nxt_stripped and not nxt.startswith(" "):
                        break
                    if nxt.startswith(" "):
                        desc_parts.append(nxt_stripped)
                        i += 1
                        continue
                    break

                result[name] = _normalize_doc_text(" ".join(desc_parts)) or "-"
                continue
        i += 1

    return result


def _augment_param_description(param_name: str, description: str) -> str:
    extras: list[str] = []
    if param_name == "template":
        extras.append("See [template_reference.md](template_reference.md).")
    if param_name == "config":
        extras.append("Schema details in [schema_reference.md](schema_reference.md).")
    if param_name == "action":
        extras.append("Command/event details in [api.md](api.md#execute_command).")

    if not extras:
        return description
    if description == "-":
        return " ".join(extras)
    return f"{description} {' '.join(extras)}"


def _collect_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ParamInfo]:
    args = node.args
    params: list[ParamInfo] = []
    doc = ast.get_docstring(node) or ""
    doc_params = _parse_numpy_doc_params(doc)

    positional = list(args.posonlyargs) + list(args.args)
    pos_defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)

    for arg, default in zip(positional, pos_defaults, strict=True):
        if arg.arg in {"self", "cls"}:
            continue
        type_hint = ast.unparse(arg.annotation) if arg.annotation else "Any"
        default_text = ast.unparse(default) if default is not None else "-"
        params.append(
            ParamInfo(
                name=arg.arg,
                type_hint=type_hint,
                default=default_text,
                description=_augment_param_description(arg.arg, doc_params.get(arg.arg, "-")),
            )
        )

    if args.vararg:
        params.append(
            ParamInfo(
                name=f"*{args.vararg.arg}",
                type_hint=ast.unparse(args.vararg.annotation) if args.vararg.annotation else "Any",
                default="-",
                description=_augment_param_description(args.vararg.arg, doc_params.get(args.vararg.arg, "-")),
            )
        )

    for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        type_hint = ast.unparse(kw_arg.annotation) if kw_arg.annotation else "Any"
        default_text = ast.unparse(kw_default) if kw_default is not None else "-"
        params.append(
            ParamInfo(
                name=kw_arg.arg,
                type_hint=type_hint,
                default=default_text,
                description=_augment_param_description(kw_arg.arg, doc_params.get(kw_arg.arg, "-")),
            )
        )

    if args.kwarg:
        params.append(
            ParamInfo(
                name=f"**{args.kwarg.arg}",
                type_hint=ast.unparse(args.kwarg.annotation) if args.kwarg.annotation else "Any",
                default="-",
                description=_augment_param_description(args.kwarg.arg, doc_params.get(args.kwarg.arg, "-")),
            )
        )

    return params


def _escape_md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip() or "-"


def _add_parameters_table(lines: list[str], parameters: list[ParamInfo]) -> None:
    if not parameters:
        lines.append("Parameters: none")
        lines.append("")
        return

    lines.extend(
        [
            "Parameters:",
            "",
            "|Parameter|Type|Default|Description|",
            "|---|---|---|---|",
        ]
    )
    for param in parameters:
        lines.append(
            "|"
            f"{_escape_md_cell(param.name)}|"
            f"{_escape_md_cell(param.type_hint)}|"
            f"{_escape_md_cell(param.default)}|"
            f"{_escape_md_cell(param.description)}|"
        )
    lines.append("")


def _extract_module_info(file_path: Path, repo_root: Path) -> ModuleInfo:
    module_path = file_path.relative_to(repo_root).as_posix()
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    classes: list[ClassInfo] = []
    functions: list[FunctionInfo] = []

    module_summary = _doc_summary(tree)

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            class_methods: list[FunctionInfo] = []
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                    class_methods.append(
                        FunctionInfo(
                            name=child.name,
                            signature=_signature_from_function(child),
                            summary=_doc_summary(child),
                            parameters=_collect_parameters(child),
                        )
                    )
            classes.append(
                ClassInfo(
                    name=node.name,
                    signature="",
                    summary=_doc_summary(node),
                    methods=class_methods,
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions.append(
                FunctionInfo(
                    name=node.name,
                    signature=_signature_from_function(node),
                    summary=_doc_summary(node),
                    parameters=_collect_parameters(node),
                )
            )

    return ModuleInfo(
        module_path=module_path,
        summary=module_summary,
        classes=classes,
        functions=functions,
    )


def _render_markdown(modules: Iterable[ModuleInfo]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = [
        "# Python API Reference",
        "",
        "_Auto-generated file. Do not edit manually._",
        "",
        f"Generated: {generated}",
        "",
    ]

    for module in modules:
        lines.extend(
            [
                f"## {module.module_path}",
                "",
                module.summary,
                "",
            ]
        )

        if module.classes:
            lines.append(f"### Classes in {module.module_path}")
            lines.append("")
            for cls in module.classes:
                lines.append(f"#### {cls.name}")
                lines.append("")
                lines.append(cls.summary)
                lines.append("")
                if cls.methods:
                    lines.append("Methods:")
                    lines.append("")
                    for method in cls.methods:
                        lines.append(f"- `{method.name}{method.signature}`")
                        lines.append(f"  - {method.summary}")
                        _add_parameters_table(lines, method.parameters)

        if module.functions:
            lines.append(f"### Functions in {module.module_path}")
            lines.append("")
            for func in module.functions:
                lines.append(f"- `{func.name}{func.signature}`")
                lines.append(f"  - {func.summary}")
                _add_parameters_table(lines, func.parameters)

    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = is_blank

    return "\n".join(normalized).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Python API reference markdown")
    parser.add_argument(
        "--output",
        default="doc/python_api_reference.md",
        help="Output markdown path (default: doc/python_api_reference.md)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_path = (repo_root / args.output).resolve()

    source_files = [
        repo_root / "elab_api" / "__init__.py",
        repo_root / "elab_api" / "local_node.py",
        repo_root / "elab_api" / "shared_memory_channel.py",
        repo_root / "elab_bridge" / "bridge_daemon.py",
    ]

    modules = [_extract_module_info(path, repo_root) for path in source_files if path.exists()]
    markdown = _render_markdown(modules)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
