from enum import Enum


class GraphTimeFrames(int, Enum):
    _7D = 7
    _14D = 14
    _30D = 30
    _60D = 60
    _90D = 90
    _180D = 180
    _1Y = 12
    _24H = 24

    @classmethod
    def get(cls, name: str, default: int  | None= None):
        try:
            name = name.upper()
            return cls[f'_{name}' if not name.startswith('_') else name]
        except KeyError:
            return default
