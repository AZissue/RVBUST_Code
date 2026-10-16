# 阶段 14 — 埃夫特（EFORT）连不上的根因：绿色包缺 `log4cpp.conf`；以及 8003 / 8100 到底是谁的端口

> 用户报告：把 **test2.4 绿色包**交给客户测试连接埃夫特机器人，**连不上**。
> 客户给的是 `IP = 192.168.0.1`、`端口 = 8003`（客户不确认是 8003 还是 80003）。
> 界面**埃夫特协议下没有端口输入框**，客户问为什么。
> 客户提供的 SDK 在 `D:\MyCode\EfortSDK`。
> 本轮**只本地验证，不打包**（用户明确：他说打包再打包）。

---

## 1. 结论先说

| # | 问题 | 结论 |
|---|---|---|
| **1** | **为什么连不上** | **不是网络、不是 IP、更不是端口 —— 是 test2.4 绿色包里根本没有 `log4cpp.conf`。** 埃夫特 SDK（`EftSdk.dll`）在**打开任何 socket 之前**先调 `log4cpp::PropertyConfigurator::configure("log4cpp.conf")`，且用的是**找不到文件就抛异常**的那个重载 → 连接第 0 步直接抛 `File log4cpp.conf does not exist`。这个缺陷**把所有其它原因都遮住了**：不管 IP 对不对、机器人开没开，现场看到的都是"连不上"。 |
| **2** | **界面为什么没有端口框** | 因为**埃夫特这条链路没有端口可填**：SDK 的 `ConnectRobot` 只收一个地址串，端口在库里写死 **8100**（见 §2）。留一个填了也不起作用的框，等于制造"填了就有用"的错觉。 |
| **3** | **8003 是什么** | **不是这条链路用的东西。** 8003 / 80003 在 `EftSdk.dll`、`rlibcpp-bcc.dll` 里**一个都不存在**（全库没有这两个立即数）；厂商手册把 8000/8100 这一段标为「示教器 / SDK 内部使用，禁止占用」。埃夫特允许用户在示教器上自开 5 个 client / 3 个 server socket，**8003 几乎可以肯定是客户自己开的那个用户 socket**，与 SDK 连接无关。 |
| **4** | **正确做法** | **只填 IP。** 而且必须**把 "IP:端口" 里的端口切掉**再交给 SDK —— SDK 的地址解析遇到 `:` 不会报错，会把整串**悄悄拼成另一个 IP**（`192.168.0.1:8003` → **192.171.44.131**，实测），现场只会继续"连不上"，没有任何第二种线索。 |

**为什么本地复现不出来**：`build/src/Release/` 里 CMake 已经按规矩部署了 `log4cpp.conf`
（`src/CMakeLists.txt`），只有**打包脚本**漏了它 → 只有客户手里那份会出问题。

---

## 2. 证据链

### 2.1 `log4cpp.conf` 是怎么丢的

