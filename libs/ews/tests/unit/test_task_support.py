"""Task helpers: UUIDv7 creation time, labels / watchers storage, PATCH semantics, time log minutes."""

from datetime import datetime
from uuid import UUID, uuid4

import db.models.ews as ews_models
from ews.ppm._time import EntryIn, _minutes
from ews.ppm.controllers._task_support import (
    apply_task_update,
    clamp_priority,
    clean_list,
    task_labels,
    task_to_response,
    task_watchers,
    uuid7_time,
)

# UUIDv7 whose 48-bit timestamp is 2026-09-27T09:47:23.996Z.
_UUID7 = UUID('01a0e243-1bdc-75f3-a0fb-5898097b5f1c')


def test_uuid7_time_reads_the_embedded_timestamp():
    assert uuid7_time(_UUID7) == datetime(2026, 9, 27, 9, 47, 23, 996000)
    assert uuid7_time(str(_UUID7)) == datetime(2026, 9, 27, 9, 47, 23, 996000)


def test_uuid7_time_ignores_other_ids():
    assert uuid7_time(uuid4()) is None
    assert uuid7_time('not-a-uuid') is None
    assert uuid7_time(None) is None


def test_clean_list_trims_and_deduplicates_in_order():
    assert clean_list([' ui ', 'api', 'ui', '', '  ']) == ['ui', 'api']
    assert clean_list(None) == []


def test_clamp_priority():
    assert clamp_priority(None) is None
    assert clamp_priority(-3) == 0
    assert clamp_priority(3) == 3
    assert clamp_priority(9) == 5


def test_apply_task_update_sets_fields_labels_watchers_and_html():
    task = ews_models.Task(name='Old', tags={'other': 1})
    list_id = '01a0e243-1b90-7ac3-a0ca-b04e73a50af8'
    apply_task_update(
        task,
        {
            'name': 'New',
            'user_id': 'jane@example.com',
            'task_list_id': list_id,
            'priority': 7,
            'labels': ['ui', ' ui', 'api'],
            'watchers': ['me@example.com'],
            'description': 'Hello',
            'description_html': '<p><b>Hello</b></p>',
        },
    )
    assert task.name == 'New'
    assert task.user_id == 'jane@example.com'
    assert task.task_list_id == UUID(list_id)
    assert task.priority == 5
    assert task_labels(task) == ['ui', 'api']
    assert task.tags['other'] == 1
    assert task_watchers(task) == ['me@example.com']
    assert task.html_text == '<p><b>Hello</b></p>'
    assert task.content_type == 'html'


def test_apply_task_update_clears_only_clearable_fields():
    task = ews_models.Task(
        name='Keep',
        user_id='jane@example.com',
        due_date=datetime(2026, 10, 1),
        html_text='<p>x</p>',
        content_type='html',
    )
    apply_task_update(
        task, {'clear': ['user_id', 'due_date', 'description_html', 'name']}
    )
    assert task.user_id is None
    assert task.due_date is None
    assert task.html_text is None
    assert task.name == 'Keep'


def test_task_to_response_derives_created_at_and_lists():
    task = ews_models.Task(
        id=_UUID7,
        name='T',
        tags={'labels': ['a']},
        followers={'users': ['me@example.com']},
        actual_minutes=None,
    )
    response = task_to_response(task)
    assert response.labels == ['a']
    assert response.watchers == ['me@example.com']
    assert response.actual_minutes == 0
    assert response.created_at == datetime(2026, 9, 27, 9, 47, 23, 996000)


def test_entry_minutes_prefer_explicit_minutes_then_the_time_range():
    """Time entries (``ews.ppm._time``): minutes win; a reversed range gives ≤ 0 (refused by validation)."""
    assert _minutes(EntryIn(minutes=45)) == 45
    assert (
        _minutes(
            EntryIn(
                start_time=datetime(2026, 9, 27, 9, 0),
                end_time=datetime(2026, 9, 27, 17, 0),
            )
        )
        == 480
    )
    assert (
        _minutes(
            EntryIn(
                start_time=datetime(2026, 9, 27, 17, 0),
                end_time=datetime(2026, 9, 27, 9, 0),
            )
        )
        <= 0
    )
    assert _minutes(EntryIn()) == 0
