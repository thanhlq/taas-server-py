from pydantic.alias_generators import to_camel
from abc import ABC
from pydantic import BaseModel as PydanticBaseModel, ConfigDict


class BaseEntityPydantic(PydanticBaseModel, ABC):
    model_config = ConfigDict(
        alias_generator=to_camel,
        serialize_by_alias=True,  # Always use camelCase in JSON output
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",  # Ignore extra field from original object when converting
    )

    def as_json(self, **kwargs):
        # v2
        return self.model_dump_json()
