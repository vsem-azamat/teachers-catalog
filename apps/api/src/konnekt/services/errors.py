"""What a service raises when the caller broke a rule.

Four of them, stated without reference to HTTP. A service that raises
`HTTPException` has an opinion about a protocol, which is exactly what stops
the bot from calling it — and the bot answering "422 Unprocessable Content" to
somebody typing into a chat is not an answer.

`main.py` maps each to a status code in one place. Anything else that calls a
service catches the same four and says something in words.
"""


class ServiceError(Exception):
    """A rule the caller broke. Never raised directly — one of the four below."""


class NotFound(ServiceError):
    """The thing addressed does not exist, or the caller may not know it does."""


class Forbidden(ServiceError):
    """It exists, the caller may not do this to it."""


class Conflict(ServiceError):
    """The state moved on: already answered, already chosen, already closed."""


class Invalid(ServiceError):
    """The request contradicts itself or names something that is not there."""
