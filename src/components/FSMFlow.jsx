import React from "react";

import {

CheckCircle,

Circle

} from "lucide-react";



const states=[

{
key:"PROFILING",
name:"学情诊断",
desc:"正在分析你的学习背景和需求..."
},

{
key:"DISPATCHING",
name:"Agent调度",
desc:"正在选择最适合的智能体..."
},

{
key:"GENERATING",
name:"内容生成",
desc:"正在生成学习内容，这是最耗时的步骤，请耐心等待..."
},

{
key:"REVIEWING",
name:"质量审核",
desc:"正在审核内容质量..."
},

{
key:"FOCUSING",
name:"结果聚合",
desc:"正在聚合关键信息..."
},

{
key:"JUDGING",
name:"裁判评估",
desc:"正在多维度评估学习效果..."
},

{
key:"FORMATTING",
name:"资源整理",
desc:"正在整理最终资源包..."
},

{
key:"COMPLETE",
name:"任务完成",
desc:"全部完成！"
}

];



// PENDING 是任务刚提交、尚未进入 FSM 流程的过渡状态
const pendingDesc = "任务已提交，等待启动...";





function FSMFlow({

currentState

}){



const currentIndex=

states.findIndex(

item=>

item.key===currentState

);



const isActive = currentState && currentState !== "";



// 计算进度百分比
let progressPercent = 0;
if (currentState === "COMPLETE") {
  progressPercent = 100;
} else if (currentState === "PENDING") {
  progressPercent = 5;
} else if (currentIndex >= 0) {
  progressPercent = Math.round(((currentIndex + 1) / states.length) * 100);
}

// 当前状态描述文案
const currentDesc = currentState === "PENDING"
  ? pendingDesc
  : (currentIndex >= 0 ? states[currentIndex].desc : "");





return (

<div className="info-card">



<div className="card-title">


<h2>

⚙️ 智能协同流程

</h2>


</div>



{/* 进度条 + 状态描述文案 */}
{isActive && (
  <div style={{ marginBottom: "20px" }}>
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      marginBottom: "8px"
    }}>
      <span style={{ color: "#b8c4ff", fontSize: "14px" }}>
        {currentDesc}
      </span>
      <span style={{ color: "#b8c4ff", fontSize: "14px", fontWeight: "bold" }}>
        {progressPercent}%
      </span>
    </div>
    <div style={{
      width: "100%",
      height: "8px",
      borderRadius: "4px",
      background: "rgba(255,255,255,0.1)",
      overflow: "hidden"
    }}>
      <div style={{
        height: "100%",
        width: progressPercent + "%",
        borderRadius: "4px",
        background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
        transition: "width 0.5s ease"
      }} />
    </div>
  </div>
)}



<div className="fsm-container">

{

states.map((item,index)=>(



<div

className={
`
fsm-item
${
index<=currentIndex
?
"active"
:
""
}
`
}

key={item.key}

>


{
index<=currentIndex
?
<CheckCircle size={22}/>
:
<Circle size={22}/>
}


<div>


<h4>

{item.name}

</h4>


<span>

{item.key}

</span>


</div>



</div>


))

}


</div>



</div>


)



}



export default FSMFlow;
