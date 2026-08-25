#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace pcsearch::core {

// A subset of points plus geometry parameters produced by a step/node.
// `indices` always refer to the point set of the owning PointCloudObject,
// which keeps results traceable back to the original file.
struct Region {
    enum class Kind {
        All,          // whole cloud
        Manual,       // user selection (2D box / lasso, etc.)
        Cluster,      // density / euclidean cluster
        Plane,        // params: [a,b,c,d] with a*x+b*y+c*z+d=0, unit normal
        Sphere,       // params: [cx,cy,cz,r]
        Cylinder,     // params: [ax,ay,az,bx,by,bz,r]
        Cuboid,       // params: OBB/AABB (to be defined in shapes module)
        Circle,       // 2D circle on a plane: [cx,cy,cz,nx,ny,nz,r]
        Rectangle,    // 2D rectangle on a plane (to be defined in shapes module)
        Hole,         // params: [cx,cy,cz,nx,ny,nz,size...] (to be defined)
    };

    std::string id;
    std::string label;
    Kind kind = Kind::Manual;
    std::vector<std::int64_t> indices;
    std::vector<double> params;
    std::string provenance;  // node id that produced this region
    std::int64_t pointCount() const { return static_cast<std::int64_t>(indices.size()); }
};

}  // namespace pcsearch::core

