import os
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from functools import wraps
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandStart
from dotenv import load_dotenv
from database import db
from crypto import crypto_pay, init_crypto_pay
from auth import auth_manager, init_auth, close_auth
from typing import Optional, Callable, Any, Awaitable, Union
import random
import string

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher with memory storage
storage = MemoryStorage()
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN', '7742888647:AAFE5Y3mIGOOPo6yAFsypiqpUtdpnq8iFfU'))
dp = Dispatcher(bot=bot, storage=storage)

# Store pending payments
pending_payments = {}  # {invoice_id: {user_id: int, days: int, timestamp: datetime}}

# Store temporary data for reports
user_reports = {}  # {user_id: {'link': str, 'state': str}}

# States for report flow
class ReportStates:
    WAITING_FOR_LINK = "waiting_for_link"
    WAITING_FOR_REASON = "waiting_for_reason"

class PromoStates:
    WAITING_FOR_DAYS = "waiting_for_days"
    WAITING_FOR_USES = "waiting_for_uses"

class UserStates:
    WAITING_FOR_PROMO = "waiting_for_promo"

def check_ban(func):
    """Decorator to check if user is banned before processing a message or callback"""
    @wraps(func)
    async def wrapper(update: Union[types.Message, types.CallbackQuery], *args, **kwargs):
        # Get user ID from the update
        user_id = None
        if isinstance(update, types.CallbackQuery):
            user_id = update.from_user.id
            message = update.message
        elif isinstance(update, types.Message):
            user_id = update.from_user.id
            message = update
        else:
            return await func(update, *args, **kwargs)
        
        # Skip check for admin commands if user is an admin
        if user_id and db.is_admin(user_id):
            return await func(update, *args, **kwargs)
            
        # Check if user is banned
        if user_id and db.is_banned(user_id):
            ban_info = db.get_ban_info(user_id)
            if ban_info:
                reason = ban_info.get('reason', 'Не указана')
                admin_id = ban_info.get('admin_id', 'Неизвестен')
                ban_date = ban_info.get('banned_at', 'Неизвестно')
                
                # Try to get admin username
                admin_username = db.get_username(admin_id) or f"ID: {admin_id}"
                
                ban_message = (
                    "🚫 Вы заблокированы!\n"
                    f"📅 Дата бана: {ban_date}\n"
                    f"📝 Причина: {reason}\n"
                    f"👨‍💼 Администратор: {admin_username}"
                )
                
                # Try to send the ban message
                try:
                    if isinstance(update, types.CallbackQuery):
                        await update.answer(ban_message, show_alert=True)
                    else:
                        await message.answer(ban_message)
                except Exception as e:
                    logger.error(f"Failed to send ban message: {e}")
                
                return  # Stop further processing
        
        return await func(update, *args, **kwargs)
    return wrapper

