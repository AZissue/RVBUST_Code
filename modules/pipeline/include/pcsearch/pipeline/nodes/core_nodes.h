#pragma once

#include "pcsearch/pipeline/node.h"

#include <string>

namespace pcsearch::pipeline {

class LoadCloudNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "load_cloud"; }
    std::string title() const override { return "Load Cloud"; }
    std::string category() const override { return "IO"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 0; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
    // Batch-source contract: a non-empty folder with mode stream/chunked
    // drives chunked execution (PROJECT §8.4); mode=all and single files run
    // in one pass.
    bool batchEnabled() const override;
    std::int64_t batchChunkSize() const override;
    std::int64_t batchTotal() const override;
};

class SaveCloudNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "save_cloud"; }
    std::string title() const override { return "Save Cloud"; }
    std::string category() const override { return "IO"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class RemoveInvalidNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "remove_invalid"; }
    std::string title() const override { return "Remove Invalid Points"; }
    std::string category() const override { return "Filters"; }
    std::vector<ParamDef> paramDefs() const override { return {}; }
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class VoxelDownsampleNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "voxel_downsample"; }
    std::string title() const override { return "Voxel Downsample"; }
    std::string category() const override { return "Filters"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class RandomDownsampleNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "random_downsample"; }
    std::string title() const override { return "Random Downsample"; }
    std::string category() const override { return "Filters"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class ZFilterNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "z_filter"; }
    std::string title() const override { return "Z Range Filter"; }
    std::string category() const override { return "Filters"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class BoxRoiNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "box_roi"; }
    std::string title() const override { return "Box ROI"; }
    std::string category() const override { return "ROI"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::size_t outputCount() const override { return 2; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud", "region"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>&, const Params&) override {
        return {};
    }
    std::vector<core::ObjectList> executeAll(
        const std::vector<core::ObjectList>& inputs, const Params& params) override;
};

class RoiCropNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "roi_crop"; }
    std::string title() const override { return "ROI Crop"; }
    std::string category() const override { return "ROI"; }
    std::vector<ParamDef> paramDefs() const override { return {}; }
    std::size_t inputCount() const override { return 2; }
    std::vector<std::string> inputKinds() const override { return {"cloud", "region"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class Display3DNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "display3d"; }
    std::string title() const override { return "Display 3D"; }
    std::string category() const override { return "Display"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::size_t outputCount() const override { return 0; }
    // any: display accepts cloud / region / future geometry layers so several
    // display3d nodes can stack on one viewport (PROJECT §8.7).
    std::vector<std::string> inputKinds() const override { return {"any"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
    void setup() override;
};

class PlaneDetectNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "plane_detect"; }
    std::string title() const override { return "Plane Detection"; }
    std::string category() const override { return "Segmentation"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class DbscanNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "dbscan"; }
    std::string title() const override { return "DBSCAN Clustering"; }
    std::string category() const override { return "Clustering"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

class EuclideanClusterNode final : public Node {
public:
    using Node::Node;
    std::string type() const override { return "euclidean_cluster"; }
    std::string title() const override { return "Euclidean Clustering"; }
    std::string category() const override { return "Clustering"; }
    std::vector<ParamDef> paramDefs() const override;
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    std::vector<std::string> outputKinds() const override { return {"cloud"}; }
    core::ObjectList execute(const std::vector<core::ObjectList>& inputs,
                             const Params& params) override;
};

void registerCoreNodes();

}  // namespace pcsearch::pipeline
