# 11.21 赛事观战回放实验

2026-10-24，接续 `tournament-hud-in-replays-11.21.md`。用户明确授权开始实验；仅使用本地回放副本与当前暂停回放。

## 已完成

### 实验 A：在回放初始化前指定录制者观战身份

`research/scripts/make_observer_replay_trial.py` 对样本 `EntityMethod 48 / wrapper 1` 开局名单中、dbid 与 `meta.json` 录制者一致的那一项，增加 `VehicleInfo.observer_mode = 2`。

- 原始包序号 4，raw clock `0.1692429929971695`，实体 `136616900`。
- 仅这一包有业务载荷变化，增加 2 字节；同步修正嵌套 protobuf、方法参数、包和文件的长度。
- 元数据、结算数据、其他数据包和末尾终止记录保持原样。末尾 16 字节的语义没有猜测或重算；客户端随后实际接受文件。
- 将增加的字段撤销后，整个 `data.wotreplay` 与原始内容逐字节一致；ZIP CRC 正常。
- 原始回放 SHA-256 `50ae08302cd51c1d5990c69d799e8733ffa7f067efee066b2584c586bf0b40e7` 未改变。
- 实验副本 SHA-256 `af101551857fed5603d952b28357ee71628c0287c9d363fc88e0cdd7e55ae853`。

游戏导入副本到自身 `DAVAProject/replays/observer-both-player.wotbreplay`。读取当前 ReplayPlayer 所持有文件，哈希与实验副本相同，排除误读原回放。

实测玩家模型 `+0x80` 从 0 变成 2，HUDLayer `+0x180` 为 2，ObserverBattleStatusController 实例从 0 个变为 1 个。用户确认普通跟随视角出现两侧逐人血量与顶部双方总血量。

**结论：当前样本中，普通回放能够通过开局观战身份字段激活原生赛事血量界面，不需要替换游戏 EXE。**

### 实验 B：自由镜头保留赛事 HUD

用户确认切入自由镜头后 HUD 隐藏，显示界面的眼睛按钮也不可用。只读快照确认自由镜头已激活、赛事控制器仍存在，HUD 仍为模式 2。

定位到 `BattleController`（不是 AvatarControllerReplay 或 AvatarGameLogic）：

- 主虚表 preferred VA `0x37F8F70`，`+0x120` 指向同一回放上下文。
- 切相机函数 `0x1772360` 调用 `0x1751400` 改变界面显示计数，并分别设置图层可见性。
- 当前 `BattleController+0x158` 计数为 0，其 `+0x150` 所指对象的 `+0x18` 为 1，满足隐藏分支。
- 经 `BattleController+0x150 → +0x38`，取得 `+0x5C/+0x60/+0x68/+0x6C` 四个 UI 图层。其中 `+0x60` 精确对应已验证 HUDLayer。
- `HUDLayer+0x260` 还有一个单独隐藏的 UI 控件，在切换代码中被单独设为不可见；后续 UI 树确认是 `NotificationHolder/NotificationIconContainer`，不是小地图。
- `0xD05020` 为此次使用的原生可见性 setter：参数为 bool，更新 UIControl `+0x4C` 的 bit 1，并执行原生状态通知。

临时工具只在主线程任务队列中对上述五个现有控件调用 setter，不改摄像机指针、显示计数、回放时钟或游戏文件。执行前验证精确构建、回放副本哈希、暂停状态、主线程、对象引用、赛事身份与原生代码字节。

本地 13 项模拟验证通过：空操作、显示、恢复隐藏、幂等、时钟变化、普通 HUD、失效引用、回调阶段、线程、超时监督、两种取消和未暂停拒绝。

实机空操作通过，随后显示操作通过：