# Inline keyboard for report reasons
def get_report_reasons_keyboard():
    buttons = [
        [
            InlineKeyboardButton(text="Spam", callback_data="report_spam"),
            InlineKeyboardButton(text="Pornography", callback_data="report_porn"),
            InlineKeyboardButton(text="Violence", callback_data="report_violence")
        ],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_report")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Inline keyboard for sauces
async def get_inline_keyboard(show_back=False, show_info=False, show_prices=False, show_sauces=False):
    if show_sauces:
        sauce1 = InlineKeyboardButton(text="Фирменный соус", callback_data="sauce_signature")
        sauce2 = InlineKeyboardButton(text="Почтовый соус", callback_data="sauce_post")
        sauce3 = InlineKeyboardButton(text="Грибной соус", callback_data="sauce_mushroom")
        sauce4 = InlineKeyboardButton(text="Комбо соус", callback_data="sauce_combo")
        sauce5 = InlineKeyboardButton(text="Премиум соус", callback_data="sauce_premium")
        back_btn = InlineKeyboardButton(text="Назад", callback_data="back_to_main")
        
        return InlineKeyboardMarkup(inline_keyboard=[
            [sauce1],
            [sauce3, sauce2],
            [sauce5, sauce4],
            [back_btn]
        ])
    
    if show_back:
        back_button = InlineKeyboardButton(text="Назад", callback_data="back_to_main")
        return InlineKeyboardMarkup(inline_keyboard=[[back_button]])
    
    if show_info:
        channel_btn = InlineKeyboardButton(
            text="Канал",
            url="https://t.me/+-hWilIpL3EI3YTVk"
        )
        chat_btn = InlineKeyboardButton(
            text="Наш чат",
            url="https://t.me/+q4PxR4t2K3cwODk0"
        )
        support_btn = InlineKeyboardButton(
            text="Поддержка",
            url="https://t.me/aircrouching"
        )
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )
        return InlineKeyboardMarkup(inline_keyboard=[
            [channel_btn, chat_btn, support_btn],
            [back_btn]
        ])
    
    if show_prices:
        hour1_btn = InlineKeyboardButton(
            text="1 час - 0.01$",
            callback_data="price_1hour"
        )
        day1_btn = InlineKeyboardButton(
            text="1 день - 2$",
            callback_data="price_1day"
        )
        days3_btn = InlineKeyboardButton(
            text="3 дня - 3$",
            callback_data="price_3days"
        )
        days7_btn = InlineKeyboardButton(
            text="7 дней - 5$",
            callback_data="price_7days"
        )
        days30_btn = InlineKeyboardButton(
            text="30 дней - 9$",
            callback_data="price_30days"
        )
        forever_btn = InlineKeyboardButton(
            text="Навсегда - 13$",
            callback_data="price_forever"
        )
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )
        return InlineKeyboardMarkup(inline_keyboard=[
            [hour1_btn],
            [day1_btn, days3_btn],
            [days7_btn, days30_btn],
            [forever_btn],
            [back_btn]
        ])
    
    # Main menu buttons
    order_button = InlineKeyboardButton(text="🪙Заказать шаучак", callback_data="order")
    profile_button = InlineKeyboardButton(text="🌯Профиль", callback_data="profile")
    info_button = InlineKeyboardButton(text="❓Информация", callback_data="info")
    promo_button = InlineKeyboardButton(text="🎁Промокод", callback_data="promo")
    prices_button = InlineKeyboardButton(text="💶Цены на шаучак", callback_data="prices")
    
    keyboard = [
        [order_button],
        [profile_button, info_button],
        [promo_button, prices_button]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Dictionary to store admin actions in progress
admin_actions = {}
promo_states = {}  # Track promo code generation state
user_states = {}  # Track user states for promo code entry

def generate_promo_code(length: int = 8) -> str:
    """Generate a random promo code"""
    chars = '!@#$%^&' + string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

@dp.message(Command("adm"))
@check_ban
async def admin_panel(message: types.Message):
    """Show admin panel"""
    user_id = message.from_user.id
    
    # Check if user is admin
    if not db.is_admin(user_id):
        await message.answer("‼️У вас нет доступа к админ панели.")
        return
    
    # Create admin keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔨 Забанить пользователя", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🔓 Разбанить пользователя", callback_data="admin_unban")],
        [InlineKeyboardButton(text="🎟 Выдать подписку", callback_data="admin_add_sub")],
        [InlineKeyboardButton(text="❌ Забрать подписку", callback_data="admin_remove_sub")],
        [InlineKeyboardButton(text="🎫 Создать промокод", callback_data="admin_create_promo")]
    ])
    
    await message.answer("👑 Админ панель:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith('admin_'))
@check_ban
async def process_admin_action(callback_query: types.CallbackQuery):
    """Process admin panel actions"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await callback_query.answer("У вас нет доступа к админ панели.")
        return
    
    action = callback_query.data.split('_', 1)[1]
    
    if action == 'ban':
        admin_actions[user_id] = {'action': 'ban'}
        await callback_query.message.answer("Введите ID пользователя и причину бана через пробел (например: 123456 Нарушение правил):")
    
    elif action == 'unban':
        admin_actions[user_id] = {'action': 'unban'}
        await callback_query.message.answer("Введите ID пользователя для разбана:")
    
    elif action == 'add_sub':
        admin_actions[user_id] = {'action': 'add_sub'}
        await callback_query.message.answer("Введите ID пользователя и количество дней через пробел (например: 123456 30):")
    
    elif action == 'remove_sub':
        admin_actions[user_id] = {'action': 'remove_sub'}
        await callback_query.message.answer("Введите ID пользователя для удаления подписки:")
    
    elif action == 'create_promo':
        promo_states[user_id] = {'state': PromoStates.WAITING_FOR_DAYS}
        await callback_query.message.answer("Введите количество дней подписки для промокода:")
    
    await callback_query.answer()

@dp.message(lambda message: message.from_user.id in admin_actions or message.from_user.id in promo_states)
@check_ban
async def process_admin_input(message: types.Message):
    """Process admin action input"""
    user_id = message.from_user.id
    
    # Handle promo code creation first
    if user_id in promo_states:
        state = promo_states[user_id].get('state')
        
        try:
            if state == PromoStates.WAITING_FOR_DAYS:
                days = int(message.text)
                if days <= 0:
                    raise ValueError
                promo_states[user_id].update({
                    'state': PromoStates.WAITING_FOR_USES,
                    'days': days
                })
                await message.answer(f"Введите максимальное количество активаций для промокода на {days} дней:")
                return
                
            elif state == PromoStates.WAITING_FOR_USES:
                max_uses = int(message.text)
                if max_uses <= 0:
                    raise ValueError
                
                days = int(promo_states[user_id]['days'])
                code = generate_promo_code()
                expires_days = 30  # Promo code will be valid for 30 days
                
                if db.create_promo_code(code, days, max_uses, user_id, expires_days):
                    expires_at = (datetime.now() + timedelta(days=expires_days)).strftime('%Y-%m-%d %H:%M:%S')
                    await message.answer(
                        "✅ Промокод создан!\n\n"
                        f"🔑 Код: <code>{code}</code>\n"
                        f"📅 Дней: {days}\n"
                        f"🔄 Активаций: {max_uses}\n"
                        f"⏳ Действует до: {expires_at}\n\n"
                        "Отправьте пользователю: /promo " + code,
                        parse_mode="HTML"
                    )
                else:
                    await message.answer("❌ Ошибка при создании промокода")
                # Only remove state after successful or failed creation
                promo_states.pop(user_id, None)
                return
                
        except ValueError:
            await message.answer("❌ Неверный формат. Введите положительное число.")
            # Don't remove state on error, let user retry
            return
        except Exception as e:
            logger.error(f"Error in promo creation: {e}")
            await message.answer("❌ Произошла ошибка при создании промокода. Пожалуйста, попробуйте снова.")
            promo_states.pop(user_id, None)
            return
    
    # Existing admin actions handling
    if not db.is_admin(user_id):
        admin_actions.pop(user_id, None)
        return
        
    action_data = admin_actions.get(user_id, {})
    action = action_data.get('action')
    
    if not action:
        return
    
    try:
        if action == 'ban':
            parts = message.text.split(' ', 1)
            if len(parts) < 2:
                await message.answer("Неверный формат. Используйте: ID_пользователя причина_бана")
                return
                
            target_id = int(parts[0])
            reason = parts[1]
            
            if db.ban_user(target_id, reason, user_id):
                await message.answer(f"✅ Пользователь {target_id} забанен. Причина: {reason}")
                # Notify the banned user if possible
                try:
                    await bot.send_message(target_id, f"❌ Вы были забанены. Причина: {reason}")
                except:
                    pass
            else:
                await message.answer("❌ Ошибка при бане пользователя")
        
        elif action == 'unban':
            target_id = int(message.text)
            if db.unban_user(target_id):
                await message.answer(f"✅ Пользователь {target_id} разбанен")
                # Notify the unbanned user if possible
                try:
                    await bot.send_message(target_id, "‼️ Ваш бан был снят.")
                except:
                    pass
            else:
                await message.answer("❌ Ошибка при разблокировке пользователя или пользователь не был забанен")
        
        elif action == 'add_sub':
            parts = message.text.split()
            if len(parts) != 2:
                await message.answer("Неверный формат. Используйте: ID_пользователя количество_дней")
                return
                
            target_id = int(parts[0])
            days = int(parts[1])
            
            if db.add_subscription(target_id, days):
                await message.answer(f"✅ Подписка на {days} дней выдана пользователю {target_id}")
                # Notify the user
                try:
                    await bot.send_message(target_id, f"‼️ Вам выдана подписка на {days} дней!")
                except:
                    pass
            else:
                await message.answer("❌ Ошибка при выдаче подписки")
        
        elif action == 'remove_sub':
            target_id = int(message.text)
            if db.remove_subscription(target_id):
                await message.answer(f"✅ Подписка у пользователя {target_id} отозвана")
                # Notify the user
                try:
                    await bot.send_message(target_id, "‼️ Ваша подписка была отозвана администратором.")
                except:
                    pass
            else:
                await message.answer("❌ Ошибка при отзыве подписки или подписка не найдена")
        
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат ввода. Пожалуйста, проверьте введенные данные.")
    except Exception as e:
        logger.error(f"Admin action error: {e}")
        await message.answer("❌ Произошла ошибка при выполнении операции.")
    
    # Clear the admin action
    admin_actions.pop(user_id, None)

# Inline keyboard for report reasons
def get_report_reasons_keyboard():
    buttons = [
        [
            InlineKeyboardButton(text="Spam", callback_data="report_spam"),
            InlineKeyboardButton(text="Pornography", callback_data="report_porn"),
            InlineKeyboardButton(text="Violence", callback_data="report_violence")
        ],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_report")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Inline keyboard for sauces
async def get_inline_keyboard(show_back=False, show_info=False, show_prices=False, show_sauces=False):
    if show_sauces:
        sauce1 = InlineKeyboardButton(text="Фирменный соус", callback_data="sauce_signature")
        sauce2 = InlineKeyboardButton(text="Почтовый соус", callback_data="sauce_post")
        sauce3 = InlineKeyboardButton(text="Грибной соус", callback_data="sauce_mushroom")
        sauce4 = InlineKeyboardButton(text="Комбо соус", callback_data="sauce_combo")
        sauce5 = InlineKeyboardButton(text="Премиум соус", callback_data="sauce_premium")
        back_btn = InlineKeyboardButton(text="Назад", callback_data="back_to_main")
        
        return InlineKeyboardMarkup(inline_keyboard=[
            [sauce1],
            [sauce3, sauce2],
            [sauce5, sauce4],
            [back_btn]
        ])
    
    if show_back:
        back_button = InlineKeyboardButton(text="Назад", callback_data="back_to_main")
        return InlineKeyboardMarkup(inline_keyboard=[[back_button]])
    
    if show_info:
        channel_btn = InlineKeyboardButton(
            text="Канал",
            url="https://t.me/+-hWilIpL3EI3YTVk"
        )
        chat_btn = InlineKeyboardButton(
            text="Наш чат",
            url="https://t.me/+q4PxR4t2K3cwODk0"
        )
        support_btn = InlineKeyboardButton(
            text="Поддержка",
            url="https://t.me/aircrouching"
        )
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )
        return InlineKeyboardMarkup(inline_keyboard=[
            [channel_btn, chat_btn, support_btn],
            [back_btn]
        ])
    
    if show_prices:
        hour1_btn = InlineKeyboardButton(
            text="1 час - 0.01$",
            callback_data="price_1hour"
        )
        day1_btn = InlineKeyboardButton(
            text="1 день - 2$",
            callback_data="price_1day"
        )
        days3_btn = InlineKeyboardButton(
            text="3 дня - 3$",
            callback_data="price_3days"
        )
        days7_btn = InlineKeyboardButton(
            text="7 дней - 5$",
            callback_data="price_7days"
        )
        days30_btn = InlineKeyboardButton(
            text="30 дней - 9$",
            callback_data="price_30days"
        )
        forever_btn = InlineKeyboardButton(
            text="Навсегда - 13$",
            callback_data="price_forever"
        )
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )
        return InlineKeyboardMarkup(inline_keyboard=[
            [hour1_btn],
            [day1_btn, days3_btn],
            [days7_btn, days30_btn],
            [forever_btn],
            [back_btn]
        ])
    
    # Main menu buttons
    order_button = InlineKeyboardButton(text="🪙Заказать шаучак", callback_data="order")
    profile_button = InlineKeyboardButton(text="🌯Профиль", callback_data="profile")
    info_button = InlineKeyboardButton(text="❓Информация", callback_data="info")
    promo_button = InlineKeyboardButton(text="🎁Промокод", callback_data="promo")
    prices_button = InlineKeyboardButton(text="💶Цены на шаучак", callback_data="prices")
    
    keyboard = [
        [order_button],
        [profile_button, info_button],
        [promo_button, prices_button]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Command /start
@dp.message(Command(commands=["start"]))
@check_ban
async def send_welcome(message: types.Message):
    # Welcome message with photo URL
    photo_url = "https://i.pinimg.com/736x/c0/cb/0c/c0cb0c0e9a4710d84bca369e3e1f95e1.jpg"
    welcome_text = "Хочешь шаучак!? Добро пожаловать"
    caption = f"<i>\n{welcome_text}\n</i>"
    
    # Send photo with caption and inline keyboard
    await message.answer_photo(
        photo=photo_url,
        caption=caption,
        reply_markup=await get_inline_keyboard(),
        parse_mode="HTML"
    )

async def check_pending_payments():
    """Periodically check and update pending payments"""
    while True:
        try:
            current_time = datetime.now()
            to_remove = []
            
            for invoice_id, payment in list(pending_payments.items()):
                # Check if payment is too old
                if (current_time - payment['timestamp']) > timedelta(minutes=30):
                    to_remove.append(invoice_id)
                    continue
                
                # Check payment status
                invoice_data = await crypto_pay.get_invoice(invoice_id)
                if invoice_data and invoice_data.get('items'):
                    invoice = invoice_data['items'][0]
                    if invoice.get('status') == 'paid':
                        db.add_subscription(payment['user_id'], payment['days'])
                        await bot.send_message(
                            payment['user_id'],
                            "✅ Оплата получена! Ваша подписка активирована."
                        )
                        to_remove.append(invoice_id)
            
            # Clean up processed or expired payments
            for invoice_id in to_remove:
                if invoice_id in pending_payments:
                    del pending_payments[invoice_id]
                
        except Exception as e:
            logger.error(f"Error in payment checker: {e}")
        
        await asyncio.sleep(60)  # Check every minute

@dp.callback_query()
@check_ban
async def process_callback(callback_query: types.CallbackQuery):
    """Route callback queries to their respective handlers"""
    data = callback_query.data
    
    # Handle sauce selection
    if data.startswith('sauce_'):
        if data == 'sauce_signature':
            await handle_signature_sauce(callback_query)
        else:
            # Check subscription for other sauces
            has_sub = await check_user_subscription(callback_query.from_user.id)
            if not has_sub:
                await show_no_subscription(callback_query)
                return
                
            sauce_name = data.split('_')[1]
            sauce_names = {
                'signature': 'Фирменный соус',
                'post': 'Почтовый соус',
                'mushroom': 'Грибной соус',
                'combo': 'Комбо соус',
                'premium': 'Премиум соус'
            }
            await callback_query.answer(f"Вы выбрали {sauce_names.get(sauce_name, sauce_name)}")
            return
    # Handle report reasons
    elif data.startswith('report_'):
        await process_report_reason(callback_query)
    # Handle cancel report
    elif data == 'cancel_report':
        await cancel_report(callback_query)
    # Handle other callbacks
    elif data == 'back_to_main':
        user_states.pop(callback_query.from_user.id, None)
        await show_main_menu(callback_query)
    elif data == 'order':
        await handle_order(callback_query)
    elif data == 'profile':
        await show_profile(callback_query)
    elif data == 'info':
        await show_info(callback_query)
    elif data == 'prices':
        await show_prices(callback_query)
    elif data.startswith('price_'):
        await handle_price_selection(callback_query)
    elif data == 'promo':
        await handle_promo(callback_query)
    else:
        await callback_query.answer("Неизвестная команда")

async def check_user_subscription(user_id: int) -> bool:
    """Check if user has an active subscription"""
    has_sub, _ = db.get_subscription_status(user_id)
    return has_sub

async def handle_signature_sauce(callback_query: types.CallbackQuery):
    """Handle signature sauce selection"""
    user_id = callback_query.from_user.id
    has_sub = await check_user_subscription(user_id)
    
    if not has_sub:
        await show_no_subscription(callback_query)
        return
        
    user_reports[user_id] = {'state': ReportStates.WAITING_FOR_LINK}
    
    try:
        await callback_query.message.edit_caption(
            caption="Введите ссылку на сообщение в чате Telegram:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="cancel_report")]
            ])
        )
    except Exception as e:
        await callback_query.message.answer(
            "Введите ссылку на сообщение в чате Telegram:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="cancel_report")]
            ])
        )
    await callback_query.answer()

async def show_no_subscription(callback_query: types.CallbackQuery):
    """Show message when user has no active subscription"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main")],
        [InlineKeyboardButton(text="Купить подписку", callback_data="prices")]
    ])
    
    try:
        await callback_query.message.edit_caption(
            caption="❌ У вас нет активной подписки 💶",
            reply_markup=keyboard
        )
    except:
        await callback_query.message.edit_text(
            text="❌ У вас нет активной подписки 💶",
            reply_markup=keyboard
        )
    await callback_query.answer()

