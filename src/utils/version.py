from __future__ import annotations


def parse_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.replace("-", ".").split("."):
        digits = "".join(char for char in chunk if char.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def is_newer_version(latest: str, current: str) -> bool:
    return parse_version_tuple(latest) > parse_version_tuple(current)
