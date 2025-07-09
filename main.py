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
CHANNEL_ID = 847486457509576718  # <-- เปลี่ยนเป็น channel id ที่จะใช้แจ้งเตือน

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
            INSERT INTO bosses (name, locate, period, next_spawn) VALUES (?, ?, ?, ?)
        """, [
            ("เชอร์ทูบา", None, "06:00", "2025-05-31 14:14"),
            ("เคลซอส", None, "10:00", None),
            ("บาซิลา", None, "04:00", "2025-05-31 09:47"),
            ("เฟลิส", None, "03:00", "2025-05-31 09:40"),
            ("ทาลาคิน", None, "10:00", "2025-05-31 15:02"),
            ("พันดรายด์", None, "12:00", "2025-05-31 09:31"),
            ("ซาร์ก้า", None, "10:00", "2025-05-31 09:13"),
            ("ทิมิทริส", None, "08:00", "2025-05-31 13:04"),
            ("สตัน", None, "07:00", "2025-05-31 12:41"),
            ("ครูม่ากลายพัน", None, "08:00", "2025-05-31 11:32"),
            ("พันนาโรด", None, "10:00", "2025-05-31 13:19"),
            ("เมดูซ่า", None, "10:00", "2025-05-31 14:38"),
            ("เบรก้า", None, "06:00", "2025-05-31 14:34"),
            ("มาทูรา", None, "06:00", "2025-05-31 12:18"),
            ("แบล็คลิลลี่", None, "12:00", "2025-05-31 09:27"),
            ("เบฮีมอธ", None, "09:00", "2025-05-31 10:50"),
            ("ซาบัน", "มดชั้น2", "12:00", None),
            ("ราชินีมด", "มดชั้น3", "06:00", "2025-05-31 09:24"),
            ("ครูม่าปนเปื้อน", "ครูม่าชั้น 3", "08:00", "2025-05-31 15:51"),
            ("คาทาน", "ครูม่าชั้น 6", "10:00", "2025-05-31 16:57"),
            ("คอร์ซัส", "ครูม่าชั้น 7", "10:00", "2025-05-31 15:02"),
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
    today_killed = datetime.combine(now.date(), killed_time_obj).replace(tzinfo=ZoneInfo("Asia/Bangkok"))

    if(today_killed > now):
        killed_datetime = today_killed - timedelta(days=1)
    else:
        killed_datetime = today_killed
    
    #if (now - killed_datetime).total_seconds() > 3600:
    #    killed_datetime += timedelta(days=1)
    print(killed_datetime)
    next_spawn = killed_datetime + timedelta(hours=period.hour, minutes=period.minute)
    spawn_str = next_spawn.strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET next_spawn = ? WHERE no = ?", (spawn_str, no))
        await db.commit()
    await interaction.response.send_message(f"✅ ตั้งเวลาฟื้นครั้งถัดไปของบอส {boss_name} เป็น {spawn_str} (เวลาไทย)")



# ---------- Incoming ----------
@bot.tree.command(name="incoming", description="ดูบอสที่ใกล้จะเกิด เรียงตามลำดับเวลา")
async def incoming(interaction: discord.Interaction):
    await interaction.response.defer()  # เผื่อโหลดข้อมูลนาน
    now = datetime.now() + timedelta(hours=7)  # ปรับเวลาประเทศไทย

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name, next_spawn FROM bosses WHERE next_spawn IS NOT NULL")
        rows = await cursor.fetchall()

    upcoming = []
    past = []

    for name, next_spawn_str in rows:
        try:
            next_spawn = datetime.strptime(next_spawn_str, "%Y-%m-%d %H:%M")
            if next_spawn >= now:
                upcoming.append((next_spawn, name))
            else:
                past.append((next_spawn, name))
        except Exception as e:
            print(f"❌ Error parsing next_spawn for {name}: {e}")

    upcoming.sort()
    past.sort()

    all_bosses = upcoming + past

    if not all_bosses:
        await interaction.followup.send("❌ ยังไม่มีข้อมูลเวลาฟื้นของบอสใดๆ")
        return

    lines = []
    for spawn_time, name in all_bosses:
        diff_min = int((spawn_time - now).total_seconds() // 60)
        if diff_min >= 0:
            lines.append(f"🕒 **{name}** – ฟื้นในอีก {diff_min} นาที ({spawn_time.strftime('%H:%M')})")
        else:
            lines.append(f"⏳ **{name}** – เกิดแล้วเมื่อ {abs(diff_min)} นาทีที่แล้ว ({spawn_time.strftime('%H:%M')})")

    message = "\n".join(lines)
    await interaction.followup.send(message)



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
            if 0 < diff <= 720:
                await channel.send(f"⏰ ใกล้ถึงเวลาเกิดของ **{name}** (อยู่ {locate}) แล้ว! อีก {int(diff // 60)} นาที")
        except Exception as e:
            print(f"❌ Error parsing spawn time: {e}")


server_on()

# ---------- RUN ----------
async def main():
    await init_db()
    await bot.start(TOKEN)

asyncio.run(main())
