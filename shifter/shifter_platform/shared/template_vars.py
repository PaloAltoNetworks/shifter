"""Template variable parsing and validation. Re-exports from cyberscript.template_vars."""

from cyberscript.template_vars import (
    ALLOWED_PROPERTIES,
    TemplateString,
    build_instance_data,
    extract_variables,
    resolve_template,
    validate_template,
)

__all__ = [
    "ALLOWED_PROPERTIES",
    "TemplateString",
    "build_instance_data",
    "extract_variables",
    "resolve_template",
    "validate_template",
]
