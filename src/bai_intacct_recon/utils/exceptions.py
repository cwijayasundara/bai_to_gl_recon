"""Custom exceptions for the reconciliation application."""


class ReconciliationError(Exception):
    """Base exception for reconciliation errors."""

    pass


class BAI2ParseError(ReconciliationError):
    """Error parsing BAI2 file."""

    pass


class IntacctParseError(ReconciliationError):
    """Error parsing Intacct CSV file."""

    pass


class ConfigurationError(ReconciliationError):
    """Error in configuration."""

    pass


class ValidationError(ReconciliationError):
    """Data validation error."""

    pass


class ReportGenerationError(ReconciliationError):
    """Error generating Excel report."""

    pass
