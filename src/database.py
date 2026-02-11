import psycopg2
from psycopg2 import pool
from config import Config
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    _connection_pool = None
    
    # Определяем эмоции
    POSITIVE_REACTIONS = ['👍', '❤️', '🔥', '🎉', '👏', '😂']
    NEGATIVE_REACTIONS = ['👎', '💩', '🤮', '😡', '🤬', '🚫']
    NEUTRAL_REACTIONS = ['🤔', '😐', '🙄', '😴', '🤷', '⁉️']
    
    @classmethod
    def initialize(cls):
        """Инициализация пула соединений"""
        try:
            cls._connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20, Config.DATABASE_URL, sslmode='require'
            )
            logger.info("Database pool initialized successfully")
            cls.create_tables()
        except Exception as e:
            logger.error(f"Error initializing database pool: {e}")
            raise
    
    @classmethod
    def get_connection(cls):
        """Получить соединение из пула"""
        if cls._connection_pool is None:
            cls.initialize()
        return cls._connection_pool.getconn()
    
    @classmethod
    def return_connection(cls, connection):
        """Вернуть соединение в пул"""
        cls._connection_pool.putconn(connection)
    
    @classmethod
    def create_tables(cls):
        """Создание таблиц"""
        conn = cls.get_connection()
        try:
            with conn.cursor() as cur:
                # Таблица пользователей с расширенной статистикой
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        rating INTEGER DEFAULT 1000,
                        warnings INTEGER DEFAULT 0,
                        is_banned BOOLEAN DEFAULT FALSE,
                        ban_until TIMESTAMP,
                        total_reports INTEGER DEFAULT 0,
                        reports_received INTEGER DEFAULT 0,
                        reports_made INTEGER DEFAULT 0,
                        positive_reactions INTEGER DEFAULT 0,
                        negative_reactions INTEGER DEFAULT 0,
                        neutral_reactions INTEGER DEFAULT 0,
                        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Таблица сообщений (для сохранения контента)
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        message_id BIGINT,
                        chat_id BIGINT,
                        user_id BIGINT,
                        message_type TEXT,
                        content TEXT,
                        photo_url TEXT,
                        file_id TEXT,
                        caption TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_deleted BOOLEAN DEFAULT FALSE,
                        deleted_at TIMESTAMP,
                        PRIMARY KEY (message_id, chat_id)
                    )
                ''')
                
                # Таблица реакций на сообщения
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS message_reactions (
                        reaction_id SERIAL PRIMARY KEY,
                        message_id BIGINT,
                        chat_id BIGINT,
                        user_id BIGINT,
                        reaction TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(message_id, chat_id, user_id, reaction)
                    )
                ''')
                
                # Таблица жалоб
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS reports (
                        report_id SERIAL PRIMARY KEY,
                        chat_id BIGINT,
                        reporter_id BIGINT,
                        reported_user_id BIGINT,
                        message_id BIGINT,
                        reason TEXT,
                        report_type TEXT, -- 'spam', 'abuse', 'scam', 'other'
                        status TEXT DEFAULT 'pending', -- 'pending', 'reviewed', 'dismissed', 'action_taken'
                        moderator_id BIGINT,
                        resolution TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        resolved_at TIMESTAMP
                    )
                ''')
                
                # Таблица голосований с расширенными полями
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS votes (
                        vote_id SERIAL PRIMARY KEY,
                        chat_id BIGINT,
                        target_user_id BIGINT,
                        initiator_user_id BIGINT,
                        vote_type TEXT, -- 'ban', 'kick', 'mute', 'warn'
                        duration_minutes INTEGER,
                        reason TEXT,
                        related_message_id BIGINT,
                        related_report_id BIGINT,
                        votes_for INTEGER DEFAULT 0,
                        votes_against INTEGER DEFAULT 0,
                        required_votes INTEGER DEFAULT 5,
                        voters JSONB DEFAULT '[]',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '5 minutes'),
                        is_active BOOLEAN DEFAULT TRUE,
                        result BOOLEAN,
                        ban_executed BOOLEAN DEFAULT FALSE
                    )
                ''')
                
                # Таблица предупреждений
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS warnings (
                        warning_id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        chat_id BIGINT,
                        reason TEXT,
                        given_by BIGINT,
                        severity INTEGER DEFAULT 1, -- 1-3
                        is_active BOOLEAN DEFAULT TRUE,
                        expires_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Индексы для производительности
                cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, chat_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_reactions_user ON message_reactions(user_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_reports_reported ON reports(reported_user_id, status)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_votes_active ON votes(is_active, expires_at) WHERE is_active = TRUE')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_warnings_active ON warnings(user_id, is_active) WHERE is_active = TRUE')
                
            conn.commit()
            logger.info("Tables created successfully")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating tables: {e}")
            raise
        finally:
            cls.return_connection(conn)
    
    @classmethod
    def save_message_content(cls, message, context):
        """Сохранить содержимое сообщения"""
        conn = cls.get_connection()
        try:
            with conn.cursor() as cur:
                content = None
                photo_url = None
                file_id = None
                caption = message.caption
                message_type = 'text'
                
                if message.text:
                    content = message.text
                    message_type = 'text'
                elif message.photo:
                    # Сохраняем самую большую версию фото
                    photo = message.photo[-1]
                    file_id = photo.file_id
                    # Получаем URL файла (нужен доступ к боту)
                    try:
                        file = context.bot.get_file(file_id)
                        photo_url = file.file_path
                    except:
                        photo_url = None
                    message_type = 'photo'
                    content = caption or "Фото"
                elif message.document:
                    file_id = message.document.file_id
                    content = message.document.file_name
                    message_type = 'document'
                elif message.sticker:
                    file_id = message.sticker.file_id
                    content = message.sticker.emoji or "Стикер"
                    message_type = 'sticker'
                elif message.video:
                    file_id = message.video.file_id
                    content = caption or "Видео"
                    message_type = 'video'
                elif message.audio:
                    file_id = message.audio.file_id
                    content = caption or message.audio.title or "Аудио"
                    message_type = 'audio'
                elif message.voice:
                    file_id = message.voice.file_id
                    content = "Голосовое сообщение"
                    message_type = 'voice'
                
                cur.execute('''
                    INSERT INTO messages 
                    (message_id, chat_id, user_id, message_type, content, photo_url, file_id, caption)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_id, chat_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    photo_url = EXCLUDED.photo_url,
                    caption = EXCLUDED.caption
                ''', (
                    message.message_id,
                    message.chat.id,
                    message.from_user.id if message.from_user else None,
                    message_type,
                    content,
                    photo_url,
                    file_id,
                    caption
                ))
                
                # Обновляем статистику пользователя
                if message.from_user:
                    cur.execute('''
                        UPDATE users 
                        SET last_active = CURRENT_TIMESTAMP
                        WHERE user_id = %s
                    ''', (message.from_user.id,))
                
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            conn.rollback()
            return False
        finally:
            cls.return_connection(conn)
    
    @classmethod
    def get_user_statistics(cls, user_id, chat_id=None):
        """Получить полную статистику пользователя"""
        conn = cls.get_connection()
        try:
            with conn.cursor() as cur:
                # Базовая информация
                cur.execute('''
                    SELECT username, first_name, rating, warnings, 
                           reports_received, positive_reactions, 
                           negative_reactions, neutral_reactions
                    FROM users WHERE user_id = %s
                ''', (user_id,))
                
                user_data = cur.fetchone()
                if not user_data:
                    return None
                
                # Подсчет реакций по категориям
                cur.execute('''
                    SELECT 
                        COUNT(CASE WHEN reaction IN %s THEN 1 END) as positive,
                        COUNT(CASE WHEN reaction IN %s THEN 1 END) as negative,
                        COUNT(CASE WHEN reaction NOT IN %s AND reaction NOT IN %s THEN 1 END) as neutral
                    FROM message_reactions 
                    WHERE user_id = %s
                ''', (
                    tuple(cls.POSITIVE_REACTIONS),
                    tuple(cls.NEGATIVE_REACTIONS),
                    tuple(cls.POSITIVE_REACTIONS),
                    tuple(cls.NEGATIVE_REACTIONS),
                    user_id
                ))
                
                reactions = cur.fetchone()
                
                # Активные предупреждения
                cur.execute('''
                    SELECT COUNT(*), 
                           STRING_AGG(reason, '; ' ORDER BY created_at DESC)
                    FROM warnings 
                    WHERE user_id = %s AND is_active = TRUE
                ''', (user_id,))
                
                warnings_data = cur.fetchone()
                
                # Жалобы на пользователя
                cur.execute('''
                    SELECT COUNT(*), 
                           STRING_AGG(reason, '; ' ORDER BY created_at DESC)
                    FROM reports 
                    WHERE reported_user_id = %s AND status = 'pending'
                ''', (user_id,))
                
                reports_data = cur.fetchone()
                
                return {
                    'username': user_data[0],
                    'first_name': user_data[1],
                    'rating': user_data[2],
                    'warnings': user_data[3],
                    'reports_received': user_data[4],
                    'positive_reactions': user_data[5],
                    'negative_reactions': user_data[6],
                    'neutral_reactions': user_data[7],
                    'reactions_received': {
                        'positive': reactions[0] if reactions else 0,
                        'negative': reactions[1] if reactions else 0,
                        'neutral': reactions[2] if reactions else 0
                    },
                    'active_warnings': warnings_data[0] if warnings_data else 0,
                    'warning_reasons': warnings_data[1] if warnings_data else None,
                    'pending_reports': reports_data[0] if reports_data else 0,
                    'report_reasons': reports_data[1] if reports_data else None
                }
                
        except Exception as e:
            logger.error(f"Error getting user statistics: {e}")
            return None
        finally:
            cls.return_connection(conn)
    
    @classmethod
    def get_message_content(cls, message_id, chat_id):
        """Получить сохраненное содержимое сообщения"""
        conn = cls.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT message_type, content, photo_url, file_id, caption
                    FROM messages 
                    WHERE message_id = %s AND chat_id = %s
                ''', (message_id, chat_id))
                
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Error getting message content: {e}")
            return None
        finally:
            cls.return_connection(conn)
    
    @classmethod
    def create_report(cls, reporter_id, reported_user_id, message_id, chat_id, reason, report_type):
        """Создать жалобу"""
        conn = cls.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO reports 
                    (chat_id, reporter_id, reported_user_id, message_id, reason, report_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING report_id
                ''', (chat_id, reporter_id, reported_user_id, message_id, reason, report_type))
                
                report_id = cur.fetchone()[0]
                
                # Обновляем статистику
                cur.execute('''
                    UPDATE users 
                    SET reports_received = reports_received + 1
                    WHERE user_id = %s
                ''', (reported_user_id,))
                
                cur.execute('''
                    UPDATE users 
                    SET reports_made = reports_made + 1
                    WHERE user_id = %s
                ''', (reporter_id,))
                
            conn.commit()
            return report_id
        except Exception as e:
            logger.error(f"Error creating report: {e}")
            conn.rollback()
            return None
        finally:
            cls.return_connection(conn)
