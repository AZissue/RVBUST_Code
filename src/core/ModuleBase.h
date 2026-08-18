#pragma once

// 模块基类与模块执行上下文。
// 所有流程模块（采集、算法、显示等）均继承 ModuleBase。
//
// 参数机制：模块构造时通过 declareParam() 声明参数（ParamDesc），
// getParam/setParam 通用读写；saveParams/loadParams 遍历声明表通用实现，
// UI 参数面板按 ParamDesc 自动生成编辑控件，模块无需各自特判。

#include <functional>
#include <map>
#include <memory>
#include <string>
#include <variant>
#include <vector>

#include <QJsonObject>

#include "DataTypes.h"

namespace rvc {

// 端口声明：名字 + 数据类型 + 是否可选（可选输入允许未连接）
struct PortDecl {
    std::string name;
    DataType   type;
    bool       optional = false;
};

// ---- 参数描述机制 ----

enum class ParamType { Double, Int, Bool, String, FilePath };

using ParamValue = std::variant<double, int, bool, std::string>;

struct ParamDesc {
    std::string name;    // 参数键（同时作为面板标签）
    ParamType   type = ParamType::Double;
    ParamValue  defaultValue;
    double      minValue = -1e9;  // 数值类型的编辑范围
    double      maxValue = 1e9;
};

// 模块执行上下文：由执行引擎构造并传入 execute()。
// 提供读输入端口值、写输出端口值、日志输出三种能力。
class ModuleContext {
public:
    ModuleContext(const std::map<std::string, PortValue>& inputs, std::vector<std::string>& logs)
        : inputs_(inputs), logs_(logs)
    {
    }

    // 读取输入端口值；端口不存在或无有效数据时返回无效 PortValue
    PortValue input(const std::string& port) const
    {
        auto it = inputs_.find(port);
        return it != inputs_.end() ? it->second : PortValue{};
    }

    bool hasInput(const std::string& port) const
    {
        auto it = inputs_.find(port);
        return it != inputs_.end() && it->second.isValid();
    }

    // 写输出端口值（execute 返回后由引擎缓存，供下游模块读取）
    void setOutput(const std::string& port, PortValue value) { outputs_[port] = std::move(value); }

    const std::map<std::string, PortValue>& outputs() const { return outputs_; }

    // 输出执行日志（由引擎收集，UI 层展示到日志栏）
    void log(const std::string& msg) { logs_.push_back(msg); }

private:
    const std::map<std::string, PortValue>& inputs_;
    std::map<std::string, PortValue>        outputs_;
    std::vector<std::string>&               logs_;
};

// 模块基类
class ModuleBase {
public:
    virtual ~ModuleBase() = default;

    // 模块类型 ID（注册表键，全局唯一，如 "Acquisition.LoadPly"）
    virtual std::string typeId() const = 0;
    // 实例显示名（画布节点标题，默认等于类型显示名，可由 UI 改写）
    virtual std::string name() const { return displayName_; }
    void setName(const std::string& n) { displayName_ = n; }

    virtual std::vector<PortDecl> inputPorts() const = 0;
    virtual std::vector<PortDecl> outputPorts() const = 0;

    // 执行模块逻辑；返回 false 表示失败（原因应通过 ctx.log 输出）
    virtual bool execute(ModuleContext& ctx) = 0;

    // ---- 参数（通用机制，子类构造时 declareParam 声明即可）----

    const std::vector<ParamDesc>& paramDescs() const { return paramDescs_; }

    // 按名读取参数；不存在时返回 defaultValue 语义的空 string
    ParamValue getParam(const std::string& name) const
    {
        auto it = paramValues_.find(name);
        return it != paramValues_.end() ? it->second : ParamValue{std::string{}};
    }

    double getDouble(const std::string& name, double fallback = 0.0) const
    {
        const ParamValue v = getParam(name);
        if (const auto* p = std::get_if<double>(&v))
            return *p;
        return fallback;
    }
    int getInt(const std::string& name, int fallback = 0) const
    {
        const ParamValue v = getParam(name);
        if (const auto* p = std::get_if<int>(&v))
            return *p;
        return fallback;
    }
    bool getBool(const std::string& name, bool fallback = false) const
    {
        const ParamValue v = getParam(name);
        if (const auto* p = std::get_if<bool>(&v))
            return *p;
        return fallback;
    }
    std::string getString(const std::string& name) const
    {
        const ParamValue v = getParam(name);
        if (const auto* p = std::get_if<std::string>(&v))
            return *p;
        return {};
    }

    // 写参数；参数名不存在或类型不符返回 false
    bool setParam(const std::string& name, const ParamValue& value)
    {
        for (const auto& d : paramDescs_) {
            if (d.name == name) {
                // 类型须与声明一致（int 参数允许 double 写入时取整；
                // FilePath 底层存 std::string）
                if (d.type == ParamType::Int && std::holds_alternative<double>(value)) {
                    paramValues_[name] = static_cast<int>(std::get<double>(value));
                    return true;
                }
                const size_t expected = d.type == ParamType::FilePath
                                            ? static_cast<size_t>(ParamType::String)
                                            : static_cast<size_t>(d.type);
                if (expected != value.index())
                    return false;
                paramValues_[name] = value;
                return true;
            }
        }
        return false;
    }

    // 参数序列化（Solution 保存/加载）：通用遍历 ParamDesc
    virtual QJsonObject saveParams() const
    {
        QJsonObject obj;
        for (const auto& d : paramDescs_) {
            const ParamValue& v = getParam(d.name);
            switch (d.type) {
            case ParamType::Double:
                obj[QString::fromStdString(d.name)] = std::get<double>(v);
                break;
            case ParamType::Int:
                obj[QString::fromStdString(d.name)] = std::get<int>(v);
                break;
            case ParamType::Bool:
                obj[QString::fromStdString(d.name)] = std::get<bool>(v);
                break;
            case ParamType::String:
            case ParamType::FilePath:
                obj[QString::fromStdString(d.name)] =
                    QString::fromStdString(std::get<std::string>(v));
                break;
            }
        }
        return obj;
    }

    virtual void loadParams(const QJsonObject& obj)
    {
        for (const auto& d : paramDescs_) {
            const QString key = QString::fromStdString(d.name);
            if (!obj.contains(key))
                continue;
            const QJsonValue jv = obj[key];
            switch (d.type) {
            case ParamType::Double:
                setParam(d.name, jv.toDouble());
                break;
            case ParamType::Int:
                setParam(d.name, jv.toInt());
                break;
            case ParamType::Bool:
                setParam(d.name, jv.toBool());
                break;
            case ParamType::String:
            case ParamType::FilePath:
                setParam(d.name, jv.toString().toStdString());
                break;
            }
        }
    }

    // 构造期声明参数（当前值初始化为 defaultValue）。
    // public：允许 CloudUtils 等自由函数辅助批量声明参数组。
    void declareParam(const ParamDesc& desc)
    {
        paramDescs_.push_back(desc);
        paramValues_[desc.name] = desc.defaultValue;
    }

protected:
    std::string displayName_;

private:
    std::vector<ParamDesc>              paramDescs_;
    std::map<std::string, ParamValue>   paramValues_;
};

using ModulePtr = std::unique_ptr<ModuleBase>;
using ModuleFactory = std::function<ModulePtr()>;

} // namespace rvc
