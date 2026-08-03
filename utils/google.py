import os
from openai import OpenAI

# Вставь свой ключ сюда вместо "AIzaSy..."
GEMINI_API_KEY = "Вставьте свой ключ API"

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

def get_available_models():
    print("🔍 Получаем список доступных моделей Google Gemini...\n")
    try:
        models = client.models.list()
        for model in models.data:
            print(f"• ID: {model.id}")
            print(f"  Владелец: {model.owned_by}")
            print("-" * 40)
    except Exception as e:
        print(f"❌ Ошибка при получении списка: {e}")

if __name__ == "__main__":
    get_available_models()