- 5 次原生显示调用，状态掩码从 0 变为 31。
- tick 和主线程任务同为线程 107404；临时回调已恢复，队列任务已结束。
- 自由镜头前后均保持开启。
- 回放 raw `48.24052047729492`、origin `4.18244743347168`、播放时刻 `44.05807304382324`、暂停状态均未变化。
- 用户随后确认“赛事界面和标记均出现，标记跟随正常”。这证实自由镜头与原生赛事展示可以同时运行，但不代表完整功能正确，后续发现的副作用见下文。
- 后续只读复核 `after-show-check.json`：同一回放仍暂停在 `44.05807304382324` 秒，自由镜头开启，四个顶层控件的可见位仍为 1，赛事控制器仍存在。此复核没有再次执行显示调用，也不替代画面确认。

## 限制

本实验没有补足原回放缺失的敌方位置、血量或装填数据。实验 A 复用参战者身份确实影响车辆筛选，实验 C 使用独立虚拟身份已解决原主角缺失；双方总血量仍未逐项对照验证。可见性操作是一次性的，切换相机、拖动时间或重建回放后可能需要重做。仅验证当前 11.21.0.1235 构建及这个样本，尚未接入正式工作站。

## 用户后续验证：身份复用存在副作用

- 录制者同时缺失于侧边血量名单与头顶标记。
- 底部个人血条仍显示；原录制者开镜、受击时还会触发位置异常的个人 UI 提示。
- 静态检查确认 `TeamPanelLogic` 的车辆加入回调 `0x1D8E8F0` 在 `0x1D8E929` 检查 `ArenaVehicleInfo+0x80`；非零会直接跳过。所以将参战者改成 observer 导致名单缺人，有确切代码依据。
- 当前 UI 树仍有 `HUDLayer/BottomHUDLayoutProtector`、`Ammo`、`ConsumablesPanel` 与 `BattleUILayer/AimContainer` 等个人控件。五个图层全显示不能充当完成版观战 UI。
- `output/observer-replay-trial-20261024/self-missing-ui-tree.json` 保存了 1698 个控件的只读树快照；四个图层的名称分别为 `BattleUILayer`、`HUDLayer`、`TankDirectionViewBackground`、`TankDirectionView`。

用户提出“创建虚拟角色，由它启动回放”。独立实验 C 保留原始 14 个名单条目的原始字节，增加一个 `ReplayCamera` 观战身份，并在该样本的唯一 Type 1 cell 初始化中，将玩家车辆引用（payload +41）改为新 ID。客户端日志及实时 `BattlePlayerInfo+0x0C` 均确认 ID 变为 `0x70000001`、observerMode 为 2；这一偏移只在当前样本验证，不能推广为所有回放的固定布局。

实验 C 第一版不添加 Type 33/5 实体，只修改第 4、10 两个包；身份绑定成功但加载卡住，用户确认并重启客户端。文件与清单位于 `output/virtual-observer-trial-20261024/`，生成器为 `research/scripts/make_virtual_observer_trial.py`。

### 实验 C 第二版：实体化虚拟观战者并隐藏模型（用户已验证）

`virtual-observer-materialized.wotbreplay` 的 SHA-256 为 `35d3159d5b3f662539202fbdbb0ad3ed71ad4d8f9cafc5bafa4b7175e65323af`。在第一版基础上，克隆原录制车辆的 Type 33 准备包、Type 5 创建包，把实体 ID 和名字改为虚拟观战者；保留其他原始业务包、元数据、结算和终止记录。逆向撤销转换后完整数据仍与原样本逐字节一致。

第二版正常加载。只读名单包含原始 14 名普通参战者和 1 名观战者，原录制者仍是 observerMode 0。用户确认原主角 Wot_Bismarck 出现在侧边名单和头顶标记中。赛事展示采用掩码 3，只显示 `BattleUILayer`、`HUDLayer`；另外隐藏 12 个已识别的个人 UI 根控件，包括 `AimContainer`、`BottomHUDLayoutProtector`、弹药、消耗品和方向/提示相关面板。用户确认底部个人血条消失。

实体化会在原出生点多出一辆不动的 Maus。采用保留实体、仅隐藏三维模型的方案：

