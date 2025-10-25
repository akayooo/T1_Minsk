from typing import Dict, List
from fastapi import  WebSocket
import asyncio
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ConnectionManager:
    """Управляет WebSocket-подключениями операторов."""
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, chat_id: str):
        await websocket.accept()
        if chat_id not in self.active_connections:
            self.active_connections[chat_id] = []
        self.active_connections[chat_id].append(websocket)
        logger.info(f"Оператор подключился к чату {chat_id}")

    def disconnect(self, websocket: WebSocket, chat_id: str):
        if chat_id in self.active_connections and websocket in self.active_connections[chat_id]:
            self.active_connections[chat_id].remove(websocket)
            if not self.active_connections[chat_id]:
                del self.active_connections[chat_id]
            logger.info(f"Оператор отключился от чата {chat_id}")

    async def send_message_to_operator(self, chat_id: str, message: dict) -> bool:
        """
        Отправляет сообщение оператору в чате.
        Возвращает True, если оператор подключен и сообщение отправлено, иначе False.
        """
        operator_connections = self.active_connections.get(chat_id)
        if not operator_connections:
            logger.warning(f"Оператор для чата {chat_id} не в сети. Сообщение не доставлено.")
            return False
        results = await asyncio.gather(
            *(conn.send_json(message) for conn in operator_connections),
            return_exceptions=True
        )
        if any(not isinstance(res, Exception) for res in results):
            return True
        else:
            logger.error(f"Не удалось отправить сообщение ни одному оператору в чате {chat_id}. Очистка соединений.")
            for conn in operator_connections[:]: 
                self.disconnect(conn, chat_id)
            return False
        
ws_manager = ConnectionManager()