"""murmurent — group-level agentic infrastructure for the Hallett bioconvergence center."""

# CalVer: YYYY.M.MICRO (issue #24). Bump ONLY on a *structural* release — a new
# commons agent, a marker/schema change, or anything that should make existing
# murmurent-ready repos want `murmurent repo upgrade`. Agent-content edits
# propagate via symlink and need no bump. This string is the single source of
# truth for the version (pyproject reads it) and is stamped into every repo's
# .murmurent.yaml as bootstrap_version. MICRO increments for a second release
# in the same month. NOT the same as the on-disk schema versions
# (MARKER_SCHEMA / CARD_VERSION / SIGNED_CARD_VERSION), which bump independently.
__version__ = "2026.7.0"
