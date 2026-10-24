/**
 * 原始 u16 血量的 canonical 分类。**两条路径，各自单一权威**：
 *
 *  - `hp_state` 在场（上游 ≥ v0.4.9）：该字段是**唯一权威分类**（`current`/`zero`/`terminal`），
 *    逐事件直用——`terminal` = 负 i16 终态哨兵**全族**（实测 0xFFFF/0xFFFE/0xFFFD，其余负值同编码）。
 *  - 字段缺省（旧产物 / pin < v0.4.9）：维持 **legacy 分类**——仅 `{0x0000, 0xFFFD}` 为终态，
 *    `0xFFFF`/`0xFFFE` 等仍是"未证明哨兵，血量与生死都未知"。**不得**在缺省路径上把全族放宽
 *    为终态（存量语料把 0xFFFF 记为 unavailable；缺省放宽会在旧产物上产生无旁证的死亡判定）。
 *
 * 语义红线：
 *  - 终态哨兵的血量**未知 ≠ 0**，不得改写成 0（`knownHpOf` → null）；归零呈现由 DESTROYED 覆盖；
 *  - 上游 `damage.hp` 的钳 0 只是显示便利，canonical 一律读 `hp_raw`；
 *  - 只依赖 wire 形状，不依赖客户端版本。
 *
 * 枚举 SSOT：本文件的字段类型直接复用 Agent-wire 的 `AiHpStateField`（`api/agent-replay-facets.ts`
 * 的 `AI_HP_STATES` tuple 派生）——producer enum 变更只改那一处，本层不再独立维护第二份枚举。
 *
 * 历史（2026-10-16 裁决，见上游 docs/wotbtools-cross-reference.md §七）：`hp_state` 的动机是
 * 0xFFFE 档弹药架殉爆被本层判成存活（血量冻在最后正值、装填条继续播放；实例 1910 局
 * Intotherainy）；而全族语义经字段获得、缺省不放宽，则来自本仓评审（存量语料的 unavailable
 * 记录 + "未证明哨兵"回归用例）。
 */
export function classifyHpRaw(rawValue, hpState) {
    // 字段在场 = 权威（禁二次解释）
    if (hpState === 'current')
        return 'CURRENT_HP';
    if (hpState === 'zero')
        return 'HP_ZERO_TERMINAL';
    if (hpState === 'terminal')
        return 'DEATH_TERMINAL';
    // 缺省 = legacy 分类（与既有实现逐值一致）
    const raw = rawValue & 0xffff;
    if (raw === 0x0000)
        return 'HP_ZERO_TERMINAL';
    if (raw === 0xfffd)
        return 'DEATH_TERMINAL_FFFD';
    if (raw === 0xffff)
        return 'UNKNOWN_FFFF';
    if (raw === 0xfffe)
        return 'UNKNOWN_OTHER';
    return toSignedShort(raw) > 0 ? 'CURRENT_HP' : 'UNKNOWN_OTHER';
}
export function isTerminalHpState(state) {
    return state === 'HP_ZERO_TERMINAL' || state === 'DEATH_TERMINAL_FFFD' || state === 'DEATH_TERMINAL';
}
/** Java `HealthChangedEvent.isPlausibleHp`：0 < hp < 0xFF00 */
export function isPlausibleHp(hp) {
    return typeof hp === 'number' && hp > 0 && hp < 0xff00;
}
/**
 * 原始值对应的确知当前血量：CURRENT_HP → 有符号值，HP_ZERO → 0，终态哨兵 → null（未知 ≠ 0）。
 * 与 Java prop3 `currentHealth` 的取值口径一致（终态哨兵的 currentHealth 为 null）。
 */
export function knownHpOf(rawValue, hpState) {
    const state = classifyHpRaw(rawValue, hpState);
    if (state === 'CURRENT_HP')
        return toSignedShort(rawValue & 0xffff);
    if (state === 'HP_ZERO_TERMINAL')
        return 0;
    return null;
}
function toSignedShort(raw) {
    return raw >= 0x8000 ? raw - 0x10000 : raw;
}
export function semanticCauseOf(causeFlag, sourceEid, victimEid) {
    const external = sourceEid !== victimEid;
    switch (causeFlag) {
        case 0: return 'DIRECT';
        case 1: return external ? 'FIRE' : null;
        case 2: return external ? 'RAMMING' : null;
        case 3: return external ? null : 'WORLD_OR_ENVIRONMENT';
        case 5: return external ? null : 'DROWNING';
        default: return null;
    }
}
