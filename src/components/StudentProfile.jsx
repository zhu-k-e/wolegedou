import React from "react";
import { Brain, GraduationCap, Target } from "lucide-react";

// 中文映射（后端可能返回英文或中文，都兼容）
const levelMap = {
    beginner: "初级", intermediate: "中级", advanced: "高级",
    "入门": "入门", "初级": "初级", "中级": "中级", "高级": "高级",
};
const backgroundMap = {
    cs_student: "计算机方向学生", developer: "开发人员",
    researcher: "科研人员", product_manager: "产品方向人员",
    "理科_无编程": "理科/无编程基础",
    "有Python基础": "有Python基础",
    "有ML基础": "有ML基础",
    "文科": "文科",
};
const goalMap = {
    learn_basics: "基础学习", build_project: "项目实践",
    deploy: "项目部署", debug: "问题调试", research: "科研探索",
    "深入理解原理": "深入理解原理",
};

function StudentProfile({ profile }) {
    if (!profile) return null;

    // 优先用映射表，映射不到就直接显示后端原始值（后端可能直接返回中文）
    const level = levelMap[profile.knowledge_level] || profile.knowledge_level || "未知";
    const bg = backgroundMap[profile.background] || profile.background || "未知";
    const goal = goalMap[profile.current_goal] || profile.current_goal || "未知";

    return (
        <div className="info-card">
            <div className="card-title">
                <Brain size={24} />
                <h2>学情画像分析</h2>
            </div>

            <div className="profile-grid">
                <div className="profile-item">
                    <h4>知识水平</h4>
                    <p>{level}</p>
                </div>
                <div className="profile-item">
                    <h4>学习背景</h4>
                    <p>{bg}</p>
                </div>
                <div className="profile-item">
                    <h4>学习目标</h4>
                    <p>{goal}</p>
                </div>
            </div>

            <div className="ai-tip">
                系统通过 AI 学情诊断模块自动分析学生状态，无需手动填写个人信息。
            </div>
        </div>
    );
}

export default StudentProfile;
