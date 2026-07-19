from typing import Optional


def parse_cookies(cookie_header: str, filter: Optional[str] = None) -> dict[str, str]:
    """
    Parse a Cookie header string into a dictionary of cookie names and values.
    """
    cookies = {}
    if not cookie_header:
        return cookies

    # Split cookies by '; ' delimiter
    cookie_pairs = cookie_header.split('; ')
    for pair in cookie_pairs:
        if '=' in pair:
            name, value = pair.split('=', 1)
            if not filter or filter in name:
                cookies[name] = value
    return cookies
