# 离线预览炮管姿态修复

2026-10-24，源码修改；已纳入 0.9.4.1 便携包。

## 原因与实现

预览 Worker 原先只调用 `parsePlayback(bytes)`，没有传入第三个参数 `limits`。Agent 在缺少车型俯仰锚定时，将 `hull_pitch` 填入 `gun_pitch`；于是炮管跟着车体倾斜，独立瞄准的抬炮、压炮没有还原。

参照本地 WotbTools 的 `frontend/src/scene/replaySource.js` 与 `pitchLimits.js`，改为先解析名册、获取俯仰范围、带参数重新解析。参数直接从已固定版本的 `models.pb` 读取，按回放 `turret_local` / `gun_local` 匹配实际装配，保留前后扇区以及过渡角。只存在一个配置时允许缺少装配编号；多配置而编号缺失或不匹配时不猜测，预览提示缺少参数。旧模型缓存无需重建。

角度单位和符号遵循固定版本 Agent 的 [pitch.rs](https://github.com/fanypcd/WoT-Blitz-Agent/blob/0a9da93a0074a95af406db3468e6a81a5a6b139f/crates/replay-core/src/replay/combat/pitch.rs)：`dep=max`，`ele=-min`，输入为度；输出 `gun_pitch` 为弧度、正值抬炮。

炮塔水平角、炮管旋转轴和初始模型姿态补偿与 WotbTools `poseGlbRig` 一致，本次没有改动这些符号或强行将炮口对齐弹道。通过明确方向用例及实际模型世界方向核对组合结果，避免用修改符号掩盖解析数据错误。

## 验证

- `python -m unittest tests.test_replay_preview tests.test_server`：29 项通过，包括装配选择、前后扇区、过渡角、中文昵称、旧回放缺少装配编号，以及 7 组车体倾斜 / 炮塔横转 / 炮管俯仰组合和反复跳转。
- `python -m tools.verify_replay_aim --project <项目.json>`：使用项目副本及隔离服务，调用实际 Worker、WASM、HTTP 参数接口、模型缓存及浏览器渲染。对比原先无锚定解析，检查所有车辆俯仰数据发生变化、最终炮口方向与解析姿态一致，前后拖动不累积旋转。
- 本地 Kranvagn、Maus、FVE Defender 三份回放共 35 条车辆记录；验证结果与修复前后同视角截图存放于 `output/replay-aim-acceptance/`。这些输出含本地回放数据，不进入版本库。

验证没有连接或启动游戏，没有改写原项目、回放或发布包。此验证覆盖离线解析与实际渲染；未将画面与游戏内同一时刻逐帧叠图比对。
