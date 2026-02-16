from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import AuthContext, require_verified_email
from app.config import settings
from app.schemas import AskRequest, AskResponse, ErrorResponse, LayerPercentage

app = FastAPI(title="ELIN Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/ask",
    response_model=AskResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
def ask(payload: AskRequest, _: AuthContext = Depends(require_verified_email)) -> AskResponse:
    return AskResponse(
        answer=f"（Mock）已收到你的問題：{payload.question}。目前為開發環境回覆。",
        source="mock",
        layer_percentages=[
            LayerPercentage(label="主層", pct=70),
            LayerPercentage(label="輔層", pct=20),
            LayerPercentage(label="參照層", pct=10),
        ],
        request_id=str(uuid4()),
    )
