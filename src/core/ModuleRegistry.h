#pragma once

// 模块注册表：工厂注册 + 按类别枚举（UI 工具箱的数据源）。

#include <map>
#include <string>
#include <vector>

#include "ModuleBase.h"

namespace rvc {

struct ModuleInfo {
    std::string  typeId;       // 全局唯一类型 ID
    std::string  category;     // 分类（工具箱分组），如 "采集" / "显示"
    std::string  displayName;  // 显示名
    ModuleFactory factory;
};

class ModuleRegistry {
public:
    static ModuleRegistry& instance()
    {
        static ModuleRegistry reg;
        return reg;
    }

    void registerType(ModuleInfo info)
    {
        infos_[info.typeId] = std::move(info);
    }

    // 便捷模板：按模块类注册
    template <typename T>
    void reg(const std::string& typeId, const std::string& category, const std::string& displayName)
    {
        registerType(ModuleInfo{typeId, category, displayName, [] { return std::make_unique<T>(); }});
    }

    const ModuleInfo* find(const std::string& typeId) const
    {
        auto it = infos_.find(typeId);
        return it != infos_.end() ? &it->second : nullptr;
    }

    ModulePtr create(const std::string& typeId) const
    {
        const ModuleInfo* info = find(typeId);
        return info ? info->factory() : nullptr;
    }

    std::vector<ModuleInfo> all() const
    {
        std::vector<ModuleInfo> out;
        out.reserve(infos_.size());
        for (const auto& [id, info] : infos_)
            out.push_back(info);
        return out;
    }

    // 按类别分组枚举（工具箱用），保持注册类别出现顺序
    std::map<std::string, std::vector<ModuleInfo>> byCategory() const
    {
        std::map<std::string, std::vector<ModuleInfo>> grouped;
        for (const auto& [id, info] : infos_)
            grouped[info.category].push_back(info);
        return grouped;
    }

private:
    std::map<std::string, ModuleInfo> infos_;
};

} // namespace rvc
