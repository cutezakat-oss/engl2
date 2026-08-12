import os
import aiohttp
import asyncio
import logging
import ssl
import base64
import uuid
import json
import re
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# ---------- Промпты с примером и переводом примера ----------
DIFFICULTY_PROMPTS = {
    "easy": "Дай простое английское слово уровня A1-A2, его транскрипцию (произношение), перевод на русский, пример использования на английском (само слово выдели звёздочками *слово* внутри предложения) и перевод этого примера на русский. Ответ строго в формате: слово|транскрипция|перевод|пример|перевод_примера. Не используй Markdown (кроме звёздочек для выделения), не добавляй пояснений, ответ должен содержать только одну строку.",
    "medium": "Дай английское слово уровня B1-B2, его транскрипцию, перевод и пример, выдели слово звёздочками. Ответ в формате: слово|транскрипция|перевод|пример|перевод_примера. Не используй Markdown (кроме звёздочек), не добавляй пояснений.",
    "hard": "Дай сложное английское слово уровня C1-C2, его транскрипцию, перевод и пример, выдели слово звёздочками. Ответ в формате: слово|транскрипция|перевод|пример|перевод_примера. Не используй Markdown (кроме звёздочек), не добавляй пояснений.",
}

# ---------- SSL ----------
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# ---------- Авторизация ----------
def get_basic_auth_header() -> str:
    credentials = f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"

async def get_access_token() -> str:
    headers = {
        "Authorization": get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "GIGACHAT_API_PERS",
    }

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(GIGACHAT_AUTH_URL, headers=headers, data=data, timeout=30) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"Ошибка авторизации GigaChat: {resp.status} - {text}")
                raise Exception(f"Auth error: {resp.status}")
            result = await resp.json()
            token = result.get("access_token")
            if not token:
                raise Exception("No access_token in response")
            return token

# ---------- Функция для парсинга ответа слов дня (5 частей) ----------
def parse_word_response(raw: str):
    raw = raw.replace('\n', ' ').replace('\r', '').strip()

    # 1. Пробуем разделить по | (ожидаем 5 частей)
    parts = raw.split('|')
    if len(parts) >= 5:
        word = parts[0].strip()
        transcription = parts[1].strip()
        translation = parts[2].strip()
        example = parts[3].strip()
        example_translation = parts[4].strip()
        if word and translation and example:
            return (word, transcription, translation, example, example_translation)

    # 2. Пробуем старый формат (4 части) для обратной совместимости
    if len(parts) >= 4:
        word = parts[0].strip()
        transcription = parts[1].strip()
        translation = parts[2].strip()
        example = parts[3].strip()
        if word and translation and example:
            return (word, transcription, translation, example, "")

    return None

# ---------- Функция для слов дня ----------
async def generate_word(difficulty: str = "medium", exclude: list = None) -> dict:
    if exclude is None:
        exclude = []

    prompt = DIFFICULTY_PROMPTS[difficulty]
    if exclude:
        prompt += f" Не используй эти слова: {', '.join(exclude)}."

    logger.info(f"Запрос к GigaChat (слово дня): {prompt[:100]}...")

    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        logger.error("GIGACHAT_CLIENT_ID или GIGACHAT_CLIENT_SECRET не заданы в .env")
        return fallback()

    try:
        token = await get_access_token()
    except Exception as e:
        logger.error(f"Ошибка получения токена: {e}")
        return fallback()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": "GigaChat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 250,
    }

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(5):
            try:
                async with session.post(GIGACHAT_API_URL, json=payload, headers=headers, timeout=30) as resp:
                    status = resp.status
                    text = await resp.text()
                    logger.info(f"Ответ GigaChat статус: {status}, тело: {text[:500]}")
                    if status == 200:
                        data = await resp.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            raw = data["choices"][0]["message"]["content"].strip()
                            logger.info(f"Сырой ответ: {raw}")

                            parsed = parse_word_response(raw)
                            if parsed:
                                word, transcription, translation, example, example_translation = parsed
                                if word in exclude:
                                    logger.warning(f"Слово '{word}' уже выучено, пробуем снова...")
                                    continue
                                return {
                                    "word": word,
                                    "transcription": transcription,
                                    "translation": translation,
                                    "example": example,
                                    "example_translation": example_translation
                                }
                            else:
                                logger.warning(f"Не удалось распарсить ответ: {raw}")
                                if attempt == 4:
                                    break
                                continue
                    elif status == 401:
                        logger.warning("Токен протух, обновляем...")
                        try:
                            token = await get_access_token()
                            headers["Authorization"] = f"Bearer {token}"
                        except Exception:
                            logger.error("Не удалось обновить токен")
                            break
                    else:
                        logger.error(f"Ошибка API: {status} - {text}")
                        await asyncio.sleep(1)
            except asyncio.TimeoutError:
                logger.error("Таймаут соединения с GigaChat")
                await asyncio.sleep(1)
            except Exception as e:
                logger.exception(f"Исключение: {e}")
                await asyncio.sleep(1)

    return fallback()

def fallback():
    return {
        "word": "unknown",
        "transcription": "",
        "translation": "не удалось получить",
        "example": "Попробуйте ещё раз",
        "example_translation": ""
    }

# ---------- Функции для PvP (без изменений) ----------
def is_cyrillic(text: str) -> bool:
    return bool(re.search(r'[а-яА-ЯёЁ]', text))

