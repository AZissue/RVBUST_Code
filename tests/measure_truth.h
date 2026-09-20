#pragma once

// Known-truth synthetic data for the measurement tools (round 7, P1).
//
// The measurement panel's numbers had no ground truth to check against: a Ø
// value that is wrong by 10 mm looks exactly like one that is right.  This
// module generates datasets whose every number is known by construction, in the
// same two carriers the application itself uses:
//
//   *.grid  — the organized point grid, byte-isomorphic with what
//             CameraManager::lastGrid() hands to the panel: an ASCII header
//             "<w> <h>\n" followed by w*h*3 little-endian float32 (x,y,z) mm,
//             row-major (cell = y*w + x), NaN where the cell is invalid.
//   *.ply   — the same points as a binary little-endian PLY, so a human can
//             open the data in MeshLab/CloudCompare and see what the checker
//             measured.
//
// Everything is deterministic: the RNG is built from raw std::mt19937_64 output
// with explicit Box-Muller math, so the same seed gives the same bytes on every
// compiler and standard library.
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace MeasureTruth {

// One assertion: a measurement the harness must reproduce, the truth recorded by
// the generator, and the tolerance it must hold within.
struct Check {
    std::string id;        // check kind, see measure_truth.cpp's dispatch
    std::string title;     // display label (UTF-8)
    std::string unit;      // "mm" / "°" / "点"
    double truth = 0.0;    // recorded truth (may be the *realized* noise, see notes)
    double tol = 0.0;      // |measured - truth| <= tol
    double truth2 = 0.0;   // second number of the same check (e.g. hole centre y)
    double tol2 = 0.0;     // > 0 enables the second number
    bool perFrame = false; // check runs on every file of the scene (repeatability)
    std::vector<int> roi;  // image px, left/top/right/bottom (inclusive)
    std::vector<int> roi2; // optional second ROI (datum + measured region)
    std::string criterion; // human-readable pass rule
};

struct Scene {
    std::string name;
    int gridW = 0;
    int gridH = 0;
    int imageW = 0;        // the "camera image" the ROI is dragged on; it does
    int imageH = 0;        // NOT have to match the grid (roi_map_* exploits that)
    std::vector<std::string> files;
    std::vector<std::vector<double>> frames;   // per file: w*h*3 mm
    std::string notes;
    std::vector<Check> checks;

    // ── "该用哪个方法 / 该画哪个 ROI"（round 7, P1）────────────────────
    // method  = src/logic/MeasureMethods.h 里的方法 id：界面左列表选哪一项。
    // roiHint = 用大白话写清这一框该框哪儿（每个 Check 自己的 roi 是像素矩形，
    //           只有跑工装的人用得上；roiHint 是给人看的操作说明）。
    // 工装会断言 method 一定是目录里的合法 id，所以这两项不会随界面改名而失效。
    std::string method;
    std::string roiHint;
};

// Scene catalogue, in the order the manifest lists them.
std::vector<std::string> sceneNames();

// Builds a scene's data and its checks.  Unknown name -> a scene with no files
// and a note saying so (the caller reports it).
Scene buildScene(const std::string& name);

// ── data writers (mm, NaN = invalid) ───────────────────────────────────
bool writeGrid(const std::string& path, const std::vector<double>& grid, int w, int h);
bool writePly(const std::string& path, const std::vector<double>& grid, int w, int h);

} // namespace MeasureTruth
