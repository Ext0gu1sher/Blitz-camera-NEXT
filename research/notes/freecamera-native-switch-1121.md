# 原生自由视角切换与重新绑定实验

2026-10-22。用户授权尝试方案 2，并进行实机实验。本轮只新增隔离实验代码和证据，未改工作站、现有跳转按钮或回放重建逻辑。

## 结果和验证边界

在当前 Steam 11.21.0.1235、PID 16160、当前回放暂停于 38.29992866516113 秒的场景中，完整验证了：

- 主线程队列空操作：成功，未提交相机切换。
- 原生自由视角 → 普通视角：成功，提交一次动作。
- 原生普通视角 → 自由视角：成功，提交一次动作。
- 自动重新识别相机，并通过工作站 `/api/connect` 重新绑定：成功，无手动按键、焦点切换或点击。
- 已处于自由视角时再次请求开启：成功，原生动作调用数为 0，没有反向切回普通视角。
- 所有上述实验中回放 raw、origin、rate 和暂停状态保持不变；临时 tick 回调均已恢复，任务执行完毕。
- 13 项本地模拟检查通过，包括主线程、ABI、重复请求、取消、时钟变化、旧 HUD、模式标志不一致和暂停状态。

本次没有再次触发回放回退，也没有覆盖其他回放、客户端版本、连续回退/渲染/退出。切换可行不代表回退重建的既有崩溃已修复。当前场景来自先前已完成的跳转，测试开始前已手动切成自由视角；因此本次采用原生切换回普通视角来复现需要自动恢复的相机状态。

实机报告：

- `output/free-camera-switch-research/20261022T051338966525Z/report.json`：空操作。
- `output/free-camera-switch-research/20261022T051354659346Z/report.json`：切普通视角。
- `output/free-camera-switch-research/20261022T051405030639Z/report.json`：切自由视角并自动重新绑定。
- `output/free-camera-switch-research/20261022T051452131193Z/report.json`：重复开启不会关闭。

较早 `20261022T051320073624Z` 报告是受限进程访问失败，未加载 DLL 或提交动作；随后按已授权实验范围取得所需进程访问，以上四次测试通过。

## 确认的原生调用路径

仅适配 SHA256 `5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608`。以下均为 preferred VA，运行时按模块基址重定位。

1. `CameraModSelector.yaml` 的 FreeCamera 按钮发送 `CAMERA_STATE_CHANGED(true)`，回放界面映射到 `CAMERA_CHANGED`。
2. `ReplayHUDController` 的 `CAMERA_CHANGED` 回调为 `0x1e173e0`，调用约定 `__thiscall(HUD*, Any const&)`，`ret 4`。HUD 主 VFT 为 `0x3853e68`。**this 是 HUD，不能传 GameSceneController。**
3. HUD `+0x120` 为 `AvatarContextReplay`；`+0x148` 为 `ReplayHudModel`，模型 VFT `0x385332c`。参数 bool 的 Any 用原生 `0x717250` 构造：`__thiscall(Any*, bool const*, uint32_t=1)`，`ret 8`；Any 20 字节，结束后对 `Any+4` 调用 `0x6a4720` 清理存储。
4. HUD 回调先更新按键索引 153 的 UI 模型，随后向 context 的事件分发器发送 `.onChangeCameraState`（事件全局 `0x46e8c30`）。
5. 注册回调 `0x1765470` 调用 `0x1772360`，原生流程处理相机控制器、场景相机、输入和 UI，并广播 `.onFreeCameraStateChanged`。

**关键：参数 true 只更新 UI，底层命令仍是 toggle。必须先检查实际模式；已经自由视角时直接跳过调用。**

Context 虚表 `+0x1b4` 指向 `0x1776700`，读取 `context+0x190` 的自由视角 bool；`+0x1b8` 指向原生 setter `0x176f430`。实验只读此标志，不写。若它与 scene/render 的实际相机不一致，则拒绝 toggle，避免误切。

GameSceneController `0x1e15460` 虽会设置自由相机，但跳过上层流程；本实验没有直接调用它或直接改相机指针。

## 执行阶段及接入要求

