from __future__ import annotations

import hmac

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/ticks")
async def ticks(ws: WebSocket, token: str = ""):
    """Streams live quote and mark-to-market snapshots. Browsers cannot set
    headers on a WebSocket, so the session token travels as a query parameter."""
    expected = ws.app.state.token
    if expected and not hmac.compare_digest(token.encode(), expected.encode()):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub = ws.app.state.hub
    if hub is None:
        await ws.send_json({"type": "snapshot", "quotes": {}, "portfolio": None,
                            "status": {"source": "none", "state": "off", "detail": "Live feed is off"}})
    else:
        await hub.add(ws)
    try:
        while True:
            await ws.receive_text()  # clients send nothing; this just waits for the close
    except WebSocketDisconnect:
        pass
    finally:
        if hub is not None:
            hub.remove(ws)
