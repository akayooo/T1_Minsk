export interface User {
  id: string;
  name: string;
  email: string;
}

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  imageUrl?: string; // URL изображения, если сообщение содержит изображение
  serverImageUrl?: string; // Серверный URL изображения, используется для сохранения в базе данных
  timestamp?: string;
}

export interface Chat {
  id: string; // user_id (telegram user id)
  title?: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
  chat_id?: string; // ObjectId чата в MongoDB
  telegram_chat_id?: number; // ID чата в Telegram
}

export interface LoginRequest {
  login: string;
  password: string;
}

export interface RegisterRequest {
  name: string;
  email: string;
  password: string;
}

export interface LoginResponse {
  message: string;
  token: string;
  user_id?: string;
  email?: string;
  name?: string;
}

export interface MessageRequest {
  message: string;
  chat_id?: string;
  chat_status: 'new' | 'existing';
  assistant_type?: string;
  photos?: File[];
}

export interface MessageResponse {
  chatId: string;
  response: string;
  chatTitle?: string;
  photoUrl?: string; // URL фото загруженного на сервер
}

export interface ErrorResponse {
  error: string;
}

// Новые типы для работы с фотографиями
export interface PhotoAnalysisRequest {
  photo: File;
  chat_id?: string;
  chat_status: 'new' | 'existing';
}

export interface PhotoAnalysisResponse {
  chatId: string;
  response: string;
  chatTitle?: string;
}

declare global {
  interface Window {
    uploadPhotoForAnalysis?: (file: File) => void;
  }
}
