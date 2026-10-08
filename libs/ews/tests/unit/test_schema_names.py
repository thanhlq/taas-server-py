"""Wire types (msgspec structs) have unique class names across the EWS API.

The OpenAPI document names components by class name and keeps the first class it meets: two apps with a
``PageOut`` each silently share one schema (and the generated ``types.gen.ts``). Prefix app types
(``KbPageOut``, ``BlogPostOut``, ``FileNodeOut``) or reuse the shared ones (``ews.access.schemas``).
"""

import importlib
import inspect
import pkgutil
from collections import defaultdict

import ews
import msgspec

# Modules that cannot be imported on their own (pre-existing); they define no API types.
_BROKEN = {'ews.ppm.repos._project_wiki_repo'}


def _struct_classes() -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for info in pkgutil.walk_packages(ews.__path__, 'ews.'):
        if info.name in _BROKEN:
            continue
        module = importlib.import_module(info.name)
        for obj in vars(module).values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, msgspec.Struct)
                and obj.__module__.startswith('ews.')
            ):
                found[obj.__name__].add(f'{obj.__module__}.{obj.__qualname__}')
    return found


def test_wire_type_names_are_unique():
    duplicates = {
        name: sorted(where)
        for name, where in _struct_classes().items()
        if len(where) > 1
    }
    assert duplicates == {}, (
        f'rename (prefix with the app) or reuse a shared type: {duplicates}'
    )
