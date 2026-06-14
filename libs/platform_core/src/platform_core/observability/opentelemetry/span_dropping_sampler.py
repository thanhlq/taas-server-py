from typing import Optional, Sequence

from opentelemetry import context as context_api
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult
from opentelemetry.trace import Link, SpanKind
from opentelemetry.trace.span import TraceState
from opentelemetry.util.types import Attributes

from ..constants import IGNORED_SPAN_NAMES


class SpanDroppingSampler(Sampler):
    """Use this sampler to drop spans in early stage.
    A custom sampler that drops spans with the name 'connect'.
    Should support to pass ignore list in future enhancements.
    """

    def should_sample(
        self,
        parent_context: Optional[context_api.Context],
        trace_id: int,
        name: str,
        kind: Optional[SpanKind] = None,
        attributes: Attributes = None,
        links: Optional[Sequence['Link']] = None,
        trace_state: Optional['TraceState'] = None,
    ) -> 'SamplingResult':
        if name in IGNORED_SPAN_NAMES:
            return SamplingResult(decision=Decision.DROP)

        return SamplingResult(decision=Decision.RECORD_AND_SAMPLE)

    def get_description(self) -> str:
        return 'SpanDroppingSampler'
