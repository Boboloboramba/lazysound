"""Batch editing operations for audio metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lazysound.core.metadata import AudioMetadata, read_metadata, write_metadata
from lazysound.core.scanner import AudioFile


@dataclass
class BatchOperation:
    """A single tag operation to apply."""

    field: str
    value: str
    mode: str = "set"  # set, append, prepend, clear, find_replace

    # For find_replace mode
    find: str = ""
    replace: str = ""


@dataclass
class BatchResult:
    """Result of applying batch operations."""

    total_files: int = 0
    success_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)  # (filename, error)

    @property
    def summary(self) -> str:
        parts = [f"{self.success_count} updated"]
        if self.error_count:
            parts.append(f"{self.error_count} errors")
        if self.skipped_count:
            parts.append(f"{self.skipped_count} skipped")
        return ", ".join(parts)


class BatchEditor:
    """Apply tag changes to multiple files at once."""

    def __init__(self) -> None:
        self._operations: list[BatchOperation] = []

    def add_operation(self, op: BatchOperation) -> None:
        self._operations.append(op)

    def clear_operations(self) -> None:
        self._operations.clear()

    @property
    def operations(self) -> list[BatchOperation]:
        return list(self._operations)

    def apply(
        self,
        audio_files: list[AudioFile],
        dry_run: bool = False,
    ) -> BatchResult:
        """Apply all queued operations to the given files.

        Args:
            audio_files: Files to modify.
            dry_run: If True, validate but don't write.

        Returns:
            BatchResult with success/error counts.
        """
        result = BatchResult(total_files=len(audio_files))

        for af in audio_files:
            try:
                meta = read_metadata(af)
                if meta.error:
                    result.error_count += 1
                    result.errors.append((af.path.name, meta.error))
                    continue

                changed = False
                for op in self._operations:
                    if self._apply_operation(meta, op):
                        changed = True

                if changed and not dry_run:
                    error = write_metadata(meta)
                    if error:
                        result.error_count += 1
                        result.errors.append((af.path.name, error))
                    else:
                        result.success_count += 1
                elif changed:
                    result.success_count += 1  # Would succeed in non-dry-run
                else:
                    result.skipped_count += 1

            except Exception as e:
                result.error_count += 1
                result.errors.append((af.path.name, str(e)))

        return result

    def _apply_operation(self, meta: AudioMetadata, op: BatchOperation) -> bool:
        """Apply a single operation to metadata. Returns True if modified."""
        current = meta.tags.get(op.field, "")

        if op.mode == "set":
            if current != op.value:
                meta.set_tag(op.field, op.value)
                return True
        elif op.mode == "append":
            if op.value not in current:
                meta.set_tag(op.field, current + op.value)
                return True
        elif op.mode == "prepend":
            if op.value not in current:
                meta.set_tag(op.field, op.value + current)
                return True
        elif op.mode == "clear":
            if current:
                meta.set_tag(op.field, "")
                return True
        elif op.mode == "find_replace":
            if op.find and op.find in current:
                meta.set_tag(op.field, current.replace(op.find, op.replace))
                return True

        return False


def batch_set_field(
    audio_files: list[AudioFile],
    field: str,
    value: str,
    dry_run: bool = False,
) -> BatchResult:
    """Convenience function to set a single field on multiple files."""
    editor = BatchEditor()
    editor.add_operation(BatchOperation(field=field, value=value, mode="set"))
    return editor.apply(audio_files, dry_run=dry_run)


def batch_find_replace(
    audio_files: list[AudioFile],
    field: str,
    find: str,
    replace: str,
    dry_run: bool = False,
) -> BatchResult:
    """Convenience function for find/replace across multiple files."""
    editor = BatchEditor()
    editor.add_operation(BatchOperation(field=field, value="", mode="find_replace", find=find, replace=replace))
    return editor.apply(audio_files, dry_run=dry_run)
