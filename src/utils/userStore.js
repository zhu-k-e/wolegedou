// ===========================
// 多学员身份层（Multi-Tenant User Store）
// 需求：multi_tenant_isolation_spec.md
//   FR-1  每位学员拥有稳定且唯一的 session_id，跨刷新/跨对话持续复用
//   FR-2  前端维护"学员身份 ↔ session_id"映射，localStorage 持久化
//   FR-3  切换学员时携带对应学员的 session_id，严禁全局共用一个
// 存储结构：
//   ai_learn_users          { [userId]: sessionId }   学员标识 → 会话
//   ai_learn_current_user   当前学员标识
//   persistentSessionId     （旧版单学员 key，仅用于一次性迁移，不再写入）
// ===========================

const USERS_KEY = "ai_learn_users";
const CURRENT_KEY = "ai_learn_current_user";
const LEGACY_SID_KEY = "persistentSessionId";

// 迁移时给旧数据起的默认学员名（无 userId 的旧提问历史条目也归属该学员）
export const DEFAULT_USER_NAME = "学员一";

function safeGet(key) {
    try { return localStorage.getItem(key); } catch { return null; }
}

function safeSet(key, value) {
    try { localStorage.setItem(key, value); return true; } catch { return false; }
}

// 全部学员映射 { userId: sessionId }
export function getUsers() {
    try {
        const raw = localStorage.getItem(USERS_KEY);
        const obj = raw ? JSON.parse(raw) : {};
        return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
    } catch {
        return {};
    }
}

function saveUsers(obj) {
    return safeSet(USERS_KEY, JSON.stringify(obj));
}

// 当前学员标识
export function getCurrentUserId() {
    return safeGet(CURRENT_KEY) || "";
}

export function setCurrentUserId(userId) {
    if (userId) safeSet(CURRENT_KEY, userId);
}

// 某学员绑定的 session_id（未提问过则返回 ""）
export function getSessionForUser(userId) {
    if (!userId) return "";
    const users = getUsers();
    return users[userId] || "";
}

// 将 session_id 绑定到某学员（学员首次提问后由 App 调用）
export function bindSession(userId, sessionId) {
    if (!userId || !sessionId) return;
    const users = getUsers();
    users[userId] = sessionId;
    saveUsers(users);
}

// 重新诊断：为学员生成全新的 session 并绑定（覆盖旧映射）。
// 用途：后端对同一 session 的报告只在首次生成、不随新任务更新（实测），
// 学员想看到"热力图随学习推进变化"时，调用本函数换一个新会话，
// 下次提问走后端会重新诊断并生成全新报告。
export function resetUserSession(userId) {
    if (!userId) return "";
    const newSid = "session_" + Date.now();
    const users = getUsers();
    users[userId] = newSid;
    saveUsers(users);
    return newSid;
}

// 新增学员：写入映射（session 可为空，首次提问时生成并绑定），并设为当前学员
export function createUser(userId, sessionId = "") {
    if (!userId) return;
    const users = getUsers();
    if (!users[userId]) {
        users[userId] = sessionId || "";
        saveUsers(users);
    }
    setCurrentUserId(userId);
}

// 学员标识列表（用于切换列表展示）
export function listUsers() {
    return Object.keys(getUsers());
}

// 旧数据一次性迁移：
//  - 完全没有学员映射时，把旧 persistentSessionId 绑定给默认学员"学员一"，
//    保证老用户刷新后热力图不归零（AC-2 连续性）
//  - 之后 persistentSessionId 不再作为主路径（只读不写）
export function migrateLegacySession() {
    const users = getUsers();
    if (Object.keys(users).length > 0) return; // 已有学员数据，不重复迁移

    const legacy = safeGet(LEGACY_SID_KEY);
    if (legacy) {
        users[DEFAULT_USER_NAME] = legacy;
    } else {
        users[DEFAULT_USER_NAME] = "";
    }
    saveUsers(users);
    if (!getCurrentUserId()) {
        setCurrentUserId(DEFAULT_USER_NAME);
    }
}
