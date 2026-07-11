from foundation.resiliant.outbox import IOutboxPublisher, OutboxMessage


class MessagePublisher(IOutboxPublisher):
    def __init__(self, topic: str):
        self.topic = topic

    def getOutboxService(self) -> IOutboxService:
        # Placeholder for actual outbox service retrieval logic
        return None

    async def publish(self, message: OutboxMessage) -> None:
        # Placeholder for actual publish logic
        print(f"Publishing message to topic '{self.topic}': {message}")