async def process_report_reason(callback_query: types.CallbackQuery):
    """Process report reason and send reports"""
    user_id = callback_query.from_user.id
    user_data = user_reports.get(user_id, {})
    
    if user_data.get('state') != ReportStates.WAITING_FOR_REASON:
        await callback_query.answer("Неверное состояние. Пожалуйста, начните заново.")
        return
    
    reason = callback_query.data.replace('report_', '')
    
    if reason == 'cancel_report':
        await cancel_report(callback_query)
        return
    
    # Map the callback reason to the correct report type
    reason_map = {
        'spam': 'spam',
        'porn': 'pornography',  # Map 'porn' to 'pornography'
        'violence': 'violence'
    }
    
    report_reason = reason_map.get(reason)
    if not report_reason:
        await callback_query.answer("❌ Неверная причина жалобы")
        return
    
    if 'link' not in user_data:
        await callback_query.answer("Ошибка: данные сессии утеряны. Пожалуйста, начните заново.")
        await cancel_report(callback_query)
        return
    
    link = user_data['link']
    
    # Send processing message
    msg = await bot.send_message(callback_query.message.chat.id, "🔄 Отправка жалоб...")
    
    # Send reports using auth manager
    try:
        result = await auth_manager.send_reports(link, report_reason)
        
        # Prepare result message
        if result['success'] > 0:
            success_msg = f"✅ Успешно отправлено {result['success']} из {result['total']} жалоб"
        else:
            success_msg = "❌ Не удалось отправить жалобы"
        
        # Add error details if any
        error_msg = ""
        if result.get('errors'):
            unique_errors = list(set(result['errors']))
            error_msg = "\n\nОшибки:\n" + "\n".join(unique_errors[:3])  # Show max 3 unique errors
            if len(result['errors']) > 3:
                error_msg += f"\n...и еще {len(result['errors']) - 3} ошибок"
        
        # Edit message with results
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=f"{success_msg}{error_msg}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Вернуться в меню", callback_data="back_to_main")]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending reports: {e}")
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text="❌ Произошла ошибка при отправке жалоб. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Вернуться в меню", callback_data="back_to_main")]
            ])
        )
    
    # Clean up
    if user_id in user_reports:
        del user_reports[user_id]
    await callback_query.answer()

