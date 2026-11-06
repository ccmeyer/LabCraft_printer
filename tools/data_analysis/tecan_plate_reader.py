"""Read Tecan i-control fluorescence XLSX exports without Excel or hardware.

Only stored cell values are read. Formulas are never evaluated, and an explicit
worksheet is required when a workbook contains multiple measurement sheets.
"""

from __future__ import annotations

import hashlib
import math
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WELL_RE = re.compile(r"^[A-P](?:[1-9]|1[0-9]|2[0-4])$")


def worksheet_output_token(sheet_name: str) -> str:
    """Keep distinct sheet names distinct even after filesystem sanitization."""
    label = re.sub(r"[^A-Za-z0-9_-]+", "_", sheet_name).strip("_")[:60] or "worksheet"
    digest = hashlib.sha256(sheet_name.encode("utf-8")).hexdigest()[:8]
    return f"{label}_{digest}"


def _xml(archive: ZipFile, member: str) -> ET.Element:
    if archive.getinfo(member).file_size > 32 * 1024 * 1024:
        raise ValueError(f"Tecan workbook XML is too large: {member}")
    return ET.fromstring(archive.read(member))


def read_workbook_rows(path: str | Path) -> dict[str, list[list[object]]]:
    """Decode the small OOXML cell subset used by instrument exports."""
    try:
        with ZipFile(path) as archive:
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = ["".join(t.text or "" for t in item.findall(".//x:t", NS))
                          for item in _xml(archive, "xl/sharedStrings.xml").findall("x:si", NS)]
            relationships = {
                rel.attrib["Id"]: rel.attrib["Target"]
                for rel in _xml(archive, "xl/_rels/workbook.xml.rels").findall(f"{{{REL_NS}}}Relationship")
                if rel.get("TargetMode") != "External"
            }
            result = {}
            for sheet in _xml(archive, "xl/workbook.xml").findall("x:sheets/x:sheet", NS):
                target = relationships[sheet.attrib[f"{{{DOC_REL_NS}}}id"]]
                member = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
                if not member.startswith("xl/"):
                    raise ValueError("Invalid worksheet location in Tecan workbook.")
                rows = []
                for row in _xml(archive, member).findall("x:sheetData/x:row", NS):
                    values = {}
                    for cell in row.findall("x:c", NS):
                        reference = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", cell.attrib["r"])
                        if reference is None:
                            raise ValueError("Invalid cell reference in Tecan workbook.")
                        column = 0
                        for char in reference[1]:
                            column = column * 26 + ord(char) - ord("A") + 1
                        if column > 16384 or column in values:
                            raise ValueError("Invalid or duplicate cell in Tecan workbook.")
                        raw = cell.find("x:v", NS)
                        if cell.find("x:f", NS) is not None:
                            value = "=" + (cell.find("x:f", NS).text or "")
                        elif cell.get("t") == "inlineStr":
                            value = "".join(t.text or "" for t in cell.findall(".//x:t", NS))
                        elif raw is None or raw.text is None:
                            value = None
                        elif cell.get("t") == "s":
                            shared_index = int(raw.text)
                            if not 0 <= shared_index < len(shared):
                                raise ValueError("Invalid shared-string reference in Tecan workbook.")
                            value = shared[shared_index]
                        elif cell.get("t") == "b":
                            value = "TRUE" if raw.text == "1" else "FALSE"
                        elif cell.get("t") in {"str", "e", "d"}:
                            value = raw.text
                        else:
                            value = float(raw.text)
                        values[column] = value
                    if any(value is not None and str(value).strip() for value in values.values()):
                        rows.append([values.get(c) for c in range(1, max(values) + 1)])
                result[sheet.attrib["name"]] = rows
            return result
    except (BadZipFile, KeyError, IndexError, ET.ParseError, OverflowError) as exc:
        raise ValueError(f"Could not read Tecan XLSX workbook: {exc}") from exc


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _is_tecan(rows: list[list[object]]) -> bool:
    return any(_text(row[0]).lower().startswith("application: tecan i-control") for row in rows)


def _headers(rows: list[list[object]]) -> list[int]:
    return [i for i, row in enumerate(rows) if _text(row[0]) in {"Time [s]", "<>"}]


def list_tecan_measurement_sheets(path: str | Path) -> list[str]:
    return [name for name, rows in read_workbook_rows(path).items() if _is_tecan(rows) and _headers(rows)]


def _select_sheet(sheets: dict[str, list[list[object]]], sheet_name: str | None) -> str:
    candidates = [name for name, rows in sheets.items() if _is_tecan(rows) and _headers(rows)]
    if sheet_name is not None:
        if sheet_name not in candidates:
            raise ValueError(f"Worksheet {sheet_name!r} is not a Tecan measurement sheet. Available: {', '.join(candidates) or '(none)'}")
        return sheet_name
    if not candidates:
        raise ValueError("No supported Tecan fluorescence measurement sheets were found.")
    if len(candidates) != 1:
        raise ValueError("Multiple Tecan measurement sheets were found. Select a worksheet in the app or pass --sheet: " + ", ".join(candidates))
    return candidates[0]


def resolve_tecan_sheet_name(path: str | Path, sheet_name: str | None = None) -> str:
    return _select_sheet(read_workbook_rows(path), sheet_name)


