#include "Engine.h"

#include <chrono>
#include <exception>

namespace rvc {

RunResult Engine::runOnce(Process& process, ProgressCallback onModule)
{
    RunResult result;

    std::string err;
    const std::vector<int> order = process.topologicalOrder(&err);
    if (!err.empty()) {
        result.error = err;
        return result;
    }

    process.clearOutputCache();

    for (const int nodeId : order) {
        ProcessNode* node = process.node(nodeId);
        if (!node || !node->module)
            continue;

        ModuleRunRecord record;
        record.nodeId = nodeId;
        record.name = node->module->name();

        // 从上游输出缓存收集本模块输入端口值
        std::map<std::string, PortValue> inputs;
        for (const auto& l : process.links()) {
            if (l.toNode == nodeId)
                inputs[l.toPort] = process.cachedOutput(l.fromNode, l.fromPort);
        }

        ModuleContext ctx(inputs, record.logs);
        const auto t0 = std::chrono::steady_clock::now();
        try {
            record.success = node->module->execute(ctx);
        } catch (const std::exception& e) {
            record.logs.push_back(std::string("exception: ") + e.what());
            record.success = false;
        } catch (...) {
            record.logs.push_back("unknown exception");
            record.success = false;
        }
        record.elapsedMs = std::chrono::duration<double, std::milli>(
                               std::chrono::steady_clock::now() - t0)
                               .count();

        // 缓存输出端口值，供下游模块读取
        for (const auto& [port, value] : ctx.outputs())
            process.setCachedOutput(nodeId, port, value);

        result.records.push_back(record);
        if (onModule)
            onModule(record);
    }

    result.ok = true;
    return result;
}

} // namespace rvc
