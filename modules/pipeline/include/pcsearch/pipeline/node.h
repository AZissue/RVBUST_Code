#pragma once

#include "pcsearch/core_data/object.h"
#include "pcsearch/pipeline/params.h"

#include <memory>
#include <string>
#include <vector>

namespace pcsearch::pipeline {

class Node {
public:
    explicit Node(std::string id) : id_(std::move(id)) {}
    virtual ~Node() = default;

    // Called once by the graph after construction (virtual dispatch is safe
    // only after the object is fully built).
    virtual void setup() { params_.define(paramDefs()); }

    const std::string& id() const { return id_; }
    void setId(std::string id) { id_ = std::move(id); }

    virtual std::string type() const = 0;
    virtual std::string title() const = 0;
    virtual std::string category() const = 0;
    virtual std::string description() const { return {}; }
    virtual std::vector<ParamDef> paramDefs() const = 0;
    virtual std::size_t inputCount() const = 0;
    virtual std::size_t outputCount() const { return 1; }

    // Port type hints. Empty kind means "any" (compatible with everything).
    // Kinds let the UI colour ports and reject mismatched connections early.
    virtual std::vector<std::string> inputKinds() const { return {}; }
    virtual std::vector<std::string> outputKinds() const { return {}; }

    std::string inputKind(std::size_t index) const {
        const std::vector<std::string> kinds = inputKinds();
        return index < kinds.size() ? kinds[index] : std::string{};
    }
    std::string outputKind(std::size_t index) const {
        const std::vector<std::string> kinds = outputKinds();
        return index < kinds.size() ? kinds[index] : std::string{};
    }

    // inputs[i] is the ObjectList arriving at input port i.
    virtual core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                                     const Params& params) = 0;
    // One ObjectList per output port. Default implementation serves
    // single-output nodes; multi-output nodes (e.g. box_roi -> cloud + roi)
    // override this.
    virtual std::vector<core::ObjectList> executeAll(
        const std::vector<core::ObjectList>& inputs, const Params& params) {
        return {execute(inputs, params)};
    }

    Params& params() { return params_; }
    const Params& params() const { return params_; }

private:
    std::string id_;
    Params params_;
};

using NodePtr = std::unique_ptr<Node>;

}  // namespace pcsearch::pipeline
