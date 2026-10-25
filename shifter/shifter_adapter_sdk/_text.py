"""Bounded display text, independent of platform logging configuration."""


def safe_log_value(value: object, max_len: int = 200) -> str:
    """Escape controls and backslashes using the existing verification contract."""
    if value is None:
        return "<none>"
    text = str(value).replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    cleaned = "".join(char if char.isprintable() or char == " " else f"\\x{ord(char):02x}" for char in text)
    return cleaned if len(cleaned) <= max_len else cleaned[: max_len - 3] + "..."
