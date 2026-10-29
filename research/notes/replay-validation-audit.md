# 回放核验逻辑清单

核对日期：2026-10-27。对应测试修订 `1.0.1-beta.1` 的源码及成品；此前已发出的测试包保持原样。

## 本轮删除与修复

- 删除应用中读取进程启动参数的 `launch_arguments`，以及从参数提取回放的 `replay_path_from_arguments`、`launch_replay_path`。
- 删除 `session_timeline` 的启动参数回退分支；当前回放只从游戏内 `ReplayPlayer` 持有的文件读取。
- 地图识别辅助代码也改用当前回放文件，不再读取启动参数。
- 删除把来源降级标记为 `launch_argument` / `launch_arguments` 的应用逻辑。仅选择文件或发出打开请求，不会直接获得“已核验当前回放”状态。
- 修复宿主与加密组件的 `BuildProfile` 类型不相同导致能力误判的问题，改为检查所选适配布局是否提供当前回放读取能力。

本次根因已在加密安装测试中复现：组件内的配置类位于独立命名空间，原 `isinstance(profile, BuildProfile)` 判定失败，导致已经支持的 11.21 也进入旧回退。修复后使用原交付版运行环境、原 r2 组件及离线对象样本，宿主能正常识别当前回放。

“在游戏中打开回放”仍会把所选文件传给游戏，这是启动操作；程序不再反过来读取这些参数作为当前回放的证据。历史研究诊断脚本与其独立测试仍保留启动信息观察功能，位于 `research/`，不参与应用运行和打包；旧包及历史报告也未改写。

## 文件与身份核验

| 编号 | 核验内容 | 触发位置与失败行为 | 代码位置 |
| --- | --- | --- | --- |
| R01 | 所选文件必须存在、扩展名为 `.wotbreplay`，ZIP 可读，恰有一份未加密的 `meta.json`，元数据不超过 64 KiB，JSON 可解析 | 选择、关联、启动、读取当前回放时失败则报错 | `blitzcam/replay_timeline.py:file_timeline` |
| R02 | `battleDuration` 必须是有限数字且 `0 < 时长 ≤ 3600`；比赛开始事件不得超出该长度 | 无有效全片时长则文件读取失败；事件超界则标记赛前长度不可用 | `blitzcam/replay_timeline.py:file_timeline` |
| R03 | 游戏当前文件的持有对象类型、引用计数、文件指针、`ReplayFile` 类型及其与播放器的引用必须一致；支持两种已验证的持有方式 | 关联及播放前读取失败时，当前文件不可确认；相机连接可能继续保留 | `blitzcam/replay_source.py:_owner_type,runtime_replay_source` |
| R04 | 当前文件路径必须是绝对路径、扩展名正确、无控制字符；字符串长度、容量、地址、终止符与前后读取一致；内部回放标识为 32 位十六进制且两个对象一致 | 不满足则拒绝本次文件读取，不猜测其他文件 | `blitzcam/replay_source.py:_string,runtime_replay_source` |
| R05 | 读取文件前后重新核对对象；磁盘文件版本须与游戏内回放版本或客户端标记之一对应，允许已适配的跨区版本差异 | 读取途中切换、文件版本变化时报错，不使用旧结果 | `blitzcam/replay_timeline.py:session_timeline` |
| R06 | 项目与当前文件优先比较完整文件 SHA-256；改名、复制、路径改变但内容相同可通过 | 游戏内随对局播放、准备和跳转前，不同内容被拦截 | `blitzcam/replay_timeline.py:replay_matches`；`server.py:play`；`replay_preparation.py`；`replay_seek.py` |
| R07 | 旧项目没有已存哈希时尝试读取原文件计算；原文件无法读取且无已存哈希时，函数仍保留规范路径相等的兼容比较 | 这是仍存在的旧项目兼容规则，与已删除的启动参数核验不同 | `blitzcam/replay_timeline.py:replay_matches` |
| R08 | 跨电脑打开项目回放：原路径失效时，只自动采用项目旁内容哈希相符的同名文件，否则让用户选择；有已知身份时选择结果必须同内容 | 防止把同名但不同场次的文件绑定到原项目；完全无旧身份的旧项目允许手动补绑定 | `blitzcam/server.py:open_project_replay,open_replay` |
| R09 | 本工具发出打开请求后，比较实际连接的客户端安装路径与请求路径，并用运行时文件内容核对请求；不要求 Steam 转交前后的 PID 相同 | 未确认当前文件时不标记成功；若运行时已明确识别用户手动切换的另一份回放，连接保留并清理旧请求，但原项目播放仍受 R06 限制 | `blitzcam/replay_launcher.py:verify_launch_source`；`server.py:connect` |
| R10 | 打开回放的客户端必须属于已安装的 Steam 国际版应用；路径及应用清单对应 | 只影响由工具启动游戏的入口；不符合时拒绝启动 | `blitzcam/replay_launcher.py:steam_client,locate_client,launch_replay` |

