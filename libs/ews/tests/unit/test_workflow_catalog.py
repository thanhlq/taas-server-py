"""Workflow template catalog integrity + project process rules."""

import json
from pathlib import Path

import db.models.ews as ews_models
import pytest
from ews.ppm import _workflow_service as wfs
from ews.ppm import workflow_catalog as catalog
from foundation.exceptions import ClientException

_I18N = Path(catalog.__file__).parent / 'data' / 'i18n'


def _paths(value, prefix=''):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _paths(v, f'{prefix}/{k}')
    else:
        yield prefix


def test_every_template_is_consistent():
    ids = catalog.template_ids()
    assert len(ids) == 49
    for tid in ids:
        t = catalog.get_template(tid)
        allowed = set(t['allowed_stage_types'])
        assert all(catalog.is_stage_type(k) for k in allowed), tid
        assert {'blocked', 'on_hold', 'cancelled'} <= allowed, tid
        stage_types = [s['stage_type'] for s in t['stages']]
        assert set(stage_types) <= allowed, tid
        assert {s['stage_type'] for s in t['stage_suggestions']} <= allowed, tid
        assert sum(1 for s in t['stages'] if s.get('is_default')) == 1, tid
        assert any(catalog.stage_type_info(k).band == 'done' for k in stage_types), tid
        keys = [w['key'] for w in t['work_item_types']]
        assert len(keys) == len(set(keys)), tid


def test_categories_cover_every_template_once():
    listed = [t['id'] for c in catalog.list_categories() for t in c['templates']]
    assert sorted(listed) == sorted(catalog.template_ids())
    assert [c['id'] for c in catalog.list_categories()][0] == 'universal'


def test_stage_type_bands_drive_progress():
    assert {
        'done',
        'completed',
        'deployed',
        'closed',
        'archived',
    } == catalog.done_stage_types()
    assert {'cancelled', 'rejected'} == catalog.excluded_stage_types()
    assert catalog.stage_type_info('review').band == 'review'
    assert catalog.stage_type_tone('unknown') == 'gray'


def test_translations_mirror_english():
    english = set(_paths(json.loads((_I18N / 'en.json').read_text())))
    for path in _I18N.glob('*.json'):
        assert set(_paths(json.loads(path.read_text()))) >= english - {
            '/labels/main_workflow'
        }, path.name


@pytest.mark.parametrize(
    ('tag', 'expected'),
    [
        (None, 'en'),
        ('xx', 'en'),
        ('EN-us', 'en'),
        ('zh-HK', 'zh-TW'),
        ('zh', 'zh-CN'),
        ('pt-PT', 'pt-BR'),
    ],
)
def test_resolve_locale(tag, expected):
    if expected != 'en' and expected not in catalog.available_locales():
        pytest.skip(f'{expected} catalog not present')
    assert catalog.resolve_locale(tag) == expected


def test_seed_without_template_is_unconstrained():
    seed = wfs.seed_process(None, None)
    assert seed.process.template_id is None
    assert seed.process.allowed_stage_types is None
    assert not seed.process.work_item_types_locked
    assert seed.process.allows_stage_type('deployed')
    assert seed.process.check_work_item_type('anything') == 'anything'
    assert [s['stage_type'] for s in seed.stages] == [
        'new',
        'in_progress',
        'review',
        'done',
    ]


def test_seed_with_template_is_sticky_and_constrained():
    seed = wfs.seed_process('construction.design', None)
    process = seed.process
    assert process.template_id == 'construction.design'
    assert process.work_item_types_locked
    assert seed.workflow_name == 'Construction Design'
    with pytest.raises(ClientException):
        process.check_stage_type('deployed')
    with pytest.raises(ClientException):
        process.check_stage_type('not-a-type')
    with pytest.raises(ClientException):
        process.check_work_item_type('bug')
    assert process.check_stage_type('review') == 'review'
    assert process.default_work_item_type() == 'task'


def test_blank_template_keeps_work_item_types_open():
    seed = wfs.seed_process('custom.workflow', None)
    assert not seed.process.work_item_types_locked
    assert seed.process.work_item_types  # defaults from the universal template


def test_unknown_template_is_rejected():
    with pytest.raises(ClientException):
        wfs.seed_process('nope.nope', None)


def test_process_round_trips_through_the_project():
    project = ews_models.Project(workflow={'stages': [{'stage_type': 'backlog'}]})
    assert not wfs.ProjectProcess.of(project).initialized
    wfs.seed_process('technology.scrum', None).process.save(project)
    process = wfs.ProjectProcess.of(project)
    assert process.template_id == 'technology.scrum'
    assert 'stages' not in project.workflow
    assert process.initialized


def test_checked_work_item_types():
    project = ews_models.Project()
    open_process = wfs.seed_process(None, None).process
    assert wfs.checked_work_item_types(
        open_process, [{'key': 'x', 'term': ' X '}], project
    ) == [{'key': 'x', 'term': 'X'}]
    with pytest.raises(ClientException):
        wfs.checked_work_item_types(
            open_process,
            [{'key': 'x', 'term': 'X'}, {'key': 'x', 'term': 'Y'}],
            project,
        )
    with pytest.raises(ClientException):
        wfs.checked_work_item_types(open_process, [], project)
    locked = wfs.seed_process('technology.scrum', None).process
    renamed = wfs.checked_work_item_types(
        locked, [{'key': 'bug', 'term': 'Defect'}], project
    )
    assert renamed[0]['term'] == 'Defect' and renamed[0]['icon'] == 'bug'
    with pytest.raises(ClientException):
        wfs.checked_work_item_types(
            locked, [{'key': 'custom', 'term': 'Custom'}], project
        )


def test_visibility_by_privacy():
    project = ews_models.Project(user_id='owner@example.com')
    shared = ews_models.Workflow(privacy='all')
    private = ews_models.Workflow(privacy='assigned')
    assert wfs.visible_to(shared, [], 'someone@example.com', project)
    assert not wfs.visible_to(
        private, ['a@example.com'], 'someone@example.com', project
    )
    assert wfs.visible_to(private, ['a@example.com'], 'a@example.com', project)
    assert wfs.visible_to(private, [], 'owner@example.com', project)
    assert wfs.visible_to(private, [], None, project)
