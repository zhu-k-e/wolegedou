import React, {
    useState,
    useEffect
} from "react";


import {

    Rocket,

    Brain,

    Target,

    Sparkles,

    BookOpen,

    GraduationCap,

    ChevronDown,

    ChevronUp,

    Zap,

    ClipboardList

} from "lucide-react";



import {

    askQuestion,
    getTaskStatus

} from "../api/api";





// ===========================
// 安全写入 localStorage
// 容量满（QuotaExceededError，5MB 上限）时 setItem 会抛错，
// 若在 try 块外抛错会静默中断流程（表现为"按钮点了没反应"）。
// 这里：写入失败时自动压缩历史数据释放空间后重试一次。
// ===========================
function safeSetItem(key, value) {
    try {
        localStorage.setItem(key, value);
        return true;
    } catch (e) {
        console.warn(`localStorage 写入失败(${key})：`, e);
        try {
            // 压缩 questionHistory：只留最近 15 条，超长 answer 置为占位对象
            const rawQh = localStorage.getItem("questionHistory");
            const qh = rawQh ? JSON.parse(rawQh) : [];
            const slim = (Array.isArray(qh) ? qh : []).slice(-15).map(it => {
                if (it && it.answer && typeof it.answer === "object") {
                    it.answer = { trimmed: true };
                }
                return it;
            });
            localStorage.setItem("questionHistory", JSON.stringify(slim));
            // 压缩 sessionIds：只留最近 20 个会话
            const rawSids = localStorage.getItem("sessionIds");
            const sids = rawSids ? JSON.parse(rawSids) : [];
            if (Array.isArray(sids) && sids.length > 20) {
                localStorage.setItem("sessionIds", JSON.stringify(sids.slice(-20)));
            }
            // 重试原写入
            localStorage.setItem(key, value);
            console.warn("已自动压缩历史记录并重试写入成功");
            return true;
        } catch (e2) {
            console.warn("压缩后仍无法写入 localStorage:", e2);
            return false;
        }
    }
}

// ===========================
// 学情画像预设用例（严格对齐 data/io_examples/bm_TC-XXX_io.json 的 input_profile 真值）
// 录制演示视频时直接点这三个按钮，字段值与提交的 I/O 示例文档逐字一致
// ===========================
const PROFILE_PRESETS = [
    {
        label: "TC-001 入门·CS学生",
        desc: "cs_student / LLM基础 / 深入理解原理",
        data: {
            knowledge_level: "入门",
            background: "cs_student",
            domain_hint: ["LLM基础"],
            question_type: "概念理解",
            current_goal: "深入理解原理",
            complexity_estimate: "单领域",
            intent_type: "generation"
        }
    },
    {
        label: "TC-020 中级·开发者",
        desc: "developer / Agent框架 / 项目落地",
        data: {
            knowledge_level: "中级",
            background: "developer",
            domain_hint: ["Agent框架"],
            question_type: "概念理解",
            current_goal: "项目落地",
            complexity_estimate: "单领域",
            intent_type: "generation"
        }
    },
    {
        label: "TC-048 进阶·开发者",
        desc: "developer / Agent框架 / 项目落地",
        data: {
            knowledge_level: "进阶",
            background: "developer",
            domain_hint: ["Agent框架"],
            question_type: "操作步骤",
            current_goal: "项目落地",
            complexity_estimate: "单领域",
            intent_type: "generation"
        }
    }
];

// ===========================
// 各字段的枚举选项（严格匹配后端要求）
// ===========================
const LEVEL_OPTIONS    = ["入门", "中级", "进阶"];
const BACKGROUND_OPTIONS = [
    "文科",
    "理科_无编程",
    "有Python基础",
    "有ML基础",
    { value: "cs_student", label: "CS学生" },
    { value: "developer", label: "开发者" }
];
const GOAL_OPTIONS      = ["快速上手应用", "深入理解原理", "项目落地", "算法研究"];
const QTYPE_OPTIONS     = ["概念理解", "操作步骤", "调试排错", "架构设计", "全链路规划"];
const COMPLEXITY_OPTIONS = ["单领域", "跨领域", "全链路"];
const INTENT_OPTIONS    = [
    { value: "generation",    label: "内容生成" },
    { value: "navigation",   label: "路径导航" },
    { value: "clarification", label: "问题澄清" }
];