R03–R05 读取不可用时，现在直接报告运行时读取原因。未适配当前文件读取的旧构建不再自动尝试命令行识别。仅镜头模式仍可使用独立有效的相机连接；已绑定回放的随对局播放需要重新确认实际文件。

## 连接与回放状态核验

| 编号 | 核验内容 | 失败行为 | 代码位置 |
| --- | --- | --- | --- |
| R11 | 找到唯一游戏进程；游戏 EXE 精确 SHA-256、架构、映像大小、基址与适配一致；已打开的进程身份再次核对；Pro 组件支持的游戏哈希与会话一致 | 未适配或身份变化则拒绝连接，不按版本文字套用布局 | `blitzcam/memory.py:find_process,verify_binary,ProcessMemory`；`game_backend.py:GameBackend.connect` |
| R12 | 发现唯一有效回放相机对象链，播放器、场景、渲染、相机及控制器类型与互相引用一致；每次采样重新检查 | 对象变化或切场景则停止旧会话，要求重新连接；不把旧地址继续用于新回放 | `blitzcam/reader.py:CameraSession.discover,_guard` |
| R13 | 回放时钟已初始化，无正在进行的跳转、重建或待执行任务；时间与倍率有限，倍率在读取支持范围内 | 正在重建或数值无效时拒绝读取 | `blitzcam/reader.py:_clock` |
| R14 | 连续采样时间原点不变、时间不倒退，不出现超过倍率与经过时间允许值的不合理前跳；一次快照内暂停和倍率状态一致 | 原点或时序变化使旧会话失效；瞬间跨更新阶段则丢弃快照 | `blitzcam/reader.py:_clock_interval,capture` |
| R15 | 相机数值、朝向、投影和矩阵一致；记录要求暂停；播放接管前还检查按键释放、缩放与动画稳定、场景/会话一致 | 拒绝记录或接管，不是“回放文件不一致”判断 | `blitzcam/reader.py:_camera,_native_controller,capture`；`hook_guards.py:validate_snapshot,controller_extra,same_scene` |
| R16 | 关联任务、回放选择与启动任务必须仍属于当前项目、项目修订和连接代次；播放/准备未停止时不允许重入 | 取消过期结果，避免切项目后旧结果覆盖新状态；重复任务被拦截 | `blitzcam/server.py:connect,open_replay,_switch_to,play`；`playback.py:PositionPlayback` |

## 时间区间与播放条件

| 编号 | 核验内容 | 失败行为 | 代码位置 |
| --- | --- | --- | --- |
| R17 | 项目回放时间轴必须为对局绝对时间；长度与入出点为 0–3600 秒有限数，满足 `0 ≤ 入点 < 出点 ≤ 全片长度`；已存路径、哈希和事件字段格式合法 | 拒绝载入或保存无效时间轴 | `blitzcam/replay_timeline.py:validate_timeline` |
| R18 | 赛前边界来自已适配的比赛开始事件，或用户手动设置；新增/移动关键帧、修改入点、游戏播放入点不得早于比赛开始 | 未识别事件时要求手动设置；保留旧关键帧，不因此删除项目数据；仅镜头模式不执行新增关键帧赛前限制 | `blitzcam/replay_events.py`；`replay_timeline.py:replay_keyframe_guard,validate_new_keyframes,validate_work_start`；`server.py:_keyframe_metadata` |
| R19 | 单次回放工作区间 0.5–120 秒；联动续播当前时间应在区间内（入点容差 0.05 秒），剩余不足 0.5 秒拒绝；联动战斗不能倒放 | 入点前可进入准备流程；到达出点需重新定位；不按绝对时间是否超过 120 秒判断 | `blitzcam/replay_timeline.py:playback_window` |
| R20 | 固定/曲线倍率 1/16×–1×；曲线 2–64 点，进度递增、覆盖 0%–100%，时间范围和手柄合法；实际执行时长 0.5–1920 秒 | 说明实际拍摄时长和原因后拒绝；区间外沿用端点速度，不自动重写曲线 | `blitzcam/speed.py:validate_speed,playback_timing,validate_shooting_duration` |
| R21 | 原有“固定镜头仅变速”入口的 `seconds` 参数仍单独限制 0.5–120 秒；路径编译还要求足够关键帧、合法采样容量与轨迹边界 | 拒绝该操作。此处 120 秒限制仍存在，不能概括为全部入口已放宽到 1920 秒 | `blitzcam/server.py:play(speed_only=True)`；`playback.py:compile_positions,validate_channels,check_positions` |
| R22 | 入点准备重新连接后再次核对项目文件，等待有效暂停状态；不自动倒回已越过的时间；等待有超时和取消条件 | 等待回放稳定，或终止准备；错误文件不会继续接管 | `blitzcam/replay_preparation.py:prepare_replay` |
| R23 | 跳转前再次匹配文件和精确构建，要求暂停；核对跳转只执行一次、主线程记录、落点误差 ≤0.12 秒；重连后播放器身份与时间一致 | 停止错误或超时跳转，不重复提交；执行后必须确认组件撤出 | `blitzcam/replay_seek.py:seek_replay,native_seek`；`seek_phase_trial.py:prepare` |
| R24 | 原生播放/跳转组件的 DLL 哈希、路径、ABI、目标入口、当前对象与时钟配置匹配；运行中检查心跳、入口与播放状态，结束检查倍率恢复和 Hook 撤出 | 拒绝安装、停止执行或报告恢复未确认。原生端也有曲线容量、倍率、时长检查，不能只改界面限制 | `blitzcam/playback.py:_run`；`replay_seek.py:native_seek`；`native/position_replay_clock.h`；`native/replay_seek_phase_guards_1121.h` |

