# 11.21 回到 35 秒后的闪退

2026-10-19，本机同一 Steam 11.21.0.1235 构建。结论：**回跳尚未修复。改用原生主线程任务队列后，前两次回跳短期稳定，第三次仍在重建清理中崩溃；两条 seek 试验入口均已停用。** 最早异常已捕获，根因仍未确认。不再将时钟稳定视为场景生命周期稳定。下文先保留原始事件，新增调查见“后续定位与重复验证”。

用户明确要求回到 35 秒并保持暂停。操作前只读确认当前暂停在 `100.69889545440674` 秒；本轮将试验工具的位移时间上限从初始 5 秒扩大，最终为 120 秒。C/Python 布局不变，本地 8 组 x86 假对象测试及 5 项 Python 定向测试通过；这些测试没有覆盖真实客户端的大跨度场景重建，因此不足以证明此次操作稳定。

实际单次请求 delta 为 `-65.69889831542969`，请求 DLL 为 `replay_seek_trial_1121.43fae9ec8448.dll`，SHA-256 `43fae9ec8448da2f251de58ff8e3a0b1d6528d8fd222c9964bc4f91bdbfffe14`。没有修改游戏文件、相机位姿或直接写 raw。

## 时间顺序与证据

所有运行记录在 `output/replay-seek-runs/20261019T150502309281Z/`：

- 请求后约 1.063 秒，观察到显示时间 `35.09989643096924`、paused=1、rate=1、initialized/active=1，seek/waiting=0，任务 token=-1。实验 Header status=4、active=0、detached=1，requests=1。
- 这只证明请求返回和播放器字段短时稳定。相机完整对象链未重连成功；记录泵和原生事件完成不构成全场景有效性的证明。
- 游戏日志 UTC 15:05:05 记载战斗 LEAVE/WAIT、重新成为玩家、场景 UNLOAD/UNLOADED/LoadGameScene；15:05:06 有粒子脚本无效参数、UI 包加载异常以及纹理信息。日志不单独证明这些警告就是根因。
- 游戏自身 Sentry 转储 UTC 15:05:06.824 已记录异常。此前报告仍以短时落点作为完成依据，因此成功判定错误。
- Windows Application Error 在本地 23:05:07.170、23:05:12.636 记录同一 PID 62220 的 `0xc0000005`，模块 RVA `0x006bb0ab`。随后两份 WER dump 分别写完于 UTC 15:05:12.293、15:05:18.241。

## 离线转储检查

只读取磁盘转储，无调试附加、无自动重启，无新运行时写入。解析工具为 `research/scripts/inspect_seek_crash_dump.py`。该工具解析 x86 MINIDUMP_EXCEPTION_STREAM / CONTEXT、模块和内存流，沿 EBP 链读取返回地址；不具备符号化或可靠 FPO 展开，额外栈扫描明确标记为候选地址。

原始文件：

```text
C:\Users\Ext1nguisher\AppData\Local\CrashDumps\wotblitz.exe.62220.dmp
C:\Users\Ext1nguisher\AppData\Local\CrashDumps\wotblitz.exe(1).62220.dmp
C:\Users\Ext1nguisher\AppData\Local\wotblitz\DAVAProject\sentrydb\42a464ca-8905-4b54-ab96-bf488e76d165.run\4d9b1e49-6b06-41b0-b34b-05d8baaac3f5.dmp
C:\Users\Ext1nguisher\AppData\Local\wotblitz\DAVAProject\blitz-logs_20261019214811.txt
```

分析结果为该运行目录的 `crash-dump-analysis.json`、`crash-dump-analysis-2.json`、`sentry-crash-analysis.json`。

- WER：线程 21792（本轮原生请求同一主线程），EIP `0x0089b0ab`，游戏基址 `0x001e0000`，首选 VA `0x00abb0ab`；指令 `mov edi,[ebx+0x98]`，EBX/ECX=0，读地址 `0x98`。调用者经过 `0x00ac32c0` 析构样式路径，而该函数先通过 `0x00ab2830` 取得指针，再调用崩溃函数。
- 更早的 Sentry：同线程，`ntdll.dll+0x65995`，写地址 `0x14`，EBP 返回链经过 `0x00900a85 → 0x00af104f → 0x00c75bd4 → 0x00aa9d07 → 0x00aa935e`。`0x00aa9c40` 为逐项清理成员、虚析构并释放对象的路径；Sentry 也已在这段清理过程中。
- 两类异常均不能直接解释**为什么先进入清理**。当前 EBP 链没有指向自建 seek DLL，但这不能排除该调用对生命周期或状态造成的间接影响。
- 日志没有足够证据支持“只是网络问题”“原生游戏老毛病”“已经修复”等说法。

