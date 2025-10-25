import React, { ReactNode } from 'react';

interface AuthLayoutProps {
  children: ReactNode;
  title: string;
  subtitle: string;
}

const AuthLayout: React.FC<AuthLayoutProps> = ({ children, title, subtitle }) => {
  return (
    <div className="flex min-h-screen w-full bg-dark-primary">
      {/* Центральный контейнер */}
      <div className="flex items-center justify-center w-full h-full min-h-screen p-4">
        <div className="w-full max-w-md">
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-semibold text-white mb-2">{title}</h1>
            <p className="text-gray-400 text-sm">{subtitle}</p>
          </div>
          
          <div className="p-6 rounded-xl bg-dark-secondary/80 backdrop-blur-sm border border-dark-border/50 shadow-2xl">
            {children}
          </div>
          
          <div className="mt-6 text-center">
            <p className="text-xs text-gray-500">
              Техническая поддержка: <a href="mailto:support@t1.ru" className="text-custom-blue hover:underline transition-colors">support@t1.ru</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AuthLayout;
