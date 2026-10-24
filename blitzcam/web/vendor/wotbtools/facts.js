/**
 * WotbTools canonical replay facts：上游 Agent 切面（BattleResult + PlaybackData + AiReviewFacet）
 * → WotbTools 自己的语义事实层。2D 回放投影（`playback/toBattlePlaybackDataset`）与 AI 复盘投影
 * （`ai/toClientAiReviewProjection`）都只消费这一层，不直接把 Agent DTO 当领域契约。
 *
 * 帧与归因规则沿用已退役 Java canonical 层（出处见各段注释），补充已验证的 Avatar 累计伤害广播。
 * 输入只用上游**已明确提供**
 * 的事实；上游没给的不猜，交给 `limitations` / `unavailableEvidence` 如实降级：
 *  - 身份：`TeamEntityMapper` / `TeamPerspectiveResolver`（结算花名册是队伍权威）；
 *  - AoI 观测段：`ReplayAoiLifecycle`（[observedFrom, absentFrom) 半开区间）；
 *  - 血量采样：`EntityIndex.healths`（prop3 + 每次物化快照；method1 不进血量帧）；
 *  - 掉血 / 归属 / 击毁：`PlaybackCombatReconstruction` + `ReplayTerminalLifecycle`
 *    （method8 直击 = 归属证据，非直击 / 短体变体 = 冲突证据，fail-closed）。
 * 时间一律 battle-relative（原始时钟 − 战斗开始 = period 3 时钟）。
 */
import { classifyHpRaw, isPlausibleHp, isTerminalHpState, knownHpOf, semanticCauseOf, } from './hpRawState.js';
export const EPS = 1e-6;
/** Java `BattleTimelineBuilder.MAX_BATTLE_DURATION_SEC` */
const MAX_BATTLE_DURATION_SEC = 420;
/** Java `PlaybackCombatReconstruction.KILL_BACKING_WINDOW_SEC` */
export const KILL_BACKING_WINDOW_SEC = 0.25;
/** Java `ReplayTerminalLifecycle.SAME_CLOCK_EPSILON` */
const SAME_CLOCK_EPSILON = 1e-6;
/** Java `EntityMethodDecoder.DAMAGE_SUB_DIRECT`：method8 result=3 才是直击（其余为未解码变体） */
const DAMAGE_SUB_DIRECT = 3;
/** Java parseDamage：body = payload[8..]，body < 18 字节 → 短体变体 ⇔ payload < 26 */
const DAMAGE_MIN_PAYLOAD_LEN = 26;
/** 上游 playback COVERAGE_GAP：原始采样间隙 > 2 s 视为空洞 */
const STREAM_GAP_SEC = 2;
const PERIOD_BATTLE = 3;
const PERIOD_AFTERBATTLE = 4;
/**
 * Java `BattleTimelineBuilder.resolveClock / resolveDurationSec` 同优先级：
 * 时长 ① 结算 root5（cap 420）② AFTERBATTLE − 开始 ③ meta battleDuration（cap 420）④ 流末时钟 − 开始。
 */
