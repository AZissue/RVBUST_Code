#pragma once
#include <QWidget>
#include <QLabel>
#include <QPushButton>
#include <QFutureWatcher>
#include <vector>
#include <array>
#include <memory>

class QTimer;

struct VisSceneViewImpl;

class VisSceneView : public QWidget {
    Q_OBJECT
public:
    explicit VisSceneView(QWidget* parent = nullptr);
    ~VisSceneView() override;

    // Point cloud (xyz in mm, rgb in [0,1])
    void updatePointCloud(const std::vector<float>& xyz,
                          const std::vector<float>& rgb = {});
    void highlightPoints(const std::vector<std::array<float, 3>>& pts3dMM);
    void clear();

    // Camera presets
    void setViewPreset(const QString& name);
    void resetView(bool animated = true);

    // Scene objects (return handle indices, -1 = failure)
    int addSphere(const std::array<float, 3>& centerMM, float radiusMM,
                  const std::array<float, 3>& color = {1,0,0});
    int addBox(const std::array<float, 3>& centerMM,
               const std::array<float, 3>& halfExtentsMM,
               const std::array<float, 3>& color = {1,0,0});
    int addCone(const std::array<float, 3>& centerMM, float radiusMM,
                float heightMM, const std::array<float, 3>& color = {1,0,0});
    int addCylinder(const std::array<float, 3>& centerMM, float radiusMM,
                    float heightMM, const std::array<float, 3>& color = {1,0,0});
    int addArrow(const std::array<float, 3>& tailMM, const std::array<float, 3>& headMM,
                 float radiusMM = 2.0f, const std::array<float, 3>& color = {1,0,0});
    int addPlane(float xLenM, float yLenM, int xCells = 8, int yCells = 8,
                 const std::array<float, 3>* posMM = nullptr,
                 const std::array<float, 4>* quat = nullptr,
                 const std::array<float, 3>& color = {0.5f,0.5f,0.5f});
    int addMesh(const std::vector<float>& vertsM, const std::vector<int>& faces,
                const std::array<float, 3>& color = {1,0,0});
    int addText(const QString& content, const std::array<float, 3>& posMM,
                float fontSize = 0.02f, const std::array<float, 3>& color = {1,1,1});
    int addSpheresBatch(const std::vector<float>& centersMMFlat, float radiusMM,
                        const std::array<float, 3>& color = {1,0,0});
    int loadModel(const QString& filepath);

    // Object manipulation
    void removeObject(int handle);
    void setVisible(int handle, bool visible);
    void setObjectPosition(int handle, const std::array<float, 3>& posMM);
    void setObjectRotation(int handle, const std::array<float, 4>& quat);
    void setObjectColor(int handle, const std::array<float, 3>& color);
    void setObjectTransparency(int handle, float alpha);

    // 2D image overlay (for stereo camera right-eye preview)
    void showImage(const QImage& img);
    void hideImage();

    // ── Marker picking (识别点选择填充) ──
    // Recognition markers (3D + their 2D-overlay labels) become clickable /
    // hoverable in the 3D scene.  Picking never changes the rendered scene:
    // hit-testing is done by projecting markers to screen coordinates.
    void setSelectableMarkers(const std::vector<std::array<float, 3>>& pts3dMM,
                              const std::vector<int>& indices);
    void setMarkerPickEnabled(bool enabled);

    // Lifecycle — call before destroying the parent window
    void shutdown();

    // Emitted when the user clicks on/near a selectable marker.
    // index matches the 2D overlay label; xyz in mm.
signals:
    void markerPicked(int index, float x, float y, float z);

protected:
    void resizeEvent(QResizeEvent* event) override;
    void showEvent(QShowEvent* event) override;

private slots:
    void resetViewNoAnim();

public slots:
    // Called from the native WNDPROC (render thread) via queued invocation.
    void onVisMouseMoved();
    void onVisMousePress();
    void onVisMouseClick(int x, int y);
    void onVisMouseLeave();
    void onHoverTimeout();

private:
    void setupToolbar();
    void applyVisGeometry();   // debounced native Vis window resize/init
    // Marker picking state (GUI thread only)
    struct PickMarker {
        int index = -1;
        std::array<float, 3> pos{};
    };
    // Asynchronous pick query: runs the Vis camera-pose read + projection on a
    // worker thread so the UI can never be blocked by a stuck Vis render
    // thread (GetCameraPose is a synchronous command with no timeout).
    struct PickResult {
        int index = -1;
        std::array<float, 3> pos{};
    };
    static PickResult runPickQuery(
        const std::shared_ptr<VisSceneViewImpl>& impl,
        const std::vector<PickMarker>& markers,
        int mouseX, int mouseY, int radiusPx, float fovDeg);
    void startPickQuery(int kind, int x, int y, int radiusPx);
    void onPickQueryFinished();
    void showHoverResult(const PickResult& result);
    void handleClickResult(const PickResult& result);

    QWidget* m_toolbar = nullptr;
    QWidget* m_containerWidget = nullptr;
    QWidget* m_viewport = nullptr;
    QLabel* m_placeholder = nullptr;
    QLabel* m_imageOverlay = nullptr;
    QLabel* m_pickHint = nullptr;
    QLabel* m_hoverTip = nullptr;   // light-weight hover label (white text +
                                    // black outline, no tooltip window)
    bool m_shuttingDown = false;

    QTimer* m_hoverTimer = nullptr;
    QTimer* m_resizeTimer = nullptr;
    std::vector<PickMarker> m_pickMarkers;
    bool m_pickEnabled = false;

    std::shared_ptr<VisSceneViewImpl> d;
    QFutureWatcher<PickResult>* m_pickWatcher = nullptr;
    bool m_pickQueryRunning = false;
    int m_pickQueryId = 0;        // incremented to invalidate stale results
    int m_activeQueryId = -1;
    int m_activeQueryKind = -1;   // 0 = hover, 1 = click
    int m_pendingClickX = -1;     // click that arrived while a query was running
    int m_pendingClickY = -1;
    static constexpr float MM_TO_M = 0.001f;
    // OSG viewer default vertical FOV.  Kept as a constant so it can be
    // tuned if hover/click hit-testing ever feels misaligned.
    static constexpr float kPickFovDeg = 30.0f;
    static constexpr int kHoverRadiusPx = 12;   // strict: only show when really
    static constexpr int kClickRadiusPx = 16;   // on/near the marker
};
