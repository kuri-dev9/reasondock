from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree as ET


SPEC_FILENAME = "XDR_Specification_s-probe_corr_20210729.xlsx"
SHEET_NAME = "LTE-Call-KPI"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass(frozen=True)
class FieldSpec:
    no: int
    index: int
    sheet_name: str
    section: str
    tree_path: tuple[str, ...]
    name: str
    collect_type: str
    description: str


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - 64
    return index - 1


def _xlsx_rows(path: Path, sheet_name: str) -> list[list[str | None]]:
    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in shared_root.findall("a:si", NS):
            shared_strings.append("".join(t.text or "" for t in item.findall(".//a:t", NS)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("rel:Relationship", REL_NS)
        }

        target = None
        sheets = workbook.find("a:sheets", NS)
        if sheets is None:
            raise ValueError("Invalid xlsx: workbook has no sheets")
        for sheet in sheets.findall("a:sheet", NS):
            if sheet.attrib["name"] == sheet_name:
                rel_id = sheet.attrib[
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                ]
                target = "xl/" + rel_map[rel_id]
                break
        if target is None:
            raise ValueError(f"Sheet not found: {sheet_name}")

        root = ET.fromstring(archive.read(target))
        rows: list[list[str | None]] = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            values: list[str | None] = []
            last_index = -1
            for cell in row.findall("a:c", NS):
                index = _column_index(cell.attrib["r"])
                while last_index + 1 < index:
                    values.append(None)
                    last_index += 1
                value_node = cell.find("a:v", NS)
                value = None if value_node is None else value_node.text
                if cell.attrib.get("t") == "s" and value is not None:
                    value = shared_strings[int(value)]
                values.append(value)
                last_index = index
            rows.append(values)
        return rows


@lru_cache(maxsize=1)
def load_lte_call_kpi_spec() -> tuple[FieldSpec, ...]:
    candidates = [
        Path.cwd() / "data" / SPEC_FILENAME,
        Path(__file__).resolve().parents[3] / "data" / SPEC_FILENAME,
        Path(__file__).resolve().parents[2] / "data" / SPEC_FILENAME,
    ]
    spec_path = next((path for path in candidates if path.exists()), None)
    if spec_path is None:
        raise FileNotFoundError(
            "XDR spec not found. Tried: " + ", ".join(str(path) for path in candidates)
        )

    rows = _xlsx_rows(spec_path, SHEET_NAME)
    header = rows[3]
    no_index = next((idx for idx, value in enumerate(header) if value == "No."), 0)
    name_index = next((idx for idx, value in enumerate(header) if value == "Name"), 4)
    hierarchy_indexes = list(range(no_index + 1, name_index))

    fields: list[FieldSpec] = []
    current_path: list[str] = [""] * len(hierarchy_indexes)
    for row in rows[4:]:
        if not row or not row[0]:
            continue
        no = int(float(row[0]))
        for path_pos, column_index in enumerate(hierarchy_indexes):
            value = row[column_index] if len(row) > column_index else None
            if value:
                current_path[path_pos] = value
                for deeper in range(path_pos + 1, len(current_path)):
                    current_path[deeper] = ""
        tree_path = tuple(part for part in current_path if part)
        section = tree_path[0] if tree_path else ""
        name = row[name_index] if len(row) > name_index and row[name_index] else f"Reserved_{no}"
        collect_type = row[7] if len(row) > 7 and row[7] else "string"
        description = row[10] if len(row) > 10 and row[10] else ""
        fields.append(
            FieldSpec(
                no=no,
                index=no - 1,
                sheet_name=SHEET_NAME,
                section=section,
                tree_path=tree_path,
                name=name,
                collect_type=collect_type,
                description=description,
            )
        )
    return tuple(fields)


def fields_by_name(fields: tuple[FieldSpec, ...]) -> dict[str, FieldSpec]:
    return {field.name: field for field in fields}
