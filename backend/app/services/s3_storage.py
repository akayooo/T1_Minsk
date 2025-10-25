import logging
import os
import uuid
from io import BytesIO
from typing import Optional, Union

import boto3
from botocore.exceptions import ClientError


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Minio S3-совместимое хранилище
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://minio:9000')  # Для загрузки (внутри Docker)
S3_PUBLIC_URL = os.getenv('S3_PUBLIC_URL', 'http://localhost:9000')  # Для отдачи фронту (публичный доступ)
S3_REGION = os.getenv('S3_REGION', 'us-east-1')

ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']

IMAGE_CONTENT_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml'
}


def create_s3_session():
    """
    Создает и настраивает сессию для работы с Minio S3.
    """
    try:
        session = boto3.session.Session(
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION
        )
        s3_client = session.client(
            service_name='s3',
            endpoint_url=S3_ENDPOINT_URL
        )
        return s3_client
    except Exception as e:
        logging.error(f"Не удалось создать Minio S3 сессию: {e}")
        return None


def upload_image_to_s3(
    s3_client, 
    image_data: Union[str, BytesIO, bytes], 
    bucket_name: str,
    filename: Optional[str] = None,
    folder: str = "images"
) -> Optional[str]:
    """
    Загружает изображение в Minio S3.
    
    Args:
        s3_client: Клиент S3
        image_data: Путь к файлу, BytesIO объект или bytes
        bucket_name: Имя бакета
        filename: Имя файла (если None, генерируется уникальное)
        folder: Папка в бакете для хранения изображений
    
    Returns:
        URL загруженного изображения или None в случае ошибки
    """
    if not S3_ACCESS_KEY or not S3_SECRET_KEY or not bucket_name:
        logging.error("Учетные данные Minio (access key, secret key, bucket) не найдены.")
        return None

    if isinstance(image_data, str):
        if not os.path.exists(image_data):
            logging.error(f"Файл для загрузки не найден: {image_data}")
            return None
        
        file_name = filename or os.path.basename(image_data)
        file_ext = os.path.splitext(file_name)[1].lower()
        
        if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
            logging.warning(f"Неподдерживаемый тип изображения: {file_ext}. Допускаются: {ALLOWED_IMAGE_EXTENSIONS}")
            return None
        
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        object_name = f"{folder}/{unique_filename}"
        content_type = IMAGE_CONTENT_TYPES.get(file_ext, 'application/octet-stream')
        
        try:
            logging.info(f"Начало загрузки {image_data} в бакет {bucket_name}...")
            s3_client.upload_file(
                image_data, 
                bucket_name, 
                object_name,
                ExtraArgs={'ContentType': content_type}
            )
            logging.info(f"Изображение успешно загружено: {object_name}")
            
            # Используем внутренний Docker URL (для Telegram bot и фронтенда)
            image_url = f"{S3_ENDPOINT_URL}/{bucket_name}/{object_name}"
            return image_url
            
        except ClientError as e:
            logging.error(f"Ошибка при загрузке изображения в S3: {e}")
            return None
    
    elif isinstance(image_data, (BytesIO, bytes)):
        if filename is None:
            filename = f"{uuid.uuid4()}.jpg"
        
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
            file_ext = '.jpg' 
            filename = f"{os.path.splitext(filename)[0]}{file_ext}"
        
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        object_name = f"{folder}/{unique_filename}"
        content_type = IMAGE_CONTENT_TYPES.get(file_ext, 'image/jpeg')
        
        try:
            logging.info(f"Начало загрузки изображения из памяти в бакет {bucket_name}...")
            
            if isinstance(image_data, bytes):
                image_data = BytesIO(image_data)
            
            s3_client.upload_fileobj(
                image_data,
                bucket_name,
                object_name,
                ExtraArgs={'ContentType': content_type}
            )
            logging.info(f"Изображение успешно загружено: {object_name}")
            
            # Используем внутренний Docker URL (для Telegram bot и фронтенда)
            image_url = f"{S3_ENDPOINT_URL}/{bucket_name}/{object_name}"
            return image_url
            
        except ClientError as e:
            logging.error(f"Ошибка при загрузке изображения в S3: {e}")
            return None


def get_photo_url(
    image_data: Union[str, BytesIO, bytes],
    filename: Optional[str] = None,
    folder: str = "tech-support-images"
) -> Optional[str]:
    """
    Загружает фото в Minio S3 и возвращает URL.
    
    Args:
        image_data: Путь к файлу, BytesIO объект или bytes
        filename: Имя файла (опционально)
        folder: Папка в бакете для хранения
    
    Returns:
        URL загруженного изображения или None в случае ошибки
    """
    s3_client = create_s3_session()
    if not s3_client:
        logging.error("Не удалось создать Minio S3 клиент.")
        return None
    
    image_url = upload_image_to_s3(
        s3_client=s3_client,
        image_data=image_data,
        bucket_name=S3_BUCKET_NAME,
        filename=filename,
        folder=folder
    )
    
    return image_url


# def main():
#     """
#     Тестовая функция для демонстрации загрузки изображений.
#     """

#     script_dir = os.path.dirname(os.path.abspath(__file__))
#     test_image_path = os.path.join(script_dir, "0001.png")
    
#     logging.info(f"Попытка загрузить тестовое изображение: {test_image_path}")
    
#     image_url = get_photo_url(image_data=test_image_path)
    
#     if image_url:
#         logging.info(f"Изображение успешно загружено!")
#     else:
#         logging.error("Не удалось загрузить изображение")


# if __name__ == "__main__":
#     main()