静态对应：`research/builds/11.21.0.1235/replay-seek-crash-site-20.txt`、`replay-seek-crash-callers-21.txt`、`replay-seek-crash-cleanup-22.txt`。首选 VA 来自该构建磁盘 EXE；模块地址按实际基址重定位。

## 已采取的处理与下一步

`tools/verify_replay_seek.py` 在执行任何服务/游戏访问之前拒绝 `--execute`；只读检查保留。不自动重开、不再提交跳转。现有轨迹/速度 UI 未增加跳转按钮，保存的四机位项目未改写。

下一步先离线追查原生 UI 提交时机、重建任务及引擎退出清理之间的关系，检查直接从 Replay tick 内重入重建的合法性、场景/控制器事件及异步对象寿命。只有提出具体修复后，才在新开的回放中安排一次独立验证，覆盖落点后的持续渲染、暂停/恢复、自由镜头切换及退出回放；短时读到目标秒数不再单独算通过。

## 后续定位与重复验证（2026-10-19 UTC 15:05–15:32）

### 构建与证据边界

本节全部地址是本机 Steam `11.21.0.1235` 的首选 VA，不是通用地址，也不能直接当作下一次运行的绝对地址使用：

```text
EXE: C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\wotblitz.exe
SHA-256: 5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608
本次 PID: 56148，主线程: 47148，实际 EXE 基址: 0x001e0000
```

用户已授权继续运行验证。这一轮并非只读：加载了工作区内自行编译的独立研究 DLL，临时替换已确认的 Replay tick 回调方法槽以安排一次任务，在任务入队前恢复原方法槽；只请求原生 seek，没有直接写回放时钟、相机、UI 组件或材质。未修改游戏文件，未接入生产 UI。异常观察器只记录首个 AV，然后返回 `EXCEPTION_CONTINUE_SEARCH`，不吞异常。

### 原始崩溃中更早的异常

原 WER 的所选异常位于退出清理，但其主线程捕获栈还保留了有效的 x86 `EXCEPTION_RECORD/CONTEXT` 相邻记录。新增只读扫描同时核验异常 IP、参数个数、CS/SS 与栈范围；这不是按时间排序的完整异常日志。

在 PID 62220 的保留记录中找到：

- 首选 VA `0x006ab2c7`，读取 `0x3a00c744`，EAX=`0x3a00c748`。对应大块 vector 分配释放辅助函数读取 `[pointer-4]`。
- 调用链包含 `0x00c9f72b → 0x00c9be95 → 0x00c7adc6`，落在 `DAVA::NMaterial` 子缓存清理及渲染路径，早于最终引擎退出异常。
- 被清理子块为 `0x16c53560`，其 `+0x1c` 向量指针/容量组合异常；外层材质为 `0x3b122878`，RTTI 支持 NMaterial 类型判断。
- 该地址恰与之前一个 ReplayCameraController 地址加 `0x68` 相同，只能作为堆复用线索；没有分配/释放时间线，不能据此断言相机对象覆盖了材质。

结果：`output/replay-seek-runs/20261019T150502309281Z/crash-retained-context-analysis.json`；分析器为 `research/scripts/inspect_seek_crash_dump.py`。因此此前只依据 WER 最终选中的退出清理异常定位是不完整的。

### 调用时机试验与结果

假设：原来直接从正在发射的 Replay tick 中调用 seek，可能重入当前回调的清理；改到原生主线程任务队列能否避免。

队列入口 `0x0091d090`，使用原生 `Function<void()>` 的 `0x28` 字节布局与内联 8 字节 functor，force=1 延后执行。seek 入口仍为 `0x013e5ea0`。执行时严格核验：当前仅原生任务队列泵自身的引擎回调正在发射，Replay 回调未发射；主线程与排队线程一致；暂停、回放、时钟和回调身份仍符合快照。

