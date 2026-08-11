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
    "easy": "Дай простое английское слово уровня A1-A2, его транскрипцию (произношение), перевод на русский и пример использования. Ответ строго в формате: слово|транскрипция|перевод|пример. Не используй Markdown, не добавляй пояснений, ответ должен содержать только одну строку.",
    "medium": "Дай английское слово уровня B1-B2, его транскрипцию, перевод и пример. Ответ строго в формате: слово|транскрипция|перевод|пример. Не используй Markdown, не добавляй пояснений, ответ должен содержать только одну строку.",
    "hard": "Дай сложное английское слово уровня C1-C2, его транскрипцию, перевод и пример. Ответ строго в формате: слово|транскрипция|перевод|пример. Не используй Markdown, не добавляй пояснений, ответ должен содержать только одну строку.",
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

# ---------- Функция для парсинга ответа слов дня ----------
def parse_word_response(raw: str):
    raw = raw.replace('\n', ' ').replace('\r', '').strip()

    bold_match = re.search(r'\*\*(.+?)\*\*', raw)
    if bold_match:
        content = bold_match.group(1).strip()
        parts = content.split('|')
        if len(parts) >= 4:
            word = parts[0].strip()
            transcription = parts[1].strip()
            translation = parts[2].strip()
            example = parts[3].strip()
            example = re.sub(r'\s*\([^)]*\)\s*$', '', example).strip()
            if word and translation:
                return (word, transcription, translation, example)

    list_match = re.search(r'-\s+\*\*(.+?)\*\*\s*\|?\s*\[?([^\]]*)\]?\s*\|?\s*(.+?)(?=\s*-\s|\s*$)', raw, re.DOTALL)
    if list_match:
        word = list_match.group(1).strip()
        transcription = list_match.group(2).strip()
        rest = list_match.group(3).strip()
        if '|' in rest:
            parts = rest.split('|')
            translation = parts[0].strip()
            example = parts[1].strip() if len(parts) > 1 else ''
        else:
            ru_match = re.search(r'([А-Яа-яЁё\s,;:!?]+)', rest)
            en_match = re.search(r'([A-Za-z\s,;:!?\']+)', rest)
            translation = ru_match.group(1).strip() if ru_match else ''
            example = en_match.group(1).strip() if en_match else ''
            if translation and example and example in translation:
                after_trans = rest.split(translation)[-1].strip()
                en_match2 = re.search(r'([A-Za-z\s,;:!?\']+)', after_trans)
                example = en_match2.group(1).strip() if en_match2 else ''
        if word and translation:
            return (word, transcription, translation, example)

    parts = raw.split('|')
    if len(parts) >= 4:
        word = parts[0].strip()
        transcription = parts[1].strip()
        translation = parts[2].strip()
        example = parts[3].strip()
        if word and translation:
            return (word, transcription, translation, example)

    word_match = re.search(r'\b([A-Za-z\']+)\b', raw)
    trans_match = re.search(r'[\[\(]([^\]]+)[\]\)]', raw)
    trans_ru_match = re.search(r'[А-Яа-яЁё][А-Яа-яЁё\s,;:!?]{2,}', raw)
    example_match = re.search(r'([A-Z][A-Za-z\s,;:!?\']{5,})', raw)

    word = word_match.group(1) if word_match else ''
    transcription = trans_match.group(1) if trans_match else ''
    translation = trans_ru_match.group(0) if trans_ru_match else ''
    example = example_match.group(1) if example_match else ''

    if word and translation:
        return (word, transcription, translation, example)

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

                            parsed = parse_word_response(raw)
                            if parsed:
                                word, transcription, translation, example = parsed
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
        "example": "Попробуйте ещё раз"
    }

# ---------- Вспомогательные функции для PvP ----------
def is_cyrillic(text: str) -> bool:
    return bool(re.search(r'[а-яА-ЯёЁ]', text))

def is_latin(text: str) -> bool:
    return bool(re.search(r'[a-zA-Z]', text))

def extract_json(text: str):
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