export function resolveReplayClock(periods, result, streamEndRaw) {
    const battleStart = periods.find((p) => p.period === PERIOD_BATTLE);
    const roundFinished = periods.find((p) => p.period === PERIOD_AFTERBATTLE);
    const settlement = positive(result?.result_duration_secs);
    let startRaw;
    let estimated = false;
    if (battleStart && Number.isFinite(battleStart.clock)) {
        startRaw = battleStart.clock;
    }
    else if (roundFinished && settlement !== null) {
        startRaw = roundFinished.clock - settlement;
        estimated = true;
    }
    else {
        return null;
    }
    let durationSec = null;
    if (settlement !== null)
        durationSec = Math.min(settlement, MAX_BATTLE_DURATION_SEC);
    else if (roundFinished && roundFinished.clock - startRaw > 0)
        durationSec = roundFinished.clock - startRaw;
    else if (positive(result?.battle_duration_secs) !== null) {
        durationSec = Math.min(result.battle_duration_secs, MAX_BATTLE_DURATION_SEC);
    }
    else if (typeof streamEndRaw === 'number' && streamEndRaw - startRaw > 0) {
        durationSec = Math.min(streamEndRaw - startRaw, MAX_BATTLE_DURATION_SEC);
    }
    if (durationSec === null || !(durationSec > 0))
        return null;
    return { startRaw, durationSec, estimated };
}
function positive(v) {
    return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null;
}
// ---------- 构建 ----------
export function buildCanonicalReplayFacts(input) {
    const { result, aiReview } = input;
    const periods = aiReview.battle.periods.map((p) => ({ clock: p.clock, period: p.period }));
    const clock = resolveReplayClock(periods, result, input.streamEndRaw ?? null);
    if (!clock)
        return null;
    const rel = (raw) => raw - clock.startRaw;
    const afterBattle = periods.find((p) => p.period === PERIOD_AFTERBATTLE);
    const events = aiReview.events;
    // ---- 身份（TeamEntityMapper：结算花名册是队伍权威；只收实际参战者） ----
    const settlement = new Map();
    for (const p of result?.players ?? [])
        if (p.account_id > 0 && (p.team === 1 || p.team === 2))
            settlement.set(p.account_id, p);
    const recorderAccountId = positive(result?.author_account_id) ?? null;
    const entities = new Map();
    const entityIdsByAccount = new Map();
    const mappingLimitations = [];
    let mappingConflict = false;
    for (const r of aiReview.rosters) {
        if (!(r.eid > 0) || !(typeof r.account_id === 'number' && r.account_id > 0))
            continue;
        const player = settlement.get(r.account_id);
        if (!player)
            continue;
        const team = player.team;
        // 实体自报队伍与结算矛盾：身份不可信，整条实体不进 canonical（与 Java 冲突实体剔除同口径）
        if (r.team !== undefined && r.team !== 0 && r.team !== team) {
            mappingConflict = true;
            continue;
        }
        entities.set(r.eid, {
            entityId: r.eid,
            accountId: r.account_id,
            team,
            nickname: player.nickname || r.nickname || '',
            tankId: player.tank_id > 0 ? player.tank_id : r.tank_id ?? 0,
            recorder: recorderAccountId !== null && r.account_id === recorderAccountId,
        });
        const ids = entityIdsByAccount.get(r.account_id) ?? [];
        ids.push(r.eid);
        entityIdsByAccount.set(r.account_id, ids);
    }
    for (const ids of entityIdsByAccount.values())
        ids.sort((a, b) => a - b);
    if (mappingConflict)
        mappingLimitations.push('TEAM_ENTITY_MAPPING_CONFLICT');
    if (entities.size === 0)
        mappingLimitations.push('TEAM_ENTITY_MAPPING_INSUFFICIENT');
    // ---- 视角（TeamPerspectiveResolver） ----
    const perspectiveLimitations = [];
    const recorderTeam = recorderAccountId !== null ? settlement.get(recorderAccountId)?.team : undefined;
    const perspectiveTeam = recorderTeam === 1 || recorderTeam === 2 ? recorderTeam : null;
    if (perspectiveTeam === null)
        perspectiveLimitations.push('PERSPECTIVE_TEAM_UNRESOLVED');
    const recorderEntityIds = recorderAccountId !== null ? entityIdsByAccount.get(recorderAccountId) ?? [] : [];
    if (perspectiveTeam !== null && recorderEntityIds.length === 0)
        perspectiveLimitations.push('RECORDER_ENTITY_UNMAPPED');
    if (recorderEntityIds.length > 1)
        perspectiveLimitations.push('RECORDER_ENTITY_REENTRY');
    const accountOf = (eid) => entities.get(eid)?.accountId ?? null;
    // ---- 战斗车辆类（Java EntityClassRegistry）：Type5 entityTypeId=2 物化证据（visibility.hp_raw 在场）
    // → VEHICLE；映射到录像者账号的实体 → AVATAR（粘性，覆盖 VEHICLE：录像者实体按 Avatar 协议角色分派方法）。
    // 只有 VEHICLE 实体的 method8 才是伤害/命中通知——录像者被击中的通知因此不进归属证据（固定的旧口径）。
    const vehicleEntityIds = new Set();
    for (const e of events)
        if (e.type === 'visibility' && typeof e.hp_raw === 'number')
            vehicleEntityIds.add(e.eid);
    for (const id of recorderEntityIds)
        vehicleEntityIds.delete(id);
    // ---- AoI 观测段 + 血量采样 + method1 + method8 ----
    const observation = new Map();
    const hpSamples = new Map();
    const healthEvents = [];
    const damageNotices = [];
    events.forEach((e, order) => {
        switch (e.type) {
            case 'visibility': {
                const w = {
                    entityId: e.eid,
                    fromSec: rel(e.t_in),
                    toSec: typeof e.t_out === 'number' ? rel(e.t_out) : null,
                    materializationHp: typeof e.hp_raw === 'number' && isPlausibleHp(e.hp_raw) ? e.hp_raw : null,
                    order,
                };
                push(observation, e.eid, w);
                if (w.materializationHp !== null) {
                    push(hpSamples, e.eid, {
                        t: w.fromSec, entityId: e.eid, hp: w.materializationHp, kind: 'MATERIALIZATION',
                        rawState: null, alive: true, exact: true, order,
                    });
                }
                break;
            }
            case 'health': {
                // 上游 `hp_state` 在场 = 权威分类；缺省（旧产物）按 hp_raw 同一规则现算（见 hpRawState.ts）
                const rawState = classifyHpRaw(e.hp_raw, e.hp_state);
                push(hpSamples, e.eid, {
                    t: rel(e.t), entityId: e.eid, hp: knownHpOf(e.hp_raw, e.hp_state), kind: 'PROP3', rawState,
                    alive: rawState === 'CURRENT_HP' ? true : isTerminalHpState(rawState) ? false : null,
                    // 缺 hp_state 的旧产物：正 i16 与终态族在 Java 同为 EXACT，其余负值 PARTIAL（现规则下不存在该档）
                    exact: rawState === 'CURRENT_HP' || isTerminalHpState(rawState),
                    order,
                });
                break;
            }
            case 'damage':
                healthEvents.push({
                    t: rel(e.t), entityId: e.victim_eid, hpRaw: e.hp_raw,
                    rawState: classifyHpRaw(e.hp_raw, e.hp_state),
                    sourceEntityId: e.source_eid, causeFlag: e.cause, order,
                });
                break;
            case 'hit_notice': {
                // Java：method8 只对战斗车辆实体解码（其它类 = METHOD8_CLASS_MISMATCH，不产出事件）
                if (!vehicleEntityIds.has(e.eid))
                    break;
                const t = rel(e.t);
                if (e.payload_len < DAMAGE_MIN_PAYLOAD_LEN) {
                    damageNotices.push({
                        t, kind: 'SHORT_VARIANT', envelopeEntityId: e.eid, attackerEntityId: 0, victimEntityId: e.eid,
                        primaryResult: null, secondaryResult: null, order,
                    });
                    break;
                }
                const attacker = toSignedInt(e.shooter_eid ?? 0);
                const victimRaw = toSignedInt(e.victim_eid ?? 0);
                const victim = victimRaw > 0 ? victimRaw : e.eid;
                damageNotices.push({
                    t, kind: e.result === DAMAGE_SUB_DIRECT ? 'HIT' : 'UNDECODED_VARIANT', envelopeEntityId: e.eid,
                    attackerEntityId: attacker, victimEntityId: victim,
                    primaryResult: e.result ?? null, secondaryResult: e.secondary ?? null, order,
                });
                break;
            }
            default:
                break;
        }
    });
    for (const list of observation.values())
        list.sort((a, b) => a.fromSec - b.fromSec || a.order - b.order);
    for (const list of hpSamples.values())
        list.sort((a, b) => a.t - b.t || a.order - b.order);
    // ---- 原始位姿 / 炮塔（按时钟稳定排序；包序同刻保留） ----
    const poses = new Map();
    for (const p of aiReview.poses) {
        const idx = p.t.map((_, i) => i).sort((a, b) => p.t[a] - p.t[b] || a - b);
        poses.set(p.eid, {
            entityId: p.eid, t: idx.map((i) => rel(p.t[i])), x: idx.map((i) => p.x[i]), y: idx.map((i) => p.y[i]),
            z: idx.map((i) => p.z[i]), yaw: idx.map((i) => p.yaw[i]),
        });
    }
    const turrets = new Map();
    for (const tr of aiReview.turrets) {
        const idx = tr.t.map((_, i) => i).sort((a, b) => tr.t[a] - tr.t[b] || a - b);
        turrets.set(tr.eid, { entityId: tr.eid, t: idx.map((i) => rel(tr.t[i])), relYawDeg: idx.map((i) => prop2RelYawDeg(tr.raw[i])) });
    }
    const inBattle = (t) => Number.isFinite(t) && t >= 0 && t <= clock.durationSec + EPS;
    // The recorder Avatar has a different eid from the vehicle roster. prop10 broadcasts belong
    // to that recorder, not to the Avatar eid as a player. Preserve their actual observation clock;
    // a settlement total must never appear early in playback. Conflicting sources fail closed.
    const recorderDamageDealt = [];
    if (recorderAccountId !== null && settlement.has(recorderAccountId)) {
        const ticks = events.filter((e) => e.type === 'damage_tick' && Number.isSafeInteger(e.eid) && e.eid > 0
            && Number.isSafeInteger(e.cumulative) && e.cumulative >= 0 && inBattle(rel(e.t))
            && (accountOf(e.eid) === null || accountOf(e.eid) === recorderAccountId));
        if (new Set(ticks.map(e => e.eid)).size === 1) {
            ticks.sort((a, b) => a.t - b.t);
            for (const tick of ticks) {
                const last = recorderDamageDealt.at(-1);
                if (last && tick.cumulative < last.total)
                    continue;
                const timeSec = rel(tick.t);
                if (last && Math.abs(timeSec - last.timeSec) <= EPS)
                    last.total = tick.cumulative;
                else
                    recorderDamageDealt.push({ timeSec, total: tick.cumulative });
            }
        }
    }
    // ---- 掉血（PlaybackCombatReconstruction.derive）：只用 prop3 可信采样 ----
    const samplesByAccount = new Map();
    for (const [eid, list] of hpSamples) {
        const account = accountOf(eid);
        if (account === null)
            continue;
        for (const s of list) {
            if (s.kind !== 'PROP3' || !s.exact || s.hp === null || !inBattle(s.t))
                continue;
            if (s.hp !== 0 && !isPlausibleHp(s.hp))
                continue;
            push(samplesByAccount, account, { t: s.t, hp: s.hp });
        }
    }
    const hitsByVictim = new Map();
    const conflictsByVictim = new Map();
    const unresolvedConflicts = [];
    for (const n of damageNotices) {
        if (!inBattle(n.t))
            continue;
        const victim = accountOf(n.victimEntityId);
        if (n.kind === 'HIT') {
            const attacker = n.attackerEntityId > 0 ? accountOf(n.attackerEntityId) ?? 0 : 0;
            if (victim === null)
                unresolvedConflicts.push(n.t);
            else
                push(hitsByVictim, victim, { t: n.t, attacker });
        }
        else if (victim === null) {
            unresolvedConflicts.push(n.t);
        }
        else {
            push(conflictsByVictim, victim, n.t);
        }
    }
    for (const list of samplesByAccount.values())
        list.sort((a, b) => a.t - b.t);
    for (const list of hitsByVictim.values())
        list.sort((a, b) => a.t - b.t);
    const lossesByVictim = new Map();
    for (const [victim, raw] of samplesByAccount) {
        const list = collapseSameClock(raw);
        const out = [];
        for (let i = 1; i < list.length; i++) {
            const prev = list[i - 1];
            const cur = list[i];
            if (prev.hp <= 0 || cur.hp >= prev.hp)
                continue;
            let sole = null;
            let inWindow = 0;
            let mixed = false;
            for (const h of hitsByVictim.get(victim) ?? []) {
                if (!within(h.t, prev.t, cur.t))
                    continue;
                inWindow++;
                if (h.attacker <= 0)
                    mixed = true;
                else if (sole === null)
                    sole = h.attacker;
                else if (sole !== h.attacker)
                    mixed = true;
            }
            const conflict = (conflictsByVictim.get(victim) ?? []).some((t) => within(t, prev.t, cur.t))
                || unresolvedConflicts.some((t) => within(t, prev.t, cur.t));
            const reliable = !mixed && !conflict && inWindow >= 1 && sole !== null;
            out.push({
                fromSec: prev.t, toSec: cur.t, hpLoss: prev.hp - cur.hp,
                attackerAccountId: reliable ? sole : null, attackerReliable: reliable,
                damageEventCount: inWindow, fromHp: prev.hp, toHp: cur.hp,
            });
        }
        if (out.length)
            lossesByVictim.set(victim, out.sort((a, b) => a.fromSec - b.fromSec));
    }
    // ---- 击毁（ReplayTerminalLifecycle.finalStateByAccount）+ 击杀者（uniqueKiller） ----
    const evidence = [];
    const addEvidence = (eid, t, order, terminal, kind) => {
        const account = accountOf(eid);
        if (account === null || !Number.isFinite(t) || t <= 0)
            return;
        evidence.push({ accountId: account, entityId: eid, timeSec: t, order, terminal, kind });
    };
    for (const list of hpSamples.values()) {
        for (const s of list) {
            if (!s.exact)
                continue;
            if (s.kind === 'MATERIALIZATION') {
                addEvidence(s.entityId, s.t, s.order, false, null);
            }
            else if (s.rawState !== null && isTerminalHpState(s.rawState)) {
                addEvidence(s.entityId, s.t, s.order, true, s.rawState === 'HP_ZERO_TERMINAL' ? 'HP_ZERO' : 'DEATH_SENTINEL');
            }
            else if (s.alive === true && isPlausibleHp(s.hp)) {
                addEvidence(s.entityId, s.t, s.order, false, null);
            }
        }
    }
    for (const h of healthEvents) {
        // 身份门（VehicleHealthCauseValidator）：原因只对可用参战者成立
        const cause = accountOf(h.entityId) !== null
            ? semanticCauseOf(h.causeFlag, h.sourceEntityId, h.entityId) : null;
        if (cause === 'DROWNING')
            addEvidence(h.entityId, h.t, h.order, true, 'DROWNING');
        else if (isTerminalHpState(h.rawState)) {
            addEvidence(h.entityId, h.t, h.order, true, h.rawState === 'HP_ZERO_TERMINAL' ? 'HP_ZERO' : 'DEATH_SENTINEL');
        }
    }
    evidence.sort((a, b) => a.timeSec - b.timeSec || a.order - b.order);
    const finalState = new Map();
    for (const e of evidence) {
        const cur = finalState.get(e.accountId);
        finalState.set(e.accountId, cur ? laterEvidence(cur, e) : e);
    }
    const destroyed = [];
    for (const terminal of finalState.values()) {
        if (!terminal.terminal || !inBattle(terminal.timeSec) || terminal.kind === null)
            continue;
        const victim = terminal.accountId;
        const t = terminal.timeSec;
        let killer = null;
        if (terminal.kind !== 'DROWNING') {
            const lethal = lethalLossWindow(samplesByAccount.get(victim) ?? [], t);
            const from = lethal ?? t - KILL_BACKING_WINDOW_SEC;
            killer = uniqueKiller(victim, from, t, hitsByVictim, conflictsByVictim, unresolvedConflicts);
        }
        destroyed.push({ timeSec: t, accountId: victim, killerAccountId: killer, kind: terminal.kind });
    }
    destroyed.sort((a, b) => a.timeSec - b.timeSec);
    const winner = aiReview.battle.winner;
    const streamEndSec = typeof input.streamEndRaw === 'number' && Number.isFinite(input.streamEndRaw) ? rel(input.streamEndRaw) : null;
    return {
        clock,
        battleEndSec: afterBattle ? rel(afterBattle.clock) : null,
        streamEndSec,
        streamTruncated: !afterBattle && streamEndSec !== null && streamEndSec < clock.durationSec - STREAM_GAP_SEC,
        winnerTeam: winner === 1 || winner === 2 ? winner : null,
        recorderAccountId,
        perspectiveTeam,
        recorderEntityIds,
        entities,
        entityIdsByAccount,
        vehicleEntityIds,
        observation,
        poses,
        turrets,
        hpSamples,
        healthEvents,
        recorderDamageDealt,
        damageNotices,
        lossesByVictim,
        destroyed,
        mappingLimitations,
        perspectiveLimitations,
    };
}
// ---------- 查询（与 Java 同一边界语义） ----------
/** Java `ReplayAoiLifecycle.segmentAt`：[observedFrom, absentFrom) 半开区间 */
export function observationAt(facts, entityId, t) {
    for (const w of facts.observation.get(entityId) ?? []) {
        if (!Number.isFinite(t) || t < w.fromSec - 1e-9)
            continue;
        if (w.toSec === null || t < w.toSec - 1e-9)
            return w;
    }
    return null;
}
/** Java `EntityIndex.lastHealthAtOrBefore` */
export function lastHpSampleAtOrBefore(facts, entityId, t) {
    let hit = null;
    for (const s of facts.hpSamples.get(entityId) ?? []) {
        if (s.t > t)
            break;
        hit = s;
    }
    return hit;
}
/** Java `EntityIndex.displayCapacityHpAt`：截至 t 的可信 currentHp 最大值（仅 HP bar 量程，不是 max HP 事实） */
export function displayCapacityAt(facts, entityId, t) {
    let max = 0;
    for (const s of facts.hpSamples.get(entityId) ?? []) {
        if (s.t > t + 1e-9)
            break;
        if (s.hp !== null && s.hp > max)
            max = s.hp;
    }
    return max > 0 ? max : null;
}
/** Java `EntityIndex.lastPositionAtOrBefore`：≤ t 的最后一个原始观测下标；无 → -1 */
export function lastPoseIndexAtOrBefore(track, t) {
    if (!track)
        return -1;
    let lo = 0, hi = track.t.length - 1, hit = -1;
    while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (track.t[mid] <= t) {
            hit = mid;
            lo = mid + 1;
        }
        else
            hi = mid - 1;
    }
    return hit;
}
/**
 * prop2 u16 → 炮塔相对偏航（度）：`u16 · 360 / 65536 − 180`——WotbTools 已证明的 canonical 编码
 * （`docs/research/replay/turret-direction.md`，java/AGENTS.md「勿改编码常量」）。上游把低 6 位解释为
 * 俯仰比例、只取高 10 位；两者相差 ≤ 0.35°，canonical 保持旧口径不静默改变。
 */
