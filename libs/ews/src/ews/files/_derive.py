"""Derived data of a file version (File-0302, File-0400, File-0601): pure functions on bytes — no I/O, no database
(unit-tested in ``tests/unit/test_files_derive.py``). The pipeline (``_pipeline``) runs ``derive`` in a thread.

| Type (sniffed from the content) | Variants | Text (local index) | Metadata |
| --- | --- | --- | --- |
| Raster images (PNG, JPEG, GIF, WebP, AVIF, BMP, TIFF) | ``thumb`` ≤ 480 px, ``preview`` ≤ 1920 px (large or non-web formats), placeholder | — (OCR: P2) | width, height, taken_at |
| PDF (PDFium) | ``thumb`` of page 1, placeholder | every page (≤ 300) | pages, title, author |
| Office Open XML / OpenDocument | embedded thumbnail when the file has one | document text, slides, shared strings | title, author, pages |
| Text, Markdown, CSV, JSON, XML, code, HTML (tags removed) — any text content | — (rendered by the client) | the text | lines |

Everything else gets nothing (``none``): the web shows the type icon. Files are hostile input: Pillow's pixel limit
(decompression bombs), capped ZIP members, regex text extraction for XML (no entity expansion), PDFium under a lock
(not thread-safe).
"""

from __future__ import annotations

import base64
import html
import io
import re
import threading
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 80_000_000  # decompression-bomb guard (same as ews.media)

type Status = Literal['ready', 'none', 'failed']

THUMB_BOX = 480
PREVIEW_BOX = 1920
PLACEHOLDER_BOX = 24
PLACEHOLDER_MAX = 2048
"""Longest ``data:`` URI kept as a placeholder (column size)."""
MAX_PDF_TEXT_PAGES = 300
MAX_ZIP_MEMBER = 20 * 1024 * 1024
MAX_ZIP_TOTAL = 60 * 1024 * 1024
WEB_FORMATS = frozenset({'JPEG', 'PNG', 'GIF', 'WEBP', 'AVIF'})
READABLE_IMAGES = frozenset(
    {
        'image/png',
        'image/jpeg',
        'image/gif',
        'image/webp',
        'image/avif',
        'image/bmp',
        'image/tiff',
    }
)
"""Types Pillow reads here: one of them that does not open is broken (``failed``); others (HEIC …) are ``none``."""

_PDFIUM_LOCK = threading.Lock()


@dataclass(slots=True)
class DerivedImage:
    variant: Literal['thumb', 'preview']
    body: bytes
    width: int
    height: int
    mime: str = 'image/webp'


@dataclass(slots=True)
class Derived:
    sniffed: str | None = None
    """Type from the content's magic bytes (``None``: unknown binary)."""
    meta: dict[str, Any] = field(default_factory=dict)
    images: list[DerivedImage] = field(default_factory=list)
    placeholder: str | None = None
    text: str | None = None
    truncated: bool = False
    preview: Status = 'none'
    index: Status = 'none'
    error: str | None = None


# --- type sniffing --------------------------------------------------------------------------------

_MAGIC: list[tuple[bytes, int, str]] = [
    (b'%PDF-', 0, 'application/pdf'),
    (b'\x89PNG\r\n\x1a\n', 0, 'image/png'),
    (b'\xff\xd8\xff', 0, 'image/jpeg'),
    (b'GIF87a', 0, 'image/gif'),
    (b'GIF89a', 0, 'image/gif'),
    (b'BM', 0, 'image/bmp'),
    (b'II*\x00', 0, 'image/tiff'),
    (b'MM\x00*', 0, 'image/tiff'),
    (b'\x1f\x8b', 0, 'application/gzip'),
    (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 0, 'application/x-ole-storage'),
    (b'OggS', 0, 'audio/ogg'),
    (b'fLaC', 0, 'audio/flac'),
    (b'ID3', 0, 'audio/mpeg'),
    (b'\x1a\x45\xdf\xa3', 0, 'video/webm'),
]
_FTYP = {
    b'avif': 'image/avif',
    b'avis': 'image/avif',
    b'heic': 'image/heic',
    b'heix': 'image/heic',
    b'mif1': 'image/heif',
    b'M4A ': 'audio/mp4',
    b'qt  ': 'video/quicktime',
}
_OOXML = {
    'word/document.xml': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xl/workbook.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'ppt/presentation.xml': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}
