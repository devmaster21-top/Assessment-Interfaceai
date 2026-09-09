from __future__ import annotations

import re
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Locator, Page, async_playwright

from cuagent.models import LocatorCandidate, Observation, ObservedControl, TargetLocator
from cuagent.surface.base import Surface


CONTROL_JS = r"""
() => {
  const els = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"],[tabindex],[aria-label]'));
  const visible = els.filter(el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  });
  const labelFor = (el) => {
    if (!el) return '';
    if (el.labels && el.labels.length) return Array.from(el.labels).map(x => x.innerText.trim()).join(' ');
    const id = el.getAttribute('id');
    if (id) {
      const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (lab) return lab.innerText.trim();
    }
    const parent = el.closest('label');
    return parent ? parent.innerText.trim() : '';
  };
  const roleFor = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (['submit','button','reset'].includes(t)) return 'button';
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      return 'textbox';
    }
    return null;
  };
  const nameFor = (el) => {
    return (el.getAttribute('aria-label') || labelFor(el) || el.innerText || el.getAttribute('value') || el.getAttribute('placeholder') || '').trim();
  };
  return visible.slice(0, 80).map((el, index) => {
    const r = el.getBoundingClientRect();
    return {
      index,
      tag: el.tagName.toLowerCase(),
      role: roleFor(el),
      accessible_name: nameFor(el),
      text: (el.innerText || '').trim().slice(0, 300),
      label: labelFor(el).slice(0, 300),
      name_attr: el.getAttribute('name'),
      input_type: el.getAttribute('type'),
      placeholder: el.getAttribute('placeholder'),
      aria_label: el.getAttribute('aria-label'),
      href: el.getAttribute('href'),
      bbox: {x: r.x + r.width/2, y: r.y + r.height/2, width: r.width, height: r.height}
    };
  });
}
"""


class PlaywrightSurface(Surface):
    def __init__(self, headed: bool = False, slow_mo: int = 0):
        self.headed = headed
        self.slow_mo = slow_mo
        self._pw = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self, entry_point: str) -> None:
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(headless=not self.headed, slow_mo=self.slow_mo)
        self.context = await self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = await self.context.new_page()
        await self.page.goto(entry_point, wait_until="domcontentloaded")

    def _require_page(self) -> Page:
        if not self.page:
            raise RuntimeError("surface not started")
        return self.page

    async def observe(self, screenshot_path: str | None = None) -> Observation:
        page = self._require_page()
        if screenshot_path:
            Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=screenshot_path, full_page=True)
        controls = await page.evaluate(CONTROL_JS)
        text = await page.locator("body").inner_text()
        text = re.sub(r"\n{3,}", "\n\n", text).strip()[:12000]
        return Observation(
            url=page.url,
            title=await page.title(),
            visible_text=text,
            controls=[ObservedControl.model_validate(c) for c in controls],
            screenshot_path=screenshot_path,
        )

    async def _locator_from_control(self, control: ObservedControl) -> Locator:
        page = self._require_page()
        # The observation index is over *visible* candidate controls. Resolve the same
        # visible ordinal here instead of relying on hidden DOM nodes having the same index.
        candidates = page.locator('a,button,input,textarea,select,[role="button"],[role="link"],[tabindex],[aria-label]')
        visible_ordinal = -1
        for dom_index in range(await candidates.count()):
            candidate = candidates.nth(dom_index)
            if await candidate.is_visible():
                visible_ordinal += 1
                if visible_ordinal == control.index:
                    return candidate
        raise RuntimeError(f"visible control index {control.index} no longer exists")

    async def click_control(self, control: ObservedControl) -> None:
        loc = await self._locator_from_control(control)
        await loc.click(timeout=5000)
        await self._settle()

    async def type_control(self, control: ObservedControl, value: str) -> None:
        loc = await self._locator_from_control(control)
        await loc.fill(value, timeout=5000)

    async def extract_control(self, control: ObservedControl) -> str:
        loc = await self._locator_from_control(control)
        try:
            return (await loc.input_value()).strip()
        except Exception:
            return (await loc.inner_text()).strip()

    async def _settle(self) -> None:
        page = self._require_page()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        await page.wait_for_timeout(150)

    def locator_candidates_for(self, control: ObservedControl) -> TargetLocator:
        candidates: list[LocatorCandidate] = []
        description = control.accessible_name or control.label or control.text or control.name_attr or control.tag
        if control.label:
            candidates.append(LocatorCandidate(strategy="label", value=control.label))
        if control.role and control.accessible_name:
            candidates.append(
                LocatorCandidate(strategy="role_name", role=control.role, value=control.accessible_name)
            )
        if control.name_attr:
            candidates.append(LocatorCandidate(strategy="css", value=f'[name="{control.name_attr}"]'))
        if control.aria_label:
            safe_aria = control.aria_label.replace('"', '\"')
            candidates.append(LocatorCandidate(strategy="css", value=f'[aria-label="{safe_aria}"]'))
        if control.text and len(control.text) <= 120 and not control.aria_label:
            candidates.append(LocatorCandidate(strategy="text", value=control.text))
        if control.bbox:
            candidates.append(
                LocatorCandidate(
                    strategy="coordinates",
                    x=control.bbox["x"],
                    y=control.bbox["y"],
                )
            )
        # de-duplicate while preserving order
        unique: list[LocatorCandidate] = []
        seen = set()
        for c in candidates:
            key = (c.strategy, c.value, c.role, c.x, c.y)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return TargetLocator(description=description[:200], candidates=unique)

    async def _resolve(self, target: TargetLocator) -> tuple[Locator | None, LocatorCandidate]:
        page = self._require_page()
        last_error: Exception | None = None
        for candidate in target.candidates:
            try:
                if candidate.strategy == "label":
                    loc = page.get_by_label(candidate.value, exact=True).first
                elif candidate.strategy == "role_name":
                    loc = page.get_by_role(candidate.role, name=candidate.value, exact=True).first
                elif candidate.strategy == "text":
                    loc = page.get_by_text(candidate.value, exact=True).first
                elif candidate.strategy == "css":
                    loc = page.locator(candidate.value).first
                else:
                    return None, candidate
                await loc.wait_for(state="visible", timeout=1200)
                return loc, candidate
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise RuntimeError(f"no usable locator for {target.description}")

    async def click_locator(self, locator: TargetLocator) -> str:
        page = self._require_page()
        loc, used = await self._resolve(locator)
        if used.strategy == "coordinates":
            await page.mouse.click(used.x, used.y)
        else:
            assert loc is not None
            await loc.click(timeout=5000)
        await self._settle()
        return used.strategy

    async def type_locator(self, locator: TargetLocator, value: str) -> str:
        page = self._require_page()
        loc, used = await self._resolve(locator)
        if used.strategy == "coordinates":
            await page.mouse.click(used.x, used.y)
            await page.keyboard.press("Control+A")
            await page.keyboard.type(value)
        else:
            assert loc is not None
            await loc.fill(value, timeout=5000)
        return used.strategy

    async def extract_locator(self, locator: TargetLocator) -> tuple[str, str]:
        page = self._require_page()
        loc, used = await self._resolve(locator)
        if used.strategy == "coordinates":
            # Coordinates can click/type, but deterministic extraction needs a readable element.
            raise RuntimeError("coordinate-only locator cannot extract text deterministically")
        assert loc is not None
        try:
            value = (await loc.input_value()).strip()
        except Exception:
            value = (await loc.inner_text()).strip()
        return value, used.strategy

    async def wait(self, ms: int) -> None:
        await self._require_page().wait_for_timeout(ms)

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()
