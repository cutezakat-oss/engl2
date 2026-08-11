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

# ---------- Промпты для слов дня ----------
DIFFICULTY_PROMPTS = {
    "easy": "Дай простое английское слово уровня A1-A2, его транскрипцию (произношение), перевод на русский и пример использования. Ответ строго в формате: слово|транскрипция|перевод|пример",
    "medium": "Дай английское слово уровня B1-B2, его транскрипцию, перевод и пример. Ответ в формате: слово|транскрипция|перевод|пример",
    "hard": "Дай сложное английское слово уровня C1-C2, его транскрипцию, перевод и пример. Ответ в формате: слово|транскрипция|перевод|пример",
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
        "temperature": 0.8,
        "max_tokens": 200,
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
                            parts = raw.split("|")
                            if len(parts) >= 4:
                                word = parts[0].strip()
                                transcription = parts[1].strip()
                                translation = parts[2].strip()
                                example = parts[3].strip()
                                if word in exclude:
                                    logger.warning(f"Слово '{word}' уже выучено, пробуем снова...")
                                    continue
                                return {
                                    "word": word,
                                    "transcription": transcription,
                                    "translation": translation,
                                    "example": example
                                }
                            else:
                                logger.warning(f"Неверный формат ответа: {raw}")
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
        "example": "Попробуйте ещё раз"
    }

# ---------- Вспомогательные функции для валидации PvP вопросов ----------
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

# ---------- Функция для извлечения JSON из текста ----------
def extract_and_parse_json(text: str):
    """
    Пытается извлечь JSON-объект из текста, исправляя кавычки и удаляя комментарии.
    Возвращает распарсенный словарь или None.
    """
    # Заменяем все возможные варианты кавычек на стандартные двойные кавычки
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    # Удаляем многострочные комментарии /* ... */
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Удаляем однострочные комментарии // ... до конца строки
    text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
    # Удаляем пояснения в скобках и после них
    text = re.sub(r'\s*\([^)]*\)\s*', ' ', text)
    # Ищем что-то похожее на JSON-объект { ... }
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if not match:
        # Если не нашли простой объект, пробуем найти с вложенными структурами
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
                    if not stack:
                        candidate = text[start:i+1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            pass
        return None
    candidate = match.group()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None

class GigaChatError(Exception):
    pass

# ---------- НОВАЯ ФУНКЦИЯ ДЛЯ PVP С ПЕРЕРАБОТАННЫМИ ПРОМПТАМИ ----------
async def generate_question(difficulty: str = "medium", question_type: str = "word_to_translate") -> dict:
    # Определяем текстовое описание уровня
    level_desc = {
        "easy": "начального уровня (A1-A2)",
        "medium": "среднего уровня (B1-B2)",
        "hard": "продвинутого уровня (C1-C2)"
    }.get(difficulty, "среднего уровня (B1-B2)")

    if question_type == "word_to_translate":
        prompt = (
            f"Придумай случайное английское слово {level_desc}. "
            "Дай его перевод на русский язык и 3 неверных перевода на русский язык. "
            "Слово не должно быть связано с уровнями сложности (не используй слова 'medium', 'easy', 'hard', 'elementary', 'intermediate', 'advanced' и т.п.). "
            "Ответ строго в формате JSON: "
            '{"word": "английское слово", "correct": "правильный перевод", "wrong": ["ложный1", "ложный2", "ложный3"]}'
        )
    else:  # translate_to_word
        prompt = (
            f"Придумай случайное русское слово, соответствующее английскому слову {level_desc}. "
            "Дай правильный английский перевод и 3 неверных английских перевода. "
            "Слово не должно быть связано с уровнями сложности (не используй слова 'medium', 'easy', 'hard', 'elementary', 'intermediate', 'advanced' и т.п.). "
            "Ответ строго в формате JSON: "
            '{"word": "русское слово", "correct": "правильное английское слово", "wrong": ["ложное1", "ложное2", "ложное3"]}'
        )

    logger.info(f"Запрос к GigaChat для PvP: {prompt[:100]}...")

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
        "temperature": 0.5,  # уменьшил для стабильности
        "max_tokens": 250,
    }

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(10):
            try:
                async with session.post(GIGACHAT_API_URL, json=payload, headers=headers, timeout=30) as resp:
                    status = resp.status
                    text = await resp.text()
                    if status == 200:
                        data = await resp.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            raw = data["choices"][0]["message"]["content"].strip()
                            logger.info(f"Сырой ответ GigaChat: {raw}")

                            parsed = extract_and_parse_json(raw)
                            if parsed is None:
                                logger.warning("Не удалось извлечь JSON, пробуем снова...")
                                continue

                            word = parsed.get("word", "").strip()
                            correct = parsed.get("correct", "").strip()
                            wrong = parsed.get("wrong", [])
                            if isinstance(wrong, list) and len(wrong) >= 3:
                                wrong = wrong[:3]
                            else:
                                logger.warning(f"Неверный формат wrong: {wrong}")
                                continue
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

    raise GigaChatError("Не удалось сгенерировать вопрос после 10 попыток")