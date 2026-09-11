# 代码改进建议 - 具体实施方案

## 1. 异常处理规范化

### 问题代码位置
- **DetectionEngine.cpp** 第 36-47 行
- **LogManager.cpp** 第 39-47 行
- **CaptureFlow.cpp** 第 202-241 行

### 改进方案

#### 方案 A: 统一日志级别
```cpp
// 创建 src/logic/ErrorLogger.h
#pragma once
#include <QString>

namespace ErrorLogger {
	void logException(const std::exception& e, const char* context);
	void logUnknownException(const char* context);
	void logWarning(const QString& message);
	void logError(const QString& message);
}
```

#### 方案 B: 使用宏简化异常处理
```cpp
#define TRY_CATCH_LOG(block, context) \
	try { \
		block \
	} catch (const std::exception& e) { \
		ErrorLogger::logException(e, context); \
	} catch (...) { \
		ErrorLogger::logUnknownException(context); \
	}

// 使用方式
TRY_CATCH_LOG({
	auto result = detectConcentricNative(pngPath, plyPath);
	if (!result.first.empty())
		return result;
}, "[DetectionEngine] Native detection");
```

---

## 2. 输入验证框架

### 创建验证工具类

**文件**: `src/logic/InputValidator.h`

```cpp
#pragma once
#include <QString>
#include <optional>
#include <regex>

class InputValidator {
public:
	// 数值范围验证
	static std::optional<double> validateDouble(
		const QString& input,
		double minVal = -1e308,
		double maxVal = 1e308,
		QString& errorMsg);

	// 文件路径验证
	static bool validateFilePath(
		const QString& path,
		bool checkExists = true,
		QString& errorMsg);

	// 整数验证
	static std::optional<int> validateInt(
		const QString& input,
		int minVal = INT_MIN,
		int maxVal = INT_MAX,
		QString& errorMsg);

	// 列表解析验证
	static std::optional<std::vector<double>> validateNumberList(
		const QString& input,
		size_t expectedCount,
		QString& errorMsg);

	// 主机名/IP 验证
	static bool validateHostAddress(
		const QString& host,
		QString& errorMsg);

private:
	static const std::regex g_ipv4Regex;
	static const std::regex g_hostnameRegex;
};
```

### 使用示例

**ToolsPanel.cpp** 改进版本:
```cpp
// 修改前
const double scale = m_robotScale->text().trimmed().toDouble(&okScale);

// 修改后
QString errorMsg;
auto scale = InputValidator::validateDouble(
	m_robotScale->text(),
	0.001,  // 最小值
	10.0,   // 最大值
	errorMsg);
if (!scale) {
	m_logger->error(QStringLiteral("机器人缩放系数错误: %1").arg(errorMsg));
	return false;
}
```

---

## 3. RAII 资源管理模式

### 创建作用域守卫类

**文件**: `src/logic/ResourceGuard.h`

```cpp
#pragma once
#include <QString>
#include <QDir>
#include <functional>

class TempDirGuard {
	QString m_path;
	bool m_enabled = true;

public:
	explicit TempDirGuard(const QString& path);
	~TempDirGuard();

	// 禁用自动清理（用于保留结果）
	void release() { m_enabled = false; }

	const QString& path() const { return m_path; }

private:
	Q_DISABLE_COPY(TempDirGuard);
};

class FileGuard {
	QString m_path;
	std::function<void()> m_cleanup;

public:
	explicit FileGuard(const QString& path,
					  std::function<void()> cleanup = nullptr);
	~FileGuard();
	void release() { m_cleanup = nullptr; }
};
```

### 在 CalibrationService 中使用

