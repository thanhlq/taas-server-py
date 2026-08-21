from typing import Literal


type SerializationFormat = Literal["json", "msgpack", "avro", "protobuf", "custom"] | str