原生队列泵自己也处于引擎更新信号内，因此“所有回调都未发射”不是可用条件。已确认其 functor vft `0x0372ab00`、入口 `0x0092aec0`。另外，原生 functor 析构参数是 bool，只有低字节有效；研究实现已在实际 seek 前修正上位垃圾位的错误判定。所有实际 seek 都使用最终 SHA 对应 DLL。

研究 DLL：`blitzcam/native/replay_seek_phase_trial_1121.36b4fc664b8e.dll`，SHA-256 `36b4fc664b8e159407c5784230cc0fe40cc3a8ecaf7c52b4dd0aed8dde21e610`。10 项本地 x86 假对象测试通过，只覆盖 ABI、取消、守卫和首异常记录，不证明客户端重建稳定。

所有试验目录在 `output/replay-seek-phase-runs/`；表内目录前缀均为 `20261019T`。

| 目录后缀 | 请求 | 结果及观察窗 |
|---|---|---|
| `152641165842Z` | 队列 no-op，不调用 seek | 主线程执行一次、无 AV，时间不变，5 秒稳定 |
| `152708950360Z` | 11.2792425 → 10.2792425 秒 | 实到 10.3000383，15 秒内暂停稳定，重连新相机链 |
| `152836360068Z` | 前进至 100.7 秒 | 实到 100.7988939，15 秒内暂停稳定 |
| `152909612757Z` | 回到 35 秒 | 实到 35.0998964，20 秒内暂停稳定，重连新相机链 |
| `153029874429Z` | 前进至 100.6 秒 | 实到 100.69889545440674，精确复现旧失败起始时间，15 秒稳定 |
| `153128517789Z` | 再次回到 35 秒 | 约 0.078 秒捕获首个 AV，未到落点，游戏随后退出 |

成功回跳后游戏回到跟随镜头，使用游戏的镜头切换按钮再切自由镜头；它不等于自动保留原构图。场景 `0x34da0020` 和 RenderSystem `0x324f85d0` 在成功重建间保留，Context、控制器及相机对象被替换，故旧链不能继续使用。

暂停时做过只读材质缓存结构抽样检查，覆盖约 5261–5271 个 NMaterial、19640–20094 个子块，未发现结构性错误，双读相同。它不是原子堆快照，不验证分配所有权，也不能排除稍后清理时才暴露的悬空引用。样本在 `output/replay-seek-cache-*-1121.json`，脚本为 `research/scripts/audit_replay_render_cache_1121.py`。

原生 seek 泵按约 0.1 秒步长追赶；本次落点误差约 0.021–0.100 秒。不能把“指定 35 秒”写成已实现帧级精确跳转。

### 第三次回跳的首个异常与清理链

独立捕获：`output/replay-seek-phase-runs/20261019T153128517789Z/first-fault.bin`，3676 字节。可复现分析器为 `research/scripts/inspect_seek_first_fault.py`，产物 `first-fault-captured-only.json`。其中列出的关键 EBP 返回地址全部位于**首异常当时**保存的 2048 字节栈中，不需要借用后来的 WER 栈；只做 EBP 展开，不支持 FPO。

```text
异常：0xc0000005，写 0xfd99faf6
实际 EIP: 0x00adab78；首选 VA: 0x00cfab78
EAX: 0xfd99faee，EBX: 0x36f9b3b8，EDI: 0x3d03fa90，ESI: 0x3d001abc

原生任务泵 0x0092b033
  → AvatarControllerBase::ReloadScreenForRewind（返回地址 0x0176e289）
  → BattleResources 清理路径（返回地址 0x0177491c）
  → 0x01bbe6b0 清理其 +0x19c 容器中的 UI 引用（返回地址 0x01bbe755）
  → 多层 UIControl 子对象 Release / 析构
  → 0x00cfab30 清除组件；0x00cfab78 写 [component+8]=0 时异常
```

