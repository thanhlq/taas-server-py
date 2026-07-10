import logging
from logging import Logger
from typing import Optional


class DBSessionStats:
    """
    A class to track statistics about database sessions.
    """

    def __init__(self, logger: Optional[Logger] = None, debug: bool = False):
        self.logger = logger or logging.getLogger(__name__)
        self.debug = debug
        self.total_sessions_created: int = 0
        self.total_sessions_closed: int = 0
        self.total_sessions_committed: int = 0
        self.total_sessions_rolled_back: int = 0
        self.total_sessions_reused: int = 0

    def increment_reused(self, count: int = 1):
        self.total_sessions_reused += count
        if self.debug:
            self.logger.debug(f'Sessions reused: {self.total_sessions_reused}')

    def increment_created(self, count: int = 1):
        self.total_sessions_created += count
        if self.debug:
            self.logger.debug(f'Sessions created: {self.total_sessions_created}')

    def increment_closed(self, count: int = 1):
        self.total_sessions_closed += count
        if self.debug:
            self.logger.debug(f'Sessions closed: {self.total_sessions_closed}')

    def increment_committed(self, count: int = 1):
        self.total_sessions_committed += count
        if self.debug:
            self.logger.debug(f'Sessions committed: {self.total_sessions_committed}')

    def increment_rolled_back(self, count: int = 1):
        self.total_sessions_rolled_back += count
        if self.debug:
            self.logger.debug(
                f'Sessions rolled back: {self.total_sessions_rolled_back}'
            )

    def get_stats(self) -> dict:
        return {
            'total_sessions_created': self.total_sessions_created,
            'total_sessions_closed': self.total_sessions_closed,
            'total_sessions_committed': self.total_sessions_committed,
            'total_sessions_rolled_back': self.total_sessions_rolled_back,
            'total_sessions_reused': self.total_sessions_reused,
        }

    def to_dict(self) -> dict:
        """
        Returns the statistics as a dictionary.
        """
        return self.get_stats()
