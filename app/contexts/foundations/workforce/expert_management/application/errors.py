"""Expert Management adapter failures."""


class ExpertWriteConflict(Exception):
    """A profile write violated an existing unique fact."""
