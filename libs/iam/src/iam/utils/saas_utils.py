from advanced_alchemy.base import ModelProtocol
from foundation.config import get_settings


def generate_saas_subdomain(name: str, max_length: int = 12) -> str:
    """Generate a subdomain name for a SaaS tenant based on the given name.

    Args:
        name (str): The base name to generate the subdomain from.
        max_length (int, optional): Maximum length of the subdomain. Defaults to 12.

    Returns:
        str: A sanitized subdomain name.
    """
    # Sanitize the name: lowercase, replace spaces with hyphens, remove invalid characters
    sanitized_name = ''.join(
        char.lower() if char.isalnum() or char == '-' else '-' if char.isspace() else ''
        for char in name
    )
    # Truncate to max_length
    return sanitized_name[:max_length].rstrip('-')


def get_keycloak_subdomain(domain_alias: str, max_length: int = 20) -> str:
    """Must remove https or http from root domain"""
    settings = get_settings()
    root_domain = settings.app.FRONTEND_URL
    if 'https://' in root_domain:
        root_domain = root_domain.replace('https://', '')
        root_domain = f'{domain_alias}.{root_domain}'
    elif 'http://' in root_domain:
        root_domain = root_domain.replace('http://', '')
        root_domain = f'http://{domain_alias}.{root_domain}'
    return root_domain

# Example usage:
# print(generate_saas_subdomain("My Awesome Company!"))  # Output: my-awesome-company
# print(generate_saas_subdomain("EMSA TECHNOLOGY!", 5))  # Output: my-awesome-company
# print(generate_saas_subdomain("Nvidia"))  # Output: my-awesome-company

def orm_to_dict(orm_model: type[ModelProtocol], **kwargs) -> dict:
    # TODO: to review again if the copy() action is needed or simply using: orm_model.__dict__
    # copy = orm_model.__dict__.copy()
    copy = orm_model._asdict()  # type: ignore[attr-defined]
    copy.pop('_sa_instance_state', None)

    execlude = kwargs.get('exclude', None)
    if execlude:
        if isinstance(execlude, str):
            execlude = [execlude]
        for key in execlude:
            if key in copy:
                copy.pop(key)

    return copy
