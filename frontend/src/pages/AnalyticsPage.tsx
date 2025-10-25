import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import ChatSidebar from '../components/ChatSidebar';
import api, { chatService } from '../services/api';

interface OperatorStats {
  operator_id: string;
  total_stats: number;
  average_rating: number | null;
  rating_distribution: { [key: string]: number };
}

interface RecentReview {
  rating: number;
  comment: string | null;
  date: string;
}

const AnalyticsPage: React.FC = () => {
  const { user } = useAuth();
  const [stats, setStats] = useState<OperatorStats | null>(null);
  const [recentReviews, setRecentReviews] = useState<RecentReview[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sidebarVisible, setSidebarVisible] = useState(true);

  useEffect(() => {
    loadAnalytics();
  }, [user]);

  const loadAnalytics = async () => {
    if (!user?.id) {
      setError('Пользователь не авторизован');
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);
      setError(null);

      // Получаем статистику оператора через nginx proxy (используем прямой URL без /api/v1 префикса)
      const response = await fetch(`/stats/stats/${user.id}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      
      if (response.status === 404) {
        // Если у оператора нет статистики - это нормально для новых операторов
        setError('У вас пока нет обработанных тикетов.\nНачните помогать клиентам, и здесь появится ваша статистика!');
        setIsLoading(false);
        return;
      }
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      setStats(data);

      // Получаем последние отзывы через новый API
      try {
        const reviewsData = await chatService.getLatestReviews(user.id);
        const formattedReviews: RecentReview[] = reviewsData.map((review: any) => ({
          rating: review.rating,
          comment: review.comment,
          date: review.closed_at || new Date().toISOString()
        }));
        setRecentReviews(formattedReviews);
      } catch (reviewsError) {
        console.error('Error loading reviews:', reviewsError);
        // Если не удалось загрузить отзывы, оставляем пустой массив
        setRecentReviews([]);
      }

    } catch (err: any) {
      console.error('Error loading analytics:', err);
      setError('Не удалось загрузить статистику. Попробуйте позже.');
    } finally {
      setIsLoading(false);
    }
  };

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
    
    return new Date(dateString).toLocaleDateString('ru-RU');
  };

  const getRatingColor = (rating: number) => {
    if (rating >= 4.5) return 'text-green-400';
    if (rating >= 3.5) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getRatingStars = (rating: number) => {
    return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
  };

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
        {/* Header */}
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
            <h2 className="text-lg font-medium">Аналитика работы</h2>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-custom-blue mb-4"></div>
                <p className="text-dark-text">Загрузка статистики...</p>
              </div>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center max-w-md">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-16 w-16 mx-auto mb-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <p className="text-white text-xl font-medium mb-2">
                  {error.split('\n')[0]}
                </p>
                <p className="text-dark-text/70">
                  {error.split('\n')[1]}
                </p>
              </div>
            </div>
          ) : stats ? (
            <div className="max-w-6xl mx-auto space-y-6">
              {/* Основная статистика */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Средний рейтинг */}
                <div className="bg-dark-secondary border border-dark-border rounded-xl p-6 hover:border-custom-blue/50 transition-all">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm text-dark-text/70">Средний рейтинг</h3>
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                    </svg>
                  </div>
                  <div className={`text-4xl font-bold ${stats.average_rating ? getRatingColor(stats.average_rating) : 'text-gray-500'}`}>
                    {stats.average_rating ? stats.average_rating.toFixed(1) : 'N/A'}
                  </div>
                </div>

                {/* Обработано тикетов */}
                <div className="bg-dark-secondary border border-dark-border rounded-xl p-6 hover:border-custom-blue/50 transition-all">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm text-dark-text/70">Обработано тикетов</h3>
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-custom-blue" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                      <path fillRule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm9.707 5.707a1 1 0 00-1.414-1.414L9 12.586l-1.293-1.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div className="text-4xl font-bold text-white">
                    {stats.total_stats}
                  </div>
                  <p className="text-xs text-dark-text/50 mt-2">С момента начала работы</p>
                </div>

                {/* Успешных решений */}
                <div className="bg-dark-secondary border border-dark-border rounded-xl p-6 hover:border-custom-blue/50 transition-all">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm text-dark-text/70">Отличных оценок</h3>
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div className="text-4xl font-bold text-green-400">
                    {stats.rating_distribution['5'] || 0}
                  </div>
                  <p className="text-xs text-dark-text/50 mt-2">Оценок 5/5</p>
                </div>
              </div>

              {/* Распределение оценок */}
              <div className="bg-dark-secondary border border-dark-border rounded-xl p-6">
                <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-custom-blue" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
                  </svg>
                  Распределение оценок
                </h3>
                
                <div className="space-y-3">
                  {[5, 4, 3, 2, 1].map(rating => {
                    const count = stats.rating_distribution[rating.toString()] || 0;
                    const percentage = stats.total_stats > 0 ? (count / stats.total_stats) * 100 : 0;
                    
                    return (
                      <div key={rating} className="flex items-center gap-3">
                        <div className="flex items-center gap-2 w-16">
                          <div className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-custom-blue bg-custom-blue bg-opacity-20">
                            {rating}
                          </div>
                        </div>
                        
                        <div className="flex-1 h-8 bg-dark-accent/30 rounded-lg overflow-hidden">
                          <div 
                            className="h-full bg-gradient-to-r from-custom-blue to-custom-blue/60 transition-all duration-500 flex items-center justify-end pr-3"
                            style={{ width: `${percentage}%` }}
                          >
                            {count > 0 && (
                              <span className="text-xs font-medium text-white">{count}</span>
                            )}
                          </div>
                        </div>
                        
                        <div className="w-16 text-right text-sm text-dark-text/70">
                          {percentage.toFixed(0)}%
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Последние отзывы */}
              <div className="bg-dark-secondary border border-dark-border rounded-xl p-6">
                <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-custom-blue" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clipRule="evenodd" />
                  </svg>
                  Последние отзывы
                </h3>
                
                {recentReviews.length === 0 ? (
                  <p className="text-center text-dark-text/50 py-8">Пока нет отзывов</p>
                ) : (
                  <div className="space-y-3">
                    {recentReviews.map((review, index) => (
                      <div 
                        key={index}
                        className="bg-dark-accent/30 border border-dark-border/50 rounded-lg p-4 hover:border-custom-blue/30 transition-all"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <div className="text-custom-blue text-lg">
                              {getRatingStars(review.rating)}
                            </div>
                            <span className="text-sm font-medium text-custom-blue">
                              {review.rating}/5
                            </span>
                          </div>
                          <span className="text-xs text-dark-text/50">
                            {getRelativeTime(review.date)}
                          </span>
                        </div>
                        {review.comment && (
                          <p className="text-sm text-dark-text/80 italic">
                            "{review.comment}"
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Дополнительная информация */}
              <div className="bg-dark-secondary border border-dark-border rounded-xl p-6">
                <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-custom-blue" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                  </svg>
                  Дополнительная информация
                </h3>
                
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-dark-text/50 mb-1">Оператор</p>
                    <p className="text-white">{user?.name || 'Не указано'}</p>
                  </div>
                  <div>
                    <p className="text-dark-text/50 mb-1">Email</p>
                    <p className="text-white">{user?.email || 'Не указан'}</p>
                  </div>
                  <div>
                    <p className="text-dark-text/50 mb-1">Положительных отзывов</p>
                    <p className="text-green-400 font-medium">
                      {((stats.rating_distribution['5'] || 0) + (stats.rating_distribution['4'] || 0))} 
                      <span className="text-xs ml-1">
                        ({stats.total_stats > 0 ? (((stats.rating_distribution['5'] || 0) + (stats.rating_distribution['4'] || 0)) / stats.total_stats * 100).toFixed(0) : 0}%)
                      </span>
                    </p>
                  </div>
                  <div>
                    <p className="text-dark-text/50 mb-1">Требуют улучшения</p>
                    <p className="text-yellow-400 font-medium">
                      {((stats.rating_distribution['3'] || 0) + (stats.rating_distribution['2'] || 0) + (stats.rating_distribution['1'] || 0))}
                      <span className="text-xs ml-1">
                        ({stats.total_stats > 0 ? (((stats.rating_distribution['3'] || 0) + (stats.rating_distribution['2'] || 0) + (stats.rating_distribution['1'] || 0)) / stats.total_stats * 100).toFixed(0) : 0}%)
                      </span>
                    </p>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default AnalyticsPage;

