from pathlib import Path
import shutil


class LocalDocumentStorageAdapter:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str) -> Path:
        candidate = (self.root / path).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("storage path escapes storage root")
        return candidate

    def save_bytes(self, path: str, content: bytes) -> str:
        full_path = self._full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return path

    def read_bytes(self, path: str) -> bytes:
        return self._full_path(path).read_bytes()

    def save_text(self, path: str, content: str) -> str:
        return self.save_bytes(path, content.encode("utf-8"))

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def exists(self, path: str) -> bool:
        return self._full_path(path).exists()

    def delete(self, path: str) -> None:
        full_path = self._full_path(path)
        if full_path.is_dir():
            shutil.rmtree(full_path)
        elif full_path.exists():
            full_path.unlink()

    def delete_prefix(self, prefix: str) -> None:
        self.delete(prefix.rstrip("/"))