```cpp
// 修改前
const QString tmpDir = QDir::tempPath() + QStringLiteral("/HandEyeCalib/calib_") + stamp;
QDir().mkpath(tmpDir);
auto cleanup = [tmpDir]() { QDir(tmpDir).removeRecursively(); };
// ... 可能异常 ...
cleanup();  // ❌ 异常时不会执行

// 修改后
const QString tmpDir = QDir::tempPath() + QStringLiteral("/HandEyeCalib/calib_") + stamp;
QDir().mkpath(tmpDir);
TempDirGuard guard(tmpDir);  // ✅ 作用域结束自动清理

// ... 所有操作 ...
// 如果要保留结果，显式调用 release()
guard.release();
```

---

## 4. 统一日志系统

### 增强 LogManager

**文件**: `src/logic/LogManager.h`

```cpp
#pragma once
#include <QString>

enum class LogLevel {
	Debug,
	Info,
	Warning,
	Error,
	Critical
};

class LogManager : public QObject {
	Q_OBJECT
public:
	explicit LogManager(QObject* parent = nullptr);

	// 按级别记录
	void log(LogLevel level, const QString& category, const QString& message);

	// 便利函数
	void debug(const QString& msg) { log(LogLevel::Debug, "General", msg); }
	void info(const QString& msg) { log(LogLevel::Info, "General", msg); }
	void warning(const QString& msg) { log(LogLevel::Warning, "General", msg); }
	void error(const QString& msg) { log(LogLevel::Error, "General", msg); }
	void critical(const QString& msg) { log(LogLevel::Critical, "General", msg); }

	// 带分类的日志
	void logDetection(LogLevel level, const QString& msg);
	void logCapture(LogLevel level, const QString& msg);
	void logCalibration(LogLevel level, const QString& msg);

	// 配置
	void setMinLevel(LogLevel level);
	void setFileOutput(const QString& path);
	void setMaxFileSize(qint64 bytes);

signals:
	void entryAdded(const QString& timestamp, const QString& level,
				   const QString& category, const QString& message);

private:
	void addEntry(LogLevel level, const QString& category, const QString& message);
	LogLevel m_minLevel = LogLevel::Info;
};
```

### 日志宏定义

**文件**: `src/logic/LogMacros.h`

```cpp
#pragma once
#include "logic/LogManager.h"

// 全局日志管理器指针（由主窗口设置）
extern LogManager* g_logger;

#define LOG_DEBUG(cat, msg)    if (g_logger) g_logger->log(LogLevel::Debug, cat, msg)
#define LOG_INFO(cat, msg)     if (g_logger) g_logger->log(LogLevel::Info, cat, msg)
#define LOG_WARNING(cat, msg)  if (g_logger) g_logger->log(LogLevel::Warning, cat, msg)
#define LOG_ERROR(cat, msg)    if (g_logger) g_logger->log(LogLevel::Error, cat, msg)

// 快速版本
#define LOG_DET_ERROR(msg)     LOG_ERROR("Detection", msg)
#define LOG_CAP_ERROR(msg)     LOG_ERROR("Capture", msg)
#define LOG_CALIB_ERROR(msg)   LOG_ERROR("Calibration", msg)
```

---

## 5. 常量集中管理

### 创建配置头文件

**文件**: `src/logic/AppConstants.h`

