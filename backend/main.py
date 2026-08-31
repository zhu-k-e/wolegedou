"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# 下面是你原有代码不变
from loguru import logger

from backend.config import get_settings
from backend.db.init_db import init_database
from backend.services.rag.kb_manager import init_knowledge_base
from backend.services.compliance import cleanup_expired
from backend.api.routes import ask, status, feedback, quiz, ws, kb, report, memory


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库和知识库"""
    logger.info("正在初始化数据库...")
    init_database()
    logger.info(f"数据库已就绪: {settings.db_full_path}")

    logger.info("正在初始化知识库...")
    init_knowledge_base()

    # 数据合规：启动时清理过期对话历史（方案书 7.4 节）
    try:
        expired = cleanup_expired()
        if expired:
            logger.info(f"已清理过期对话历史: {expired} 条")
    except Exception as e:
        logger.warning(f"过期对话清理失败（不影响启动）: {e}")

    logger.info("多智能体协同决策系统启动完成")
    yield
    logger.info("系统关闭")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """可选 API Key 认证中间件。

    仅当 config.api_key 非空时在 create_app 中挂载；为空则不启用，保持向后兼容。
    WebSocket 握手阶段不强制（前端联调场景）。
    """

    async def dispatch(self, request, call_next):
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        # 预检请求(OPTIONS)直接放行，否则 CORS 预检会被拦截导致跨域失败
        if request.method == "OPTIONS":
            return await call_next(request)
        api_key = get_settings().api_key
        if not api_key:
            return await call_next(request)
        provided = request.headers.get("X-API-Key") or request.query_params.get(
            "api_key"
        )
        if provided != api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "无效或缺失 API Key（需在请求头携带 X-API-Key）"},
            )
        return await call_next(request)


def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    app = FastAPI(
        title="领域知识个性化生成与多智能体协同决策系统",
        description="挑战杯揭榜挂帅 XH-202630 后端API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS：优先用配置的白名单；未配置则回退到开发态通配（适配异地联调穿透）
    # 部署到生产时在 .env 设置 CORS_ORIGINS 为前端域名白名单即可收紧
    cors_origins = settings.cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 简单 API Key 认证（config.api_key 为空则不启用）
    if settings.api_key:
        app.add_middleware(APIKeyMiddleware)

    # 注册路由
    app.include_router(ask.router, prefix="/api", tags=["问答"])
    app.include_router(status.router, prefix="/api", tags=["状态"])
    app.include_router(feedback.router, prefix="/api", tags=["反馈"])
    app.include_router(quiz.router, prefix="/api", tags=["答题"])
    app.include_router(kb.router, prefix="/api", tags=["知识库"])
    app.include_router(report.router, prefix="/api", tags=["报告"])
    app.include_router(memory.router, prefix="/api", tags=["贡献记忆"])
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
