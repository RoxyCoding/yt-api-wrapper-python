"""Exception hierarchy for yt-api-wrapper."""

from __future__ import annotations


class YouTubeError(Exception):
    """Base class for every error raised by this library."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class NetworkError(YouTubeError):
    """A network / HTTP-level failure while talking to YouTube."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause)
        self.status = status


class ParseError(YouTubeError):
    """YouTube answered, but the payload could not be understood."""


class UnavailableError(YouTubeError):
    """The requested resource does not exist, is private, or is region blocked."""

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class MembersOnlyError(UnavailableError):
    """The video exists but is gated behind a channel membership.

    YouTube states the required tier in the reason text, which ``required_tier``
    extracts when it can be recognised.
    """

    def __init__(self, message: str, required_tier: str | None = None) -> None:
        super().__init__(message, reason="MEMBERS_ONLY")
        self.required_tier = required_tier


class InvalidArgumentError(YouTubeError):
    """The caller passed something invalid (bad id, bad URL, bad option)."""