## 离线预览与地图

| 编号 | 核验内容 | 失败行为 | 代码位置 |
| --- | --- | --- | --- |
| R25 | 预览文件 ≤64 MiB，ZIP 展开总量 ≤256 MiB；`data.wotreplay` 唯一、未加密且长度有界；记录魔数、分段和时间原点合法 | 停止加载预览或自动时钟对齐，不代表游戏当前文件与项目不一致 | `blitzcam/replay_preview.py:replay_metadata`；`replay_clock.py:replay_data,replay_records,origin_from_data` |
| R26 | 预览文件请求属于当前选择，读取内容哈希与选择时一致；场景资源属于当前预览，后台生成代次未过期；地图和车辆编号、数量合法 | 丢弃旧请求或要求重新载入，防止跨项目混用文件与资源 | `blitzcam/replay_preview.py:replay_bytes,asset_path,prepare,_publish` |
| R27 | 解析器指纹匹配固定版本；运动数据样本 1–36001、车辆 ≤64，位置/角度数组长度与有限数合法；覆盖区间、重建关键点及时间递增；实体身份和战斗时钟可建立 | 报告解析/预览数据错误，停止该预览；不检查游戏进程启动参数 | `blitzcam/web/replay-preview-worker.js`；`replay-preview-core.js:validatePlayback,createReplaySampler` |
| R28 | 地图辅助解析核对地图名/编号、场景资源路径与实体名称、地图目录唯一匹配；元数据与场景不同时以场景为准 | 只影响选图结果；当前代码搜索未发现工作台调用 `ReplayMapResolver`，列出以免把保留的辅助代码漏算 | `blitzcam/replay_map.py:replay_metadata,scene_resource,match_map,ReplayMapResolver` |

以上覆盖应用自身的回放文件、身份、连接、编辑、播放、跳转和预览核验入口，并归纳原生组件的对应保护。依赖解析器内部还可能返回其自身的文件格式解析错误；未逐条展开第三方解析器内部断言。升级包签名、设备密钥与授权校验是独立的组件部署机制，不属于判断两份回放是否相同的规则。

## 本轮验证

- 加密组件回放识别回归在修改前确实失败，进入已退役的参数读取分支；修改后通过。
- 相关回放测试 173 项通过；加密部署测试 21 项通过。
- 全量测试执行 635 项：634 项通过、1 项跳过；随后新增的地图来源测试 2 项单独通过，覆盖正常读取与读取途中切换。全量记录：`output/archive/2026-10-27/logs/replay-validation-removal-full-tests.log`。
- 原交付运行环境 + 原 r2 母包按临时设备加密安装，隔离覆盖 Cinema / Spectator 两类控制器及两种文件持有方式；四种组合全部通过当前文件识别、错误文件拒绝、文件持有关系改变拒绝。仅在副本覆盖四个修改后的宿主模块，没有改动原交付包。
- 成品边界报告：`output/packaged-replay-source-acceptance/run-8ip7c06o/result.json`。此验证使用归档对象数据，不操作真实游戏。
- 交付前最终回归 637 项：636 项通过、1 项跳过。最终成品不覆盖源码，通过同样四种加密组件组合；报告：`output/packaged-replay-source-acceptance/run-dcvv6w51/result.json`。
- 从 `1.0.0-beta` 和 `1.0.1-beta` 到本修订的签名增量升级、自动重启及用户数据保留通过；成品桌面与悬浮窗验收通过。汇总：`output/updates/BlitzCamera-1.0.1-beta.1-verification.json`。未进行新的笔记本游戏现场测试。

后续只要调整回放读取、适配加载或打包方式，就应继续运行真实加密组件与宿主交界的识别测试，不能仅用“组件可导入”作为回放关联已通过的证据。
