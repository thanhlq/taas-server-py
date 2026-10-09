"""PPM dashboards & reports, pure parts (taas-specs/ppm/reporting/dashboards-reports-spec.md): widget query and filter
validation, layout rules (12 columns, ≤ 24 widgets), the system dashboards, CSV / XLSX files."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from foundation.exceptions import ClientException

from ews.ppm import _dashboards as dashboards
from ews.ppm import _reports as reports
from ews.ppm import _widgets as widgets
from ews.shared import to_xlsx


def test_queries_are_validated():
    q = widgets.clean_query(
        {
            'source': 'items',
            'group_by': 'assignee',
            'filters': {'open': 1, 'labels': 'x'},
        }
    )
    assert q == {
        'source': 'items',
        'measure': 'count',
        'group_by': 'assignee',
        'filters': {'open': True, 'labels': ['x']},
    }
    assert widgets.clean_query({'source': 'kpi'})['metric'] == 'open'
    for bad in (
        {'source': 'nope'},
        {'source': 'items', 'measure': 'money'},
        {'source': 'items', 'group_by': 'health'},
        {'source': 'items', 'stack_by': 'band'},
        {'source': 'item_list', 'limit': 500},
        {'source': 'items', 'filters': {'evil': 1}},
        {'source': 'items', 'filters': {'project_ids': ['not-an-id']}},
        {'source': 'items', 'filters': {'date_from': 'yesterday'}},
    ):
        with pytest.raises(ClientException):
            widgets.clean_query(bad)


def test_filters_merge_later_layers_win():
    merged = widgets.merge_filters(
        {'owner': 'a', 'open': True}, {'owner': 'b', 'labels': []}, None, {'mine': True}
    )
    assert merged == {'owner': 'b', 'open': True, 'mine': True}


def test_layout_rules():
    layout = dashboards.clean_layout(
        [
            {
                'id': 'a',
                'type': 'kpi',
                'x': 0,
                'y': 0,
                'w': 3,
                'h': 2,
                'query': {'source': 'kpi', 'metric': 'overdue'},
            },
            {
                'id': 'b',
                'type': 'text',
                'x': 3,
                'y': 0,
                'w': 9,
                'h': 2,
                'text': 'Hello',
                'viz': {'tone': 'info'},
            },
        ]
    )
    assert layout['schema_version'] == 1
    assert layout['widgets'][1] == {
        'id': 'b',
        'type': 'text',
        'x': 3,
        'y': 0,
        'w': 9,
        'h': 2,
        'text': 'Hello',
        'viz': {'tone': 'info'},
    }
    bad_layouts = (
        [{'id': 'a', 'type': 'kpi', 'x': 10, 'w': 3}],  # past column 12
        [{'id': 'a', 'type': 'pie'}],  # unknown type
        [{'id': 'a', 'type': 'kpi'}, {'id': 'a', 'type': 'kpi'}],  # duplicate id
        [
            {'id': 'a', 'type': 'kpi', 'query': {'source': 'items'}}
        ],  # source not allowed for the type
        [{'id': str(i), 'type': 'text'} for i in range(25)],  # more than 24 widgets
    )
    for bad in bad_layouts:
        with pytest.raises(ClientException):
            dashboards.clean_layout(bad)


def test_system_dashboards_are_valid():
    for key in dashboards.SYSTEM:
        layout = dashboards.system_layout(key)
        assert layout['widgets'], key
        cells = set()
        for w in layout['widgets']:
            for x in range(w['x'], w['x'] + w['w']):
                for y in range(w['y'], w['y'] + w['h']):
                    assert (x, y) not in cells, f'{key}: {w["id"]} overlaps'
                    cells.add((x, y))


def test_csv_and_xlsx_files():
    result = widgets.Result(
        [
            {'key': 'id', 'type': 'project'},
            {'key': 'name', 'type': 'string'},
            {'key': 'due', 'type': 'date'},
        ],
        [['p1', '=HYPERLINK("x")', '2026-10-09'], ['p2', 'Mobile & Web <app>', None]],
        2,
    )
    body, media, name = reports.render(
        result, 'csv', labels={'name': 'Nom'}, title='status'
    )
    text = body.decode('utf-8')
    assert (
        media.startswith('text/csv')
        and name.startswith('status-')
        and name.endswith('.csv')
    )
    assert text.startswith('﻿Nom,due')  # id columns are left out
    assert "'=HYPERLINK" in text  # formula-safe
    body, media, _ = reports.render(result, 'xlsx')
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        sheet = z.read('xl/worksheets/sheet1.xml').decode()
        assert 'Mobile &amp; Web &lt;app&gt;' in sheet
        assert '<f>' not in sheet  # inline strings, never formulas
        assert '<c r="B2" s="2"><v>' in sheet  # a date cell
    with pytest.raises(ClientException):
        reports.render(result, 'pdf')


def test_xlsx_types():
    data = to_xlsx(['n', 'ok', 'day'], [[1.5, True, date(2026, 1, 1)]])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheet = z.read('xl/worksheets/sheet1.xml').decode()
        assert set(z.namelist()) >= {
            '[Content_Types].xml',
            'xl/workbook.xml',
            'xl/styles.xml',
        }
    assert '<c r="A2"><v>1.5</v></c>' in sheet
    assert '<c r="B2" t="b"><v>1</v></c>' in sheet
    assert '<c r="C2" s="2"><v>46023</v></c>' in sheet
