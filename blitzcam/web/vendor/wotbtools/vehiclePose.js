/**
 * 回放位姿求值——2D 战术俯视与 3D 场景共用的**唯一实现**。
 *
 * 数据面：facet 的位姿列 = 客户端滤波器输出（`filter.rs` 移植，60Hz 逐帧）。渲染**以
 * `pose_kf` 折线为准**（上游 2026-10-18 起为显示重建：段首稳态 0.2s 延迟、只保留 0.2s
 * 静止，段内线性插值即平滑画面）；旧产物缺 `pose_kf` 时回退 10Hz 网格线性插值。理由与
 * 实测见 [`scene/trackInterp.js`] 头注释（网格与 ≈10~12Hz 位置更新不同相会把阶梯混叠成
 * 速度摆动）。判定锚点仍用客户端 0.02s 复位，与渲染折线分属两层。
 *
 * 坐标系契约（**本模块输出 game 系，不做任何镜像**）：
 *   - `x` = 回放世界 x、`y` = 高度、`z` = 回放世界 z；yaw 0 = +z（北）、顺时针为正（rad）。
 *   - 各视图自己施加帧变换，禁止在别处再补符号：
 *     · 3D 场景（`scene/playbackScene.js`）：`pos = (−x, y, z)`、`yaw` 取负、`roll` 取负、
 *       `pitch` 不变（"场景系 x = −游戏 x" 的镜像，与 pack 资产的取向契约同源）；
 *     · 2D 俯视（`utils/mapView.js`）：`toX`/`toY`（y 轴翻转、**无** x 镜像）；
 *       `screenRotation(yawDeg)` 恒等——两侧同为「左 = −300 游戏 x、上 = +300 游戏 z」，
 *       即 3D 场景把相机压到正上方（游戏 +x 朝右）时与 2D 底图是同一张画面。
 *   帧契约的可执行验收见同目录 `vehiclePose.parity.test.ts`。
 *
 * 炮塔：`turret_yaw` 是**绝对角网格**（上游 = prop2 相对角 + 同刻车体 yaw 再解卷绕，
 * 见 `crates/replay-core/src/replay/playback.rs`），本模块换算为相对角 `turretRel = wrapPi(turretAbs − yaw)`；
 * 上游保证该列与 `hull_yaw` 严格同长（本车无 prop2 ⇒ 相对 0 回退），故 2D 不再出现
 * 「prop2 首样本前无炮塔」的空窗。
 *
 * 纯函数、无 THREE/DOM 依赖（单测锁不变量）。
 */
import { GRID_DT, coverageSpanAt, keyframeAt, sampleChannel, sampleChannelWithin, sampleKeyframes, segmentAt, visibilitySpanForSampling } from './trackInterp.js';
import { activeEntityAt } from './facts.js';
export { GRID_DT, coverageSpanAt, keyframeAt, sampleChannel, sampleChannelWithin, sampleKeyframes, segmentAt, visibilitySpanForSampling };
/**
 * 协议精确的 AoI 在场段按 eid 投影为 flat `[t0,t1,...]`（末段缺 `t_out` = 战斗结束 → +∞）。
 * 2D（`buildPoseFacet`）与 3D（`playbackScene` 的 `DATA.visibility`）共用同一投影，
 * 避免两视图对短隐藏段给出不同的炮塔/侧倾插值。
 */
export function visibilitySpansByEid(visibility) {
    const out = new Map();
    for (const w of visibility ?? []) {
        if (!Number.isFinite(w.t_in))
            continue;
        const spans = out.get(w.eid) ?? [];
        spans.push(w.t_in, w.t_out ?? Number.POSITIVE_INFINITY);
        out.set(w.eid, spans);
    }
    return out;
}
/** 从 playback facet 投影出瘦身位姿切面（数组按引用复用，structured clone 时拷贝一次）。 */
export function buildPoseFacet(playback, entityStartsByAccount) {
    const visByEid = visibilitySpansByEid(playback.visibility);
    return {
        tStart: playback.meta.t_start,
        samples: playback.meta.samples,
        vehicles: playback.vehicles.map((v) => ({
            eid: v.eid,
            account_id: v.account_id,
            pos: v.pos,
            hull_yaw: v.hull_yaw,
            hull_pitch: v.hull_pitch,
            hull_roll: v.hull_roll,
            turret_yaw: v.turret_yaw,
            gun_pitch: v.gun_pitch,
            pose_kf: v.pose_kf,
            coverage: v.coverage,
            visibility: visByEid.get(v.eid) ?? v.coverage,
        })),
        ...(entityStartsByAccount ? { entityStartsByAccount } : {}),
    };
}
/**
 * 多实体账号的**活跃实体**选择（2D 渲染用）。
 *
 * 判据与 3D 场景的死亡归属完全同源：`activeEntityAt(firstSeen, tBattle)`（canonical 身份证据，
 * `replay-local/canonical/facts.ts`）。单实体账号直取（无判定成本）；证据缺失或并列（歧义）
 * 一律返回 null —— 调用方回退 canonical 位姿（fail-closed，不猜）。
 */
