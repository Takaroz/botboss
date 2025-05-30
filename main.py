import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from myServer import server_on

# ---------- CONFIG ----------
TOKEN = os.getenv('TOKEN')  # <-- ใส่ Token จริงที่นี่
DB_PATH = "bosses.db"
CHANNEL_ID = 1377663275650515094  # <-- เปลี่ยนเป็น channel id ที่จะใช้แจ้งเตือน

# ---------- BOT SETUP ----------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# ---------- AUTOCOMPLETE ----------
async def boss_name_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name FROM bosses WHERE name LIKE ?", (f"%{current}%",))
        names = [row[0] for row in await cursor.fetchall()]
    return [app_commands.Choice(name=name, value=name) for name in names]

# ---------- ON READY ----------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    check_spawn_notifications.start()

# ---------- CREATE TABLE ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bosses (
                no INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                period TEXT NOT NULL,
                next_spawn TEXT,
                locate TEXT DEFAULT '-'
            )
        """)
        await db.executemany("""
            INSERT INTO bosses (name, period, locate) VALUES (?, ?, ?)
        """, [
            ("เชอร์ทูบา", "06:00", "-"),
            ("เคลซอส", "10:00", "-"),
            ("บาซิลา", "04:00", "-"),
            ("เฟลิส", "03:00", "-"),
            ("ทาลาคิน", "10:00", "-"),
            ("พันดรายด์", "12:00", "-"),
            ("ซาร์ก้า", "10:00", "-"),
            ("ทิมิทริส", "08:00", "-"),
            ("สตัน", "07:00", "-"),
            ("ครูม่ากลายพัน", "08:00", "-"),
            ("พันนาโรด", "10:00", "-"),
            ("เมดูซ่า", "10:00", "-"),
            ("เบรก้า", "06:00", "-"),
            ("มาทูรา", "06:00", "-"),
            ("แบล็คลิลลี่", "12:00", "-"),
            ("เบฮีมอธ", "09:00", "-"),
            ("ซาบัน", "12:00", "มดชั้น2"),
            ("ราชินีมด", "06:00", "มดชั้น3"),
            ("ครูม่าปนเปื้อน", "08:00", "ครูม่าชั้น 3"),
            ("คาทาน", "10:00", "ครูม่าชั้น 6"),
            ("คอร์ซัส", "10:00", "ครูม่าชั้น 7"),
        ])
        await db.commit()

# ---------- ADD BOSS ----------
@bot.tree.command(name="addboss", description="เพิ่มบอสใหม่")
@app_commands.describe(name="ชื่อบอส", period="ช่วงเวลาเกิดใหม่ (HH:MM)", locate="สถานที่")
async def addboss(interaction: discord.Interaction, name: str, period: str, locate: str = "-"):
    try:
        datetime.strptime(period, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ รูปแบบเวลาไม่ถูกต้อง (ต้องเป็น HH:MM)", ephemeral=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO bosses (name, period, locate) VALUES (?, ?, ?)", (name, period, locate))
        await db.commit()
    await interaction.response.send_message(f"✅ เพิ่มบอส {name} แล้ว")

# ---------- LIST BOSSES ----------
@bot.tree.command(name="listboss", description="แสดงรายชื่อบอสทั้งหมด")
async def listboss(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT no, name, locate, period, next_spawn FROM bosses ORDER BY no ASC") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await interaction.response.send_message("⚠️ ยังไม่มีข้อมูลบอสในระบบ")
        return
    msg = "**📋 รายชื่อบอสทั้งหมด:**\n"
    for no, name, locate, period, next_spawn in rows:
        msg += f"NO.{no}\t {name}\t {locate}\t ({period})\t {next_spawn}\n"
    await interaction.response.send_message(msg)

# ---------- DELETE BOSS ----------
@bot.tree.command(name="deleteboss", description="ลบบอส")
@app_commands.describe(boss_name="ชื่อบอสที่จะลบ")
@app_commands.autocomplete(boss_name=boss_name_autocomplete)
async def deleteboss(interaction: discord.Interaction, boss_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bosses WHERE name = ?", (boss_name,))
        await db.commit()
    await interaction.response.send_message(f"🗑️ ลบบอส {boss_name} แล้ว")

# ---------- EDIT BOSS ----------
@bot.tree.command(name="editboss", description="แก้ไขชื่อและเวลาของบอส")
@app_commands.describe(no="หมายเลขบอส", name="ชื่อใหม่", period="เวลาใหม่ (HH:MM)")
async def editboss(interaction: discord.Interaction, no: int, name: str, period: str):
    try:
        datetime.strptime(period, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ รูปแบบเวลาไม่ถูกต้อง (ต้องเป็น HH:MM)", ephemeral=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET name = ?, period = ? WHERE no = ?", (name, period, no))
        await db.commit()
    await interaction.response.send_message(f"✏️ แก้ไขบอสหมายเลข {no} เป็น {name} ({period}) เรียบร้อย")

# ---------- KILLNOW ----------
@bot.tree.command(name="killnow", description="แจ้งเวลาที่บอสตายตอนนี้")
@app_commands.describe(boss_name="ชื่อบอส")
@app_commands.autocomplete(boss_name=boss_name_autocomplete)
async def killnow(interaction: discord.Interaction, boss_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT no, period FROM bosses WHERE name = ?", (boss_name,))
        row = await cursor.fetchone()
    if not row:
        await interaction.response.send_message("❌ ไม่พบบอสชื่อนี้", ephemeral=True)
        return
    no, period_str = row
    period = datetime.strptime(period_str, "%H:%M")
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    next_spawn = now + timedelta(hours=period.hour, minutes=period.minute)
    spawn_str = next_spawn.strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET next_spawn = ? WHERE no = ?", (spawn_str, no))
        await db.commit()
    await interaction.response.send_message(f"✅ บอส {boss_name} จะเกิดอีกครั้งที่ {spawn_str} (เวลาไทย)")

# ---------- KILLAT ----------
@bot.tree.command(name="killat", description="ระบุเวลาที่บอสถูกฆ่า")
@app_commands.describe(boss_name="ชื่อบอส", killed_time="เวลาที่บอสถูกฆ่า (เช่น 13:45)")
@app_commands.autocomplete(boss_name=boss_name_autocomplete)
async def killat(interaction: discord.Interaction, boss_name: str, killed_time: str):
    try:
        killed_time_obj = datetime.strptime(killed_time, "%H:%M").time()
    except ValueError:
        await interaction.response.send_message("❌ เวลาที่ระบุไม่ถูกต้อง ต้องอยู่ในรูปแบบ HH:MM", ephemeral=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT no, period FROM bosses WHERE name = ?", (boss_name,))
        row = await cursor.fetchone()
    if not row:
        await interaction.response.send_message("❌ ไม่พบบอสชื่อนี้", ephemeral=True)
        return
    no, period_str = row
    period = datetime.strptime(period_str, "%H:%M")
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    killed_datetime = datetime.combine(now.date(), killed_time_obj).replace(tzinfo=ZoneInfo("Asia/Bangkok"))
    if (now - killed_datetime).total_seconds() > 3600:
        killed_datetime += timedelta(days=1)
    next_spawn = killed_datetime + timedelta(hours=period.hour, minutes=period.minute)
    spawn_str = next_spawn.strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET next_spawn = ? WHERE no = ?", (spawn_str, no))
        await db.commit()
    await interaction.response.send_message(f"✅ ตั้งเวลาฟื้นครั้งถัดไปของบอส {boss_name} เป็น {spawn_str} (เวลาไทย)")

# ---------- CHECK NOTIFICATIONS ----------
@tasks.loop(seconds=180)
async def check_spawn_notifications():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("❌ ไม่พบช่องสำหรับแจ้งเตือน")
        return
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, locate, next_spawn FROM bosses WHERE next_spawn IS NOT NULL") as cursor:
            rows = await cursor.fetchall()
    for name, locate, next_spawn_str in rows:
        try:
            next_spawn_time = datetime.strptime(next_spawn_str, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Bangkok"))
            diff = (next_spawn_time - now).total_seconds()
            if 0 < diff <= 600:
                await channel.send(f"⏰ ใกล้ถึงเวลาเกิดของ **{name}** (อยู่ {locate}) แล้ว! อีก {int(diff // 60)} นาที")
        except Exception as e:
            print(f"❌ Error parsing spawn time: {e}")


server_on()

# ---------- RUN ----------
async def main():
    await init_db()
    await bot.start(TOKEN)

asyncio.run(main())
