import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ContextTypes, filters,
    CallbackContext
)
from config import Config
from database import Database
import html

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
Database.initialize()

async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранить все сообщения"""
    if update.effective_message:
        Database.save_message_content(update.effective_message, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    # Клавиатура быстрого доступа
    keyboard = [
        [
            InlineKeyboardButton("📊 Рейтинг чата", callback_data="chat_rating"),
            InlineKeyboardButton("👤 Моя статистика", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("⚠️ Пожаловаться", callback_data="report_menu"),
            InlineKeyboardButton("⚖️ Голосование", callback_data="vote_menu")
        ],
        [
            InlineKeyboardButton("ℹ️ Правила", callback_data="rules"),
            InlineKeyboardButton("🆘 Помощь", callback_data="help")
        ]
    ]
    
    await update.message.reply_text(
        f'🛡️ <b>Система модерации и рейтинга</b>\n\n'
        f'Привет, {user.first_name}!\n'
        f'Я помогаю поддерживать порядок в чате через систему голосований и рейтинга.\n\n'
        f'<b>Основные функции:</b>\n'
        f'• 📊 Система рейтинга участников\n'
        f'• ⚖️ Голосования за бан/мут\n'
        f'• ⚠️ Система жалоб с сохранением контента\n'
        f'• 🎯 Кодовые слова для бонусов\n'
        f'• 📈 Детальная статистика по реакциям\n\n'
        f'Используйте кнопки ниже или команды.',
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def handle_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /report"""
    if not update.effective_message.reply_to_message:
        await update.message.reply_text(
            "❌ <b>Использование:</b>\n"
            "Ответьте на сообщение нарушителя командой <code>/report</code> или\n"
            "<code>/report причина</code>\n\n"
            "<b>Пример:</b> <code>/report спам</code>",
            parse_mode='HTML'
        )
        return
    
    reported_message = update.effective_message.reply_to_message
    reported_user = reported_message.from_user
    
    if reported_user.id == update.effective_user.id:
        await update.message.reply_text("⚠️ Нельзя пожаловаться на самого себя!")
        return
    
    # Получаем причину
    reason = " ".join(context.args) if context.args else "Нарушение правил"
    
    # Сохраняем сообщение если еще не сохранено
    Database.save_message_content(reported_message, context)
    
    # Создаем жалобу
    report_id = Database.create_report(
        reporter_id=update.effective_user.id,
        reported_user_id=reported_user.id,
        message_id=reported_message.message_id,
        chat_id=update.effective_chat.id,
        reason=reason,
        report_type='abuse'
    )
    
    if report_id:
        # Показываем меню действий
        keyboard = [
            [
                InlineKeyboardButton("⚖️ Начать голосование", callback_data=f"vote_from_report:{report_id}"),
                InlineKeyboardButton("⚠️ Выдать предупреждение", callback_data=f"warn:{reported_user.id}")
            ],
            [
                InlineKeyboardButton("👁️ Просмотреть сообщение", callback_data=f"view_message:{reported_message.message_id}"),
                InlineKeyboardButton("❌ Отклонить жалобу", callback_data=f"dismiss_report:{report_id}")
            ]
        ]
        
        await update.message.reply_text(
            f"✅ <b>Жалоба #{report_id} зарегистрирована</b>\n\n"
            f"👤 <b>Нарушитель:</b> @{reported_user.username or reported_user.first_name}\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f"🕐 <b>Время:</b> {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"Сообщение сохранено в базе данных.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ Ошибка при создании жалобы")

async def handle_vote_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Улучшенная команда /vote_ban с детальной статистикой"""
    if not update.effective_message.reply_to_message and len(context.args) < 1:
        await show_vote_help(update, context)
        return
    
    # Определяем цель
    if update.effective_message.reply_to_message:
        # Если ответ на сообщение
        target_message = update.effective_message.reply_to_message
        target_user = target_message.from_user
        target_username = target_user.username or target_user.first_name
        
        # Сохраняем сообщение
        Database.save_message_content(target_message, context)
        related_message_id = target_message.message_id
    else:
        # Если через аргументы
        target_username = context.args[0].replace('@', '')
        related_message_id = None
        
        # Находим пользователя по username
        conn = Database.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT user_id, first_name FROM users WHERE username = %s',
                    (target_username,)
                )
                result = cur.fetchone()
                if not result:
                    await update.message.reply_text(f"❌ Пользователь @{target_username} не найден")
                    return
                target_user_id, first_name = result
                target_username = target_username or first_name
        finally:
            Database.return_connection(conn)
        target_user = type('obj', (object,), {'id': target_user_id, 'username': target_username})
    
    # Проверяем себя
    if target_user.id == update.effective_user.id:
        await update.message.reply_text("⚠️ Нельзя начать голосование против себя!")
        return
    
    # Получаем параметры
    try:
        duration = int(context.args[1]) if len(context.args) > 1 else 60
        if duration <= 0 or duration > 10080:
            await update.message.reply_text("⏱️ Укажите время от 1 до 10080 минут (7 дней)")
            return
    except (ValueError, IndexError):
        duration = 60
    
    reason = " ".join(context.args[2:]) if len(context.args) > 2 else "Нарушение правил чата"
    
    # Получаем детальную статистику пользователя
    stats = Database.get_user_statistics(target_user.id, update.effective_chat.id)
    
    if not stats:
        await update.message.reply_text("❌ Не удалось получить статистику пользователя")
        return
    
    # Создаем голосование
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO votes 
                (chat_id, target_user_id, initiator_user_id, vote_type, 
                 duration_minutes, reason, related_message_id, required_votes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 
                        GREATEST(3, CAST((SELECT COUNT(*) FROM chat_members WHERE chat_id = %s) * 0.3 AS INTEGER)))
                RETURNING vote_id
            ''', (
                update.effective_chat.id,
                target_user.id,
                update.effective_user.id,
                'ban',
                duration,
                reason,
                related_message_id,
                update.effective_chat.id
            ))
            
            vote_id = cur.fetchone()[0]
        conn.commit()
    except Exception as e:
        logger.error(f"Error creating vote: {e}")
        await update.message.reply_text("❌ Ошибка при создании голосования")
        return
    finally:
        Database.return_connection(conn)
    
    # Формируем детальную информацию
    stats_text = f"""
📊 <b>Статистика пользователя:</b>
├ Положительные реакции: {stats['positive_reactions']} 👍❤️🔥
├ Отрицательные реакции: {stats['negative_reactions']} 👎💩🤮
├ Нейтральные реакции: {stats['neutral_reactions']} 🤔😐🙄
├ Получено жалоб: {stats['reports_received']}
├ Активные предупреждения: {stats['active_warnings']}/3
└ Рейтинг: {stats['rating']} ⭐
"""
    
    if stats['warning_reasons']:
        stats_text += f"\n📝 <b>Причины предупреждений:</b>\n{stats['warning_reasons']}\n"
    
    # Создаем клавиатуру
    keyboard = [
        [
            InlineKeyboardButton(f"✅ ЗА БАН ({duration} мин)", callback_data=f"vote:for:{vote_id}"),
            InlineKeyboardButton(f"❌ ПРОТИВ", callback_data=f"vote:against:{vote_id}")
        ],
        [
            InlineKeyboardButton("👁️ Просмотреть сообщение", callback_data=f"view_related:{related_message_id}" if related_message_id else "no_message"),
            InlineKeyboardButton("📊 Детальная статистика", callback_data=f"full_stats:{target_user.id}")
        ],
        [
            InlineKeyboardButton("📝 История нарушений", callback_data=f"violation_history:{target_user.id}"),
            InlineKeyboardButton("⏰ Осталось: 5:00", callback_data=f"vote_timer:{vote_id}")
        ]
    ]
    
    vote_text = f"""
🗳️ <b>ГОЛОСОВАНИЕ ЗА БАН #{vote_id}</b>

👤 <b>Цель:</b> @{target_username} (ID: {target_user.id})
⏱️ <b>Длительность:</b> {duration} минут
📝 <b>Причина:</b> {reason}
👤 <b>Инициатор:</b> @{update.effective_user.username}

{stats_text}

⏰ <b>Голосование активно 5 минут</b>
📊 <b>Требуется большинство голосов</b>
"""
    
    message = await update.message.reply_text(
        vote_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    
    # Запускаем таймер обновления
    context.job_queue.run_repeating(
        update_vote_timer,
        interval=30,
        first=30,
        data={
            'chat_id': update.effective_chat.id,
            'message_id': message.message_id,
            'vote_id': vote_id,
            'end_time': datetime.now() + timedelta(minutes=5)
        }
    )
    
    # Запускаем завершение голосования
    context.job_queue.run_once(
        finish_vote,
        300,
        data={
            'chat_id': update.effective_chat.id,
            'vote_id': vote_id,
            'message_id': message.message_id,
            'target_user_id': target_user.id,
            'duration': duration
        }
    )

async def update_vote_timer(context: CallbackContext):
    """Обновление таймера голосования"""
    job_data = context.job.data
    
    try:
        # Получаем текущее состояние голосования
        conn = Database.get_connection()
        with conn.cursor() as cur:
            cur.execute('''
                SELECT votes_for, votes_against, voters
                FROM votes WHERE vote_id = %s
            ''', (job_data['vote_id'],))
            
            result = cur.fetchone()
            if not result:
                return
            
            votes_for, votes_against, voters = result
            total_voters = len(voters) if voters else 0
    finally:
        Database.return_connection(conn)
    
    # Рассчитываем оставшееся время
    remaining = job_data['end_time'] - datetime.now()
    if remaining.total_seconds() <= 0:
        context.job.schedule_removal()
        return
    
    minutes = int(remaining.total_seconds() // 60)
    seconds = int(remaining.total_seconds() % 60)
    
    # Обновляем кнопку таймера
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=job_data['chat_id'],
            message_id=job_data['message_id'],
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"✅ ЗА ({votes_for})", callback_data=f"vote:for:{job_data['vote_id']}"),
                    InlineKeyboardButton(f"❌ ПРОТИВ ({votes_against})", callback_data=f"vote:against:{job_data['vote_id']}")
                ],
                [
                    InlineKeyboardButton("📊 Голосовало", callback_data=f"voters_list:{job_data['vote_id']}"),
                    InlineKeyboardButton(f"⏰ {minutes}:{seconds:02d}", callback_data=f"vote_timer:{job_data['vote_id']}")
                ]
            ])
        )
    except:
        pass  # Игнорируем ошибки редактирования

async def show_vote_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать помощь по голосованиям"""
    help_text = """
🗳️ <b>СИСТЕМА ГОЛОСОВАНИЙ</b>

<b>Способы использования:</b>

1. <b>Ответить на сообщение:</b>
   <code>/vote_ban 60 спам</code>
   → Бан на 60 минут за спам

2. <b>По username:</b>
   <code>/vote_ban @username 120 оскорбления</code>
   → Бан @username на 120 минут

3. <b>Быстрое голосование:</b>
   Ответить на сообщение командой <code>/report</code>

<b>Доступные типы голосований:</b>
• /vote_ban - Бан пользователя
• /vote_mute - Мут (запрет писать)
• /vote_kick - Исключение из чата
• /vote_warn - Выдать предупреждение

<b>При голосовании показывается:</b>
✅ Статистика реакций пользователя
✅ История предупреждений
✅ Сохраненное сообщение (если есть)
✅ Причины прошлых жалоб
"""
    
    await update.message.reply_text(help_text, parse_mode='HTML')

async def handle_view_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать сохраненное сообщение"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    message_id = int(data[1])
    
    # Получаем сохраненное сообщение
    message_data = Database.get_message_content(message_id, query.message.chat_id)
    
    if not message_data:
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ Сообщение не найдено в архиве",
            reply_markup=query.message.reply_markup
        )
        return
    
    message_type, content, photo_url, file_id, caption = message_data
    
    if message_type == 'photo' and file_id:
        try:
            # Пытаемся отправить фото
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=file_id,
                caption=f"📸 <b>Сохраненное сообщение</b>\nID: {message_id}\n\n{caption or 'Фото'}",
                parse_mode='HTML',
                reply_to_message_id=query.message.message_id
            )
        except:
            # Если не удалось, показываем информацию
            preview_text = f"📸 Фото (ID: {file_id[:20]}...)\n{caption or 'Без описания'}"
            await query.answer(preview_text, show_alert=True)
    
    elif content:
        escaped_content = html.escape(content[:1000])
        if len(content) > 1000:
            escaped_content += "..."
        
        preview_text = f"""
💬 <b>Сохраненное сообщение</b>
ID: {message_id}
Тип: {message_type}

<b>Содержимое:</b>
{escaped_content}
"""
        
        if caption:
            escaped_caption = html.escape(caption[:500])
            preview_text += f"\n<b>Описание:</b>\n{escaped_caption}"
        
        await query.answer(preview_text, show_alert=True)
    
    else:
        await query.answer("⚠️ Сообщение без текстового содержимого", show_alert=True)

