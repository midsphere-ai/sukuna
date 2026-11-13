"""Custom exception classes for the projects service layer."""


class ProjectsServiceError(Exception):
    """Base exception for all project related errors"""

    pass


class CreateProjectFailedError(ProjectsServiceError):
    """This will trigger when Project creation has failed"""

    pass


class UpdateProjectFailedError(ProjectsServiceError):
    """Similarly when modification fails - this will trigger"""

    pass


class ProjectObjectNotFoundError(ProjectsServiceError):
    """If a Project object does not exists, then this exception is thrown"""

    pass


class ProjectFileNotFoundError(ProjectsServiceError):
    """Raised when a requested ProjectFile does not exist."""

    pass


class ProjectFileUploadError(ProjectsServiceError):
    """Raised when uploading a file to a project fails."""

    pass
