#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import safe_paths


@dataclass(frozen=True)
class MarkdownSnapshot:
    """One immutable, bounded UTF-8 registry-file snapshot."""

    path: Path
    text: str


def normalize_reference_dirs(reference_dirs: Path | tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    if isinstance(reference_dirs, Path):
        return (reference_dirs,)
    return tuple(reference_dirs)


def _relative_label(root: Path, path: Path, *, description: str) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{description} must stay under repository root: {path}") from exc


def read_markdown_snapshot(
    root: Path,
    path: Path,
    *,
    description: str,
    missing_ok: bool = False,
) -> MarkdownSnapshot | None:
    """Read one registry input once through the shared descriptor-safe reader."""

    rel = _relative_label(root, path, description=description)
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=description,
        )
    except FileNotFoundError as exc:
        if missing_ok:
            return None
        raise ValueError(f"{description} disappeared during inventory: {rel}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description} must be valid UTF-8: {rel}: {exc}") from exc
    return MarkdownSnapshot(path=path, text=text)


def reference_directory_markdown_snapshots(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
) -> tuple[MarkdownSnapshot, ...]:
    candidates: set[Path] = set()
    for reference_dir in normalize_reference_dirs(reference_dirs):
        directory = safe_paths.safe_relative_child(
            root,
            reference_dir,
            description="reference directory",
        )
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise ValueError(f"reference directory is not a directory: {reference_dir}")
        candidates.update(
            candidate
            for candidate in directory.rglob("*.md")
            if candidate.name != "README.md"
        )

    snapshots: list[MarkdownSnapshot] = []
    for candidate in sorted(candidates):
        snapshot = read_markdown_snapshot(
            root,
            candidate,
            description="reference file",
        )
        if snapshot is None:  # pragma: no cover - missing_ok is false above
            raise RuntimeError("required reference snapshot unexpectedly missing")
        snapshots.append(snapshot)
    return tuple(snapshots)


def project_registry_markdown_snapshots(
    root: Path,
    files: tuple[Path, ...],
) -> tuple[MarkdownSnapshot, ...]:
    snapshots: list[MarkdownSnapshot] = []
    for rel in files:
        candidate = safe_paths.safe_relative_child(
            root,
            rel,
            description="project source registry file",
        )
        snapshot = read_markdown_snapshot(
            root,
            candidate,
            description="project source registry file",
            missing_ok=True,
        )
        if snapshot is not None:
            snapshots.append(snapshot)
    return tuple(sorted(snapshots, key=lambda item: item.path))


def registry_markdown_snapshots(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    project_files: tuple[Path, ...] = (),
) -> tuple[MarkdownSnapshot, ...]:
    by_path = {
        snapshot.path: snapshot
        for snapshot in (
            *reference_directory_markdown_snapshots(root, reference_dirs),
            *project_registry_markdown_snapshots(root, project_files),
        )
    }
    return tuple(by_path[path] for path in sorted(by_path))


def project_registry_markdown_files(root: Path, files: tuple[Path, ...]) -> list[Path]:
    return [snapshot.path for snapshot in project_registry_markdown_snapshots(root, files)]


def registry_markdown_files(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    project_files: tuple[Path, ...] = (),
) -> list[Path]:
    return [
        snapshot.path
        for snapshot in registry_markdown_snapshots(root, reference_dirs, project_files)
    ]