实验单独复用了已验证的执行方式：临时接管唯一 Replay tick 的 functor `+0x10`，恢复原指针后投递到原生 main-job 队列，在唯一的 `0x92aec0` job pump 回调里执行相机动作，确认与 tick 同线程且 Replay signal 已退出。未调用 seek，未修改游戏文件或时钟/相机字段。

实机观测：动作返回时 `after_mode=-1`，因为 scene 相机已经切换而 render 指针尚未同步；稍后新发现的两组 scene/render 引用一致，模式正确。**必须等新的活动相机链稳定后再连接，不能在原生回调刚返回时立刻绑定。**

后续接入跳转按钮的顺序：

1. 等 native seek 完成，播放器暂停、seek/wait/task 全部结束。
2. 丢弃旧 HUD/context/scene/camera 引用，重新发现当前回放的唯一 HUD 和活动相机链。
3. 检查内部模式和实际相机一致；已自由视角则跳过，否则经主线程队列调用一次原生 HUD 动作。
4. 等 scene 和 render 全部指向当前自由相机，且回放时间不变。
5. 重新创建 `CameraSession`，交给现有跳转后的镜头构图恢复、adopt-session 流程；在该流程内不要再调用工作站 `/api/connect`，以免取消仍进行中的跳转。
6. 不确定结果时停止并报告，不盲目再 toggle，不复用重建前对象，不写 `context+0x190`。

实验命令（在已停止接管、暂停回放时）：

```powershell
python -X utf8 -B research/scripts/verify_freecamera_switch.py --inspect
python -X utf8 -B research/scripts/verify_freecamera_switch.py --execute --mode noop
python -X utf8 -B research/scripts/verify_freecamera_switch.py --execute --mode tracked
python -X utf8 -B research/scripts/verify_freecamera_switch.py --execute --mode free --reconnect
```

`tracked` 仅用于受控复现场景；正式功能只需 ensure-free。`--reconnect` 只供独立实验，不适合直接放进仍活跃的跳转管理器。

源码：`research/scripts/freecamera_switch_1121.c`、`freecamera_switch_selftest.c`、`verify_freecamera_switch.py`。构建产物和 manifest 位于 `output/free-camera-switch-research`，成功实机 DLL SHA256 为 `2344f5e4a578504444897602f345043391fd176893bedd3bc0899bafaa8af573`。当前 DLL 留在进程中但没有活动 hook、队列任务或驻留修补，实验不要求重启游戏。

## 正式跳转流程接入（2026-10-22，后续主聊天）

已将相机切换接入 `blitzcam/freecamera.py` 和 `blitzcam/replay_seek.py`：

- 跳转完成后仅保留进程句柄与仍存活的 ReplayPlayer 身份；重新扫描唯一 HUD/context/scene/render 链，不复用旧场景地址。
- 普通视角时只提交一次原生切换；已经自由视角时不加载或挂接切换组件。切换后等新的场景/渲染引用一致、暂停时钟不变，再创建 CameraSession 并恢复入点构图。
- 使用管理器内部 adopt-session，不调用 `/api/connect`，避免取消正在执行的定位。
- 用户明确要求：若游戏崩溃，跳过后续步骤，再发一次原有的回放启动命令。现通过原进程句柄的 GetExitCodeProcess 确认退出，关闭读取器、结束接管后，仅对原项目绑定文件请求重开一次；不重试跳转，不自动再次构图。超时、读取失败或无法确认退出均不会触发重开。取消、连接代际或项目变化会取消尚未发出的重开。
- 构建脚本为 `tools/build_freecamera_switch.ps1`，正式 DLL 与 manifest 位于 `blitzcam/native/`，桌面打包包含对应组件。研究源码与原始实机报告保持原样。

接入验证：原生本地 13 项模拟检查、53 项相关 Python 测试、播放栏浏览器回归均通过。已覆盖延迟渲染、幂等、取消、退出后跳过远程清理、仅重开一次、启动前项目/连接变化等情况。本次接入未重新执行实机回退或制造崩溃，完整跳转后的恢复与崩溃重开仍待实机验收；前述原生切换成功不代表回退崩溃根因已修复。
