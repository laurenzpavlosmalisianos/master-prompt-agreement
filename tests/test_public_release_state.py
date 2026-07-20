"""Adversarial tests for the durable public-release phase ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX discovery only
    fcntl = None  # type: ignore[assignment]

from tests.validation_test_support import REPO_ROOT  # noqa: F401

import public_release_state


_OPERATION_ID = "release-20260720-test"
_CONTROLLER_SHA256 = "c" * 64
_EXPECTED_PARENT = "a" * 40
_CANDIDATE_COMMIT = "b" * 40
_REQUEST = {
    "branch": "master",
    "operation_root": str(Path(tempfile.gettempdir()) / "release-test"),
    "remote_name": "origin",
}
_STAGED_RECEIPT = {"phase": "staged", "receipt": "evidence"}
_COMMITTED_RECEIPT = {"phase": "committed", "receipt": "evidence"}


def _sha(character: str) -> str:
    return character * 64


def _payload(phase: str) -> dict[str, object]:
    if phase == "export-verified":
        return {
            "export_marker_sha256": _sha("1"),
            "git_sha256": _sha("2"),
            "python_sha256": _sha("3"),
            "uv_sha256": _sha("4"),
        }
    if phase == "staged-verified":
        return {
            "expected_parent": _EXPECTED_PARENT,
            "staged_receipt": dict(_STAGED_RECEIPT),
            "commit_spec_sha256": _sha("5"),
        }
    if phase == "candidate-verified":
        return {
            "candidate_commit": _CANDIDATE_COMMIT,
            "committed_receipt": dict(_COMMITTED_RECEIPT),
            "staged_receipt_sha256": public_release_state.canonical_json_sha256(
                _STAGED_RECEIPT
            ),
        }
    if phase == "publication-bound":
        return {
            "candidate_commit": _CANDIDATE_COMMIT,
            "expected_parent": _EXPECTED_PARENT,
            "refspec_sha256": _sha("6"),
            "credential_boundary_sha256": _sha("7"),
            "mode": "controller-push",
        }
    if phase in {"push-observed", "readback-verified"}:
        return {"candidate_commit": _CANDIDATE_COMMIT}
    raise AssertionError(f"unsupported phase fixture: {phase}")


@unittest.skipUnless(fcntl is not None, "release state requires POSIX file locking")
class PublicReleaseStateTests(unittest.TestCase):
    def _initialize(
        self, parent: Path
    ) -> tuple[Path, public_release_state.ReleaseStateSnapshot]:
        state = parent / "state"
        snapshot = public_release_state.init_state(
            state,
            operation_id=_OPERATION_ID,
            request=dict(_REQUEST),
            controller_sha256=_CONTROLLER_SHA256,
        )
        return state, snapshot

    def _append(
        self,
        state: Path,
        snapshot: public_release_state.ReleaseStateSnapshot,
        phase: str,
        payload: dict[str, object] | None = None,
    ) -> public_release_state.ReleaseStateSnapshot:
        return public_release_state.append_event(
            state,
            operation_id=_OPERATION_ID,
            request_sha256=snapshot.request_sha256,
            phase=phase,
            payload=_payload(phase) if payload is None else payload,
        )

    def _rewrite_event(self, path: Path, value: object) -> None:
        raw = (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        path.chmod(0o600)

    def test_initialize_is_canonical_owner_only_and_self_describing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))

            self.assertEqual(snapshot.operation_id, _OPERATION_ID)
            self.assertEqual(snapshot.phase, "initialized")
            self.assertEqual(snapshot.sequence, 1)
            self.assertEqual(snapshot.request, _REQUEST)
            self.assertEqual(snapshot.controller_sha256, _CONTROLLER_SHA256)
            self.assertEqual(
                snapshot.request_sha256,
                public_release_state.canonical_json_sha256(_REQUEST),
            )
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((state / ".lock").stat().st_mode), 0o600)
            self.assertEqual((state / ".lock").stat().st_nlink, 1)
            self.assertEqual((state / ".lock").read_bytes(), b"")
            self.assertEqual(
                stat.S_IMODE((state / ".operation.lock").stat().st_mode),
                0o600,
            )
            self.assertEqual((state / ".operation.lock").stat().st_nlink, 1)
            self.assertEqual((state / ".operation.lock").read_bytes(), b"")
            event = state / "00000001.json"
            self.assertEqual(stat.S_IMODE(event.stat().st_mode), 0o600)
            self.assertEqual(event.stat().st_nlink, 1)
            self.assertEqual(event.read_bytes()[-1:], b"\n")
            self.assertNotIn(b" ", event.read_bytes())

            discovered = public_release_state.inspect_state(state)
            self.assertEqual(discovered, snapshot)
            bound = public_release_state.inspect_state(
                state,
                operation_id=_OPERATION_ID,
                request_sha256=snapshot.request_sha256,
            )
            self.assertEqual(bound, snapshot)

    def test_complete_linear_ledger_has_monotonic_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            for phase in public_release_state.PHASES[1:]:
                snapshot = self._append(state, snapshot, phase)

            self.assertEqual(snapshot.phase, "readback-verified")
            self.assertEqual(snapshot.sequence, len(public_release_state.PHASES))
            for previous, current in zip(snapshot.events, snapshot.events[1:]):
                self.assertEqual(current.sequence, previous.sequence + 1)
                self.assertEqual(current.previous_event_sha256, previous.sha256)
            self.assertEqual(
                sorted(path.name for path in state.iterdir()),
                [
                    ".lock",
                    ".operation.lock",
                    *(f"{index:08d}.json" for index in range(1, 8)),
                ],
            )
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "already complete"
            ):
                self._append(state, snapshot, "readback-verified")

    def test_phase_order_and_closed_payload_schema_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "next release phase must equal 'export-verified'",
            ):
                self._append(state, snapshot, "staged-verified")

            payload = _payload("export-verified")
            payload["unknown"] = _sha("8")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "unknown fields: unknown"
            ):
                self._append(state, snapshot, "export-verified", payload)
            self.assertEqual(public_release_state.inspect_state(state).sequence, 1)

    def test_cross_phase_receipt_commit_and_parent_bindings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            snapshot = self._append(state, snapshot, "export-verified")
            snapshot = self._append(state, snapshot, "staged-verified")

            wrong_receipt = _payload("candidate-verified")
            wrong_receipt["staged_receipt_sha256"] = _sha("9")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "does not bind the staged receipt",
            ):
                self._append(state, snapshot, "candidate-verified", wrong_receipt)

            snapshot = self._append(state, snapshot, "candidate-verified")
            wrong_commit = _payload("publication-bound")
            wrong_commit["candidate_commit"] = "d" * 40
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "candidate does not match",
            ):
                self._append(state, snapshot, "publication-bound", wrong_commit)

            wrong_parent = _payload("publication-bound")
            wrong_parent["expected_parent"] = "e" * 40
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "parent does not match",
            ):
                self._append(state, snapshot, "publication-bound", wrong_parent)

            wrong_adoption = _payload("publication-bound")
            wrong_adoption["mode"] = "adopt-observed-candidate"
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "no-credential sentinel",
            ):
                self._append(
                    state,
                    snapshot,
                    "publication-bound",
                    wrong_adoption,
                )

            wrong_controller_push = _payload("publication-bound")
            wrong_controller_push["credential_boundary_sha256"] = (
                public_release_state.NO_CREDENTIAL_BOUNDARY_SHA256
            )
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "requires a credential digest",
            ):
                self._append(
                    state,
                    snapshot,
                    "publication-bound",
                    wrong_controller_push,
                )

    def test_wrong_external_bindings_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "operation ID"
            ):
                public_release_state.inspect_state(
                    state,
                    operation_id="different-operation",
                )
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "request digest"
            ):
                public_release_state.inspect_state(
                    state,
                    request_sha256=_sha("f"),
                )
            self.assertEqual(public_release_state.inspect_state(state), snapshot)

    def test_orphan_incomplete_next_is_recovered_after_intact_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            next_path = state / ".next"
            next_path.write_bytes(b'{"incomplete":')
            next_path.chmod(0o600)

            recovered = public_release_state.inspect_state(state)

            self.assertEqual(recovered, snapshot)
            self.assertFalse(next_path.exists())
            self.assertEqual((state / "00000001.json").stat().st_nlink, 1)

    def test_final_and_next_same_inode_recover_to_final_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            event = state / "00000001.json"
            os.link(event, state / ".next")
            self.assertEqual(event.stat().st_nlink, 2)

            recovered = public_release_state.inspect_state(state)

            self.assertEqual(recovered, snapshot)
            self.assertFalse((state / ".next").exists())
            self.assertEqual(event.stat().st_nlink, 1)

    def test_interrupted_prelink_append_discards_only_next_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            with mock.patch.object(
                public_release_state.os,
                "link",
                side_effect=OSError("injected pre-link interruption"),
            ):
                with self.assertRaisesRegex(
                    public_release_state.ReleaseStateError, "append failed"
                ):
                    self._append(state, snapshot, "export-verified")
            self.assertTrue((state / ".next").exists())

            recovered = public_release_state.inspect_state(state)

            self.assertEqual(recovered.phase, "initialized")
            self.assertFalse((state / ".next").exists())

    def test_interrupted_postlink_append_recovers_committed_final(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            real_unlink = os.unlink

            def interrupt_next(name: str, *, dir_fd: int | None = None) -> None:
                if name == ".next":
                    raise OSError("injected post-link interruption")
                real_unlink(name, dir_fd=dir_fd)

            with mock.patch.object(
                public_release_state.os,
                "unlink",
                side_effect=interrupt_next,
            ):
                with self.assertRaisesRegex(
                    public_release_state.ReleaseStateError, "append failed"
                ):
                    self._append(state, snapshot, "export-verified")
            self.assertEqual((state / "00000002.json").stat().st_nlink, 2)
            self.assertTrue((state / ".next").exists())

            recovered = public_release_state.inspect_state(state)

            self.assertEqual(recovered.phase, "export-verified")
            self.assertFalse((state / ".next").exists())
            self.assertEqual((state / "00000002.json").stat().st_nlink, 1)

    def test_unknown_files_gaps_and_forks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            unknown = state / ".DS_Store"
            unknown.write_bytes(b"noise")
            unknown.chmod(0o600)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "unknown entries"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            snapshot = self._append(state, snapshot, "export-verified")
            (state / "00000002.json").rename(state / "00000003.json")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "gap or non-monotonic"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            os.link(state / "00000001.json", state / "00000001.fork")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "unknown entries"
            ):
                public_release_state.inspect_state(state)

    def test_symlinks_and_unexpected_hardlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, _snapshot = self._initialize(root)
            event = state / "00000001.json"
            os.link(event, root / "outside-event-link")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "link count"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, _snapshot = self._initialize(root)
            lock = state / ".lock"
            lock.rename(root / "real-lock")
            lock.symlink_to(root / "real-lock")
            with self.assertRaises(public_release_state.ReleaseStateError):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, _snapshot = self._initialize(root)
            outside = root / "outside"
            outside.write_bytes(b"foreign")
            outside.chmod(0o600)
            os.link(outside, state / ".next")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "invalid hard-link relationship|does not identify",
            ):
                public_release_state.inspect_state(state)

    def test_active_lock_fails_immediately_instead_of_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            descriptor = os.open(state / ".lock", os.O_RDWR)
            lock_module = fcntl
            assert lock_module is not None
            try:
                lock_module.flock(
                    descriptor,
                    lock_module.LOCK_EX | lock_module.LOCK_NB,
                )
                with self.assertRaisesRegex(
                    public_release_state.ReleaseStateError,
                    "currently owns",
                ):
                    public_release_state.inspect_state(state)
            finally:
                lock_module.flock(descriptor, lock_module.LOCK_UN)
                os.close(descriptor)

    def test_active_operation_lease_fails_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            with public_release_state.operation_lease(state):
                with self.assertRaisesRegex(
                    public_release_state.ReleaseStateError,
                    "operation lease",
                ):
                    with public_release_state.operation_lease(state):
                        self.fail("a second operation lease must not be acquired")

    def test_operation_lock_identity_mode_links_and_content_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            (state / ".operation.lock").chmod(0o644)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "mode must equal",
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            (state / ".operation.lock").write_bytes(b"unexpected")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "must remain empty",
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, _snapshot = self._initialize(root)
            os.link(state / ".operation.lock", root / "outside-operation-lock")
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "link count",
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, _snapshot = self._initialize(root)
            lock = state / ".operation.lock"
            lock.rename(root / "real-operation-lock")
            lock.symlink_to(root / "real-operation-lock")
            with self.assertRaises(public_release_state.ReleaseStateError):
                public_release_state.inspect_state(state)

    def test_modes_noncanonical_json_duplicates_and_chain_tampering_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            state.chmod(0o755)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "mode must equal 0o700"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            event = state / "00000001.json"
            value = json.loads(event.read_text(encoding="utf-8"))
            event.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            event.chmod(0o600)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "not encoded as canonical"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            event = state / "00000001.json"
            raw = event.read_text(encoding="utf-8")
            event.write_text(
                raw.replace(
                    '{"operation_id":',
                    '{"operation_id":"x","operation_id":',
                    1,
                ),
                encoding="utf-8",
            )
            event.chmod(0o600)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "duplicate key"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, snapshot = self._initialize(Path(temporary))
            snapshot = self._append(state, snapshot, "export-verified")
            initial = state / "00000001.json"
            value = json.loads(initial.read_text(encoding="utf-8"))
            value["payload"]["controller_sha256"] = _sha("d")
            self._rewrite_event(initial, value)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "ledger continuity"
            ):
                public_release_state.inspect_state(state)

    def test_unknown_event_fields_and_invalid_initialized_request_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            event = state / "00000001.json"
            value = json.loads(event.read_text(encoding="utf-8"))
            value["unknown"] = True
            self._rewrite_event(event, value)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError, "unknown fields: unknown"
            ):
                public_release_state.inspect_state(state)

        with tempfile.TemporaryDirectory() as temporary:
            state, _snapshot = self._initialize(Path(temporary))
            event = state / "00000001.json"
            value = json.loads(event.read_text(encoding="utf-8"))
            value["payload"]["request"]["branch"] = "other"
            self._rewrite_event(event, value)
            with self.assertRaisesRegex(
                public_release_state.ReleaseStateError,
                "request does not match request_sha256",
            ):
                public_release_state.inspect_state(state)


if __name__ == "__main__":
    unittest.main()
