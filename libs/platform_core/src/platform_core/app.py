from dataclasses import field

from platform_core.config.allowed_hosts import AllowedHostsConfig
from platform_core.config.app import AppConfig
from platform_core.config.compression import CompressionConfig
from platform_core.config.cors import CORSConfig
from platform_core.config.csrf import CSRFConfig
from platform_core.openapi.config import OpenAPIConfig


class TaasApp:
    debug: bool = False
    pdb_on_exception: bool = False

    cors_config: CORSConfig | None = None
    csrf_config: CSRFConfig | None = None

    allowed_hosts: list[str] | AllowedHostsConfig | None = field(default=None)

    openapi_config: OpenAPIConfig | None = None

    compression_config: CompressionConfig | None = None

    def __init__(self, config: AppConfig) -> None:
        self.debug = config.debug
        self.pdb_on_exception = config.pdb_on_exception
        self.cors_config = config.cors_config
        self.csrf_config = config.csrf_config
        self.allowed_hosts = config.allowed_hosts
        self.openapi_config = config.openapi_config
        self.compression_config = config.compression_config

        self.template_engine = None
