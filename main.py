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
CHANNEL_ID = 1375815326658461736  # <-- เปลี่ยนเป็น channel id ที่จะใช้แจ้งเตือน

# ---------- BOT SETUP ----------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
intents.message_content = True
#bot = commands.Bot(command_prefix="/", intents=intents)

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
                name TEXT NOT NULL,         -- name_en
                name_th TEXT DEFAULT '-',   -- เพิ่มตรงนี้
                period TEXT NOT NULL,
                next_spawn TEXT,
                locate TEXT DEFAULT '-',
                occ TEXT DEFAULT '-'
            )
        """)
        # await db.executemany("""
        #     INSERT INTO bosses (name, locate, period, next_spawn) VALUES (?, ?, ?, ?)
        # """, [
        #     ("เชอร์ทูบา", None, "06:00", "2025-05-31 14:14"),
        #     ("เคลซอส", None, "10:00", None),
        #     ("บาซิลา", None, "04:00", "2025-05-31 09:47"),
        #     ("เฟลิส", None, "03:00", "2025-05-31 09:40"),
        #     ("ทาลาคิน", None, "10:00", "2025-05-31 15:02"),
        #     ("พันดรายด์", None, "12:00", "2025-05-31 09:31"),
        #     ("ซาร์ก้า", None, "10:00", "2025-05-31 09:13"),
        #     ("ทิมิทริส", None, "08:00", "2025-05-31 13:04"),
        #     ("สตัน", None, "07:00", "2025-05-31 12:41"),
        #     ("ครูม่ากลายพัน", None, "08:00", "2025-05-31 11:32"),
        #     ("พันนาโรด", None, "10:00", "2025-05-31 13:19"),
        #     ("เมดูซ่า", None, "10:00", "2025-05-31 14:38"),
        #     ("เบรก้า", None, "06:00", "2025-05-31 14:34"),
        #     ("มาทูรา", None, "06:00", "2025-05-31 12:18"),
        #     ("แบล็คลิลลี่", None, "12:00", "2025-05-31 09:27"),
        #     ("เบฮีมอธ", None, "09:00", "2025-05-31 10:50"),
        #     ("ซาบัน", "มดชั้น2", "12:00", None),
        #     ("ราชินีมด", "มดชั้น3", "06:00", "2025-05-31 09:24"),
        #     ("ครูม่าปนเปื้อน", "ครูม่าชั้น 3", "08:00", "2025-05-31 15:51"),
        #     ("คาทาน", "ครูม่าชั้น 6", "10:00", "2025-05-31 16:57"),
        #     ("คอร์ซัส", "ครูม่าชั้น 7", "10:00", "2025-05-31 15:02"),
        # ])
        await db.commit()

@bot.event
async def on_message(message: discord.Message):
    # อย่าจับข้อความของบอตตัวเอง
    if message.author.bot:
        return

    content = message.content.strip()  # ตัดช่องว่าง/บรรทัดนำท้าย
    if content.lower().startswith("!importbosses"):
        tz = ZoneInfo("Asia/Bangkok")
        lines_raw = content.splitlines()[1:]  # ตัดบรรทัดคำสั่ง
        # กรองบรรทัดว่าง
        lines = [ln for ln in lines_raw if ln.strip()]

        inserted, updated = 0, 0
        current_date = datetime.now(tz).date()
        last_time = None  # เก็บเวลาแถวก่อนหน้า เพื่อตรวจข้ามวัน

        async with aiosqlite.connect(DB_PATH) as db:
            for line in lines:
                parts = [p.strip() for p in line.split(",")]

                # ต้องมีอย่างน้อย 6 คอลัมน์: no, name, locate, ???, next_time, period, [occ]
                if len(parts) < 6:
                    print(f"⚠️ บรรทัดขาดคอลัมน์: {line!r}")
                    continue

                # mapping field (ปรับตามรูปแบบจริงของคุณ)
                # parts: 0=no, 1=name, 2=locate, 3=ignored?, 4=next_time, 5=period, 6=occ(optional)
                name = parts[1]
                name_th = parts[2].strip()
                next_time_str = parts[4]
                period_str = parts[5]
                occ = parts[6] if len(parts) > 6 and parts[6] else "-"

                # parse เวลาฟื้น
                spawn_time_obj = None
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        spawn_time_obj = datetime.strptime(next_time_str, fmt).time()
                        break
                    except ValueError:
                        pass
                if spawn_time_obj is None:
                    print(f"❌ ข้าม {name}: เวลา '{next_time_str}' ไม่ตรงฟอร์แมต")
                    continue

                # ตรรกะข้ามวันตามลำดับไฟล์นำเข้า:
                # แถวแรก = วันนี้, แถวถัดไป ถ้าเวลาน้อยกว่า (หรือเท่ากับ) เวลาแถวก่อนหน้า → +1 วัน
                if last_time is not None and spawn_time_obj <= last_time:
                    current_date += timedelta(days=1)
                last_time = spawn_time_obj

                # รวมวัน+เวลา (ไม่มีวินาทีตามที่ต้องการ)
                spawn_dt = datetime.combine(current_date, spawn_time_obj).replace(tzinfo=tz)
                spawn_str = spawn_dt.strftime("%Y-%m-%d %H:%M")

                # ตรวจว่ามีชื่อใน DB หรือยัง
                cursor = await db.execute("SELECT 1 FROM bosses WHERE name = ?", (name,))
                exists = await cursor.fetchone()

                if exists:
                    await db.execute(
                        "UPDATE bosses SET next_spawn = ?, period = ?, occ = ?, name_th = ? WHERE name = ?",
                        (spawn_str, period_str, occ, name_th, name)
                    )
                    updated += 1
                else:
                    await db.execute(
                        "INSERT INTO bosses (name, name_th, next_spawn, period, occ) VALUES (?, ?, ?, ?, ?)",
                        (name, name_th, spawn_str, period_str, occ)
                    )
                    inserted += 1

            await db.commit()

        await message.channel.send(
            f"✅ เพิ่มใหม่ {inserted} รายการ, อัปเดต {updated} รายการเรียบร้อยแล้ว"
        )

    # สำคัญ: ให้คำสั่งอื่นยังทำงาน
    await bot.process_commands(message)