```cpp
#pragma once
#include <QString>
#include <cstddef>

namespace AppConstants {
	// 数据采集限制
	static constexpr int MAX_CAPTURE_RECORDS = 15;
	static constexpr int MIN_CAPTURE_RECORDS = 6;

	// 窗口配置
	static constexpr int DEFAULT_WINDOW_WIDTH = 1280;
	static constexpr int DEFAULT_WINDOW_HEIGHT = 720;
	static constexpr int MIN_WINDOW_WIDTH = 800;
	static constexpr int MIN_WINDOW_HEIGHT = 600;

	// 标定板参数范围
	static constexpr int MIN_PATTERN_WIDTH = 3;
	static constexpr int MAX_PATTERN_WIDTH = 20;
	static constexpr float MIN_CIRCLE_STEP = 5.0f;    // mm
	static constexpr float MAX_CIRCLE_STEP = 100.0f;  // mm

	// 机器人连接参数
	static constexpr int DEFAULT_ROBOT_PORT = 30003;
	static constexpr double MIN_ROBOT_SCALE = 0.001;
	static constexpr double MAX_ROBOT_SCALE = 10.0;
	static constexpr int ROBOT_CONNECT_TIMEOUT = 5000;  // ms

	// 文件系统
	static constexpr const char* SESSION_DIR_PATTERN = "calibration_data_%1";
	static constexpr const char* BACKUP_DIR_NAME = "backup";
	static constexpr const char* POSE_FILE_NAME = "pose.txt";

	// 检测参数
	static constexpr float DEFAULT_ERROR_THRESHOLD = 5.0f;  // %
	static constexpr int DETECTION_TIMEOUT = 30000;         // ms

	// 缓冲区大小
	static constexpr std::size_t INTRINSIC_MATRIX_SIZE = 9;
	static constexpr std::size_t DISTORTION_PARAMS_SIZE = 5;

	// 重试策略
	static constexpr int MAX_DEVICE_SCAN_RETRIES = 3;
	static constexpr int DEVICE_SCAN_RETRY_DELAY = 500;  // ms
	static constexpr int VIS_WINDOW_FIND_RETRIES = 20;
	static constexpr int VIS_WINDOW_FIND_DELAY = 25;     // ms
}
```

### 用法

```cpp
// 修改前
const int maxCount = 15;
resize(1280, 720);
setMinimumSize(800, 600);

// 修改后
#include "logic/AppConstants.h"
const int maxCount = AppConstants::MAX_CAPTURE_RECORDS;
resize(AppConstants::DEFAULT_WINDOW_WIDTH, 
	   AppConstants::DEFAULT_WINDOW_HEIGHT);
setMinimumSize(AppConstants::MIN_WINDOW_WIDTH,
			  AppConstants::MIN_WINDOW_HEIGHT);
```

---

## 6. 边界检查包装类

### 创建安全容器访问工具

**文件**: `src/logic/SafeAccess.h`

```cpp
#pragma once
#include <vector>
#include <optional>
#include <QString>

namespace SafeAccess {
	// 安全索引访问
	template<typename T>
	std::optional<std::reference_wrapper<T>> at(
		std::vector<T>& vec,
		int index,
		QString& errorMsg) {
		if (index < 0 || index >= static_cast<int>(vec.size())) {
			errorMsg = QStringLiteral("Index %1 out of range [0, %2)")
				.arg(index).arg(vec.size());
			return std::nullopt;
		}
		return std::reference_wrapper<T>(vec[index]);
	}

	// const 版本
	template<typename T>
	std::optional<std::reference_wrapper<const T>> at_const(
		const std::vector<T>& vec,
		int index,
		QString& errorMsg) {
		if (index < 0 || index >= static_cast<int>(vec.size())) {
			errorMsg = QStringLiteral("Index %1 out of range [0, %2)")
				.arg(index).arg(vec.size());
			return std::nullopt;
		}
		return std::reference_wrapper<const T>(vec[index]);
	}
}
```

### 使用示例

```cpp
// 修改前 - 危险
auto& rec = m_records[index - 1];
if (index < 1 || index > static_cast<int>(m_records.size()))
	return;

// 修改后 - 安全
QString errMsg;
auto recOpt = SafeAccess::at(m_records, index - 1, errMsg);
if (!recOpt) {
	LOG_ERROR("DataManager", errMsg);
	return false;
}
auto& rec = recOpt->get();
```

---

## 7. 文档注释模板

### Doxygen 配置

**CMakeLists.txt 添加**:
```cmake
find_package(Doxygen)
if(DOXYGEN_FOUND)
	set(DOXYGEN_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/docs")
	set(DOXYGEN_EXTRACT_ALL YES)
	set(DOXYGEN_EXTRACT_PRIVATE YES)
	doxygen_add_docs(docs ALL
		WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
		COMMENT "Generating API documentation with Doxygen")
endif()
```

### 注释模板

