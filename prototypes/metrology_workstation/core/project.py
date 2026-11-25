from __future__ import annotations

import json
from pathlib import Path


class ProjectRepository:
    FILE_NAME = "project.json"

    def create(self, directory: str | Path, name: str, part_number: str = "") -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        for folder in ("raw", "reconstruction", "models", "cad", "measurement", "reports", "logs", "database"):
            (root / folder).mkdir(exist_ok=True)
        path = root / self.FILE_NAME
        self.save(path, {"name": name, "part_number": part_number, "version": 1, "assets": []})
        return path

    def save(self, path: str | Path, data: dict) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def load(self, path: str | Path) -> dict:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("项目文件缺少有效的项目名称")
        return data
