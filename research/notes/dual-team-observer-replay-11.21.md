# 双方回放合并与赛事观战：11.21 实测

日期：2026-10-25。仅限用户提供的同场训练赛两个本地回放；未改原始回放或安装目录。客户端为 Steam 11.21.0.1235，EXE SHA-256 `5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608`。

## 当前结果

用户已确认：双方 14 辆参赛车辆持续可见并正常移动，没有额外虚拟车；第二版修复红方持续卡顿；中央敌人方向箭头、右侧弹药和消耗品栏均隐藏，赛事血量及头顶标记正常。

当前实验文件为 `output/dual-replay-trial-20261025/tick-v2/dual-team-observer-tick-v2.wotbreplay`，SHA-256 `8381de0f2474ed79804aeae31e11f0d24a39df42f8d7204213874fe36f8056df`。界面抑制及虚拟车隐藏属于当前场景的一次原生操作，重新加载或重建场景后需要重新应用。尚未接入正式工作站。

## 原始材料与合并范围

- A：Arknihht_怀黍离·黍 / Kranvagn，team 2，实体 13073154；SHA-256 `09becd67a9c7525069a6d0f718e6157d374bc459ea5a567b689fe9cd4f557924`。
- B：东京の雨恋粉樱时 / Maus，team 1，实体 13073165；SHA-256 `b13fad2ef39bf89c547e288e3e44a8d8cbfab1fa8e8a642b8d3a9b6d0faf1ba6`。
- 同一 arenaUniqueId `12217899554750596`，Normandy，地图 42；名单 16 项相同，包括 14 个参战者和两个原有 observerMode 1 观战者。两个真实观战者均保留。
- 以较长的 A 为基础，B 提供其 7 个本阵营参战者的实体记录，类型为 4/5/7/8/10/33。B 提前结束后的尾部继续使用 A；尾部仍存活的两辆红方车辆在 A 中都有连续记录。
- 只融合上述实体记录，不宣称合并了完整全场炮弹、曳光或其他全局效果；也不代表服务器录像。
- 追加 ReplayCamera 身份（实体 `0x70000001`、observerMode 2），实体化后仅隐藏模型。保留原始 16 名单项，实际参战者状态不因观战身份而被修改。

## 第一版卡顿原因与第二版修复

第一版按 390 个共同战场事件估计 B 到 A 的到达时间偏移，中位数约 -0.014389 秒，95% 残差约 0.01596 秒。它解决了敌方灭点消失，但用户进一步发现红方整段持续卡顿。

两个文件同时包含 Type 36 的共同初始计数 `620952` 和 Type 35 的连续单字节周期计数。周期计数按模 256 展开，两份数据覆盖的相同周期可以精确配对。运动包属于其前面的周期记录；将另一份文件的位置包仅按浮点到达时间插入，会让它们跨过 A 的周期边界。

独立审计第一版的全部 17,336 个导入运动包，8,551 个被分配到与 B 原文件不同的周期，主要落后一个周期。两个连续运动包可能因此被交给同一个周期。这是已确认的数据问题；客户端平滑内部的全部实现并未逐层逆向。

第二版 `make_dual_tick_trial.py` 将 B 的目标实体记录依原顺序放在 A 对应 Type 35 后，并使用该 A 周期的记录时刻。保留所有导入业务载荷，包括坐标字节；不增加插值位置、不改变采样数量。A 非替换记录的顺序、时刻、载荷全部不变。

第二版末个 B 周期为 `623541`，对应 A raw `258.90704345703125`。移除 A 14,222 个目标记录、导入 B 32,339 个记录。普通合并副本 118,558 条记录；再添加两个虚拟观战者实体记录。第二版普通合并 SHA-256 `2e681b23158ffef93a7304da2b860822fa9f7bc88e27bda401c029646306eb69`。

`verify_dual_tick_trial.py` 独立读取归档和来源索引，确认：所有导入记录周期归属均与 B 一致（错误数 0）；业务载荷全部保留；A 的非替换记录流完全相同；原始元数据、结算、终止记录保留；添加虚拟观战者不改变参战者实体记录。WASM 解码仍为 14 名参战者，全部存活区间有位置覆盖，尾部接续间隔及位移通过约束。原文件哈希未变。

