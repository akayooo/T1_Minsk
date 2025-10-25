import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import AuthLayout from '../components/AuthLayout';
import RegisterFormNew from '../components/RegisterForm';

const RegisterPage: React.FC = () => {
  const { isAuthenticated } = useAuth();
  
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <AuthLayout 
      title="Создайте аккаунт"
      subtitle="Заполните данные для быстрой регистрации"
    >
      <RegisterFormNew />
    </AuthLayout>
  );
};

export default RegisterPage;
