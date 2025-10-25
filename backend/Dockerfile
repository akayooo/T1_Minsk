FROM python:3.12-slim

# Обновляем список пакетов и устанавливаем Tesseract OCR и языковые пакеты
# tesseract-ocr - сам движок
# tesseract-ocr-rus - русский язык
# tesseract-ocr-eng - английский язык
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8000

CMD ["python", "main.py"]

