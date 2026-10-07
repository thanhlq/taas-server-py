"""Media file checks and processing (Site-0403): type from magic bytes (never the client's type or the
extension), EXIF location stripped from photos, SVG sanitized, responsive WebP / AVIF variants.

Pure functions on bytes: no I/O, unit-tested in ``tests/unit/test_media_processing.py``.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError, features

type MediaKind = Literal['image', 'video', 'audio']

Image.MAX_IMAGE_PIXELS = 80_000_000  # decompression-bomb guard (~ 9000 x 9000)

_GPS_IFD = 0x8825


class MediaRejected(ValueError):
    """The file is not an accepted media type, or is malformed / unsafe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SniffedType:
    kind: MediaKind
    mime: str
    ext: str


@dataclass(slots=True)
class ProcessedVariant:
    name: str
    """``w640.webp`` …"""
    body: bytes
    width: int
    height: int
    format: str
    mime: str


@dataclass(slots=True)
class ProcessedMedia:
    kind: MediaKind
    mime: str
    ext: str
    body: bytes
    """The stored original (GPS stripped / SVG sanitized)."""
    width: int | None = None
    height: int | None = None
    variants: list[ProcessedVariant] = field(default_factory=list)


# --- type detection -------------------------------------------------------------------------------

_IMAGE_SIGNATURES: list[tuple[bytes, int, str, str]] = [
    (b'\xff\xd8\xff', 0, 'image/jpeg', 'jpg'),
    (b'\x89PNG\r\n\x1a\n', 0, 'image/png', 'png'),
    (b'GIF87a', 0, 'image/gif', 'gif'),
    (b'GIF89a', 0, 'image/gif', 'gif'),
]
_FTYP_IMAGE = {b'avif': ('image/avif', 'avif'), b'avis': ('image/avif', 'avif')}
_FTYP_AUDIO = {b'M4A ': ('audio/mp4', 'm4a'), b'M4B ': ('audio/mp4', 'm4a')}
_FTYP_VIDEO_QT = {b'qt  ': ('video/quicktime', 'mov')}


def _looks_like_svg(head: bytes) -> bool:
    text = head[:2048].lstrip(b'\xef\xbb\xbf').lstrip().lower()
    return text.startswith(b'<svg') or (text.startswith(b'<?xml') and b'<svg' in text) or (
        text.startswith(b'<!--') and b'<svg' in text
    )


def sniff(data: bytes) -> SniffedType:
    """Media type from the content's magic bytes. Documents and anything else → ``MediaRejected``."""
    if len(data) < 12:
        raise MediaRejected('unsupported_type', 'file is empty or too small')
    for sig, offset, mime, ext in _IMAGE_SIGNATURES:
        if data[offset : offset + len(sig)] == sig:
            return SniffedType('image', mime, ext)
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return SniffedType('image', 'image/webp', 'webp')
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return SniffedType('audio', 'audio/wav', 'wav')
    if data[4:8] == b'ftyp':
        brand = data[8:12]
        if brand in _FTYP_IMAGE:
            return SniffedType('image', *_FTYP_IMAGE[brand])
        if brand in _FTYP_AUDIO:
            return SniffedType('audio', *_FTYP_AUDIO[brand])
        if brand in _FTYP_VIDEO_QT:
            return SniffedType('video', *_FTYP_VIDEO_QT[brand])
        return SniffedType('video', 'video/mp4', 'mp4')
    if data[:4] == b'\x1a\x45\xdf\xa3':
        return SniffedType('video', 'video/webm', 'webm')
    if data[:4] == b'OggS':
        return SniffedType('audio', 'audio/ogg', 'ogg')
    if data[:3] == b'ID3' or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return SniffedType('audio', 'audio/mpeg', 'mp3')
    if data[:4] == b'fLaC':
        return SniffedType('audio', 'audio/flac', 'flac')
    if _looks_like_svg(data):
        return SniffedType('image', 'image/svg+xml', 'svg')
    if data[:5] == b'%PDF-' or data[:4] == b'PK\x03\x04' or data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        raise MediaRejected(
            'document_not_media', 'documents (PDF, office files, archives) belong to the Documents app'
        )
    raise MediaRejected('unsupported_type', 'only images, videos and audio files are accepted')


# --- SVG ------------------------------------------------------------------------------------------

_SVG_NS = 'http://www.w3.org/2000/svg'
_XLINK = '{http://www.w3.org/1999/xlink}href'
_FORBIDDEN_TAGS = {'script', 'foreignobject', 'iframe', 'embed', 'object', 'audio', 'video', 'handler', 'listener'}
_URL_IN_STYLE = re.compile(r'url\s*\(\s*["\']?\s*(?!#)', re.IGNORECASE)
_IMPORT_IN_STYLE = re.compile(r'@import', re.IGNORECASE)
_SAFE_HREF = re.compile(r'^(#|data:image/(png|jpeg|gif|webp);base64,)', re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1].lower()