- 精确身份链：`AvatarContextReplay+0x1AC → BattlePlayerInfo+0x10 → VehicleGameLogic+0x74 → TankVisual`；玩家车辆 ID 与 TankVisual+0x58 均须为 `0x70000001`，并校验各类型虚表和引用。
- 当前构建原生 `DAVA::Entity` 可见性入口为 preferred `0xD71EF0`，调用 `0xD71E50`。默认可见性类别由 `0x471EF94` 指向，编号 0、名称 `User`（静态初始化及运行时数据交叉验证）。
- 它递归改变每个实体 `+0x48/+0x4C` 的可见性原因掩码，并通过 `0xDBDDC0` 更新渲染对象/粒子显示。没有删除实体、改坐标、改血量或碰撞数据。
- 本次虚拟车有 128 个模型节点；先完整保存其父子结构、类型、原始掩码，再在主线程调用一次隐藏。其余类别位保持不变。恢复按前序逐节点重放原始 User 可见性，保留原本隐藏的部件。
- 组件 v3 使用 Magic `0x33485542`，原生/Python 布局一致：Config 8720、Header 60、Shared 8780 字节。27 项本地验证通过，新增覆盖虚拟车与原参战者区分、完整树/父子引用/状态变化拒绝、递归隐藏及混合原始状态恢复。
- 实机空操作 `141718307517-probe/report.json` 通过，无可见性调用。
- 实机显示/隐藏 `141806661955-show/report.json` 通过：12 次 UI 调用加 1 次虚拟车模型隐藏，128 个节点的 User 隐藏位均置位，其余掩码保持；回放 raw `82.65925598144531`、暂停状态及自由镜头保持，任务已结束、临时回调已恢复。

用户最终确认：**额外 Maus 已消失，其余车辆正常；继续播放到原主角开镜、受击位置后，屏幕中央错位提示、底部个人血条和镜头异常均未再出现。** 这是当前样本的实测通过，不代表任意回放、时间跳转和相机反复切换均已验证。

当前复现（先打开第二版，切自由视角并暂停）：

```powershell
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action probe --clean --hide-ghost --manifest output/virtual-observer-trial-20261024/manifest-materialized.json --url http://127.0.0.1:58123
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action show --clean --hide-ghost --manifest output/virtual-observer-trial-20261024/manifest-materialized.json --url http://127.0.0.1:58123
```

完整恢复使用同一会话中该次 show 报告的 `--action restore --restore-report <report.json>`，并传入同一 manifest 和服务地址。恢复在模型树结构或上下文改变时拒绝执行；新的回放须重新读取对象。

## 文件与复现

- 实验回放：`output/observer-replay-trial-20261024/observer-both-player.wotbreplay`
- 原样对照：同目录 `original-control.wotbreplay`。
- 来源与差异：同目录 `manifest.json`。
- 只读快照：`after-load.json`、`free-camera-hidden.json`、`free-camera-visibility.json`。
- 原生空操作：`125856032709-probe/report.json`。
- 原生显示：`125958906394-show/report.json`。
- 早期 `125727599246-probe/report.json` 是工作站服务地址过期造成的连接失败，未读取游戏或加载组件。随后核实实际仍运行的服务为 `127.0.0.1:58123`，处于停止且已撤下接管状态。

脚本：

```powershell
python -X utf8 -B research/scripts/inspect_observer_trial.py --out output/observer-replay-trial-20261024/check.json
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action probe --url http://127.0.0.1:58123
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action show --url http://127.0.0.1:58123
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action restore --restore-report output/observer-replay-trial-20261024/125958906394-show/report.json --url http://127.0.0.1:58123
```

恢复操作只接受同一会话中的原控件地址和上下文；不会把旧地址用于新回放。组件源码 `observer_hud_visibility_1121.c` 基于现有自由相机主线程调度实验；独立测试为 `observer_hud_visibility_selftest.c`。未修改正式组件。上述早期 v1 布局为 Config 172、Header 60、Shared 232 字节，当前 v3 布局见实验 C。
