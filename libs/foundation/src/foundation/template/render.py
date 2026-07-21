from typing import Any

from jinja2 import Template

# from jinja2 import Template


def render_template_sync(template_str: str, context: dict[str, Any]) -> str:
    """
    Render a template string with the provided context using Jinja2.

    Args:
        template_str (str): The template string to render.
        context (dict[str, any]): The context data for rendering.

    Returns:
        str: The rendered template string.
    """
    return Template(template_str).render(context)


async def render_template(template_str: str, context: dict[str, Any]) -> str:
    """
    Render a template string with the provided context using Jinja2.

    Args:
        template_str (str): The template string to render.
        context (dict[str, any]): The context data for rendering.

    Returns:
        str: The rendered template string.
    """
    return Template(template_str).render_async(context)
