"""MinerU API integration for AutoPM3.

Submodules
----------
``client``
    Synchronous client wrapping the MinerU cloud APIs (precise v4 + agent v1).
``exceptions``
    Exception hierarchy for API errors.

Quick start
-----------
>>> from mineru import MinerUClient
>>> client = MinerUClient(token="YOUR_TOKEN")
>>> paths = client.parse_url(
...     "https://example.com/paper.pdf",
...     output_dir="output/paper",
...     model_version="pipeline",
... )
"""

from .client import (
    AGENT_DONE,
    AGENT_FAILED,
    AGENT_MAX_FILE_SIZE_BYTES,
    AGENT_MAX_PAGES,
    AGENT_RUNNING_STATES,
    DEFAULT_BASE_URL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TIMEOUT,
    LOCAL_BACKEND_HYBRID,
    LOCAL_BACKEND_PIPELINE,
    LOCAL_BACKEND_VLM,
    LOCAL_COMPLETED,
    LOCAL_DEFAULT_BASE_URL,
    LOCAL_FAILED,
    LOCAL_FILE_PARSE_PATH,
    LOCAL_PENDING,
    LOCAL_PROCESSING,
    LOCAL_RUNNING_STATES,
    LOCAL_TASKS_PATH,
    MAX_BATCH_FILES,
    MAX_FILE_SIZE_BYTES,
    MAX_PAGES,
    PRECISE_DONE,
    PRECISE_FAILED,
    PRECISE_RUNNING_STATES,
    BatchStatus,
    LocalParseRequest,
    MinerUClient,
    MinerULocalClient,
    TaskStatus,
)
from .client import (
    MinerUAPIError,
    MinerUAuthError,
    MinerUError,
    MinerUFileError,
    MinerUTimeoutError,
)

__all__ = [
    "MinerUClient",
    "MinerULocalClient",
    "LocalParseRequest",
    "TaskStatus",
    "BatchStatus",
    "MinerUError",
    "MinerUAuthError",
    "MinerUAPIError",
    "MinerUFileError",
    "MinerUTimeoutError",
    "DEFAULT_BASE_URL",
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_TIMEOUT",
    "MAX_FILE_SIZE_BYTES",
    "MAX_PAGES",
    "MAX_BATCH_FILES",
    "AGENT_MAX_FILE_SIZE_BYTES",
    "AGENT_MAX_PAGES",
    "PRECISE_DONE",
    "PRECISE_FAILED",
    "PRECISE_RUNNING_STATES",
    "AGENT_DONE",
    "AGENT_FAILED",
    "AGENT_RUNNING_STATES",
    "LOCAL_DEFAULT_BASE_URL",
    "LOCAL_BACKEND_PIPELINE",
    "LOCAL_BACKEND_VLM",
    "LOCAL_BACKEND_HYBRID",
    "LOCAL_PENDING",
    "LOCAL_PROCESSING",
    "LOCAL_COMPLETED",
    "LOCAL_FAILED",
    "LOCAL_RUNNING_STATES",
    "LOCAL_TASKS_PATH",
    "LOCAL_FILE_PARSE_PATH",
]
