"""
Unit tests for playwright_flow.py — all Playwright interactions mocked.
No live browser is used.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class TestOpenBuildableAreaPanel:

    def _make_page(self):
        page = AsyncMock()
        page.wait_for_selector = AsyncMock()

        parcel_locator = AsyncMock()
        parcel_locator.wait_for = AsyncMock()
        parcel_locator.dispatch_event = AsyncMock()

        buildable_btn = AsyncMock()
        buildable_btn.wait_for = AsyncMock()
        buildable_btn.click = AsyncMock()

        run_btn = AsyncMock()
        run_btn.wait_for = AsyncMock()

        def get_by_role_side_effect(role, **kwargs):
            name = kwargs.get("name", "")
            if name == "Buildable Area":
                return buildable_btn
            if name == "Run Buildable Area":
                return run_btn
            return AsyncMock()

        page.locator = MagicMock(return_value=parcel_locator)
        page.get_by_role = MagicMock(side_effect=get_by_role_side_effect)
        return page, parcel_locator, buildable_btn, run_btn

    @pytest.mark.asyncio
    async def test_dispatches_contextmenu_and_clicks_buildable_area(self):
        from playwright_flow import open_buildable_area_panel

        page, parcel_locator, buildable_btn, run_btn = self._make_page()

        await open_buildable_area_panel(page, "USNY_42")

        page.wait_for_selector.assert_awaited_once_with("text=Objects", timeout=30_000)
        page.locator.assert_called_once_with('p:has-text("Parcel USNY_42")')
        parcel_locator.wait_for.assert_awaited_once_with(state="visible", timeout=10_000)
        parcel_locator.dispatch_event.assert_awaited_once_with(
            "contextmenu", {"bubbles": True, "cancelable": True}
        )
        buildable_btn.wait_for.assert_awaited_once_with(state="visible", timeout=5_000)
        buildable_btn.click.assert_awaited_once()
        run_btn.wait_for.assert_awaited_once_with(state="visible", timeout=10_000)

    @pytest.mark.asyncio
    async def test_raises_if_buildable_area_not_found(self):
        from playwright_flow import open_buildable_area_panel

        page, parcel_locator, buildable_btn, run_btn = self._make_page()
        buildable_btn.wait_for = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout 5000ms exceeded")
        )

        with pytest.raises(PlaywrightTimeoutError):
            await open_buildable_area_panel(page, "USNY_42")


class TestRunBuildableAreaAndCopy:

    def _make_page(self, is_visible_returns=True, evaluate_returns="62.44"):
        page = AsyncMock()

        run_btn = AsyncMock()
        run_btn.click = AsyncMock()

        copy_btn = AsyncMock()
        copy_btn.click = AsyncMock()
        copy_btn.is_visible = AsyncMock(return_value=is_visible_returns)

        def locator_side_effect(selector):
            if "Copy to project" in selector:
                return copy_btn
            return AsyncMock()

        def get_by_role_side_effect(role, **kwargs):
            name = kwargs.get("name", "")
            if name == "Run Buildable Area":
                return run_btn
            if name == "Copy to project":
                return copy_btn
            return AsyncMock()

        page.locator = MagicMock(side_effect=locator_side_effect)
        page.get_by_role = MagicMock(side_effect=get_by_role_side_effect)
        page.evaluate = AsyncMock(return_value=evaluate_returns)
        return page, copy_btn

    @pytest.mark.asyncio
    async def test_returns_acres_when_copy_button_appears(self):
        from playwright_flow import run_buildable_area_and_copy

        page, copy_btn = self._make_page(is_visible_returns=True, evaluate_returns="62.44")
        copy_btn.is_visible = AsyncMock(return_value=True)

        result = await run_buildable_area_and_copy(page)

        assert result == pytest.approx(62.44)
        copy_btn.click.assert_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_when_acres_not_parseable(self):
        from playwright_flow import run_buildable_area_and_copy

        page, copy_btn = self._make_page(is_visible_returns=True, evaluate_returns=None)

        result = await run_buildable_area_and_copy(page)

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        from playwright_flow import run_buildable_area_and_copy

        page, copy_btn = self._make_page(is_visible_returns=False)
        copy_btn.is_visible = AsyncMock(return_value=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await run_buildable_area_and_copy(page)

        assert result is None


class TestClickNewAnalysisAndReadKw:

    def _make_page(self):
        page = AsyncMock()
        new_analysis_btn = AsyncMock()
        new_analysis_btn.click = AsyncMock()

        page.get_by_role = MagicMock(return_value=new_analysis_btn)
        page.wait_for_function = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_clicks_new_analysis_and_returns_kw(self):
        from playwright_flow import click_new_analysis_and_read_kw

        page = self._make_page()

        with patch(
            "playwright_flow._read_kw_from_page",
            new=AsyncMock(return_value=15040.0),
        ):
            result = await click_new_analysis_and_read_kw(page)

        assert result == pytest.approx(15040.0)
        page.get_by_role.assert_called_with("button", name="New analysis", exact=False)

    @pytest.mark.asyncio
    async def test_timeout_still_returns_kw_if_readable(self):
        from playwright_flow import click_new_analysis_and_read_kw

        page = self._make_page()
        page.wait_for_function = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout 60000ms exceeded")
        )

        with patch(
            "playwright_flow._read_kw_from_page",
            new=AsyncMock(return_value=6770.0),
        ):
            result = await click_new_analysis_and_read_kw(page)

        assert result == pytest.approx(6770.0)

    @pytest.mark.asyncio
    async def test_returns_none_if_kw_unreadable(self):
        from playwright_flow import click_new_analysis_and_read_kw

        page = self._make_page()
        page.wait_for_function = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout 60000ms exceeded")
        )

        with patch(
            "playwright_flow._read_kw_from_page",
            new=AsyncMock(return_value=None),
        ):
            result = await click_new_analysis_and_read_kw(page)

        assert result is None
