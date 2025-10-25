import React from 'react';
import { Navigate } from 'react-router-dom';
import LoginFormNew from '../components/LoginForm';
import { useAuth } from '../context/AuthContext';
import AuthLayout from '../components/AuthLayout';

const LoginPage: React.FC = () => {
  const { isAuthenticated } = useAuth();
  
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <AuthLayout 
      title="Добро пожаловать"
      subtitle="Войдите в свой аккаунт – это займет всего мгновение!"
    >
      <LoginFormNew />
    </AuthLayout>
  );
};

export default LoginPage;