def _number(value: object, context: str) -> float:
    if _text(value).upper() == "OVER":
        raise ValueError(f"Over-range (OVER) reading at {context}. Select a lower-gain measurement sheet; saturated values cannot be analyzed quantitatively.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Missing or nonnumeric value at {context}: {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"Non-finite value at {context}.")
    return number


def _metadata(rows: list[list[object]], label: str) -> object:
    matches = [row for row in rows if _text(row[0]) == label]
    if len(matches) != 1:
        raise ValueError(f"Tecan worksheet must contain exactly one {label!r} field.")
    return next((value for value in matches[0][1:] if _text(value)), None)


def _elapsed_time(seconds: float) -> str:
    whole_seconds, nanoseconds = divmod(pd.to_timedelta(seconds, unit="s").value, 1_000_000_000)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    fraction = f".{nanoseconds:09d}".rstrip("0") if nanoseconds else ""
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{fraction}"


def parse_tecan_plate_reader(path: str | Path, sheet_name: str | None = None) -> pd.DataFrame:
    sheets = read_workbook_rows(path)
    selected = _select_sheet(sheets, sheet_name)
    rows = sheets[selected]
    headers = _headers(rows)
    if len(headers) != 1:
        raise ValueError("Tecan worksheet must contain exactly one kinetic table or endpoint grid.")
    header_index = headers[0]
    metadata = rows[:header_index]
    mode = _text(_metadata(metadata, "Mode"))
    if "fluorescence" not in mode.lower():
        raise ValueError(f"Unsupported Tecan measurement mode: {mode!r}; expected fluorescence.")
    excitation = _number(_metadata(metadata, "Excitation Wavelength"), "excitation wavelength")
    emission = _number(_metadata(metadata, "Emission Wavelength"), "emission wavelength")
    if any(value <= 0 or not value.is_integer() for value in (excitation, emission)):
        raise ValueError("Tecan excitation/emission wavelengths must be positive integer nanometers.")
    gain = _number(_metadata(metadata, "Gain"), "gain")
    if gain < 0:
        raise ValueError("Tecan gain must be nonnegative.")
    fluorophore = f"{int(excitation)}_{int(emission)}"
    kinetic = _text(rows[header_index][0]) == "Time [s]"
    header = rows[header_index]
    columns = [(i, _number(value, "time" if kinetic else "plate column")) for i, value in enumerate(header[1:], 1) if _text(value)]
    if not columns or len({v for _, v in columns}) != len(columns):
        raise ValueError("Tecan measurement header contains no columns or duplicate times/plate columns.")
    if [i for i, _ in columns] != list(range(1, len(columns) + 1)):
        raise ValueError("Tecan measurement header contains blank time/plate-column headers.")
    if kinetic:
        times = [value for _, value in columns]
        if times[0] < 0 or times != sorted(times):
            raise ValueError("Tecan elapsed seconds must be nonnegative and strictly increasing.")
        if len(rows) <= header_index + 1:
            raise ValueError("Tecan kinetic table is missing the temperature row.")
        temperature_row = rows[header_index + 1]
        if not _text(temperature_row[0]).startswith("Temp."):
            raise ValueError("Tecan kinetic table is missing the temperature row.")
        temperatures = {i: _number(temperature_row[i] if i < len(temperature_row) else None, "temperature") for i, _ in columns}
        data_rows = rows[header_index + 2:]
    else:
        if any(not value.is_integer() or not 1 <= value <= 24 for _, value in columns):
            raise ValueError("Tecan endpoint plate columns must be integers from 1 to 24.")
        temperature_values = [match.group(1) for row in metadata for value in row
                              if (match := re.match(r"Temperature:\s*([-+]?\d+(?:\.\d+)?)", _text(value)))]
        if len(temperature_values) != 1:
            raise ValueError("Tecan endpoint grid must specify one measurement temperature.")
        temperatures = {i: float(temperature_values[0]) for i, _ in columns}
        data_rows = rows[header_index + 1:]

    records = []
    seen = set()
    for row in data_rows:
        label = _text(row[0]).upper()
        if label == "END TIME:":
            break
        if not (WELL_RE.fullmatch(label) if kinetic else re.fullmatch(r"[A-P]", label)):
            raise ValueError(f"Unexpected Tecan measurement row: {row[0]!r}")
        if label in seen:
            raise ValueError(f"Duplicate Tecan measurement row: {label}")
        seen.add(label)
        if any(_text(value) for value in row[max(i for i, _ in columns) + 1:]):
            raise ValueError(f"Tecan row {label} has readings without a time/plate-column header.")
        for column, value in columns:
            well = label if kinetic else f"{label}{int(value)}"
            seconds = value if kinetic else 0.0
            rfu = _number(row[column] if column < len(row) else None, f"{selected!r}, well {well}, time {seconds:g} s")
            records.append({"time": _elapsed_time(seconds),
                            "time_seconds": seconds, "time_minutes": seconds / 60,
                            "temperature_c": temperatures[column], "well": well,
                            "fluorophore": fluorophore, "excitation_nm": int(excitation),
                            "emission_nm": int(emission), "rfu": rfu})
    if not records:
        raise ValueError("No fluorescence readings were found in the Tecan worksheet.")
    dataframe = pd.DataFrame(records).sort_values(["well", "fluorophore", "time_seconds"], kind="stable").reset_index(drop=True)
    dataframe.attrs.update(source_sheet=selected, gain=gain, measurement_kind="kinetic" if kinetic else "endpoint", read_mode=mode)
    return dataframe