用户在第二版中实际播放后确认“红方移动已顺畅，现已暂停”。第一版不应继续作为平滑播放的验收通过版本。

## 个人界面反复出现：原因与 v4 抑制

第一版开始时已经隐藏个人 UI 根控件，但播放后游戏会重新设置 `/HUDLayer/Ammo` 和 `/HUDLayer/ConsumablesPanel` 的可见性。中央红色方向提示来自 7 个独立的 `/BattleUILayer/EnemyMarker`，与 `SpectatorBothVehicleMarker` 赛事头顶标记不同。一次 SetVisibility 无法保持这些控件隐藏。

v4 在上述 9 个控件上使用原生 `DAVA::UIOpacityComponent`，设置 opacity 为 0。新建前检查原组件是否存在并保存原值；这次 9 个根控件都没有该组件。Native GetOrCreateComponent 将组件交由原 UI 控件管理，不删除控件、不重设阵营、不修改赛事标记，也不保留持续 Hook。

精确构建证据（preferred VA）：

- `0xCE2D60`：UIControl 按类型 GetOrCreateComponent；参数为类型指针和组件序号 0。
- `0x4695104`：UIOpacityComponent 类型指针；`0x4696D94` 为注册索引，实测为 2。
- `0x3781EE4`：UIOpacityComponent 虚表；`+8` 为所属 UIControl，`+0x14` 为 opacity。
- `0x102AB30`：原生 SetOpacity(float)，将数值限制到 0..1 后设置字段。
- 原游戏调用 `0x1BCDD6A`、`0x1D9655E` 等按同样顺序 GetOrCreateComponent → SetOpacity，可核对 ABI。
- UIControl `+0xF0 → +0x24` 为组件索引表，`+0xE4/+0xE8` 为每种组件的指针容器表，用于只读验证；实际创建和设置均通过原生方法执行。

研究组件 v4 Magic `0x34485542`，Config 9188 / Header 60 / Shared 9248 字节，Python 与原生布局一致。33 项本地验证通过，包含空操作不创建、原生组件创建、可见位变化不改透明度、失效父节点拒绝、非有限值拒绝、恢复原透明度和表长度拒绝。恢复会恢复显示值；本次新增的透明度组件会留在原控件上并随场景释放，不声称撤销为完全相同的组件树。

实机报告（均在 tick-v2 目录）：

- `024623979033-show/report.json`：v3 恢复赛事 HUD、隐藏虚拟车，13 次调用，用户随后确认第二版移动顺畅。
- `025200639812-probe/report.json`：v4 空操作通过，0 次显示/透明度调用，未创建组件。
- `025255553940-show/report.json`：v4 应用成功，9 次透明度调用加 2 次个人栏重新隐藏，11 次请求；主线程 106132，状态 4，错误 0，active/queued 均 0，临时回调已恢复；暂停时钟和自由镜头不变。

用户继续播放并移动镜头后确认“三项都已隐藏，赛事界面正常”。这验证当前场景中的持续效果，尚未覆盖任意回放、重载、跳转、所有镜头切换或不可见控件的输入行为。

随后 `tick-v2/opacity-followup.json` 在播放时刻约 118.59 秒的只读检查确认：9 个目标组件透明度均仍为 0，尽管其中多数箭头以及两个右侧栏的 visible 位已经被游戏重新置为 true。这与用户画面验证一致，说明本次隐藏能经受播放中的可见性刷新。

## 重现

打开第二版，切自由镜头并暂停后：

```powershell
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action probe --clean --hide-ghost --suppress-personal --manifest output/dual-replay-trial-20261025/tick-v2/observer-manifest.json --url http://127.0.0.1:58123
python -X utf8 -B research/scripts/run_observer_visibility_trial.py --action show --clean --hide-ghost --suppress-personal --manifest output/dual-replay-trial-20261025/tick-v2/observer-manifest.json --url http://127.0.0.1:58123
```

恢复时传 `--action restore --restore-report <本次 show/report.json>`、同一 manifest 和服务地址。对象或场景改变时拒绝恢复旧地址。合并/校验入口为 `make_dual_tick_trial.py`、`make_dual_observer_trial.py`、`decode_dual_replay.mjs`、`verify_dual_tick_trial.py`。
