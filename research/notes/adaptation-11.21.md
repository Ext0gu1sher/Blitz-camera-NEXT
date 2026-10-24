# Steam 11.21 只读适配记录

检查日期：2026-10-18。工具版本：0.1.1。本轮只修改工具工作区文件；对游戏仅查询和读取，没有写内存、注入、调用游戏函数、修改资源或自动操作游戏。回放由用户手动打开、暂停和移动镜头。

## 构建与适配选择

- EXE：`C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\wotblitz.exe`
- FileVersion / ProductVersion：`11.21.0.1235`；Steam app `444200`，本机 manifest build `25930627`。
- SHA-256：`5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608`。
- x86 / PE32；文件 73,841,664 字节；SizeOfImage 74,563,584 字节；首选基址 `0x400000`。
- 本次运行模块基址为 `0x1e0000`，读取器按实际基址重定位。本文类型和指令地址均为这个精确 EXE 的首选 VA；不能当作其他版本或当前进程的直接地址。

读取器按 EXE 哈希选择独立的不可变构建配置，再核对架构、首选基址与运行模块大小。原 11.20 精确哈希布局保留；未知构建拒绝。原来的错误提示正是这一保护，不是回放打不开。

## 实际变化

通过 PE RTTI、构造函数静态反汇编与暂停进程对象切片交叉核对，发现只替换哈希和类型地址会失败：

| 关联字段 | 11.20 | 11.21 |
|---|---|---|
| Scene → RenderSystem | `+0xac` | `+0xa8` |
| Scene 的两处相机引用 | `+0x128 / +0x12c` | `+0x120 / +0x124` |
| RenderSystem 的两处相机引用 | `+0xb0 / +0xb4` | `+0xb4 / +0xb8` |

控制器所属的 scene/context/game/free/replay 引用、context→player、GameCamera↔ReplayCameraController、SpectatorCameraController→FreeCamera 在本轮采样中保持原字段位置。生产读取器逐次检查这些关联及各对象的类型。

新主 VFT：ReplayPlayer `0x37c1f44`，AvatarContextReplay `0x37f8a00`，ReplayCameraController `0x3844b80`，GameCamera `0x382da70`，FreeCamera `0x385402c`，RenderSystem `0x3777120`，GameScene `0x3713a60`，GameSceneController `0x3853fd4`，SpectatorCameraController `0x3844c48`。ReplayPlayer 的 `+0xc` 次级 VFT 为 `0x37c1f4c`。完整 RTTI 证据见 [static-rtti.json](../builds/11.21.0.1235/static-rtti.json)。这些名称来自二进制 RTTI，不是公开 SDK 接口。

静态锚点及必要片段：

- [static-instructions.txt](../builds/11.21.0.1235/static-instructions.txt)：FreeCamera 构建分配 `0x26c` 字节，`0x1e0d35d` 写入新 VFT，`0x1e0d3a2` 存入所属控制器 `+0x94`；context 构造在 `0x1743576` 关联 player `+0x1b0`。
- [static-instructions-2.txt](../builds/11.21.0.1235/static-instructions-2.txt)：Scene 构造 `0xd2e22c` 清零 `+0xa8`，`0xd2e36c / 0xd2e376` 清零 `+0x120 / +0x124`；RenderSystem 构造 `0xefe80a / 0xefe810` 清零 `+0xb4 / +0xb8`。初始化本身不证明语义，运行关联匹配提供了另外一层证据。
- Camera 的位置 `+0x38`、方向 `+0x50`、view `+0xc0`、projection `+0x100`、VP `+0x140` 及接口 FOV `+0x268` 在样本中自洽。观察到新投影深度系数 `m22=0, m32=1`；本轮不据此宣布所有渲染路径都采用某种深度方案。水平 FOV 仍由 `2 atan(1/projection[0])` 求出，矩阵乘积和宽高比检查通过。

## 回放时钟

[static-clock.txt](../builds/11.21.0.1235/static-clock.txt) 中 `0x13ecd90` 检查 `+0x35` 初始化状态，取 `+0x18` 并减去 `+0x64`。读取器只接受已初始化活动状态，使用 `raw_time - origin`。