def is_latin(text: str) -> bool:
    return bool(re.search(r'[a-zA-Z]', text))

def validate_question(question: dict, q_type: str) -> bool:
    word = question.get("word", "")
    correct = question.get("correct_answer", "")
    options = question.get("options", [])

    if len(set(options)) != len(options):
        return False
    if correct in options and options.count(correct) > 1:
        return False

    if q_type == "word_to_translate":
        if not is_latin(word):
            return False
        if not is_cyrillic(correct):
            return False
        for opt in options:
            if not is_cyrillic(opt):
                return False
    else:
        if not is_cyrillic(word):
            return False
        if not is_latin(correct):
            return False
        for opt in options:
            if not is_latin(opt):
                return False
    return True

def extract_and_parse_json(text: str):
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*\([^()]*\)\s*', ' ', text)
    text = re.sub(r'^\s*[\-\*\d]+\.?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    
    stack = []
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if not stack:
                start = i
            stack.append(ch)
        elif ch == '}':
            if stack:
                stack.pop()
                if not stack and start != -1:
                    candidate = text[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        candidate = re.sub(r',\s*}', '}', candidate)
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            pass
    return None

class GigaChatError(Exception):
    pass

async def generate_question(difficulty: str = "medium", question_type: str = "word_to_translate", used_words: list = None) -> dict:
    if used_words is None:
        used_words = []

    forbidden = ["easy", "medium", "hard", "elementary", "intermediate", "advanced", "beginner", "proficient"] + used_words
    forbidden_str = ", ".join(forbidden)

    if question_type == "word_to_translate":
        prompt = (
            "Ты — генератор слов для викторины по английскому языку.\n"
            "Придумай случайное английское слово (существительное, прилагательное или глагол).\n"
            f"Запрещённые слова: {forbidden_str} (их нельзя использовать).\n"
            "Дай его перевод на русский язык.\n"
            "Верни только JSON-объект с полями: word (английское слово), correct (перевод на русский).\n"
            "Пример: {\"word\": \"cat\", \"correct\": \"кошка\"}\n"
            "Не добавляй пояснений или комментариев, только JSON."
        )
    else:
        prompt = (
            "Ты — генератор слов для викторины по английскому языку.\n"
            "Придумай случайное русское слово (существительное, прилагательное или глагол).\n"
            f"Запрещённые слова: {forbidden_str} (их нельзя использовать).\n"
            "Дай его правильный перевод на английский язык.\n"
            "Верни только JSON-объект с полями: word (русское слово), correct (перевод на английский).\n"
            "Пример: {\"word\": \"кошка\", \"correct\": \"cat\"}\n"
            "Не добавляй пояснений или комментариев, только JSON."
        )

    logger.info(f"Запрос к GigaChat для PvP: {prompt[:200]}...")

    try:
        token = await get_access_token()
    except Exception as e:
        logger.error(f"Ошибка получения токена: {e}")
        raise GigaChatError("Не удалось авторизоваться в GigaChat") from e

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": "GigaChat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 200,
    }

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(20):
            try:
                async with session.post(GIGACHAT_API_URL, json=payload, headers=headers, timeout=30) as resp:
                    status = resp.status
                    text = await resp.text()
                    if status == 200:
                        data = await resp.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            raw = data["choices"][0]["message"]["content"].strip()
                            logger.info(f"Сырой ответ GigaChat (PvP): {raw}")

                            parsed = extract_and_parse_json(raw)
                            if parsed is None:
                                logger.warning("Не удалось извлечь JSON, пробуем снова...")
                                continue

                            word = parsed.get("word", "").strip()
                            correct = parsed.get("correct", "").strip()

                            if not word or not correct:
                                logger.warning("Пустые поля, пробуем снова...")
                                continue

                            if word.lower() in [w.lower() for w in forbidden]:
                                logger.warning(f"Слово '{word}' в запрещённом списке, пробуем снова...")
                                continue

                            if len(word) < 3 or len(correct) < 2:
                                logger.warning("Слишком короткое слово или перевод, пробуем снова...")
                                continue

                            if question_type == "word_to_translate" and not is_latin(word):
                                logger.warning(f"Слово '{word}' не английское, пробуем снова...")
                                continue
                            if question_type == "translate_to_word" and not is_cyrillic(word):
                                logger.warning(f"Слово '{word}' не русское, пробуем снова...")
                                continue

                            # Генерируем ложные варианты из запасного списка (можно оставить, но можно и убрать, если нужна только проверка)
                            # В текущей реализации PvP мы используем только слово и правильный перевод, варианты не используются.
                            # Но для совместимости оставим заглушку.
                            wrong = ["ошибка1", "ошибка2", "ошибка3"]
                            options = [correct] + wrong
                            random.shuffle(options)

                            question_data = {
                                "word": word,
                                "correct_answer": correct,
                                "options": options
                            }

                            if validate_question(question_data, question_type):
                                return question_data
                            else:
                                logger.warning("Вопрос не прошёл валидацию, пробуем снова...")
                                continue
                    else:
                        logger.error(f"Ошибка GigaChat: {status} - {text}")
                        await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка при запросе: {e}")
                await asyncio.sleep(1)

    raise GigaChatError("Не удалось сгенерировать вопрос после 20 попыток")
