import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { Message } from '../types';
import { chatService } from '../services/api';

interface ChatMessagesProps {
  messages: Message[];
  isLoading?: boolean;
  getFullImageUrl?: (message: Message) => string;
  onSendMessage?: (message: string) => void;
}

const defaultGetFullImageUrl = (message: Message): string => {
  // Динамически определяем хост (работает как в Docker, так и локально)
  const currentHost = window.location.host; // автоматически включает порт
  
  // Сначала проверяем, есть ли серверный URL
  if (message.serverImageUrl) {
    console.log('Using server image URL:', message.serverImageUrl);
    // Заменяем внутренний Docker URL на nginx proxy с текущим хостом
    const publicUrl = message.serverImageUrl.replace('http://minio:9000', `http://${currentHost}/storage`);
    console.log('Converted to nginx proxy URL:', publicUrl);
    return publicUrl;
  }
  
  // Если нет серверного URL, используем обычный imageUrl
  const imageUrl = message.imageUrl;
  if (!imageUrl) return '';
  
  // Проверяем URL изображения
  console.log('Original image URL:', imageUrl);
  
  // Если URL является blob URL, возвращаем его как есть
  if (imageUrl.startsWith('blob:')) {
    console.log('URL is a blob URL, using as is:', imageUrl);
    return imageUrl;
  }
  
  // Если URL уже начинается с http, заменяем minio на фронтенд прокси
  if (imageUrl.startsWith('http')) {
    console.log('URL already starts with http:', imageUrl);
    // Заменяем внутренний Docker URL на nginx proxy с текущим хостом
    const publicUrl = imageUrl.replace('http://minio:9000', `http://${currentHost}/storage`);
    console.log('Converted to nginx proxy URL:', publicUrl);
    return publicUrl;
  }
  
  // Иначе добавляем базовый URL
  const baseUrl = `http://${currentHost}`;
  const fullUrl = imageUrl.startsWith('/') ? `${baseUrl}${imageUrl}` : `${baseUrl}/${imageUrl}`;
  console.log('Converted to full URL:', fullUrl);
  return fullUrl;
};

