#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import stat
import sys

import integration_registry
import safe_paths


INTEGRATION_TEMPLATE_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RenderFile:
    source: Path
    target: Path
    content: bytes


@dataclass(frozen=True, slots=True)
class RenderPlan:
    output_root: Path
    directories: tuple[Path, ...]
    files: tuple[RenderFile, ...]
    force: bool


def rendered_target(src: Path, template_root: Path, output_root: Path) -> Path:
    rel = src.relative_to(template_root)
    if src.name.endswith(".template"):
        rel = rel.with_name(src.name[: -len(".template")])
    return output_root / rel


def path_within_root(path: Path, root: Path) -> bool:
    return safe_paths.path_within_root(path, root)


def output_path_errors(path: Path, root: Path) -> list[str]:
    return safe_paths.output_path_errors(path, root, "output root")


def template_source_errors(path: Path, template_root: Path) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        errors.append(f"refusing to render symlinked template path: {path}")
    if not path_within_root(path, template_root):
        errors.append(f"refusing to read template outside template root: {path}")
    return errors


def template_paths(template_root: Path) -> list[Path]:
    if template_root.is_symlink() or any(
        not safe_paths.is_allowed_system_symlink(component)
        for component in safe_paths.symlink_components(template_root)
    ):
        raise ValueError(f"refusing to render symlinked template root: {template_root}")
    if not template_root.is_dir():
        raise ValueError(f"integration template root must be a directory: {template_root}")
    paths = sorted(template_root.rglob("*"))
    errors = [
        error
        for path in paths
        for error in template_source_errors(path, template_root)
    ]
    if errors:
        raise ValueError("; ".join(errors))
    return paths


def _is_strict_ancestor(parent: Path, child: Path) -> bool:
    try:
        relative = child.relative_to(parent)
    except ValueError:
        return False
    return bool(relative.parts)


def _render_source_bytes(
    source: Path,
    framework_ref: str,
    contract_root_ref: str,
) -> bytes:
    raw = safe_paths.read_regular_file_bytes(
        source,
        description="integration template",
        max_bytes=INTEGRATION_TEMPLATE_MAX_BYTES,
    )
    if not source.name.endswith(".template"):
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"integration template must be UTF-8: {source}") from exc
    return integration_registry.render_template_text(
        text,
        framework_ref,
        contract_root_ref,
        template_label=str(source),
    ).encode("utf-8")


def _finalize_render_plan(
    output_root: Path,
    directories: list[Path],
    files: list[RenderFile],
    force: bool,
) -> RenderPlan:
    """Validate one complete file graph before any integration output is written."""

    directories = sorted(set(directories))
    targets = [item.target for item in files]
    target_errors = [
        error
        for target in [output_root, *directories, *targets]
        for error in output_path_errors(target, output_root)
    ]
    if target_errors:
        raise ValueError("; ".join(target_errors))

    sources_by_target: dict[Path, list[Path]] = {}
    for item in files:
        sources_by_target.setdefault(item.target, []).append(item.source)
    duplicate_targets = {
        target: sources
        for target, sources in sources_by_target.items()
        if len(sources) > 1
    }
    if duplicate_targets:
        details = "; ".join(
            f"{target} <- {', '.join(str(source) for source in sources)}"
            for target, sources in sorted(
                duplicate_targets.items(),
                key=lambda item: str(item[0]),
            )
        )
        raise ValueError(f"multiple integration sources render to one target: {details}")

    directory_set = set(directories)
    collisions = [target for target in targets if target in directory_set]
    if collisions:
        raise ValueError(
            "integration render target is both a file and directory: "
            + ", ".join(str(target) for target in sorted(collisions))
        )
    planned_paths = [*directories, *targets]
    ancestor_files = [
        target
        for target in targets
        if any(
            _is_strict_ancestor(target, other)
            for other in planned_paths
            if other != target
        )
    ]
    if ancestor_files:
        raise ValueError(
            "integration rendered file would contain another planned target: "
            + ", ".join(str(target) for target in sorted(set(ancestor_files)))
        )

    existing_kind_errors: list[str] = []
    for directory in [output_root, *directories]:
        if directory.exists() and not directory.is_dir():
            existing_kind_errors.append(
                f"planned integration directory is not a directory: {directory}"
            )
    for target in targets:
        if target.exists() and not target.is_file():
            existing_kind_errors.append(
                f"existing integration target is not a regular file: {target}"
            )
        parent = target.parent
        while True:
            if parent.exists() and not parent.is_dir():
                existing_kind_errors.append(
                    f"integration target parent is not a directory: {parent}"
                )
                break
            if parent == output_root:
                break
            try:
                parent.relative_to(output_root)
            except ValueError:
                break
            parent = parent.parent
    if existing_kind_errors:
        raise ValueError("; ".join(existing_kind_errors))
    if not force:
        existing = [target for target in targets if target.exists()]
        if existing:
            raise FileExistsError(
                "refusing to overwrite existing rendered file without --force: "
                + ", ".join(str(path) for path in existing)
            )
    return RenderPlan(
        output_root=output_root,
        directories=tuple(directories),
        files=tuple(files),
        force=force,
    )