async def cancel_report(callback_query: types.CallbackQuery):
    """Cancel report and return to sauce menu"""
    user_id = callback_query.from_user.id
    if user_id in user_reports:
        del user_reports[user_id]
    
    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption="Выберите какой шаучак вам нужен!?",
        reply_markup=await get_inline_keyboard(show_sauces=True)
    )
    await callback_query.answer()

async def handle_order(callback_query: types.CallbackQuery):
    """Handle order button click"""
    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption="Выберите какой шаучак вам нужен!?",
        reply_markup=await get_inline_keyboard(show_sauces=True)
    )

async def show_profile(callback_query: types.CallbackQuery):
    """Show user profile with subscription status"""
    user = callback_query.from_user
    has_sub, status = db.get_subscription_status(user.id)
    
    profile_text = (
        "<b>🌯 Профиль</b>\n\n"
        f"▪️  Имя:  {user.first_name or 'Не указано'}\n"
        f"▪️  ID:  {user.id}\n"
        f"▪️  Username:  @{user.username if user.username else 'Не указан'}\n"
        f"▪️  Подписка:  {status}"
    )
    
    try:
        await bot.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            caption=profile_text,
            reply_markup=await get_inline_keyboard(show_back=True),
            parse_mode="HTML"
        )
    except:
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=profile_text,
            reply_markup=await get_inline_keyboard(show_back=True),
            parse_mode="HTML"
        )