正常推进 `0x140d100` 在 `+0x2d / +0x2e` 特殊推进状态下走另一支路；正常分支先检查 `+0x12` 暂停，再将 dt 乘 `+0x14` rate 累加至 `+0x18`。这证明静态语义仍匹配旧读取规则，但本轮没有播放、变速或跳转的实机测试。

[static-clock-guards.txt](../builds/11.21.0.1235/static-clock-guards.txt) 中 `0x1408dde` 置 `+0x11=1`，`0x1409cd0` 清零该标志，清理分支 `0x1409d3b` 清零 `+0xa0`。`0x1412c76` 使排队任务 `+0x108=0xffffffff`，随后设置特殊推进标志；任务取消也有 sentinel 检查。因此读取器继续拒绝活动跳转、等待或未完成重建状态，不能只看暂停字节。

## 只读实测

完整摘要：[1121-verification.json](../../output/1121-verification.json)。原始读数和录制可核查，数字不是成功率估计。

1. [起始机位](../../output/1121-live-snapshot.json)：暂停 `23.61650562286377` 秒，XYZ `[-135.5417786, -130.8596954, 34.7776871]`，水平 FOV `68.41167535°`；接口 FOV 是 `54°`，不能混用。
2. [静止 5 秒摘要](../../output/1121-paused-recording.jsonl.summary.json)：50 Hz 调度，250 次尝试全部有效，时间和位置均只有一个值。这是读取采样，不是 250 个渲染帧。
3. [手动平移 45 秒录制摘要](../../output/1121-manual-movement.jsonl.summary.json)：用户在其中一小段按 W；2250 次尝试中 2241 有效，9 次相机与矩阵暂未一致被丢弃。回放时间始终相同，191 个不同位置，最大位移 `5.3707044` 个客户端世界单位。朝向、FOV 在这段有效记录中没有变化，所以转向、横滚、变焦的动态响应仍未验证。
4. 有效样本最大眼点变换误差 `7.8126e-5`，旋转正交误差 `1.2921e-7`，view×projection 与 VP 最大分量误差 `1.2846e-5`。这些为数值一致性证据，不是画面像素误差。
5. 新后台 [HTTP 连接与遥测](../../output/1121-http-state.json) 成功，Server 为 `BlitzCameraLab/0.1.1`，快照构建为 11.21，能力仍为只读。未更新用户既有项目。
6. 52 项离线测试通过：[测试日志](../../output/1121-offline-tests.txt)。新增真实对象切片回归、旧字段位置拒绝、新旧哈希选择、未知哈希拒绝、架构/模块大小检查及相机引用切换停止测试。旧客户端本轮没有重新启动复测。

## 结论与下一步

后续本构建更新链已继续定位，见 [11.21 相机更新链与 A 恢复实验方案](restore-experiment-11.21.md)。该记录包含新的原生更新/约束/矩阵证据、只读预检与 R1/R2/R3 分阶段验收；没有执行游戏写入。

0.1.1 已恢复这个精确 11.21 构建的暂停机位读取、保存和后台显示。暂停时原生自由镜头平移响应已观察到；姿态和 FOV 的静态读数通过矩阵校验。

仍未验证 engine-active-root→当前 scene 的独立根链、引擎帧屏障或最终呈现帧，因此保留 `active_root_verified=false`、`frame_synchronized=false`、`engine_tick_fence=false`。没有把匹配对象链升级成最终画面逐帧证明。

A 的“恢复”部分仍未执行。原 [恢复实验方案](runtime-evidence-and-restore-plan.md) 及 [FreeCamera 更新研究](freecamera-update.md) 主要属于 11.20 历史证据：其中函数地址、字段和写入顺序不能直接用于 11.21。恢复前必须重新追踪本构建目标位置/平滑状态→FreeCamera→矩阵更新的具体链，并提交限定在确认回放模式下的单次实验。本轮适配不放行任何游戏写入。

未来更新需重查哈希、类型与字段、相机更新链、投影及回放状态；同版本号的新 EXE 也要重新核对。本地回放用途不构成运营方许可，未对运营规则风险作保证。
