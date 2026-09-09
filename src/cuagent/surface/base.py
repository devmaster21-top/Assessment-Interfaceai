from __future__ import annotations

from abc import ABC, abstractmethod

from cuagent.models import Observation, ObservedControl, TargetLocator


class Surface(ABC):
    @abstractmethod
    async def start(self, entry_point: str) -> None: ...

    @abstractmethod
    async def observe(self, screenshot_path: str | None = None) -> Observation: ...

    @abstractmethod
    async def click_control(self, control: ObservedControl) -> None: ...

    @abstractmethod
    async def type_control(self, control: ObservedControl, value: str) -> None: ...

    @abstractmethod
    async def extract_control(self, control: ObservedControl) -> str: ...

    @abstractmethod
    async def click_locator(self, locator: TargetLocator) -> str: ...

    @abstractmethod
    async def type_locator(self, locator: TargetLocator, value: str) -> str: ...

    @abstractmethod
    async def extract_locator(self, locator: TargetLocator) -> tuple[str, str]: ...

    @abstractmethod
    async def wait(self, ms: int) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