组件列表指针来自 UIControl `+0xe4/+0xe8`；从内层 vector 的 end-4 取出 `0xfd99faee`，再写其 `+8` 时失败。RTTI 支持这里是 `DAVA::UIControl` 清理。缓冲区在研究 DLL 中命名为 child/material，但它们实际上只是 ESI/EDI 原始窗口，不能用变量名推断本次对象类型。

此处 EDI 又恰为上一代 ReplayCameraController `0x3d03fa10 + 0x80`。与原始材质异常的复用迹象相似，但仍不足以确认同一内存破坏源，也不能排除研究调用造成间接影响。不能将它归咎于网络或认定为游戏自身问题。

### 场景缓存条件已追到的部分

磁盘 EXE 保留原始字符串：

```text
0x037f94ac AvatarControllerBase::ReloadScreenForRewind
0x037f9324 C:/ba/tc/work/t/client/Classes/Battle/AvatarControllerBase.cpp
0x037f94d8 resources->isSceneDataCached
0x037f94f8 Trying to make rewind cycle without caching scene data!
0x037fa9c8 gameScene->GetRetainCount() == 1 || (gameScene->GetRetainCount() == 2 && isSceneDataCached)
```

这些是客户端内嵌字符串，**不是已取得该版本源码**。源码路径来自构建机，不是本机路径。

- `ReloadScreenForRewind` 在 `0x0176e159` 取 `[this+0x154]`，检查其 `+0x90` 字节；为 0 时进入受日志级别控制的断言报告，随后仍继续清理。
- 清理入口 `0x017745a0` 在 `0x017748b9` 再判断资源对象 `+0x90`：非 0 才走包含 `0x01bbe6b0` 的 UI 清理分支；0 则调用另一完整清理分支 `0x01775130`。
- 因为本次实际崩溃栈经过非 0 分支，**不支持“只是没把缓存标志设为 1”的解释**。不要强写该标志或屏蔽析构作为修复。
- `0x01768960` 先执行 `0x01d625e0`、`0x01bc0640` 等原生准备，再把 `[this+0x150]->+0x90` 设为 1。其注册处 `0x01754e8b` 的 functor RTTI 明确为 `BattleController` 对 `GES::Avatar::RewindStarted` 的订阅；相邻订阅为 RewindFinished。这支持准备工作本来由原生事件负责，而不是随意添加一个开关。不同控制器对象的字段偏移不能混用。
- 非缓存分支会释放更多资源；缓存分支保留场景及若干系统，并在结尾检查场景引用计数为 1 或“缓存且为 2”。目前没有查清每个 UI 缓存/组件引用的创建、失效与释放顺序。

静态证据位于 `research/builds/11.21.0.1235/` 的 `replay-seek-*-23` 至 `replay-seek-*-46` 文件，尤其是 `scene-cache-41`、`cache-teardown-42`、`cache-strings-43`、`cache-writers-44`、`cache-callers-45`、`ui-cache-cycle-46`。

### 当前处置及下一轮具体条件

1. `tools/verify_replay_seek.py` 和 `tools/verify_replay_seek_phase.py` 均拒绝实际 seek；新入口在任何服务、进程、文件访问之前检查。新增两项测试验证拒绝发生在这些操作之前。队列 no-op 仍需显式 `--execute`，本次结束后未再运行。
2. 第三次异常后已停止运行测试，未自动重启游戏。生产轨迹/速度 UI 未加入回跳；保存的 `output/project.json` 未由研究流程改写。
3. 下一轮应先做**每代对象的生命周期记录**：在 RewindStarted 前后、旧 UI 清理前、RewindFinished 后记录资源缓存状态、场景引用计数、UI 容器及组件 vector 所有者；针对已定位的 UI 组件列表记录首次创建/替换/释放。用代际标记区分地址复用，不仅比较裸地址。必要时在独立调试实验中记录目标分配的调用栈，而非跳过 Release 或反复盲跳。
4. 修复候选必须解释旧 UI/组件为何仍引用已失效存储，再安排重复回跳、暂停/播放、切镜头及退出回放验证。两次通过、最后一帧截图、时钟到点都不足以验收。首异常观察窗要覆盖清理和持续渲染。
5. 若缓存内重建不能稳定，备选为走完整的退出/重新打开同一回放，再用已验证程度较高的前向追赶到目标时刻，代价是等待与重新关联镜头。该方案尚未实现或验证，不能当作当前可用回跳功能。

