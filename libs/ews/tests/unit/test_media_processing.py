"""Media checks and processing (Site-0403): magic bytes, GPS strip, SVG sanitizing, variants."""

from __future__ import annotations

import io

import pytest
from ews.media._processing import MediaRejected, process_media, sanitize_svg, sniff
from PIL import Image


def _jpeg_with_gps() -> bytes:
    image = Image.new('RGB', (640, 480), 'green')
    exif = Image.Exif()
    exif[0x0112] = 1  # orientation
    exif[0x8825] = {1: 'N', 2: (48.0, 51.0, 29.0)}  # GPS IFD
    out = io.BytesIO()
    image.save(out, 'JPEG', exif=exif.tobytes())
    return out.getvalue()


@pytest.mark.parametrize(
    ('head', 'kind', 'mime'),
    [
        (b'\xff\xd8\xff\xe0' + b'\0' * 20, 'image', 'image/jpeg'),
        (b'\x89PNG\r\n\x1a\n' + b'\0' * 20, 'image', 'image/png'),
        (b'RIFF\0\0\0\0WEBPVP8 ' + b'\0' * 8, 'image', 'image/webp'),
        (b'\0\0\0\x18ftypisom' + b'\0' * 12, 'video', 'video/mp4'),
        (b'\0\0\0\x18ftypM4A ' + b'\0' * 12, 'audio', 'audio/mp4'),
        (b'\x1a\x45\xdf\xa3' + b'\0' * 20, 'video', 'video/webm'),
        (b'ID3\x04' + b'\0' * 20, 'audio', 'audio/mpeg'),
        (b'OggS' + b'\0' * 20, 'audio', 'audio/ogg'),
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'image', 'image/svg+xml'),
    ],
)
def test_sniff_by_magic_bytes(head: bytes, kind: str, mime: str):
    sniffed = sniff(head)
    assert (sniffed.kind, sniffed.mime) == (kind, mime)


def test_documents_are_not_media():
    with pytest.raises(MediaRejected) as error:
        sniff(b'%PDF-1.7\n' + b'0' * 20)
    assert error.value.code == 'document_not_media'
    with pytest.raises(MediaRejected):
        sniff(b'just some plain text file')


def test_gps_is_stripped_and_variants_are_built():
    data = _jpeg_with_gps()
    assert 0x8825 in Image.open(io.BytesIO(data)).getexif()
    processed = process_media(data, widths=(320, 1280), avif=False)
    assert 0x8825 not in Image.open(io.BytesIO(processed.body)).getexif()
    assert (processed.width, processed.height) == (640, 480)
    assert [v.name for v in processed.variants] == ['w320.webp', 'w640.webp']
    assert all(v.width <= 640 for v in processed.variants)


def test_svg_scripts_handlers_and_external_refs_are_removed():
    clean, width, height = sanitize_svg(
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="24" height="12" '
        b'onclick="x()"><script>evil()</script><a href="javascript:evil()"><text>hi</text></a>'
        b'<image xlink:href="https://tracker.example/p.png"/><use href="#ok"/><foreignObject/></svg>'
    )
    text = clean.decode()
    assert (width, height) == (24, 12)
    for bad in ('script', 'onclick', 'javascript', 'tracker.example', 'foreignObject'):
        assert bad not in text
    assert 'href="#ok"' in text


def test_svg_with_entities_is_refused():
    with pytest.raises(MediaRejected):
        sanitize_svg(b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>')