def build_render_plan(
    template_root: Path,
    output_root: Path,
    framework_ref: str,
    force: bool,
    *,
    contract_root_ref: str = ".",
) -> RenderPlan:
    paths = template_paths(template_root)
    directories: list[Path] = []
    files: list[RenderFile] = []
    for source in paths:
        metadata = source.lstat()
        relative = source.relative_to(template_root)
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(output_root / relative)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"integration template entry must be a directory or regular file: {source}"
            )
        files.append(
            RenderFile(
                source=source,
                target=rendered_target(source, template_root, output_root),
                content=_render_source_bytes(
                    source,
                    framework_ref,
                    contract_root_ref,
                ),
            )
        )
    return _finalize_render_plan(output_root, directories, files, force)


def _registered_target_directories(
    output_root: Path,
    targets: list[Path],
) -> list[Path]:
    directories: set[Path] = set()
    for target in targets:
        parent = target.parent
        while parent != output_root:
            try:
                parent.relative_to(output_root)
            except ValueError:
                break
            directories.add(parent)
            parent = parent.parent
    return sorted(directories)


def build_registered_render_plan(
    family: str,
    repo_root: Path,
    output_root: Path,
    framework_ref: str,
    force: bool,
    *,
    contract_root_ref: str = ".",
) -> RenderPlan:
    """Render exactly the entrypoint and one file per registered wrapper."""

    config = integration_registry.family_config(family, repo_root)
    entrypoint_source = integration_registry.resolve_repo_path(
        repo_root,
        config["entrypoint"]["path"],
        f"{family}.entrypoint.path",
    )
    entrypoint_content = _render_source_bytes(
        entrypoint_source,
        framework_ref,
        contract_root_ref,
    )
    try:
        entrypoint_text = entrypoint_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{family} rendered entrypoint must be UTF-8"
        ) from exc
    entrypoint_output = config["entrypoint"]["output"]
    rendered_framework_ref, authority_errors = (
        integration_registry.entrypoint_authority_load_references(
            entrypoint_output,
            entrypoint_text,
            contract_root_ref=contract_root_ref,
            authority_load_syntax=config["entrypoint"]["authority_load_syntax"],
            repo_root=repo_root,
        )
    )
    if rendered_framework_ref is not None and rendered_framework_ref != framework_ref:
        authority_errors.append(
            f"{entrypoint_output} framework authority-load reference "
            f"{rendered_framework_ref!r} does not match the selected rendered "
            f"reference {framework_ref!r}"
        )
    if authority_errors:
        raise ValueError(
            f"{family} rendered entrypoint violates its registry-selected "
            "authority grammar: " + "; ".join(authority_errors)
        )
    files = [
        RenderFile(
            source=entrypoint_source,
            target=output_root / entrypoint_output,
            content=entrypoint_content,
        )
    ]
    wrapper_ids = integration_registry.wrapper_names(family, repo_root)
    wrapper_texts = integration_registry.render_wrapper_outputs(
        family,
        wrapper_ids,
        framework_ref,
        contract_root_ref,
        repo_root,
    )
    for wrapper_id in wrapper_ids:
        wrapper = config["wrappers"][wrapper_id]
        source = integration_registry.resolve_repo_path(
            repo_root,
            wrapper["path"],
            f"{family}.wrappers.{wrapper_id}.path",
        )
        output = wrapper["repo_output"]
        files.append(
            RenderFile(
                source=source,
                target=output_root / output,
                content=wrapper_texts[output].encode("utf-8"),
            )
        )
    targets = [item.target for item in files]
    return _finalize_render_plan(
        output_root,
        _registered_target_directories(output_root, targets),
        files,
        force,
    )


