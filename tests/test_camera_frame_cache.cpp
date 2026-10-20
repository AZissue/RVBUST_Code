#include "test_camera_frame_cache.h"

#include <QtTest>

#include "logic/CameraFrameCache.h"

namespace {

CameraFrameCache::Frame makeFrame(std::vector<double> grid, int gw, int gh)
{
    CameraFrameCache::Frame f;
    f.gridPoints = FrameBuffer::makeDouble(std::move(grid));
    f.gridW = gw;
    f.gridH = gh;
    return f;
}

} // namespace

void TestCameraFrameCache::emptyCacheReportsNothing()
{
    CameraFrameCache cache;
    FrameBuffer::DoubleBuf buf;
    int w = -1, h = -1;

    QVERIFY(!cache.grid(buf, w, h));
    QVERIFY(!buf);
    QVERIFY(!cache.correspond(buf, w, h));
    QVERIFY(cache.gridAligned());          // default: the grid is image-ordered
    QCOMPARE(cache.bytes(), std::size_t(0));

    const auto markers = cache.nativeMarkers();
    QVERIFY(markers.first.empty());
    QVERIFY(markers.second.empty());
}

void TestCameraFrameCache::publishSharesWithoutCopying()
{
    const auto grid = FrameBuffer::makeDouble(std::vector<double>(300, 1.5));
    CameraFrameCache::Frame f;
    f.gridPoints = grid;
    f.gridW = 10;
    f.gridH = 10;

    CameraFrameCache cache;
    cache.publish(f);

    FrameBuffer::DoubleBuf out;
    int w = 0, h = 0;
    QVERIFY(cache.grid(out, w, h));
    QCOMPARE(w, 10);
    QCOMPARE(h, 10);
    QCOMPARE(out->size(), std::size_t(300));
    // get() hands out the same block: a read is a refcount bump, not a copy.
    QCOMPARE(out.get(), grid.get());
    QVERIFY(out.use_count() >= 2);
}

void TestCameraFrameCache::republishReleasesThePreviousFrame()
{
    CameraFrameCache cache;
    cache.publish(makeFrame(std::vector<double>(100, 1.0), 4, 5));

    FrameBuffer::DoubleBuf first;
    int w = 0, h = 0;
    QVERIFY(cache.grid(first, w, h));
    QCOMPARE(first->size(), std::size_t(100));

    cache.publish(makeFrame(std::vector<double>(10, 2.0), 2, 5));

    FrameBuffer::DoubleBuf second;
    QVERIFY(cache.grid(second, w, h));
    QCOMPARE(w, 2);
    QCOMPARE(second->size(), std::size_t(10));
    QVERIFY(second.get() != first.get());
    // The cache dropped its reference to the old block; only `first` keeps it.
    QCOMPARE(first.use_count(), 1L);
}

void TestCameraFrameCache::correspondAndAlignmentAreReported()
{
    auto cmap = FrameBuffer::makeDouble(std::vector<double>(18, 3.0));
    CameraFrameCache::Frame f = makeFrame(std::vector<double>(9, 0.0), 1, 3);
    f.correspondMap = cmap;
    f.cmW = 3;
    f.cmH = 6;
    f.gridAligned = false;

    CameraFrameCache cache;
    cache.publish(std::move(f));

    QVERIFY(!cache.gridAligned());
    FrameBuffer::DoubleBuf out;
    int w = 0, h = 0;
    QVERIFY(cache.correspond(out, w, h));
    QCOMPARE(out.get(), cmap.get());
    QCOMPARE(w, 3);
    QCOMPARE(h, 6);
}

void TestCameraFrameCache::bytesIncludeEveryCachedPart()
{
    CameraFrameCache::Frame f = makeFrame(std::vector<double>(100, 0.0), 5, 20);
    f.correspondMap = FrameBuffer::makeDouble(std::vector<double>(50, 0.0));
    f.nativePixels = std::vector<float>(10, 0.0f);
    f.nativePoints = std::vector<float>(20, 0.0f);

    CameraFrameCache cache;
    cache.publish(std::move(f));

    const std::size_t expected = 100 * sizeof(double)   // grid
                               + 50 * sizeof(double)    // correspond
                               + 10 * sizeof(float)     // native pixels
                               + 20 * sizeof(float);    // native points
    QCOMPARE(cache.bytes(), expected);
}

void TestCameraFrameCache::clearDropsEverything()
{
    CameraFrameCache::Frame f = makeFrame(std::vector<double>(100, 0.0), 5, 20);
    f.correspondMap = FrameBuffer::makeDouble(std::vector<double>(50, 0.0));
    f.nativePixels = {1.0f, 2.0f};
    f.nativePoints = {3.0f, 4.0f, 5.0f};

    CameraFrameCache cache;
    cache.publish(std::move(f));
    QVERIFY(cache.bytes() > 0);

    cache.clear();

    FrameBuffer::DoubleBuf buf;
    int w = -1, h = -1;
    QVERIFY(!cache.grid(buf, w, h));
    QVERIFY(!cache.correspond(buf, w, h));
    QVERIFY(cache.gridAligned());          // back to the pre-capture state
    QCOMPARE(cache.bytes(), std::size_t(0));
    QVERIFY(cache.nativeMarkers().first.empty());
    QVERIFY(cache.nativeMarkers().second.empty());
}

void TestCameraFrameCache::nativeMarkersAreCopied()
{
    CameraFrameCache::Frame f = makeFrame(std::vector<double>(3, 0.0), 1, 1);
    f.nativePixels = {10.0f, 20.0f};
    f.nativePoints = {1.0f, 2.0f, 3.0f};

    CameraFrameCache cache;
    cache.publish(std::move(f));

    auto markers = cache.nativeMarkers();
    QCOMPARE(markers.first.size(), std::size_t(2));
    QCOMPARE(markers.first[1], 20.0f);
    QCOMPARE(markers.second.size(), std::size_t(3));

    // A caller mutating its copy must not change the cache.
    markers.first[0] = -1.0f;
    QCOMPARE(cache.nativeMarkers().first[0], 10.0f);
}
