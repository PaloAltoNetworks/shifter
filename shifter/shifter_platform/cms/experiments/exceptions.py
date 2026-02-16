"""Experiment manager exceptions."""

from shared.exceptions import CMSError


class ExperimentError(CMSError):
    """Base exception for experiment operations."""


class ScriptUploadError(ExperimentError):
    """Raised when script upload fails."""


class ExperimentValidationError(ExperimentError):
    """Raised when experiment configuration is invalid."""


class ExperimentStateError(ExperimentError):
    """Raised when experiment is in wrong state for requested operation."""


class ArtifactError(ExperimentError):
    """Raised when artifact operations fail."""
