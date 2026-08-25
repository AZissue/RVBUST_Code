#pragma once
#include <vector>
#include <string>
#include <tuple>
#include <QImage>

// Forward-declare RVC types to avoid leaking RVC headers
namespace RVC {
struct Image;
}

struct MarkerOverlay {
    std::vector<std::tuple<float, float, std::string>> overlay2d; // x, y, label
    std::vector<std::array<float, 3>> highlights3d;              // mm
    // Original 2D-label index for each entry in highlights3d (NaN 3D points
    // are skipped, so highlight i corresponds to 2D label highlightIndices[i]).
    std::vector<int> highlightIndices;
};

class DetectionEngine {
public:
    static constexpr int DEFAULT_PATTERN_COLS = 4;     // short side (width)
    static constexpr int DEFAULT_PATTERN_ROWS = 11;    // long side (height), must be odd
    static constexpr float DEFAULT_CIRCLE_STEP = 7.0f;  // mm, A9

    // Concentric circle detection (RVC native → HandEyeSDK fallback)
    static std::pair<std::vector<std::pair<float, float>>,
                     std::vector<std::array<float, 3>>>
    detectConcentric(const std::string& pngPath, const std::string& plyPath);

    // Caliboard detection via HandEyeSDK's built-in DetectCaliboard3D
    struct CaliboardResult {
        std::vector<float> pixelXy;       // flat [x0,y0,...]
        std::vector<float> pointXyz;      // flat [x0,y0,z0,...]
        float measuringDistance = 0.0f;
        float errorPercentage = 0.0f;
    };

    static CaliboardResult
    detectCaliboard(const std::string& pngPath, const std::string& plyPath,
                    const std::vector<float>& intrinsic = {},
                    const std::vector<float>& distortion = {},
                    int patternW = DEFAULT_PATTERN_COLS,
                    int patternH = DEFAULT_PATTERN_ROWS,
                    float circleStep = DEFAULT_CIRCLE_STEP);

    // Image conversion utilities (BGR→RGB pixel swizzle)
    static QImage rvcToQImage(const RVC::Image& img);
    static void extractColors(const RVC::Image& img, std::vector<float>& rgbOut);

    // Formatting utilities
    static std::string formatXyzForCard(const std::vector<std::array<float, 3>>& pts3d);
    static MarkerOverlay
    formatMarkersForOverlay(const std::vector<std::pair<float, float>>& pts2d,
                            const std::vector<std::array<float, 3>>& pts3d);

    // Reference origin for the calibration target.
    //
    // Both RVC's DetectConcentricCircleMarker3d / TestAccuracy and the
    // HandEyeSDK board detectors order their returned points starting from
    // the calibration reference origin (first point == origin).  For a
    // concentric-circle marker the first point is the shared marker center;
    // for the asymmetric board it is the origin corner.  Returns {x,y,z} of
    // the first valid (non-NaN) point, or an empty vector when none exists.
    static std::vector<float> firstValidPoint3d(
        const std::vector<std::array<float, 3>>& pts3d);

private:
    // RVC native concentric detection
    static std::pair<std::vector<std::pair<float, float>>,
                     std::vector<std::array<float, 3>>>
    detectConcentricNative(const std::string& pngPath, const std::string& plyPath);

    // RVC native caliboard detection (TestAccuracy)
    static CaliboardResult
    detectCaliboardNative(const std::string& pngPath, const std::string& plyPath,
                          const float intrinsic[9], const float distortion[5],
                          int patternW, int patternH, float circleStepM);

    // HandEyeSDK caliboard detection (fallback)
    static CaliboardResult
    detectCaliboardHandEye(const std::string& pngPath, const std::string& plyPath,
                           const std::vector<float>& intrinsic,
                           const std::vector<float>& distortion,
                           int patternW, int patternH, float circleStep);

    // HandEyeSDK concentric fallback
    static std::pair<std::vector<std::pair<float, float>>,
                     std::vector<std::array<float, 3>>>
    detectConcentricHandEye(const std::string& pngPath, const std::string& plyPath);
};
