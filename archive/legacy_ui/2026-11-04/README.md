# 旧版UI退役备份

退役日期：2026-11-04。备份来源提交：`a6941638602d86da2183b4b151c0eac53d22fa22`。

`legacy_ui_source.zip`包含退役前已提交的main.py、src/ui_v2和src/ui_common源码；manifest.json记录文件清单和SHA256校验值。快照不包含工作区中其他任务尚未提交的修改，不作为运行入口、不参与SDK初始化。

## 当前处理

启动小窗仅显示四个industrial工作区；取消经典布局入口与“试用”标识。历史classic启动选择统一回退至industrial。旧版布局代码暂留并标记，以便恢复和依赖梳理。

## 保留依赖，不能整目录删除

- src/ui_v2/workspaces/：新版仍复用其中的控制按钮、状态门禁和业务信号。
- src/ui_v2/industrial_presentation.py：将原布局保留为classic容器，并把共享内容移入新版布局。
- src/ui_v2/main_window.py：set_presentation的classic分支仅供内部兼容/回归，启动UI不再提供入口。
- src/ui_v2/backend_bridge.py及ui_common：设备服务、后台任务、日志、渲染等正式共享代码，不属于可直接删除的旧版专属代码。

后续删除前需梳理工作区动作和信号连接，完成采集、会话、标定、拼接、后处理与关闭生命周期回归。不要把备份所覆盖的全部文件当作退役专属代码。

如需参考旧实现，先校验manifest中的SHA256，再把zip解压到独立临时目录；对照文件恢复必要片段，勿覆盖当前工作区。
