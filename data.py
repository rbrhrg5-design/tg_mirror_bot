import asyncio
import logging
import re
import sqlite3
import feedparser
from telethon import TelegramClient, events

DB_FILE = "state.db"

# ------------- دیتابیس -------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS sources(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        identifier TEXT,
        interval_sec INTEGER
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS targets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT,
        topic_id INTEGER
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS processed(
        id TEXT PRIMARY KEY
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS block_words(word TEXT PRIMARY KEY)
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS replacements(find TEXT PRIMARY KEY, replace TEXT)
    """)
    conn.commit()
    conn.close()

def add_processed(message_id: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO processed(id) VALUES(?)", (message_id,))
    conn.commit()
    conn.close()

def is_processed(message_id: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM processed WHERE id=?", (message_id,))
    res = c.fetchone()
    conn.close()
    return res is not None

# ------------- کلاس ربات -------------
class MirrorBot:
    def __init__(self, api_id:int, api_hash:str, session:str):
        self.client = TelegramClient(session, api_id, api_hash)
        self.sources = []   
        self.targets = []   
        self.block_words = []   
        self.replacements = []  

    async def start(self):
        await self.client.start()
        logging.info("Bot started")
        self.load_db()
        # تلگرام
        self.client.add_event_handler(self.on_message, events.NewMessage(chats=[s['identifier'] for s in self.sources if s['type']=='telegram']))
        # RSS
        asyncio.create_task(self.rss_loop())
        # دستورات مدیریتی
        asyncio.create_task(self.admin_commands())

    def load_db(self):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT type, identifier, interval_sec FROM sources")
        self.sources = [{'type':row[0], 'identifier':row[1], 'interval_sec':row[2]} for row in c.fetchall()]
        c.execute("SELECT chat, topic_id FROM targets")
        self.targets = [{'chat':row[0], 'topic_id':row[1]} for row in c.fetchall()]
        c.execute("SELECT word FROM block_words")
        self.block_words = [row[0] for row in c.fetchall()]
        c.execute("SELECT find, replace FROM replacements")
        self.replacements = [{'find':row[0], 'replace':row[1]} for row in c.fetchall()]
        conn.close()

    def transform_text(self, text:str) -> str:
        t = text or ""
        for w in self.block_words:
            if w.lower() in t.lower():
                return ""
        for rule in self.replacements:
            t = re.sub(rule['find'], rule['replace'], t, flags=re.IGNORECASE)
        return t.strip()

    async def on_message(self, event):
        message = event.message
        if is_processed(str(message.id)):
            return
        text = self.transform_text(message.text or "")
        if not text:
            return
        for target in self.targets:
            try:
                await self.client.send_message(target['chat'], text)
            except Exception as e:
                logging.warning(f"Failed to send message: {e}")
        add_processed(str(message.id))

    # ------------- RSS -------------
    async def rss_loop(self):
        while True:
            for s in self.sources:
                if s['type'] == 'rss':
                    try:
                        feed = feedparser.parse(s['identifier'])
                        for entry in feed.entries:
                            msg_id = entry.id if 'id' in entry else entry.link
                            if is_processed(msg_id):
                                continue
                            text = self.transform_text(entry.title + "\n" + entry.get('summary',''))
                            if text:
                                for target in self.targets:
                                    await self.client.send_message(target['chat'], text)
                            add_processed(msg_id)
                    except Exception as e:
                        logging.warning(f"RSS error {s['identifier']}: {e}")
            await asyncio.sleep(60)

    # ------------- پنل مدیریتی -------------
    async def admin_commands(self):
        @self.client.on(events.NewMessage(pattern=r'/add_source (.+)'))
        async def add_source(event):
            chat = event.pattern_match.group(1)
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO sources(type, identifier, interval_sec) VALUES(?,?,?)", ('telegram', chat, 180))
            conn.commit()
            conn.close()
            self.load_db()
            await event.reply(f"Source added: {chat}")

        @self.client.on(events.NewMessage(pattern=r'/remove_source (.+)'))
        async def remove_source(event):
            chat = event.pattern_match.group(1)
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM sources WHERE identifier=?", (chat,))
            conn.commit()
            conn.close()
            self.load_db()
            await event.reply(f"Source removed: {chat}")

        @self.client.on(events.NewMessage(pattern=r'/add_target (.+)'))
        async def add_target(event):
            chat = event.pattern_match.group(1)
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO targets(chat, topic_id) VALUES(?,?)", (chat, None))
            conn.commit()
            conn.close()
            self.load_db()
            await event.reply(f"Target added: {chat}")

        @self.client.on(events.NewMessage(pattern=r'/remove_target (.+)'))
        async def remove_target(event):
            chat = event.pattern_match.group(1)
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM targets WHERE chat=?", (chat,))
            conn.commit()
            conn.close()
            self.load_db()
            await event.reply(f"Target removed: {chat}")

        # بلاک و جایگزینی میشه مشابه اضافه کرد

# ------------- اجرای ربات -------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    api_id = 1234567           # مقدار واقعی خودت
    api_hash = "YOUR_API_HASH" # مقدار واقعی خودت
    session = "mirror_session"
    bot = MirrorBot(api_id, api_hash, session)
    asyncio.run(bot.start())