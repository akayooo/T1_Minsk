import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { authService } from '../services/api';
import { User, LoginRequest, RegisterRequest } from '../types';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (data: LoginRequest) => Promise<void>;
  register: (data: RegisterRequest) => Promise<void>;
  logout: () => void;
  error: string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Проверяем, есть ли токен в localStorage
    const checkAuth = async () => {
      try {
        const isAuth = authService.isAuthenticated();
        if (isAuth) {
          try {
            // Пытаемся получить данные пользователя из localStorage
            const storedUser = localStorage.getItem('user');
            if (storedUser) {
              const userData = JSON.parse(storedUser);
              setUser(userData);
            } else {
              // Если данных нет, используем загрушку
              const defaultUser = { id: 'user-id', name: 'User', email: 'user@example.com' };
              setUser(defaultUser);
              // Сохраняем загрушку в localStorage
              localStorage.setItem('user', JSON.stringify(defaultUser));
            }
          } catch (error) {
            console.error('Failed to parse user data:', error);
            // В случае ошибки используем загрушку
            const defaultUser = { id: 'user-id', name: 'User', email: 'user@example.com' };
            setUser(defaultUser);
            // Сохраняем загрушку в localStorage
            localStorage.setItem('user', JSON.stringify(defaultUser));
          }
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        authService.logout();
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, []);

  const login = async (data: LoginRequest) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await authService.login(data);
      // Создаем объект пользователя, используя данные, полученные с сервера
      const userData = { 
        id: response?.user_id || 'user-id', 
        name: response?.name || data.login, 
        email: response?.email || `${data.login}@example.com` 
      };
      
      // Сохраняем данные пользователя в localStorage
      localStorage.setItem('user', JSON.stringify(userData));
      
      // Устанавливаем данные пользователя в состоянии
      setUser(userData);
      
      // Добавляем событие для оповещения других компонентов о смене токена
      window.dispatchEvent(new Event('storage'));
      console.log('AuthContext - Login successful, storage event dispatched');
    } catch (err: any) {
      setError(err.response?.data?.error || 'Ошибка авторизации');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const register = async (data: RegisterRequest) => {
    setIsLoading(true);
    setError(null);
    try {
      await authService.register(data);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Ошибка регистрации');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    authService.logout();
    // Удаляем данные пользователя из localStorage
    localStorage.removeItem('user');
    setUser(null);
    
    // Добавляем событие для оповещения других компонентов о выходе из системы
    window.dispatchEvent(new CustomEvent('logout'));
    console.log('AuthContext - Logout completed, logout event dispatched');
  };

  const value = {
    user,
    isAuthenticated: !!user,
    isLoading,
    login,
    register,
    logout,
    error,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
