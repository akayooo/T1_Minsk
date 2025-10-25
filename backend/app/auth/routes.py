from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
import os
import logging

from app.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 14 

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer()


class OperatorRegister(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    password: str


class OperatorLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Хэширует пароль"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Создает JWT токен"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_operator_by_email(email: str) -> Optional[dict]:
    """Получает оператора по email"""
    try:
        db = get_database()
        collection = db.operators
        
        operator = await collection.find_one({"email": email})
        
        return operator
    except Exception as e:
        logger.error(f"Ошибка при получении оператора: {e}")
        return None


async def save_operator_to_db(operator_data: dict) -> bool:
    """Сохраняет оператора в MongoDB"""
    try:
        db = get_database()
        collection = db.operators
        
        result = await collection.insert_one(operator_data)
        
        if result.inserted_id:
            logger.info(f"Зарегистрирован новый оператор: {operator_data['email']}")
            return True
        
        return False
    except Exception as e:
        logger.error(f"Ошибка при сохранении оператора: {e}")
        return False


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Проверяет JWT токен"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный токен",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/register")
async def register_operator(operator: OperatorRegister):
    """
    Регистрация нового оператора техподдержки.
    
    Args:
        operator: Данные оператора (email, имя, фамилия, пароль)
    
    Returns:
        JSON с результатом регистрации
    """
    try:
        existing_operator = await get_operator_by_email(operator.email)
        
        if existing_operator:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Оператор с таким email уже зарегистрирован"
            )
        
        hashed_password = get_password_hash(operator.password)
        
        operator_data = {
            "email": operator.email,
            "first_name": operator.first_name,
            "last_name": operator.last_name,
            "password": hashed_password,
            "registered_at": datetime.utcnow().isoformat(),
            "is_active": True
        }
        
        success = await save_operator_to_db(operator_data)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось сохранить оператора в базу данных"
            )
        
        logger.info(f"Оператор {operator.email} успешно зарегистрирован")
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "success": True,
                "message": "Оператор успешно зарегистрирован",
                "operator": {
                    "email": operator.email,
                    "first_name": operator.first_name,
                    "last_name": operator.last_name
                }
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при регистрации оператора: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.post("/login")
async def login_operator(credentials: OperatorLogin):
    """
    Авторизация оператора техподдержки.
    
    Args:
        credentials: Email и пароль
    
    Returns:
        JSON с JWT токеном
    """
    try:
        operator = await get_operator_by_email(credentials.email)
        
        if not operator:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль"
            )
        
        if not verify_password(credentials.password, operator["password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль"
            )
        
        if not operator.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аккаунт деактивирован"
            )
        
        operator_id = str(operator["_id"])
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": operator["email"],
                "operator_id": operator_id
            },
            expires_delta=access_token_expires
        )
        
        logger.info(f"Оператор {credentials.email} успешно авторизован")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "access_token": access_token,
                "token_type": "bearer",
                "operator": {
                    "id": operator_id,
                    "email": operator["email"],
                    "first_name": operator["first_name"],
                    "last_name": operator["last_name"]
                }
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при авторизации оператора: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/me")
async def get_current_operator(payload: dict = Depends(verify_token)):
    """
    Получает информацию о текущем авторизованном операторе.
    
    Args:
        payload: Данные из JWT токена
    
    Returns:
        JSON с информацией об операторе
    """
    try:
        email = payload.get("sub")
        operator = await get_operator_by_email(email)
        
        if not operator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Оператор не найден"
            )
        
        operator.pop("password", None)
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "operator": operator
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении данных оператора: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

