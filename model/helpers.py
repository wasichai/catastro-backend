"""Test helpers shared by the importers' tests: temp files and a CLI runner that captures output."""
import io
import os
import tempfile
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from xml.sax.saxutils import escape


def write_csv(testcase, text, suffix=".csv"):
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(text)
    testcase.addCleanup(os.unlink, f.name)
    return f.name


def write_xlsx(testcase, header, rows):
    """A one-sheet xlsx with shared strings; `rows` are lists of cell texts (None leaves the cell out)."""
    return write_xlsx_sheets(testcase, {"Hoja1": (header, rows)})


def _column_letters(index):
    """The Excel column of a 0-based index: A..Z, AA.."""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def write_xlsx_sheets(testcase, sheets):
    """An xlsx with one sheet per entry of `sheets` (name -> (header, rows)), in that order, sharing one strings
    table; rows are as in write_xlsx."""
    shared, sheet_xml = [], []
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    for header, rows in sheets.values():
        cells = []
        for r_index, values in enumerate([header, *rows], start=1):
            xml_cells = []
            for c_index, value in enumerate(values):
                if value is None:
                    continue
                shared.append(str(value))
                ref = f"{_column_letters(c_index)}{r_index}"
                xml_cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            cells.append(f'<row r="{r_index}">{"".join(xml_cells)}</row>')
        sheet_xml.append(f'<worksheet {ns}><sheetData>{"".join(cells)}</sheetData></worksheet>')
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    testcase.addCleanup(os.unlink, path)
    names = list(sheets)
    with zipfile.ZipFile(path, "w") as z:
        entries = "".join(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>' for n, name in enumerate(names, start=1))
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel_ns}><sheets>{entries}</sheets></workbook>')
        relations = "".join(
            f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            for n in range(1, len(names) + 1)
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relations}</Relationships>',
        )
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>{"".join(f"<si><t>{escape(s)}</t></si>" for s in shared)}</sst>')
        for n, xml in enumerate(sheet_xml, start=1):
            z.writestr(f"xl/worksheets/sheet{n}.xml", xml)
    return path


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()
