# 摄像机类型与赛事观战界面调查（11.21）

日期：2026-10-24（Asia/Shanghai）。范围：官方资料、用户提供的赛事截图、当前普通 Steam 客户端的静态文件及已有项目研究。没有启动或操作游戏，没有写进程内存或修改游戏资源。本次没有实测观战房间，也没有取得截图所用网易赛事客户端。

## 结论

截图中的自由飞行、红蓝双方车辆标记、逐车生命值、队伍总生命值、点亮提示和装填状态，与普通客户端自带的双方观战及赛事 HUD 高度吻合。实现这些核心功能不需要假设另有定制客户端；但不能据此证明该场网易赛事实际使用了哪个客户端版本。

观战不是只有一个不同的 Camera：至少要区分镜头控制、观战身份/信息范围、HUD 呈现和直播包装。截图本身不能判断是现场观战还是观战录像重播。顶部队标、系列赛比分和赛事横幅具有直播包装特征；没有制作工程，无法确定具体叠加方式。

## 官方公开依据

- [Wargaming：Spectator Mode in Training Battles](https://www.wargaming.net/support/en/products/wotb/article/15441/)：房主可分配仅观看友军或观看双方的观战身份；支持 C 开启自由摄像机及 1–9 调速。由此确认普通训练房已有公开观战入口，不是只对官方解说开放的新功能。该页面适用于 Wargaming 版，不能代替当前网易版的实测。
- [官方 Steam 4.6 更新公告](https://store.steampowered.com/news/posts/?appgroupname=World+of+Tanks+Blitz&appids=444200&enddate=1519806023)：2018 年已明确区分仅己方和双方观战，提及生命值、车辆编号及蓝队切换；当时取消了仅己方模式的自由镜头。它提供历史依据，不作为当前所有按键和限制已经实测的证明。
- [官方 Steam 历史公告：4.1](https://store.steampowered.com/oldnews/?appgroupname=World+of+Tanks+Blitz&appids=444200&enddate=1514793600&feed=steam_community_announcements)：包含第一人称观战准星抖动修复记录，证明第一人称观战并非推测出来的独立功能。

## 当前客户端静态证据

安装位置：`C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz`。

- 资源版本：`11.21.0.1235_7376187 release/11.21.0 WOTB_Win7`。
- EXE SHA-256：`5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608`。
- 本次解压的资源通过 DVPL 长度、CRC32 和解压后长度检查；副本保存在 `output/archive/2026-10-27/research/camera-mode-survey-20261024/decoded/`，索引和原资源哈希见同目录 `evidence.json`。

| 证据 | 文件及行号（解压副本） | 意义 |
| --- | --- | --- |
| 训练房双方观战选项 | `UI/Screens/Lobby/Training/PrebattleRoomSpectatorPopup.yaml:54` | `WatchBothTeams` 是普通客户端已有 UI 选项 |
| 双方玩家列表 | `UI/Screens/Battle/HUDLayerTournament.yaml:95` | `UITeamPanel` / `UITankPanelTournament` |
| 玩家名、车型、数值血量、点亮灯泡 | 同文件 `:177`、`:198`、`:214`、`:232` | 与截图两侧列表对应 |
| 顶部双方总血量 | 同文件 `:368`、`:397`、`:422` | `ObserverBattleStatusControl` / `HealthLeft` / `HealthRight` |
| 双方车辆标记 | 同文件 `:646` | `SpectatorBothVehicleMarker` |
| 头顶血条及装填条 | `UI/Screens/Battle/VehicleUIObjectMarker/VehicleUIObjectMarkerTournament.yaml:91`、`:100` | `Health` / `LoadState`，后者使用 `spectator-style` |
| 开发用电影相机选项 | `optionsGlobal.yaml:4032` | `Replays / Dev Cinema Camera` 默认 `false` |

中文资源中真实文本为“只观看友军”“观看双方团队”“停止观看”“设置旁观者”；亦含观察者名额和设备不支持的提示。原文行号节选保存在 `localization-excerpts.txt`。

截图顶部的 19,798 和 22,096，分别恰好等于左右七名玩家所示当前血量之和。这是队伍生命值；附近的 420/480 是另一组占领积分。不能把这些数值或直播比分的变化当作另一种镜头的证据。

## 值得区分的镜头用途

| 用途/模式 | 已有证据 | 控制能力的验证边界 |
| --- | --- | --- |
| 普通战斗第三人称、瞄准视角 | 当前 `GameCamera`、`CameraController` 等类型；官方历史资料亦明确第一人称观战 | 不是本轮验证过的新接管接口；不能把每种视角都命名成独立 Camera 类 |
| 回放原视角 | 当前 `ReplayCameraController`、`ReplayHUDController`；已有原生普通/自由切换实验 | 原生切换在既有 11.21 实验中验证过 |
| 回放自由视角 | 当前 `FreeCamera`、`SpectatorCameraController`、`BaseSpectatorCameraController` | 当前项目已控制的主要路径；类名含 Spectator 不代表具有双方观战身份 |
| 训练/赛事观战的跟随、第一人称和自由飞行 | 官方文档、当前观战输入控制器和赛事 HUD | 功能存在；当前项目尚未在真实双方观战场景验证绑定、切镜、时钟或回放兼容性 |
| Cinema 电影相机分支 | 当前 EXE 有 `CinemaCameraController`，配置有默认关闭的 `Dev Cinema Camera` | 已有 11.20 研究追到 Cinema/Spectator 条件创建与共同基类；尚不能直接套用旧地址，也未证明当前配置字段与创建条件的完整绑定或实际启用成功 |
| 车库镜头 | 当前 `HangarCameraController`、`NewbieHangarCameraController` | 独立使用场景，不能由类型存在推断战斗中可直接切用 |

当前 EXE 另含 `ObserverSystemController`、`ObserverCachedVehicleState`、`ObserverBattleStatusController`、`ObserverUIObjectMarker`、`ObserverCameraStateListener`、`ObserverGunStateListener`、`KeyboardMouseInputSpectatorController`、`GamepadInputSpectatorController` 等类型字符串。它们是后续定位线索，不是已验证的导出 API、字段布局或调用地址。

已有相关研究：`freecamera-update.md`、`adaptation-11.21.md`、`freecamera-native-switch-1121.md`。不能将 11.20 的地址当作当前 11.21 的地址。

## 对项目的研究方向

1. 比较普通回放在普通/自由镜头下的 HUD 和标记隐藏条件，定位哪些显示策略属于 `ReplayHUDController`，哪些属于观战控制器。
2. 在房主正常分配的双方观战场景取得运行时对象关系，确认是否复用同类 FreeCamera 和 SpectatorCameraController，以及赛事 HUD 的初始化入口。需要真实训练房场景才能完成，静态文件不能替代这一步。
3. 核对玩家回放和观战回放的实体、血量、装填、点亮及视角数据范围。没有记录的数据不能仅凭显示开关或镜头切换恢复；本轮未证明某一份回放包含完整双方状态。
4. 将“自由镜头保留 HUD”和“原生赛事 HUD 复用”作为两项独立候选。前者也要确认数据与投影正确；后者还需要观战模型及生命周期，不能仅加载 YAML 或改 observer 标志就宣称完成。
5. Cinema 分支单独调查，其存在不是截图属于秘密赛事客户端的证据。

本次没有变更工作站功能。`output/` 内的静态证据为调查产物；已有其他工作区修改不属于本次研究。

后续更新：同日进一步完成了 `Dev Cinema Camera` 到配置 `+0x52D` 的静态映射，并在本机回放只读确认 Cinema 实际活动；详见 `cinema-vs-spectator-11.21.md`。上表中的未验证状态描述的是本篇初次调查时的边界。

后续更新：同日已继续追踪赛事 HUD 的创建条件，并只读确认普通回放上下文模式为 Both、玩家模型与 HUD 模式却为 None；详见 `tournament-hud-in-replays-11.21.md`。已定位初始化入口，但尚未实测启用赛事界面。
