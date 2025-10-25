import axios, { AxiosInstance } from 'axios';
import { Chat, Message, MessageRequest, MessageResponse, LoginRequest, LoginResponse, RegisterRequest } from '../types';

// Создаем базовый экземпляр axios
const api: AxiosInstance = axios.create({
  baseURL: '/api/v1', // Nginx проксирует /api/ на backend
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Интерцептор для добавления токена к каждому запросу
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Интерцептор для обработки ошибок авторизации
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Если получили 401, удаляем токен и перенаправляем на логин
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const authService = {
  login: async (data: LoginRequest): Promise<LoginResponse> => {
    try {
      const response = await api.post('/auth/login', {
        email: data.login, // Backend ожидает email
        password: data.password,
      });
      
      const { access_token, operator } = response.data;
      
      // Сохраняем токен
      localStorage.setItem('token', access_token);
      
      // Возвращаем данные в формате, который ожидает frontend
      return {
        message: 'Login successful',
        token: access_token,
        user_id: operator.id || operator.email, // Используем ID оператора
        name: `${operator.first_name} ${operator.last_name}`,
        email: operator.email,
      };
    } catch (error: any) {
      console.error('Login error:', error);
      throw error;
    }
  },

  register: async (data: RegisterRequest): Promise<void> => {
    try {
      // Разбиваем имя на first_name и last_name
      const nameParts = data.name.trim().split(' ');
      const first_name = nameParts[0] || data.name;
      const last_name = nameParts.slice(1).join(' ') || '';
      
      await api.post('/auth/register', {
        email: data.email,
        first_name: first_name,
        last_name: last_name,
        password: data.password,
      });
    } catch (error: any) {
      console.error('Register error:', error);
      throw error;
    }
  },

  logout: (): void => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  },

  isAuthenticated: (): boolean => {
    return !!localStorage.getItem('token');
  },

  // Получить информацию о текущем пользователе
  getCurrentUser: async () => {
    try {
      const response = await api.get('/auth/me');
      return response.data.operator;
    } catch (error) {
      console.error('Get current user error:', error);
      throw error;
    }
  },
};

export const chatService = {
  sendMessage: async (request: MessageRequest): Promise<MessageResponse> => {
    try {
      console.log('Send message:', request);
      
      // Формируем FormData для отправки
      const formData = new FormData();
      formData.append('telegram_chat_id', request.chat_id || '');
      formData.append('message', request.message);
      formData.append('flag', 'operator');
      
      // Добавляем фото если есть (только первое фото, так как бэкенд принимает одно фото)
      if (request.photos && request.photos.length > 0) {
        console.log('Adding photo to request:', request.photos[0].name);
        formData.append('photo', request.photos[0]);
      }
      
      const response = await api.post('/tickets/message/create', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      console.log('Backend response:', response.data);
      
      // Возвращаем ответ в формате, который ожидает frontend
      return {
        chatId: request.chat_id || response.data.message_id,
        response: request.message, // Эхо сообщения оператора
        chatTitle: `Заявка #${(request.chat_id || '').substring(0, 8)}`,
        photoUrl: response.data.photo_url // Добавляем URL фото из ответа сервера
      };
    } catch (error: any) {
      console.error('Send message error:', error);
      throw error;
    }
  },

  analyzePhoto: async (photo: File, chatId?: string): Promise<{ analysis: string, imageUrl: string, chatId: string, parsingResults?: string }> => {
    console.log('Analyze photo:', photo.name, chatId);
    
    // TODO: Реализовать реальный API запрос после подключения ML routes
    const mockImageUrl = URL.createObjectURL(photo);
    const mockChatId = chatId || 'mock-photo-chat-' + Date.now();
    
    return {
      analysis: `Это mock анализ изображения "${photo.name}". ML API будет подключен в следующем шаге.`,
      imageUrl: mockImageUrl,
      chatId: mockChatId,
      parsingResults: 'Mock результаты парсинга'
    };
  },

  getChats: async (): Promise<Chat[]> => {
    console.log('Get chats');
    
    try {
      // Загружаем назначенные чаты оператора
      const assignedTickets = await chatService.getAssignedChats();
      
      // Преобразуем в формат Chat
      const chats: Chat[] = assignedTickets.map(ticket => ({
        id: ticket.user_id,
        title: ticket.title || `Заявка #${ticket.user_id.substring(0, 8)}`,
        messages: [], // Сообщения загружаются отдельно при выборе чата
        createdAt: ticket.created_at,
        updatedAt: ticket.assigned_at || ticket.created_at,
        chat_id: ticket.chat_id,
        telegram_chat_id: ticket.telegram_chat_id
      }));
      
      return chats;
    } catch (error: any) {
      console.error('Error loading chats:', error);
      return []; // Возвращаем пустой массив в случае ошибки
    }
  },

  getChatHistory: async (chatId: string): Promise<{ messages: Message[], title?: string, createdAt?: string, updatedAt?: string, chat_id?: string, telegram_chat_id?: number }> => {
    try {
      console.log('Get chat history for user_id:', chatId);
      
      // Используем эндпоинт который получает чат по user_id
      const response = await api.get(`/chat/user/${chatId}`);
      
      return {
        messages: response.data.messages || [],
        title: response.data.title,
        createdAt: response.data.createdAt,
        updatedAt: response.data.updatedAt,
        chat_id: response.data.chat?.chat_id,
        telegram_chat_id: response.data.chat?.telegram_chat_id
      };
    } catch (error: any) {
      console.error('Get chat history error:', error);
      
      // Если чат не найден, возвращаем пустую историю
      if (error.response?.status === 404) {
        return {
          messages: [],
          title: `Заявка #${chatId.substring(0, 8)}`,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString()
        };
      }
      
      throw error;
    }
  },

  deleteChat: async (chatId: string): Promise<void> => {
    console.log('Delete chat:', chatId);
    // TODO: Реализовать реальный API запрос
  },

  deleteAllChats: async (): Promise<void> => {
    console.log('Delete all chats');
    // TODO: Реализовать реальный API запрос
  },

  // Получение ожидающих заявок
  getPendingChats: async (): Promise<any[]> => {
    try {
      const response = await api.get('/chat/pending');
      return response.data.chats || [];
    } catch (error: any) {
      console.error('Get pending chats error:', error);
      throw error;
    }
  },

  // Получение заявок назначенных текущему оператору
  getAssignedChats: async (): Promise<any[]> => {
    try {
      const response = await api.get('/chat/assigned');
      return response.data.chats || [];
    } catch (error: any) {
      console.error('Get assigned chats error:', error);
      throw error;
    }
  },

  // Назначение оператора на чат (взять в работу)
  assignOperator: async (chatId: string, operatorId: string): Promise<any> => {
    try {
      const response = await api.post('/chat/assign', {
        chat_id: chatId,
        operator_id: operatorId
      });
      return response.data.chat;
    } catch (error: any) {
      console.error('Assign operator error:', error);
      console.error('Error response:', error.response?.data);
      console.error('Error status:', error.response?.status);
      throw error;
    }
  },

  // Получение истории сообщений по telegram_chat_id
  getMessagesByTelegramChatId: async (telegramChatId: number, limit: number = 50): Promise<Message[]> => {
    try {
      const response = await api.get(`/tickets/messages/${telegramChatId}?limit=${limit}`);
      return response.data.messages || [];
    } catch (error: any) {
      console.error('Get messages error:', error);
      throw error;
    }
  },

  // Закрытие тикета оператором
  closeTicket: async (userId: string, comment?: string): Promise<void> => {
    try {
      console.log('Closing ticket for user:', userId, 'comment:', comment);
      
      await api.post(`/chat/close-by-operator/${userId}`, {
        comment: comment || null
      });
      
      console.log('Ticket closed successfully');
    } catch (error: any) {
      console.error('Close ticket error:', error);
      throw error;
    }
  },

  // Получение AI подсказок для сообщения
  getAiHints: async (messageId: string): Promise<any> => {
    try {
      console.log('Getting AI hints for message:', messageId);
      
      const response = await api.get(`/ml/assist?message_id=${messageId}`, {
        timeout: 140000  // Увеличиваем timeout до 120 секунд для ML сервиса (медленный процесс)
      });
      
      console.log('AI hints response:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('Get AI hints error:', error);
      throw error;
    }
  },

  getLatestReviews: async (operatorId: string): Promise<any> => {
    try {
      console.log('Getting latest reviews for operator:', operatorId);
      const response = await fetch(`/stats/list-stats/${operatorId}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log('Latest reviews response:', data);
      return data;
    } catch (error: any) {
      console.error('Get latest reviews error:', error);
      throw error;
    }
  }
};

export default api;