const ChatMessages: React.FC<ChatMessagesProps> = ({ messages, isLoading = false, getFullImageUrl = defaultGetFullImageUrl, onSendMessage }) => {
  const messagesEndRef = React.createRef<HTMLDivElement>();
  const [copiedMessageIndex, setCopiedMessageIndex] = useState<number | null>(null);
  const [aiSuggestionsVisible, setAiSuggestionsVisible] = useState<number | null>(null);
  const [aiSuggestionsLoading, setAiSuggestionsLoading] = useState<number | null>(null);
  const [aiSuggestions, setAiSuggestions] = useState<{[key: number]: {answer: string, actions: string[]}}>({});
  const [aiSuggestionsTab, setAiSuggestionsTab] = useState<{[key: number]: 'answer' | 'actions'}>({});
  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [selectedImage, setSelectedImage] = useState<string>('');

  // Автоматическая прокрутка вниз при добавлении новых сообщений
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, messagesEndRef]);

  // Добавляем логирование при изменении сообщений
  useEffect(() => {
    console.log('ChatMessages - messages updated:', JSON.stringify(messages));
    // Добавляем подробное логирование каждого сообщения
    messages.forEach((msg, index) => {
      console.log(`Message ${index}:`, {
        role: msg.role,
        content: msg.content || 'ПУСТОЕ СОДЕРЖИМОЕ',
        timestamp: msg.timestamp,
        imageUrl: msg.imageUrl || 'НЕТ ИЗОБРАЖЕНИЯ'
      });
      
      // Проверяем URL изображения
      if (msg.imageUrl) {
        console.log(`Image URL for message ${index}:`, msg.imageUrl);
        // Проверяем, что URL изображения содержит базовый URL
        if (!msg.imageUrl.startsWith('http')) {
          console.log(`Image URL does not start with http, full URL should be: http://localhost:8080${msg.imageUrl.startsWith('/') ? '' : '/'}${msg.imageUrl}`);
        }
      }
    });
  }, [messages]);

  const formatTimestamp = (timestamp: string | undefined) => {
    if (!timestamp) {
      console.log('Invalid timestamp:', timestamp);
      return '';
    }
    
    try {
      const date = new Date(timestamp);
      // Проверка на валидность даты
      if (isNaN(date.getTime())) {
        console.log('Invalid timestamp value:', timestamp);
        return '';
      }
      
      return new Intl.DateTimeFormat('ru-RU', {
        hour: '2-digit',
        minute: '2-digit',
      }).format(date);
    } catch (error) {
      console.error('Error formatting timestamp:', error, timestamp);
      return '';
    }
  };

  // Функция для проверки валидности сообщения
  const isValidMessage = (message: any): message is Message => {
    return (
      message &&
      typeof message === 'object' &&
      typeof message.role === 'string' &&
      ['user', 'assistant'].includes(message.role) &&
      (message.content === undefined || message.content === null || typeof message.content === 'string') &&
      (message.imageUrl === undefined || message.imageUrl === null || typeof message.imageUrl === 'string')
    );
  };

  // Используем переданную функцию getFullImageUrl

  // Функция для получения содержимого сообщения
  const getMessageContent = (message: Message) => {
    if (message.content && message.content.trim() !== '') {
      return message.content;
    }
    return 'Пустое сообщение';
  };

  // Функция для определения, содержит ли сообщение результаты парсинга Wildberries
  const isWildberriesParsingResult = (content: string): boolean => {
    // Проверяем наличие заголовка с или без эмодзи
    return content.includes('## Найденные товары на Wildberries') || 
           content.includes('## 🛍️ Найденные товары на Wildberries') || 
           // Проверяем наличие подзаголовков с или без эмодзи
           content.includes('### ') || 
           content.includes('### 🔍') || 
           // Проверяем наличие сообщений об ошибках с или без эмодзи
           content.includes('Не удалось найти похожие товары') || 
           content.includes('### ❌ Не удалось найти похожие товары');
  };

  // Функция для копирования текста в буфер обмена
  const copyMessageToClipboard = (text: string, groupIndex: number) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedMessageIndex(groupIndex);
      // Сбрасываем состояние через 2 секунды
      setTimeout(() => {
        setCopiedMessageIndex(null);
      }, 2000);
    }).catch(err => {
      console.error('Не удалось скопировать текст:', err);
    });
  };

  // Функция для получения AI подсказок
  const getAiSuggestions = async (message: Message, groupIndex: number) => {
    // Если подсказки уже видны, скрываем их
    if (aiSuggestionsVisible === groupIndex) {
      setAiSuggestionsVisible(null);
      return;
    }

    // Проверяем наличие ID сообщения
    if (!message.id) {
      console.error('Message ID is missing, cannot get AI hints');
      // Показываем заглушку если ID отсутствует
      setAiSuggestions(prev => ({
        ...prev,
        [groupIndex]: { answer: 'Не удалось получить подсказки: отсутствует ID сообщения', actions: [] }
      }));
      setAiSuggestionsTab(prev => ({
        ...prev,
        [groupIndex]: 'answer'
      }));
      setAiSuggestionsVisible(groupIndex);
      return;
    }

    // Показываем загрузку
    setAiSuggestionsLoading(groupIndex);
    setAiSuggestionsVisible(groupIndex);

    try {
      // Реальный запрос к ML API через бэкенд
      const response = await chatService.getAiHints(message.id);
      
      console.log('AI hints received:', response);
      
      // Извлекаем подсказки из ответа, разделяя на "Вариант ответа" и "Действия"
      let answerText = '';
      const actions: string[] = [];
      
      // Если есть шаблон ответа - используем его
      if (response.hints?.response_template) {
        answerText = response.hints.response_template;
      }
      // Иначе, если есть relevant_docs, берем самый релевантный
      else if (response.relevant_docs && Array.isArray(response.relevant_docs) && response.relevant_docs.length > 0) {
        const mostRelevant = response.relevant_docs[0];
        if (mostRelevant.payload?.knowledge) {
          answerText = mostRelevant.payload.knowledge;
        }
      }
      
      // Добавляем предложенные действия если есть
      if (response.hints?.suggested_actions && Array.isArray(response.hints.suggested_actions)) {
        response.hints.suggested_actions.forEach((action: any) => {
          if (typeof action === 'string') {
            actions.push(action);
          } else if (action.description) {
            actions.push(action.description);
          }
        });
      }
      
      // Если нет подсказок, показываем сообщение
      if (!answerText && actions.length === 0) {
        answerText = 'AI не смог сгенерировать подсказки для этого сообщения.';
      }
      
      setAiSuggestions(prev => ({
        ...prev,
        [groupIndex]: { answer: answerText, actions }
      }));
      
      // Устанавливаем начальную вкладку (ответ, если есть, иначе действия)
      setAiSuggestionsTab(prev => ({
        ...prev,
        [groupIndex]: answerText ? 'answer' : 'actions'
      }));
      
      setAiSuggestionsLoading(null);
    } catch (error: any) {
      console.error('Error getting AI hints:', error);
      
      let errorMessage = 'Ошибка при получении подсказок.';
      if (error.code === 'ECONNABORTED') {
        errorMessage = 'Превышено время ожидания. ML сервис перегружен, попробуйте позже.';
      }
      
      // Показываем ошибку пользователю
      setAiSuggestions(prev => ({
        ...prev,
        [groupIndex]: { answer: errorMessage, actions: [] }
      }));
      setAiSuggestionsTab(prev => ({
        ...prev,
        [groupIndex]: 'answer'
      }));
      setAiSuggestionsLoading(null);
    }
  };

  return (
    <div 
      className="flex-1 overflow-y-auto custom-scrollbar bg-dark-primary" 
      data-component-name="ChatMessages"
    >
      {messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full px-4 py-12">
          <div className="max-w-2xl w-full text-center space-y-6">
            <h2 className="text-2xl font-semibold text-white">Панель оператора</h2>
            <p className="text-dark-text/70 text-base max-w-md mx-auto">
              Выберите заявку из списка или создайте новую для работы с клиентами.
            </p>
          </div>
        </div>
      ) : (
        // Группируем сообщения по параметру (пользователь + ассистент)
        (() => {
          // Фильтруем невалидные сообщения
          const validMessages = messages.filter(message => isValidMessage(message));
          const messageGroups = [];
          
          // Отображаем сообщения в правильном порядке: пользователь -> ассистент
          for (let i = 0; i < validMessages.length; i++) {
            const currentMessage = validMessages[i];
            const nextMessage = validMessages[i + 1];
            
            if (currentMessage.role === 'user') {
              // Сообщение пользователя - проверяем есть ли ответ ассистента
              if (nextMessage && nextMessage.role === 'assistant') {
                messageGroups.push({ userMessage: currentMessage, assistantMessage: nextMessage });
                i++; // Пропускаем следующее сообщение ассистента
              } else {
                messageGroups.push({ userMessage: currentMessage, assistantMessage: null });
              }
            } else if (currentMessage.role === 'assistant') {
              // Если первое сообщение от ассистента (не должно быть в нормальном потоке)
              messageGroups.push({ userMessage: null, assistantMessage: currentMessage });
            }
          }
          
          return (
            <div className="px-4 py-6 space-y-4">
              {messageGroups.map((group, groupIndex) => (
                <div 
                  key={groupIndex} 
                  className="space-y-3"
                >
                  {group.userMessage && (
                    <div className="flex justify-start">
                      <div className="flex items-start space-x-2 max-w-xs lg:max-w-md xl:max-w-lg">
                         <div className="w-8 h-8 rounded-full bg-dark-accent flex items-center justify-center flex-shrink-0 border border-dark-border/50">
                           <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                             <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
                           </svg>
                         </div>
                        <div className="flex-1">
                          <div className="text-xs text-dark-text/50 mb-1 px-1">
                            Клиент
                          </div>
                         <div className="bg-dark-secondary/80 backdrop-blur-sm text-dark-text rounded-2xl rounded-tl-md px-4 py-2 shadow-lg border border-dark-border/50">
                          <div className="text-sm leading-relaxed">{getMessageContent(group.userMessage)}</div>
                          {group.userMessage.imageUrl && (
                            <div className="mt-2">
                              <img 
                                src={getFullImageUrl(group.userMessage)} 
                                alt="Uploaded by user" 
                                className="max-w-full h-auto rounded-xl max-h-60 object-cover cursor-pointer hover:opacity-80 transition-opacity"
                                onClick={() => {
                                  setSelectedImage(getFullImageUrl(group.userMessage));
                                  setImageModalOpen(true);
                                }}
                                onError={(e) => {
                                  const url = getFullImageUrl(group.userMessage);
                                  console.error('Error loading image:', {
                                    originalUrl: group.userMessage.imageUrl,
                                    serverUrl: group.userMessage.serverImageUrl,
                                    fullUrl: url,
                                    element: e.currentTarget
                                  });
                                  
                                  if (url.startsWith('blob:')) {
                                    console.log('Not retrying for blob URL');
                                    e.currentTarget.onerror = null;
                                    e.currentTarget.style.display = 'none';
                                    return;
                                  }
                                  
                                  if (url.includes('/api/images/')) {
                                    const imageId = url.split('/api/images/')[1];
                                    console.log('Trying alternative URL format with image ID:', imageId);
                                    e.currentTarget.src = `http://localhost:8080/api/images/${imageId}`;
                                    return;
                                  }
                                  e.currentTarget.onerror = null;
                                  e.currentTarget.style.display = 'none';
                                }}
                              />
                            </div>
                          )}
                          <div className="flex justify-start items-center gap-3 mt-1">
                            <button 
                              onClick={() => getAiSuggestions(group.userMessage, groupIndex)}
                              className="opacity-70 hover:opacity-100 transition-opacity duration-200 text-xs text-custom-blue hover:text-custom-blue/80 flex items-center gap-1"
                              title="AI подсказки"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                              </svg>
                              AI подсказки
                            </button>
                            <button 
                              onClick={() => copyMessageToClipboard(getMessageContent(group.userMessage), groupIndex)}
                              className="opacity-70 hover:opacity-100 transition-opacity duration-200 text-xs text-dark-text/70 hover:text-dark-text"
                              title="Скопировать текст"
                            >
                              {copiedMessageIndex === groupIndex ? (
                                <span className="text-custom-blue">✓ Скопировано</span>
                              ) : (
                                'Копировать'
                              )}
                            </button>
                          </div>

                          {/* AI Подсказки */}
                          {aiSuggestionsVisible === groupIndex && (
                            <div className="mt-2 p-3 bg-dark-accent/30 rounded-lg border border-custom-blue/30">
                              {aiSuggestionsLoading === groupIndex ? (
                                <div className="flex flex-col items-center justify-center py-4">
                                  <div className="relative w-12 h-12 mb-3">
                                    {/* Внешнее вращающееся кольцо */}
                                    <div className="absolute inset-0 border-2 border-custom-blue/20 rounded-full"></div>
                                    <div className="absolute inset-0 border-2 border-transparent border-t-custom-blue rounded-full animate-spin"></div>
                                    
                                    {/* Внутренний пульсирующий круг */}
                                    <div className="absolute inset-2 bg-custom-blue/20 rounded-full animate-pulse"></div>
                                    
                                    {/* AI иконка в центре */}
                                    <div className="absolute inset-0 flex items-center justify-center">
                                      <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-custom-blue" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                                      </svg>
                                    </div>
                                  </div>
                                  <span className="text-xs text-custom-blue font-medium animate-pulse">AI генерирует подсказки</span>
                                </div>
                              ) : (
                                <div className="space-y-2">
                                  {/* Вкладки для переключения между "Вариант ответа" и "Действия" */}
                                  <div className="flex items-center gap-4 mb-3">
                                    {aiSuggestions[groupIndex]?.answer && (
                                      <button
                                        onClick={() => setAiSuggestionsTab(prev => ({ ...prev, [groupIndex]: 'answer' }))}
                                        className={`text-xs font-medium transition-colors ${
                                          aiSuggestionsTab[groupIndex] === 'answer'
                                            ? 'text-custom-blue border-b-2 border-custom-blue pb-1'
                                            : 'text-dark-text/60 hover:text-custom-blue/80 pb-1'
                                        }`}
                                      >
                                        Вариант ответа
                                      </button>
                                    )}
                                    {aiSuggestions[groupIndex]?.actions && aiSuggestions[groupIndex]?.actions.length > 0 && (
                                      <button
                                        onClick={() => setAiSuggestionsTab(prev => ({ ...prev, [groupIndex]: 'actions' }))}
                                        className={`text-xs font-medium transition-colors ${
                                          aiSuggestionsTab[groupIndex] === 'actions'
                                            ? 'text-custom-blue border-b-2 border-custom-blue pb-1'
                                            : 'text-dark-text/60 hover:text-custom-blue/80 pb-1'
                                        }`}
                                      >
                                        Действия
                                      </button>
                                    )}
                                  </div>

                                  {/* Контент в зависимости от активной вкладки */}
                                  <div 
                                    onClick={() => {
                                      // Находим textarea и вставляем текст в зависимости от вкладки
                                      let textToInsert = '';
                                      const currentTab = aiSuggestionsTab[groupIndex] || 'answer';
                                      const suggestions = aiSuggestions[groupIndex];
                                      
                                      if (currentTab === 'answer' && suggestions?.answer) {
                                        textToInsert = suggestions.answer;
                                      } else if (currentTab === 'actions' && suggestions?.actions) {
                                        textToInsert = suggestions.actions.map(a => `• ${a}`).join('\n');
                                      }
                                      
                                      const textarea = document.querySelector('textarea[data-component-name="ChatInput"]') as HTMLTextAreaElement;
                                      if (textarea && textToInsert) {
                                        textarea.value = textToInsert;
                                        textarea.focus();
                                        // Автоматически подстраиваем высоту textarea
                                        textarea.style.height = 'auto';
                                        textarea.style.height = `${textarea.scrollHeight}px`;
                                        
                                        // Обновляем позицию кнопок над полем ввода
                                        const extraHeight = Math.max(0, textarea.clientHeight - 44);
                                        const buttonsContainer = document.querySelector('div[data-component-name="ChatPage"]');
                                        if (buttonsContainer) {
                                          const sidebarVisible = document.querySelector('.w-64.opacity-100') !== null;
                                          buttonsContainer.setAttribute('style', `left: ${sidebarVisible ? '16rem' : '0'}; bottom: calc(5.5rem + ${extraHeight}px)`);
                                        }
                                      }
                                    }}
                                    className="p-3 bg-dark-secondary/50 rounded-md text-sm text-dark-text hover:bg-dark-secondary/80 cursor-pointer transition-colors border border-dark-border/30 hover:border-custom-blue/50"
                                  >
                                    {aiSuggestionsTab[groupIndex] === 'answer' ? (
                                      // Показываем вариант ответа
                                      <div className="whitespace-pre-wrap leading-relaxed">
                                        {aiSuggestions[groupIndex]?.answer || 'Нет варианта ответа'}
                                      </div>
                                    ) : (
                                      // Показываем действия
                                      <div className="space-y-2">
                                        {aiSuggestions[groupIndex]?.actions && aiSuggestions[groupIndex]?.actions.length > 0 ? (
                                          aiSuggestions[groupIndex]?.actions.map((action, idx) => (
                                            <div key={idx} className="flex items-start gap-2">
                                              <span className="text-custom-blue mt-1">•</span>
                                              <span className="flex-1">{action}</span>
                                            </div>
                                          ))
                                        ) : (
                                          <div>Нет предложенных действий</div>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                        </div>
                      </div>
                    </div>
                  )}
              
                  {group.assistantMessage && (
                    <div className="flex justify-end">
                      <div className="max-w-xs lg:max-w-md xl:max-w-lg">
                        <div className="text-xs text-dark-text/50 mb-1 text-right px-1">
                          Оператор (Вы)
                        </div>
                         <div className="bg-custom-blue/20 text-white rounded-2xl rounded-br-md px-4 py-2 shadow-lg border border-custom-blue/30">
                          <div className="text-sm leading-relaxed">{getMessageContent(group.assistantMessage)}</div>
                            {group.assistantMessage.imageUrl && (
                              <div className="mt-2">
                                <img 
                                  src={getFullImageUrl(group.assistantMessage)} 
                                  alt="Assistant response" 
                                  className="max-w-full h-auto rounded-xl max-h-60 object-cover cursor-pointer hover:opacity-80 transition-opacity"
                                  onClick={() => {
                                    setSelectedImage(getFullImageUrl(group.assistantMessage));
                                    setImageModalOpen(true);
                                  }}
                                  onError={(e) => {
                                    const url = getFullImageUrl(group.assistantMessage);
                                    console.error('Error loading image:', {
                                      originalUrl: group.assistantMessage.imageUrl,
                                      serverUrl: group.assistantMessage.serverImageUrl,
                                      fullUrl: url,
                                      element: e.currentTarget
                                    });
                                    
                                    if (url.startsWith('blob:')) {
                                      console.log('Not retrying for blob URL');
                                      e.currentTarget.onerror = null;
                                      e.currentTarget.style.display = 'none';
                                      return;
                                    }
                                    
                                    if (url.includes('/api/images/')) {
                                      const imageId = url.split('/api/images/')[1];
                                      console.log('Trying alternative URL format with image ID:', imageId);
                                      e.currentTarget.src = `http://localhost:8080/api/images/${imageId}`;
                                      return;
                                    }
                                    
                                    e.currentTarget.onerror = null;
                                    e.currentTarget.style.display = 'none';
                                  }}
                                />
                              </div>
                            )}
                          </div>
                         <div className="text-xs text-white/70 mt-1 text-right px-1">
                           {formatTimestamp(group.assistantMessage.timestamp)}
                         </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          );
        })()
      )}
      <div ref={messagesEndRef} />
      
      {/* Добавляем отступ после последнего сообщения */}
      <div className="h-32" aria-hidden="true"></div>
      
      {/* Модальное окно для просмотра изображения */}
      {imageModalOpen && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setImageModalOpen(false)}
        >
          <div className="relative max-w-5xl max-h-[90vh]">
            <button
              onClick={() => setImageModalOpen(false)}
              className="absolute -top-10 right-0 text-white hover:text-gray-300 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <img 
              src={selectedImage} 
              alt="Full size" 
              className="max-w-full max-h-[85vh] object-contain rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatMessages;
