import React, { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { chatService } from '../services/api';
import { Chat, Message, MessageRequest } from '../types';

interface ChatContextType {
  chats: Chat[];
  currentChat: Chat | null;
  isLoading: boolean;
  error: string | null;
  sendMessage: (message: string, photos?: File[]) => Promise<void>;
  selectChat: (chatId: string) => Promise<void>;
  createNewChat: () => void;
  deleteChat: (chatId: string) => Promise<void>;
  refreshChats: () => Promise<void>;
  uploadPhotoForAnalysis: (photo: File) => Promise<void>;
  addMessageToCurrentChat: (message: Message) => void;
  closeTicket: (userId: string, comment?: string) => Promise<void>;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

export const useChat = () => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
};

interface ChatProviderProps {
  children: ReactNode;
}

export const ChatProvider: React.FC<ChatProviderProps> = ({ children }) => {
  const [chats, setChats] = useState<Chat[]>([]);
  const [currentChat, setCurrentChat] = useState<Chat | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [initialLoadDone, setInitialLoadDone] = useState<boolean>(false);

  // Мемоизируем функцию refreshChats, чтобы избежать бесконечных вызовов
  const refreshChats = useCallback(async () => {
    if (isLoading) return; // Предотвращаем параллельные вызовы
    
    console.log('ChatContext - refreshChats called');
    setIsLoading(true);
    setError(null);
    try {
      const fetchedChats = await chatService.getChats();
      console.log('ChatContext - Fetched chats from server:', fetchedChats);
      // Проверяем, что fetchedChats является массивом, если нет - создаем пустой массив
      setChats(Array.isArray(fetchedChats) ? fetchedChats : []);
      console.log('ChatContext - Chats state updated');
    } catch (err: any) {
      console.error('ChatContext - Error fetching chats:', err);
      setError(err.response?.data?.error || 'Ошибка при загрузке чатов');
      setChats([]); // В случае ошибки устанавливаем пустой массив
    } finally {
      setIsLoading(false);
    }
  }, [isLoading]);

  // Загрузка списка чатов при монтировании компонента - только один раз
  useEffect(() => {
    // Создаем функцию загрузки чатов, чтобы избежать зависимостей от refreshChats
    const loadChats = async () => {
      try {
        if (localStorage.getItem('token') && !initialLoadDone) {
          console.log('ChatContext - Initial load of chats triggered');
          // Используем функцию загрузки чатов напрямую, без вызова refreshChats
          setIsLoading(true);
          setError(null);
          try {
            const fetchedChats = await chatService.getChats();
            console.log('ChatContext - Initial load fetched chats:', fetchedChats);
            setChats(Array.isArray(fetchedChats) ? fetchedChats : []);
            setInitialLoadDone(true);
          } catch (err: any) {
            console.error('ChatContext - Error in initial load:', err);
            setError(err.response?.data?.error || 'Ошибка при загрузке чатов');
            setChats([]);
          } finally {
            setIsLoading(false);
          }
        }
      } catch (err) {
        console.error('Failed to load chats:', err);
      }
    };

    loadChats();
    // Удаляем все зависимости, чтобы избежать повторных вызовов
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Добавляем эффект для отслеживания изменений токена
  useEffect(() => {
    const handleStorageChange = () => {
      const token = localStorage.getItem('token');
      if (token && !initialLoadDone) {
        console.log('ChatContext - Token detected, triggering chat load');
        refreshChats();
        setInitialLoadDone(true);
      }
    };

    // Обработчик события выхода из системы
    const handleLogout = () => {
      console.log('ChatContext - Logout event detected, clearing chats');
      setChats([]);
      setCurrentChat(null);
      setInitialLoadDone(false);
    };

    // Проверяем токен при монтировании
    handleStorageChange();

    // Добавляем слушатели событий
    window.addEventListener('storage', handleStorageChange);
    window.addEventListener('logout', handleLogout);
    
    // Очистка при размонтировании
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('logout', handleLogout);
    };
  }, [refreshChats, initialLoadDone]);

  const selectChat = useCallback(async (chatId: string) => {
    console.log(`Selecting chat with ID: ${chatId}`);
    
    // Проверяем, что chatId является валидным ID
    if (!chatId || chatId === 'undefined' || chatId === 'null' || chatId === '000000000000000000000000') {
      console.log('Invalid chat ID, not selecting:', chatId);
      return;
    }

    // Проверяем, не выбран ли уже этот чат
    let alreadySelected = false;
    setCurrentChat(prev => {
      if (prev && prev.id === chatId) {
        console.log('Chat already selected, skipping');
        alreadySelected = true;
      }
      return prev;
    });
    
    if (alreadySelected) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Используем функциональное обновление для получения актуального списка чатов
      let existingChat: Chat | undefined;
      setChats(prev => {
        existingChat = prev.find(chat => chat.id === chatId);
        return prev;
      });
      
      if (existingChat) {
        console.log('Found chat in local list, setting as current');
        setCurrentChat(existingChat);
        
        // Загружаем историю чата с сервера
        console.log('Fetching chat history from server');
        const history = await chatService.getChatHistory(chatId);
        console.log('Received chat history:', history);
        
        // Проверяем, что история содержит сообщения
        if (history && Array.isArray(history.messages) && history.messages.length > 0) {
          // Обновляем чат с полученной историей
          setCurrentChat(prev => prev ? {
            ...prev,
            title: history.title || prev.title,
            messages: history.messages,
            chat_id: history.chat_id,
            telegram_chat_id: history.telegram_chat_id
          } : null);
        } else {
          // Если история пуста, сбрасываем сообщения в чате
          setCurrentChat(prev => prev ? {
            ...prev,
            title: history.title || prev.title,
            messages: [],
            chat_id: history.chat_id,
            telegram_chat_id: history.telegram_chat_id
          } : null);
        }
      } else {
        console.log('Chat not found in local list, fetching from server');
        // Если чата нет в локальном списке, загружаем его с сервера
        try {
          const history = await chatService.getChatHistory(chatId);
          
          if (history && history.messages) {
            // Создаем новый чат и добавляем его в список
            const newChat = {
              id: chatId,
              messages: history.messages,
              createdAt: history.createdAt || new Date().toISOString(),
              updatedAt: history.updatedAt || new Date().toISOString(),
              title: history.title,
              chat_id: history.chat_id,
              telegram_chat_id: history.telegram_chat_id
            };
            
            setCurrentChat(newChat);
            // Проверяем, нет ли уже чата с таким ID перед добавлением
            setChats(prev => {
              const exists = prev.some(chat => chat.id === chatId);
              if (exists) {
                console.log('Chat already exists in list, not adding duplicate');
                return prev;
              }
              return [...prev, newChat];
            });
          } else {
            console.error('Failed to load chat history or chat not found');
            throw new Error('Чат не найден или история не доступна');
          }
        } catch (error) {
          console.log('Chat not found on server, creating new chat with provided ID');
          // Если чат не найден на сервере, создаем новый чат с переданным ID
          const newChat: Chat = {
            id: chatId,
            title: `Заявка #${chatId.substring(0, 8)}`,
            messages: [{
              role: 'user' as const,
              content: 'Новая заявка от пользователя',
              timestamp: new Date().toISOString(),
            }],
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
          };
          
          setCurrentChat(newChat);
          // Проверяем, нет ли уже чата с таким ID перед добавлением
          setChats(prev => {
            const exists = prev.some(chat => chat.id === chatId);
            if (exists) {
              console.log('Chat already exists in list, not adding duplicate');
              return prev;
            }
            return [...prev, newChat];
          });
        }
      }
    } catch (err: any) {
      console.error('Error selecting chat:', err);
      setError(err.response?.data?.error || 'Ошибка при загрузке чата');
      // В случае ошибки не меняем текущий чат
    } finally {
      setIsLoading(false);
    }
  }, []); // Убираем зависимости, так как используем функциональное обновление состояния

  // Используем useCallback для функции createNewChat
  const createNewChat = useCallback(() => {
    // Создаем новый чат с временным ID
    const tempId = '000000000000000000000000';
    
    // Создаем начальное сообщение от клиента (пример заявки)
    const initialClientMessage: Message = {
      role: 'user',
      content: 'Здравствуйте! У меня возник вопрос по использованию сервиса. Можете помочь?',
      timestamp: new Date().toISOString(),
    };
    
    const newChat: Chat = {
      id: tempId,
      title: 'Новая заявка',
      messages: [initialClientMessage],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // Добавляем новый чат в список
    setChats(prevChats => [newChat, ...prevChats]);
    
    // Устанавливаем новый чат как текущий
    setCurrentChat(newChat);
    
    // Сбрасываем ошибку, если она была
    setError(null);
  }, [setChats, setCurrentChat, setError]);

  const sendMessage = async (message: string, photos: File[] = []) => {
    if (!message.trim() && photos.length === 0) {
      console.error('Cannot send empty message without content or photos');
      return;
    }

    setIsLoading(true);
    console.log('Sending message:', message, 'with photos:', photos.length);

    // Объявляем переменные вне try, чтобы иметь доступ к ним в catch
    let chatToUpdate = currentChat;
    let currentMessages: Message[] = [];
    let updatedMessages: Message[] = [];
    let updatedChat: Chat | null = null;
    // Сохраняем текущий заголовок чата, чтобы не потерять его при обновлении
    let currentTitle = chatToUpdate?.title || null;

    try {
      // Создаем blob URL для превью фото если есть
      let previewImageUrl: string | undefined;
      if (photos && photos.length > 0) {
        previewImageUrl = URL.createObjectURL(photos[0]);
      }
      
      // Создаем объект сообщения оператора (assistant)
      const operatorMessage: Message = {
        role: 'assistant',
        content: message,
        timestamp: new Date().toISOString(),
        imageUrl: previewImageUrl, // Используем blob URL для превью
      };

      // Проверяем что у нас есть активный чат
      if (!chatToUpdate || chatToUpdate.id === 'temp-id') {
        console.error('Cannot send message: no active chat selected');
        throw new Error('Выберите чат для отправки сообщения');
      }

      // Сохраняем текущие сообщения для предотвращения потери
      if (chatToUpdate.messages && Array.isArray(chatToUpdate.messages)) {
        currentMessages = [...chatToUpdate.messages];
      }

      // Добавляем сообщение оператора в чат (оптимистичное обновление UI)
      updatedMessages = [...currentMessages, operatorMessage];
      
      // Обновляем чат с новым сообщением оператора
      updatedChat = {
        ...chatToUpdate,
        messages: updatedMessages,
        updatedAt: new Date().toISOString(),
      };
      setCurrentChat(updatedChat);

      // Подготавливаем запрос к API
      const request: MessageRequest = {
        message,
        chat_status: 'existing', // Оператор всегда отправляет в существующий чат
        photos, // Добавляем массив фото
      };

      // Добавляем telegram_chat_id для отправки сообщения
      if (chatToUpdate.telegram_chat_id) {
        request.chat_id = String(chatToUpdate.telegram_chat_id);
      } else {
        throw new Error('Не удалось определить чат для отправки сообщения');
      }

      console.log('Prepared request:', request, 'photos count:', photos.length);

      // Функция для отправки запроса с повторными попытками
      const sendWithRetry = async (retries = 2): Promise<boolean> => {
        try {
          const response = await chatService.sendMessage(request);
          console.log('Message response received:', response);
          
          // Если сервер вернул URL фото, обновляем сообщение оператора
          if (response.photoUrl && previewImageUrl) {
            console.log('Updating operator message with server photo URL:', response.photoUrl);
            setCurrentChat(prev => {
              if (!prev) return prev;
              
              // Находим последнее сообщение оператора (которое мы только что добавили)
              const messages = [...prev.messages];
              const lastMessageIndex = messages.length - 1;
              
              if (lastMessageIndex >= 0 && messages[lastMessageIndex].role === 'assistant') {
                // Обновляем imageUrl с blob на серверный URL
                messages[lastMessageIndex] = {
                  ...messages[lastMessageIndex],
                  imageUrl: response.photoUrl,
                  serverImageUrl: response.photoUrl
                };
              }
              
              return {
                ...prev,
                messages
              };
            });
            
            // Освобождаем blob URL
            URL.revokeObjectURL(previewImageUrl);
          }
          
          // Сообщение оператора уже добавлено в updatedChat (оптимистичное обновление)
          // Ответ от пользователя придет через WebSocket, поэтому не добавляем его здесь
          
          // Обновляем время последнего сообщения в списке чатов
          const chatId = chatToUpdate?.id;
          if (chatId) {
            setChats(prevChats => {
              return prevChats.map(chat => {
                if (chat.id === chatId) {
                  return {
                    ...chat,
                    updatedAt: new Date().toISOString()
                  };
                }
                return chat;
              });
            });
          }

          return true; // Успешно
        } catch (error: any) {
          console.error('Error sending message:', error);
          
          // Проверяем, содержит ли ошибка сообщение "no documents in result"
          const errorMessage = error.response?.data?.error || error.message || '';
          if (errorMessage.includes('no documents in result') || errorMessage.includes('mongo: no documents')) {
            console.log('Чат не найден, создаем новый чат...');
            
            // Изменяем статус чата на 'new' и удаляем chat_id
            request.chat_status = 'new';
            delete request.chat_id;
            
            // Если есть еще попытки, пробуем снова
            if (retries > 0) {
              console.log(`Retrying with new chat... ${retries} attempts left`);
              return sendWithRetry(retries - 1);
            }
          }
          
          // Если есть еще попытки, пробуем снова
          if (retries > 0) {
            console.log(`Retrying... ${retries} attempts left`);
            return sendWithRetry(retries - 1);
          }
          
          // Если попытки закончились, пробрасываем ошибку дальше
          throw error;
        }
      };

      // Отправляем запрос с повторными попытками
      await sendWithRetry();

    } catch (error: any) {
      console.error('Failed to send message after retries:', error);
      
      // Восстанавливаем исходное состояние чата, если есть сохраненные сообщения
      if (currentChat && currentMessages && currentMessages.length > 0) {
        console.log('Restoring chat to previous state with messages:', currentMessages);
        setCurrentChat({
          ...currentChat,
          messages: currentMessages
        });
      }
      
      // Пробрасываем ошибку дальше
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const uploadPhotoForAnalysis = useCallback(async (photo: File) => {
    setIsLoading(true);
    setError(null);
    
    try {
      console.log('Uploading photo for analysis...');
      
      // Получаем ID текущего чата
      let currentChatId = currentChat?.id;
      
      // Проверяем, нужно ли создавать новый чат
      if (!currentChatId || currentChatId === '000000000000000000000000' || currentChatId === 'undefined' || currentChatId === 'null') {
        console.log('Will use server-side chat creation for photo analysis');
        currentChatId = undefined; // Устанавливаем undefined, чтобы сервер создал новый чат
        
        // Создаем временный чат для отображения в UI
        if (!currentChat) {
          const tempChat: Chat = {
            id: 'temp-id',
            title: 'Новый анализ',
            messages: [],
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
          };
          setCurrentChat(tempChat);
        }
      } else {
        console.log('Using existing chat ID for photo analysis:', currentChatId);
      }
      
      // Добавляем временное сообщение пользователя с изображением в чат
      const imageUrl = URL.createObjectURL(photo);
      
      // Создаем сообщение пользователя
      const userMessage: Message = {
        role: 'user',
        content: 'Анализ изображения',
        imageUrl: imageUrl,
        timestamp: new Date().toISOString()
      };
      
      // Добавляем сообщение пользователя в чат (для всех случаев)
      setCurrentChat(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          messages: [...(prev.messages || []), userMessage]
        };
      });
      
      // Создаем временное сообщение ассистента
      const tempAssistantMessage: Message = {
        role: 'assistant',
        content: 'Обрабатываю фото...',
        timestamp: new Date().toISOString()
      };
      
      // Добавляем временное сообщение ассистента в чат (для всех случаев)
      setCurrentChat(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          messages: [...(prev.messages || []), tempAssistantMessage]
        };
      });
      
      // Формируем полный URL изображения
      const getFullImageUrl = (url: string): string => {
        if (!url) return '';
        
        // Если URL является blob URL, возвращаем его как есть
        if (url.startsWith('blob:')) {
          return url;
        }
        
        // Если URL уже начинается с http, возвращаем его как есть
        if (url.startsWith('http')) {
          return url;
        }
        
        // Иначе добавляем базовый URL
        const baseUrl = 'http://localhost:8080';
        return url.startsWith('/') ? `${baseUrl}${url}` : `${baseUrl}/${url}`;
      };
      
      // Отправляем фото на анализ
      const { analysis, imageUrl: serverImageUrl, chatId, parsingResults } = await chatService.analyzePhoto(
        photo, 
        currentChatId
      );
      
      // Формируем полный URL изображения
      const fullImageUrl = getFullImageUrl(serverImageUrl);
      
      console.log('Получен ответ от сервера:', { analysis, serverImageUrl, fullImageUrl, chatId, parsingResults });
      
      // Если сервер вернул chatId, значит был создан новый чат или использован существующий
      if (chatId) {
        console.log('Получен chatId от сервера:', chatId);
        
        // Обновляем список чатов
        await refreshChats();
        
        // Получаем историю чата с сервера
        const newChat = await chatService.getChatHistory(chatId);
        if (newChat && newChat.messages) {
          setCurrentChat({
            id: chatId,
            messages: newChat.messages,
            title: newChat.title || 'Анализ фотографии',
            createdAt: newChat.createdAt || new Date().toISOString(),
            updatedAt: newChat.updatedAt || new Date().toISOString()
          });
          return; // Выходим из функции, так как чат уже обновлен
        }
      }
      
      // Если не был создан новый чат, обновляем текущий
      setCurrentChat(prev => {
        if (!prev) return prev;
        const updatedMessages = [...(prev.messages || [])];
        
        // Находим сообщение пользователя и обновляем его изображение
        const userMessageIndex = updatedMessages.findIndex(msg => 
          msg.role === 'user' && (msg.imageUrl === imageUrl || msg.content === ''));
        
        if (userMessageIndex !== -1) {
          // Сохраняем исходный URL изображения, если это blob URL
          const originalImageUrl = updatedMessages[userMessageIndex].imageUrl;
          const shouldKeepOriginalUrl = originalImageUrl && originalImageUrl.startsWith('blob:');
          
          updatedMessages[userMessageIndex] = {
            ...updatedMessages[userMessageIndex],
            imageUrl: shouldKeepOriginalUrl ? originalImageUrl : fullImageUrl
          };
          
          // Добавляем серверный URL изображения в отдельное поле
          if (shouldKeepOriginalUrl) {
            updatedMessages[userMessageIndex] = {
              ...updatedMessages[userMessageIndex],
              serverImageUrl: fullImageUrl // Сохраняем серверный URL в отдельном поле
            };
          }
        }
        
        // Находим временное сообщение ассистента и обновляем его содержимое
        const assistantMessageIndex = updatedMessages.findIndex(msg => 
          msg.role === 'assistant' && msg.content === 'Обрабатываю фото...');
        
        if (assistantMessageIndex !== -1) {
          updatedMessages[assistantMessageIndex] = {
            ...updatedMessages[assistantMessageIndex],
            content: analysis
          };
        }
        
        // Если есть результаты парсинга, добавляем их как новое сообщение ассистента
        if (parsingResults) {
          console.log('Добавляем результаты парсинга в чат:', parsingResults);
          
          const parsingMessage: Message = {
            role: 'assistant',
            content: parsingResults,
            timestamp: new Date().toISOString()
          };
          
          updatedMessages.push(parsingMessage);
        }
        
        return {
          ...prev,
          messages: updatedMessages
        };
      });
    } catch (error) {
      console.error('Error uploading photo for analysis:', error);
      setError('Не удалось проанализировать фотографию');
      
      // Удаляем временное сообщение ассистента в случае ошибки
      setCurrentChat(prev => {
        if (!prev) return prev;
        const updatedMessages = [...(prev.messages || [])];
        const tempAssistantIndex = updatedMessages.findIndex(msg => 
          msg.role === 'assistant' && msg.content === 'Обрабатываю фото...');
        
        if (tempAssistantIndex !== -1) {
          updatedMessages.splice(tempAssistantIndex, 1);
        }
        
        return {
          ...prev,
          messages: updatedMessages
        };
      });
    } finally {
      setIsLoading(false);
    }
  }, [currentChat, setIsLoading, setError, setCurrentChat, refreshChats]);

  const deleteChat = async (chatId: string) => {
    // Проверяем, что chatId является валидным ID
    if (!chatId || chatId === 'undefined' || chatId === 'null' || chatId === '000000000000000000000000' || chatId === 'temp-id') {
      console.log('Invalid chat ID, not deleting:', chatId);
      
      // Удаляем чат из локального списка
      setChats(prev => prev.filter(chat => chat.id !== chatId));
      
      // Если удаляемый чат был текущим, сбрасываем текущий чат
      if (currentChat && currentChat.id === chatId) {
        setCurrentChat(null);
      }
      
      return;
    }
    
    setIsLoading(true);
    setError(null);
    try {
      console.log(`Deleting chat ${chatId}...`);
      await chatService.deleteChat(chatId);
      console.log(`Successfully deleted chat ${chatId}`);
      
      // Обновляем список чатов
      setChats(prev => prev.filter(chat => chat.id !== chatId));
      
      // Если удаляемый чат был текущим, сбрасываем текущий чат
      if (currentChat && currentChat.id === chatId) {
        setCurrentChat(null);
      }
    } catch (err: any) {
      console.error('Error deleting chat:', err);
      setError(err.response?.data?.error || 'Ошибка при удалении чата');
      
      // Если чата нет на сервере, удаляем его из локального списка
      if (err.response?.status === 404 || (err.response?.data?.error && err.response.data.error.includes('не найден'))) {
        console.log('Chat not found on server, removing from local state');
        setChats(prev => prev.filter(chat => chat.id !== chatId));
        
        if (currentChat && currentChat.id === chatId) {
          setCurrentChat(null);
        }
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Функция для добавления сообщения в текущий чат (для WebSocket)
  const addMessageToCurrentChat = useCallback((message: Message) => {
    console.log('ChatContext - addMessageToCurrentChat called:', message);
    
    setCurrentChat(prev => {
      if (!prev) {
        console.log('ChatContext - No current chat, skipping message add');
        return prev;
      }
      
      // Проверяем, нет ли уже такого сообщения (по timestamp и content)
      const isDuplicate = prev.messages.some(m => 
        m.timestamp === message.timestamp && 
        m.content === message.content
      );
      
      if (isDuplicate) {
        console.log('ChatContext - Duplicate message detected, skipping');
        return prev;
      }
      
      console.log('ChatContext - Adding message to current chat');
      return {
        ...prev,
        messages: [...prev.messages, message],
        updatedAt: message.timestamp || new Date().toISOString()
      };
    });
    
    // Также обновляем чат в списке чатов
    setChats(prevChats => {
      const updatedChats = prevChats.map(chat => {
        if (currentChat && chat.id === currentChat.id) {
          return {
            ...chat,
            updatedAt: message.timestamp || new Date().toISOString()
          };
        }
        return chat;
      });
      return updatedChats;
    });
  }, [currentChat]);

  // Закрытие тикета
  const closeTicket = async (userId: string, comment?: string) => {
    try {
      setIsLoading(true);
      console.log('Closing ticket for user:', userId);
      
      await chatService.closeTicket(userId, comment);
      
      // После успешного закрытия обновляем список чатов
      await refreshChats();
      
      // Сбрасываем текущий чат
      setCurrentChat(null);
      
      console.log('Ticket closed successfully');
    } catch (err: any) {
      console.error('Error closing ticket:', err);
      setError(err.response?.data?.error || 'Ошибка при закрытии тикета');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    window.uploadPhotoForAnalysis = uploadPhotoForAnalysis;
    
    // Очистка при размонтировании
    return () => {
      window.uploadPhotoForAnalysis = undefined;
    };
  }, [currentChat, isLoading, uploadPhotoForAnalysis, refreshChats]);

  const value = {
    chats,
    currentChat,
    isLoading,
    error,
    sendMessage,
    selectChat,
    createNewChat,
    deleteChat,
    refreshChats,
    uploadPhotoForAnalysis,
    addMessageToCurrentChat,
    closeTicket,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
};
