import pytesseract
from PIL import Image
import requests
from io import BytesIO

def extract_text_from_url(url: str, lang: str = 'rus+eng') -> str:
    """
    Извлекает текст из изображения по URL с помощью Tesseract OCR.

    :param url: URL-адрес изображения.
    :param lang: Язык(и) для распознавания (по умолчанию 'rus+eng').
                 Например, 'eng' для английского, 'rus' для русского.
    :return: Извлеченный текст в виде строки или сообщение об ошибке.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip()

    except requests.exceptions.RequestException as e:
        return f"Ошибка при загрузке изображения: {e}"
    except Exception as e:
        return f"Произошла ошибка: {e}"

# # --- Пример использования ---
# if __name__ == '__main__':
#     pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
#     image_url = 'https://storage.yandexcloud.net/hackminsk/tech-support-images/091e5fc8-6c16-42c7-9d14-7ac2f17579e1.jpg'
#     extracted_text = extract_text_from_url(image_url, lang='rus+eng')
#     print(extracted_text)

