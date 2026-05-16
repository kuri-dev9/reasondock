from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from app.rca.spec_loader import FieldSpec


RS = "\x1e"


@dataclass(frozen=True)
class ParseStats:
    total_lines: int
    parsed_records: int
    skipped_records: int
    expected_fields: int
    bad_field_counts: dict[int, int]


@dataclass(frozen=True)
class ParsedXdr:
    records: list[dict[str, str]]
    stats: ParseStats


def _iter_lines(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        for line in file:
            yield line.rstrip("\r\n")


def parse_xdr_file(path: Path, fields: tuple[FieldSpec, ...]) -> ParsedXdr:
    expected = len(fields)
    records: list[dict[str, str]] = []
    total = 0
    skipped = 0
    bad_counts: dict[int, int] = {}

    for line in _iter_lines(path):
        if not line:
            continue
        total += 1
        parts = line.split(RS)
        if len(parts) != expected:
            skipped += 1
            bad_counts[len(parts)] = bad_counts.get(len(parts), 0) + 1
            continue
        records.append({field.name: parts[field.index] for field in fields})

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
