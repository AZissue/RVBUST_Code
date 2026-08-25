#pragma once

#include <string>

namespace pcsearch::pipeline {

class Graph;

// Serialize a graph (nodes, parameters, edges) to compact JSON.
std::string saveGraphJson(const Graph& graph);

// Replace the graph contents from JSON produced by saveGraphJson.
// Returns false on parse/apply errors (details in graph.lastError()).
bool loadGraphJson(Graph& graph, const std::string& json_text);

}  // namespace pcsearch::pipeline
