import re
import unicodedata
from typing import Optional


def camel_to_snake(value: 'str') -> 'str':
    """
    Convert value from camelCase to snake_case
    :param value: Camel case value
    :return: Snake case value
    """
    return re.sub('(?!^)([A-Z]+)', r'_\1', value).lower()


def snake_to_camel(value: 'str') -> 'str':
    """
    Convert value from snake_case to camelCase
    :param value: Snake case value
    :return: Camel case value
    """
    words = value.split('_')
    return words[0] + ''.join(w.title() for w in words[1:])

def slugify(value: str, allow_unicode: bool = False, separator: Optional[str] = None) -> str:
    """Slugify.

    Convert to ASCII if ``allow_unicode`` is ``False``. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.

    Args:
        value (str): the string to slugify
        allow_unicode (bool, optional): allow unicode characters in slug. Defaults to False.
        separator (str, optional): by default a `-` is used to delimit word boundaries.
            Set this to configure something different.

    Returns:
        str: a slugified string of the value parameter
    """
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    if separator is not None:
        return re.sub(r"[-\s]+", "-", value).strip("-_").replace("-", separator)
    return re.sub(r"[-\s]+", "-", value).strip("-_")
