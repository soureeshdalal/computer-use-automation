"""Playwright surface adapter with semantic observation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from computer_use.models import LocatorCandidate
from computer_use.safety.policy import PolicyEngine


@dataclass
class ObservedElement:
    element_id: str
    role: str
    name: str
    tag: str
    input_type: str | None = None
    value: str | None = None
    href: str | None = None
    enabled: bool = True


@dataclass
class PageObservation:
    url: str
    title: str
    visible_text_excerpt: str
    elements: list[ObservedElement] = field(default_factory=list)
    dialog_text: str | None = None


class PlaywrightSurface:
    def __init__(
        self,
        policy: PolicyEngine,
        headless: bool = True,
        base_url: str = "http://127.0.0.1:8765",
    ) -> None:
        self.policy = policy
        self.headless = headless
        self.base_url = base_url.rstrip("/")
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None
        self._element_map: dict[str, ObservedElement] = {}

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        context = self._browser.new_context(viewport={"width": 1280, "height": 800})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = context.new_page()

    def stop(self, trace_path: str | None = None) -> None:
        if self.page and trace_path:
            context = self.page.context
            context.tracing.stop(path=trace_path)
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self.page = None

    def navigate(self, path: str) -> None:
        assert self.page is not None
        url = path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))
        self.policy.check_url(url)
        self.page.goto(url, wait_until="domcontentloaded")

    def observe(self) -> PageObservation:
        assert self.page is not None
        self._element_map.clear()
        elements: list[ObservedElement] = []
        selectors = "button, a, input, select, textarea, [role='dialog']"
        handles = self.page.locator(selectors).all()
        for index, handle in enumerate(handles, start=1):
            if not handle.is_visible():
                continue
            tag = handle.evaluate("el => el.tagName.toLowerCase()")
            role = handle.get_attribute("role") or _default_role(tag)
            name = (
                handle.get_attribute("aria-label")
                or handle.get_attribute("name")
                or (handle.inner_text(timeout=500).strip() if tag in {"button", "a"} else "")
                or handle.get_attribute("placeholder")
                or ""
            )
            input_type = handle.get_attribute("type")
            value = None
            if tag == "input":
                try:
                    value = handle.input_value(timeout=500)
                except Exception:
                    value = handle.get_attribute("value")
            element_id = f"e{index}"
            observed = ObservedElement(
                element_id=element_id,
                role=role,
                name=name.strip(),
                tag=tag,
                input_type=input_type,
                value=value,
                href=handle.get_attribute("href"),
                enabled=handle.is_enabled(),
            )
            elements.append(observed)
            self._element_map[element_id] = observed

        dialog = self.page.locator("[role='dialog']").first
        dialog_text = None
        if dialog.count() > 0 and dialog.is_visible():
            dialog_text = dialog.inner_text(timeout=1000)

        body_text = self.page.locator("body").inner_text(timeout=2000)
        excerpt = " ".join(body_text.split())[:500]
        return PageObservation(
            url=self.page.url,
            title=self.page.title(),
            visible_text_excerpt=excerpt,
            elements=elements,
            dialog_text=dialog_text,
        )

    def build_targets(self, element_id: str) -> list[LocatorCandidate]:
        element = self._element_map.get(element_id)
        if not element:
            return []
        candidates: list[LocatorCandidate] = []
        if element.name:
            candidates.append(
                LocatorCandidate(
                    strategy="role_name",
                    role=element.role,
                    name=element.name,
                    rationale="Primary accessible role and name pairing.",
                )
            )
            candidates.append(
                LocatorCandidate(
                    strategy="label",
                    label=element.name,
                    rationale="Form label or aria-label text.",
                )
            )
        if element.input_type == "password":
            candidates.append(
                LocatorCandidate(
                    strategy="css_attr",
                    attribute="type",
                    value="password",
                    rationale="Password field fallback.",
                )
            )
        if element.tag in {"button", "a"} and element.name:
            candidates.append(
                LocatorCandidate(
                    strategy="text",
                    text=element.name,
                    rationale="Visible control text for legacy buttons/links.",
                )
            )
        return candidates

    def click_element(self, element_id: str) -> None:
        assert self.page is not None
        handle = self._resolve_handle(element_id)
        handle.click(timeout=self.policy.step_timeout_ms)
        self.page.wait_for_load_state("domcontentloaded")

    def type_element(self, element_id: str, text: str, clear: bool = True) -> None:
        assert self.page is not None
        handle = self._resolve_handle(element_id)
        if clear:
            handle.fill(text, timeout=self.policy.step_timeout_ms)
        else:
            handle.type(text, timeout=self.policy.step_timeout_ms)

    def extract_by_selector(self, css_selector: str) -> str:
        assert self.page is not None
        locator = self.page.locator(css_selector).first
        locator.wait_for(state="visible", timeout=self.policy.step_timeout_ms)
        return locator.inner_text(timeout=self.policy.step_timeout_ms).strip()

    def page_contains(self, text: str) -> bool:
        assert self.page is not None
        return text.lower() in self.page.content().lower()

    def screenshot(self, path: str) -> None:
        assert self.page is not None
        self.page.screenshot(path=path, full_page=True)

    def current_url(self) -> str:
        assert self.page is not None
        return self.page.url

    def _resolve_handle(self, element_id: str):
        assert self.page is not None
        element = self._element_map.get(element_id)
        if not element:
            raise KeyError(f"Unknown element id {element_id}")
        if element.name:
            locator = self.page.get_by_role(element.role, name=element.name, exact=False)
            if locator.count() >= 1:
                return locator.first
        if element.tag == "input" and element.name:
            return self.page.get_by_label(element.name).first
        return self.page.locator(element.tag).filter(has_text=element.name).first

    def resolve_locator(self, candidates: list[LocatorCandidate]):
        assert self.page is not None
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                locator = _candidate_to_locator(self.page, candidate)
                locator.first.wait_for(state="visible", timeout=self.policy.step_timeout_ms)
                return locator.first
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise RuntimeError(f"Unable to resolve locator candidates: {last_error}")

    def click_locator(self, candidates: list[LocatorCandidate]) -> None:
        handle = self.resolve_locator(candidates)
        handle.click(timeout=self.policy.step_timeout_ms)

    def type_locator(
        self, candidates: list[LocatorCandidate], text: str, clear: bool = True
    ) -> None:
        handle = self.resolve_locator(candidates)
        if clear:
            handle.fill(text, timeout=self.policy.step_timeout_ms)
        else:
            handle.type(text, timeout=self.policy.step_timeout_ms)


def _default_role(tag: str) -> str:
    mapping = {
        "button": "button",
        "a": "link",
        "input": "textbox",
        "select": "combobox",
        "textarea": "textbox",
    }
    return mapping.get(tag, tag)


def _candidate_to_locator(page: Page, candidate: LocatorCandidate):
    if candidate.strategy == "role_name" and candidate.role and candidate.name:
        return page.get_by_role(candidate.role, name=candidate.name, exact=False)
    if candidate.strategy == "label" and candidate.label:
        return page.get_by_label(candidate.label, exact=False)
    if candidate.strategy == "placeholder" and candidate.placeholder:
        return page.get_by_placeholder(candidate.placeholder, exact=False)
    if candidate.strategy == "text" and candidate.text:
        return page.get_by_text(candidate.text, exact=False)
    if candidate.strategy == "css_attr" and candidate.attribute and candidate.value:
        return page.locator(f"[{candidate.attribute}='{candidate.value}']")
    raise ValueError(f"Unsupported locator candidate: {candidate}")
