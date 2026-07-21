from typing import Any

from jinja2 import Environment, Template

# from jinja2 import Template

# 1. Enable async mode in the environment
environment = Environment(
    # loader=FileSystemLoader("templates"),
    enable_async=True  # <-- Add this line
)


def render_template_sync(template_str: str, context: dict[str, Any]) -> str:
    """
    Render a template string with the provided context using Jinja2.

    Args:
        template_str (str): The template string to render.
        context (dict[str, any]): The context data for rendering.

    Returns:
        str: The rendered template string.
    """
    return Template(source=template_str, enable_async=True).render(context)


async def render_template(template_str: str, context: dict[str, Any]) -> str:
    """
    Render a template string with the provided context using Jinja2.

    Args:
        template_str (str): The template string to render.
        context (dict[str, any]): The context data for rendering.

    Returns:
        str: The rendered template string.
    """
    return await Template(source=template_str, enable_async=True).render_async(context)
