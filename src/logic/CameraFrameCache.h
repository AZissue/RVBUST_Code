#pragma once

#include <cstddef>
#include <utility>
#include <vector>

#include "logic/FrameBuffer.h"

// Last-frame lookup data produced by a 3D capture:
//   * the organized grid (image-ordered, mm) used for pixel <-> 3D lookup;
//   * the line-scan CorrespondMap (3D point index -> 2D pixel), when available;
//   * the camera's native concentric-circle detection result.
//
// This used to be eight members of CameraManager plus four accessors.  Keeping
// it here means CameraManager is only the device facade and this cache can be
// exercised without RVC/SDK: the buffers are shared (a read is a refcount bump,
// never a 37 MB copy) and replacing a frame releases the previous block at a
// defined point.
class CameraFrameCache {
public:
    // One capture's payload.  Heavy buffers are moved in, not copied; the
    // small native-detection vectors are moved too.
    struct Frame {
        FrameBuffer::DoubleBuf gridPoints;   // w*h*3, empty when no grid
        int gridW = 0;
        int gridH = 0;
        FrameBuffer::DoubleBuf correspondMap; // w*h*2, empty when aligned grid
        int cmW = 0;
        int cmH = 0;
        bool gridAligned = true;
        std::vector<float> nativePixels;     // flat [x0,y0,...] in px
        std::vector<float> nativePoints;     // flat [x0,y0,z0,...] in mm
    };

    // Replace the cached frame; the previous buffers are freed unless another
    // holder (a worker result, a signal argument) still references them.
    void publish(Frame frame);

    bool grid(FrameBuffer::DoubleBuf& xyzMm, int& w, int& h) const;
    bool correspond(FrameBuffer::DoubleBuf& cmap, int& w, int& h) const;
    // True when the grid is image-ordered; false exactly when correspond data
    // is available instead.
    bool gridAligned() const { return m_gridAligned; }

    // Copies the (small, <=1000 entries) native detection result, as before.
    std::pair<std::vector<float>, std::vector<float>> nativeMarkers() const;

    // Bytes held by the cached buffers, for the [MEM] runtime trace.
    std::size_t bytes() const;

    // Drop every reference now (camera teardown), instead of leaving tens of
    // MB alive until the next capture.
    void clear();

private:
    FrameBuffer::BufferSlot<std::vector<double>> m_grid;
    int m_gridW = 0;
    int m_gridH = 0;
    FrameBuffer::BufferSlot<std::vector<double>> m_correspond;
    int m_cmW = 0;
    int m_cmH = 0;
    bool m_gridAligned = true;
    std::vector<float> m_nativePixels;
    std::vector<float> m_nativePoints;
};
