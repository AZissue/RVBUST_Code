from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    sample: str | None = None


class ProjectLibrary:
    def __init__(self, directory: Path):
        self.directory = directory

    def create(self, name: str) -> Project:
        name = name.strip()
        if not name:
            raise ValueError("请输入工程名称。")
        destination = self.directory / f"{uuid4().hex}.rvcproj"
        data = json.dumps({"version": 1, "name": name}, ensure_ascii=False)
        self._write_project(destination, data.encode("utf-8"))
        return Project(name, destination.resolve())

    def install_demo(self, source: Path) -> None:
        destination = self.directory / source.name
        if not destination.exists():
            self._write_project(destination, source.read_bytes())

    def _write_project(self, destination: Path, data: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb", dir=self.directory, delete=False
        ) as file:
            pending = Path(file.name)
            try:
                file.write(data)
                file.close()
                pending.replace(destination)
            finally:
                file.close()
                pending.unlink(missing_ok=True)

    @staticmethod
    def load(path: Path) -> Project:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("工程文件格式或版本无效。")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("工程文件缺少有效的工程名称。")
        sample = data.get("sample")
        if sample not in (None, "flange"):
            raise ValueError("工程文件使用了未知的演示模型。")
        return Project(name.strip(), path.resolve(), sample)

    def list_projects(self) -> list[Project]:
        projects = []
        for path in self.directory.glob("*.rvcproj"):
            try:
                projects.append(self.load(path))
            except (OSError, ValueError):
                # A damaged project should not prevent access to other projects.
                continue
        return sorted(projects, key=lambda project: (project.name.casefold(), project.path))
