"""Page documents (editor-spec §1): validation against the block catalog (Site-0103), references to
media / pages, plain text for AI and SEO.

Document = ``{"schemaVersion": 1, "sections": [Block]}``; Block = ``{"id", "type", "props"?,
"content"? (richText: ProseMirror JSON), "children"? (containers)}``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

_DATA = Path(__file__).parent / 'data'

SCHEMA_VERSION = 1
_ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
_ICON = re.compile(r'^[a-z0-9-]{1,40}$')
_ASSET = re.compile(r'^asset:([0-9a-fA-F-]{36})$')
_PAGE = re.compile(r'^page:([0-9a-fA-F-]{36})(#[A-Za-z0-9_-]{1,60})?$')
_SAFE_URL = re.compile(r'^(https?://[^\s<>"]+|mailto:[^\s<>"]+|tel:[+0-9 ()-]+|#[A-Za-z0-9_-]{0,60}|/[^\s<>"]*)$', re.I)
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# ProseMirror schema of the richText block (Tiptap StarterKit subset + tables, editor-spec Site-0104).
_PM_NODES = {
    'doc', 'paragraph', 'heading', 'text', 'bulletList', 'orderedList', 'listItem', 'taskList', 'taskItem', 'blockquote',
    'codeBlock', 'hardBreak', 'horizontalRule', 'table', 'tableRow', 'tableHeader', 'tableCell',
}
_PM_MARKS = {'bold', 'italic', 'strike', 'code', 'link', 'underline'}
_TABLE_CELLS = {'tableHeader', 'tableCell'}


@dataclass(frozen=True, slots=True)
class DocumentIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f'{self.path}: {self.message}'


@lru_cache(maxsize=1)
def block_catalog() -> dict[str, Any]:
    return json.loads((_DATA / 'blocks.json').read_text(encoding='utf-8'))


def block_types() -> dict[str, Any]:
    return block_catalog()['blocks']


def empty_document() -> dict[str, Any]:
    return {'schemaVersion': SCHEMA_VERSION, 'sections': []}


def is_safe_url(value: str) -> bool:
    return bool(_SAFE_URL.match(value) or _PAGE.match(value))


def _accepts(parent: str | None, child: str) -> bool:
    if parent is None:
        return child != 'column'
    rule = block_types()[parent].get('accepts')
    if rule == 'column':
        return child == 'column'
    if child in ('section', 'column'):
        return False
    return not (parent == 'column' and child == 'columns')


class _Validator:
    def __init__(self) -> None:
        self.issues: list[DocumentIssue] = []
        self.ids: set[str] = set()
        self.count = 0
        limits = block_catalog()['limits']
        self.max_blocks = limits['maxBlocks']
        self.max_depth = limits['maxDepth']
        self.max_text = limits['maxTextLength']
        self.max_list = limits['maxListItems']
        self.max_table_columns = limits['maxTableColumns']
        self.max_table_rows = limits['maxTableRows']

    def add(self, path: str, message: str) -> None:
        if len(self.issues) < 50:
            self.issues.append(DocumentIssue(path, message))

    def value(self, path: str, spec: dict[str, Any], value: Any) -> None:
        kind = spec['type']
        if value is None:
            if spec.get('required'):
                self.add(path, 'is required')
            return
        if kind in ('string', 'text'):
            if not isinstance(value, str):
                self.add(path, 'must be text')
                return
            if spec.get('required') and not value.strip():
                self.add(path, 'is required')
            if len(value) > spec.get('max', self.max_text):
                self.add(path, f'is longer than {spec.get("max", self.max_text)} characters')
            if kind == 'string' and ('\n' in value or _CONTROL.search(value)):
                self.add(path, 'must be a single line')
            elif kind == 'text' and _CONTROL.search(value):
                self.add(path, 'contains control characters')
        elif kind == 'number':
            if isinstance(value, bool) or not isinstance(value, int):
                self.add(path, 'must be a whole number')
            elif not spec.get('min', value) <= value <= spec.get('max', value):
                self.add(path, f'must be between {spec.get("min")} and {spec.get("max")}')
        elif kind == 'boolean':
            if not isinstance(value, bool):
                self.add(path, 'must be true or false')
        elif kind == 'enum':
            if value not in spec['options']:
                self.add(path, f'must be one of {", ".join(spec["options"])}')
        elif kind == 'asset':
            if not isinstance(value, str) or not _ASSET.match(value):
                self.add(path, 'must be a media reference asset:<id>')
        elif kind == 'url':
            if not isinstance(value, str) or len(value) > 2048 or (value and not is_safe_url(value)):
                self.add(path, 'must be an http(s), mailto:, tel:, /path, #anchor or page:<id> link')
            elif spec.get('required') and not value:
                self.add(path, 'is required')
        elif kind == 'icon':
            if not isinstance(value, str) or not _ICON.match(value):
                self.add(path, 'must be an icon name')
        elif kind == 'list':
            if not isinstance(value, list):
                self.add(path, 'must be a list')
                return
            if len(value) > min(spec.get('max', self.max_list), self.max_list):
                self.add(path, f'has more than {min(spec.get("max", self.max_list), self.max_list)} items')
            for i, item in enumerate(value):
                self.props(f'{path}[{i}]', spec['fields'], item)
        else:  # pragma: no cover - catalog error
            self.add(path, f'unknown prop type {kind}')

    def props(self, path: str, specs: dict[str, Any], props: Any) -> None:
        if not isinstance(props, dict):
            self.add(path, 'must be an object')
            return
        for name in props:
            if name not in specs:
                self.add(f'{path}.{name}', 'unknown property')
        for name, spec in specs.items():
            self.value(f'{path}.{name}', spec, props.get(name))

    def rich_text(self, path: str, node: Any, depth: int = 0) -> None:
        if not isinstance(node, dict) or node.get('type') not in _PM_NODES:
            self.add(path, f'unsupported rich text node {node.get("type") if isinstance(node, dict) else node!r}')
            return
        if depth > 12:
            self.add(path, 'rich text is nested too deeply')
            return
        if node['type'] == 'text':
            text = node.get('text')
            if not isinstance(text, str) or len(text) > self.max_text:
                self.add(path, 'invalid text')
            for mark in node.get('marks') or []:
                if not isinstance(mark, dict) or mark.get('type') not in _PM_MARKS:
                    self.add(path, 'unsupported text mark')
                elif mark['type'] == 'link':
                    href = (mark.get('attrs') or {}).get('href')
                    if not isinstance(href, str) or not is_safe_url(href):
                        self.add(path, 'unsafe link')
            return
        if node['type'] == 'tableRow' or node['type'] in _TABLE_CELLS:
            self.add(path, f'{node["type"]} must be inside a table')
            return
        if node['type'] == 'heading' and (node.get('attrs') or {}).get('level') not in (1, 2, 3, 4):
            self.add(path, 'heading level must be 1 to 4')
        if node['type'] == 'taskItem' and not isinstance((node.get('attrs') or {}).get('checked', False), bool):
            self.add(path, 'checked must be true or false')
        if node['type'] == 'table':
            self.table(path, node, depth)
            return
        for i, child in enumerate(node.get('content') or []):
            self.rich_text(f'{path}.content[{i}]', child, depth + 1)

    def table(self, path: str, node: dict[str, Any], depth: int) -> None:
        """Rich text table (Site-0104): rows of cells of paragraphs, the same number of cells per row, ≤ limits."""
        rows = node.get('content') if isinstance(node.get('content'), list) else []
        if not rows:
            self.add(path, 'a table needs at least one row')
            return
        if len(rows) > self.max_table_rows:
            self.add(path, f'a table has at most {self.max_table_rows} rows')
            return
        width: int | None = None
        for r, row in enumerate(rows):
            row_path = f'{path}.content[{r}]'
            is_row = isinstance(row, dict) and row.get('type') == 'tableRow'
            cells = row.get('content') if is_row and isinstance(row.get('content'), list) else []
            if not is_row:
                self.add(row_path, 'a table holds table rows only')
            elif not cells:
                self.add(row_path, 'a table row needs at least one cell')
            elif width is None and len(cells) > self.max_table_columns:
                self.add(path, f'a table has at most {self.max_table_columns} columns')
                return
            elif width is not None and len(cells) != width:
                self.add(row_path, 'every table row has the same number of cells')
            if not cells:
                continue
            width = len(cells) if width is None else width
            for c, cell in enumerate(cells):
                cell_path = f'{row_path}.content[{c}]'
                if not isinstance(cell, dict) or cell.get('type') not in _TABLE_CELLS:
                    self.add(cell_path, 'a table row holds table cells only')
                    continue
                attrs = cell.get('attrs') if isinstance(cell.get('attrs'), dict) else {}
                if attrs.get('colspan') not in (None, 1) or attrs.get('rowspan') not in (None, 1):
                    self.add(cell_path, 'merged table cells are not supported')
                paragraphs = cell.get('content') if isinstance(cell.get('content'), list) else []
                for p, paragraph in enumerate(paragraphs):
                    if not isinstance(paragraph, dict) or paragraph.get('type') != 'paragraph':
                        self.add(f'{cell_path}.content[{p}]', 'a table cell holds paragraphs only')
                    else:
                        self.rich_text(f'{cell_path}.content[{p}]', paragraph, depth + 3)

    def block(self, path: str, block: Any, parent: str | None, depth: int) -> None:
        self.count += 1
        if self.count > self.max_blocks:
            if self.count == self.max_blocks + 1:
                self.add(path, f'a page holds at most {self.max_blocks} blocks')
            return
        if not isinstance(block, dict):
            self.add(path, 'must be a block object')
            return
        bid, btype = block.get('id'), block.get('type')
        if not isinstance(bid, str) or not _ID.match(bid):
            self.add(path, 'id must be 1-40 letters, digits, - or _')
        elif bid in self.ids:
            self.add(path, f'duplicate block id {bid}')
        else:
            self.ids.add(bid)
        spec = block_types().get(btype) if isinstance(btype, str) else None
        if spec is None:
            self.add(path, f'unknown block type {btype!r}')
            return
        label = f'{path}<{btype}>'
        if not _accepts(parent, btype):
            self.add(label, f'cannot be placed {"at the top level" if parent is None else f"inside {parent}"}')
        for key in block:
            if key not in ('id', 'type', 'props', 'content', 'children', 'hidden'):
                self.add(f'{label}.{key}', 'unknown field')
        self.props(f'{label}.props', spec.get('props', {}), block.get('props') or {})
        hidden = block.get('hidden')
        if hidden is not None and (
            not isinstance(hidden, list) or any(h not in ('desktop', 'tablet', 'mobile') for h in hidden)
        ):
            self.add(f'{label}.hidden', 'must list desktop, tablet or mobile')
        if spec.get('content'):
            content = block.get('content')
            if content is not None:
                if not isinstance(content, dict) or content.get('type') != 'doc':
                    self.add(f'{label}.content', 'must be a rich text document')
                else:
                    self.rich_text(f'{label}.content', content)
        elif 'content' in block:
            self.add(f'{label}.content', 'not allowed on this block')
        children = block.get('children')
        if spec.get('container'):
            if children is None:
                return
            if not isinstance(children, list):
                self.add(f'{label}.children', 'must be a list')
                return
            if depth + 1 > self.max_depth:
                self.add(f'{label}.children', f'blocks nest at most {self.max_depth} levels')
                return
            if spec.get('maxChildren') and len(children) > spec['maxChildren']:
                self.add(f'{label}.children', f'holds at most {spec["maxChildren"]} blocks')
            for i, child in enumerate(children):
                self.block(f'{label}.children[{i}]', child, btype, depth + 1)
        elif children:
            self.add(f'{label}.children', 'this block holds no children')


def validate_document(doc: Any) -> list[DocumentIssue]:
    """Issues of a page document (empty = valid)."""
    v = _Validator()
    if not isinstance(doc, dict):
        return [DocumentIssue('$', 'must be a document object')]
    if doc.get('schemaVersion') != SCHEMA_VERSION:
        v.add('$.schemaVersion', f'must be {SCHEMA_VERSION}')
    for key in doc:
        if key not in ('schemaVersion', 'sections'):
            v.add(f'$.{key}', 'unknown field')
    sections = doc.get('sections')
    if not isinstance(sections, list):
        v.add('$.sections', 'must be a list')
        return v.issues
    size = len(json.dumps(doc, separators=(',', ':')))
    if size > block_catalog()['limits']['maxDocBytes']:
        v.add('$', f'document is larger than {block_catalog()["limits"]["maxDocBytes"] // 1024} KB')
    for i, block in enumerate(sections):
        v.block(f'$.sections[{i}]', block, None, 1)
    return v.issues


def migrate_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Bring an old revision to the current schema on read (Site-0103). Version 1 is the first one."""
    return doc


