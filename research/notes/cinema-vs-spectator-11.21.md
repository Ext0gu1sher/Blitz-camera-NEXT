# Cinema 与普通自由镜头的区别（11.21）

日期：2026-10-24（Asia/Shanghai）。用户先要求调查并可做独立 Web 实验，随后调整为先比较区别、差别不大则不做。最终未创建或启动独立网页，也未修改游戏配置或写游戏进程。本轮在用户调整任务前打开了当前项目已使用的本地回放；后续只读检查确认其已暂停并处于 Cinema 自由镜头。

## 结论

Cinema 是游戏内置的另一种自由镜头控制器，和 Spectator 共享主要移动、旋转、FOV、平滑更新实现。它不等于赛事双方观战模式。本轮没有发现 Cinema 自带独立轨道编辑、关键帧系统或赛事血量界面的证据。

更重要的是，本机当前配置已启用 Cinema，当前运行回放也确实使用 Cinema。因此不需要为了“试用另一套电影相机”额外制作独立网页；现有项目已经识别并支持这个控制器类型。此次仅验证配置映射、运行时识别和共享实现，未新增运镜写入试验，不能将识别成功写成所有运镜行为已实测。

## 证据范围

当前 EXE 仍为 11.21.0.1235，SHA-256：`5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608`。以下代码地址均为 preferred VA，不能直接当成运行地址。

原始输出：

- `output/cinema-lab-research/creation-and-config.txt`
- `output/cinema-lab-research/controller-differences.txt`
- `output/cinema-lab-research/mode-and-bounds.txt`
- `output/cinema-lab-research/live-readonly.json`

静态反汇编只把磁盘 EXE 数据映射到分析程序自身的不可执行内存；DbgEng 只附加自身。运行时使用项目已有 ReadOnlyMemory 和 CameraSession，访问权限为查询和读取。

## 已完成配置名称与创建条件的映射

1. `0x37031BC` 是 `Dev Cinema Camera`，`0x3703194` 是 `Replays`。
2. `0x006D6EE5` 引用该选项名，`0x006D6EFE` 引用分组名，读取结果在 `0x006D6F27` 保存至配置对象 `+0x52D`。
3. `0x01753249` 读取同一配置字段。真分支在 `0x0175328A` 调用 Cinema 构造 `0x01B8FD40`，并保存到所属对象 `+0x68`；假分支在 `0x017532D9` 调用 Spectator 构造 `0x01D49300`。
4. Cinema 构造在 `0x01B8FD6C` 调用共同基类构造 `0x01B8EDC0`，随后写入 VFT `0x03830F9C`。Spectator VFT 为 `0x03844C48`。

项目已有 KeyedArchive 解析器完整消费了本机 `AppData/Local/wotblitz/DAVAProject/optionsGlobal.bin`，其中 `Replays / Dev Cinema Camera / value` 为 `true`。用户旧有 camera plugin 样本也为 true，original 样本为 false。本轮没有改写这些文件，也没有改动其他回放设置。

这补足了旧调查中“配置字段名尚未独立映射”的缺口。资源默认值 false 与用户当前实际覆盖配置 true 必须区分。

## 差异与共同点

| 项目 | Cinema | Spectator | 证据与边界 |
| --- | --- | --- | --- |
| 底层相机 | 控制 FreeCamera | 控制 FreeCamera | 不是一个完全不同的渲染相机体系 |
| 主要状态更新 | 共同基类及共同更新路径 | 同左 | 平移、朝向、FOV、平滑状态布局共用；不能仅凭 Cinema 名称宣称更高级的运镜算法 |
| 初始空间边界 | 三轴均为 -500 到 +500 | 由场景相关函数计算 | Cinema 常量来自 `0x037FC3A0` 加两个 500，传入共同构造；Spectator 走 `0x0175DC70`，包含 `Landscape` 与 `CameraMaxZ` 资源引用 |
| 一条位置约束检查 | virtual slot 6 直接返回 false | 特定场景条件下调用额外函数 | Cinema 为 `0x006CD9B0`，Spectator 为 `0x01D50610`；尚未完全命名额外算法，不能宣称关闭全部碰撞或所有地图边界 |
| 启用／停用 | 比公共逻辑多一次模式设定，启用传 2，停用传 0 | 不做这两个额外调用 | `0x01BA74B0` / `0x01BA7220` 调 `0x00AB9EB0`；接收者精确类型与枚举语义尚未确认，不将它写成 HUD 或光标开关 |
| 赛事信息与全知数据 | 未见因此启用 | 取决于观战身份、数据与 HUD | 不可由控制器切换推导能看到双方完整战斗状态 |

`Cinema.yaml` 在共同基类构造中加载，包含移动、角速度和速度平滑配置。因此文件名也不能证明这些能力只属于 Cinema。

## 本机运行时确认

读取 PID 93944 的当前回放，得到：

- 活动控制器：`CinemaCameraController`。
- Cinema 候选 1，Spectator 候选 0，完整有效对象链 1。
- 控制器、FreeCamera、场景及渲染引用通过现有完整身份检查。
- 回放暂停，回放时间 `48.219282150268555` 秒。
- 控制器空间边界实读为 `[-500,-500,-500]` 至 `[500,500,500]`。
- 位置盒列表为空；不能只据空列表推断所有场景约束都消失。

该运行时结果证明当前回放真正启用了 Cinema，而不仅是配置为 true 或 EXE 中有类型名。仅代表本次会话，不追溯断言此前所有回放都使用 Cinema。

项目的 `CameraSession`、`PROFILE_1121` 和已有播放配置已接受并锁定实际 Cinema/Spectator 类型。本轮未改这些功能。此前 `cinema-controller-compatibility.json` 中还有另一台机器的只读 Cinema 诊断，这与本次本机观测相互印证；离线模拟测试依然不等于完整实机运镜验证。

## 决定

按用户最新要求，不继续制作独立 Web。Cinema 的主要增量在自由镜头的边界、约束和启停模式；对当前已控制位置、旋转、FOV 的工作站没有发现值得单独起一套工具的新能力。后续如果目标仍是赛事截图，应继续研究观战 HUD 与回放数据范围，而非单凭 Cinema 分支推导赛事功能。
