import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from services.webrtc_stream import WebRTCConnectionManager

router = APIRouter()
logger = logging.getLogger(__name__)

_manager: WebRTCConnectionManager | None = None


def get_manager() -> WebRTCConnectionManager:
    global _manager
    if _manager is None:
        _manager = WebRTCConnectionManager(target_fps=15)
    return _manager


class WebRTCOffer(BaseModel):
    sdp: str
    type: str = "offer"
    ice_servers: Optional[list[dict]] = None


class WebRTCAnswer(BaseModel):
    sdp: str
    type: str
    connection_id: str


class DisconnectRequest(BaseModel):
    connection_id: str


@router.post("/offer", response_model=WebRTCAnswer)
async def webrtc_offer(offer: WebRTCOffer):
    """Handle SDP offer from browser client. Returns SDP answer."""
    mgr = get_manager()
    answer_sdp, answer_type, conn_id = await mgr.create_connection(
        offer_sdp=offer.sdp,
        offer_type=offer.type,
        ice_servers=offer.ice_servers,
    )
    return WebRTCAnswer(sdp=answer_sdp, type=answer_type, connection_id=conn_id)


@router.post("/disconnect")
async def webrtc_disconnect(req: DisconnectRequest):
    """Close a WebRTC connection."""
    mgr = get_manager()
    await mgr.close_connection(req.connection_id)
    return {"ok": True}
