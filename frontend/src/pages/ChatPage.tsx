import React, { useEffect, useState, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import ChatSidebar from '../components/ChatSidebar';
import ChatMessages from '../components/ChatMessages';
import { useChat } from '../context/ChatContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { Message } from '../types';

const ChatPage: React.FC = () => {
  const location = useLocation();
  const { currentChat, sendMessage, isLoading, selectChat, refreshChats, createNewChat, uploadPhotoForAnalysis, addMessageToCurrentChat, closeTicket } = useChat();
  const [error, setError] = useState<string | null>(null);
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [uploadedPhotos, setUploadedPhotos] = useState<File[]>([]);
  const [photoPreviewUrls, setPhotoPreviewUrls] = useState<string[]>([]);
  const chatLoadedFromStateRef = useRef(false);
  const [incomingMessages, setIncomingMessages] = useState<Message[]>([]);
  const [closeTicketModalOpen, setCloseTicketModalOpen] = useState(false);
  const [ticketComment, setTicketComment] = useState<string>('');

  // WebSocket подключение для получения сообщений в реальном времени
  useWebSocket(currentChat?.chat_id || null, {
    onMessage: (data) => {
      console.log('=== WEBSOCKET MESSAGE RECEIVED ===');
      console.log('Full data:', data);
      console.log('Flag:', data.flag);
      console.log('Message:', data.message);
      
      // Проверяем что это новое сообщение от ПОЛЬЗОВАТЕЛЯ (не от оператора)
      if (data.message && data.flag === 'user') {
        console.log('✅ Message is from user, adding to chat');
        const newMessage: Message = {
          id: data.message_id,    // Используем message_id из Kafka как временный ID
          role: 'user',
          content: data.message,  // Используем message, не merge_text
          imageUrl: data.photo,   // URL фото если есть
          timestamp: data.date
        };
        
        // Добавляем сообщение в список входящих
        setIncomingMessages(prev => [...prev, newMessage]);
      } else {
        console.log('❌ Message ignored - flag:', data.flag);
      }
    },
    onOpen: () => {
      console.log('WebSocket connected');
    },
    onClose: () => {
      console.log('WebSocket disconnected');
    },
    onError: (error) => {
      console.error('WebSocket error:', error);
    }
  });

  // Добавляем входящие сообщения в текущий чат
  useEffect(() => {
    if (incomingMessages.length > 0 && currentChat) {
      console.log('New incoming messages:', incomingMessages);
      
      // Добавляем каждое сообщение в текущий чат через ChatContext
      incomingMessages.forEach(message => {
        addMessageToCurrentChat(message);
      });
      
      // Очищаем список входящих
      setIncomingMessages([]);
    }
  }, [incomingMessages, currentChat, addMessageToCurrentChat]);

  // Добавлено логирование текущего чата при его изменении
  useEffect(() => {
    console.log('Current chat updated:', currentChat);
    // Сбрасываем ошибку при смене чата
    setError(null);
    // Сбрасываем входящие сообщения при смене чата
    setIncomingMessages([]);
  }, [currentChat]);

  // Проверяем, есть ли chat_id в state навигации
  useEffect(() => {
    const state = location.state as { chat_id?: string } | null;
    
    console.log('ChatPage - location.state:', state);
    console.log('ChatPage - chatLoadedFromStateRef.current:', chatLoadedFromStateRef.current);
    
    if (state?.chat_id && !chatLoadedFromStateRef.current) {
      console.log('Loading chat from navigation state:', state.chat_id);
      selectChat(state.chat_id).catch(error => {
        console.error('Error loading chat:', error);
      });
      chatLoadedFromStateRef.current = true;
    }
  }, [location.state, selectChat]);

  // Обработчик отправки сообщения с обработкой ошибок
  const handleSendMessage = async (message: string, photos: File[] = []) => {
    try {
      console.log('ChatPage - handleSendMessage:', message, 'photos:', photos.length);
      setError(null);
      await sendMessage(message, photos);
    } catch (err: any) {
      console.error('Error sending message:', err);
      setError(err.message || 'Ошибка при отправке сообщения');
      // Обновляем список чатов в случае ошибки, чтобы убедиться, что UI синхронизирован
      refreshChats();
    }
  };

  // Обработчик выбора фото
  const handlePhotoSelect = (file: File) => {
    // Создаем временный URL для превью
    const previewUrl = URL.createObjectURL(file);
    
    // Добавляем фото к списку
    setUploadedPhotos(prev => [...prev, file]);
    setPhotoPreviewUrls(prev => [...prev, previewUrl]);
    
    // Фото будет загружено на S3 только при отправке сообщения
  };

  // Удаление конкретного фото по индексу
  const handleRemovePhoto = (index: number) => {
    // Освобождаем URL
    if (photoPreviewUrls[index]) {
      URL.revokeObjectURL(photoPreviewUrls[index]);
    }
    
    // Удаляем фото из массивов
    setUploadedPhotos(prev => prev.filter((_, i) => i !== index));
    setPhotoPreviewUrls(prev => prev.filter((_, i) => i !== index));
  };

  // Очистка всех фото
  const handleClearAllPhotos = () => {
    // Освобождаем все URL
    photoPreviewUrls.forEach(url => URL.revokeObjectURL(url));
    
    setUploadedPhotos([]);
    setPhotoPreviewUrls([]);
  };

  // Обновляем позицию кнопок при изменении превью фото
  useEffect(() => {
    const updateButtonsPosition = () => {
      const textarea = document.querySelector('textarea[data-component-name="ChatInput"]') as HTMLTextAreaElement;
      const photoPreview = document.querySelector('.px-5.pt-2.pb-2.border-b') as HTMLElement;
      const buttonsContainer = document.querySelector('div[data-component-name="ChatPage"]');
      
      if (textarea && buttonsContainer) {
        const textareaExtraHeight = Math.max(0, textarea.clientHeight - 44);
        const photoHeight = photoPreview ? photoPreview.clientHeight : 0;
        const totalExtraHeight = textareaExtraHeight + photoHeight;
        
        buttonsContainer.setAttribute('style', `left: ${sidebarVisible ? '16rem' : '0'}; bottom: calc(5.5rem + ${totalExtraHeight}px)`);
      }
    };

    // Небольшая задержка чтобы DOM успел обновиться
    const timer = setTimeout(updateButtonsPosition, 50);
    return () => clearTimeout(timer);
  }, [photoPreviewUrls, sidebarVisible]);

  return (
    <div className="flex h-screen bg-dark-primary text-dark-text overflow-hidden">
      <div 
        className={`transition-all duration-300 ease-in-out ${sidebarVisible ? 'w-64 opacity-100' : 'w-0 opacity-0 overflow-hidden'}`}
      >
        <ChatSidebar />
      </div>
      
      <div className="flex-1 flex flex-col">
        <div className="border-b border-dark-border p-4 flex items-center relative">
          <div className="absolute left-4">
            <button 
              onClick={() => setSidebarVisible(!sidebarVisible)}
              className="text-dark-text hover:text-custom-blue focus:outline-none"
              title={sidebarVisible ? 'Скрыть панель' : 'Показать панель'}
              data-component-name="ChatPage"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" data-component-name="ChatPage">
                {sidebarVisible ? (
                  <path fillRule="evenodd" d="M2 4.75A.75.75 0 012.75 4h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 4.75zm0 10.5a.75.75 0 01.75-.75h7.5a.75.75 0 010 1.5h-7.5a.75.75 0 01-.75-.75zM2 10a.75.75 0 01.75-.75h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 10z" clipRule="evenodd" />
                ) : (
                  <path fillRule="evenodd" d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" clipRule="evenodd" />
                )}
              </svg>
            </button>
          </div>
          
          <div className="w-full flex justify-center items-center relative">
            <div className="max-w-[48rem] w-full text-center">
              <h2 
                className="text-lg font-medium" 
                data-component-name="ChatPage"
              >
                       {currentChat ? (currentChat.title || `Заявка #${currentChat.id.substring(0, 8)}`) : 'Новая заявка'}
              </h2>
            </div>
            
            {/* Кнопка закрытия тикета */}
            {currentChat && currentChat.id !== 'temp-id' && (
              <button
                onClick={() => setCloseTicketModalOpen(true)}
                className="absolute right-4 p-2 text-dark-text hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all duration-200"
                title="Закрыть тикет"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
          
          {/* Удален блок аккаунта, так как он перенесен в боковую панель */}
        </div>
        
        {error && (
          <div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-2">
            <p>{error}</p>
          </div>
        )}
        
        <ChatMessages 
          messages={currentChat?.messages || []} 
          isLoading={isLoading}
          onSendMessage={handleSendMessage}
        />
        
        <div className="mb-4" />
        
        <div 
          className="fixed left-0 right-0 flex justify-center space-x-4 px-4 transition-all duration-300 ease-in-out mb-2"
          style={{ 
            left: sidebarVisible ? '16rem' : '0',
            bottom: `calc(5.5rem + ${(document.querySelector('textarea[data-component-name="ChatInput"]')?.clientHeight || 44) - 44}px)`
          }}
          data-component-name="ChatPage"
        >
          <button
            onClick={() => !isLoading && createNewChat()}
            disabled={isLoading}
            className="px-3.5 py-1.5 text-sm text-dark-text border border-dark-border rounded-xl bg-dark-accent/90 hover:bg-dark-accent focus:outline-none focus:ring-2 focus:ring-custom-blue disabled:opacity-50 shadow-sm hover:shadow-md transition-all duration-300"
                   title="Создать новую заявку"
            data-component-name="ChatPage"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5 inline mr-1" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 3a1 1 0 00-1 1v5H4a1 1 0 100 2h5v5a1 1 0 102 0v-5h5a1 1 0 100-2h-5V4a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
                   новая заявка
          </button>
          
          <button
            onClick={() => {
              if (isLoading) return;
              
              // Создаем скрытый input для выбора файла
              const fileInput = document.createElement('input');
              fileInput.type = 'file';
              fileInput.accept = 'image/*';
              fileInput.style.display = 'none';
              
              // Обработчик выбора файла
              fileInput.onchange = (e) => {
                const target = e.target as HTMLInputElement;
                if (target.files && target.files.length > 0) {
                  const file = target.files[0];
                  handlePhotoSelect(file);
                }
              };
              
              // Добавляем input в DOM и имитируем клик
              document.body.appendChild(fileInput);
              fileInput.click();
              
              // Удаляем input из DOM после имитации клика
              setTimeout(() => {
                document.body.removeChild(fileInput);
              }, 1000);
            }}
            disabled={isLoading}
            className="px-3.5 py-1.5 text-sm text-dark-text border border-dark-border rounded-xl bg-dark-accent/90 hover:bg-dark-accent focus:outline-none focus:ring-2 focus:ring-custom-blue disabled:opacity-50 shadow-sm hover:shadow-md transition-all duration-300"
            title="Добавить фото"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5 inline mr-1" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 5a2 2 0 00-2 2v8a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-1.586a1 1 0 01-.707-.293l-1.121-1.121A2 2 0 0011.172 3H8.828a2 2 0 00-1.414.586L6.293 4.707A1 1 0 015.586 5H4zm6 9a3 3 0 100-6 3 3 0 000 6z" clipRule="evenodd" />
            </svg>
            добавить фото
          </button>
        </div>
        
        <form 
          onSubmit={(e) => {
            e.preventDefault();
            const textarea = document.querySelector('textarea[data-component-name="ChatInput"]') as HTMLTextAreaElement;
            if (textarea && (textarea.value.trim() || uploadedPhotos.length > 0) && !isLoading) {
              console.log('Sending message:', textarea.value, 'with photos:', uploadedPhotos.length);
              // Отправляем сообщение с фото на сервер
              handleSendMessage(textarea.value, uploadedPhotos);
              textarea.value = '';
              // Сбрасываем высоту после отправки
              textarea.style.height = 'auto';
              // Очищаем фото после отправки
              handleClearAllPhotos();
            }
          }} 
          className="fixed bottom-10 left-0 right-0 flex justify-center px-4 transition-all duration-300 ease-in-out"
          style={{ left: sidebarVisible ? '16rem' : '0' }}
          data-component-name="ChatPage"
        >
          <div 
            className="flex flex-col rounded-xl border border-dark-border overflow-hidden shadow-md bg-dark-accent/90 hover:bg-dark-accent transition-all duration-300 w-full max-w-[48rem] focus-within:bg-dark-accent"
          >
            {/* Превью загруженных фото */}
            {photoPreviewUrls.length > 0 && (
              <div className="px-5 pt-2 pb-2 border-b border-dark-border/30">
                <div className="flex flex-wrap gap-2">
                  {photoPreviewUrls.map((url, index) => (
                    <div key={index} className="relative inline-block">
                      <img 
                        src={url} 
                        alt={`Preview ${index + 1}`} 
                        className="w-12 h-12 object-cover rounded-md border border-dark-border/50"
                      />
                      
                      {/* Кнопка удаления */}
                      <button
                          type="button"
                          onClick={() => handleRemovePhoto(index)}
                          className="absolute -top-1 -right-1 w-4 h-4 bg-dark-secondary/90 hover:bg-dark-accent text-gray-400 hover:text-white rounded-full flex items-center justify-center transition-colors border border-dark-border/50"
                          title="Удалить фото"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-2.5 w-2.5" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                          </svg>
                        </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            <div className="flex items-center">
              <textarea
              placeholder="Введите сообщение..."
              disabled={isLoading}
              className="flex-1 px-5 py-[0.875rem] bg-transparent text-dark-text focus:outline-none disabled:opacity-50 resize-none min-h-[2.75rem] max-h-32 hide-scrollbar bg-dark-accent/90"
              style={{ 
                scrollbarWidth: 'none', 
                msOverflowStyle: 'none', 
                WebkitAppearance: 'none',
                transition: 'height 150ms ease-in-out, background-color 150ms ease-in-out'
              }}

              data-component-name="ChatInput"
              rows={1}
              onInput={(e) => {
                const textarea = e.target as HTMLTextAreaElement;
                
                // Если текст превышает максимальную высоту, включаем скролл
                // Сначала скрываем оверфлоу, чтобы избежать мерцания
                textarea.style.overflow = 'hidden';
                
                if (textarea.scrollHeight > 128) {
                  // Фиксируем максимальную высоту
                  textarea.style.height = '128px';
                  // Добавляем небольшую задержку перед включением скролла
                  setTimeout(() => {
                    textarea.style.overflow = 'auto';
                    textarea.classList.add('hide-scrollbar');
                  }, 50);
                } else {
                  textarea.style.height = 'auto';
                  textarea.style.height = `${textarea.scrollHeight}px`;
                }
                
                // Вычисляем дополнительную высоту для позиционирования кнопок
                const textareaExtraHeight = Math.max(0, textarea.clientHeight - 44);
                const photoPreview = document.querySelector('.px-5.pt-2.pb-2.border-b') as HTMLElement;
                const photoHeight = photoPreview ? photoPreview.clientHeight : 0;
                const totalExtraHeight = textareaExtraHeight + photoHeight;
                
                // Обновляем позицию кнопок при изменении высоты текстового поля
                const buttonsContainer = document.querySelector('div[data-component-name="ChatPage"]');
                if (buttonsContainer) {
                  buttonsContainer.setAttribute('style', `left: ${sidebarVisible ? '16rem' : '0'}; bottom: calc(5.5rem + ${totalExtraHeight}px)`);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  const textarea = e.target as HTMLTextAreaElement;
                  if ((textarea.value.trim() || uploadedPhotos.length > 0) && !isLoading) {
                    console.log('Sending message via Enter key:', textarea.value, 'with photos:', uploadedPhotos.length);
                    // Отправляем сообщение с фото на сервер
                    handleSendMessage(textarea.value, uploadedPhotos);
                    textarea.value = '';
                    // Сбрасываем высоту после отправки
                    textarea.style.height = 'auto';
                    // Очищаем фото после отправки
                    handleClearAllPhotos();
                  }
                }
              }}
            />
            <button
              type="submit"
              disabled={isLoading}
              className="h-10 w-10 flex items-center justify-center text-dark-text bg-dark-accent/90 hover:bg-dark-accent focus:outline-none focus:ring-2 focus:ring-custom-blue disabled:opacity-50 rounded-xl mr-1 transition-all duration-300"
              title="Отправить сообщение"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" data-component-name="ChatPage">
                <path fillRule="evenodd" d="M10.293 5.293a1 1 0 011.414 0l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414-1.414L12.586 11H5a1 1 0 110-2h7.586l-2.293-2.293a1 1 0 010-1.414z" clipRule="evenodd" data-component-name="ChatPage" />
              </svg>
            </button>
            </div>
          </div>
        </form>
      </div>
      
      {/* Модальное окно подтверждения закрытия тикета */}
      {closeTicketModalOpen && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => {
            setCloseTicketModalOpen(false);
            setTicketComment('');
          }}
        >
          <div 
            className="bg-dark-secondary border border-dark-border rounded-xl shadow-2xl p-6 max-w-md w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-xl font-medium text-white mb-4">Закрыть тикет</h3>
            <p className="text-dark-text mb-4">
              Вы уверены, что хотите закрыть это обращение? При необходимости оставьте комментарий.
            </p>
            
            {/* Комментарий */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-dark-text mb-2">
                Комментарий (опционально):
              </label>
              <textarea
                value={ticketComment}
                onChange={(e) => setTicketComment(e.target.value)}
                className="w-full px-3 py-2 bg-dark-primary border border-dark-border rounded-lg text-white placeholder-dark-text/50 focus:outline-none focus:ring-2 focus:ring-custom-blue resize-none"
                rows={3}
                placeholder="Укажите причину закрытия или дополнительные заметки..."
              />
            </div>
            
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => {
                  setCloseTicketModalOpen(false);
                  setTicketComment('');
                }}
                className="px-4 py-2 text-dark-text hover:text-white bg-dark-accent/30 hover:bg-dark-accent/50 rounded-lg transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={async () => {
                  try {
                    if (!currentChat?.id) {
                      console.error('No current chat selected');
                      return;
                    }
                    
                    console.log('Closing ticket:', currentChat.id, 'comment:', ticketComment);
                    
                    await closeTicket(currentChat.id, ticketComment || undefined);
                    
                    // Закрываем модальное окно и сбрасываем форму
                    setCloseTicketModalOpen(false);
                    setTicketComment('');
                  } catch (err: any) {
                    console.error('Error closing ticket:', err);
                    setError(err.message || 'Ошибка при закрытии тикета');
                  }
                }}
                disabled={isLoading}
                className="px-4 py-2 text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Закрытие...' : 'Закрыть тикет'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatPage;
