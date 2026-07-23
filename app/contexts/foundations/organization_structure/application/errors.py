"""Organization Structure adapter failures."""


class OrganizationWriteConflict(Exception):
    """A department write violated a persistence constraint."""


class ExternalDepartmentUnavailable(Exception):
    """One external department roster could not be loaded and may be skipped."""
