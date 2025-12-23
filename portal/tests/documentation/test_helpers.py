"""Tests for documentation helper functions.

Unit tests for nav tree building, markdown rendering, and path handling.
"""

import tempfile
from pathlib import Path

import pytest


class TestTitleFromFilename:
    """Tests for _title_from_filename helper."""

    def test_converts_dashes_to_spaces(self):
        """design-system becomes Design System."""
        from documentation.views import _title_from_filename

        assert _title_from_filename("design-system") == "Design System"

    def test_converts_underscores_to_spaces(self):
        """kali_ami becomes Kali Ami."""
        from documentation.views import _title_from_filename

        assert _title_from_filename("kali_ami") == "Kali Ami"

    def test_index_becomes_overview(self):
        """index becomes Overview."""
        from documentation.views import _title_from_filename

        assert _title_from_filename("index") == "Overview"

    def test_title_case_applied(self):
        """Words are title-cased."""
        from documentation.views import _title_from_filename

        assert _title_from_filename("hello-world") == "Hello World"

    def test_single_word(self):
        """Single words are title-cased."""
        from documentation.views import _title_from_filename

        assert _title_from_filename("architecture") == "Architecture"


class TestBuildNavTree:
    """Tests for _build_nav_tree helper."""

    def test_returns_list(self):
        """Returns a list."""
        from documentation.views import DOCS_ROOT, _build_nav_tree

        result = _build_nav_tree(DOCS_ROOT)
        assert isinstance(result, list)

    def test_excludes_deprecated_folder(self):
        """_deprecated folder is excluded."""
        from documentation.views import _build_nav_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Create structure
            (tmp_path / "_deprecated").mkdir()
            (tmp_path / "_deprecated" / "old.md").write_text("# Old")
            (tmp_path / "current.md").write_text("# Current")

            result = _build_nav_tree(tmp_path)

            names = [item["name"] for item in result]
            assert "_deprecated" not in str(names).lower()
            assert "Current" in names

    def test_excludes_hidden_files(self):
        """Files starting with . are excluded."""
        from documentation.views import _build_nav_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / ".hidden.md").write_text("# Hidden")
            (tmp_path / "visible.md").write_text("# Visible")

            result = _build_nav_tree(tmp_path)

            names = [item["name"] for item in result]
            assert "Hidden" not in names
            assert "Visible" in names

    def test_folders_have_children(self):
        """Folders have is_folder=True and children list."""
        from documentation.views import _build_nav_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "folder").mkdir()
            (tmp_path / "folder" / "doc.md").write_text("# Doc")

            result = _build_nav_tree(tmp_path)

            folder = next(item for item in result if item["is_folder"])
            assert folder["children"] is not None
            assert isinstance(folder["children"], list)

    def test_files_have_path(self):
        """Files have is_folder=False and path."""
        from documentation.views import _build_nav_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "doc.md").write_text("# Doc")

            result = _build_nav_tree(tmp_path)

            file_item = next(item for item in result if not item["is_folder"])
            assert file_item["path"] is not None
            assert file_item["path"] == "doc"

    def test_empty_folders_excluded(self):
        """Folders with no .md files are excluded."""
        from documentation.views import _build_nav_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "empty_folder").mkdir()
            (tmp_path / "has_content").mkdir()
            (tmp_path / "has_content" / "doc.md").write_text("# Doc")

            result = _build_nav_tree(tmp_path)

            names = [item["name"] for item in result]
            assert "Empty Folder" not in names
            assert "Has Content" in names

    def test_nested_paths_correct(self):
        """Nested files have correct paths like 'folder/doc'."""
        from documentation.views import _build_nav_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "parent").mkdir()
            (tmp_path / "parent" / "child.md").write_text("# Child")

            result = _build_nav_tree(tmp_path)

            folder = next(item for item in result if item["is_folder"])
            child = folder["children"][0]
            assert child["path"] == "parent/child"


class TestRenderMarkdown:
    """Tests for _render_markdown helper."""

    def test_renders_basic_markdown(self):
        """Renders basic markdown to HTML."""
        from documentation.views import _render_markdown

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Hello\n\nWorld")
            f.flush()

            result = _render_markdown(Path(f.name))

            assert "<h1>" in result or "<h1" in result
            assert "Hello" in result
            assert "World" in result

    def test_renders_tables(self):
        """Renders markdown tables."""
        from documentation.views import _render_markdown

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("| A | B |\n|---|---|\n| 1 | 2 |")
            f.flush()

            result = _render_markdown(Path(f.name))

            assert "<table" in result

    def test_renders_fenced_code(self):
        """Renders fenced code blocks."""
        from documentation.views import _render_markdown

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("```python\nprint('hello')\n```")
            f.flush()

            result = _render_markdown(Path(f.name))

            assert "<code" in result or "<pre" in result

    def test_preserves_mermaid_blocks(self):
        """Mermaid blocks are preserved for client-side rendering."""
        from documentation.views import _render_markdown

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("```mermaid\nflowchart TB\n    A --> B\n```")
            f.flush()

            result = _render_markdown(Path(f.name))

            # Mermaid content should be in output
            assert "flowchart" in result or "mermaid" in result

    def test_nonexistent_file_raises_404(self):
        """Missing file raises Http404."""
        from django.http import Http404

        from documentation.views import _render_markdown

        with pytest.raises(Http404):
            _render_markdown(Path("/nonexistent/path/file.md"))

    def test_handles_unicode(self):
        """Handles unicode content correctly."""
        from documentation.views import _render_markdown

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Hello 世界 🎉\n\nこんにちは")
            f.flush()

            result = _render_markdown(Path(f.name))

            assert "世界" in result
            assert "🎉" in result


class TestPathSanitization:
    """Tests for path sanitization in doc_page view."""

    def test_normalize_removes_double_dots(self):
        """os.path.normpath handles .."""
        import os

        # This is what we use in the view
        result = os.path.normpath("portal/../index")
        assert ".." not in result

    def test_lstrip_removes_leading_slash(self):
        """lstrip removes leading /."""
        path = "/some/path"
        result = path.lstrip("/")
        assert result == "some/path"
