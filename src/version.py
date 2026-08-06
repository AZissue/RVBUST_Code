# -*- coding: utf-8 -*-
"""版本控制模块 — MultiCameraCalibration

版本规则（语义化版本）：
  - v0.0.x → 小改版（UI 微调、bugfix、文案调整）
  - v0.x.0 → 中等规模（功能优化、模块重构、新增小功能）
  - vx.0.0 → 大型功能/架构升级（全新模块、重大重构、里程碑发布）

当前版本: 1.0.0-alpha（P1 算法验证 — 双模式工作流架构）
"""

__VERSION__ = "1.0.0-alpha"
__VERSION_FILE__ = __file__


def get_version() -> str:
    """返回当前版本字符串（带 v 前缀）。"""
    return f"v{__VERSION__}"


def _parse_version() -> tuple:
    """解析当前版本为 (major, minor, patch) 整数元组。"""
    parts = __VERSION__.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump_patch() -> str:
    """小改版：patch + 1（如 v0.1.0 → v0.1.1）"""
    global __VERSION__
    major, minor, patch = _parse_version()
    patch += 1
    __VERSION__ = f"{major}.{minor}.{patch}"
    _write_version_file()
    return get_version()


def bump_minor() -> str:
    """中等规模：minor + 1, patch 归零（如 v0.1.1 → v0.2.0）"""
    global __VERSION__
    major, minor, patch = _parse_version()
    minor += 1
    patch = 0
    __VERSION__ = f"{major}.{minor}.{patch}"
    _write_version_file()
    return get_version()


def bump_major() -> str:
    """大型功能：major + 1, minor/patch 归零（如 v0.2.0 → v1.0.0）"""
    global __VERSION__
    major, minor, patch = _parse_version()
    major += 1
    minor = 0
    patch = 0
    __VERSION__ = f"{major}.{minor}.{patch}"
    _write_version_file()
    return get_version()


def _write_version_file():
    """将新版本写回本文件（自动持久化）。"""
    try:
        with open(__VERSION_FILE__, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            if line.startswith("__VERSION__"):
                new_lines.append(f'__VERSION__ = "{__VERSION__}"\n')
            else:
                new_lines.append(line)

        with open(__VERSION_FILE__, "w", encoding='utf-8') as f:
            f.writelines(new_lines)
    except Exception as e:
        # 写回失败不影响运行时，仅记录
        import warnings
        warnings.warn(f"版本文件写回失败: {e}")


def bump(rule: str) -> str:
    """按规则自动升级版本并持久化。

    Args:
        rule: "patch" | "minor" | "major"

    Returns:
        新版本字符串（带 v 前缀）
    """
    if rule == "patch":
        return bump_patch()
    elif rule == "minor":
        return bump_minor()
    elif rule == "major":
        return bump_major()
    else:
        raise ValueError(f"未知版本规则: {rule}，请用 patch/minor/major")


if __name__ == "__main__":
    print(f"当前版本: {get_version()}")
    print("用法: from version import bump; bump('minor')")
