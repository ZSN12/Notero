"""Default logging fields for structured request logs.

The JSON/text formatters in main.py reference request_id/method/path/status_code/
latency_ms for every record. Non-request logs (startup, third-party libraries,
service logs) do not have these attributes, which causes Python's logging to emit
"Formatting field not found in record" warnings. This filter fills in sensible
defaults so all records can be formatted safely.
"""

import logging


class RequestLogFilter(logging.Filter):
    """Ensure every LogRecord carries request-log fields.

    Missing fields are populated with "-" so formatters do not fail.
    """

    DEFAULTS = {
        "request_id": "-",
        "method": "-",
        "path": "-",
        "status_code": "-",
        "latency_ms": "-",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        for key, default in self.DEFAULTS.items():
            if not hasattr(record, key):
                setattr(record, key, default)
        return True
