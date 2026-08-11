from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from bot.database import AsyncSessionLocal
from bot.models import User
from bot.keyboards.reply import get_main_keyboard

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    async with AsyncSessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            session.add(user)
            await session.commit()
            text = f"Привет, {user.first_name}! Ты зарегистрирован. Перейди в меню для выбора функций."
        else:
            text = f"С возвращением, {user.first_name}! Ты уже зарегистрирован. Перейди в меню для выбора функций."
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Перейти в меню", callback_data="go_to_menu")]
            ]
        )
        
        await message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await message.answer(
            "Выберите раздел:",
            reply_markup=get_main_keyboard()
        )

@router.callback_query(lambda c: c.data == "go_to_menu")
async def go_to_menu_callback(callback: types.CallbackQuery):
    await callback.answer()  # <-- СНАЧАЛА ПОДТВЕРЖДАЕМ
    await callback.message.delete()
    await callback.message.answer(
        "📋 *Главное меню*\n\nВыберите раздел:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )