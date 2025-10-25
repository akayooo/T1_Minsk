import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import ChatSidebar from '../components/ChatSidebar';
import { chatService } from '../services/api';

interface Ticket {
  user_id: string;
  telegram_chat_id: number;
  title: string;
  first_message: string;
  priority: 'высокая' | 'средняя' | 'низкая';
  status: 'pending' | 'assigned' | 'closed';
  created_at: string;
  assigned_to?: string; // ID оператора, который взял заявку
  assigned_at?: string; // Время взятия заявки
}

type PriorityFilter = 'все' | 'высокая' | 'средняя' | 'низкая';
type CategoryFilter = 'все темы' | 'технические' | 'финансовые' | 'общие';
type SortType = 'по времени' | 'по срочности';

const AllTicketsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [pendingTickets, setPendingTickets] = useState<Ticket[]>([]);
  const [assignedTickets, setAssignedTickets] = useState<Ticket[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [sidebarVisible, setSidebarVisible] = useState(true);
  
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('все темы');
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>('все');
  const [sortType, setSortType] = useState<SortType>('по времени');

  useEffect(() => {
    loadTickets();
  }, []);

  const loadTickets = async () => {
    try {
      setIsLoading(true);
      
      // Получаем ожидающие заявки
      const pendingChats = await chatService.getPendingChats();
      
      // Получаем заявки назначенные текущему оператору
      const assignedChats = await chatService.getAssignedChats();
      
      // Преобразуем данные с backend в формат Ticket
      const pendingTicketsData: Ticket[] = pendingChats.map((chat: any) => ({
        user_id: chat.user_id,
        telegram_chat_id: chat.telegram_chat_id,
        title: chat.title || 'Без названия',
        first_message: chat.first_message || '',
        priority: 'средняя', // TODO: Добавить приоритет в базу данных
        status: 'pending',
        created_at: chat.created_at
      }));
      
      const assignedTicketsData: Ticket[] = assignedChats.map((chat: any) => ({
        user_id: chat.user_id,
        telegram_chat_id: chat.telegram_chat_id,
        title: chat.title || 'Без названия',
        first_message: chat.first_message || '',
        priority: 'средняя', // TODO: Добавить приоритет в базу данных
        status: 'assigned',
        created_at: chat.created_at,
        assigned_to: chat.operator_id,
        assigned_at: chat.assigned_at
      }));
      
      setPendingTickets(pendingTicketsData);
      setAssignedTickets(assignedTicketsData);
    } catch (error) {
      console.error('Ошибка загрузки заявок:', error);
      // В случае ошибки показываем пустые списки
      setPendingTickets([]);
      setAssignedTickets([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleTakeTicket = async (userId: string, telegramChatId: number) => {
    try {
      console.log('=== ВЗЯТИЕ ЗАЯВКИ ===');
      console.log('Взята заявка:', userId);
      console.log('telegramChatId:', telegramChatId);
      console.log('user?.id:', user?.id);
      console.log('user?.email:', user?.email);
      
      // Реальный API вызов для назначения оператора
      if (user?.id) {
        try {
          await chatService.assignOperator(userId, user.id);
        } catch (error: any) {
          // Если чат уже назначен, все равно переходим в него
          if (error.response?.status === 400 && 
              error.response?.data?.detail?.includes('уже назначен')) {
            console.log('Чат уже назначен, переходим в него');
          } else {
            throw error; // Перебрасываем другие ошибки
          }
        }
        
        // Находим заявку в списке ожидающих
        const ticketToMove = pendingTickets.find(ticket => ticket.user_id === userId);
        
        if (ticketToMove) {
          // Удаляем из списка ожидающих
          setPendingTickets(prevTickets => 
            prevTickets.filter(ticket => ticket.user_id !== userId)
          );
          
          // Добавляем в список взятых в работу
          const assignedTicket: Ticket = {
            ...ticketToMove,
            status: 'assigned',
            assigned_to: user?.id || user?.email || 'current_operator',
            assigned_at: new Date().toISOString()
          };
          
          setAssignedTickets(prevAssigned => [assignedTicket, ...prevAssigned]);
        }
        
        // Переходим в чат с этой заявкой только после успешного назначения
        console.log('Переходим в чат с userId:', userId);
        navigate('/', { state: { chat_id: userId } });
        console.log('Навигация выполнена');
      }
      
    } catch (error) {
      console.error('Ошибка взятия заявки:', error);
      // Перезагружаем список заявок в случае ошибки
      loadTickets();
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'высокая': return 'text-red-400 bg-red-500/10 border-red-500/30';
      case 'средняя': return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30';
      case 'низкая': return 'text-green-400 bg-green-500/10 border-green-500/30';
      default: return 'text-gray-400 bg-gray-500/10 border-gray-500/30';
    }
  };

  const getTimeAgo = (dateString: string) => {
    const now = new Date().getTime();
    const created = new Date(dateString).getTime();
    const diffMs = now - created;
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'только что';
    if (diffMins < 60) return `${diffMins} мин. назад`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} ч. назад`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} дн. назад`;
  };

  const applyFiltersAndSort = (tickets: Ticket[]) => {
    let result = [...tickets];

    // Фильтр по приоритету
    if (priorityFilter !== 'все') {
      result = result.filter(ticket => ticket.priority === priorityFilter);
    }

    // Сортировка
    if (sortType === 'по времени') {
      result.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    } else if (sortType === 'по срочности') {
      const priorityOrder = { 'высокая': 0, 'средняя': 1, 'низкая': 2 };
      result.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
    }

    return result;
  };

  const filteredPendingTickets = applyFiltersAndSort(pendingTickets);
  const filteredAssignedTickets = applyFiltersAndSort(assignedTickets);

  return (
    <div className="flex h-screen bg-dark-primary text-dark-text overflow-hidden">
      {/* Sidebar */}
      <div 
        className={`transition-all duration-300 ease-in-out ${sidebarVisible ? 'w-64 opacity-100' : 'w-0 opacity-0 overflow-hidden'}`}
      >
        <ChatSidebar />
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="border-b border-dark-border p-4 flex items-center relative">
          <div className="absolute left-4">
            <button 
              onClick={() => setSidebarVisible(!sidebarVisible)}
              className="text-dark-text hover:text-custom-blue focus:outline-none"
              title={sidebarVisible ? 'Скрыть панель' : 'Показать панель'}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                {sidebarVisible ? (
                  <path fillRule="evenodd" d="M2 4.75A.75.75 0 012.75 4h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 4.75zm0 10.5a.75.75 0 01.75-.75h7.5a.75.75 0 010 1.5h-7.5a.75.75 0 01-.75-.75zM2 10a.75.75 0 01.75-.75h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 10z" clipRule="evenodd" />
                ) : (
                  <path fillRule="evenodd" d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" clipRule="evenodd" />
                )}
              </svg>
            </button>
          </div>
          
          <div className="w-full flex justify-center">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-white">Все заявки</h1>
            </div>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-7xl mx-auto px-6 py-6">
            
            {/* Filters */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex gap-3">
                <button
                  onClick={() => setCategoryFilter('все темы')}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-all border ${
                    categoryFilter === 'все темы'
                      ? 'bg-custom-blue/20 text-custom-blue border-custom-blue/30 shadow-md'
                      : 'bg-dark-accent/40 text-gray-300 hover:bg-dark-accent/60 border-dark-border/50'
                  }`}
                >
                  Все темы
                </button>
                
                <div className="relative group">
                  <button className="px-4 py-2 rounded-lg text-sm font-medium bg-dark-accent/40 text-gray-300 hover:bg-dark-accent/60 transition-all flex items-center gap-2">
                    Любая срочность
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </button>
                </div>
                
                <div className="relative group">
                  <button className="px-4 py-2 rounded-lg text-sm font-medium bg-dark-accent/40 text-gray-300 hover:bg-dark-accent/60 transition-all flex items-center gap-2">
                    {sortType}
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-2 text-sm text-gray-400">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                  <path fillRule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z" clipRule="evenodd" />
                </svg>
                Всего заявок: <span className="text-white font-semibold">{pendingTickets.length + assignedTickets.length}</span>
              </div>
            </div>

            {/* Loading State */}
            {isLoading ? (
              <div className="flex items-center justify-center py-20">
                <div className="relative w-12 h-12">
                  <div className="absolute inset-0 border-4 border-custom-blue/20 rounded-full"></div>
                  <div className="absolute inset-0 border-4 border-transparent border-t-custom-blue rounded-full animate-spin"></div>
                </div>
              </div>
            ) : (
              <div className="space-y-8">
                
                {/* Pending Tickets Section */}
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                      Ожидают ответа ({filteredPendingTickets.length})
                    </h2>
                  </div>
                  
                  {filteredPendingTickets.length === 0 ? (
                    <div className="text-center py-12 bg-dark-secondary/30 rounded-lg border border-dark-border/50">
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 text-green-400 mx-auto mb-3" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                      <p className="text-gray-400">Нет заявок в ожидании</p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {filteredPendingTickets.map((ticket) => (
                        <div
                          key={ticket.user_id}
                          onClick={() => navigate(`/?chat_id=${ticket.user_id}`)}
                          className="bg-dark-secondary border border-dark-border rounded-lg p-5 hover:border-custom-blue/30 transition-all duration-300 hover:shadow-lg cursor-pointer h-48 flex flex-col justify-between"
                        >
                          <div>
                            <div className="flex items-start justify-between mb-3">
                              <h3 className="text-white font-medium text-lg pr-2 line-clamp-2">
                                {ticket.title}
                              </h3>
                              <span className={`px-2 py-1 rounded-full text-xs font-medium border ${getPriorityColor(ticket.priority)}`}>
                                {ticket.priority}
                              </span>
                            </div>
                            
                            <p className="text-gray-300 text-sm line-clamp-3">
                              {ticket.first_message.length > 100 
                                ? `${ticket.first_message.substring(0, 100)}...` 
                                : ticket.first_message
                              }
                            </p>
                          </div>
                          
                          <div className="flex items-center justify-between pt-3 border-t border-dark-border/50 mt-auto">
                            <div className="flex items-center gap-2 text-xs text-gray-500">
                              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                              </svg>
                              {getTimeAgo(ticket.created_at)}
                            </div>
                            
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTakeTicket(ticket.user_id, ticket.telegram_chat_id);
                              }}
                              className="px-4 py-2 bg-custom-blue/20 hover:bg-custom-blue/30 text-custom-blue text-sm font-medium rounded-lg transition-all duration-200 border border-custom-blue/30 hover:border-custom-blue/50"
                            >
                              Взять в работу
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Assigned Tickets Section */}
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                      В работе ({filteredAssignedTickets.length})
                    </h2>
                  </div>
                  
                  {filteredAssignedTickets.length === 0 ? (
                    <div className="text-center py-12 bg-dark-secondary/30 rounded-lg border border-dark-border/50">
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 text-gray-400 mx-auto mb-3" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
                      </svg>
                      <p className="text-gray-400">Нет заявок в работе</p>
                      <p className="text-gray-500 text-sm mt-1">Взятые заявки будут отображаться здесь</p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {filteredAssignedTickets.map((ticket) => (
                        <div
                          key={ticket.user_id}
                          onClick={() => navigate(`/?chat_id=${ticket.user_id}`)}
                          className="bg-dark-secondary border border-green-500/20 rounded-lg p-5 hover:border-green-500/40 transition-all duration-300 hover:shadow-lg cursor-pointer h-48 flex flex-col justify-between"
                        >
                          <div>
                            <div className="flex items-start justify-between mb-3">
                              <h3 className="text-white font-medium text-lg pr-2 line-clamp-2">
                                {ticket.title}
                              </h3>
                              <span className={`px-2 py-1 rounded-full text-xs font-medium border ${getPriorityColor(ticket.priority)}`}>
                                {ticket.priority}
                              </span>
                            </div>
                            
                            <p className="text-gray-300 text-sm line-clamp-3">
                              {ticket.first_message.length > 100 
                                ? `${ticket.first_message.substring(0, 100)}...` 
                                : ticket.first_message
                              }
                            </p>
                          </div>
                          
                          <div className="flex items-center pt-3 border-t border-dark-border/50 mt-auto">
                            <div className="flex items-center gap-2 text-xs text-gray-500">
                              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                              </svg>
                              Взято {ticket.assigned_at ? getTimeAgo(ticket.assigned_at) : 'недавно'}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AllTicketsPage;