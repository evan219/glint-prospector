"""
Unit tests for installed_capacity.py — selector guard logic and kW text parsing.
Playwright browser interactions are mocked; no live browser needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSelectorGuard:
    """
    The selector guard in get_installed_capacity should skip parcels when any
    config value is "TODO" or empty, logging which items are unresolved.
    """

    def _make_config(self, **overrides):
        defaults = {
            "PROJECT_URL": "TODO",
            "SEL_NEW_ANALYSIS": "TODO",
            "SEL_CAPACITY_KW": "TODO",
            "SCREENSHOT_DIR": "/tmp/test_screenshots",
        }
        mock = MagicMock()
        for k, v in {**defaults, **overrides}.items():
            setattr(mock, k, v)
        return mock

    @pytest.mark.asyncio
    async def test_all_todo_returns_none(self):
        from installed_capacity import get_installed_capacity
        mock_context = AsyncMock()
        parcel = {"parcel_id": "USNY_123"}

        with patch("installed_capacity.config", self._make_config()):
            result = await get_installed_capacity(mock_context, parcel)

        assert result is None
        mock_context.new_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_string_selector_also_skips(self):
        from installed_capacity import get_installed_capacity
        mock_context = AsyncMock()
        parcel = {"parcel_id": "USNY_123"}

        cfg = self._make_config(
            SEL_CAPACITY_KW="",  # empty string — should be caught
        )
        with patch("installed_capacity.config", cfg):
            result = await get_installed_capacity(mock_context, parcel)

        assert result is None
        mock_context.new_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_todo_skips_and_names_unresolved(self, capsys):
        from installed_capacity import get_installed_capacity
        mock_context = AsyncMock()
        parcel = {"parcel_id": "USNY_123"}

        cfg = self._make_config(
            PROJECT_URL="https://app.glintsolar.com/ground/org/x/portfolios/y/projects/z",
            # SEL_NEW_ANALYSIS and SEL_CAPACITY_KW still TODO
        )
        with patch("installed_capacity.config", cfg):
            result = await get_installed_capacity(mock_context, parcel)

        assert result is None
        out = capsys.readouterr().out
        assert "SEL_NEW_ANALYSIS" in out
        assert "SEL_CAPACITY_KW" in out


class TestKwTextParsing:
    """
    Test the kW value parsing logic in isolation by exercising the full flow
    with a mock page that returns known text.
    """

    def _make_all_configured_config(self):
        mock = MagicMock()
        mock.PROJECT_URL = "https://app.glintsolar.com/ground/org/x/portfolios/y/projects/z"
        mock.SEL_NEW_ANALYSIS = "button.new-analysis"
        mock.SEL_CAPACITY_KW = "div.capacity"
        mock.SCREENSHOT_DIR = "/tmp/test_screenshots"
        return mock

    def _make_mock_page(self, kw_text: str | None):
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.screenshot = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_function = AsyncMock()
        page.text_content = AsyncMock(return_value=kw_text)
        page.close = AsyncMock()
        return page

    def _make_mock_context(self, page):
        ctx = AsyncMock()
        ctx.new_page = AsyncMock(return_value=page)
        return ctx

    @pytest.mark.asyncio
    async def test_parses_comma_formatted_kw(self):
        from installed_capacity import get_installed_capacity
        page = self._make_mock_page("1,234 kW")
        ctx = self._make_mock_context(page)

        with patch("installed_capacity.config", self._make_all_configured_config()):
            result = await get_installed_capacity(ctx, {"parcel_id": "USNY_1"})

        assert result == pytest.approx(1234.0)

    @pytest.mark.asyncio
    async def test_parses_plain_number(self):
        from installed_capacity import get_installed_capacity
        page = self._make_mock_page("3.71")
        ctx = self._make_mock_context(page)

        with patch("installed_capacity.config", self._make_all_configured_config()):
            result = await get_installed_capacity(ctx, {"parcel_id": "USNY_1"})

        assert result == pytest.approx(3.71)

    @pytest.mark.asyncio
    async def test_none_text_content_returns_none(self):
        """page.text_content returning None should return None gracefully."""
        from installed_capacity import get_installed_capacity
        page = self._make_mock_page(None)
        ctx = self._make_mock_context(page)

        with patch("installed_capacity.config", self._make_all_configured_config()):
            result = await get_installed_capacity(ctx, {"parcel_id": "USNY_1"})

        assert result is None

    @pytest.mark.asyncio
    async def test_page_closed_on_error(self):
        """Page must be closed even when an error occurs."""
        from installed_capacity import get_installed_capacity
        page = self._make_mock_page(None)
        page.goto = AsyncMock(side_effect=Exception("navigation failed"))
        ctx = self._make_mock_context(page)

        with patch("installed_capacity.config", self._make_all_configured_config()):
            result = await get_installed_capacity(ctx, {"parcel_id": "USNY_1"})

        assert result is None
        page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_per_parcel_project_url_overrides_config(self):
        """parcel['project_url'] takes precedence over config.PROJECT_URL."""
        from installed_capacity import get_installed_capacity
        page = self._make_mock_page("5.00")
        ctx = self._make_mock_context(page)
        parcel_url = "https://app.glintsolar.com/ground/org/x/portfolios/y/projects/per_parcel"

        with patch("installed_capacity.config", self._make_all_configured_config()):
            result = await get_installed_capacity(
                ctx, {"parcel_id": "USNY_1", "project_url": parcel_url}
            )

        assert result == pytest.approx(5.0)
        page.goto.assert_called_once_with(parcel_url)

    @pytest.mark.asyncio
    async def test_unparseable_text_returns_none(self):
        """Non-numeric text from the DOM should return None gracefully."""
        from installed_capacity import get_installed_capacity
        page = self._make_mock_page("N/A")
        ctx = self._make_mock_context(page)

        with patch("installed_capacity.config", self._make_all_configured_config()):
            result = await get_installed_capacity(ctx, {"parcel_id": "USNY_1"})

        assert result is None
