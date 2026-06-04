from logging import Logger


class BaseService:
    _logger: Logger | None = None

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = Logger(self.__class__.__name__)
        return self._logger

    async def start(self) -> 'BaseService':
        return self

    async def stop(self):
        pass
