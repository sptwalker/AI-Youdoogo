#!/usr/bin/env python3
"""Build and inspect the runtime Python import graph for one package tree."""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModuleSource:
    """Canonical module metadata discovered below a package root."""

    name: str
    path: Path
    is_package: bool


@dataclass(frozen=True)
class ImportGraph:
    """Directed runtime imports between modules in one package tree."""

    modules: Mapping[str, ModuleSource]
    edges: Mapping[str, frozenset[str]]

    def strongly_connected_components(self) -> tuple[frozenset[str], ...]:
        """Return every strongly connected component in stable order."""
        index = 0
        indexes: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[frozenset[str]] = []

        def visit(module: str) -> None:
            nonlocal index
            indexes[module] = index
            lowlinks[module] = index
            index += 1
            stack.append(module)
            on_stack.add(module)

            for dependency in sorted(self.edges[module]):
                if dependency not in indexes:
                    visit(dependency)
                    lowlinks[module] = min(lowlinks[module], lowlinks[dependency])
                elif dependency in on_stack:
                    lowlinks[module] = min(lowlinks[module], indexes[dependency])

            if lowlinks[module] != indexes[module]:
                return

            component: set[str] = set()
            while stack:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == module:
                    break
            components.append(frozenset(component))

        for module in sorted(self.modules):
            if module not in indexes:
                visit(module)

        return tuple(sorted(components, key=lambda item: tuple(sorted(item))))

    def cycles(self) -> tuple[frozenset[str], ...]:
        """Return the non-trivial strongly connected components."""
        cyclic = [
            component
            for component in self.strongly_connected_components()
            if len(component) > 1
            or any(module in self.edges[module] for module in component)
        ]
        return tuple(sorted(cyclic, key=lambda item: tuple(sorted(item))))


class _RuntimeImportVisitor(ast.NodeVisitor):
    """Collect imports that execute at runtime, including imports in functions."""

    def __init__(self) -> None:
        self.nodes: list[ast.Import | ast.ImportFrom] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        self.nodes.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.nodes.append(node)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        if _is_type_checking_guard(node.test):
            for statement in node.orelse:
                self.visit(statement)
            return
        self.generic_visit(node)


def _is_type_checking_guard(expression: ast.expr) -> bool:
    if isinstance(expression, ast.Name):
        return expression.id == "TYPE_CHECKING"
    return (
        isinstance(expression, ast.Attribute)
        and expression.attr == "TYPE_CHECKING"
        and isinstance(expression.value, ast.Name)
        and expression.value.id in {"typing", "t"}
    )


def discover_modules(package_root: Path) -> dict[str, ModuleSource]:
    """Discover canonical modules below ``package_root``."""
    package_root = package_root.resolve()
    source_root = package_root.parent
    modules: dict[str, ModuleSource] = {}
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(source_root).with_suffix("")
        is_package = relative.name == "__init__"
        parts = relative.parent.parts if is_package else relative.parts
        name = ".".join(parts)
        modules[name] = ModuleSource(name=name, path=path, is_package=is_package)
    return modules


def _runtime_import_nodes(path: Path) -> tuple[ast.Import | ast.ImportFrom, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _RuntimeImportVisitor()
    visitor.visit(tree)
    return tuple(visitor.nodes)


def runtime_import_names(path: Path) -> set[str]:
    """Return raw absolute runtime imports for framework-boundary checks."""
    imported: set[str] = set()
    for node in _runtime_import_nodes(path):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif node.level == 0 and node.module:
            imported.add(node.module)
    return imported


def _absolute_from_module(node: ast.ImportFrom, source: ModuleSource) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = source.name.split(".") if source.is_package else source.name.split(".")[:-1]
    ascend = node.level - 1
    if ascend > len(package_parts):
        return ""
    base_parts = package_parts[: len(package_parts) - ascend]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def _longest_known_prefix(name: str, known: set[str]) -> str | None:
    parts = name.split(".")
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        if candidate in known:
            return candidate
    return None


def _resolved_targets(
    node: ast.Import | ast.ImportFrom,
    source: ModuleSource,
    known: set[str],
) -> set[str]:
    if isinstance(node, ast.Import):
        candidates = {alias.name for alias in node.names}
    else:
        base = _absolute_from_module(node, source)
        candidates = {base} if base else set()
        candidates.update(
            f"{base}.{alias.name}"
            for alias in node.names
            if base and alias.name != "*"
        )

    targets: set[str] = set()
    for candidate in candidates:
        target = _longest_known_prefix(candidate, known)
        if target is None:
            continue
        targets.add(target)
    targets.discard(source.name)
    return targets


def build_import_graph(package_root: Path) -> ImportGraph:
    """Build the internal runtime import graph for ``package_root``."""
    modules = discover_modules(package_root)
    known = set(modules)
    edges: dict[str, frozenset[str]] = {}
    for module in modules.values():
        dependencies: set[str] = set()
        for node in _runtime_import_nodes(module.path):
            dependencies.update(_resolved_targets(node, module, known))
        edges[module.name] = frozenset(dependencies)
    return ImportGraph(modules=modules, edges=edges)


def format_cycles(cycles: Iterable[frozenset[str]]) -> str:
    """Format cycle diagnostics with every participating module."""
    groups = [", ".join(sorted(component)) for component in cycles]
    return "\n".join(f"SCC {index}: {group}" for index, group in enumerate(groups, 1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="?", type=Path, default=Path("app"))
    args = parser.parse_args()

    graph = build_import_graph(args.package)
    cycles = graph.cycles()
    if not cycles:
        print(f"{len(graph.modules)} modules: acyclic")
        return 0
    print(format_cycles(cycles))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