async def show_info(callback_query: types.CallbackQuery):
    """Show information page"""
    info_text = (
        "<b>❓ Информация</b>\n\n"
        "Наши сообщества по приготовлению шаучака!!"
    )
    try:
        await bot.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            caption=info_text,
            reply_markup=await get_inline_keyboard(show_info=True),
            parse_mode="HTML"
        )
    except:
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=info_text,
            reply_markup=await get_inline_keyboard(show_info=True),
            parse_mode="HTML"
        )

async def show_prices(callback_query: types.CallbackQuery):
    """Show prices page"""
    prices_text = (
    "<b>🌯 Ассортимент</b>\n\n"
    "🌯 Шаучак:\n"
    "└─ 1 час - 0.01$\n"
    "└─ 1 день - 2$\n"
    "└─ 3 дня - 3$\n"
    "└─ 7 дней - 5$\n"
    "└─ 30 дней - 9$\n"
    "└─ Навсегда - 13$"
)
    try:
        await bot.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            caption=prices_text,
            reply_markup=await get_inline_keyboard(show_prices=True),
            parse_mode="HTML"
        )
    except:
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=prices_text,
            reply_markup=await get_inline_keyboard(show_prices=True),
            parse_mode="HTML"
        )

async def handle_price_selection(callback_query: types.CallbackQuery):
    """Handle price selection and create payment"""
    tariff_id = callback_query.data.replace("price_", "")
    price_map = {
    '1hour': (0.01, "1 час"),
    '1day': (2, "1 день"),
    '3days': (3, "3 дня"),
    '7days': (5, "7 дней"),
    '30days': (9, "30 дней"),
    'forever': (13, "Навсегда")
}
    
    if tariff_id not in price_map:
        await callback_query.answer("❌ Неверный тариф")
        return
        
    price, period = price_map[tariff_id]
    tariff_days = {
    '1hour': 1/24,  # 1 hour in days
    '1day': 1,
    '3days': 3,
    '7days': 7,
    '30days': 30,
    'forever': 3650  # ~10 years
}
    
    days = tariff_days.get(tariff_id, 0)
    user_id = callback_query.from_user.id
    
    # Create invoice
    invoice = await crypto_pay.create_invoice(
        user_id=user_id,
        amount=price,
        description=f"Подписка на {period}"
    )
    
    if invoice:
        # Store payment info
        pending_payments[invoice['invoice_id']] = {
            'user_id': user_id,
            'days': days,
            'timestamp': datetime.now()
        }
        
        await bot.send_message(
            user_id,
            f"💳 Оплатите {price}$ за тариф на {period}:\n\n"
            f"<a href='{invoice['pay_url']}'>Оплатить {price}$</a>\n\n"
            "После оплаты доступ будет выдан автоматически (проверка каждую минуту).",
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            user_id,
            "❌ Не удалось создать счёт. Пожалуйста, попробуйте позже или свяжитесь с поддержкой."
        )

