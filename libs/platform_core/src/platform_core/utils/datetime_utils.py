import datetime


def now_in_utc():
    return datetime.datetime.now(datetime.UTC)