def install_render_plan(plan: RenderPlan) -> list[Path]:
    for directory in [plan.output_root, *plan.directories]:
        safe_paths.ensure_directory(directory, root=plan.output_root)
    for item in plan.files:
        safe_paths.write_bytes(
            item.target,
            item.content,
            force=plan.force,
            root=plan.output_root,
        )
    return [item.target for item in plan.files]


def render_templates(
    template_root: Path,
    output_root: Path,
    framework_ref: str,
    force: bool,
    *,
    contract_root_ref: str = ".",
) -> list[Path]:
    return install_render_plan(
        build_render_plan(
            template_root,
            output_root,
            framework_ref,
            force,
            contract_root_ref=contract_root_ref,
        )
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Render path-resolved runtime integration files from templates.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--integration",
        default="all",
        help="Which integration family to render, or 'all'.",
    )
    parser.add_argument(
        "--framework-root",
        default=str(repo_root),
        help="Framework repository root used to resolve templates and as the default framework reference.",
    )
    parser.add_argument(
        "--framework-ref",
        help=(
            "Framework reference resolved from the downstream project root. "
            "Nested Codex skills are rebased from their own directories. "
            "Defaults to --framework-root."
        ),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where rendered integration files will be written.",
    )
    parser.add_argument(
        "--contract-root",
        default=".",
        help=(
            "Contract directory relative to the downstream project root; nested "
            "Codex skill references are rebased from their own directories."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing rendered files.")
    args = parser.parse_args()

    framework_root = Path(args.framework_root).expanduser().resolve()
    raw_framework_ref = args.framework_ref if args.framework_ref is not None else str(framework_root)
    try:
        framework_ref = safe_paths.canonical_framework_reference(raw_framework_ref)
    except ValueError as exc:
        parser.error(str(exc))
    if args.contract_root == ".":
        contract_root_ref = "."
    else:
        try:
            contract_root_ref = integration_registry.validate_relative_path(
                args.contract_root,
                "contract root",
            )
        except ValueError as exc:
            parser.error(str(exc))
        contract_root_errors = safe_paths.project_relative_reference_errors(
            contract_root_ref,
            "contract root",
        )
        if contract_root_errors:
            parser.error("; ".join(contract_root_errors))
    raw_output_root = Path(args.output_dir).expanduser()
    safe_paths.require_output_path(raw_output_root)
    output_root = raw_output_root.absolute()
    available_integrations = integration_registry.family_names(framework_root)
    if args.integration != "all" and args.integration not in available_integrations:
        parser.error(
            f"--integration must be one of: {', '.join([*available_integrations, 'all'])}"
        )
    if args.framework_ref is None and safe_paths.starts_with_host_identity_path(framework_ref):
        print(
            "warning: rendered framework reference is host-specific; use --framework-ref for shared or public output",
            file=sys.stderr,
        )

    integrations = [args.integration] if args.integration != "all" else available_integrations

    plans: list[RenderPlan] = []
    for integration in integrations:
        plans.append(
            build_registered_render_plan(
                integration,
                framework_root,
                output_root / integration,
                framework_ref,
                args.force,
                contract_root_ref=contract_root_ref,
            )
        )

    written = [
        path
        for plan in plans
        for path in install_render_plan(plan)
    ]

    print(f"Rendered {len(written)} files into {output_root}")
    for path in written:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
