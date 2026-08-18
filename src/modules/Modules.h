#pragma once

// 内置模块统一注册入口（工具箱 / Solution 加载 / 自测共用）。

namespace rvc {

// 将所有内置模块类型注册到 ModuleRegistry（幂等，可重复调用）
void registerBuiltinModules();

} // namespace rvc