```cpp
/**
 * @file DetectionEngine.h
 * @brief 标定板和标记点检测引擎
 * 
 * 该模块提供同心圆和标定板检测功能，支持多个后端
 * （RVC 原生、HandEyeSDK）和自动降级策略。
 * 
 * @author Team
 * @version 1.0
 * @date 2024-01-01
 */

/**
 * @class DetectionEngine
 * @brief 标定板和标记点检测
 * 
 * 主要功能：
 * - 同心圆检测（2D + 3D）
 * - 标定板检测
 * - 多后端支持和自动降级
 * 
 * @note 线程安全吗？ 单线程使用
 */
class DetectionEngine {
public:
	/**
	 * @brief 检测图像中的同心圆标记
	 * 
	 * 从 PNG 和 PLY 文件中检测同心圆，返回 2D 像素坐标和 3D 世界坐标。
	 * 优先使用 RVC 原生检测，如果失败则降级到 HandEyeSDK。
	 * 
	 * @param pngPath PNG 图像文件路径（支持 UTF-8）
	 * @param plyPath PLY 点云文件路径（支持 UTF-8）
	 * 
	 * @return 一对向量: (2D 像素坐标, 3D 世界坐标)，如果检测失败为空
	 * 
	 * @throw 无异常保证（内部异常被捕获）
	 * 
	 * @see detectConcentric, detectCaliboard
	 * 
	 * @note 该函数会进行文件 I/O，可能阻塞
	 */
	std::pair<std::vector<Vec2f>, std::vector<Vec3f>>
	detectConcentric(const std::string& pngPath, const std::string& plyPath);
};
```

---

## 8. 并发控制状态机

### 创建操作管理器

**文件**: `src/logic/OperationManager.h`

```cpp
#pragma once
#include <QString>
#include <QObject>
#include <map>

enum class OperationType {
	Idle,
	ScanningDevices,
	CapturingImage,
	DetectingMarkers,
	Calibrating
};

class OperationManager : public QObject {
	Q_OBJECT
public:
	explicit OperationManager(QObject* parent = nullptr);

	// 尝试启动操作
	bool tryStart(OperationType op, const QString& description = {});

	// 检查操作是否运行中
	bool isRunning(OperationType op) const;

	// 获取当前操作
	OperationType current() const { return m_current; }

	// 完成操作
	void finish(OperationType op);

	// 取消所有操作
	void cancelAll();

signals:
	void operationChanged(OperationType op);

private:
	OperationType m_current = OperationType::Idle;
	std::map<OperationType, QString> m_descriptions;
};
```

### 使用示例

```cpp
// MainWindow.cpp
void MainWindow::onCapture() {
	if (!m_opMgr->tryStart(OperationType::CapturingImage, "采集图像...")) {
		m_logger->warning(QStringLiteral("另一个操作正在进行"));
		return;
	}
	// 执行采集...
}

void MainWindow::onCalibrate() {
	if (!m_opMgr->tryStart(OperationType::Calibrating, "标定计算中...")) {
		m_logger->warning(QStringLiteral("另一个操作正在进行，请等待"));
		return;
	}
	// 执行标定...
}
```

---

## 优先级实施计划

### 第一阶段（第 1-2 周）
- [ ] 创建 `InputValidator` 和 `AppConstants`
- [ ] 修复所有 catch(...) 异常处理
- [ ] 添加关键路径的日志

### 第二阶段（第 3-4 周）
- [ ] 创建 `ResourceGuard` 和 `SafeAccess`
- [ ] 升级 `LogManager`
- [ ] 添加 `OperationManager`

### 第三阶段（第 5-6 周）
- [ ] 添加完整 Doxygen 文档
- [ ] 修复 Test Explorer 集成
- [ ] 代码风格统一检查

---

## 验证清单

在应用每项改进后，验证：
- [ ] 代码编译无警告
- [ ] 现有测试仍通过
- [ ] 新增验证逻辑覆盖常见错误
- [ ] 日志输出清晰且完整
- [ ] 文档自动生成成功（`make docs`）

