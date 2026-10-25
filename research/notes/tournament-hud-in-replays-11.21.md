# 11.21 回放中的赛事观战 HUD：可行性调查

后续实机进展：用户授权后，回放副本已成功创建原生赛事血量界面。自由视角显隐实验见 `tournament-observer-experiment-11.21.md`；以下保留实验之前的调查状态。

日期：2026-10-24。范围：Steam 11.21.0.1235_7376187，普通本地回放。此次只读取游戏文件、回放文件和运行内存；没有改变观战身份、补丁、调用游戏函数或创建实验 Web。

## 结论与证据等级

- **已验证**：普通发行客户端包含原生赛事 HUD。其初始化条件为 HUD 使用的观战模式等于 Both（2）。顶部双方总血量、两侧赛事队伍面板和双方车辆标记各有相应创建分支。
- **已验证**：回放上下文的观战模式与 HUD 使用的玩家观战身份不是同一个值。当前样本前者已经是 2，后者是 0，赛事总血量控制器未发现。只把回放上下文设为 2，不能解决当前问题。
- **有明确依据、尚待激活试验**：可以研究在回放初始化之前改变被 HUD 读取的玩家观战身份，使客户端自行创建赛事 UI。回放的车辆名单实际有 `observer_mode` 协议字段；不是只能凭空加载一张 YAML。
- **不能据此承诺**：尚未在此样本中成功启用赛事 HUD；尚未证明只修改车辆名单的一个字段就足够。普通玩家回放存在实际数据空缺，无法通过开启界面恢复没有录下的完整战场运动。

## 构建与样本

- EXE：`C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\wotblitz.exe`
- SHA-256：`5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608`
- 样本：`C:\Users\Ext1nguisher\Downloads\20261015_2239__Wot_Bismarck_Maus_583139071758493108.wotbreplay`
- `meta.json`：version 11.21.0，arenaBonusType 1，录制者 Wot_Bismarck / Maus。
- 下文静态地址均为 EXE 首选基址 0x400000 下的 VA，不能跨构建使用。运行指针只是本次采样的临时地址。

## HUD 的实际选择路径

枚举注册函数 `0x706AE0` 与 protobuf 描述符一致：None=0、Team=1、Both=2。

`HUDLayer` 初始化函数 `0x1DB8DD0`：

1. `0x1DB8FB4` 调用上下文虚表 `+0x28`，得到管理战斗模型的对象。
2. `0x1DBA81E` 调用 `0x1D537A0`，根据当前 Avatar 的实体 ID 查询模型。
3. `0x1DBA823` 取模型 `+0x80`，`0x1DBA829` 保存到 `HUDLayer+0x180`。
4. `0x1DBAB32` 比较该值是否为 2，把结果交给队伍面板初始化函数 `0x1DC6AF0`。
5. `0x1DBAD37` 调用状态栏初始化函数 `0x1DB4760`；该函数同样检查 `HUDLayer+0x180 == 2`，选择赛事资源，进而在 `0x1DB4A7D` 创建 `ObserverBattleStatusController`。

资源包括 `Battle/HUDLayerTournament`、`ObserverBattleStatusControl1`。标记原型初始化 `0x1B96D40` 另按模式区分普通、单队观战与 `SpectatorBothVehicleMarker`；完整调用参数链尚未闭合，不把它当作已完成的激活方案。

`0x1D537A0` 的查询链：manager `+0x34` → context 虚表 `+0x18C` → Avatar → `0x701A60` 读取 Avatar `+0x0C` 的实体 ID → `0x1D54100` 查 manager `+0x110` 的映射 → 返回玩家模型。该路径已用当前进程只读核对。

## 为什么直接改回放上下文无效

`AvatarContextReplay` 虚表 `0x37F8A00` 的 `+0xAC` 项是 `0x7BD830`，返回对象 `+0x1B8`。构造函数 `0x1743589` 将构造参数写入这一字段。

本次运行采样：

