"""A minimal XLSX writer (Office Open XML, one sheet, no dependency) for exports of every app (Ppm-1971): typed
cells — numbers, booleans, dates (date format), text as inline strings (never formulas, so no injection) — a bold
header row and frozen header pane."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

_ILLEGAL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]')
_EPOCH = date(1899, 12, 30)
MAX_TEXT = 32_767

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/></Relationships>'
)
_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/></Relationships>'
)
# styles: 0 default · 1 bold (header) · 2 date (built-in format 14) · 3 date + time (22)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '</fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    '</styleSheet>'
)


def _column(index: int) -> str:
    name = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _text(value: str) -> str:
    return escape(_ILLEGAL.sub('', value)[:MAX_TEXT])


def _cell(ref: str, value: Any, style: int = 0) -> str:
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float, Decimal)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    if isinstance(value, datetime):
        serial = (
            value - datetime.combine(_EPOCH, datetime.min.time(), value.tzinfo)
        ).total_seconds() / 86400
        return f'<c r="{ref}" s="3"><v>{serial}</v></c>'
    if isinstance(value, date):
        return f'<c r="{ref}" s="2"><v>{(value - _EPOCH).days}</v></c>'
    s = f' s="{style}"' if style else ''
    return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{_text(str(value))}</t></is></c>'


def to_xlsx(
    header: Sequence[str], rows: Iterable[Sequence[Any]], sheet: str = 'Export'
) -> bytes:
    """One sheet: ``header`` (bold, frozen) then ``rows``; ISO date strings stay text — pass ``date`` objects."""
    lines = [
        '<row r="1">'
        + ''.join(_cell(f'{_column(i)}1', h, 1) for i, h in enumerate(header))
        + '</row>'
    ]
    for r, row in enumerate(rows, start=2):
        lines.append(
            f'<row r="{r}">'
            + ''.join(_cell(f'{_column(i)}{r}', v) for i, v in enumerate(row))
            + '</row>'
        )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
        'state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(lines)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_text(sheet[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CONTENT_TYPES)
        z.writestr('_rels/.rels', _RELS)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', _WORKBOOK_RELS)
        z.writestr('xl/styles.xml', _STYLES)
        z.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return out.getvalue()
