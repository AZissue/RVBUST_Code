#pragma once

#include <QObject>

// T-005（Codex 验收测试）：保存路径的"假成功"。
//
// 现状：`CaptureFlow::save()` 丢掉 `DataManager::writeHandEyeOutput()` 的返回值，
// 而后者内部的三个导出文件（pose.txt / cameraCapturePointXyz.txt / tcp.txt）写失败
// 时只 `qWarning`（进 runtime 日志，不进界面）——界面照样弹"保存成功"。
// 备份侧还有两个洞：`writeBackupNow()` 用裸 QFile（非原子）且无版本字段，
// `findLatestBackup()` 只按 mtime 挑最新的、不验内容。
class TestSaveExport : public QObject {
    Q_OBJECT
private slots:
    void exportFailureIsReported();       // 导出失败 → 返回 false + 可读原因
    void exportSuccessStillWrites();      // 正常路径不回归
    void captureFlowSurfacesExportFailure();   // save() 不能报"保存成功"
    void undoSurfacesExportFailure();          // undo() 同理
    void backupCarriesVersion();              // 备份有 version 字段
    void findLatestBackupSkipsCorrupt();      // 坏备份不被选中
};
