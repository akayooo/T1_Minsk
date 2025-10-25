import { useEffect, useRef, useCallback } from 'react';

interface UseWebSocketOptions {
  onMessage: (data: any) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
}

export const useWebSocket = (chatId: string | null, options: UseWebSocketOptions) => {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const currentChatIdRef = useRef<string | null>(null);
  const maxReconnectAttempts = 5;
  const reconnectDelay = 3000; // 3 секунды

  // Используем ref для опций чтобы избежать переподключений
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const connect = useCallback(() => {
    if (!chatId) {
      console.log('useWebSocket: No chatId provided, skipping connection');
      return;
    }

    // Проверяем, не подключены ли мы уже к этому чату
    if (wsRef.current && 
        wsRef.current.readyState === WebSocket.OPEN && 
        currentChatIdRef.current === chatId) {
      console.log('useWebSocket: Already connected to this chat, skipping reconnection');
      return;
    }

    // Закрываем предыдущее соединение если есть
    if (wsRef.current) {
      console.log('useWebSocket: Closing previous connection');
      wsRef.current.close();
    }
    
    // Обновляем текущий chatId
    currentChatIdRef.current = chatId;

    try {
      // WebSocket URL через nginx proxy (используем динамический хост)
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host; // автоматически использует правильный порт
      const wsUrl = `${protocol}//${host}/ws/${chatId}`;
      console.log('Connecting to WebSocket:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected for chat:', chatId);
        reconnectAttemptsRef.current = 0; // Сбрасываем счетчик попыток
        optionsRef.current.onOpen?.();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('WebSocket message received:', data);
          
          // Обрабатываем ping/pong
          if (data.type === 'ping') {
            ws.send('pong');
            return;
          }
          
          if (data.type === 'pong') {
            return;
          }
          
          optionsRef.current.onMessage(data);
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        optionsRef.current.onError?.(error);
      };

      ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);
        optionsRef.current.onClose?.();
        
        // Автоматическое переподключение только если соединение не было закрыто намеренно
        if (event.code !== 1000 && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current++;
          console.log(`Reconnecting... Attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts}`);
          
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectDelay);
        } else if (event.code === 1000) {
          console.log('WebSocket closed normally, not reconnecting');
        } else {
          console.error('Max reconnection attempts reached');
        }
      };

      // Отправляем ping каждые 30 секунд для поддержания соединения
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 30000);

      // Сохраняем интервал для очистки
      (ws as any).pingInterval = pingInterval;

    } catch (error) {
      console.error('Error creating WebSocket:', error);
    }
  }, [chatId]);

  useEffect(() => {
    if (chatId) {
      connect();
    }

    return () => {
      // Очистка при размонтировании
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      
      if (wsRef.current) {
        const ws = wsRef.current;
        
        // Очищаем ping интервал
        if ((ws as any).pingInterval) {
          clearInterval((ws as any).pingInterval);
        }
        
        // Закрываем с кодом 1000 (нормальное закрытие)
        ws.close(1000, 'Component unmounting');
        wsRef.current = null;
      }
      
      // Сбрасываем текущий chatId и счетчик попыток
      currentChatIdRef.current = null;
      reconnectAttemptsRef.current = 0;
    };
  }, [chatId, connect]);

  const sendMessage = useCallback((message: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.error('WebSocket is not connected');
    }
  }, []);

  return { sendMessage };
};

