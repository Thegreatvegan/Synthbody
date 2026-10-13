"""Single source of truth for software versioning stamped into every simulation record."""
from __future__ import annotations

SOFTWARE_NAME = "SYNTHBODY"
SOFTWARE_VERSION = "0.1.0"

# Bumped whenever the engine changes in a way that could alter previously
# recorded results OR the hashes that identify them. Provenance records store
# this so an old run can never be silently confused with a new one, and so a
# reproducibility mismatch is explained rather than mysterious.
#
# History:
#   engine-2026.10.12   initial release
#   engine-2026.10.12b  input_hash narrowed to the numerically determining
#                       parameter fields (name, value, unit); evidence metadata
#                       moved to record_hash only. Numerical behaviour
#                       unchanged, but hashes recorded before this revision
#                       will not match.
ENGINE_REVISION = "engine-2026.10.12b"

# Bumped when the shape of a persisted provenance record changes.
PROVENANCE_SCHEMA_VERSION = "1.0.0"