| 项目 | 读取结果 |
|---|---|
| 进程 | 93944 |
| 已验证回放上下文 | `0x0F9F0990` |
| context `+0x1B8` | 2 |
| 相机控制器 | CinemaCameraController |
| 当前 Avatar 实体 ID | 136616900，与样本录制者一致 |
| 管理模型对象 | `0x491BF930`，其 `+0x34` 正确指回同一 context |
| 当前玩家模型 | `0x31C4B420` |
| 当前玩家模型 `+0x80` | 0 |
| HUDLayer | `0x36B9D8D8`，主、次虚表均匹配 |
| HUDLayer `+0x180` | 0 |
| ObserverSystemController | 找到 1 个主虚表候选 |
| ObserverBattleStatusController | 私有可读内存扫描未找到主虚表实例 |

最后一项是本次扫描结果，不是所有运行状态的不存在证明。这里最关键的正证据是 HUD 来源模型和 HUD 本身都为 0，而回放上下文已为 2。

## 回放身份字段与数据边界

EXE 内 protobuf 描述符明确声明：

`UpdateArenaGenerated.VehicleInfo.observer_mode` = 字段 14，枚举 `ObserverMode`。

`VehicleList.vehicles` = repeated 字段 1。样本 `EntityMethod 48 / wrapper 1` 的 root field 1 → repeated field 1 得到 14 个车辆名单项。全部没有显式字段 14，对应默认 None；录制者也如此。样本 `meta.json` 没有 `observerMode` 键，不应凭另一个同名字符串就声称修改 meta 能生效。

协议字段到模型 `+0x80` 的赋值函数尚未逐指令闭合，因此“修改该字段可触发完整赛事 HUD”仍是待验证假设。

依据项目已使用的上游解析器，对样本的实体离开/重新进入记录进行计数：有 **17 段**车辆 Type4 → Type5 重入区间，全部在区间内部没有该车辆的 Type10 运动更新；最长 **84.3986 秒**（原始记录时钟 107.737854 → 192.136459）。这直接证明这份普通回放不是完整全场运动记录。它不独立证明所有血量或装填字段都缺失；这些数据仍须逐项审计，不能默认齐全。

## 后续实验优先级

1. 若有同版本、以 Both 观战身份录制的回放，先与普通样本比较初始化名单、Avatar 属性和 HUD 生命周期，作为对照。
2. 普通样本只在复制件上验证“初始化前的玩家观战身份覆盖”，让原生流程创建赛事状态栏、队伍面板及标记。仍需保留原有参赛车辆，核对人数和血量统计，避免将录制者误排除。
3. 验证暂停、跳转、重开回放时是否重建一致，检查自由镜头下 HUD 是否被另一条可见性逻辑隐藏。
4. 将成功标准分为“原生赛事界面成功创建”与“信息完整且正确”；后者不能靠界面激活弥补缺失的原始记录。

## 可复查材料

原始调查输出在 `output/observer-replay-research/`（忽略目录）：`static-anchors.json`、`hud-gates.txt`、`caller-functions.txt`、`observer-source.txt`、`model-source.txt`、`live-readonly.json`、`replay-roster.json`、`visibility-gaps.json`。少数探索反汇编从非指令边界开始的行不作为证据；上述引用均使用已确认的指令边界。

- [官方训练房观战说明](https://www.wargaming.net/support/en/products/wotb/article/15441/)：公开客户端支持单队/双方观战，以及 C 键自由镜头；该说明没有承诺普通回放能切成赛事观战。
- [当前项目固定版本的上游 arena.rs](https://github.com/fanypcd/WoT-Blitz-Agent/blob/0a9da93a0074a95af406db3468e6a81a5a6b139f/crates/replay-core/src/replay/combat/arena.rs)：`collect_aoi_lifecycle`、`decode_update_arena2`，用于回放包解析及运动覆盖检查。上游语义与本地样本统计分开记录，未把外部注释当作当前样本的实测结果。