async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка реакций на сообщения"""
    if not update.message_reaction:
        return
    
    reaction = update.message_reaction
    user = reaction.user
    
    # Сохраняем реакцию
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            # Определяем тип реакции
            reaction_emoji = reaction.new_reaction[0].emoji if reaction.new_reaction else None
            
            if not reaction_emoji:
                return
            
            # Находим автора сообщения
            cur.execute('''
                SELECT user_id FROM messages 
                WHERE message_id = %s AND chat_id = %s
            ''', (reaction.message_id, update.effective_chat.id))
            
            result = cur.fetchone()
            if not result:
                return
            
            target_user_id = result[0]
            
            # Сохраняем реакцию
            try:
                cur.execute('''
                    INSERT INTO message_reactions 
                    (message_id, chat_id, user_id, reaction)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (message_id, chat_id, user_id, reaction) DO NOTHING
                ''', (reaction.message_id, update.effective_chat.id, user.id, reaction_emoji))
            except:
                pass  # Игнорируем дубликаты
            
            # Обновляем статистику пользователя
            if reaction_emoji in Database.POSITIVE_REACTIONS:
                cur.execute('''
                    UPDATE users 
                    SET positive_reactions = positive_reactions + 1,
                        rating = rating + 5
                    WHERE user_id = %s
                ''', (target_user_id,))
            elif reaction_emoji in Database.NEGATIVE_REACTIONS:
                cur.execute('''
                    UPDATE users 
                    SET negative_reactions = negative_reactions + 1,
                        rating = rating - 3
                    WHERE user_id = %s
                ''', (target_user_id,))
            else:
                cur.execute('''
                    UPDATE users 
                    SET neutral_reactions = neutral_reactions + 1
                    WHERE user_id = %s
                ''', (target_user_id,))
            
            # Обновляем рейтинг того, кто поставил реакцию
            cur.execute('''
                UPDATE users 
                SET rating = rating + 1
                WHERE user_id = %s
            ''', (user.id,))
            
        conn.commit()
    except Exception as e:
        logger.error(f"Error processing reaction: {e}")
    finally:
        Database.return_connection(conn)

async def show_user_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детальную статистику пользователя"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    user_id = int(data[1])
    
    stats = Database.get_user_statistics(user_id, query.message.chat_id)
    
    if not stats:
        await query.answer("Статистика не найдена", show_alert=True)
        return
    
    # Получаем топ реакций
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT reaction, COUNT(*) as count
                FROM message_reactions 
                WHERE user_id = %s
                GROUP BY reaction
                ORDER BY count DESC
                LIMIT 10
            ''', (user_id,))
            
            top_reactions = cur.fetchall()
    finally:
        Database.return_connection(conn)
    
    reactions_text = ""
    for reaction, count in top_reactions[:5]:
        reactions_text += f"{reaction}: {count} раз\n"
    
    stats_text = f"""
