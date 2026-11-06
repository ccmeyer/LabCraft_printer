"""Small synthetic instrument exports; no customer workbooks in the repository."""

from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile


X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def tecan_metadata(gain=100):
    return [
        ["Application: Tecan i-control", None, None, None, "Tecan i-control , 2.0.10.0"],
        ["Device: infinite 200Pro", None, "Target Temperature: 37 °C"],
        ["Mode", None, None, None, "Fluorescence Bottom Reading"],
        ["Excitation Wavelength", None, None, None, 485, "nm"],
        ["Emission Wavelength", None, None, None, 535, "nm"],
        ["Gain", None, None, None, gain, "Manual"],
    ]


def tecan_kinetic_rows():
    return tecan_metadata() + [
        ["Cycle Nr.", 1, 2, 3, 4],
        ["Time [s]", 0, 300, 600, 900.1],
        ["Temp. [°C]", 37.3, 37.2, 36.9, 37.2],
        ["A1", 100, 200, 300, 400],
        ["A2", 110, 210, 310, 410],
        ["End Time:", "11/5/2026 3:32:30 PM"],
    ]


def tecan_endpoint_rows():
    return tecan_metadata(gain=108) + [
        [None, "Temperature: 37.1 °C"],
        ["<>", 1, 2],
        ["A", 100, 200],
        ["B", 300, 400],
        ["End Time:", "11/5/2026 3:35:39 PM"],
    ]


def write_tecan_workbook(path: Path, sheets=None, *, shared_strings=False):
    sheets = sheets if sheets is not None else {"gain 100 actual data": tecan_kinetic_rows(), "Sheet1": []}
    workbook = ET.Element(f"{{{X}}}workbook")
    sheet_nodes = ET.SubElement(workbook, f"{{{X}}}sheets")
    relationships = ET.Element(f"{{{P}}}Relationships")
    shared = []
    with ZipFile(path, "w") as archive:
        for index, (name, rows) in enumerate(sheets.items(), 1):
            ET.SubElement(sheet_nodes, f"{{{X}}}sheet", name=name, sheetId=str(index), attrib={f"{{{R}}}id": f"rId{index}"})
            ET.SubElement(relationships, f"{{{P}}}Relationship", Id=f"rId{index}", Target=f"worksheets/sheet{index}.xml", Type=f"{R}/worksheet")
            worksheet = ET.Element(f"{{{X}}}worksheet")
            data = ET.SubElement(worksheet, f"{{{X}}}sheetData")
            for row_index, values in enumerate(rows, 1):
                row = ET.SubElement(data, f"{{{X}}}row", r=str(row_index))
                for column, value in enumerate(values, 1):
                    if value is None:
                        continue
                    letters = ""
                    number = column
                    while number:
                        number, remainder = divmod(number - 1, 26)
                        letters = chr(65 + remainder) + letters
                    cell = ET.SubElement(row, f"{{{X}}}c", r=f"{letters}{row_index}")
                    if isinstance(value, str) and value.startswith("="):
                        ET.SubElement(cell, f"{{{X}}}f").text = value[1:]
                        ET.SubElement(cell, f"{{{X}}}v").text = "123"
                    elif isinstance(value, str) and shared_strings:
                        cell.set("t", "s")
                        shared.append(value)
                        ET.SubElement(cell, f"{{{X}}}v").text = str(len(shared) - 1)
                    elif isinstance(value, str):
                        cell.set("t", "inlineStr")
                        ET.SubElement(ET.SubElement(cell, f"{{{X}}}is"), f"{{{X}}}t").text = value
                    else:
                        ET.SubElement(cell, f"{{{X}}}v").text = str(value)
            archive.writestr(f"xl/worksheets/sheet{index}.xml", ET.tostring(worksheet))
        archive.writestr("xl/workbook.xml", ET.tostring(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))
        if shared_strings:
            strings = ET.Element(f"{{{X}}}sst")
            for value in shared:
                ET.SubElement(ET.SubElement(strings, f"{{{X}}}si"), f"{{{X}}}t").text = value
            archive.writestr("xl/sharedStrings.xml", ET.tostring(strings))
    return path
