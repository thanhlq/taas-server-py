"""CRM contacts, pure rules (taas-specs/crm/contacts/contacts-spec.md): e-mails (Crm-0204: one primary, flags,
duplicates, format), phones (kinds, one primary), addresses (primary · other), labels, display name."""

from __future__ import annotations

import pytest
from foundation.exceptions import ClientException

from ews.crm import _contacts as contacts


def test_emails_one_primary_lower_case_and_deduplicated():
    out = contacts.clean_emails(
        [
            {'value': ' Jane@Acme.io '},
            {'value': 'jane@acme.io', 'primary': True},
            {'value': 'j.doe@home.io', 'primary': True, 'opt_out': True},
            '',
        ]
    )
    assert [e['value'] for e in out] == ['jane@acme.io', 'j.doe@home.io']
    assert [e['primary'] for e in out] == [False, True]
    assert out[1]['opt_out'] is True and out[0]['invalid'] is False
    assert contacts.primary_of(out) == 'j.doe@home.io'
    assert contacts.clean_emails([{'value': 'a@b.io'}])[0]['primary'] is True
    with pytest.raises(ClientException) as error:
        contacts.clean_emails([{'value': 'nope'}])
    assert error.value.extra == {'code': 'invalid_contact', 'field': 'emails[0]'}


def test_phones_kinds_and_primary():
    out = contacts.clean_phones(
        [
            {'value': '+1 555 0100'},
            {'value': '(087) 165-0368', 'kind': 'mobile', 'primary': True},
        ]
    )
    assert [(p['kind'], p['primary']) for p in out] == [
        ('office', False),
        ('mobile', True),
    ]
    with pytest.raises(ClientException):
        contacts.clean_phones([{'value': 'call me'}])
    with pytest.raises(ClientException):
        contacts.clean_phones([{'value': '123', 'kind': 'fax'}])


def test_addresses_labels_and_names():
    out = contacts.clean_addresses(
        [
            {'kind': 'primary', 'city': ' Paris ', 'country': 'France'},
            {'kind': 'other', 'street': ''},
        ]
    )
    assert out == [{'kind': 'primary', 'city': 'Paris', 'country': 'France'}]
    with pytest.raises(ClientException):
        contacts.clean_addresses(
            [{'kind': 'primary', 'city': 'A'}, {'kind': 'primary', 'city': 'B'}]
        )
    assert contacts.clean_labels([' vip ', 'vip', '', 'board']) == ['vip', 'board']
    assert contacts.display_name('Jane', 'Doe', 'j@acme.io') == 'Jane Doe'
    assert contacts.display_name(None, None, 'j@acme.io') == 'j@acme.io'