📈 <b>ДЕТАЛЬНАЯ СТАТИСТИКА</b>

👤 <b>Пользователь:</b> @{stats['username'] or stats['first_name']}

🏆 <b>Рейтинг:</b> {stats['rating']} ⭐
⚠️ <b>Предупреждения:</b> {stats['warnings']}/3

📊 <b>Реакции получено:</b>
├ 👍 Положительных: {stats['positive_reactions']}
├ 👎 Отрицательных: {stats['negative_reactions']}
└ 😐 Нейтральных: {stats['neutral_reactions']}

📋 <b>Жалобы:</b>
├ 📨 Получено: {stats['reports_received']}
├ ⏳ Ожидает рассмотрения: {stats['pending_reports']}
└ 📝 Последние причины: {stats['report_reasons'] or 'Нет'}

🎯 <b>Топ реакций:</b>
{reactions_text}

📅 <b>Активность:</b>
├ 🎯 Последняя реакция: недавно
└ 🏁 В системе: с {stats.get('join_date', 'неизвестно')}
"""
    
    await query.answer(stats_text, show_alert=True)

async def handle_message_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка удаленных сообщений"""
    if not update.effective_message or not update.effective_message.delete_chat_photo:
        return
    
    deleted_message = update.effective_message
    
    # Помечаем сообщение как удаленное в базе
    conn = Database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                UPDATE messages 
                SET is_deleted = TRUE,
                    deleted_at = CURRENT_TIMESTAMP
                WHERE message_id = %s AND chat_id = %s
            ''', (deleted_message.message_id, deleted_message.chat.id))
        conn.commit()
        
        logger.info(f"Message {deleted_message.message_id} marked as deleted")
    except Exception as e:
        logger.error(f"Error marking message as deleted: {e}")
    finally:
        Database.return_connection(conn)

async def auto_save_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Автоматическое сохранение медиа-контента"""
    message = update.effective_message
    
    if not message:
        return
    
    # Сохраняем все типы сообщений
    Database.save_message_content(message, context)
    
    # Если есть подпись с кодовыми словами, обрабатываем
    if message.caption:
        await handle_codewords(update, context)

async def setup_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройка команд для администраторов"""
    commands = [
        ("start", "Запустить бота"),
        ("report", "Пожаловаться на сообщение"),
        ("vote_ban", "Начать голосование за бан"),
        ("vote_mute", "Начать голосование за мут"),
        ("rating", "Рейтинг участников"),
        ("stats", "Моя статистика"),
        ("warn", "Выдать предупреждение (админам)"),
        ("moderate", "Панель модерации (админам)")
    ]
    
    await context.bot.set_my_commands(commands)

def main():
    """Основная функция запуска бота"""
    application = Application.builder().token(Config.TOKEN).build()
    
    # Базовые команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("report", handle_report_command))
    application.add_handler(CommandHandler("vote_ban", handle_vote_ban))
    application.add_handler(CommandHandler("vote_help", show_vote_help))
    application.add_handler(CommandHandler("setup", setup_admin_commands))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(handle_view_message, pattern="^view_message:"))
    application.add_handler(CallbackQueryHandler(handle_view_message, pattern="^view_related:"))
    application.add_handler(CallbackQueryHandler(show_user_detailed_stats, pattern="^full_stats:"))
    application.add_handler(CallbackQueryHandler(show_user_detailed_stats, pattern="^violation_history:"))
    
    # Обработчики голосований (предыдущая реализация)
    application.add_handler(CallbackQueryHandler(handle_vote_button, pattern="^vote:"))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, auto_save_media))
    application.add_handler(MessageHandler(filters.REACTION, handle_reaction))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER | 
                                          filters.StatusUpdate.NEW_CHAT_MEMBERS, 
                                          save_message))
    
    # Обработчик удаленных сообщений
    application.add_handler(MessageHandler(filters.UpdateType.MESSAGE, handle_message_delete))
    
    # Запуск
    if Config.WEBHOOK_HOST:
        # Webhook для Render
        logger.info(f"Starting webhook on {Config.WEBHOOK_URL}")
        application.run_webhook(
            listen=Config.HOST,
            port=Config.PORT,
            url_path=Config.WEBHOOK_PATH,
            webhook_url=Config.WEBHOOK_URL,
            drop_pending_updates=True
        )
    else:
        # Polling для локальной разработки
        logger.info("Starting polling...")
        application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
