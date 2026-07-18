import re


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