离线验证：当前 Python 全部 178 项通过；这与原生 10 项假对象测试一起，只证明工具自身的检查和现有离线功能，**不改变本轮真实客户端回跳验收失败的结论**。

### 2026-10-20：按回调失效假设实现的实验补丁（后续实机失败，见下一节）

结论：候选补丁已实现并编译，尚未做本轮客户端测试，不能写成已修复。假设为组件移除过程中的 unregister / 虚调用 / Release 改变组件表，原函数继续使用调用前缓存的 header、slot 或 end。首异常只证明内层 vector 已不自洽，尚不能证明哪个回调是破坏源；若入口处已坏，本候选不具备修复其上游破坏源的能力。

实现位于 `blitzcam/native/replay_ui_component_repair_1121.h`，通过 `replay_seek_phase_trial_1121.c` 的原生主任务泵安装，仅修改当前进程内存：

- 清空组件入口首选 VA `0x00cfab30`（RVA `0x008fab30`），覆盖完整 6 字节指令；单组件移除入口 `0x00cfaf90`（RVA `0x008faf90`），覆盖完整 5 字节指令。安装前 Python 核对 ASLR 重定位后的两段完整函数体，native 再校验原始 prologue；只支持已记录的 EXE SHA-256。
- 从 UIControl `+0xe4/+0xe8/+0xec` 重新读取外层 vector，其元素是 12 字节的内层 vector header；每次游戏调用后按 owner 和 component 身份重找槽位，不沿用旧 header/slot/end。组件只在 `+8` 仍属于该 owner（或本次已清零）的情况下解除关联。
- 使用原生 `0x0093e9d0` Retain 临时固定当前组件，保留原生条件 `[owner+0xac] >= 1` 下的 `0x00d08840` 注销；先完成指针移动、末槽清零和 end 更新，再用 `0x0093e4c0` 释放容器引用，最后释放临时引用。相同 owner/component 的递归移除由外层移除完成；移除期间递归请求的全清理在事务提交后排空，未屏蔽最终析构。
- 保留原生属性查询顺序及清理末尾 dirty/子控件通知逻辑。其他线程经原始指令 trampoline 执行原生逻辑，本候选仅替换已核验主线程上的组件移除。
- 所有入口、unregister 前后、erase 提交后/Release 前及完成时，记录 owner/component、外层范围、内层 header/begin/end/capacity 和引用计数。若表结构异常，先记录损坏边界，再触发不可继续的实验异常 `0xe0425549`，不当作空表、不跳过 Release 后继续运行。首 AV 仍原样交给系统/游戏异常处理。
- 补丁和首异常观察器保持到该游戏进程退出；`HookDetach` 在安装本候选后仅结束一次 seek 请求，不撤销 UI 补丁/观察器。重启游戏恢复原始代码。每轮仍重新发现新相机链，时钟、缓存标志和游戏磁盘文件均不改写。

运行入口：`python -X utf8 -B tools/verify_replay_seek_phase.py --mode repair-seek --target 35 --observe 20 --execute`。旧 `--mode seek` 与原 tick 直接 seek 工具仍禁用。新模式需显式 `--execute`；每次只提交一次原生 seek，没有自动重试。短暂落点只记 `landing_observed=true`，`passed` / `full_validation_passed` 保持 false，直至外部完成全套验收。

重新开始条件：用户重开同一回放，约 100 秒暂停并切自由镜头，停止轨迹/速度播放。随后在同一进程做至少三次后向重建（可用前向追赶回到约 100.6 秒，再回到 35 秒），分别检查落点后持续渲染、暂停/恢复、自由/跟随镜头切换，最后退出回放。首个异常或结构违例即停止，不继续盲跳。

日志位于首次安装这次补丁的 `output/replay-seek-phase-runs/<时间戳>/first-fault.bin` 及 `first-fault.bin.ui.bin`；后续轮次报告的 `first_fault_path` / `component_events_path` 指向同一持续记录，覆盖回放退出。组件日志解码：`python -X utf8 -B research/scripts/inspect_ui_component_repair.py <ui.bin路径> --out <json路径>`。这些是回调边界的存储观察，**不是分配代际或 free 调用栈证据**；不能仅凭地址变化/相同解释对象类型或地址复用。

