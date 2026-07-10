from foundation.utils.lang import is_python_3_10_or_lower
import datetime


def now_in_utc():
    return datetime.datetime.now(datetime.UTC)


def now_as_iso():
    return now_in_utc().isoformat()


def convert_datetime_to_gmt_iso(dt: datetime.datetime) -> str:
    """Handle datetime serialization for nested timestamps.

    Returns:
        The ISO formatted datetime string.

    Examples:
        >>> convert_datetime_to_gmt_iso(datetime.datetime(2024, 1, 1, 12, 0, 0))
        '2024-01-01T12:00:00Z'
    """
    dt = (
        dt.replace(tzinfo=datetime.UTC)
        if not dt.tzinfo
        else dt.astimezone(datetime.UTC)
    )
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def datetime_to_iso(dt: datetime.datetime) -> str:
    return convert_datetime_to_gmt_iso(dt)

def datetime_from_iso(iso_str: str) -> datetime.datetime:
    """Convert an ISO formatted string to a datetime object.

    Args:
        iso_str (str): The ISO formatted string.

    Returns:
        datetime.datetime: The corresponding datetime object.

    Examples:
        >>> datetime_from_iso('2024-01-01T12:00:00Z')

        datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
    """
    if is_python_3_10_or_lower():
        # Does not work in python 3.10
        # For Python 3.10 and lower, we need to:
        #. - 2026-07-01T15:30:00 -> ✅ works
        #  - 2026-07-01T15:30:00Z (UTC suffix) -> ❌ replace 'Z' with '+00:00' for proper parsing
        #  - 2026-07-01T15:30:00+0200 (No colon offset) -> ❌ replace '+0200' with '+02:00' for proper parsing
        iso_str = iso_str.replace("Z", "+00:00")
        try:
            return datetime.datetime.fromisoformat(iso_str)
        except ValueError:
            # fallback to 2026-07-01T15:30:00+0200 (No colon offset)
            return datetime.datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S%z")

    return datetime.datetime.fromisoformat(iso_str)

def convert_datetime_to_utc_iso(dt: datetime.datetime) -> str:
    """Handle datetime serialization for nested timestamps.

    Returns:
        The ISO formatted datetime string.

    Examples:
        >>> convert_datetime_to_utc_iso(datetime.datetime(2024, 1, 1, 12, 0, 0))
        '2024-01-01T12:00:00Z'
    """
    dt = (
        dt.replace(tzinfo=datetime.UTC)
        if not dt.tzinfo
        else dt.astimezone(datetime.UTC)
    )
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def convert_date_to_iso(dt: datetime.date) -> str:
    """Handle date serialization for nested timestamps.

    Returns:
        The ISO formatted date string.

    Examples:
        >>> convert_date_to_iso(datetime.date(2024, 1, 1))
        '2024-01-01'
    """
    return dt.isoformat()