def iter_blocks(doc: dict[str, Any]) -> Iterator[dict[str, Any]]:
    stack = list(reversed(doc.get('sections') or []))
    while stack:
        block = stack.pop()
        if isinstance(block, dict):
            yield block
            stack.extend(reversed(block.get('children') or []))


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def asset_ids(doc: dict[str, Any], *extra: Any) -> set[UUID]:
    """Media referenced by a document (``asset:<id>`` anywhere in props) and by ``extra`` values."""
    found: set[UUID] = set()
    for value in [*(b.get('props') for b in iter_blocks(doc)), *extra]:
        for text in _strings(value):
            if m := _ASSET.match(text):
                try:
                    found.add(UUID(m.group(1)))
                except ValueError:
                    continue
    return found


def page_ids(doc: dict[str, Any]) -> set[UUID]:
    found: set[UUID] = set()
    for block in iter_blocks(doc):
        for text in _strings(block.get('props')):
            if m := _PAGE.match(text):
                found.add(UUID(m.group(1)))
    return found


def _rich_text(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get('type') == 'text' and isinstance(node.get('text'), str):
            out.append(node['text'])
        for child in node.get('content') or []:
            _rich_text(child, out)
        if node.get('type') in ('paragraph', 'heading', 'listItem', 'taskItem'):
            out.append('\n')


def plain_text(doc: dict[str, Any], limit: int = 12000) -> str:
    """Readable text of a page (AI context, SEO suggestions, search)."""
    out: list[str] = []
    skip = {'image', 'icon', 'href', 'primaryHref', 'secondaryHref', 'buttonHref', 'ctaHref', 'url', 'video', 'avatar', 'notifyEmail', 'name', 'type'}
    for block in iter_blocks(doc):
        if block.get('type') == 'richText':
            _rich_text(block.get('content'), out)
        props = block.get('props') or {}
        for key, value in props.items():
            if key in skip:
                continue
            if isinstance(value, str) and value and not value.startswith(('asset:', 'page:')):
                out.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        out.extend(v for k, v in item.items() if isinstance(v, str) and k not in skip and not v.startswith('asset:'))
        out.append('\n')
    text = re.sub(r'\n{3,}', '\n\n', ' '.join(out).replace(' \n ', '\n')).strip()
    return text[:limit]