// 理论测试成绩科目枚举（后端建议取自 DOMAIN_HINT_ENUMS，便于与学习分析关联）
const TEST_TOPIC_OPTIONS = [
    "LLM基础", "Prompt工程", "LangChain", "RAG",
    "HuggingFace", "模型微调", "向量数据库", "Agent框架", "项目部署"
];





function TaskInput({

    onTaskStart,

    onFSMUpdate,

    onTaskComplete,

    onPageReady,

    hasData,

    sessionId,

    currentUser,

    resourcesAvailable,

    pendingQuestion,

    onPendingConsumed

}){



// ===========================
// 学生问题
// ===========================

const [question,setQuestion]=useState("");

// 记录用户点了哪个生成按钮（"lecture" 讲义 / "quiz" 测试题），
// 任务完成后通过 onPageReady 回调让 App 自动打开对应全屏页面
const [pendingPage,setPendingPage]=useState(null);




// ===========================
// 学习目标（值已对齐后端 current_goal 枚举）
// ===========================
const [goal,setGoal]=useState("快速上手应用");




// ===========================
// 资源需求
// ===========================

const [resources,setResources]=useState([

"lecture",

"guide",

"quiz"

]);




// ===========================
// 学情画像（新：对应后端 profile 字段）
// 默认全部为空字符串 = 不传 = 后端自动诊断
// ===========================

const [showProfile, setShowProfile] = useState(false);

const [profile, setProfile] = useState({
    knowledge_level: "",
    background: "",
    current_goal: "",
    question_type: "",
    domain_hint: "",        // 文本输入，逗号分隔，提交时转数组
    complexity_estimate: "",
    intent_type: ""
});

// 理论测试成绩（选填，对应 profile.test_results）
// 每条 { topic: "", score: "", date: "" }，score 为 0-100 的数字，提交时 ÷100
const [testResults, setTestResults] = useState([]);
const [showTestResults, setShowTestResults] = useState(false);

// 添加一条空成绩
function addTestResult() {
    setTestResults(prev => [...prev, { topic: "", score: "", date: "" }]);
}

// 更新某条成绩的某个字段
function updateTestResult(index, field, value) {
    setTestResults(prev => prev.map((item, i) => i === index ? { ...item, [field]: value } : item));
}

// 删除某条成绩
function removeTestResult(index) {
    setTestResults(prev => prev.filter((_, i) => i !== index));
}

// 更新 profile 单个字段
function updateProfile(field, value) {
    setProfile(prev => ({ ...prev, [field]: value }));
}

// 加载预设用例
function loadPreset(presetData) {
    setProfile({
        knowledge_level: presetData.knowledge_level || "",
        background: presetData.background || "",
        current_goal: presetData.current_goal || "",
        question_type: presetData.question_type || "",
        domain_hint: (presetData.domain_hint || []).join(","),
        complexity_estimate: presetData.complexity_estimate || "",
        intent_type: presetData.intent_type || ""
    });
    // 加载预设的测试成绩（score 从 0.0-1.0 转回 0-100 用于输入框显示）
    const presetTests = presetData.test_results || [];
    setTestResults(presetTests.map(t => ({
        topic: t.topic || "",
        score: t.score != null ? Math.round(t.score * 100) : "",
        date: t.date || ""
    })));
    setShowTestResults(presetTests.length > 0);
    setShowProfile(true);
}

// 清空画像
function clearProfile() {
    setProfile({
        knowledge_level: "",
        background: "",
        current_goal: "",
        question_type: "",
        domain_hint: "",
        complexity_estimate: "",
        intent_type: ""
    });
    setTestResults([]);
    setShowTestResults(false);
}




// 加载状态

const [loading,setLoading]=useState(false);




// session 由多学员身份层统一管理（multi_tenant_isolation_spec FR-1/FR-3）：
//  - props.sessionId = 当前学员已绑定的 session（未提问过则为空字符串）
//  - 首次提问时在 createTask 中生成新 session，经 onTaskStart 回传由 App 绑定给当前学员
//  - 后续提问复用同一 session，保证该学员热力图/报告跨对话累积









// ===========================
// 修改资源选择
// ===========================


function toggleResource(type){



if(resources.includes(type)){


setResources(

resources.filter(

item=>item!==type

)

)


}

else{


setResources(

[

...resources,
type

]

)


}



}








// ===========================
// 一键生成全部学习资源（讲义 + 实操指南 + 测试题）
// 生成流程 100% 完成后，大按钮自动分散成三个小按钮
//（讲义 / 测试题 / 实操指南），点击分别打开对应全屏页
// ===========================
async function handleGenerateAll(){
  setPendingPage(null);
  // 一键生成 = 全套资源，同步勾选 UI 复选框保持一致
  setResources(["lecture", "guide", "quiz"]);
  await createTask(["lecture", "guide", "quiz"]);
}

// ===========================
// 创建学习任务
// ===========================


async function createTask(resList, overrideQuestion){
  const qText = (overrideQuestion || question || "").trim();
  if(!qText){
    alert("请输入你的学习问题");
    return;
  }
  // 多租户：复用当前学员已绑定的 session（跨对话累积热力图）；
  // 首次提问（sessionId 为空）时生成新会话，由 App 在 onTaskStart 中绑定给当前学员
  const newSid = sessionId || "session_" + Date.now();
  setLoading(true);
  try{
    // 构建请求体（resList 由调用方指定；默认使用当前勾选的资源）
    const sendData = {
      question: qText,
      goal: goal,
      resources: (resList || resources).join(","),
      session_id: newSid,
      history: []
    };

    // 构建学情画像信息（用于拼接到 question 文本，不作为独立 profile 字段传）
    // 原因：后端收到 profile 字段时会跳过画像落库，导致 /api/report 永久 404。
    // 改为将学情信息融入 question 文本，让后端自主诊断并正常落库。
    let profileData = null;
    if (showProfile) {
      profileData = {};
      if (profile.knowledge_level)     profileData.knowledge_level = profile.knowledge_level;
      if (profile.background)         profileData.background = profile.background;
      if (profile.current_goal)       profileData.current_goal = profile.current_goal;
      if (profile.question_type)      profileData.question_type = profile.question_type;
      if (profile.domain_hint && profile.domain_hint.trim()) {
          profileData.domain_hint = profile.domain_hint
              .split(/[,，]/)
              .map(s => s.trim())
              .filter(s => s);
      }
      if (profile.complexity_estimate) profileData.complexity_estimate = profile.complexity_estimate;
      if (profile.intent_type)         profileData.intent_type = profile.intent_type;

      // 理论测试成绩：score 从 0-100 转为 0.0-1.0，过滤掉不完整的条目
      if (testResults.length > 0) {
          const validTests = testResults
              .filter(t => t.topic && t.topic.trim() && t.score !== "" && t.date)
              .map(t => ({
                  topic: t.topic.trim(),
                  score: Math.min(1, Math.max(0, Number(t.score) / 100)),
                  date: t.date
              }))
              .filter(t => !isNaN(t.score) && t.score >= 0 && t.score <= 1);
          if (validTests.length > 0) {
              profileData.test_results = validTests;
          }
      }

      // 构建学情上下文，拼接到 question 前面
      if (Object.keys(profileData).length > 0) {
          const parts = [];
          if (profileData.knowledge_level)   parts.push(`知识水平: ${profileData.knowledge_level}`);
          if (profileData.background)        parts.push(`学科背景: ${profileData.background}`);
          if (profileData.current_goal)      parts.push(`学习目标: ${profileData.current_goal}`);
          if (profileData.question_type)     parts.push(`问题类型: ${profileData.question_type}`);
          if (profileData.domain_hint?.length) parts.push(`关注领域: ${profileData.domain_hint.join(", ")}`);
          if (profileData.complexity_estimate) parts.push(`复杂度: ${profileData.complexity_estimate}`);
          if (profileData.intent_type)       parts.push(`意图: ${profileData.intent_type}`);

          let context = `【学情背景】${parts.join(" | ")}`;

          // 拼接理论测试成绩
          if (profileData.test_results?.length) {
              const scores = profileData.test_results
                  .map(t => `${t.topic}: ${Math.round(t.score * 100)}分(${t.date})`)
                  .join(", ");
              context += `\n【理论测试成绩】${scores}`;
          }

          sendData.question = `${context}\n\n${qText}`;
      }
    }

    console.log("提交请求体:", JSON.stringify(sendData, null, 2));

    // 1. 提交任务，立即获取 task_id
    const response = await askQuestion(sendData);
    if (!response || !response.task_id) {
      alert("后端未返回 task_id，请检查后端是否正常运行");
      setLoading(false);
      return;
    }
    const taskId = response.task_id;
    console.log("任务已提交，task_id:", taskId);

    // 保存提问历史到 localStorage
    try {
      const stored = localStorage.getItem("questionHistory");
      const qHistory = stored ? JSON.parse(stored) : [];
      qHistory.push({
        question: qText,
        goal: goal,
        time: new Date().toISOString(),
        sessionId: newSid,
        taskId: taskId,
        userId: currentUser,   // 多租户：历史记录按学员隔离（FR-3）
        profile: showProfile ? profile : undefined
      });
      if (qHistory.length > 100) {
        qHistory.splice(0, qHistory.length - 100);
      }
      localStorage.setItem("questionHistory", JSON.stringify(qHistory));
      window.dispatchEvent(new Event("questionSubmitted"));
    } catch(e) {
      console.warn("保存提问历史失败:", e);
    }

    // 2. 通知父组件任务已启动
    // 注意：必须传 newSid（局部变量）——App 用它 setSessionId 并绑定给当前学员
    if (onTaskStart) {
      onTaskStart({
        taskId: taskId,
        sessionId: newSid,
        // 保留前端填写的画像给 HistoryPanel 做兜底（后端报告正常返回后自动替换）
        profile: profileData || null
      });
    }

    // 3. 轮询获取任务状态，每 2 秒查一次
    // 保护机制：
    //  - polling 标志：上一轮请求未返回时跳过本轮，避免并发请求堆积（axios 拦截器
    //    对网关错误会重试 3 次、最长约 9 秒，2 秒一轮会造成多请求叠加）
    //  - pollFailCount：连续失败超过上限则放弃轮询并恢复按钮，
    //    避免按钮永久卡在"AI正在分析中..."（此前轮询失败分支不重置 loading 导致按钮按不动）
    let pollFailCount = 0;
    let polling = false;
    const MAX_POLL_FAILS = 10;

    const pollTimer = setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const res = await getTaskStatus(taskId);
        console.log("轮询任务结果：", res);

        if (onFSMUpdate) onFSMUpdate(res);

        const stateUpper = (res.state || "").toUpperCase();
        if (stateUpper === "COMPLETE" || stateUpper === "COMPLETED" || stateUpper === "DONE" || stateUpper === "SUCCESS") {
          clearInterval(pollTimer);
          console.log("任务完成，停止轮询。");
          const fullData = res.result || res;
          console.log("传给 onTaskComplete 的数据：", fullData);
          if (onTaskComplete) {
            onTaskComplete(fullData);
          }
          // 用户点的是"生成讲义/生成测试题"按钮时，生成完成后自动打开对应全屏页面
          if (pendingPage && onPageReady) {
            onPageReady(pendingPage);
            setPendingPage(null);
          }
          // 把完整回答数据存入 localStorage
          try {
            const stored = localStorage.getItem("questionHistory");
            const qHistory = stored ? JSON.parse(stored) : [];
            for (let i = qHistory.length - 1; i >= 0; i--) {
              if (qHistory[i].taskId === taskId) {
                qHistory[i].answer = JSON.parse(JSON.stringify(fullData, (key, val) => {
                  if (typeof val === "string" && val.length > 800) {
                    return val.substring(0, 800) + "...(已截断)";
                  }
                  return val;
                }));
                break;
              }
            }
            localStorage.setItem("questionHistory", JSON.stringify(qHistory));
            window.dispatchEvent(new Event("questionSubmitted"));
          } catch(e) {
            console.warn("保存回答数据到历史记录失败:", e);
          }

          // 把 session_id 加到本地列表，供 HistoryPanel 加载所有历史报告
          // 注意：用 newSid（本次新建的会话），不能读 state 旧值
          try {
            const storedSids = localStorage.getItem("sessionIds");
            const sidList = storedSids ? JSON.parse(storedSids) : [];
            if (!sidList.includes(newSid)) {
              sidList.push(newSid);
              localStorage.setItem("sessionIds", JSON.stringify(sidList));
            }
          } catch(e) {
            console.warn("保存 session_id 列表失败:", e);
          }

          setLoading(false);
        } else if (stateUpper === "FAILED" || stateUpper === "ERROR") {
          clearInterval(pollTimer);
          console.error("任务失败：", res);
          alert("任务处理失败：" + (res.error || res.message || "未知错误"));
          setLoading(false);
        }
      } catch (pollError) {
        console.error("轮询出错：", pollError);
        pollFailCount++;
        if (pollFailCount >= MAX_POLL_FAILS) {
          clearInterval(pollTimer);
          setLoading(false);
          alert("与后端连接中断，未能获取任务结果。请刷新页面后重试。");
        }
      } finally {
        polling = false;
      }
    }, 2000);

  }catch(error){
    console.error("请求报错：", error);
    let errorMsg = "接口请求失败，无法连接后端";
    if (error?.response?.status === 502 || error?.response?.status === 503 || error?.response?.status === 504) {
      errorMsg = "后端服务暂时不可用（网关错误），请稍后重试或联系后端同学检查服务状态";
    } else if (error?.response?.status === 400) {
      errorMsg = "请求参数错误（400）：" + (error?.response?.data?.detail || error?.response?.data?.message || "请检查输入内容");
    } else if (error?.code === "ECONNABORTED" || error?.message?.includes("timeout")) {
      errorMsg = "请求超时，后端响应太慢，请稍后重试";
    } else if (error?.message) {
      errorMsg = error.message;
    }
    alert(errorMsg);
    setLoading(false);
  }
}


