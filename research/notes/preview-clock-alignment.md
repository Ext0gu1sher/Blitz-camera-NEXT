# 预览与实机时钟对齐（2026-10-22）

用户提供 app.mp4 与 game.mp4，指定水塔镜头为工作区入点。实机录像约 64 秒处仍是靠近入点的过渡，约 65–65.5 秒抵达水塔构图。按水塔及后续构图对照，旧预览里的车辆明显晚于实机，镜头本身按保存的绝对时间求值。

## 原因与证据

11.21 客户端的 ReplayPlayer getter 返回 raw_time - origin；编辑器捕获时间及游戏内运镜均用此时间。离线 Agent 的车辆位置、覆盖区间和可见区间则使用原始包时间。旧 createReplaySampler 直接以编辑器时间查询这些数据，漏加了原点。

此项目绑定的 Maus / Canal 回放中，data.wotreplay 偏移 32095 的首个 0x11 类型记录的 clock 为 4.18244743347168。客户端初始化将首个此类记录的 clock 写入 origin；对应静态证据见 [回放时钟边界](replay-clock-boundaries.md)。原始分帧与已固定的 Agent 提交 8dcec2c6463f23116871157ef6d64985875efd67 中 crates/replay-core/src/replay/packets.rs 一致。

本机已有实机运镜报告 output/playback-runs/20261022T015515605164Z/report.json 同时记录：

    editor/native replay time = 38.26643180847168
    raw_time                 = 42.44887924194336
    origin                   =  4.18244743347168

差值与文件中的记录完全一致。该报告末次拍摄时间与回放推进量相差约 0.000018 秒，没有持续累积出数秒的速度误差。这份文件的战斗阶段 3 起点为 raw 33.038406，它是另一个时钟边界，不用于此次转换。

## 修复

blitzcam/replay_clock.py 按记录边界读取首个 0x11 的 clock，只读 ZIP、头部和记录长度，不解释 payload，不扫描 payload 中的伪标记。缺失、截断、重复 ZIP 数据入口、无效原点或超出客户端长度上限时明确报错，不猜测零原点。

预览来源携带 replay_origin_sec。车辆采样统一使用：

    vehicle_raw_time = editor_time + replay_origin_sec + manual_residual_offset

同一换算用于实体切换、覆盖区间、可见区间和位置姿态查询。摄像机求值、工作区、速度曲线和保存的关键帧仍用原编辑器时间。诊断包含 editor time、origin 和 raw time。手动显示偏移改用新的 localStorage 键，避免旧版本为缺失原点设置的补偿被重复叠加，入口文案改为“微调”。未修改四个现有区间图标。

另外两份真实回放的原点分别为 15.758445739746094（Plant）及 1.8336540460586548（Faust），因此不采用固定 5 秒补偿。

## 验证

- 277 项离线测试通过，包含原点读取边界、错误输入、四种原点、客户端时间到车辆原始时间的转换以及摄像机时间不变。
- Canal 和 Plant 的浏览器完整离线场景验收通过；确认自动换算、正反向拖动一致、速度曲线联动及摄像机与后端求值一致，无游戏 API 请求。
- 将用户当前项目只读复制到隔离服务，用水塔入点、移动中和后续两机位生成修复前后截图，已查看水塔构图及车辆到达位置；原项目文件逐字节保持一致。旧手动补偿不会重新叠加。
- 验收结果：output/archive/2026-10-27/verification/replay-preview-091-acceptance/result.json；当前项目诊断及截图：output/archive/2026-10-27/research/timing-investigation/corrected-readings.json、corrected-*.png、previous-*.png。

本轮未启动、操作或重录游戏；实机比较依据用户提供的录像及已有运镜报告。修复消除了已确认的固定时钟偏差，不宣称车辆插值、悬挂或最终渲染达到逐帧复刻。更新后需重启工作台及本地服务，重新载入预览。
