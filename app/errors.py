"""Public-safe adapter errors."""

from dataclasses import dataclass


@dataclass(slots=True)
class AdapterError(Exception):
    """An error that can be safely rendered to an API caller."""

    status_code: int
    error_code: str
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