// ===========================
// 启发式追问注入：Quiz 里点击追问后，App 把问题文本传进来
// 填入输入框并自动触发一轮全套生成（讲义+实操指南+测试题）
// ===========================
useEffect(() => {
  if (pendingQuestion && pendingQuestion.trim()) {
    const q = pendingQuestion.trim();
    setQuestion(q);
    setResources(["lecture", "guide", "quiz"]);
    // 稍等一帧让输入框同步更新，再触发生成
    const t = setTimeout(() => {
      createTask(["lecture", "guide", "quiz"], q);
      if (onPendingConsumed) onPendingConsumed();
    }, 50);
    return () => clearTimeout(t);
  }
}, [pendingQuestion]);








// ===========================
// 通用：渲染选项按钮组
// ===========================
function renderOptionGroup(options, selectedValue, onSelect) {
    return (
        <div className="option-group" style={{ flexWrap: "wrap" }}>
            {options.map(opt => {
                const value = typeof opt === "object" ? opt.value : opt;
                const label = typeof opt === "object" ? opt.label : opt;
                return (
                    <button
                        key={value}
                        className={selectedValue === value ? "selected" : ""}
                        onClick={() => {
                            if (selectedValue === value) {
                                // 再次点击取消选择
                                onSelect("");
                            } else {
                                onSelect(value);
                            }
                        }}
                    >
                        {label}
                    </button>
                );
            })}
        </div>
    );
}





