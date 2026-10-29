# 关键帧复制粘贴（源码，未打包）

日期：2026-10-23。本轮未更新版本或便携包。

## 使用

选中时间轴单点、多点或多条轨道上的点，按 Ctrl+C；定位播放头后按 Ctrl+V。最早所选点对齐播放头，其余按原间隔放到原轨道。复制的是独立快照，之后修改源点不会改变副本。粘贴后继续选中新增或覆盖的整批点，可用 Ctrl+Z / Ctrl+Shift+Z 一次撤销或重做。

工具栏复制按钮也写入系统剪贴板，粘贴按钮使用当前编辑器最近复制的关键帧副本。切换项目保留副本；不同窗口或重载后可通过系统 Ctrl+V 粘贴。普通文本、数值输入、可编辑文本和已选择的页面文字沿用原复制粘贴行为；外部普通文字不会触发旧关键帧副本的粘贴。

同轨同刻的点被覆盖，其他轨道及其他时刻的点保留。摄像机点保存值、显式 ease 和自动曲线标记；速度点保存倍率及出段有效缓动。粘贴成功暂停预览，播放头时间和工作区间保持原样。

相机和速度点混选使用同一个最早时刻作为锚点；不受当前对局/拍摄标尺影响。速度曲线以对局时刻合并节点，按每段对局长度除以平均倍率计算拍摄长度，再重建 progress。被粘贴的点及原有未覆盖点的对局时刻保持准确；需要时扩展独立速度曲线时间范围。合法贝塞尔手柄原样保留，只有与新邻居相接后实际超出倍率范围的手柄会限制到合法范围。

模式一支持摄像机点并自动扩展可见时间范围；含速度点的批次需在模式二粘贴。越过全片边界、赛前或未知比赛开始限制、过密点、数量上限和非法剪贴板数据均整批拒绝，不修改轨迹、副本、选择或撤销记录。拖动和数值编辑期间不会复制临时数据或插入粘贴操作。

## 参考

Adobe 说明最早所选关键帧粘贴到当前时间，其余保持间隔，并粘到相同属性：[Premiere Pro 复制粘贴关键帧](https://helpx.adobe.com/premiere/desktop/add-video-effects/control-effects-and-transitions-using-keyframes/copy-and-paste-keyframes.html)。同轨同刻覆盖、混合摄像机/速率及项目限制是本应用的具体实现规则。

## 验证

- `node tools/test_keyframe_clipboard.cjs`：14 组纯数据检查，包括多轨、速度积分、原点位置、范围延伸、同刻覆盖、元数据、输入快照及非法数据拒绝。
- `tools/test_keyframe_clipboard_ui.cjs`：12 类组件场景，包括事件、普通文字、快照、跨载入、混选、两种标尺、赛前/越界原子失败、拖动、锁定及 BODY 事件目标的编辑器/输入框焦点识别。
- `python -X utf8 -B -c "from tools.test_speed_window_ui import main;main('test_keyframe_clipboard_app_ui.cjs')"`：实际工作台的 Ctrl+C/V 系统剪贴板、文本编辑、工具栏、预览暂停、保存重载、速度面板及跨项目场景。
- `python -X utf8 -B -m unittest discover -s tests -q`：459 项通过。
- `python -X utf8 -B -m tools.test_keyframe_clipboard_native`：原生 WebView2 双窗口验收通过。禁用浏览器加速键及拒绝权限时，工具栏复制、Ctrl+C/V、自定义剪贴板数据及跨窗口粘贴仍正常，输入框文字复制粘贴保留。修正原生事件落在 BODY 时的编辑器焦点识别；验收结束恢复原系统剪贴板。
- 原有工作台完整界面、速度编辑器及工作区拖动验收均通过；拖动仍保留撤销、暂停预览、固定拍摄标尺及保存重载行为。

截图及报告在 `output/archive/2026-10-27/verification/keyframe-clipboard-acceptance`、`output/archive/2026-10-27/verification/keyframe-clipboard-app-acceptance`、`output/archive/2026-10-27/verification/keyframe-clipboard-native-acceptance`。均使用独立合成数据，不连接游戏、不加载 Hook。原生验收仅编译临时探针，正式宿主及 0.9.4 便携包未改。