export function prop2RelYawDeg(raw) {
    return ((raw & 0xffff) * 360) / 65536 - 180;
}
// ---------- 内部 ----------
function push(map, key, value) {
    const list = map.get(key);
    if (list)
        list.push(value);
    else
        map.set(key, [value]);
}
function toSignedInt(v) {
    return v | 0;
}
/** (from, to] 窗口（Java `inWindow`） */
function within(t, from, to) {
    return t > from + EPS && t <= to + EPS;
}
/** 同刻重复采样折叠；同刻取值冲突 → 该刻不可用（Java `collapseSameClockDuplicates`） */
function collapseSameClock(points) {
    const out = [];
    let i = 0;
    while (i < points.length) {
        const { t, hp } = points[i];
        let conflict = false;
        let j = i + 1;
        while (j < points.length && Math.abs(points[j].t - t) <= EPS) {
            if (points[j].hp !== hp)
                conflict = true;
            j++;
        }
        if (!conflict)
            out.push({ t, hp });
        i = j;
    }
    return out;
}
function lethalLossWindow(raw, destroyedT) {
    const list = collapseSameClock(raw);
    for (let i = list.length - 1; i >= 1; i--) {
        const cur = list[i];
        if (Math.abs(cur.t - destroyedT) > EPS)
            continue;
        const prev = list[i - 1];
        if (cur.hp === 0 && prev.hp > 0)
            return prev.t;
    }
    return null;
}
function uniqueKiller(victim, from, to, hitsByVictim, conflictsByVictim, unresolvedConflicts) {
    if ((conflictsByVictim.get(victim) ?? []).some((t) => within(t, from, to)))
        return null;
    if (unresolvedConflicts.some((t) => within(t, from, to)))
        return null;
    let sole = null;
    let count = 0;
    for (const h of hitsByVictim.get(victim) ?? []) {
        if (!within(h.t, from, to))
            continue;
        count++;
        if (h.attacker <= 0 || h.attacker === victim)
            return null;
        if (sole === null)
            sole = h.attacker;
        else if (sole !== h.attacker)
            return null;
    }
    return count > 0 ? sole : null;
}
/** Java `ReplayTerminalLifecycle.later`：同一终态段保留首个时刻；同刻 FFFD/溺水终态压过正血量镜像 */
function laterEvidence(current, incoming) {
    const delta = incoming.timeSec - current.timeSec;
    if (delta > SAME_CLOCK_EPSILON)
        return current.terminal && incoming.terminal ? current : incoming;
    if (delta < -SAME_CLOCK_EPSILON)
        return current;
    if (current.terminal === incoming.terminal)
        return incoming.order >= current.order ? incoming : current;
    const terminal = current.terminal ? current : incoming;
    if (terminal.kind === 'DROWNING' || terminal.kind === 'DEATH_SENTINEL')
        return terminal;
    return incoming.order >= current.order ? incoming : current;
}
/** Canonical first identity evidence, in battle-relative seconds; unknown starts remain explicit. */
export function entityFirstSeenByAccount(facts) {
    return new Map([...facts.entityIdsByAccount].map(([accountId, ids]) => [accountId, new Map(ids.map(id => {
            const starts = [facts.poses.get(id)?.t[0], facts.hpSamples.get(id)?.[0]?.t, facts.observation.get(id)?.[0]?.fromSec]
                .filter((t) => typeof t === 'number' && Number.isFinite(t));
            return [id, starts.length ? Math.min(...starts) : null];
        }))]));
}
/** Most recently entered entity at t; numeric IDs never determine order. Ties/missing evidence stay unknown. */
export function activeEntityAt(firstSeen, t) {
    if (!Number.isFinite(t))
        return null;
    let latest = -Infinity;
    for (const first of firstSeen.values()) {
        if (first === null || !Number.isFinite(first))
            return null;
        if (first <= t + EPS)
            latest = Math.max(latest, first);
    }
    let owner = null;
    for (const [id, first] of firstSeen) {
        if (first !== null && first <= t + EPS && Math.abs(first - latest) <= EPS) {
            if (owner !== null)
                return null;
            owner = id;
        }
    }
    return owner;
}
