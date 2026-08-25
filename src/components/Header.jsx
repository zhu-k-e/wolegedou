import React from "react";


import {

Cpu,

Activity

} from "lucide-react";



function Header({ rightSlot }){


return (


<header className="header">


<div className="logo-area">


<div className="logo-icon">


<Cpu size={38}/>


</div>




<div>


<h1>

AI智能学习助手

</h1>



<p>

多智能体协同学习系统

<span>

Multi-Agent Learning System

</span>

</p>


</div>


</div>


<div style={{ display: "flex", alignItems: "center", gap: "16px" }}>


<div className="system-status">


<Activity size={18}/>


<span>

系统运行正常

</span>


</div>


{rightSlot}


</div>



</header>


)


}


export default Header;