return (

<div className="task-card">




{/* 标题 */}

<div className="card-title">


<Sparkles size={26}/>


<h2>

创建学习任务

</h2>


</div>




<p className="description">


请输入你的学习问题，
系统将通过学情诊断 Agent
自动分析需求，并选择最佳智能体完成学习任务。


</p>








{/* 问题输入 */}

<div className="input-area">


<label>


<Brain size={18}/>


学习问题


</label>




<textarea


placeholder=

"例如:什么是RAG?如何搭建知识库问答系统?"


value={question}


onChange={

e=>

setQuestion(e.target.value)

}


/>



</div>




{/* 学习目标 */}

<div className="input-area">


<label>


<Target size={18}/>


学习目标


</label>




<div className="option-group">


<button

className={

goal==="快速上手应用"

?

"selected"

:

""

}

onClick={()=>setGoal(

"快速上手应用"

)}

>

快速上手应用

</button>




<button

className={

goal==="深入理解原理"

?

"selected"

:

""

}

onClick={()=>setGoal(

"深入理解原理"

)}

>

深入理解原理

</button>




<button

className={

goal==="算法研究"

?

"selected"

:

""

}

onClick={()=>setGoal(

"算法研究"

)}

>

算法研究

</button>




<button

className={

goal==="项目落地"

?

"selected"

:

""

}

onClick={()=>setGoal(

"项目落地"

)}

>

项目落地

</button>


</div>


</div>




{/* 资源需求 */}

<div className="input-area">


<label>


<BookOpen size={18}/>


学习资源需求


</label>




<div className="resource-list">


<label>


<input

type="checkbox"

checked={

resources.includes(

"lecture"

)

}

onChange={

()=>toggleResource(

"lecture"

)

}

/>

学习讲义


</label>






<label>


<input

type="checkbox"

checked={

resources.includes(

"guide"

)

}

onChange={

()=>toggleResource(

"guide"

)

}

/>

实操指南


</label>




<label>


<input

type="checkbox"

checked={

resources.includes(

"quiz"

)

}

onChange={

()=>toggleResource(

"quiz"

)

}

/>

测试题


</label>


</div>


</div>




{/* =========================== */}
{/* 学情画像（可选 — 手动填写或选择预设用例） */}
{/* 不填则后端自动诊断；填了后端使用传入的画像 */}
{/* =========================== */}
<div className="input-area">

    <label
        style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            cursor: "pointer",
            userSelect: "none"
        }}
        onClick={() => setShowProfile(!showProfile)}
    >
        <input
            type="checkbox"
            checked={showProfile}
            onChange={(e) => setShowProfile(e.target.checked)}
            style={{ accentColor: "#8b5cf6" }}
        />
        <GraduationCap size={18} />
        <span>学情画像（选填）</span>
        {showProfile
            ? <ChevronUp size={16} style={{ marginLeft: "auto" }} />
            : <ChevronDown size={16} style={{ marginLeft: "auto" }} />
        }
    </label>

    <p style={{
        fontSize: "13px",
        color: "#8893b8",
        marginTop: "6px",
        marginBottom: "0"
    }}>
        {showProfile
            ? "填写后系统将使用你提供的画像（不再自动诊断）。不填的字段后端会自动补全。"
            : "不勾选则后端自动诊断学情。勾选后可手动填写或选择下方预设用例。"
        }
    </p>
