#pragma once

#include <cstddef>
#include <memory>
#include <vector>

// Shared, immutable heavy frame buffers.
//
// One 3D capture produces roughly 70 MB of contiguous payload: the organized
// grid (w*h*3 doubles ~ 37 MB at 1440x1080), the line-scan correspond map
// (~25 MB) and the filtered points/colors (~8 MB each at 682k points).  Before
// this header existed that payload was deep-copied at every hand-off —
// QtConcurrent's stored result, QFutureWatcher::result(), the captureComplete
// signal arguments, CameraManager's last-frame caches and CaptureFlow's
// transient state could all hold their own copy of the same bytes at once.
//
// Buffers are now passed as std::shared_ptr<const T>: handing one over costs a
// refcount bump, and the block is freed as soon as the last holder drops it.
namespace FrameBuffer {

using FloatBuf  = std::shared_ptr<const std::vector<float>>;
using DoubleBuf = std::shared_ptr<const std::vector<double>>;

// Wrap an owning vector into a shared buffer by moving it (no element copy).
FloatBuf  makeFloat(std::vector<float>&& data);
DoubleBuf makeDouble(std::vector<double>&& data);

// Deep copy a raw vector into a shared buffer (used by the SDK-facing code that
// already produced a local vector).
FloatBuf  copyFloat(const std::vector<float>& data);
DoubleBuf copyDouble(const std::vector<double>& data);

// Element count * sizeof(value_type) — for the runtime memory trace.
std::size_t bytes(const FloatBuf& b);
std::size_t bytes(const DoubleBuf& b);
std::size_t bytes(const std::vector<float>& v);
std::size_t bytes(const std::vector<double>& v);

// Single-slot holder for one heavy immutable buffer.
//
// publish() replaces the slot's reference (the previous block is freed as soon
// as no other holder remains); get() shares the existing block instead of
// copying it; clear() drops the slot's reference immediately, which is how the
// previous frame's buffers are released once a newer frame has arrived.
template <typename Vec>
class BufferSlot {
public:
    using Ptr = std::shared_ptr<const Vec>;
    using value_type = typename Vec::value_type;

    void publish(Ptr p) { m_ptr = std::move(p); }
    Ptr  get() const    { return m_ptr; }

    // True when the slot holds a non-empty buffer.
    bool valid() const { return m_ptr && !m_ptr->empty(); }

    // Drop our reference.  The block goes away unless somebody else still
    // holds it (a worker result, a signal argument, ...).
    void clear() { m_ptr.reset(); }

    std::size_t bytes() const
    {
        return m_ptr ? m_ptr->size() * sizeof(value_type) : 0;
    }

    // Number of owners of the current block; 1 means this slot is the last one.
    long useCount() const { return m_ptr.use_count(); }

private:
    Ptr m_ptr;
};

} // namespace FrameBuffer
