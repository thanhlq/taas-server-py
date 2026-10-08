"""Trees with a materialized path (``/<root id>/<child id>/``): folders of a drive, pages of a space.

Rows store ``parent_id``, ``path`` (ids of the ancestors and itself, ``/``-wrapped) and ``depth``
(0 = top level). Subtree = ``path LIKE '<node path>%'`` — one indexed query, no recursion.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from foundation.exceptions import ClientException
from sqlalchemy import func, literal, update
from sqlalchemy.ext.asyncio import AsyncSession


def child_path(parent_path: str | None, node_id: UUID | str) -> str:
    """Path of a node under ``parent_path`` (``None`` = top level)."""
    return f'{parent_path or "/"}{node_id}/'


def depth_of(path: str) -> int:
    return path.strip('/').count('/')


def ancestor_ids(path: str) -> list[UUID]:
    """Ids of the ancestors (top first), excluding the node itself."""
    return [UUID(part) for part in path.strip('/').split('/')[:-1] if part]


def check_move(
    node_path: str,
    new_parent_path: str | None,
    *,
    max_depth: int | None = None,
    subtree_height: int = 0,
) -> None:
    """400 when a node would move into itself / its subtree, or the tree would get deeper than ``max_depth``
    levels (``subtree_height`` = levels below the node)."""
    if new_parent_path and new_parent_path.startswith(node_path):
        raise ClientException(detail='cannot move an item into itself')
    if max_depth is not None:
        new_depth = depth_of(new_parent_path) + 1 if new_parent_path else 0
        if new_depth + subtree_height >= max_depth:
            raise ClientException(detail=f'the tree is limited to {max_depth} levels')


async def move_subtree(
    session: AsyncSession, model: Any, node: Any, new_parent: Any | None
) -> None:
    """Move ``node`` (and its subtree) under ``new_parent`` (``None`` = top level): rewrites ``path`` /
    ``depth`` of every descendant in one statement. ``model`` has ``path``, ``depth``, ``parent_id`` columns;
    callers scope the statement by passing rows of one tree only (paths are unique ids)."""
    old_path: str = node.path
    new_path = child_path(new_parent.path if new_parent is not None else None, node.id)
    shift = depth_of(new_path) - depth_of(old_path)
    await session.execute(
        update(model)
        .where(model.path.like(f'{old_path}%'))
        .values(
            path=literal(new_path) + func.substr(model.path, len(old_path) + 1),
            depth=model.depth + shift,
        )
        .execution_options(synchronize_session=False)
    )
    node.parent_id = new_parent.id if new_parent is not None else None
    node.path = new_path
    node.depth = depth_of(new_path)