def sanitize_svg(data: bytes) -> tuple[bytes, int | None, int | None]:
    """Remove scripts, event handlers, external references and foreign content; return the clean SVG
    and its intrinsic size (from ``width`` / ``height`` or the ``viewBox``)."""
    head = data[:4096].lower()
    if b'<!doctype' in head or b'<!entity' in data.lower():
        raise MediaRejected('unsafe_svg', 'SVG with DOCTYPE / entities is not accepted')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise MediaRejected('invalid_file', f'invalid SVG: {error}') from error
    if _local(root.tag) != 'svg':
        raise MediaRejected('invalid_file', 'not an SVG document')

    def clean(element: ET.Element) -> None:
        for child in list(element):
            if _local(child.tag) in _FORBIDDEN_TAGS:
                element.remove(child)
                continue
            if _local(child.tag) == 'style' and child.text:
                child.text = _IMPORT_IN_STYLE.sub('', _URL_IN_STYLE.sub('url(#', child.text))
            clean(child)
        for attr in list(element.attrib):
            name = _local(attr)
            value = element.attrib[attr]
            if name.startswith('on'):
                del element.attrib[attr]
            elif (attr == _XLINK or name == 'href') and not _SAFE_HREF.match(value.strip()):
                del element.attrib[attr]
            elif name == 'style' and (_URL_IN_STYLE.search(value) or 'expression' in value.lower()):
                del element.attrib[attr]
            elif 'javascript:' in value.lower().replace(' ', ''):
                del element.attrib[attr]

    clean(root)
    ET.register_namespace('', _SVG_NS)
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    out = ET.tostring(root, encoding='utf-8', xml_declaration=False)
    return out, *_svg_size(root)


def _svg_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r'^\s*([0-9.]+)\s*(px)?\s*$', value)
    return round(float(match.group(1))) if match else None


def _svg_size(root: ET.Element) -> tuple[int | None, int | None]:
    width, height = _svg_number(root.get('width')), _svg_number(root.get('height'))
    if width and height:
        return width, height
    box = (root.get('viewBox') or '').replace(',', ' ').split()
    if len(box) == 4:
        try:
            return round(float(box[2])), round(float(box[3]))
        except ValueError:
            return None, None
    return None, None


# --- raster images --------------------------------------------------------------------------------

DEFAULT_WIDTHS: tuple[int, ...] = (320, 640, 1280, 1920)


def _strip_location(image: Image.Image, original: bytes, fmt: str) -> bytes:
    """Remove the EXIF GPS block (keep the rest, e.g. orientation, copyright); bytes unchanged when the
    photo carries no location."""
    exif = image.getexif()
    if _GPS_IFD not in exif:
        return original
    del exif[_GPS_IFD]
    out = io.BytesIO()
    if fmt == 'JPEG':
        image.save(out, 'JPEG', exif=exif.tobytes(), quality='keep', icc_profile=image.info.get('icc_profile'))
    else:
        image.save(out, fmt, exif=exif.tobytes())
    return out.getvalue()


def _variant(image: Image.Image, width: int, fmt: str) -> ProcessedVariant:
    copy = image.copy()
    copy.thumbnail((width, width * 4), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if fmt == 'avif':
        copy.save(out, 'AVIF', quality=60)
    else:
        copy.save(out, 'WEBP', quality=80, method=4)
    return ProcessedVariant(
        name=f'w{width}.{fmt}', body=out.getvalue(), width=copy.width, height=copy.height, format=fmt, mime=f'image/{fmt}'
    )


def process_image(data: bytes, sniffed: SniffedType, widths: tuple[int, ...] = DEFAULT_WIDTHS, avif: bool = True) -> ProcessedMedia:
    """Validate a raster image, strip its location, build WebP (and AVIF) variants no wider than the
    original. Animated GIF / WebP keep their original only."""
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise MediaRejected('invalid_file', f'unreadable image: {error}') from error
    fmt = (image.format or '').upper()
    body = _strip_location(image, data, fmt) if fmt in ('JPEG', 'PNG', 'WEBP') else data
    upright = ImageOps.exif_transpose(image)
    width, height = upright.size
    result = ProcessedMedia(kind='image', mime=sniffed.mime, ext=sniffed.ext, body=body, width=width, height=height)
    if getattr(image, 'is_animated', False):
        return result
    if upright.mode not in ('RGB', 'RGBA'):
        upright = upright.convert('RGBA' if 'A' in upright.getbands() or 'transparency' in upright.info else 'RGB')
    use_avif = avif and features.check('avif')
    sizes = [w for w in widths if w < width] or [width]
    if width not in sizes and width <= max(widths):
        sizes.append(width)
    for w in sorted(set(sizes)):
        result.variants.append(_variant(upright, w, 'webp'))
        if use_avif:
            result.variants.append(_variant(upright, w, 'avif'))
    return result


def process_media(data: bytes, widths: tuple[int, ...] = DEFAULT_WIDTHS, avif: bool = True) -> ProcessedMedia:
    """Sniff and process an uploaded file (raises ``MediaRejected``)."""
    sniffed = sniff(data)
    if sniffed.mime == 'image/svg+xml':
        clean, width, height = sanitize_svg(data)
        return ProcessedMedia(kind='image', mime=sniffed.mime, ext='svg', body=clean, width=width, height=height)
    if sniffed.kind == 'image':
        return process_image(data, sniffed, widths, avif)
    return ProcessedMedia(kind=sniffed.kind, mime=sniffed.mime, ext=sniffed.ext, body=data)
