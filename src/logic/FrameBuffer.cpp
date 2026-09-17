#include "logic/FrameBuffer.h"

namespace FrameBuffer {

FloatBuf makeFloat(std::vector<float>&& data)
{
    return std::make_shared<const std::vector<float>>(std::move(data));
}

DoubleBuf makeDouble(std::vector<double>&& data)
{
    return std::make_shared<const std::vector<double>>(std::move(data));
}

FloatBuf copyFloat(const std::vector<float>& data)
{
    return std::make_shared<const std::vector<float>>(data);
}

DoubleBuf copyDouble(const std::vector<double>& data)
{
    return std::make_shared<const std::vector<double>>(data);
}

std::size_t bytes(const FloatBuf& b)
{
    return b ? b->size() * sizeof(float) : 0;
}

std::size_t bytes(const DoubleBuf& b)
{
    return b ? b->size() * sizeof(double) : 0;
}

std::size_t bytes(const std::vector<float>& v)
{
    return v.size() * sizeof(float);
}

std::size_t bytes(const std::vector<double>& v)
{
    return v.size() * sizeof(double);
}

} // namespace FrameBuffer