本轮构建：`replay_seek_phase_trial_1121.de4569a379da.dll`，SHA-256 `de4569a379da7c31f6ee36d9e7c395e23d33b468e771e032c0dfab83bc0fc7d0`。21 项原生离线检查通过（原有 10 项任务泵/异常检查，新增 11 项组件、引用计数、回调重分配、递归、detour/trampoline ABI 与损坏表停止检查）；Python 181 项通过。未启动或连接游戏，本轮实机验收待用户重新进入回放。

### 2026-10-20 UTC 02:26–02:32：候选实机验收失败，已停止运行测试

**结论：候选没有修复回放重建稳定性。** 用户重新进入回放并调到 1:09 后，在 PID 49772 安装上述精确 SHA 的候选；两次后向重建都短时落点，但随后前向追赶后的持续渲染发生首个 AV，游戏退出。第三次后向请求尚未进入游戏。没有完成暂停/恢复及正常退出回放验收；镜头切换只用于准备下一次请求，不能算完整验收。

本次主线程为 65028，EXE 实际基址 `0x00280000`。以下目录均在 `output/replay-seek-phase-runs/`，均为 `passed=false`：

| 目录 | 实际请求 | 短时观察 |
|---|---|---|
| `20261020T022603000807Z` | 69.1487474 → 35 秒 | 实到 35.0998964，20.016 秒暂停渲染，无首异常 |
| `20261020T022757827849Z` | 35.0998964 → 100.6 秒 | 实到 100.6988955，5.016 秒 |
| `20261020T022823372828Z` | 100.6988955 → 35 秒 | 实到 35.0998964，20 秒 |
| `20261020T023114597457Z` | 35.0998964 → 100.6 秒 | 实到 100.6988955，5.031 秒；报告结束后仍发生首异常 |
| `20261020T023156382794Z` | 拟第三次回到 35 秒 | 进程已经退出，在发现进程时拒绝，**没有提交 seek** |

持续观察器与组件事件文件保存在首次安装目录 `20261020T022603000807Z/`，不是最后一次请求的目录。新增汇总 `session-failed-summary.json` 明确记录整个会话失败，避免将前面各次的 `landing_observed=true` 误读为修复完成。

首异常及因果边界：

1. `first-fault.bin`（3676 字节）记录 GetTickCount `170154421`、线程 **56124**、`0xc0000005`，EIP `0x5f391db4`，读 `0xbf53500b`，EAX/ESI=`0xbf534f86`。游戏自身 Sentry 转储记录相同线程、IP、异常参数，模块为 `d3d11.dll+0x111db4`。这是渲染线程上的首异常，不能仅用后来的 WER 定位。
2. 首异常自身保存的 EBP 链经过 `dxgi.dll+0xdc7d0 →` 游戏首选 VA `0x00a21fa6 → 0x011161d9 → 0x0111606f`。`0x00a21fa3` 是 `[ID3D11DeviceContext vft+0x3c]` 调用，按本地 SDK 接口定义为 `Unmap`，resource 从当前命令 `+8` 读取、subresource 从 `+0x10` 读取。
3. Sentry 保存了主线程栈上的完整命令：header=`0x04d3f68c`，begin=`0x04d3f69c`，count=1；命令 tag=2，`[command+8]=0xbf534f86`、`[command+0x10]=0`。主线程正等在 `0x01115550` 的同步提交中，ESP=`0x04d3f60c`，EBP 链经 `0x00a1dba2 → 0x00a1dbdc → 0x00a6cdeb → 0x00abb473`。因此坏 resource 已在进入 D3D11 前传入；**不支持命令已经超出返回栈帧寿命的解释**。
4. `0x00a23dc0` 后端将句柄 `0x0c010002` 交给 `0x00a0c260` 查表，再尾调用 `0x00a1da90`。查表使用低 16 位索引、28 字节步长、`+0x18` 元数据的在用位和代际比较 `((handle >> 15) ^ metadata) & 0x1fe`。后续 WER 的池全局 `0x0468f1a8`（实际 `0x0450f1a8`）为 `0x17599028`，索引 2 对应 `0x17599060`。**两个转储都没有该槽的 28 字节内容；后续 WER 全局不等于首异常原子快照。** 缺页不能证明内存当时已释放，不能声称已证实代际失配。
5. `first-fault.bin.ui.bin` 有 **75,176** 条完整事件；最后状态记录 **17,458** 次组件移除、10,559 次全清理、842 次单移除，unregister 边界表地址改变=0、递归合并=0、结构违例=0。这未直接支持“unregister 重分配导致原循环失效”的假设，也不排除更早的失效、日志未覆盖的写入或候选改变寿命/时序。
6. 后续 WER 为线程 **64732** 的 `0xc0000374`，`ntdll.dll+0xedc0f`。它是后续堆损坏报告，不能倒过来替代渲染线程首异常，也尚不能证明与旧 UI 异常由同一写入造成。

