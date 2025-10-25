import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Link, useNavigate } from 'react-router-dom';

const RegisterForm: React.FC = () => {
  const { register, isLoading, error } = useAuth();
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    setFormError(null);
  };

  const validateEmail = (email: string): boolean => {
    // Простая проверка формата email
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // Сбрасываем ошибки
    setFormError(null);
    
    // Проверка заполнения полей
    if (!formData.name || !formData.email || !formData.password || !formData.confirmPassword) {
      setFormError('Пожалуйста, заполните все поля');
      return;
    }
    
    // Проверка формата email
    if (!validateEmail(formData.email)) {
      setFormError('Пожалуйста, введите корректный email');
      return;
    }
    
    // Проверка совпадения паролей
    if (formData.password !== formData.confirmPassword) {
      setFormError('Пароли не совпадают');
      return;
    }
    
    // Проверка длины пароля
    if (formData.password.length < 6) {
      setFormError('Пароль должен содержать не менее 6 символов');
      return;
    }
    
    setIsSubmitting(true);
    
    try {
      await register({
        name: formData.name,
        email: formData.email,
        password: formData.password,
      });
      
      // После успешной регистрации перенаправляем на страницу входа
      navigate('/login', { 
        state: { 
          message: 'Регистрация успешна! Теперь вы можете войти в систему.',
          email: formData.email
        } 
      });
    } catch (err: any) {
      // Обрабатываем конкретные ошибки
      const errorMessage = err.response?.data?.error || 'Произошла ошибка при регистрации';
      setFormError(errorMessage);
      
      // Если ошибка связана с отправкой email, показываем специальное сообщение
      if (errorMessage.includes('отправить код') || errorMessage.includes('email')) {
        setFormError('Не удалось отправить код подтверждения на указанный email. Пожалуйста, проверьте правильность email и попробуйте снова.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      {(error || formError) && (
        <div className="p-4 text-sm text-red-500 bg-dark-accent/50 rounded-lg border border-red-500/50 animate-fade-in mb-4 backdrop-blur-sm">
          <div className="flex items-center">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-red-500 mr-2 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <span>{formError || error}</span>
          </div>
        </div>
      )}
      
      <div className="space-y-4">
        <div className="relative">
          <label htmlFor="name" className="block text-sm font-medium text-gray-300 mb-1.5">
            Имя
          </label>
          <div className="group relative">
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-gray-500 group-focus-within:text-custom-blue transition-colors" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
              </svg>
            </div>
            <input
              id="name"
              name="name"
              type="text"
              required
              value={formData.name}
              onChange={handleChange}
              className="w-full pl-11 pr-4 py-3 text-white bg-dark-accent/70 border border-custom-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-custom-blue/50 focus:border-custom-blue/50 transition-all duration-200 placeholder-gray-500"
              placeholder="Введите ваше имя"
            />
          </div>
        </div>
        
        <div className="relative">
          <label htmlFor="email" className="block text-sm font-medium text-gray-300 mb-1.5">
            Email
          </label>
          <div className="group relative">
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-gray-500 group-focus-within:text-custom-blue transition-colors" viewBox="0 0 20 20" fill="currentColor">
                <path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z" />
                <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z" />
              </svg>
            </div>
            <input
              id="email"
              name="email"
              type="email"
              required
              value={formData.email}
              onChange={handleChange}
              className="w-full pl-11 pr-4 py-3 text-white bg-dark-accent/70 border border-custom-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-custom-blue/50 focus:border-custom-blue/50 transition-all duration-200 placeholder-gray-500"
              placeholder="Введите ваш email"
            />
          </div>
        </div>
        
        <div className="relative">
          <label htmlFor="password" className="block text-sm font-medium text-gray-300 mb-1.5">
            Пароль
          </label>
          <div className="group relative">
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-gray-500 group-focus-within:text-custom-blue transition-colors" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
              </svg>
            </div>
            <input
              id="password"
              name="password"
              type="password"
              required
              value={formData.password}
              onChange={handleChange}
              className="w-full pl-11 pr-4 py-3 text-white bg-dark-accent/70 border border-custom-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-custom-blue/50 focus:border-custom-blue/50 transition-all duration-200 placeholder-gray-500"
              placeholder="Введите пароль"
            />
          </div>
          <p className="text-xs text-gray-500 mt-1 ml-1">Минимум 6 символов</p>
        </div>
        
        <div className="relative">
          <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-300 mb-1.5">
            Подтверждение пароля
          </label>
          <div className="group relative">
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-gray-500 group-focus-within:text-custom-blue transition-colors" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
              </svg>
            </div>
            <input
              id="confirmPassword"
              name="confirmPassword"
              type="password"
              required
              value={formData.confirmPassword}
              onChange={handleChange}
              className="w-full pl-11 pr-4 py-3 text-white bg-dark-accent/70 border border-custom-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-custom-blue/50 focus:border-custom-blue/50 transition-all duration-200 placeholder-gray-500"
              placeholder="Подтвердите пароль"
            />
          </div>
        </div>
      </div>
      
      <div className="pt-2">
        <button
          type="submit"
          disabled={isLoading || isSubmitting}
          className="w-full px-4 py-2.5 text-white bg-dark-accent border border-custom-border rounded-md hover:bg-dark-secondary hover:border-custom-blue focus:outline-none focus:ring-2 focus:ring-custom-blue/50 focus:ring-offset-1 focus:ring-offset-dark-secondary disabled:opacity-50 transition-all duration-200 shadow-md hover:shadow-[0_0_10px_rgba(59,130,246,0.3)] font-medium tracking-wide text-base relative"
        >
          <span className="relative z-10 whitespace-nowrap">{isLoading || isSubmitting ? (
            <div className="flex items-center justify-center">
              <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Регистрация...
            </div>
          ) : 'Зарегистрироваться'}</span>
        </button>
      </div>
      
      <div className="text-center text-sm pt-4">
        <span className="text-gray-400">Уже есть аккаунт? </span>
        <Link to="/login" className="text-custom-blue hover:text-custom-blue/80 transition-colors focus:outline-none font-medium">
          Войти
        </Link>
      </div>
    </form>
  );
};

export default RegisterForm;
