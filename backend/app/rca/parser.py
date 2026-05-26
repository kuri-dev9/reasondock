# Backward-compat re-export — canonical location: app.qie.datasets.parser
from app.qie.datasets.parser import (  # noqa: F401
    CHUNK_SIZE,
    FIELD_SEP,
    ParsedXdr,
    ParseStats,
    RECORD_END_SEPS,
    RECORD_SEP,
    STREAMING_THRESHOLD,
    parse_xdr_file,
)
