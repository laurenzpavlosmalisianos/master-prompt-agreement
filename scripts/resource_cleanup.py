#!/usr/bin/env python3

"""Failure-preserving cleanup aggregation for import-only support modules."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import os


__all__ = ("OwnedFileDescriptors", "cleanup_actions")


def cleanup_actions(
    actions: Sequence[tuple[str, Callable[[], object]]],
    *,
    primary: BaseException | None = None,
) -> None:
    """Attempt every named action without masking an active failure."""

    failures: list[tuple[str, BaseException]] = []
    for description, action in actions:
        try:
            action()
        except BaseException as cleanup:
            failures.append((description, cleanup))
    if primary is not None:
        for description, cleanup in failures:
            primary.add_note(f"{description} cleanup failure: {cleanup}")
        return
    if failures:
        description, first = failures[0]
        first.add_note(f"cleanup failed for {description}")
        for secondary_description, secondary in failures[1:]:
            first.add_note(
                f"additional {secondary_description} cleanup failure: {secondary}"
            )
        raise first


class OwnedFileDescriptors:
    """Record descriptor ownership before any fallible predecessor cleanup.

    A descriptor is relinquished immediately before its own close attempt.
    POSIX close-failure state can be ambiguous, so cleanup never retries that
    descriptor and risk closing a number already reused elsewhere.  A newly
    acquired child is registered first and therefore remains available for a
    separate cleanup attempt if predecessor cleanup fails.
    """

    def __init__(self) -> None:
        self._owned: list[tuple[int, str]] = []

    def adopt(self, descriptor: int, description: str) -> int:
        if descriptor < 0:
            raise ValueError("owned file descriptor must be non-negative")
        if any(owned == descriptor for owned, _description in self._owned):
            raise ValueError(f"file descriptor {descriptor} is already owned")
        self._owned.append((descriptor, description))
        return descriptor

    def close(self, descriptor: int) -> None:
        for index, (owned, _description) in enumerate(self._owned):
            if owned != descriptor:
                continue
            del self._owned[index]
            os.close(descriptor)
            return
        raise ValueError(f"file descriptor {descriptor} is not owned")

    def release(self, descriptor: int) -> int:
        for index, (owned, _description) in enumerate(self._owned):
            if owned != descriptor:
                continue
            del self._owned[index]
            return descriptor
        raise ValueError(f"file descriptor {descriptor} is not owned")

    def cleanup(self, *, primary: BaseException | None = None) -> None:
        owned = tuple(reversed(self._owned))
        self._owned.clear()
        cleanup_actions(
            [
                (
                    description,
                    lambda descriptor=descriptor: os.close(descriptor),
                )
                for descriptor, description in owned
            ],
            primary=primary,
        )
