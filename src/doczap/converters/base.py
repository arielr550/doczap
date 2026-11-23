from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from doczap.utils.file_ops import FileIdentity


class Converter(ABC):
    @abstractmethod
    def convert(
        self, input_path: str, output_path: str, *, overwrite: bool = False,
        replace_only: FileIdentity | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        raise NotImplementedError
