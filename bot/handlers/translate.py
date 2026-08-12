import os
import translators as ts
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.states.translate import TranslateStates
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0

router = Router()

def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ]
    )

@router.message(Command("translate"))
async def cmd_translate(message: types.Message, state: FSMContext):
    await state.set_state(TranslateStates.waiting_for_text)
    await message.answer(
        "🔤 *Переводчик*\n\nОтправь мне любое слово, фразу или предложение, и я переведу его.",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

@router.message(TranslateStates.waiting_for_text)
async def handle_translate_text(message: types.Message, state: FSMContext):
    user_text = message.text.strip()
    if not user_text:
        await message.answer("Пожалуйста, отправь текст для перевода.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        # Определяем язык текста
        detected_lang = detect(user_text)
        # Если русский -> переводим на английский, иначе на русский
        target_lang = 'ru' if detected_lang == 'en' else 'en'

        # Используем translators (библиотека более стабильная)
        translated = ts.translate_text(
            user_text,
            translator='google',
            from_language='auto',
            to_language=target_lang
        )

        result_text = (
            f"🔄 *Перевод*\n\n"
            f"📝 *Исходный текст:*\n{user_text}\n\n"
            f"✅ *Результат:*\n{translated}"
        )
        await message.answer(result_text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    except Exception as e:
        await message.answer(
            f"❌ *Ошибка перевода*\n\n```\n{str(e)}\n```",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    finally:
        await state.clear()
