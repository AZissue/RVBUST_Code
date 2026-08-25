#include "pcsearch/pipeline/solution.h"

#include "pcsearch/pipeline/graph.h"
#include "pcsearch/pipeline/json.h"

#include <string>
#include <variant>

namespace pcsearch::pipeline {

namespace {

using json::Value;

std::string paramTypeName(const ParamValue& v) {
    switch (v.index()) {
        case 0: return "double";
        case 1: return "int";
        case 2: return "bool";
        case 3: return "string";
    }
    return "string";
}

Value paramValueToJson(const ParamValue& v) {
    switch (v.index()) {
        case 0: return Value::number(std::get<double>(v));
        case 1: return Value::number(static_cast<double>(std::get<int>(v)));
        case 2: return Value::boolean(std::get<bool>(v));
        case 3: return Value::string(std::get<std::string>(v));
    }
    return Value::null();
}

ParamValue paramValueFromJson(const std::string& type, const Value& v) {
    if (type == "double") return ParamValue{v.asNumber()};
    if (type == "int") return ParamValue{static_cast<int>(v.asNumber())};
    if (type == "bool") return ParamValue{v.asBool()};
    if (type == "string") return ParamValue{v.asString()};
    throw json::JsonError("unknown param type: " + type);
}

}  // namespace

std::string saveGraphJson(const Graph& graph) {
    Value root = Value::object();
    Value nodes = Value::array();
    for (const Node* node : graph.nodes()) {
        Value n = Value::object();
        n["type"] = Value::string(node->type());
        n["id"] = Value::string(node->id());
        Value params = Value::object();
        for (const auto& [name, value] : node->params().values()) {
            Value p = Value::object();
            p["type"] = Value::string(paramTypeName(value));
            p["value"] = paramValueToJson(value);
            params[name] = p;
        }
        n["params"] = std::move(params);
        nodes.asArray().push_back(std::move(n));
    }
    root["nodes"] = std::move(nodes);

    Value edges = Value::array();
    for (const auto& e : graph.edges()) {
        Value edge = Value::object();
        edge["from"] = Value::string(e.from_id);
        edge["from_port"] = Value::number(static_cast<double>(e.from_port));
        edge["to"] = Value::string(e.to_id);
        edge["to_port"] = Value::number(static_cast<double>(e.to_port));
        edges.asArray().push_back(std::move(edge));
    }
    root["edges"] = std::move(edges);
    return root.dump();
}

bool loadGraphJson(Graph& graph, const std::string& json_text) {
    try {
        const Value root = Value::parse(json_text);
        if (!root.isObject()) throw json::JsonError("solution root must be an object");
        const Value* nodes = root.find("nodes");
        if (!nodes || !nodes->isArray()) throw json::JsonError("missing nodes array");

        graph.clear();
        for (const Value& n : nodes->asArray()) {
            const Value* type = n.find("type");
            const Value* id = n.find("id");
            if (!type || !type->isString() || !id || !id->isString()) {
                throw json::JsonError("node missing type/id");
            }
            Node* node = graph.addNode(type->asString(), id->asString());
            if (!node) {
                throw json::JsonError("cannot create node '" + id->asString() +
                                      "' (type '" + type->asString() + "')");
            }
            const Value* params = n.find("params");
            if (params && params->isObject()) {
                for (const auto& [name, p] : params->asObject()) {
                    if (!p.isObject()) continue;
                    const Value* ptype = p.find("type");
                    const Value* pvalue = p.find("value");
                    if (!ptype || !pvalue || !ptype->isString()) continue;
                    try {
                        node->params().set(
                            name, paramValueFromJson(ptype->asString(), *pvalue));
                    } catch (const std::exception&) {
                        // Unknown parameter for this node type: ignore.
                    }
                }
            }
        }

        const Value* edges = root.find("edges");
        if (edges && edges->isArray()) {
            for (const Value& e : edges->asArray()) {
                const Value* from = e.find("from");
                const Value* from_port = e.find("from_port");
                const Value* to = e.find("to");
                const Value* to_port = e.find("to_port");
                if (!from || !from_port || !to || !to_port) continue;
                if (!graph.connect(from->asString(), static_cast<int>(from_port->asNumber()),
                                   to->asString(), static_cast<int>(to_port->asNumber()))) {
                    throw json::JsonError("cannot restore edge: " +
                                          graph.connectError());
                }
            }
        }
        return true;
    } catch (const std::exception& e) {
        graph.clear();
        graph.markError(e.what());
        return false;
    }
}

}  // namespace pcsearch::pipeline