| 环节 | 事实 |
|---|---|
| CMake 部署 | `src/CMakeLists.txt` 把 `third_party/EfortSDK/bin/log4cpp.conf` `copy_if_different` 到 exe 目录，缺源文件时直接 `FATAL_ERROR`。**构建产物里一直都有** |
| 打包脚本 | `pack_portable.ps1` 第 2 步的过滤器只挑 **应用 exe + `*.dll`**（外加排除 Debug 厂商 DLL / Qt5 debug / Qt5Test）—— **任何非 DLL 的运行时文件都进不了包** |
| 结果 | test2.4 的 `dist\HandEyeCalibrationTool_test2.4\`（207 个文件）里 `log4cpp.conf` **不存在**；`EftSdk.dll` / `log4cpp.dll` / `NTEventLogAppender.dll` 等 DLL 都在 |

### 2.2 SDK 为什么缺这个文件就抛异常

- `EftSdk.dll` 的 `EftLogger::getInstance()`（RVA `0x40CF0`）：先 `_mkdir("log")`，
  再 `log4cpp::PropertyConfigurator::configure(std::string("log4cpp.conf"))` ——
  **`std::string` 重载是会抛的那个**（`log4cpp.dll` 里带 ` does not exist` 字面量，
  抛 `ConfigureFailure("File log4cpp.conf does not exist")`）。
- 读的是**当前工作目录**下的文件。本项目在 `EfortPoseReader` 里用 `ScopedWorkingDir`
  把 CWD 临时切到 `QCoreApplication::applicationDirPath()`（= exe 目录），所以
  **"exe 旁边有没有这个文件" 就等于 "SDK 能不能找到"**。
- 调用链：`RobotAPI::ConnectRobot(addr, devId)` → `EftSdkMngr::CreateController` →
  `RoboxController` → 内嵌的 `RoboxConnection::connectRobot` ——
  **抛点在建连之前**，socket 还没开。

**历史佐证**：`.pair/ledger.md` 的 008/009/010/011 四行就是同一条链的上一轮记录 ——
008 整程序被未捕获的 C++ 异常秒杀（根因即此），010 才把 `log4cpp.conf` 部署到 exe 旁边。
**部署解决了构建机，打包脚本没跟上。**

### 2.3 8100 是 SDK 的连接端口（写死在库里）

`rlibcpp-bcc.dll` 的 `TcpIpConnection`（导出符号 `??0TcpIpConnection@Bcc@RLibCpp@@QEAA@XZ`，
RVA `0x5FEF0`）：

| 项 | 事实 |
|---|---|
| `serverIp` | `RLibCpp::Tool::String`，在对象 `+0x298` |
| `serverPort` | `int`，在对象 `+0x2A8`，**构造函数里存 `0x1FA4` = 8100** |
| 谁改它 | **没人改**。`EftSdk.dll` 连 `setServerPort` 都不导入（imports 里没有） |
| 实际连接 | `doStart`（RVA `0x60250`）在 `0x1800602FC` 读 `serverPort`，写到 TCP 端点的端口位置 → **连的就是 8100** |
| 设备发现 | `FindRRobot` / `scanPort` / `scanNetwork` 里也只有 `1FA4h`（8100）这一段 |
| 8003 / 80003 / 8000 | **全库不存在**：`EftSdk.dll` 与 `rlibcpp-bcc.dll` 里唯一落在端口区间的立即数就是 `1FA4h` |

**厂商手册**（网络检索，PDF 未能直接打开核对，故标注来源）的端口占用表：
`8000` = 示教器 & SDK 使用（禁止使用）；**`8100` = 内部调试使用（禁止使用）**；
`8008` = MES；`502` = Modbus_TCP；`44818/2222` = EtherNet/IP；0–1000 建议不要使用。
与库里的结论一致：**8100 是控制器一侧由 SDK 使用的内部服务**。

### 2.4 `192.168.0.1:8003` 交给 SDK 会变成什么

`RoboxConnectionHelper::str2IpAddr`（RVA `0x61770`）的解析方式：

```
逐字符扫描整串：
  '.'  → r8 = (r8 << 8) + r9;  r9 = 0
  其它 → r9 = r9 * 10 + (c - '0')      ← 冒号、字母一律按"数字的一部分"吃进去
