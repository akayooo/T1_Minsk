import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useChat } from '../context/ChatContext';
import { useAuth } from '../context/AuthContext';
import { Chat } from '../types';

const ChatSidebar: React.FC = () => {
  const navigate = useNavigate();
  const { chats, currentChat, selectChat, createNewChat, deleteChat, isLoading } = useChat();
  const { user, logout } = useAuth();
  const [showAccountDropdown, setShowAccountDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Закрываем выпадающее меню при клике вне его
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowAccountDropdown(false);
      }
    }
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const handleSelectChat = (chatId: string) => {
    if (!isLoading) {
      selectChat(chatId);
      // Если мы не на главной странице, переходим на неё
      if (window.location.pathname !== '/') {
        navigate('/');
      }
    }
  };

  const handleCreateNewChat = () => {
    if (!isLoading) {
      createNewChat();
      // Если мы не на главной странице, переходим на неё
      if (window.location.pathname !== '/') {
        navigate('/');
      }
    }
  };

  const handleDeleteChat = (e: React.MouseEvent, chatId: string) => {
    e.stopPropagation();
    if (!isLoading) {
      deleteChat(chatId);
    }
  };


  // Форматирование даты для заголовка группы
  const formatGroupDate = (dateString: string) => {
    const date = new Date(dateString);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    
    if (date.toDateString() === today.toDateString()) {
      return 'Сегодня';
    } else if (date.toDateString() === yesterday.toDateString()) {
      return 'Вчера';
    } else {
      return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
    }
  };

  // Форматирование относительного времени
  const getRelativeTime = (dateString: string) => {
    const now = new Date().getTime();
    const date = new Date(dateString).getTime();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'только что';
    if (diffMins < 60) return `${diffMins} мин. назад`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} ч. назад`;
    
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) return 'вчера';
    if (diffDays === 2) return 'позавчера';
    if (diffDays < 7) return `${diffDays} дн. назад`;
    if (diffDays < 30) {
      const weeks = Math.floor(diffDays / 7);
      return `${weeks} нед. назад`;
    }
    
    const diffMonths = Math.floor(diffDays / 30);
    return `${diffMonths} мес. назад`;
  };

  // Получение текста превью для чата
  const getPreviewText = (chat: Chat) => {
    if (chat.messages && chat.messages.length > 0) {
      const lastMessage = chat.messages[chat.messages.length - 1];
      return lastMessage.content.substring(0, 50) + (lastMessage.content.length > 50 ? '...' : '');
    }
    // Если сообщений нет, показываем заглушку
    return "Нет сообщений";
  };

  // Группировка чатов по дате создания
  const groupChatsByDate = (chats: Chat[]) => {
    const groups: { [key: string]: Chat[] } = {};
    
    // Сортировка чатов по дате создания (от новых к старым)
    const sortedChats = [...chats].sort((a, b) => 
      new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
    
    sortedChats.forEach(chat => {
      const date = new Date(chat.createdAt);
      const dateKey = date.toDateString(); // Используем toDateString как ключ для группировки
      
      if (!groups[dateKey]) {
        groups[dateKey] = [];
      }
      
      groups[dateKey].push(chat);
    });
    
    return groups;
  };

  // Группируем чаты по дате
  const chatGroups = groupChatsByDate(chats);
  
  return (
    <div className="h-full w-64 bg-dark-primary border-r border-dark-border/60 flex flex-col">
      <div className="p-4 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <img src="/t1.png" alt="T1 Logo" className="h-5 w-5" />
          <h2 className="text-lg font-medium text-white">Поддержка</h2>
        </div>
      </div>
      
      
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="p-4 space-y-5">
          {Object.keys(chatGroups).length === 0 ? (
            <div className="text-center py-8 text-dark-text opacity-70 flex flex-col items-center">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 text-gray-500 mb-2 opacity-50" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clipRule="evenodd" />
              </svg>
                     <p>У вас пока нет заявок</p>
                     <p className="text-sm mt-1">Создайте новую заявку, чтобы начать работу</p>
            </div>
          ) : (
            Object.entries(chatGroups).map(([dateKey, chatsInGroup]) => (
              <div key={dateKey} className="mb-6 last:mb-0">
                <h3 className="text-xs uppercase text-gray-500 mb-2 px-2">{formatGroupDate(dateKey)}</h3>
                
                {chatsInGroup.map(chat => (
                  <div 
                    key={chat.id}
                    onClick={() => handleSelectChat(chat.id)}
                    className={`p-3 rounded-md cursor-pointer transition-all duration-300 group ${
                      currentChat && currentChat.id === chat.id 
                        ? 'bg-custom-blue/10 shadow-md' 
                        : 'hover:bg-dark-accent/30'
                    }`}
                    data-component-name="ChatSidebar"
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex-1 min-w-0" data-component-name="ChatSidebar">
                               <p className="text-sm truncate flex items-center text-white" data-component-name="ChatSidebar">
                                 <span className="truncate">{chat.title || `Заявка #${chat.id.substring(0, 8)}`}</span>
                               </p>
                        <p className="text-xs truncate mt-1 text-gray-300">
                          {getPreviewText(chat)}
                        </p>
                      </div>
                      <button 
                        className="ml-2 p-1.5 text-gray-400 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-500/10 rounded-full transition-all duration-200 focus:outline-none"
                        onClick={(e) => handleDeleteChat(e, chat.id)}
                               title="Удалить заявку"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                        </svg>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </div>
      
      {/* Дополнительные кнопки действий */}
      <div className="mt-auto px-4 py-3 border-t border-dark-border/60 space-y-2">
        <button 
          onClick={() => navigate('/tickets')}
          className="w-full py-2 px-3 text-sm text-dark-text hover:text-white bg-dark-accent/30 hover:bg-dark-accent/50 rounded-lg transition-colors flex items-center justify-start gap-2"
          title="Все заявки"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
            <path fillRule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z" clipRule="evenodd" />
          </svg>
          Все заявки
        </button>
        
        <button 
          onClick={() => navigate('/analytics')}
          className="w-full py-2 px-3 text-sm text-dark-text hover:text-white bg-dark-accent/30 hover:bg-dark-accent/50 rounded-lg transition-colors flex items-center justify-start gap-2"
          title="Аналитика"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
          </svg>
          Аналитика
        </button>
      </div>
      
      {/* Блок аккаунта в самом низу боковой панели */}
      <div className="p-4 border-t border-dark-border/60 relative" ref={dropdownRef}>
        <div 
          className="flex items-center cursor-pointer"
          onClick={() => setShowAccountDropdown(!showAccountDropdown)}
        >
          <div className="w-10 h-10 rounded-lg bg-dark-accent flex items-center justify-center text-white shadow-md relative mr-3 border border-dark-border/50 hover:border-custom-blue/30 transition-colors">
            <span className="text-lg font-medium">{user?.name ? user.name.charAt(0).toUpperCase() : 'U'}</span>
          </div>
          <div className="flex-1">
            <p className="text-sm font-medium text-dark-text">{user?.name || 'Пользователь'}</p>
            <p className="text-xs text-gray-400">{user?.email || 'email@example.com'}</p>
          </div>
          <div className="ml-2">
            <svg 
              xmlns="http://www.w3.org/2000/svg" 
              className={`h-4 w-4 text-gray-400 transition-transform ${showAccountDropdown ? 'rotate-180' : ''}`} 
              viewBox="0 0 20 20" 
              fill="currentColor"
            >
              <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </div>
        </div>
        
        {/* Выпадающее меню аккаунта */}
        {showAccountDropdown && (
          <div className="absolute bottom-full left-0 right-0 mx-auto w-56 bg-dark-secondary border border-dark-border/50 rounded-lg shadow-xl overflow-hidden animate-fade-in z-10 mb-2">
            <div className="p-3">
              <div className="flex items-center mb-3 pb-3 border-b border-dark-border/30">
                <div className="w-10 h-10 rounded-lg bg-dark-accent flex items-center justify-center text-white shadow-md">
                  <span className="text-lg font-medium">{user?.name ? user.name.charAt(0).toUpperCase() : 'U'}</span>
                </div>
                <div className="ml-3">
                  <p className="text-sm font-medium text-white">{user?.name || 'Пользователь'}</p>
                  <p className="text-xs text-gray-400 truncate max-w-[160px]">{user?.email || 'email@example.com'}</p>
                </div>
              </div>
              
              <div className="space-y-1">
                <button 
                  onClick={() => {
                    setShowAccountDropdown(false);
                    logout();
                  }}
                  className="w-full text-left py-2.5 px-3 rounded-md hover:bg-dark-accent/30 flex items-center text-gray-200 transition-colors duration-200"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 mr-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                    <polyline points="16 17 21 12 16 7"></polyline>
                    <line x1="21" y1="12" x2="9" y2="12"></line>
                  </svg>
                  <span className="text-sm">Выйти</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatSidebar;
