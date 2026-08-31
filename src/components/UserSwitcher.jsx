import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";

import {
    User,
    ChevronDown,
    Plus,
    Check
} from "lucide-react";

/**
 * 学员身份切换器（多租户隔离 - FR-2/FR-3）
 * - 显示当前学员标识，点击展开下拉：
 *   ① 已保存学员列表（点击即切换，携带各自独立的 session_id）
 *   ② 新增学员输入框（学号/姓名，Enter 或点击新增按钮）
 * - 下拉菜单用 React Portal 渲染到 document.body 顶层：
 *   避免被 .header 的 backdrop-filter 层叠上下文限制，保证真正"浮"在所有面板之上
 */
function UserSwitcher({ currentUser, users = [], onSwitch, onCreate }) {
    const [open, setOpen] = useState(false);
    const [newName, setNewName] = useState("");
    const [pos, setPos] = useState(null); // 菜单定位 { top, right }（相对视口）
    const btnRef = useRef(null);
    const menuRef = useRef(null);

    // 打开时计算按钮在视口中的位置，菜单用 fixed 定位对齐
    const toggleOpen = () => {
        if (!open) {
            const rect = btnRef.current?.getBoundingClientRect();
            if (rect) {
                setPos({
                    top: rect.bottom,
                    right: window.innerWidth - rect.right,
                });
            }
            setOpen(true);
        } else {
            setOpen(false);
        }
    };

    // 点击外部 / 滚动 / 缩放时关闭（滚动不关闭会导致位置错乱，直接收起更稳妥）
    useEffect(() => {
        if (!open) return;
        const handleClickOutside = (e) => {
            if (btnRef.current && btnRef.current.contains(e.target)) return;
            if (menuRef.current && menuRef.current.contains(e.target)) return;
            setOpen(false);
        };
        const closeOnViewChange = () => setOpen(false);
        document.addEventListener("mousedown", handleClickOutside);
        window.addEventListener("scroll", closeOnViewChange, true);
        window.addEventListener("resize", closeOnViewChange);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
            window.removeEventListener("scroll", closeOnViewChange, true);
            window.removeEventListener("resize", closeOnViewChange);
        };
    }, [open]);

    const handleCreate = () => {
        const name = newName.trim();
        if (!name) return;
        onCreate(name);
        setNewName("");
        setOpen(false);
    };

    // 菜单内容样式（悬浮层：阴影 + 紫色发光边框 + 毛玻璃）
    const menuStyle = {
        position: "fixed",
        top: (pos?.top || 0) + 12,
        right: pos?.right || 0,
        minWidth: "240px",
        background: "rgba(28, 28, 56, 0.98)",
        border: "1px solid rgba(139, 92, 246, 0.45)",
        borderRadius: "14px",
        boxShadow: "0 20px 60px rgba(0,0,0,0.55), 0 0 0 1px rgba(139,92,246,0.1)",
        padding: "10px",
        zIndex: 99999,
        backdropFilter: "blur(20px)",
    };

    return (
        <>
            {/* 按钮（留在 Header 内，只把菜单 Portal 出去） */}
            <div ref={btnRef} style={{ position: "relative" }}>
                <button
                    onClick={toggleOpen}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "10px 18px",
                        borderRadius: "30px",
                        background: "rgba(139, 92, 246, 0.18)",
                        border: "1px solid rgba(139, 92, 246, 0.35)",
                        color: "#c4b5fd",
                        fontSize: "14px",
                        cursor: "pointer",
                        transition: "all 0.2s",
                        maxWidth: "220px",
                    }}
                    title="切换学员"
                >
                    <User size={16} />
                    <span
                        style={{
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                        }}
                    >
                        {currentUser || "未登录学员"}
                    </span>
                    <ChevronDown size={14} style={{ opacity: 0.7 }} />
                </button>
            </div>

            {/* 下拉菜单：Portal 到 body 顶层，浮在所有内容之上 */}
            {open && pos && createPortal(
                <div ref={menuRef} style={menuStyle}>
                    {/* 小三角箭头 —— 连接按钮与菜单 */}
                    <div
                        style={{
                            position: "absolute",
                            top: "-6px",
                            right: "24px",
                            width: "10px",
                            height: "10px",
                            background: "rgba(28, 28, 56, 0.98)",
                            transform: "rotate(45deg)",
                            borderLeft: "1px solid rgba(139, 92, 246, 0.45)",
                            borderTop: "1px solid rgba(139, 92, 246, 0.45)",
                        }}
                    />

                    <div
                        style={{
                            fontSize: "12px",
                            color: "#8888bb",
                            padding: "4px 8px 8px",
                            borderBottom: "1px solid rgba(255,255,255,0.08)",
                            marginBottom: "6px",
                        }}
                    >
                        切换学员（每位学员独立学习数据）
                    </div>

                    {/* 已保存学员列表 */}
                    {users.length > 0 ? (
                        <div style={{ maxHeight: "200px", overflowY: "auto" }}>
                            {users.map((u) => {
                                const active = u === currentUser;
                                return (
                                    <div
                                        key={u}
                                        onClick={() => {
                                            onSwitch(u);
                                            setOpen(false);
                                        }}
                                        style={{
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "space-between",
                                            padding: "9px 10px",
                                            borderRadius: "9px",
                                            cursor: "pointer",
                                            background: active
                                                ? "rgba(139, 92, 246, 0.22)"
                                                : "transparent",
                                            color: active ? "#e0e0ff" : "#b8c4ff",
                                            fontSize: "14px",
                                            marginBottom: "2px",
                                            transition: "background 0.15s",
                                        }}
                                        onMouseEnter={(e) => {
                                            if (!active) e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                                        }}
                                        onMouseLeave={(e) => {
                                            if (!active) e.currentTarget.style.background = "transparent";
                                        }}
                                    >
                                        <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                            <User size={14} style={{ opacity: 0.7 }} />
                                            {u}
                                        </span>
                                        {active && <Check size={15} color="#a78bfa" />}
                                    </div>
                                );
                            })}
                        </div>
                    ) : (
                        <div style={{ padding: "8px", color: "#888", fontSize: "13px" }}>
                            暂无其他学员
                        </div>
                    )}

                    {/* 新增学员 */}
                    <div
                        style={{
                            display: "flex",
                            gap: "6px",
                            marginTop: "10px",
                            paddingTop: "10px",
                            borderTop: "1px solid rgba(255,255,255,0.08)",
                        }}
                    >
                        <input
                            value={newName}
                            onChange={(e) => setNewName(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") handleCreate();
                            }}
                            placeholder="输入学号/姓名，新增学员"
                            style={{
                                flex: 1,
                                padding: "8px 10px",
                                borderRadius: "8px",
                                border: "1px solid rgba(139, 92, 246, 0.3)",
                                background: "rgba(255,255,255,0.06)",
                                color: "#e0e0ff",
                                fontSize: "13px",
                                outline: "none",
                                minWidth: 0,
                            }}
                        />
                        <button
                            onClick={handleCreate}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "4px",
                                padding: "8px 12px",
                                borderRadius: "8px",
                                border: "none",
                                background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
                                color: "#fff",
                                fontSize: "13px",
                                cursor: "pointer",
                                whiteSpace: "nowrap",
                            }}
                        >
                            <Plus size={14} />
                            新增
                        </button>
                    </div>
                </div>,
                document.body
            )}
        </>
    );
}

export default UserSwitcher;
