# 车辆重建时序修复及上游核对（2026-10-23）

用户在 0.9.4 便携版载入 FVE Defender / Faust 回放时遇到“车辆重建关键点不完整”。以包内固定的 Agent v0.4.9 解析器复现：14 辆车的基础采样及重建数组均完整，其中 eid 6883668 / tank_id 20849 的 `pose_kf.t` 在下标 1788 从 241.8524 倒退至 241.6651（原始包时钟秒）。回放 SHA-256 为 d8acca7cd1ad4de5999ae8ac3c9e1a7e27c1b6303e076be28c8df1bf5b8eccf8。旧校验将时间倒序与数组缺失合为同一错误，并中断整场载入。

## 上游实现与更新

我们此前固定引用 WotbTools `11d0d519aba2afedcae3d49365b0bfd1a4b5c76d`，浏览器解析器仍为 Agent v0.4.9 / `8dcec2c6463f23116871157ef6d64985875efd67`。在线核对 WotbTools 主分支 `f55952931854de8cf95c9d4d41de152ff75c0d2d`：

- [vehiclePose.ts](https://github.com/A158Coke/WotbTools/blob/f55952931854de8cf95c9d4d41de152ff75c0d2d/frontend/src/replay-local/pose/vehiclePose.ts) 与本地参考副本逐字一致（规范化换行后的 Git blob `750d398af8097302b1b3f56859b33fa3509dac18`）。
- [trackInterp.js](https://github.com/A158Coke/WotbTools/blob/f55952931854de8cf95c9d4d41de152ff75c0d2d/frontend/src/scene/trackInterp.js) 同样一致（blob `6f453e04f3a1556d579f3097a5a243657da0e498`）。该实现对关键点时间作升序二分，升序由解析器保证。
- [deploy/agent/source.json](https://github.com/A158Coke/WotbTools/blob/f55952931854de8cf95c9d4d41de152ff75c0d2d/deploy/agent/source.json) 已固定至 `fanypcd/WoT-Blitz-Agent` v0.4.11 / `0a9da93a0074a95af406db3468e6a81a5a6b139f`，发布 ZIP SHA-256 为 `8170ba26b289e1952ed04d92f572a596a0503c988b86316c008b57a3fbec96f6`。旧 A158Coke 名下的 Agent 仓库不是当前 pin 的来源。

解析器已在 [上游 PR #25](https://github.com/fanypcd/WoT-Blitz-Agent/pull/25) 修正同一根因：[pose_keyframes](https://github.com/fanypcd/WoT-Blitz-Agent/blob/0a9da93a0074a95af406db3468e6a81a5a6b139f/crates/replay-core/src/replay/playback.rs) 原先逐段消费滤波时间线自带的 +0.5 秒外推尾部。短暂离开视野时，前段尾部越过下一段起点，全局拼接后时间倒序。新实现按每段权威 `t_out` 截断；同时显示重建使用独立的 Display 初始化，段首采用稳态 0.2 秒延迟，判定层保持原客户端语义。v0.4.11 包含此项修复，并增加车辆身份、射击匹配及配件解析修正。

## 最终修复

将浏览器 WASM、JS 胶水和 fingerprint 一起升级至 WotbTools 当前固定的 v0.4.11，下载后按其公布的 ZIP 哈希校验。Worker 同步核验精确 tag/commit，并将引擎来源带入场景诊断。最终交付使用修复后的平滑曲线，严格拒绝倒序/重复、缺列或非有限值；时间顺序异常采用独立且准确的报错。

资产导出器及模型元数据仍来自原固定 v0.4.9，许可证和 provenance 将浏览器引擎与资源导出来源分别记录。此次不扩展游戏控制构建范围，不改回放文件、镜头关键帧或两种时钟。

## 验证

`tests/fixtures/replay_pose_validation.mjs` 覆盖平滑曲线与旧网格的正确求值、倒序/重复时间拒绝、隐藏与覆盖门禁、输入不变以及缺列/非有限值拒绝。`tools/verify_replay_pose.mjs` 使用实际 WASM 解析项目绑定回放，遍历整个基础时间网格并反向查询，要求所有车辆保留升序平滑曲线，检查有限位姿及输入不变；支持指定源码/便携版 `--web-root` 和隔离候选引擎 `--engine-root`。

候选 v0.4.11 实测：FVE / Faust 14 辆车全部保留有效平滑曲线，3,479 个采样时刻、44,470 个车辆帧通过有限值及前后拖动一致性检查；Maus / Canal 14 辆车同样通过（2,572 时刻、26,745 车辆帧）。本轮离线相关测试 51 项通过。原生桌面完整场景验收使用隔离的便携副本，无游戏连接或 Hook 执行；报告见 `output/archive/2026-10-27/verification/desktop-094-acceptance/result.json`。
