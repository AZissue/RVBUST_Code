#include "logic/CameraFrameCache.h"

void CameraFrameCache::publish(Frame frame)
{
    m_grid.publish(std::move(frame.gridPoints));
    m_gridW = frame.gridW;
    m_gridH = frame.gridH;
    m_correspond.publish(std::move(frame.correspondMap));
    m_cmW = frame.cmW;
    m_cmH = frame.cmH;
    m_gridAligned = frame.gridAligned;
    m_nativePixels = std::move(frame.nativePixels);
    m_nativePoints = std::move(frame.nativePoints);
}

bool CameraFrameCache::grid(FrameBuffer::DoubleBuf& xyzMm, int& w, int& h) const
{
    if (!m_grid.valid())
        return false;
    xyzMm = m_grid.get();   // refcount bump, not a 37 MB copy
    w = m_gridW;
    h = m_gridH;
    return true;
}

bool CameraFrameCache::correspond(FrameBuffer::DoubleBuf& cmap, int& w, int& h) const
{
    if (!m_correspond.valid())
        return false;
    cmap = m_correspond.get();
    w = m_cmW;
    h = m_cmH;
    return true;
}

std::pair<std::vector<float>, std::vector<float>> CameraFrameCache::nativeMarkers() const
{
    return {m_nativePixels, m_nativePoints};
}

std::size_t CameraFrameCache::bytes() const
{
    return m_grid.bytes() + m_correspond.bytes()
         + FrameBuffer::bytes(m_nativePixels)
         + FrameBuffer::bytes(m_nativePoints);
}

void CameraFrameCache::clear()
{
    m_grid.clear();
    m_gridW = m_gridH = 0;
    m_correspond.clear();
    m_cmW = m_cmH = 0;
    m_gridAligned = true;
    m_nativePixels.clear();
    m_nativePixels.shrink_to_fit();
    m_nativePoints.clear();
    m_nativePoints.shrink_to_fit();
}
