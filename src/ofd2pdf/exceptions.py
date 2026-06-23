class OfdConversionError(Exception):
    """Base error for conversion failures."""


class OfdParseError(OfdConversionError):
    """Raised when the OFD package structure is invalid."""


class OfdUnsupportedError(OfdConversionError):
    """Raised when required OFD content is not supported yet."""
