from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.rca.spec_loader import FieldSpec


FIELD_SEP = "\x1e"
RECORD_SEP = "\x1e\x1e\x1e"
RECORD_END_SEPS = (f"{RECORD_SEP}\r\n", f"{RECORD_SEP}\n")
CHUNK_SIZE = 64 * 1024 * 1024
STREAMING_THRESHOLD = 500 * 1024 * 1024


@dataclass(frozen=True)
class ParseStats:
    total_lines: int
    parsed_records: int
    skipped_records: int
    expected_fields: int
    bad_field_counts: dict[int, int]


@dataclass(frozen=True)
class ParsedXdr:
    records: list[dict[str, Any]]
    stats: ParseStats


def _find_record_end(buffer: str) -> tuple[int, int]:
    matches = [
        (index, len(separator))
        for separator in RECORD_END_SEPS
        if (index := buffer.find(separator)) >= 0
    ]
    return min(matches, default=(-1, 0))


def _iter_records_from_content(content: str) -> Iterator[str]:
    if any(separator in content for separator in RECORD_END_SEPS):
        buffer = content
        while True:
            index, separator_len = _find_record_end(buffer)
            if index < 0:
                break
            record = buffer[:index].strip("\r\n ")
            if record:
                yield record
            buffer = buffer[index + separator_len :]
        record = buffer.strip("\r\n ")
        if record:
            yield record
        return

    for line in content.splitlines():
        line = line.rstrip("\r\n")
        if line:
            yield line


def _iter_records_streaming(path: Path) -> Iterator[str]:
    buffer = ""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        while True:
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            buffer += chunk
            while True:
                index, separator_len = _find_record_end(buffer)
                if index < 0:
                    break
                record = buffer[:index].strip("\r\n ")
                if record:
                    yield record
                buffer = buffer[index + separator_len :]

    record = buffer.strip("\r\n ")
    if record:
        yield record


def _iter_records(path: Path) -> Iterator[str]:
    if path.stat().st_size >= STREAMING_THRESHOLD:
        yield from _iter_records_streaming(path)
        return

    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        yield from _iter_records_from_content(file.read())


def _timeval(value: Any, default: int = -1) -> int:
    try:
        text = str(value).strip()
        if not text:
            return default
        if "." in text:
            return int(float(text) * 1_000_000)
        parsed = int(text)
        if abs(parsed) < 1_000_000_000_000:
            return parsed * 1_000_000
        return parsed
    except (TypeError, ValueError):
        return default


def _normalize_record(parts: list[str], fields: tuple[FieldSpec, ...]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for field in fields:
        value = parts[field.index]
        if field.collect_type == "timeval":
            record[field.name] = _timeval(value)
        else:
            record[field.name] = value
    return record


def parse_xdr_file(path: Path, fields: tuple[FieldSpec, ...]) -> ParsedXdr:
    expected = len(fields)
    records: list[dict[str, Any]] = []
    total = 0
    skipped = 0
    bad_counts: dict[int, int] = {}

    for record in _iter_records(path):
        if not record:
            continue
        total += 1
        parts = record.split(FIELD_SEP)
        if len(parts) < expected:
            parts.extend([""] * (expected - len(parts)))
        if len(parts) != expected:
            skipped += 1
            bad_counts[len(parts)] = bad_counts.get(len(parts), 0) + 1
            continue
        records.append(_normalize_record(parts, fields))

    return ParsedXdr(
        records=records,
        stats=ParseStats(
            total_lines=total,
            parsed_records=len(records),
            skipped_records=skipped,
            expected_fields=expected,
            bad_field_counts=bad_counts,
        ),
    )