_HTML = re.compile(rb'^\s*(<!doctype\s+html|<html[\s>])', re.IGNORECASE)


def _zip_type(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            for member, mime in _OOXML.items():
                if member in names:
                    return mime
            if 'mimetype' in names:
                info = archive.getinfo('mimetype')
                if info.file_size < 200:
                    value = archive.read('mimetype').decode('ascii', 'ignore').strip()
                    if value.startswith('application/vnd.oasis.opendocument.'):
                        return value
    except zipfile.BadZipFile, OSError, ValueError:
        pass
    return 'application/zip'


def _looks_like_text(sample: bytes) -> bool:
    """UTF-8 (a character cut at the end of the sample is fine) or a single-byte encoding without control bytes."""
    if not sample or b'\x00' in sample:
        return False
    try:
        sample.decode('utf-8')
        return True
    except UnicodeDecodeError as error:
        if error.reason == 'unexpected end of data':
            return True
    control = sum(1 for b in sample if b < 32 and b not in (9, 10, 12, 13))
    return control / len(sample) < 0.01


def sniff(data: bytes) -> str | None:
    """Type from the magic bytes (never the extension or the client's type, File-0601)."""
    head = data[:16]
    for sig, offset, mime in _MAGIC:
        if head[offset : offset + len(sig)] == sig:
            return mime
    if head[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    if head[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return 'audio/wav'
    if data[4:8] == b'ftyp':
        return _FTYP.get(data[8:12], 'video/mp4')
    if head[:4] == b'PK\x03\x04':
        return _zip_type(data)
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return 'text/plain'  # UTF-16 with a byte order mark
    sample = data[:4096]
    stripped = sample.lstrip(b'\xef\xbb\xbf').lstrip()
    if stripped[:5].lower() == b'<?xml' or stripped[:4].lower() == b'<svg':
        return 'image/svg+xml' if b'<svg' in sample.lower() else 'application/xml'
    if _HTML.match(sample):
        return 'text/html'
    if _looks_like_text(sample):
        return 'text/plain'
    return None


# --- images ---------------------------------------------------------------------------------------


def _webp(image: Image.Image, box: int, quality: int) -> tuple[bytes, int, int]:
    copy = image.copy()
    copy.thumbnail((box, box), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    copy.save(out, 'WEBP', quality=quality, method=4)
    return out.getvalue(), copy.width, copy.height


def _web_ready(image: Image.Image) -> Image.Image:
    if image.mode in ('RGB', 'RGBA'):
        return image
    has_alpha = 'A' in image.getbands() or 'transparency' in image.info
    return image.convert('RGBA' if has_alpha else 'RGB')


def placeholder_of(image: Image.Image) -> str | None:
    """A tiny blurred WebP as a ``data:`` URI, shown while the thumbnail loads."""
    body, _, _ = _webp(_web_ready(image), PLACEHOLDER_BOX, 40)
    uri = 'data:image/webp;base64,' + base64.b64encode(body).decode()
    return uri if len(uri) <= PLACEHOLDER_MAX else None


def _taken_at(image: Image.Image) -> str | None:
    try:
        exif = image.getexif()
        value = exif.get_ifd(0x8769).get(36867) or exif.get(306)
    except Exception:  # noqa: BLE001 — broken EXIF is not an error
        return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip()[:19], '%Y:%m:%d %H:%M:%S').isoformat()
    except ValueError:
        return None


def _image_previews(out: Derived, image: Image.Image, *, rendition: bool) -> None:
    """``thumb`` (+ ``preview`` when ``rendition``) and the placeholder of an opened image."""
    ready = _web_ready(image)
    body, width, height = _webp(ready, THUMB_BOX, 78)
    out.images.append(DerivedImage('thumb', body, width, height))
    if rendition:
        body, width, height = _webp(ready, PREVIEW_BOX, 82)
        out.images.append(DerivedImage('preview', body, width, height))
    out.placeholder = placeholder_of(ready)
    out.preview = 'ready'


def _open_image(data: bytes) -> Image.Image:
    """Decode an image; more than ``MAX_IMAGE_PIXELS`` → ``DecompressionBombError`` (Pillow only warns up to 2×)."""
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Image.DecompressionBombWarning as error:
            raise Image.DecompressionBombError(str(error)) from error
    return image


def _image(out: Derived, data: bytes, sniffed: str) -> None:
    try:
        image = _open_image(data)
    except Image.DecompressionBombError:
        out.preview, out.error = 'none', 'image too large'
        return
    except UnidentifiedImageError as error:
        if sniffed in READABLE_IMAGES:
            out.preview, out.error = 'failed', f'unreadable image: {error}'[:300]
        else:
            out.preview, out.error = 'none', 'image format not supported'
        return
    except (OSError, SyntaxError, ValueError) as error:
        out.preview, out.error = 'failed', f'unreadable image: {error}'[:300]
        return
    fmt = (image.format or '').upper()
    taken = _taken_at(image)
    upright = ImageOps.exif_transpose(image)
    out.meta.update(width=upright.width, height=upright.height)
    if taken:
        out.meta['taken_at'] = taken
    large = max(upright.width, upright.height) > PREVIEW_BOX
    _image_previews(out, upright, rendition=large or fmt not in WEB_FORMATS)


# --- text -----------------------------------------------------------------------------------------

_SPACES = re.compile(r'[ \t\f\v\r]+')
_BLANK_LINES = re.compile(r'\n{3,}')
_TAG = re.compile(r'<[^>]{0,2000}>')
_SCRIPT = re.compile(r'<(script|style)\b.*?</\1\s*>', re.IGNORECASE | re.DOTALL)


def clean_text(value: str) -> str:
    """No NUL / control characters (PostgreSQL text), collapsed spaces, at most two line breaks in a row."""
    value = ''.join(c for c in value.replace('\r\n', '\n') if c in '\n\t' or c >= ' ')
    value = _SPACES.sub(' ', value)
    value = '\n'.join(line.strip() for line in value.split('\n'))
    return _BLANK_LINES.sub('\n\n', value).strip()


def _decode(data: bytes) -> str:
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        try:
            return data.decode('utf-16')
        except UnicodeDecodeError:
            pass
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252', 'replace')


def xml_text(xml: str, breaks: tuple[str, ...] = ()) -> str:
    """Text of an XML / HTML fragment by regex (no parser: no entity expansion); ``breaks`` = closing tags that end
    a paragraph (``w:p``, ``a:p``, ``text:p`` …)."""
    xml = _SCRIPT.sub(' ', xml)
    for tag in breaks:
        xml = xml.replace(f'</{tag}>', '\n')
    return html.unescape(_TAG.sub(' ', xml))


def _set_text(out: Derived, value: str, max_chars: int) -> None:
    value = clean_text(value)
    if not value:
        out.index = 'none'
        return
    if len(value) > max_chars:
        value, out.truncated = value[:max_chars], True
    out.text = value
    out.meta['words'] = len(value.split())
    out.index = 'ready'


# --- PDF ------------------------------------------------------------------------------------------


def _pdf(out: Derived, data: bytes, max_chars: int) -> None:
    import pypdfium2 as pdfium

    with _PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as error:
            out.preview = out.index = 'failed'
            out.error = f'unreadable PDF: {error}'[:300]
            return
        try:
            pages = len(doc)
            out.meta['pages'] = pages
            info = doc.get_metadata_dict(skip_empty=True)
            for source, target in (('Title', 'title'), ('Author', 'author')):
                if info.get(source):
                    out.meta[target] = str(info[source])[:300]
            if pages:
                page = doc[0]
                width, height = page.get_size()
                scale = min(max(2 * THUMB_BOX / max(width, height, 1), 0.1), 4.0)
                _image_previews(out, page.render(scale=scale).to_pil(), rendition=False)
            parts: list[str] = []
            size = 0
            for index in range(min(pages, MAX_PDF_TEXT_PAGES)):
                text = doc[index].get_textpage().get_text_bounded()
                parts.append(text)
                size += len(text)
                if size > max_chars:
                    break
            _set_text(out, '\n\n'.join(parts), max_chars)
        finally:
            doc.close()


# --- Office Open XML / OpenDocument ---------------------------------------------------------------

_OOXML_TEXT = {
    'word': (
        re.compile(r'^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$'),
        ('w:p',),
    ),
    'ppt': (
        re.compile(r'^ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml$'),
        ('a:p',),
    ),
    'xl': (re.compile(r'^xl/sharedStrings\.xml$'), ('si',)),
}
_ODF_BREAKS = ('text:p', 'text:h', 'table:table-cell')
_THUMBNAILS = (
    'docProps/thumbnail.jpeg',
    'docProps/thumbnail.jpg',
    'docProps/thumbnail.png',
    'Thumbnails/thumbnail.png',
)
_NUMBER = re.compile(r'\d+')


def _xml_value(xml: str, tag: str) -> str | None:
    match = re.search(
        rf'<{re.escape(tag)}(?:\s[^>]*)?>(.*?)</{re.escape(tag)}>', xml, re.DOTALL
    )
    value = html.unescape(match.group(1)).strip() if match else ''
    return value[:300] or None


def _member_order(name: str) -> tuple[int, str]:
    numbers = _NUMBER.findall(name)
    return (int(numbers[-1]) if numbers else 0, name)


def _office(out: Derived, data: bytes, max_chars: int) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError) as error:
        out.preview = out.index = 'failed'
        out.error = f'unreadable document: {error}'[:300]
        return
    with archive:
        infos = {i.filename: i for i in archive.infolist()}
        budget = MAX_ZIP_TOTAL

        def read(name: str) -> str | None:
            nonlocal budget
            info = infos.get(name)
            if (
                info is None
                or info.file_size > MAX_ZIP_MEMBER
                or info.file_size > budget
            ):
                return None
            budget -= info.file_size
            return archive.read(info).decode('utf-8', 'replace')

        is_odf = 'content.xml' in infos and 'mimetype' in infos
        parts: list[str] = []
        if is_odf:
            content = read('content.xml')
            if content:
                parts.append(xml_text(content, _ODF_BREAKS))
            meta = read('meta.xml') or ''
            title, author = _xml_value(meta, 'dc:title'), _xml_value(meta, 'dc:creator')
            pages = re.search(r'meta:page-count="(\d+)"', meta)
            if pages:
                out.meta['pages'] = int(pages.group(1))
        else:
            for pattern, breaks in _OOXML_TEXT.values():
                for name in sorted(
                    (n for n in infos if pattern.match(n)), key=_member_order
                ):
                    xml = read(name)
                    if xml:
                        parts.append(xml_text(xml, breaks))
            core, app = read('docProps/core.xml') or '', read('docProps/app.xml') or ''
            title, author = _xml_value(core, 'dc:title'), _xml_value(core, 'dc:creator')
            for tag in ('Pages', 'Slides'):
                value = _xml_value(app, tag)
                if value and value.isdigit():
                    out.meta['pages'] = int(value)
                    break
        if title:
            out.meta['title'] = title
        if author:
            out.meta['author'] = author
        _set_text(out, '\n\n'.join(parts), max_chars)
        for name in _THUMBNAILS:
            info = infos.get(name)
            if info is None or info.file_size > MAX_ZIP_MEMBER:
                continue
            try:
                _image_previews(out, _open_image(archive.read(info)), rendition=False)
            except (
                UnidentifiedImageError,
                OSError,
                SyntaxError,
                ValueError,
                Image.DecompressionBombError,
            ):
                continue
            break


# --- entry point ----------------------------------------------------------------------------------

_OFFICE_PREFIXES = (
    'application/vnd.openxmlformats-officedocument.',
    'application/vnd.oasis.opendocument.',
)


_TEXT_SNIFFED = ('text/plain', 'text/html', 'application/xml')
_HTML_BREAKS = ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')


def derive(data: bytes, declared_mime: str, *, max_chars: int = 200_000) -> Derived:
    """Previews, text and metadata of one file version. ``declared_mime`` = the type stored for the version (from the
    name); the content decides what is generated."""
    declared = (declared_mime or '').split(';', 1)[0].strip().lower()
    out = Derived(sniffed=sniff(data))
    out.meta['sniffed'] = out.sniffed
    sniffed = out.sniffed or ''
    try:
        if sniffed.startswith('image/') and sniffed != 'image/svg+xml':
            _image(out, data, sniffed)
        elif sniffed == 'application/pdf':
            _pdf(out, data, max_chars)
        elif sniffed.startswith(_OFFICE_PREFIXES):
            _office(out, data, max_chars)
        elif sniffed in _TEXT_SNIFFED:
            text = _decode(data)
            out.meta['lines'] = text.count('\n') + 1
            if sniffed == 'text/html' or declared == 'text/html':
                text = xml_text(text, _HTML_BREAKS)
            _set_text(out, text, max_chars)
    except Exception as error:  # noqa: BLE001 — a broken file must not stop the pipeline
        out.error = f'{type(error).__name__}: {error}'[:300]
        if out.preview != 'ready':
            out.preview = 'failed'
        if out.index != 'ready':
            out.index = 'failed'
    return out
