"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI()

# 异地联调临时放开全部跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 下面是你原有代码不变
from loguru import logger

from backend.config import get_settings
from backend.db.init_db import init_database
from backend.services.rag.kb_manager import init_knowledge_base
from backend.api.routes import ask, status, feedback, quiz, ws, kb, report


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库和知识库"""
    logger.info("正在初始化数据库...")
    init_database()
    logger.info(f"数据库已就绪: {settings.db_full_path}")

    logger.info("正在初始化知识库...")
    init_knowledge_base()

    logger.info("多智能体协同决策系统启动完成")
    yield
    logger.info("系统关闭")


def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    app = FastAPI(
        title="领域知识个性化生成与多智能体协同决策系统",
        description="挑战杯揭榜挂帅 XH-202630 后端API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS（前端团队需要跨域调用）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(ask.router, prefix="/api", tags=["问答"])
    app.include_router(status.router, prefix="/api", tags=["状态"])
    app.include_router(feedback.router, prefix="/api", tags=["反馈"])
    app.include_router(quiz.router, prefix="/api", tags=["答题"])
    app.include_router(kb.router, prefix="/api", tags=["知识库"])
    app.include_router(report.router, prefix="/api", tags=["报告"])
    app.include_router(ws.router, tags=["WebSocket"])

    @app.get("/")
    async def root():
        return JSONResponse(
            content={
                "service": "多智能体协同决策系统",
                "version": "0.1.0",
                "docs": "/docs",
            },
            media_type="application/json; charset=utf-8",
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
