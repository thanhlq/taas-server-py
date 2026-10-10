"""CRM contacts on the local database (taas-specs/crm/contacts/contacts-spec.md): create / list / search / detail /
change / soft delete (Crm-0201…0207), duplicate guard (Crm-0205), the account's primary contact (Crm-0208, Crm-0209),
lead sources (Crm-0212); PPM project client + contacts (Ppm-0113…0117). Development sign-in (all permissions)."""

from __future__ import annotations

import uuid

import httpx

C = '/api/v1/crm/contacts'
A = '/api/v1/crm/accounts'
P = '/api/v1/projects'


def _stamp() -> str:
    return uuid.uuid4().hex[:8]


async def _account(client: httpx.AsyncClient, name: str, **extra) -> dict:
    res = await client.post(f'{A}/', json={'name': name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def _contact(client: httpx.AsyncClient, **data) -> dict:
    res = await client.post(f'{C}/', json=data)
    assert res.status_code == 201, res.text
    return res.json()


async def test_contact_lifecycle_search_duplicates_and_delete(
    client: httpx.AsyncClient,
):
    s = _stamp()
    account = await _account(client, f'Green Tractor {s}')
    jane = await _contact(
        client,
        salutation='Ms',
        first_name='Jane',
        last_name=f'Doe{s}',
        job_title='CTO',
        account_id=account['id'],
        emails=[
            {'value': f'Jane.{s}@Tractor.io'},
            {'value': f'jd{s}@home.io', 'opt_out': True},
        ],
        phones=[{'value': '+1 555 0100', 'kind': 'mobile'}],
        addresses=[{'kind': 'primary', 'city': 'Paris', 'country': 'France'}],
        lead_source='referral',
        labels=['vip'],
    )
    assert jane['name'] == f'Jane Doe{s}' and jane['email'] == f'jane.{s}@tractor.io'
    assert (
        jane['account_name'] == f'Green Tractor {s}' and jane['phone'] == '+1 555 0100'
    )
    assert jane['owner'] and jane['emails'][1]['opt_out'] is True

    bad = await client.post(f'{C}/', json={'job_title': 'nobody'})
    assert bad.status_code == 400 and bad.json()['extra']['code'] == 'invalid_contact'
    twice = await client.post(
        f'{C}/',
        json={'first_name': 'Other', 'emails': [{'value': f'JANE.{s}@tractor.io'}]},
    )
    assert twice.status_code == 409 and twice.json()['extra'] == {
        'code': 'contact_exists',
        'contact_id': jane['id'],
    }
    lead = await client.post(
        f'{C}/', json={'last_name': 'X', 'lead_source': 'cold-call'}
    )
    assert lead.status_code == 400

    bob = await _contact(
        client, first_name='Bob', last_name=f'Lee{s}', reports_to_id=jane['id']
    )
    assert bob['reports_to_name'] == f'Jane Doe{s}'
    by_account = (await client.get(f'{C}/', params={'q': f'Green Tractor {s}'})).json()
    assert [c['id'] for c in by_account['items']] == [jane['id']]
    assert (await client.get(f'{C}/', params={'account_id': account['id']})).json()[
        'meta'
    ]['total'] == 1
    assert (await client.get(f'{C}/', params={'q': f'Lee{s}'})).json()['items'][0][
        'id'
    ] == bob['id']

    moved = await client.patch(
        f'{C}/{bob["id"]}', json={'account_id': account['id'], 'job_title': 'Buyer'}
    )
    assert moved.status_code == 200 and moved.json()['account_id'] == account['id']
    cleared = await client.patch(
        f'{C}/{bob["id"]}', json={'reports_to_id': '', 'labels': []}
    )
    assert (
        cleared.json().get('reports_to_id') is None
        and cleared.json().get('labels', []) == []
    )
    sources = (await client.get(f'{C}/lead-sources')).json()
    assert 'referral' in [x['value'] for x in sources]

    assert (await client.delete(f'{C}/{bob["id"]}')).status_code == 204
    assert (await client.get(f'{C}/{bob["id"]}')).status_code == 404
    assert bob['id'] not in [
        c['id']
        for c in (await client.get(f'{C}/', params={'q': f'Lee{s}'})).json()['items']
    ]


async def test_account_primary_contact_is_a_contact(client: httpx.AsyncClient):
    s = _stamp()
    account = await _account(
        client,
        f'JAB Funds {s}',
        primary_contact={
            'name': 'Carol Windom',
            'email': f'carol{s}@jab.io',
            'phone': '+44 1',
        },
    )
    primary = account['primary_contact']
    assert (
        primary['id']
        and primary['name'] == 'Carol Windom'
        and account['primary_contact_id'] == primary['id']
    )
    contact = (await client.get(f'{C}/{primary["id"]}')).json()
    assert (
        contact['account_id'] == account['id']
        and contact['is_primary']
        and contact['email'] == f'carol{s}@jab.io'
    )

    renamed = await client.patch(
        f'{A}/{account["id"]}',
        json={
            'primary_contact': {'name': 'Carol W. Smith', 'email': f'carol{s}@jab.io'}
        },
    )
    assert renamed.json()['primary_contact']['id'] == primary['id']
    assert (await client.get(f'{C}/{primary["id"]}')).json()['name'] == 'Carol W. Smith'

    other = await _contact(
        client, first_name='Dan', account_id=account['id'], primary_for_account=True
    )
    assert (await client.get(f'{A}/{account["id"]}')).json()[
        'primary_contact_id'
    ] == other['id']
    picked = await client.patch(
        f'{A}/{account["id"]}', json={'primary_contact_id': primary['id']}
    )
    assert picked.json()['primary_contact']['name'] == 'Carol W. Smith'
    await client.delete(f'{C}/{primary["id"]}')
    assert (await client.get(f'{A}/{account["id"]}')).json().get(
        'primary_contact'
    ) is None


async def test_project_client_and_contacts(client: httpx.AsyncClient):
    s = _stamp()
    account = await _account(client, f'AtoZ {s}')
    jane = await _contact(
        client, first_name='Jane', last_name=s, account_id=account['id']
    )
    bob = await _contact(
        client, first_name='Bob', last_name=s, account_id=account['id']
    )

    bad = await client.post(
        f'{P}/', json={'name': f'P {s}', 'client_id': str(uuid.uuid4())}
    )
    assert bad.status_code == 400 and bad.json()['extra']['code'] == 'invalid_account'
    project = await client.post(
        f'{P}/',
        json={
            'name': f'Rollout {s}',
            'client_id': account['id'],
            'contact_ids': [jane['id']],
        },
    )
    assert project.status_code == 201, project.text
    body = project.json()
    assert body['client_id'] == account['id']
    assert [(c['id'], c.get('is_default', False)) for c in body['contacts']] == [
        (jane['id'], True)
    ]

    both = await client.patch(
        f'{P}/{body["id"]}',
        json={'contact_ids': [jane['id'], bob['id']], 'default_contact_id': bob['id']},
    )
    assert [(c['name'], c.get('is_default', False)) for c in both.json()['contacts']] == [
        (f'Bob {s}', True),
        (f'Jane {s}', False),
    ]
    default = await client.patch(
        f'{P}/{body["id"]}', json={'default_contact_id': jane['id']}
    )
    assert default.json()['contacts'][0]['id'] == jane['id']
    wrong = await client.patch(
        f'{P}/{body["id"]}',
        json={'contact_ids': [bob['id']], 'default_contact_id': jane['id']},
    )
    assert wrong.status_code == 400

    projects = (await client.get(f'/api/v1/ppm/contacts/{bob["id"]}/projects')).json()
    assert [(p['id'], p.get('is_default', False)) for p in projects] == [(body['id'], False)]
    await client.delete(f'{C}/{bob["id"]}')
    assert [
        c['id'] for c in (await client.get(f'{P}/{body["id"]}')).json()['contacts']
    ] == [jane['id']]
    none = await client.patch(
        f'{P}/{body["id"]}', json={'contact_ids': [], 'clear': ['client_id']}
    )
    assert (
        none.json().get('contacts', []) == [] and none.json().get('client_id') is None
    )
