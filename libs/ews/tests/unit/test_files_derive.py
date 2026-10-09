"""Derived data of file versions (``ews.files._derive``, taas-specs/files File-0302 / File-0400 / File-0601): type
sniffing, image variants + placeholder, PDF thumbnail + text, Office / OpenDocument text + embedded thumbnail, text
decoding, hostile input."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from ews.files._derive import (
    PLACEHOLDER_MAX,
    PREVIEW_BOX,
    THUMB_BOX,
    clean_text,
    derive,
    sniff,
    xml_text,
)


def _image(fmt: str, size: tuple[int, int] = (64, 48), color: str = 'navy') -> bytes:
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, fmt)
    return out.getvalue()


def text_pdf(words: str) -> bytes:
    """A one-page PDF with ``words`` in Helvetica (hand-written objects + xref)."""
    stream = f'BT /F1 24 Tf 72 720 Td ({words}) Tj ET'.encode()
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % number + body + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    for offset in offsets:
        out.write(b'%010d 00000 n \n' % offset)
    out.write(
        b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
        % (len(objects) + 1, xref)
    )
    return out.getvalue()


def docx(
    paragraphs: list[str], *, thumbnail: bytes | None = None, title: str = 'Offer'
) -> bytes:
    body = ''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr(
            'word/document.xml', f'<w:document><w:body>{body}</w:body></w:document>'
        )
        archive.writestr(
            'docProps/core.xml',
            f'<cp:coreProperties><dc:title>{title}</dc:title><dc:creator>Ann</dc:creator></cp:coreProperties>',
        )
        archive.writestr(
            'docProps/app.xml', '<Properties><Pages>3</Pages></Properties>'
        )
        if thumbnail:
            archive.writestr('docProps/thumbnail.jpeg', thumbnail)
    return out.getvalue()


# --- sniffing (the content decides, never the name) -----------------------------------------------


@pytest.mark.parametrize(
    ('data', 'expected'),
    [
        (b'%PDF-1.7\n...', 'application/pdf'),
        (b'\x89PNG\r\n\x1a\n' + b'0' * 8, 'image/png'),
        (b'\xff\xd8\xff\xe0' + b'0' * 8, 'image/jpeg'),
        (b'RIFF1234WEBPVP8 ', 'image/webp'),
        (b'\x00\x00\x00\x18ftypavif' + b'0' * 8, 'image/avif'),
        (b'\x00\x00\x00\x18ftypisom' + b'0' * 8, 'video/mp4'),
        (
            b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>',
            'image/svg+xml',
        ),
        (b'<!DOCTYPE html><html><body>hi</body></html>', 'text/html'),
        (b'name;amount\nacme;12\n', 'text/plain'),
        ('café crème'.encode('cp1252'), 'text/plain'),
        ('﻿hello'.encode('utf-16'), 'text/plain'),
        (b'\x00\x01\x02\x03binary\x00', None),
    ],
)
def test_file_0601_type_is_sniffed_from_the_content(data: bytes, expected: str | None):
    assert sniff(data) == expected


def test_file_0601_zip_containers_are_told_apart():
    assert (
        sniff(docx(['x']))
        == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    odt = io.BytesIO()
    with zipfile.ZipFile(odt, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr('content.xml', '<office:document-content/>')
    assert sniff(odt.getvalue()) == 'application/vnd.oasis.opendocument.text'
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, 'w') as archive:
        archive.writestr('a.txt', 'x')
    assert sniff(plain.getvalue()) == 'application/zip'


def test_file_0601_a_disguised_file_gets_no_image_preview():
    out = derive(b'<html><script>alert(1)</script>hello</html>', 'image/png')
    assert out.sniffed == 'text/html' and out.images == [] and out.preview == 'none'
    assert out.text == 'hello'  # indexed as text, script removed


# --- images ---------------------------------------------------------------------------------------


def test_file_0302_large_photo_gets_thumb_preview_and_placeholder():
    out = derive(_image('JPEG', (3000, 2000)), 'image/jpeg')
    variants = {i.variant: i for i in out.images}
    assert out.preview == 'ready' and out.index == 'none'
    assert (variants['thumb'].width, variants['thumb'].height) == (THUMB_BOX, 320)
    assert (variants['preview'].width, variants['preview'].height) == (
        PREVIEW_BOX,
        1280,
    )
    assert all(i.mime == 'image/webp' and i.body[8:12] == b'WEBP' for i in out.images)
    assert out.placeholder and out.placeholder.startswith('data:image/webp;base64,')
    assert len(out.placeholder) <= PLACEHOLDER_MAX
    assert out.meta == {'sniffed': 'image/jpeg', 'width': 3000, 'height': 2000}


def test_file_0302_small_web_image_needs_no_rendition_but_bmp_does():
    assert [i.variant for i in derive(_image('PNG'), 'image/png').images] == ['thumb']
    assert [i.variant for i in derive(_image('BMP'), 'image/bmp').images] == [
        'thumb',
        'preview',
    ]


def test_file_0302_exif_orientation_and_date_are_read():
    image = Image.new('RGB', (40, 20), 'red')
    exif = image.getexif()
    exif[0x0112] = 6  # rotated 90° clockwise
    exif.get_ifd(0x8769)[36867] = '2026:05:01 09:30:00'
    out = io.BytesIO()
    image.save(out, 'JPEG', exif=exif.tobytes())
    derived = derive(out.getvalue(), 'image/jpeg')
    assert (derived.meta['width'], derived.meta['height']) == (20, 40)
    assert derived.meta['taken_at'] == '2026-05-01T09:30:00'


def test_file_0601_broken_and_oversized_images_do_not_raise():
    broken = derive(b'\x89PNG\r\n\x1a\n' + b'\x00' * 40, 'image/png')
    assert broken.preview == 'failed' and broken.error
    bomb = Image.new('1', (12000, 12000))
    out = io.BytesIO()
    bomb.save(out, 'PNG')
    big = derive(out.getvalue(), 'image/png')
    assert big.preview == 'none' and big.error == 'image too large'


# --- PDF, Office, text ----------------------------------------------------------------------------


def test_file_0400_pdf_text_pages_and_thumbnail():
    out = derive(text_pdf('Quarterly invoice ACME zebra'), 'application/pdf')
    assert out.preview == 'ready' and out.index == 'ready'
    assert out.text == 'Quarterly invoice ACME zebra'
    assert out.meta['pages'] == 1 and out.meta['words'] == 4
    thumb = out.images[0]
    assert thumb.variant == 'thumb' and max(thumb.width, thumb.height) == THUMB_BOX


def test_file_0601_unreadable_pdf_is_failed_not_raised():
    out = derive(b'%PDF-1.4\nnot really a pdf', 'application/pdf')
    assert out.preview == 'failed' and out.index == 'failed' and out.error


def test_file_0400_office_text_metadata_and_embedded_thumbnail():
    out = derive(
        docx(
            ['Hello &amp; welcome', 'Contract pelican'],
            thumbnail=_image('JPEG', (200, 280)),
        ),
        'application/msword',
    )
    assert out.text == 'Hello & welcome\nContract pelican'
    assert (
        out.meta['title'] == 'Offer'
        and out.meta['author'] == 'Ann'
        and out.meta['pages'] == 3
    )
    assert out.preview == 'ready' and [i.variant for i in out.images] == ['thumb']
    no_cover = derive(docx(['only text']), 'application/msword')
    assert no_cover.preview == 'none' and no_cover.index == 'ready'


def test_file_0400_opendocument_text():
    odt = io.BytesIO()
    with zipfile.ZipFile(odt, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr(
            'content.xml',
            '<office:text><text:h>Title</text:h><text:p>First line</text:p></office:text>',
        )
        archive.writestr(
            'meta.xml',
            '<meta><dc:title>Notes</dc:title><meta:document-statistic meta:page-count="2"/></meta>',
        )
    out = derive(odt.getvalue(), 'application/octet-stream')
    assert out.text == 'Title\nFirst line'
    assert out.meta['title'] == 'Notes' and out.meta['pages'] == 2


def test_file_0400_text_is_decoded_cleaned_and_capped():
    out = derive('Ünïcode line\r\n\r\n\r\n\r\nsecond\tline \x07'.encode(), 'text/plain')
    assert out.text == 'Ünïcode line\n\nsecond line'
    assert out.meta['lines'] == 5
    latin = derive('Prix: 12 € – café'.encode('cp1252'), 'text/csv')
    assert latin.text == 'Prix: 12 € – café'
    long = derive(('word ' * 1000).encode(), 'text/plain', max_chars=100)
    assert long.truncated and len(long.text or '') == 100
    assert derive(b'   \n  ', 'text/plain').index == 'none'


def test_file_0400_unknown_binaries_get_nothing():
    out = derive(b'\x00\x01\x02\x03' * 100, 'application/octet-stream')
    assert (out.preview, out.index, out.images, out.text) == ('none', 'none', [], None)


def test_xml_text_never_expands_entities():
    bomb = '<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;">]><p>&b;</p>'
    assert 'aaaaaaaaaa' not in xml_text(bomb)
    assert clean_text('a\x00b') == 'ab'
