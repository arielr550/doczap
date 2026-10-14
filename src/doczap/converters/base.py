from __future__ import annotations

import threading
from abc import ABC, abstractmethod


class Converter(ABC):
    @abstractmethod
    def convert(
        self, input_path: str, output_path: str, *, overwrite: bool = False,
        cancel: threading.Event | None = None,
    ) -> None:
        raise NotImplementedError
