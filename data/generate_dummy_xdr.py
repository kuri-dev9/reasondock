#!/usr/bin/env python3
"""Generate editable LTE-Call-KPI dummy XDR data from the bundled spec.

The generated .dat uses ASCII Record Separator (0x1E) between fields and a
newline between records. A pipe-delimited mirror file is also emitted so humans
can inspect and hand-edit the same records more comfortably.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random
from typing import Iterable
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import re


BASE_DIR = Path(__file__).resolve().parent
SPEC_PATH = BASE_DIR / "XDR_Specification_s-probe_corr_20210729.xlsx"
OUT_DIR = BASE_DIR / "dummy_xdr"
DELIMITER = "\x1e"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass(frozen=True)
class FieldSpec:
    no: int
    section: str
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
        shared_strings = []
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
        for sheet in workbook.find("a:sheets", NS).findall("a:sheet", NS):
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


def load_lte_call_kpi_spec() -> list[FieldSpec]:
    specs: list[FieldSpec] = []
    current_section = ""
    for row in _xlsx_rows(SPEC_PATH, "LTE-Call-KPI")[4:]:
        if not row or not row[0]:
            continue
        no = int(float(row[0]))
        section = row[1] or current_section
        current_section = section
        name = row[4] if len(row) > 4 and row[4] else f"Reserved_{no}"
        collect_type = row[7] if len(row) > 7 and row[7] else "string"
        description = row[10] if len(row) > 10 and row[10] else ""
        specs.append(FieldSpec(no, section, name, collect_type, description))
    return specs


def _timestamp(value: datetime) -> str:
    """Return Unix epoch timestamp in microseconds for spec timeval fields."""
    return str(int(value.replace(tzinfo=timezone.utc).timestamp() * 1_000_000))


def _default_value(field: FieldSpec, index: int, start: datetime) -> str:
    if field.collect_type == "timeval":
        return ""
    if field.collect_type in {"uint", "int"}:
        return "0"
    return ""


def _record_template(fields: list[FieldSpec], index: int, start: datetime) -> dict[str, str]:
    return {field.name: _default_value(field, index, start) for field in fields}


def _base_record(fields: list[FieldSpec], index: int, start: datetime) -> dict[str, str]:
    rng = Random(index)
    call_start = start + timedelta(seconds=index * 20)
    call_duration_us = rng.randint(80_000, 4_500_000)
    call_end = call_start + timedelta(microseconds=call_duration_us)
    imsi_tail = 10_000_000_000 + index
    enb_id = 20_000 + (index % 8)
    mme_id = 100 + (index % 4)
    sgw_id = 300 + (index % 3)

    row = _record_template(fields, index, start)
    row.update(
        {
            "SummaryCreateTime": _timestamp(call_end + timedelta(seconds=2)),
            "OngoingFlag": "2",
            "IMSI": f"450081{imsi_tail}",
            "MDN": f"010{rng.randint(10000000, 99999999)}",
            "IMEI": f"35976208{rng.randint(1000000, 9999999)}",
            "ServiceCode": "LTE",
            "PayCode": "P1",
            "Gender": "M" if index % 2 else "F",
            "Age": str(20 + (index % 45)),
            "Vendor": ["Samsung", "Apple", "LG", "Xiaomi"][index % 4],
            "Model": ["SM-S928N", "iPhone16,2", "LM-G900N", "Mi-14"][index % 4],
            "PGW_ID": str(400 + (index % 2)),
            "ims_PGW_ID": str(450 + (index % 2)),
            "SGW_ID": str(sgw_id),
            "MME_ID": str(mme_id),
            "S6a_Authentication_Equip_Type": "1",
            "S6a_Authentication_Equip_ID": "7001",
            "S6a_Location_Equip_Type": "2",
            "S6a_Location_Equip_ID": "7101",
            "S13_Equip_Type": "5",
            "S13_Equip_ID": "7201",
            "First_eNB_ID": str(enb_id),
            "First_Cell_ID": str(10 + (index % 24)),
            "First_eNB_VLAN_ID": f"VLAN-{100 + index % 10}",
            "Last_eNB_ID": str(enb_id),
            "Last_Cell ID": str(10 + (index % 24)),
            "Last_eNB_VLAN_ID": f"VLAN-{100 + index % 10}",
            "PDN_Type": "1",
            "PDN_IPv4": str(3_232_235_777 + index),
            "PDN_IPv6": "",
            "ims_PDN_Type": "1",
            "ims_PDN_IPv4": str(3_232_236_777 + index),
            "ims_PDN_IPv6": "",
            "old_call_type": str([1, 3, 5, 9][index % 4]),
            "old_call_end_time": _timestamp(call_start - timedelta(minutes=5)),
            "old_call_Last_eNB_ID": str(enb_id),
            "old_call_Last_Cell_ID": str(10 + (index % 24)),
            "old_call_Last_TAC": str(8000 + (index % 5)),
            "call_type": str([1, 3, 4, 5, 6, 9][index % 6]),
            "call_start_time": _timestamp(call_start),
            "call_end_time": _timestamp(call_end),
            "call_duration_time": str(call_duration_us),
            "APN": "lte-internet",
            "ims_APN": "ims",
            "CNDomain": "0",
            "InitialUEMessage_RRC_Establishment_Cause": str(index % 5),
            "PathSwitch_count": str(index % 2),
            "PathSwitchFailure_count": "0",
            "attempt_flag": "1",
            "success_flag": "1",
            "data_attempt_flag": "1",
            "data_success_flag": "1",
            "ims_attempt_flag": "0",
            "ims_success_flag": "0",
            "drop_flag": "0",
            "paging_attempt_flag": "1" if index % 7 == 0 else "0",
            "paging_success_flag": "1" if index % 7 == 0 else "0",
            "detachment_flag": "0",
            "detach_flag": "0",
            "npr_flag": "0",
            "auth_attempt_flag": "1",
            "auth_success_flag": "1",
            "location_attempt_flag": "1",
            "location_success_flag": "1",
            "mecheck_attempt_flag": "0",
            "mecheck_success_flag": "0",
            "interval_First_eNB_ID": str(enb_id),
            "interval_First_eNB_IP": str(3_232_238_000 + index),
            "interval_First_Cell_ID": str(10 + (index % 24)),
            "interval_First_TAC": str(8000 + (index % 5)),
            "interval_First_eNB_C_UID": str(50_000 + enb_id),
            "interval_First_eNB_VLAN_ID": f"VLAN-{100 + index % 10}",
            "interval_call_start_time": _timestamp(call_start),
            "old_call_s1ap_release_cause": "0",
            "initial_access_duration": str(rng.randint(20_000, 300_000)),
            "initial_access_msg_count": str(rng.randint(3, 9)),
            "initial_core_duration": str(rng.randint(50_000, 600_000)),
            "initial_core_msg_count": str(rng.randint(3, 12)),
            "initial_paging_duration": str(rng.randint(0, 200_000)),
            "initial_paging_msg_count": str(rng.randint(0, 4)),
            "initial_paging_attempt_count": str(rng.randint(0, 2)),
            "imsi_mcc_mnc_info": "4500810",
            "ue_dcnr": str(index % 2),
            "initial_nr_conn_time": _timestamp(call_start + timedelta(milliseconds=50)),
            "ue_usage_type": "1",
            "mme_restrict_dcnr": "0",
            "ModifyBearer_success_count": "1",
            "InitialUEMessage_Time": _timestamp(call_start + timedelta(milliseconds=10)),
            "spid": str(10 + (index % 5)),
            "ExchangeNumber": row["MDN"][3:7],
            "nas_key_validity": "1",
            "equip_nw": "0",
            "First_eNB_PLMN": "45008",
            "Last_eNB_PLMN": "45008",
            "old_call_Last_eNB_PLMN": "45008",
            "interval_First_eNB_PLMN": "45008",
        }
    )
    return row


def _mark_failure(
    row: dict[str, str],
    *,
    interface: str,
    message: int,
    cause: int,
    event_time: str,
) -> None:
    row.update(
        {
            "success_flag": "0",
            "data_success_flag": "0",
            "drop_flag": "1" if cause == 900 else "0",
            "first_error_interface_protocol": interface,
            "first_error_message": str(message),
            "first_error_time": event_time,
            "first_error_cause": str(cause),
            "last_error_interface_protocol": interface,
            "last_error_message": str(message),
            "last_error_time": event_time,
            "last_error_cause": str(cause),
        }
    )


def generate_records(fields: list[FieldSpec], count: int = 120) -> Iterable[dict[str, str]]:
    start = datetime(2026, 5, 16, 9, 0, 0)
    for index in range(count):
        row = _base_record(fields, index, start)
        call_start = start + timedelta(seconds=index * 20)
        event_time = _timestamp(call_start + timedelta(milliseconds=150))

        if 25 <= index < 65:
            row.update(
                {
                    "MME_ID": "101",
                    "First_eNB_ID": "20011",
                    "Last_eNB_ID": "20011",
                    "s1ap_error_Message": "9",
                    "s1ap_error_Time": event_time,
                    "s1ap_error_Cause": "900",
                    "UEContextReleaseRequest_Time": event_time,
                    "UEContextReleaseRequest_Cause": "900",
                    "initial_access_duration": "1800000",
                }
            )
            _mark_failure(row, interface="2", message=9, cause=900, event_time=event_time)
        elif 70 <= index < 84:
            row.update(
                {
                    "S6a_Authentication_Equip_ID": "7009",
                    "s6a_error_Message": "318",
                    "s6a_error_Time": event_time,
                    "s6a_error_Cause": "5001",
                    "AuthenticationInformation_Time": event_time,
                    "AuthenticationInformation_Cause": "5001",
                    "auth_success_flag": "0",
                }
            )
            _mark_failure(row, interface="1", message=318, cause=5001, event_time=event_time)
        elif 90 <= index < 100:
            row.update(
                {
                    "SGW_ID": "305",
                    "s11_error_Message": "32",
                    "s11_error_Time": event_time,
                    "s11_error_Cause": "64",
                    "ModifyBearer_success_count": "0",
                }
            )
            _mark_failure(row, interface="3", message=32, cause=64, event_time=event_time)
        elif 104 <= index < 110:
            row.update(
                {
                    "call_type": "9",
                    "detach_flag": "1",
                    "DetachRequest_Time": event_time,
                    "DetachRequest_Cause": "0",
                    "DetachRequest_Type": "1",
                    "DetachRequest_Switchoff": "0",
                    "DetachRequest_Direction": "0",
                }
            )

        yield row


def write_outputs(fields: list[FieldSpec], records: list[dict[str, str]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dat_path = OUT_DIR / "LTE-CALL-KPI_R1_20260516_0900.dat"
    readable_path = OUT_DIR / "LTE-CALL-KPI_R1_20260516_0900.pipe.txt"
    fields_path = OUT_DIR / "LTE-CALL-KPI_fields.tsv"
    readme_path = OUT_DIR / "README.md"

    names = [field.name for field in fields]
    with dat_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(DELIMITER.join(record.get(name, "") for name in names))
            file.write("\n")

    with readable_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write("|".join(names))
        file.write("\n")
        for record in records:
            file.write("|".join(record.get(name, "") for name in names))
            file.write("\n")

    with fields_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write("no\tsection\tname\ttype\tdescription\n")
        for field in fields:
            file.write(
                f"{field.no}\t{field.section}\t{field.name}\t"
                f"{field.collect_type}\t{field.description.replace(chr(10), ' ')}\n"
            )

    readme_path.write_text(
        "\n".join(
            [
                "# Dummy LTE-Call-KPI XDR",
                "",
                "- Source spec: `../XDR_Specification_s-probe_corr_20210729.xlsx` sheet `LTE-Call-KPI`",
                "- `.dat` delimiter: ASCII Record Separator `0x1E`",
                "- Record separator: newline `\\n`",
                "- Record count: 120",
                "- Field count per record: 154",
                "- Time format used for `timeval` fields: Unix epoch microseconds, e.g. `1778922005311671`",
                "",
                "## Injected Scenarios",
                "",
                "- Mostly successful LTE call KPI records",
                "- S1AP TIMEOUT burst around records 25-64, concentrated on `MME_ID=101` and `eNB_ID=20011`",
                "- S6a authentication failures around records 70-83, `Cause=5001`",
                "- S11 bearer failures around records 90-99, `Cause=64`, concentrated on `SGW_ID=305`",
                "- Normal Detach cleanup samples around records 104-109",
                "",
                "The pipe-delimited mirror file has a header row and is easier to edit by hand.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"wrote {dat_path}")
    print(f"wrote {readable_path}")
    print(f"wrote {fields_path}")
    print(f"wrote {readme_path}")


def main() -> None:
    fields = load_lte_call_kpi_spec()
    if len(fields) != 154:
        raise RuntimeError(f"Expected 154 LTE-Call-KPI fields, got {len(fields)}")
    records = list(generate_records(fields))
    write_outputs(fields, records)


if __name__ == "__main__":
    main()
