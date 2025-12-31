"""Documentation views - serve markdown files from documentation/docs/.

Renders markdown documentation with:
- Login required access via @login_required
- Navigation tree built from directory structure
- Mermaid diagram support (client-side rendering)
- Security: path sanitization, excluded folders
"""

import os
from pathlib import Path

import bleach
import markdown
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

# Path to docs source inside the documentation app
DOCS_ROOT = Path(settings.BASE_DIR) / "documentation" / "docs"

# Folders to exclude from navigation and access
EXCLUDED_FOLDERS = {"_deprecated"}

# Bleach allowlist for HTML sanitization
# Covers standard markdown output + code highlighting
ALLOWED_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "hr",
    "ul",
    "ol",
    "li",
    "pre",
    "code",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
    "strong",
    "em",
    "del",
    "ins",
    "img",
    "div",
    "span",  # For code highlighting classes
    "details",
    "summary",  # Collapsible sections
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "code": ["class"],  # For language-* classes
    "pre": ["class"],
    "div": ["class"],  # For codehilite, mermaid
    "span": ["class"],  # For syntax highlighting
    "th": ["align"],
    "td": ["align"],
}


def _title_from_filename(filename: str) -> str:
    """Convert filename to display title.

    Examples:
        "design-system" -> "Design System"
        "kali-ami" -> "Kali Ami"
        "index" -> "Overview"
    """
    if filename == "index":
        return "Overview"
    return filename.replace("-", " ").replace("_", " ").title()


def _build_nav_tree(base_path: Path, current_path: str = "") -> list[dict]:
    """Build navigation tree from directory structure.

    Returns list of dicts with structure:
    {
        "name": "Display Name",
        "path": "url/path",  # For files only
        "children": [...],   # For folders only
        "is_folder": bool,
    }

    Excludes:
    - _deprecated folder
    - Hidden files/folders (starting with .)
    - Empty folders (no .md files)
    """
    items = []

    try:
        entries = sorted(base_path.iterdir())
    except (PermissionError, FileNotFoundError):
        return items

    # Separate folders and files
    folders = []
    files = []

    for entry in entries:
        # Skip excluded folders
        if entry.name in EXCLUDED_FOLDERS:
            continue
        # Skip hidden files/folders
        if entry.name.startswith("."):
            continue

        if entry.is_dir():
            folders.append(entry)
        elif entry.suffix == ".md":
            files.append(entry)

    # Process folders first
    for folder in folders:
        folder_path = f"{current_path}/{folder.name}" if current_path else folder.name
        children = _build_nav_tree(folder, folder_path)
        if children:  # Only add folders with content
            items.append(
                {
                    "name": _title_from_filename(folder.name),
                    "path": None,
                    "children": children,
                    "is_folder": True,
                }
            )

    # Process markdown files
    for md_file in files:
        # Skip index.md from direct listing - it's the folder's landing page
        if md_file.name == "index.md":
            continue

        file_path = f"{current_path}/{md_file.stem}" if current_path else md_file.stem
        items.append(
            {
                "name": _title_from_filename(md_file.stem),
                "path": file_path,
                "children": None,
                "is_folder": False,
            }
        )

    return items


def _get_markdown_extensions() -> list:
    """Get markdown extensions for rendering."""
    return [
        "tables",
        "fenced_code",
        "codehilite",
        "toc",
    ]


def _render_markdown(file_path: Path) -> str:
    """Read and render markdown file to HTML.

    Raises Http404 if file doesn't exist.
    HTML output is sanitized with bleach to prevent XSS.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as err:
        raise Http404("Document not found") from err

    md = markdown.Markdown(extensions=_get_markdown_extensions())
    html = md.convert(content)

    # Sanitize HTML to prevent XSS from markdown content
    sanitized = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    )

    return sanitized


def _sanitize_path(path: str) -> str:
    """Sanitize URL path to prevent directory traversal.

    Returns cleaned path or raises Http404 if path is malicious.
    """
    # Normalize path to resolve any .. or .
    clean_path = os.path.normpath(path).lstrip("/")

    # Reject if still contains ..
    if ".." in clean_path:
        raise Http404("Invalid path")

    # Check for excluded folders in path parts
    path_parts = clean_path.split("/")
    for part in path_parts:
        if part in EXCLUDED_FOLDERS:
            raise Http404("Document not found")
        # Also block hidden files/folders
        if part.startswith("."):
            raise Http404("Document not found")

    return clean_path


@login_required
@require_GET
def doc_index(request: HttpRequest) -> HttpResponse:
    """Display documentation index page."""
    nav_tree = _build_nav_tree(DOCS_ROOT)

    # Render index.md as the main content
    index_path = DOCS_ROOT / "index.md"
    content = _render_markdown(index_path)

    context = {
        "nav_tree": nav_tree,
        "content": content,
        "current_path": "",
        "page_title": "Documentation",
        "active_nav": "docs",
    }
    return render(request, "documentation/doc_page.html", context)


@login_required
@require_GET
def doc_page(request: HttpRequest, path: str) -> HttpResponse:
    """Display a specific documentation page."""
    nav_tree = _build_nav_tree(DOCS_ROOT)

    # Sanitize path to prevent directory traversal
    clean_path = _sanitize_path(path)

    # Try to find the markdown file
    # First try exact path + .md
    file_path = DOCS_ROOT / f"{clean_path}.md"

    # If not found, try path/index.md (for folder landing pages)
    if not file_path.exists():
        file_path = DOCS_ROOT / clean_path / "index.md"

    if not file_path.exists():
        raise Http404("Document not found")

    content = _render_markdown(file_path)

    # Extract title from path
    path_parts = clean_path.split("/")
    title = _title_from_filename(path_parts[-1])

    context = {
        "nav_tree": nav_tree,
        "content": content,
        "current_path": clean_path,
        "page_title": title,
        "active_nav": "docs",
    }
    return render(request, "documentation/doc_page.html", context)
