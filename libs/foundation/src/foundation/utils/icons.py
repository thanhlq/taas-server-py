"""
Common Constants Module

This module contains all application-wide constants organized by functional areas.
Use these constants throughout the application to maintain consistency and avoid magic values.
"""


# class Logging:
#     """Logging adapter types and configuration constants."""

#     LOG_FORMAT_STANDARD = 'standard'
#     LOG_FORMAT_DETAILED = 'detailed'
#     LOG_FORMAT_JSON = 'json'

#     LOG_ADAPTER_CONSOLE = 'console'
#     """Console logging adapter (stdout/stderr)"""

#     LOG_ADAPTER_FILE = 'file'
#     """File-based logging adapter"""

#     LOG_ADAPTER_OTLP_HTTP = 'otlp-http'
#     """OpenTelemetry Protocol HTTP logging adapter"""

#     LOG_ADAPTER_OTLP_GRPC = 'otlp-grpc'
#     """OpenTelemetry Protocol gRPC logging adapter"""

#     LOG_ADAPTER_ELK = 'elk'

#     LOG_OTEL_HTTP_ENDPOINT_DEFAULT = 'http://localhost:4318/v1/logs'
#     """Default HTTP endpoint for OpenTelemetry logs"""

#     LOG_OTEL_GRPC_ENDPOINT_DEFAULT = 'http://localhost:4317'
#     """Default gRPC endpoint for OpenTelemetry logs"""


# # ═══════════════════════════════════════════════════════════════════════════════
# # 📊 TRACING CONFIGURATION CONSTANTS
# # ═══════════════════════════════════════════════════════════════════════════════
# """
# Distributed tracing configuration constants for different adapters and endpoints.
# These define the available tracing backends and their default configurations.
# """


# class Tracing:
#     """Tracing adapter types and configuration constants."""

#     DEFAULT_TRACER_NAME = 'main'
#     """Default tracer name for the application"""

#     TRACING_ADAPTER_CONSOLE = 'console'
#     """Console tracing adapter (stdout for debugging)"""

#     TRACING_ADAPTER_ELK = 'elk'
#     """Elastic tracing adapter"""

#     TRACING_ADAPTER_OTLP_HTTP = 'otlp-http'
#     """OpenTelemetry Protocol HTTP tracing adapter"""

#     TRACING_ADAPTER_OTLP_GRPC = 'otlp-grpc'
#     """OpenTelemetry Protocol gRPC tracing adapter"""

#     TRACING_OTEL_HTTP_ENDPOINT_DEFAULT = 'http://localhost:4318/v1/traces'
#     """Default HTTP endpoint for OpenTelemetry traces"""

#     TRACING_OTEL_GRPC_ENDPOINT_DEFAULT = 'http://localhost:4317'
#     """Default gRPC endpoint for OpenTelemetry traces"""


# # ═══════════════════════════════════════════════════════════════════════════════
# # 👤 USER PROFILE CONSTANTS
# # ═══════════════════════════════════════════════════════════════════════════════
# """
# Constants for user profile attributes and demographics.
# """

# GENDER_MALE = 'male'
# """Gender identifier: male"""

# GENDER_FEMALE = 'female'
# """Gender identifier: female"""

# GENDER_OTHER = 'other'
# """Gender identifier: other/non-binary/prefer not to say"""


# # ═══════════════════════════════════════════════════════════════════════════════
# # 🏢 MULTI-TENANCY (SaaS) CONSTANTS
# # ═══════════════════════════════════════════════════════════════════════════════
# """
# Constants for multi-tenant SaaS architecture.
# Tenant IDs are numeric identifiers within a specific range.
# """

# MIN_TENANT_ID = 10000000
# """Minimum tenant ID (8-digit number starting from 10,000,000)"""

# MAX_TENANT_ID = 99999999
# """Maximum tenant ID (8-digit number ending at 99,999,999)"""

# TENANT_ID_LENGTH = 8
# """Fixed length for tenant ID strings"""

# SAAS_USER_ID_LENGTH = 21
# """Length of SaaS user identifiers (tenant_id + user_id)"""

# # ═══════════════════════════════════════════════════════════════════════════════
# # 🏢 COMMON PARAMETERS
# # ═══════════════════════════════════════════════════════════════════════════════

# ORG_ID_PARAM = 'org_id'
# CONTEXT_DATA_PARAM = 'context_data'


class Icons:
    """Common emoji icons for logging and user-facing messages."""

    ON = '🟢'
    OFF = '⚫'  # GRAY

    START = '▶️'
    STOP = '⏹️'

    SUCCESS = '✅'
    ERROR = '❌'
    WARNING = '⚠️'
    INFO = 'ℹ️'
    DEBUG = '🐞'

    MESSAGE = '✉️'
    MESSAGING_SERVICE = '📡'

    MESSAGE_PUBLISHED = '📤'
    MESSAGE_RECEIVED = '📩'

    KAFKA = '📨'
    RABBIT_MQ = '🐇'
    REDIS = '🧰'
    POSTGRESQL = '🐘'
    OPENTELEMETRY = '🔭'
    AMQP = '📬'

    EVENT_HANDLER = '🎯'
    OUTBOX_SERVICE = '📦'
    SAGA_SERVICE = '🧵'
    SCHEDULER_SERVICE = '⏰'
    CRON_JOB = '⏱️'
    # 🏊 🎭 🚦
    MESSAGE_ROUTING = '🚦'
    THEATER = '🎭'
    EVENT_PROCESSOR = '⚡'
    SECRET_MANAGER = '🔐'
    AUTHENTICATION = '🔑'
    AUTHORIZATION = '🛡️'

    FASTSTREAM = '🌊'
    WEBSOCKET = '🔌'
    DATABASE = '🐘'
    CACHE = '🧠'

    FORCED_STOP = '🛑'
    STOPPED = '👋'

    DELETED = '🗑️'

    CPU = '🖥️'
    RAM = '💾'
