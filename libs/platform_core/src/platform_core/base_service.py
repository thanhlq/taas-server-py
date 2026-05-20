
from abc import abstractmethod


class IManagedService:

  @abstractmethod
  async def start(self): ...

  @abstractmethod
  async def stop(self): ...


class BaseService(IManagedService):

  async def start(self):
    pass

  async def stop(self):
    pass
