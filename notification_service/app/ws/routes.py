import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.wsmanager import ws_manager

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

router = APIRouter()
@router.get("/health")
async def health_check():
    return {"status": "ok"}

@router.websocket("/ws/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: str):
    await ws_manager.connect(websocket, chat_id)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)

                if data == "ping":
                    await websocket.send_json({"type": "pong"})
                    
            except asyncio.TimeoutError:

                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    logger.warning(f"Не удалось отправить ping клиенту в чате {chat_id}. Закрываем соединение.")
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"Клиент отключился штатно от чата {chat_id}")
    except Exception as e:
        logger.error(f"Произошла ошибка в WebSocket для чата {chat_id}: {e}", exc_info=True)
    finally:
        ws_manager.disconnect(websocket, chat_id)