# ---------- ADD BOSS ----------
@bot.tree.command(name="addboss", description="เพิ่มบอสใหม่")
@app_commands.describe(name="ชื่อบอส", period="ช่วงเวลาเกิดใหม่ (HH:MM)", locate="สถานที่", occ="โอกาสเกิด")
async def addboss(interaction: discord.Interaction, name: str, period: str, locate: str = "-", occ: str = "-"):
    try:
        datetime.strptime(period, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ รูปแบบเวลาไม่ถูกต้อง (ต้องเป็น HH:MM)", ephemeral=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO bosses (name, period, locate, occ) VALUES (?, ?, ?, ?)", (name, period, locate, occ))
        await db.commit()
    await interaction.response.send_message(f"✅ เพิ่มบอส {name} แล้ว")

# ---------- LIST BOSSES ----------
@bot.tree.command(name="listboss", description="แสดงรายชื่อบอสทั้งหมด")
async def listboss(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT no, name, locate, period, next_spawn, occ FROM bosses ORDER BY no ASC") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await interaction.response.send_message("⚠️ ยังไม่มีข้อมูลบอสในระบบ")
        return
    msg = "**📋 รายชื่อบอสทั้งหมด:**\n"
    for no, name, locate, period, next_spawn, occ in rows:
        msg += f"NO.{no}\t {name}\t {locate}\t ({period})\t {next_spawn}\t {occ}\n"
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
@app_commands.describe(no="หมายเลขบอส", name="ชื่อใหม่", period="เวลาใหม่ (HH:MM)", locate="ที่อยู่", occ="โอกาสเกิด")
async def editboss(interaction: discord.Interaction, no: int, name: str, period: str, locate: str, occ: str):
    try:
        datetime.strptime(period, "%H:%M")
    except ValueError:
        await interaction.response.send_message("❌ รูปแบบเวลาไม่ถูกต้อง (ต้องเป็น HH:MM)", ephemeral=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET name = ?, period = ?, locate = ?, occ = ? WHERE no = ?", (name, period, locate, occ, no))
        await db.commit()
    await interaction.response.send_message(f"✏️ แก้ไขบอสหมายเลข {no} เป็น {name} ({period}) อยู่ {locate} โอกาสเกิด {occ} เรียบร้อย")

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
        cursor = await db.execute("SELECT name, next_spawn, occ FROM bosses WHERE next_spawn IS NOT NULL")
        rows = await cursor.fetchall()

    upcoming = []
    past = []

    for name, next_spawn_str, occ in rows:
        try:
            next_spawn = datetime.strptime(next_spawn_str, "%Y-%m-%d %H:%M")
            if next_spawn >= now:
                upcoming.append((next_spawn, name, occ))
            else:
                past.append((next_spawn, name, occ))
        except Exception as e:
            print(f"❌ Error parsing next_spawn for {name}: {e}")

    upcoming.sort()
    past.sort()

    all_bosses = upcoming + past

    if not all_bosses:
        await interaction.followup.send("❌ ยังไม่มีข้อมูลเวลาฟื้นของบอสใดๆ")
        return

    lines = []
    for spawn_time, name, occ in all_bosses:
        diff_min = int((spawn_time - now).total_seconds() // 60)
        if diff_min >= 0:
            lines.append(f"🕒 **{name}** – โอกาส {occ} ฟื้นในอีก {diff_min} นาที ({spawn_time.strftime('%H:%M')})")
        else:
            lines.append(f"⏳ **{name}** – ผ่านแล้วเมื่อ {abs(diff_min)} นาทีที่แล้ว ({spawn_time.strftime('%H:%M')})")

    message = "\n".join(lines)
    await interaction.followup.send(message)

    





# ---------- CHECK NOTIFICATIONS ----------
@tasks.loop(seconds=60)
async def check_spawn_notifications():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("❌ ไม่พบช่องสำหรับแจ้งเตือน")
        return
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, name_th, locate, next_spawn, occ FROM bosses WHERE next_spawn IS NOT NULL") as cursor:
            rows = await cursor.fetchall()
    for name, name_th, locate, next_spawn_str, occ in rows:
        try:
            next_spawn_time = datetime.strptime(next_spawn_str, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Bangkok"))
            diff = (next_spawn_time - now).total_seconds()
            if (240 < diff <= 300) or (0 < diff <= 120):
                now_str = now.strftime("%H:%M")
                await channel.send(f"⏰ {occ} ({now_str}) ใกล้ถึงเวลาเกิดของ **{name_th}({name})** (อยู่ {locate}) แล้ว! อีก {int(diff // 60) + 1} นาที({next_spawn_time.strftime('%H:%M')})")
        except Exception as e:
            print(f"❌ Error parsing spawn time: {e}")


server_on()

# ---------- RUN ----------
async def main():
    await init_db()
    await bot.start(TOKEN)

asyncio.run(main())
