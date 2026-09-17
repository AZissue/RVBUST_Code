#include "test_frame_buffer.h"

#include <QtTest>

#include "logic/FrameBuffer.h"

#include <vector>

void TestFrameBuffer::sharesWithoutCopying()
{
    const auto buf = FrameBuffer::makeFloat({1.0f, 2.0f, 3.0f});

    // A "hand-off" is a refcount bump, not a deep copy.
    FrameBuffer::FloatBuf handOff = buf;
    QCOMPARE(handOff.get(), buf.get());
    QCOMPARE(buf.use_count(), 2L);

    // The shared block is immutable, so no holder can observe a mutation.
    QCOMPARE(buf->size(), std::size_t(3));
    QCOMPARE((*buf)[2], 3.0f);
}

void TestFrameBuffer::makeMovesTheVector()
{
    std::vector<double> owning(1024, 2.5);
    const double* raw = owning.data();

    const auto buf = FrameBuffer::makeDouble(std::move(owning));
    QCOMPARE(buf->size(), std::size_t(1024));
    // Same heap block: the vector was moved into the shared_ptr, not copied.
    QCOMPARE(buf->data(), raw);
}

void TestFrameBuffer::byteAccounting()
{
    const auto f = FrameBuffer::makeFloat(std::vector<float>(300, 0.0f));
    const auto d = FrameBuffer::makeDouble(std::vector<double>(200, 0.0));

    QCOMPARE(FrameBuffer::bytes(f), std::size_t(300 * sizeof(float)));
    QCOMPARE(FrameBuffer::bytes(d), std::size_t(200 * sizeof(double)));
    QCOMPARE(FrameBuffer::bytes(FrameBuffer::FloatBuf{}), std::size_t(0));
    QCOMPARE(FrameBuffer::bytes(std::vector<float>(10, 0.0f)), std::size_t(10 * sizeof(float)));
}

void TestFrameBuffer::slotPublishReplacesAndReleases()
{
    FrameBuffer::BufferSlot<std::vector<double>> slot;
    QVERIFY(!slot.valid());
    QCOMPARE(slot.bytes(), std::size_t(0));

    // An externally held reference keeps the old block alive after a publish.
    auto oldRef = FrameBuffer::makeDouble(std::vector<double>(100, 1.0));
    slot.publish(oldRef);
    QVERIFY(slot.valid());
    QCOMPARE(slot.bytes(), std::size_t(100 * sizeof(double)));
    QCOMPARE(slot.useCount(), 2L);   // slot + oldRef

    slot.publish(FrameBuffer::makeDouble(std::vector<double>(10, 2.0)));
    QCOMPARE(slot.bytes(), std::size_t(10 * sizeof(double)));
    QCOMPARE(slot.useCount(), 1L);   // the only holder of the new block
    QCOMPARE(oldRef.use_count(), 1L);  // the old block is now ours alone

    // clear() drops our reference; the block dies unless somebody else holds it.
    auto keep = slot.get();
    slot.clear();
    QVERIFY(!slot.valid());
    QCOMPARE(slot.useCount(), 0L);
    QVERIFY(keep);
    QCOMPARE(keep.use_count(), 1L);
}

void TestFrameBuffer::slotGetNeverCopies()
{
    FrameBuffer::BufferSlot<std::vector<float>> slot;
    slot.publish(FrameBuffer::makeFloat(std::vector<float>(64, 1.0f)));

    const auto a = slot.get();
    const auto b = slot.get();
    QCOMPARE(a.get(), b.get());
    QCOMPARE(a.get(), slot.get().get());
    QCOMPARE(slot.useCount(), 3L);
}

void TestFrameBuffer::emptyBufferIsNotValid()
{
    FrameBuffer::BufferSlot<std::vector<double>> slot;
    slot.publish(FrameBuffer::makeDouble({}));
    QVERIFY(!slot.valid());          // allocated but empty -> treated as absent
    QCOMPARE(slot.bytes(), std::size_t(0));
}
