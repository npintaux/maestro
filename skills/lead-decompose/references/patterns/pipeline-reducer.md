# Pattern 4: Pipeline-Reducer (Data Pipeline / Stream Transformer)

> **Computational Shape**: Ordered Transformation Pipeline / Stream Aggregation / Accumulating Reducer.  
> **Applicability**: IoT telemetry stream windowing (min/max/avg/p95), ETL transformations, stacked calculations (e.g. Base Amount $\to$ Tier Discount $\to$ Tax Calculation $\to$ Shipping Fee $\to$ Final Invoice).

---

## 1. Architecture Overview
An ordered sequence of `PipelineStage(abc.ABC)` steps where each stage transforms or enriches an accumulating context payload. Unlike a decision list that emits an allow/deny verdict, a pipeline produces an evolved, transformed data product.

```
Input Context ──▶ [ Stage 1: Normalize ] ──▶ [ Stage 2: Aggregate ] ──▶ [ Stage 3: Format ] ──▶ Transformed Output
```

---

## 2. Domain Models (`src/domain/models.py`)
```python
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PipelineContext:
    """Accumulating context threaded through pipeline stages."""

    stream_id: str
    raw_records: tuple[Mapping[str, Any], ...]
    accumulated_metrics: Mapping[str, float]
    metadata: Mapping[str, str]
```

---

## 3. Pipeline Stage ABC (`src/domain/stages/base.py`)
```python
import abc
from ..models import PipelineContext


class PipelineStage(abc.ABC):
    """Abstract Base Class for a transformation stage."""

    @property
    @abc.abstractmethod
    def stage_name(self) -> str:
        """Name of the pipeline stage."""
        ...

    @abc.abstractmethod
    def process(self, context: PipelineContext) -> PipelineContext:
        """Transform context and return enriched/reduced output."""
        ...
```

---

## 4. Pipeline Runner (`src/domain/pipeline.py`)
```python
from collections.abc import Sequence
from .models import PipelineContext
from .stages.base import PipelineStage


class PipelineRunner:
    """Executes ordered transformation stages sequentially."""

    def __init__(self, stages: Sequence[PipelineStage]) -> None:
        self._stages = tuple(stages)

    def run(self, initial_context: PipelineContext) -> PipelineContext:
        current = initial_context
        for stage in self._stages:
            current = stage.process(current)
        return current
```

---

## 5. Test Focus
- **Each stage in isolation**: given an input context, assert the exact enrichment/reduction it produces.
- **Immutability**: `process` returns a new `PipelineContext`; the input instance is never mutated.
- **Ordering matters**: verify the runner threads stages in declared order (e.g. discount before tax) and that reordering changes the result.
- **Aggregation correctness**: boundary cases for windowed metrics (empty stream, single record, p95 with ties).