末尾  → (r8 << 8) + r9
```

它**不校验字符、也不报错**。逐段代入 `192.168.0.1:8003`：

| 段 | 结果 |
|---|---|
| `192` | r8 = 0x000000C0，r9 = 0 |
| `168` | r8 = 0x0000C0A8，r9 = 0 |
| `0` | r8 = 0x00C0A800，r9 = 0 |
| `1:8003` | r9 = 1 → 冒号 `- '0'` → r9 = 1×10 + (−38) = **−28** → `8` → −272 → `0` → −2720 → 再两个 `0` → −272000 → `3` → −2719997 |
| 收尾 | `(r8 << 8) + r9` = `0xC0AB2C83` = **192.171.44.131** |

**连的是 192.171.44.131，而且不会有任何报错。** 这正是"必须自己把端口切掉"的理由。

---

## 3. 改动清单

### 3.1 打包脚本：非 DLL 的运行时文件 + 缺件就报错（修 ①）

`pack_portable.ps1`：

| 步骤 | 改动 |
|---|---|
| **2b（新增）** | 显式拷贝**厂商运行时数据文件** `log4cpp.conf`（源文件缺失时报错退出，不再静默漏掉）。注释写明这是 test2.4 缺件的原因，以及"缺它 → 现场看到的是连不上机器人"。 |
| **3a（新增）** | **发版断言**：`mustShip` 清单（exe、`log4cpp.conf`、`EftSdk.dll`、`log4cpp.dll`、`NTEventLogAppender.dll`、`rlibcpp-bcc.dll`、`rlibcpp-tool.dll`、`HandEyeSDK.dll`、`Qt5Core.dll`、`Qt5Widgets.dll`、`platforms\qwindows.dll`）逐个 `Test-Path`，缺任何一个 `Write-Error`（脚本退出码非 0）。放在第 3 步（拷 `platforms`/`osgPlugins`）**之后**，否则会误报 `qwindows.dll`。 |

**为什么要有 ②**：这次的真正教训不是"漏了一个文件"，而是**漏了没人知道**。
一个缺文件（`log4cpp.conf`）在现场长得像"机器人连不上"、另一个（`qwindows.dll`）长得像
"程序起不来"，都与打包无关的方向。清单化 + 失败即中止，把"静默不完整"变成"打包失败"。

### 3.2 适配器：缺配置给人话、地址只留 IP（修 ②③）

`src/logic/EfortPoseReader.{h,cpp}` 新增三个**纯函数**（头文件仍然不含 SDK 头，可单测）：

| 函数 | 作用 |
|---|---|
| `AddressSplit splitAddress(const QString& raw)` | 按**第一个**冒号切：`"192.168.0.1:8003"` → `{ "192.168.0.1", "8003" }`；无冒号时 `ip` = 原文、`portSuffix` 为空；两侧 trim；`ip` 为空时由调用方判"IP 不能为空" |
| `bool logConfigPresent(const QString& dir)` | 判 `dir` 下有没有 `log4cpp.conf`（`dir` 为空 → `false`，不猜"当前目录"） |
| `QString logConfigMissingText(const QString& dir)` | 缺文件时的中文：点名文件、给出期望路径、说明"与网络/端口无关，是部署包不完整" |

`EfortReader::connect()`：

- **删掉**原来的 `if (!address.contains(':') && port != 0) address += ":" + port;` ——
  **端口参数在埃夫特这条链路上无意义**（`Q_UNUSED(port)`，注释写明原因）。
  这是本次最重要的一行改动：原逻辑会把 UI 传进来的端口拼进地址串，
  而拼出来的串会被 SDK 解析成另一个 IP。
- 只把 `splitAddress(host).ip` 交给 SDK。
- 进 SDK 之前先 `logConfigPresent(applicationDirPath())`：缺文件就直接返回可读中文，
  **不再让厂商异常当"连接失败"**。
- 失败文案（异常 / 返回码两条）在输入里带端口时追一句
  「（输入里的":8003"已忽略：埃夫特端口由 SDK 固定，只填 IP 即可）」，
  让现场日志自己说清。

### 3.3 界面：粘进来带端口的地址，就地截断并说明（修 ③）

`src/ui/ToolsPanel.{h,cpp}`：

- IP 行下面新增一行提示 `m_robotHostNote`（默认隐藏，`Theme::WARNING` 色）。
- 点「连接」且协议为埃夫特时：`splitAddress(host)` → 有端口就**把输入框改写成纯 IP**
  并显示「已忽略输入里的":8003"：埃夫特端口由 SDK 固定（控制器内部服务 8100），
  只填 IP 即可，本连接不使用客户自定义的 socket 端口。」
- 切换协议时清掉该提示。
- 静态提示行补写端口归属（8100 是 SDK 的、8003 是客户自开的用户 socket、整串会被 SDK
  解析成另一个 IP）—— **给现场读的那一份说明写在现场会看到的地方**。

---

## 4. 验收

| 项 | 结果 |
|---|---|
| 构建 | `cmake --build … --config Release` **`$LASTEXITCODE = 0`**；`HandEyeCalibrationTool.exe` 时间戳刷新（17:23:44） |
| `unit_tests` | **334 通过 / 0 失败**（上一轮 332 → 新增 2 条） |
| 新增单测 | `TestEfortPoseReader::addressSuffixIsSplitOffTheIp`、`missingLogConfigIsDetectableAndExplained` |
| `ctest -C Release` | **3/3 通过**（`unit_tests` / `measurement_truth` / `circle_truth`，`circle_truth` 输出未变） |
| 打包脚本 | **未打包**（用户明确本轮先本地）。脚本改动做了：①PowerShell AST **语法解析通过**；②把 `mustShip` 断言**原样抽出来对着两个假包目录实测** —— 完整包 → 缺件列表为空；删掉 `log4cpp.conf` → 报 `[log4cpp.conf]`；再删 `platforms\` → 报 `[log4cpp.conf, platforms\qwindows.dll]` |
| 真机连接 | **未验证**（现场无埃夫特机器人；单位/欧拉约定仍是待证实项） |

新增测试覆盖的点：

- `addressSuffixIsSplitOffTheIp`：`192.168.0.1:8003` / `:80003`（客户两种说法都覆盖）、
  纯 IP（带空白）、`:8003`（ip 为空）、`192.168.0.1:`（尾部冒号）、
  `192.168.0.1:8003:9`（多个冒号，只按第一个切）、空串与纯空白。
- `missingLogConfigIsDetectableAndExplained`：`QTemporaryDir` 里先判"缺失"，
  建出文件后判"存在"；空目录串判"缺失"；文案里必须含 `log4cpp.conf` 与期望路径，
  并且要提到"连接/网络"（把"这不是网络问题"这句话钉进测试）。

`EfortReader::connect()` 本身**不进单测**（要真机与厂商 DLL），它只做两件事：
调 `splitAddress` / `logConfigPresent`，然后把 IP 交给 SDK —— 判据都在上面两条纯函数里。

---

## 5. 用户手动复测清单

**A. 埃夫特地址带端口（本轮主要改动）**

1. 工具 → 机器人通信 → 协议选「埃夫特（EfortSDK）」→ IP 框填 `192.168.0.1:8003` → 点「连接」。
   - 预期：IP 框**自己变成 `192.168.0.1`**（端口被切掉）。
   - 预期：IP 行下面出现一行黄字「已忽略输入里的":8003"：埃夫特端口由 SDK 固定…」。
   - 预期：日志里的地址是 `192.168.0.1`，**不是** `192.168.0.1:8003`。
   - （修复前：整串原样进 SDK，会被解析成 192.171.44.131。）
2. 同样步骤填 `192.168.0.1:80003`（客户说的另一种写法）。
   - 预期：同样被切掉，提示里写 `:80003`。
3. IP 框只填 `192.168.0.1`（不带端口）→ 点「连接」。
   - 预期：**不出现**那行黄字（端口框本来就是不给填的）。
4. 协议从「埃夫特」切到「Modbus TCP」再切回来。
   - 预期：黄字提示消失；端口框在埃夫特下仍然隐藏、在其它协议下正常显示并带默认值。

**B. 缺 `log4cpp.conf` 时报什么（本轮根因的现场形态）**

5. 把 `build\src\Release\log4cpp.conf` **临时改名**（例如 `log4cpp.conf.bak`），
   启动工具 → 用埃夫特协议点「连接」（随便填个 IP）。
   - 预期：提示是「埃夫特：缺少 SDK 配置文件 log4cpp.conf（应在 <exe 目录>）。厂商 SDK 在
     连接前必须先读它…这与网络/端口无关 —— 这是部署包不完整」。
   - 预期：**程序不崩**、**不出现** SDK 的 `File log4cpp.conf does not exist` 原文。
   - 测完**记得把文件名改回去**（`log4cpp.conf` 必须留在 exe 旁边）。
6. （可选）填一个**存在但连不上**的 IP（例如 `192.168.0.99`）→ 预期是正常的
   「连接失败：未连接（SDK 返回码 N）」—— 说明走到真正连机器那一步了。

**C. 打包（等用户说「打包」再做）**

7. 打包后**在接到包的那台机器上**先确认目录里有 `log4cpp.conf`（和 `platforms\qwindows.dll`）。
   - 预期：脚本在缺件时**直接失败**（不会再出现"包看起来完整、现场连不上"）。
8. 客户现场：埃夫特协议只填 IP → 连接 → 「拍照位姿」能读到非 0 的 6 个数。
   - 若报「六个分量全为 0」（`checkPoseSanity` 判据）→ 是**没读到**，不是端口问题，
     回来查 SDK 的单位/欧拉约定（仍是待证实项）。

---

## 6. 遗留 / 下一步

- **埃夫特的单位与欧拉约定仍未真机确认**（`normalizePose(raw, true, true)` 按 mm + 度，
  见 `RobotPose.h` 与 008 交回说明）。本轮不动 —— 需要现场一次真实读数。
- **8003 的确切用途只能由客户回答**：按现有证据它不在 SDK 里、不在厂商保留端口表里，
  最可能是示教器上自开的用户 socket。若客户坚持该 socket 与标定有关，
  请客户给出"哪个功能用它"的说明；**本工具这条链路不会用到它**。
- 厂商手册的端口占用表来源为**网络检索摘要**（`www.efort.com.cn` 的 PDF 域名在本机
  被安全策略拦住，未能直接打开核对）。库里的反汇编证据（8100 = SDK 唯一的连接端口）
  与摘要是**两个独立来源的一致结论**，故本轮结论不依赖该 PDF。
- 现场若仍连不上，按 B-5/B-6 两条把「是缺配置、还是连不通、还是读不到」区分开，
  别再来回猜。
