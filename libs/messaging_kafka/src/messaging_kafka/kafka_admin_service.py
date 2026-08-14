from logging import Logger, getLogger
from typing import Any, List, Optional

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from foundation.exceptions.report_error import report_error
from foundation.messaging.config.messaging_settings import MessagingSettings
from foundation.messaging.kafka.kafka_security import (
    KafkaSecurityConfig,
)
from foundation.messaging.kafka.kafka_settings import KafkaSettings
from foundation.messaging.types import ChannelInfo, MessagingAdminServiceT

from messaging_kafka.aiokafka_security import get_aiokafka_security_kwargs


class KafkaAdminService(MessagingAdminServiceT):
    """
    KafkaAdminService provides administrative operations for managing Kafka topics (channels).
    """

    _admin_client: Optional[AIOKafkaAdminClient] = None
    _logger: Optional[Logger] = None  # Replace with actual logger type if available
    _consistent_check_enabled: bool = True
    """ If enabled, when creating a channel that already exists, check if the existing channel's configuration matches the requested configuration. If not, log a warning. """

    def __init__(self, config: MessagingSettings, kafka_config: KafkaSettings, kafka_security_config: KafkaSecurityConfig):
        self.settings = config
        self.kafka_settings = kafka_config
        self.security_config: KafkaSecurityConfig = kafka_security_config
        self._admin_client: Optional[AIOKafkaAdminClient] = None
        self._consistent_check_enabled = config.CHANNEL_CONSISTENCY_CHECK_ENABLED

    @property
    def broker_url(self) -> List[str]:
        """Return the Kafka bootstrap servers as a list of strings."""
        return [s.strip() for s in self.kafka_settings.KAFKA_BOOTSTRAP_SERVERS.split(',') if s.strip()]

    async def start(self):
        self._admin_client = AIOKafkaAdminClient(
            bootstrap_servers=self.broker_url,
            **get_aiokafka_security_kwargs(self.security_config)
        )
        await self._admin_client.start()

    async def stop(self):
        if self._admin_client:
            await self._admin_client.close()
            self._admin_client = None

    @property
    def admin_client(self) -> AIOKafkaAdminClient:
        if not self._admin_client:
            raise RuntimeError('Admin client is not started. Call start() first.')
        return self._admin_client

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = getLogger(__name__)
        return self._logger

    # -----------------------------------------------------------------------
    # Channel management (topic admin)
    # -----------------------------------------------------------------------

    async def run_consistency_check(
        self, channel: str, num_partitions: int, replication_factor: int
    ) -> bool:
        """
        If consistency check is enabled, check if the existing topic's configuration matches the requested configuration.
        Logs a warning if there is a mismatch.

        Returns:
            ``True`` if the topic exists, ``False`` if it does not (or the check
            could not be completed). A configuration mismatch is logged as a
            warning but still returns ``True`` — existence is what the caller needs.
        """
        if not self._admin_client:
            raise RuntimeError('Call start() first.')

        is_existed = True

        try:
            existing_info = await self.get_channel_info(channel)
            if existing_info is None:
                is_existed = False
            else:
                existing_partitions = existing_info.num_partitions
                # Note: aiokafka does not provide replication factor in describe_topics response, so we cannot check it here.

                if existing_partitions != num_partitions:
                    self.logger.warning(
                        f'Consistency check: topic {channel} has {existing_partitions} partitions but expected {num_partitions}.'
                    )
                else:
                    self.logger.debug(f'[OK] Consistency check passed for topic {channel}.')
        except Exception as exc:
            # Diagnostic only — never let a failed check abort topic registration.
            # Report it and return "not existed" so create_channel falls through to
            # its idempotent create / TopicAlreadyExistsError path (a transient
            # broker/metadata error at startup must not crash registration).
            report_error(
                exc,
                title='Kafka topic consistency check error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            return False

        return is_existed

    async def create_channel(
        self,
        channel: str,
        num_partitions: int = 1,
        *,
        replication_factor: int = 1,
        retention_hours: int = 168,  # 7 days default,
        fifo: bool = False,  # Only applicable for queues: if True, create FIFO queue with ordering guarantees.
        **kwargs,
    ) -> bool:
        """
        Create a Kafka topic (channel).

        Uses the aiokafka admin client. Idempotent: creating a topic that
        already exists is not an error.

        Args:
            channel: Topic name.
            num_partitions: Number of partitions (default 1).
            replication_factor: Replication factor (default 1).

        Returns:
            ``True`` if the topic was newly created, ``False`` if it already
            existed. Raises on unexpected admin-client errors.
        """
        if not self._admin_client:
            raise RuntimeError('Call start() first.')

        is_existed = False
        if self._consistent_check_enabled:
            is_existed = await self.run_consistency_check(
                channel, num_partitions, replication_factor
            )

        try:
            if not is_existed:
                self.logger.info(f'Creating topic: {channel}, partitions: {num_partitions}, repl factor: {replication_factor}')
                topic = NewTopic(
                    name=channel,
                    num_partitions=num_partitions,
                    replication_factor=replication_factor,
                )
                await self._admin_client.create_topics([topic])
                self.logger.info(f'Created topic: {channel}, partitions: {num_partitions}, repl factor: {replication_factor}')
                return True
        except TopicAlreadyExistsError:
            self.logger.debug(f'Topic already exists: {channel}')
        except Exception as exc:
            report_error(
                exc,
                title='FastStream Create Topic Error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            raise exc
        return False

    async def create_channel_if_not_exists(
        self,
        channel: str,
        num_partitions: int = 1,
        *,
        replication_factor: int = 1,
        retention_hours: int = 168,  # 7 days default,
        fifo: bool = False,  # Only applicable for queues: if True, create FIFO queue with ordering guarantees.
        **kwargs,
    ) -> bool:
        """
        Create a Kafka topic (channel) if it does not already exist.

        Idempotent pass-through to :meth:`create_channel`: returns ``True`` if
        the topic was newly created, ``False`` if it already existed.

        Args:
            channel: Topic name.
            num_partitions: Number of partitions (default 1).
            replication_factor: Replication factor (default 1).
            retention_hours: Retention period in hours (default 168, 7 days).
            fifo: If True, create a FIFO queue with ordering guarantees (default False).
        """
        return await self.create_channel(
            channel,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
            retention_hours=retention_hours,
            fifo=fifo,
        )

    async def delete_channel(self, channel: str, **kwargs: Any) -> bool:
        """
        Delete a Kafka topic (channel).

        Args:
            channel: Topic name to delete.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        if not self._admin_client:
            raise RuntimeError('Call start() first.')
        try:
            await self._admin_client.delete_topics([channel])
            self.logger.info(f'🗑️  Deleted topic: {channel}')
            return True
        except Exception as exc:
            report_error(
                exc,
                title='FastStream Delete Topic Error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            return False

    async def list_channels(self, **kwargs: Any) -> list[str]:
        """
        List all available Kafka topics.

        Returns:
            List of topic names, excluding internal Kafka topics
            (those starting with ``_``).
        """
        if not self._admin_client:
            raise RuntimeError('Call start() first.')
        try:
            metadata = await self._admin_client.list_topics()
            return [t for t in metadata if not t.startswith('_')]
        except Exception as exc:
            report_error(
                exc,
                title='FastStream List Topics Error',
                logger=self.logger,
            )
            return []

    async def get_channel_info(self, channel: str) -> Optional[ChannelInfo]:
        """
        Get detailed information about a Kafka topic (channel).

        Returns a dict with topic metadata (partitions, replicas, configs)
        or ``None`` if the topic does not exist.
        """
        if not self._admin_client:
            raise RuntimeError('Call start() first.')
        try:
            metadata = await self._admin_client.describe_topics([channel])
            if not metadata:
                return None
            topic_meta = metadata[0]
            # aiokafka returns dicts with keys: 'topic', 'error_code', 'is_internal', 'partitions'
            if topic_meta.get('error_code', 0) != 0:
                self.logger.warning(
                    f'describe_topics returned error_code={topic_meta.get("error_code")} for {channel}'
                )
                return None
            partitions = topic_meta.get('partitions', []) or []

            return ChannelInfo(
                name=topic_meta.get('topic', channel),
                is_internal=topic_meta.get('is_internal', False),
                num_partitions=len(partitions),
                partitions=[
                    {
                        'partition': p.get('partition'),
                        'leader': p.get('leader'),
                        'replicas': p.get('replicas', []),
                        'isr': p.get('isr', []),
                    }
                    for p in partitions
                ],
            )
        except Exception as exc:
            report_error(
                exc,
                title='FastStream Describe Topic Error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            return None
