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
    shared, cells = [], []
    for r_index, values in enumerate([header, *rows], start=1):
        xml_cells = []
        for c_index, value in enumerate(values):
            if value is None:
                continue
            shared.append(str(value))
            ref = f"{chr(65 + c_index)}{r_index}"
            xml_cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
        cells.append(f'<row r="{r_index}">{"".join(xml_cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    testcase.addCleanup(os.unlink, path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel_ns}><sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>',
        )
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>{"".join(f"<si><t>{escape(s)}</t></si>" for s in shared)}</sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(cells)}</sheetData></worksheet>')
    return path


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()
