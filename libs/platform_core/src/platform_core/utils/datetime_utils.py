import datetime


def now_in_utc():
    return datetime.datetime.now(datetime.UTC)


def now_as_iso():
    return now_in_utc().isoformat()