原始转储：

```text
C:\Users\Ext1nguisher\AppData\Local\wotblitz\DAVAProject\sentrydb\793f4ee8-6ad4-4ad4-db45-615f1c1d463e.run\151937b5-d7a6-4ae3-97da-5962ea05c8d7.dmp
C:\Users\Ext1nguisher\AppData\Local\CrashDumps\wotblitz.exe.49772.dmp
```

分析产物在首次安装目录：`first-fault-captured-only.json`、`ui-components-decoded.json`、`sentry-crash-analysis.json`、`sentry-main-thread-frames.json`、`wer-crash-analysis.json`、`session-failed-summary.json`。精确 EXE 离线反汇编见 `replay-seek-render-fault-52.txt`、`render-resource-53`、`render-pool-54`、`render-handle-55`（后面三个同样以 `replay-seek-` 开头）。未调试附加游戏。

当前具体处置：`tools/verify_replay_seek_phase.py` 新增 `LIVE_UI_REPAIR_ENABLED=false`，连同原 `LIVE_SEEK_ENABLED=false`，在任何服务/进程/文件访问前拒绝两种 seek 模式；5 项针对入口、ABI 和原函数核验的测试通过。保留失败 DLL 和证据，不覆盖原始运行报告。未自动重启、未再发 seek、未强写缓存标志、未跳过析构、未修改游戏磁盘文件。

**假设及下一步所需证据**：更早的存储生命周期/覆盖问题可能同时解释旧 UI 向量与本次资源指针；本候选自身改变寿命或时序也尚未排除。下一候选前先做隔离的记录实验：不替换组件移除逻辑，按 RewindStarted / 旧 UI 清理 / RewindFinished / 持续渲染阶段标记代次，记录 UI 表缓冲区分配和释放；对资源句柄同时记录 `0x00a0c260` 的池基址、索引、`+0x18` 元数据、返回槽的 28 字节，以及创建/销毁调用栈。若代次不匹配，修复持有旧句柄的一方；若代次匹配而 COM 指针被覆盖，追首次写入。不得仅增加“坏指针则跳过 Unmap”来掩盖故障。在这些证据出现前，不再声称已给出有效根因修复。


## 2026-10-22：按用户明确要求开放工作台实验按钮

用户明确要求将原向前等待定位改为真正的实验性跳转，并移入橙色播放栏。生产入口为 `blitzcam/replay_seek.py`，由 `/api/playback/start` 的 `mode=locate` 显式触发，仅提交一次原生主线程队列请求，`ui_repair=False`；不强写回放时钟，也不自动重试。跳转前退休工作台旧采样器，整个操作暂停采样，完成后重新发现对象链。后退重建若切回跟随镜头，提示切回自由镜头并重新连接，不复用旧场景引用。

此入口是用户要求的实验功能，**不是根因修复或稳定性验收**。此前 UI/渲染崩溃证据与研究 CLI 禁用开关均保留；未把 0.6 秒时钟握手等同于后续渲染稳定。工作区时间范围允许单次 delta 至 3600 秒（Python 研究默认仍为 120 秒），诊断文件路径支持移动目录及 UTF-8；构建使用新的哈希 DLL，历史产物不覆盖。此次仅运行假对象原生自检、Python 隔离单测与拦截播放请求的浏览器验收，未对用户当前游戏发跳转、未重启游戏。