def extract_json_array(text: str):
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*\([^()]*\)\s*', ' ', text)
    text = re.sub(r'^\s*[\-\*\d]+\.?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Ищем массив [ ... ]
    stack = []
    start = -1
    for i, ch in enumerate(text):
        if ch == '[':
            if not stack:
                start = i
            stack.append(ch)
        elif ch == ']':
            if stack:
                stack.pop()
                if not stack and start != -1:
                    candidate = text[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
    return None

class GigaChatError(Exception):
    pass

# ---------- Генерация вопроса для PvP (два запроса) ----------
async def generate_question(difficulty: str = "medium", question_type: str = "word_to_translate", used_words: list = None) -> dict:
    if used_words is None:
        used_words = []

    forbidden = ["easy", "medium", "hard", "elementary", "intermediate", "advanced", "beginner", "proficient"] + used_words
    forbidden_str = ", ".join(forbidden)

    # Первый запрос: получить слово и правильный перевод
    for attempt in range(20):
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

        payload = {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 200,
        }

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.post(GIGACHAT_API_URL, json=payload, headers=headers, timeout=30) as resp:
                    status = resp.status
                    text = await resp.text()
                    if status == 200:
                        data = await resp.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            raw = data["choices"][0]["message"]["content"].strip()
                            logger.info(f"Сырой ответ GigaChat (первый запрос): {raw}")

                            parsed = extract_json(raw)
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

                            # ---- Второй запрос: получить три ложных варианта ----
                            if question_type == "word_to_translate":
                                wrong_prompt = (
                                    f"Придумай 3 ложных перевода на русский язык для английского слова '{word}'.\n"
                                    f"Правильный перевод: '{correct}'.\n"
                                    "Ложные переводы должны быть правдоподобными, но не синонимами правильного перевода.\n"
                                    "Верни только массив из трёх слов на русском языке в формате JSON: [\"ложный1\", \"ложный2\", \"ложный3\"]\n"
                                    "Не добавляй пояснений или комментариев."
                                )
                            else:
                                wrong_prompt = (
                                    f"Придумай 3 ложных перевода на английский язык для русского слова '{word}'.\n"
                                    f"Правильный перевод: '{correct}'.\n"
                                    "Ложные переводы должны быть правдоподобными, но не синонимами правильного перевода.\n"
                                    "Верни только массив из трёх слов на английском языке в формате JSON: [\"ложный1\", \"ложный2\", \"ложный3\"]\n"
                                    "Не добавляй пояснений или комментариев."
                                )

                            payload_wrong = {
                                "model": "GigaChat",
                                "messages": [{"role": "user", "content": wrong_prompt}],
                                "temperature": 0.8,
                                "max_tokens": 150,
                            }

                            try:
                                async with session.post(GIGACHAT_API_URL, json=payload_wrong, headers=headers, timeout=30) as resp2:
                                    if resp2.status == 200:
                                        data2 = await resp2.json()
                                        if "choices" in data2 and len(data2["choices"]) > 0:
                                            raw2 = data2["choices"][0]["message"]["content"].strip()
                                            logger.info(f"Сырой ответ GigaChat (второй запрос): {raw2}")
                                            wrong_array = extract_json_array(raw2)
                                            if wrong_array is not None and isinstance(wrong_array, list) and len(wrong_array) == 3:
                                                wrong = [str(x).strip() for x in wrong_array]
                                                # Проверяем, что все варианты на нужном языке
                                                if question_type == "word_to_translate":
                                                    if all(is_cyrillic(x) for x in wrong):
                                                        options = [correct] + wrong
                                                        random.shuffle(options)
                                                        return {
                                                            "word": word,
                                                            "correct_answer": correct,
                                                            "options": options
                                                        }
                                                else:
                                                    if all(is_latin(x) for x in wrong):
                                                        options = [correct] + wrong
                                                        random.shuffle(options)
                                                        return {
                                                            "word": word,
                                                            "correct_answer": correct,
                                                            "options": options
                                                        }
                                                logger.warning("Не все ложные варианты на нужном языке, пробуем снова...")
                                            else:
                                                logger.warning("Не удалось извлечь массив, пробуем снова...")
                                    else:
                                        logger.error(f"Ошибка второго запроса: {resp2.status} - {await resp2.text()}")
                            except Exception as e:
                                logger.error(f"Ошибка второго запроса: {e}")
                    else:
                        logger.error(f"Ошибка GigaChat: {status} - {text}")
                        await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка при запросе: {e}")
                await asyncio.sleep(1)

    raise GigaChatError("Не удалось сгенерировать вопрос после 20 попыток")