async def show_main_menu(callback_query: types.CallbackQuery):
    """Show main menu"""
    welcome_text = "Хочешь шаучак!? Добро пожаловать"
    caption = f"<i>\n{welcome_text}\n</i>"
    try:
        await bot.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            caption=caption,
            reply_markup=await get_inline_keyboard(),
            parse_mode="HTML"
        )
    except:
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=caption,
            reply_markup=await get_inline_keyboard(),
            parse_mode="HTML"
        )

async def handle_promo(callback_query: types.CallbackQuery):
    """Handle promo code entry"""
    user_id = callback_query.from_user.id
    user_states[user_id] = UserStates.WAITING_FOR_PROMO
    
    try:
        await bot.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            caption="✏️ Введите промокод:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing promo message: {e}")
        try:
            # Try to edit as text if there's no photo
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                text="✏️ Введите промокод:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
                ])
            )
        except Exception as e2:
            logger.error(f"Error editing text message: {e2}")
            # Fallback to sending a new message if both edits fail
            await callback_query.message.answer(
                "✏️ Введите промокод:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
                ])
            )
    await callback_query.answer()

@dp.message(lambda message: message.from_user.id in user_states and 
                          user_states[message.from_user.id] == UserStates.WAITING_FOR_PROMO)
@check_ban
async def handle_promo_code_input(message: types.Message):
    """Handle promo code input from user"""
    user_id = message.from_user.id
    code = message.text.strip().upper()
    
    # Remove the waiting state
    user_states.pop(user_id, None)
    
    # Check if promo code exists and is valid
    promo = db.get_promo_code(code)
    if not promo:
        await message.answer("❌ Неверный или неактивный промокод")
        return
    
    if promo['used_count'] >= promo['max_uses']:
        await message.answer("❌ Лимит активаций исчерпан")
        return
    
    if promo['expires_at'] and datetime.strptime(promo['expires_at'].split('.')[0], '%Y-%m-%d %H:%M:%S') < datetime.now():
        await message.answer("❌ Срок действия промокода истек")
        return
    
    # Apply promo code
    if db.use_promo_code(code, user_id):
        await message.answer(
            f"✅ Промокод активирован!\n"
            f"🎁 Получено дней подписки: {promo['days']}\n"
            f"🔄 Осталось активаций: {promo['max_uses'] - promo['used_count'] - 1}"
        )
    else:
        await message.answer("❌ Ошибка при активации промокода")