</div>


{/* 学情画像展开区域 */}
{showProfile && (

<div style={{
    marginTop: "16px",
    padding: "20px",
    borderRadius: "16px",
    background: "rgba(139,92,246,0.05)",
    border: "1px solid rgba(139,92,246,0.15)"
}}>


    {/* 预设用例快捷按钮 */}
    <div style={{ marginBottom: "20px" }}>
        <div style={{
            fontSize: "14px",
            color: "#b8c4ff",
            marginBottom: "10px",
            display: "flex",
            alignItems: "center",
            gap: "6px"
        }}>
            <Zap size={14} />
            <span>赛题学情用例（≥3 组，点击快速加载）</span>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            {PROFILE_PRESETS.map((preset, idx) => (
                <button
                    key={idx}
                    onClick={() => loadPreset(preset.data)}
                    style={{
                        padding: "8px 16px",
                        borderRadius: "12px",
                        border: "1px solid rgba(139,92,246,0.3)",
                        background: "rgba(139,92,246,0.1)",
                        color: "#c8d0ff",
                        fontSize: "13px",
                        cursor: "pointer",
                        transition: "all 0.2s"
                    }}
                    onMouseEnter={(e) => {
                        e.target.style.background = "rgba(139,92,246,0.2)";
                        e.target.style.borderColor = "rgba(139,92,246,0.5)";
                    }}
                    onMouseLeave={(e) => {
                        e.target.style.background = "rgba(139,92,246,0.1)";
                        e.target.style.borderColor = "rgba(139,92,246,0.3)";
                    }}
                >
                    <div style={{ fontWeight: "600" }}>{preset.label}</div>
                    <div style={{ fontSize: "11px", color: "#8893b8", marginTop: "2px" }}>
                        {preset.desc}
                    </div>
                </button>
            ))}
            <button
                onClick={clearProfile}
                style={{
                    padding: "8px 16px",
                    borderRadius: "12px",
                    border: "1px solid rgba(255,255,255,0.1)",
                    background: "transparent",
                    color: "#8893b8",
                    fontSize: "13px",
                    cursor: "pointer",
                    transition: "all 0.2s"
                }}
                onMouseEnter={(e) => {
                    e.target.style.color = "#f87171";
                    e.target.style.borderColor = "rgba(239,68,68,0.3)";
                }}
                onMouseLeave={(e) => {
                    e.target.style.color = "#8893b8";
                    e.target.style.borderColor = "rgba(255,255,255,0.1)";
                }}
            >
                清空画像
            </button>
        </div>
    </div>


    {/* 知识水平 */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>知识水平</span>
        </label>
        {renderOptionGroup(LEVEL_OPTIONS, profile.knowledge_level, (v) => updateProfile("knowledge_level", v))}
    </div>


    {/* 学科背景 */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>学科背景</span>
        </label>
        {renderOptionGroup(BACKGROUND_OPTIONS, profile.background, (v) => updateProfile("background", v))}
    </div>


    {/* 学习目标（profile.current_goal，与旧 goal 字段不同） */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>学习目标（画像）</span>
        </label>
        {renderOptionGroup(GOAL_OPTIONS, profile.current_goal, (v) => updateProfile("current_goal", v))}
    </div>


    {/* 问题类型 */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>问题类型</span>
        </label>
        {renderOptionGroup(QTYPE_OPTIONS, profile.question_type, (v) => updateProfile("question_type", v))}
    </div>


    {/* 复杂度估计 */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>复杂度估计</span>
        </label>
        {renderOptionGroup(COMPLEXITY_OPTIONS, profile.complexity_estimate, (v) => updateProfile("complexity_estimate", v))}
    </div>


    {/* 意图类型 */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>意图类型</span>
        </label>
        {renderOptionGroup(INTENT_OPTIONS, profile.intent_type, (v) => updateProfile("intent_type", v))}
    </div>


    {/* 领域关键词 */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0" }}>
        <label>
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>
                领域关键词 <span style={{ fontSize: "12px", color: "#8893b8" }}>（可选，逗号分隔，如：模型微调,提示工程）</span>
            </span>
        </label>
        <input
            type="text"
            placeholder="如：模型微调,提示工程,RAG"
            value={profile.domain_hint}
            onChange={(e) => updateProfile("domain_hint", e.target.value)}
            style={{
                width: "100%",
                marginTop: "8px",
                padding: "10px 14px",
                borderRadius: "10px",
                border: "1px solid rgba(255,255,255,0.15)",
                background: "rgba(255,255,255,0.05)",
                color: "#e0e0ff",
                fontSize: "14px",
                outline: "none",
                boxSizing: "border-box"
            }}
        />
    </div>


    {/* =========================== */}
    {/* 理论测试成绩（选填） */}
    {/* 对应 profile.test_results，score 提交时 ÷100 */}
    {/* =========================== */}
    <div className="input-area" style={{ background: "transparent", border: "none", padding: "0", marginTop: "16px" }}>
        <label
            style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                cursor: "pointer",
                userSelect: "none"
            }}
            onClick={() => setShowTestResults(!showTestResults)}
        >
            <input
                type="checkbox"
                checked={showTestResults}
                onChange={(e) => {
                    setShowTestResults(e.target.checked);
                    if (e.target.checked && testResults.length === 0) {
                        addTestResult();
                    }
                }}
                style={{ accentColor: "#8b5cf6" }}
                onClick={(e) => e.stopPropagation()}
            />
            <GraduationCap size={18} />
            <span style={{ fontSize: "14px", color: "#c8d0ff" }}>理论测试成绩（选填）</span>
            {showTestResults
                ? <ChevronUp size={16} style={{ marginLeft: "auto" }} />
                : <ChevronDown size={16} style={{ marginLeft: "auto" }} />
            }
        </label>
        <p style={{
            fontSize: "12px",
            color: "#8893b8",
            marginTop: "6px",
            marginBottom: "0"
        }}>
            填入已有测试成绩，系统将整合到学情画像中。分数 0–100，提交时自动转换为 0.0–1.0。
        </p>
    </div>

    {/* 测试成绩展开区域 */}
    {showTestResults && (
        <div style={{ marginTop: "12px" }}>
            <datalist id="test-topic-options">
                {TEST_TOPIC_OPTIONS.map(opt => (
                    <option key={opt} value={opt} />
                ))}
            </datalist>

            {testResults.map((test, idx) => (
                <div key={idx} style={{
                    display: "flex",
                    gap: "8px",
                    marginBottom: "8px",
                    alignItems: "center",
                    flexWrap: "wrap"
                }}>
                    {/* 科目 */}
                    <input
                        type="text"
                        list="test-topic-options"
                        placeholder="科目（如：RAG）"
                        value={test.topic}
                        onChange={(e) => updateTestResult(idx, "topic", e.target.value)}
                        style={{
                            flex: "1",
                            minWidth: "120px",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            border: "1px solid rgba(255,255,255,0.15)",
                            background: "rgba(255,255,255,0.05)",
                            color: "#e0e0ff",
                            fontSize: "13px",
                            outline: "none",
                            boxSizing: "border-box"
                        }}
                    />
                    {/* 分数 0-100 */}
                    <input
                        type="number"
                        min="0"
                        max="100"
                        placeholder="分数 0-100"
                        value={test.score}
                        onChange={(e) => updateTestResult(idx, "score", e.target.value)}
                        style={{
                            width: "110px",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            border: "1px solid rgba(255,255,255,0.15)",
                            background: "rgba(255,255,255,0.05)",
                            color: "#e0e0ff",
                            fontSize: "13px",
                            outline: "none",
                            boxSizing: "border-box"
                        }}
                    />
                    {/* 日期 */}
                    <input
                        type="date"
                        value={test.date}
                        onChange={(e) => updateTestResult(idx, "date", e.target.value)}
                        style={{
                            width: "150px",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            border: "1px solid rgba(255,255,255,0.15)",
                            background: "rgba(255,255,255,0.05)",
                            color: "#e0e0ff",
                            fontSize: "13px",
                            outline: "none",
                            boxSizing: "border-box",
                            colorScheme: "dark"
                        }}
                    />
                    {/* 删除按钮 */}
                    <button
                        onClick={() => removeTestResult(idx)}
                        style={{
                            width: "32px",
                            height: "32px",
                            borderRadius: "8px",
                            border: "1px solid rgba(248,113,113,0.25)",
                            background: "rgba(248,113,113,0.08)",
                            color: "#f87171",
                            fontSize: "16px",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                            transition: "all 0.2s"
                        }}
                        onMouseEnter={(e) => {
                            e.target.style.background = "rgba(248,113,113,0.2)";
                        }}
                        onMouseLeave={(e) => {
                            e.target.style.background = "rgba(248,113,113,0.08)";
                        }}
                    >
                        ×
                    </button>
                </div>
            ))}

            {/* 添加一条成绩 */}
            <button
                onClick={addTestResult}
                style={{
                    padding: "8px 16px",
                    borderRadius: "10px",
                    border: "1px dashed rgba(139,92,246,0.3)",
                    background: "transparent",
                    color: "#c4b5fd",
                    fontSize: "13px",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    transition: "all 0.2s"
                }}
                onMouseEnter={(e) => {
                    e.target.style.background = "rgba(139,92,246,0.1)";
                    e.target.style.borderColor = "rgba(139,92,246,0.5)";
                }}
                onMouseLeave={(e) => {
                    e.target.style.background = "transparent";
                    e.target.style.borderColor = "rgba(139,92,246,0.3)";
                }}
            >
                + 添加一条成绩
            </button>
        </div>
    )}

</div>

)}




{/* =========================== */}
{/* 生成按钮：未生成 → 一个大按钮「生成个性学习资源」 */}
{/* 生成流程 100% 完成后 → 大按钮自动分散成三个小按钮（讲义 / 测试题 / 实操指南） */}
{/* =========================== */}
{!hasData ? (

<button

className="start-button"

onClick={handleGenerateAll}

disabled={loading}

style={{
    width: "100%",
    minHeight: "54px",
    fontSize: "17px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "10px"
}}

>
<Rocket size={22}/>


{


loading
?
"AI正在分析中..."
:
"生成个性学习资源"


}
</button>

) : (

<div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>

<button

className="start-button"

onClick={() => onPageReady && onPageReady("lecture")}

disabled={!resourcesAvailable?.lecture}

style={{
    flex: 1,
    minWidth: "140px",
    opacity: resourcesAvailable?.lecture ? 1 : 0.5,
    cursor: resourcesAvailable?.lecture ? "pointer" : "not-allowed"
}}

>
<BookOpen size={20}/>

讲义
</button>

<button

className="start-button"

onClick={() => onPageReady && onPageReady("quiz")}

disabled={!resourcesAvailable?.quiz}

style={{
    flex: 1,
    minWidth: "140px",
    opacity: resourcesAvailable?.quiz ? 1 : 0.5,
    cursor: resourcesAvailable?.quiz ? "pointer" : "not-allowed"
}}

>
<ClipboardList size={20}/>

测试题
</button>

<button

className="start-button"

onClick={() => onPageReady && onPageReady("guide")}

disabled={!resourcesAvailable?.guide}

style={{
    flex: 1,
    minWidth: "140px",
    opacity: resourcesAvailable?.guide ? 1 : 0.5,
    cursor: resourcesAvailable?.guide ? "pointer" : "not-allowed"
}}

>
<GraduationCap size={20}/>

实操指南
</button>

</div>

)}



{/* 流程提示 */}

<div className="flow-tip">


系统流程：


<span>

学情诊断 → Agent调度 → 内容生成 → 审核裁判 → 资源输出


</span>


</div>




</div>


)


}


export default TaskInput;