export function selectActiveDef(defs, starts, tBattle) {
    if (defs.length === 0)
        return null;
    if (defs.length === 1)
        return defs[0];
    if (!starts)
        return null;
    const eid = activeEntityAt(starts, tBattle);
    if (eid === null)
        return null;
    return defs.find((def) => def.eid === eid) ?? null;
}
/** coverage 判定的浮点容差（原始时钟秒）。 */
const COVERAGE_EPS = 1e-6;
/**
 * 该实体的位姿列是否**覆盖**该回放时钟时刻（`coverage` = 原始时钟域的 AoI 闭区间）。
 *
 * 区间外没有位姿证据，而关键帧 / 网格采样都在首样本前**端点钳位**——直接采样会把该实体未来的
 * 首帧位姿泄漏到过去。多实体账号尤其明显：新实体的身份证据（HP / 观测先见）可能早于其首个
 * 位姿样本。故渲染前必须把采样时刻关在证据内；不覆盖 = false，由调用方回落 canonical
 * （fail-closed，不猜）。
 */
export function poseCoveredAt(def, rawTime) {
    const spans = def?.coverage;
    if (!Array.isArray(spans) || !Number.isFinite(rawTime))
        return false;
    for (let i = 0; i + 1 < spans.length; i += 2) {
        const start = spans[i];
        const end = spans[i + 1];
        if (typeof start !== 'number' || typeof end !== 'number')
            continue;
        if (!Number.isFinite(start) || !Number.isFinite(end))
            continue;
        if (rawTime >= start - COVERAGE_EPS && rawTime <= end + COVERAGE_EPS)
            return true;
    }
    return false;
}
/** 关键帧折线：缺省或单点 = null（→ 回退网格），与场景既有判据逐位一致。 */
export function poseKeyframesOf(def) {
    const k = def?.pose_kf;
    return k && Array.isArray(k.t) && k.t.length >= 2 ? k : null;
}
/** 角度 wrap 到 [−π, π)。 */
export function wrapPi(a) {
    let r = a;
    while (r > Math.PI)
        r -= 2 * Math.PI;
    while (r < -Math.PI)
        r += 2 * Math.PI;
    return r;
}
/** 网格标量列：空/缺列 → 0（fail-safe，绝不拿别的通道顶替）。
 * 给了覆盖段时只在段内网格点之间插值（禁止跨隐藏段把旧炮塔角滑到新值）。 */
function gridChannel(arr, t, grid, span) {
    if (!arr || !arr.length)
        return 0;
    if (arr.length === 1)
        return arr[0];
    if (span) {
        return sampleChannelWithin((i) => arr[i], arr.length, t, grid.tStart, GRID_DT, span[0], span[1]);
    }
    return sampleChannel((i) => arr[i], arr.length, t, grid.tStart, GRID_DT);
}
/**
 * 求一辆车在回放时刻 `t`（**回放时钟域**，与 facet 网格同域）的 game 系位姿。
 * `out` 可复用以免每帧分配；返回值即 `out`。
 */
export function sampleVehiclePoseGame(def, grid, t, out = { x: 0, y: 0, z: 0, yaw: 0, pitch: 0, roll: 0, turretAbs: 0, turretRel: 0, gunPitch: 0 }, visibleSpans) {
    // 段内采样：t 落在短隐藏段时夹到前一段（最后已知），不得退回无约束插值。
    const span = visibleSpans ? visibilitySpanForSampling(visibleSpans, t) : null;
    const kf = poseKeyframesOf(def);
    if (kf) {
        const col = (c) => (i) => kf.pos[i * 3 + c];
        out.x = sampleKeyframes(col(0), kf.t, t);
        out.y = sampleKeyframes(col(1), kf.t, t);
        out.z = sampleKeyframes(col(2), kf.t, t);
        out.yaw = sampleKeyframes((i) => kf.yaw[i], kf.t, t);
        out.pitch = sampleKeyframes((i) => kf.pitch[i], kf.t, t);
    }
    else {
        const p = def.pos;
        const n = grid.samples;
        const col = (c) => (i) => p[i * 3 + c];
        for (const c of [0, 1, 2]) {
            const get = col(c);
            const v = span
                ? sampleChannelWithin(get, n, t, grid.tStart, GRID_DT, span[0], span[1])
                : sampleChannel(get, n, t, grid.tStart, GRID_DT);
            if (c === 0)
                out.x = v;
            else if (c === 1)
                out.y = v;
            else
                out.z = v;
        }
        out.yaw = gridChannel(def.hull_yaw, t, grid, span);
        out.pitch = gridChannel(def.hull_pitch, t, grid, span);
    }
    // 侧倾与炮塔/炮管**只有网格列**（`pose_kf` 覆盖 pos/hull_yaw/hull_pitch 三列）。
    out.roll = gridChannel(def.hull_roll, t, grid, span);
    out.turretAbs = gridChannel(def.turret_yaw, t, grid, span);
    out.turretRel = wrapPi(out.turretAbs - out.yaw);
    out.gunPitch = gridChannel(def.gun_pitch, t, grid, span);
    return out;
}