@dp.message(Command("promo"))
@check_ban
async def handle_promo_command(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /promo КОД_ПРОМОКОДА")
        return
    
    code = args[1].upper()
    user_id = message.from_user.id
    
    # Check if promo code exists and is valid
    promo = db.get_promo_code(code)
    if not promo:
        await message.answer("❌ Неверный или неактивный промокод")
        return
    
    if promo['used_count'] >= promo['max_uses']:
        await message.answer("❌ Лимит активаций исчерпан")
        return
    
    if promo['expires_at'] and datetime.strptime(promo['expires_at'].split('.')[0], '%Y-%m-%d %H:%M:%S') < datetime.now():
        await message.answer("❌ Срок действия промокода истек")
        return
    
    # Apply promo code
    if db.use_promo_code(code, user_id):
        await message.answer(
            f"✅ Промокод активирован!\n"
            f"🎁 Получено дней подписки: {promo['days']}\n"
            f"🔄 Осталось активаций: {promo['max_uses'] - promo['used_count'] - 1}"
        )
    else:
        await message.answer("❌ Ошибка при активации промокода")

@dp.message()
@check_ban
async def handle_message(message: types.Message):
    """Handle all messages and check state"""
    user_id = message.from_user.id
    user_data = user_reports.get(user_id, {})
    
    if user_data.get('state') == ReportStates.WAITING_FOR_LINK:
        await process_message_link(message)

async def process_message_link(message: types.Message):
    """Process message link and send reports"""
    user_id = message.from_user.id
    link = message.text.strip()
    
    # Basic validation of the link
    if not (link.startswith('https://t.me/') and '/' in link):
        await message.answer(
            "Пожалуйста, отправьте корректную ссылку на сообщение в формате: https://t.me/username/123",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="cancel_report")]
            ])
        )
        return
    
    # Store the link in user data
    user_reports[user_id] = {
        'link': link
    }
    
    # Send processing message
    msg = await message.answer("🔄 Отправка жалоб...")
    
    # Send reports using auth manager
    try:
        result = await auth_manager.send_reports(link)
        
        # Prepare result message
        if result['success'] > 0:
            success_msg = f"✅ Успешно отправлено {result['success']} из {result['total']} жалоб"
        else:
            success_msg = "❌ Не удалось отправить жалобы"
        
        # Add error details if any
        error_msg = ""
        if result.get('errors'):
            unique_errors = list(set(result['errors']))
            error_msg = "\n\nОшибки:\n" + "\n".join(unique_errors[:3])  # Show max 3 unique errors
            if len(result['errors']) > 3:
                error_msg += f"\n...и еще {len(result['errors']) - 3} ошибок"
        
        # Edit message with results
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=f"{success_msg}{error_msg}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Вернуться в меню", callback_data="back_to_main")]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending reports: {e}")
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text="❌ Произошла ошибка при отправке жалоб. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Вернуться в меню", callback_data="back_to_main")]
            ])
        )
    finally:
        # Clean up
        if user_id in user_reports:
            del user_reports[user_id]

async def main():
    """Main function to start the bot"""
    # Initialize database
    db.create_tables()
    
    # Initialize CryptoPay
    if not await init_crypto_pay():
        logger.error("Failed to initialize CryptoPay. Check your token and network connection.")
        return
    
    # Initialize auth manager
    try:
        count = await init_auth()
        logger.info(f"Initialized {count} Telegram sessions")
        
        # Start the payment checker in the background
        asyncio.create_task(check_pending_payments())
        
        # Start the bot
        await dp.start_polling(bot)
    finally:
        # Close all connections
        await close_auth()
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
    finally:
        # Clean up resources
        asyncio.run(crypto_pay.close())