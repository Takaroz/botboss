
import os
import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import asyncio
from datetime import datetime, timedelta, time as dtime

from myServer import server_on

DB_PATH = "bosses.db"
CHANNEL_ID = 1377663275650515094  # แก้เป็น channel id ที่จะแจ้งเตือน

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# -------- Database Initialization --------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bosses (
                no INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                period TEXT NOT NULL,
                locate TEXT NOT NULL,
                next_spawn TEXT
            );
        """)
        await db.commit()

# -------- Autocomplete for Boss Name --------
async def boss_name_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name FROM bosses WHERE name LIKE ? LIMIT 25", (f"%{current}%",))
        rows = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in rows]

# -------- Commands --------
@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    print(f"✅ Bot is ready as {bot.user}")
    bot.loop.create_task(check_spawn_notifications())

@bot.tree.command(name="addboss", description="เพิ่มบอสใหม่")
@app_commands.describe(name="ชื่อบอส", locate="ที่อยู่", period="เวลาเกิดซ้ำ (HH:MM)")
async def addboss(interaction: discord.Interaction, name: str, locate:str, period: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO bosses (name, locate, period) VALUES (?, ?, ?)", (name, locate, period))
        await db.commit()
    await interaction.response.send_message(f"✅ เพิ่มบอส '{name}'  อยู่  {locate} พร้อมช่วงเวลา {period}")

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

@bot.tree.command(name="deleteboss", description="ลบบอสตามหมายเลข")
@app_commands.describe(no="หมายเลขบอส")
async def deleteboss(interaction: discord.Interaction, no: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM bosses WHERE no = ?", (no,))
        row = await cursor.fetchone()
        if not row:
            await interaction.response.send_message(f"❌ ไม่พบบอสหมายเลข {no}", ephemeral=True)
            return
        await db.execute("DELETE FROM bosses WHERE no = ?", (no,))
        await db.commit()
    await interaction.response.send_message(f"🗑️ ลบบอสหมายเลข {no} เรียบร้อยแล้ว")

@bot.tree.command(name="editboss", description="แก้ไขชื่อและเวลาของบอส")
@app_commands.describe(no="หมายเลขบอส", name="ชื่อใหม่", period="เวลาใหม่ (HH:MM)")
async def editboss(interaction: discord.Interaction, no: int, name: str, period: str):
    try:
        datetime.strptime(period, "%H:%M")  # ตรวจสอบรูปแบบก่อน
    except ValueError:
        await interaction.response.send_message("❌ รูปแบบเวลาไม่ถูกต้อง ต้องเป็น HH:MM", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET name = ?, period = ? WHERE no = ?", (name, period, no))
        await db.commit()
    await interaction.response.send_message(f"✏️ แก้ไขบอสหมายเลข {no} เป็น {name} ({period}) เรียบร้อย")


@bot.tree.command(name="killnow", description="แจ้งว่าบอสถูกฆ่าตอนนี้")
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
    now = datetime.now()
    next_spawn = now + timedelta(hours=period.hour, minutes=period.minute)
    spawn_str = next_spawn.strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET next_spawn = ? WHERE no = ?", (spawn_str, no))
        await db.commit()
    await interaction.response.send_message(f"✅ บอส {boss_name} จะฟื้นอีกครั้งที่ {spawn_str}")

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
    now = datetime.now()

    killed_datetime = datetime.combine(now.date(), killed_time_obj)

    # แก้ปัญหาเวลาเกินวันเมื่อไม่ควร
    if (now - killed_datetime).total_seconds() > 3600:
        killed_datetime += timedelta(days=1)

    next_spawn = killed_datetime + timedelta(hours=period.hour, minutes=period.minute)
    spawn_str = next_spawn.strftime("%Y-%m-%d %H:%M")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET next_spawn = ? WHERE no = ?", (spawn_str, no))
        await db.commit()

    await interaction.response.send_message(
        f"✅ ตั้งเวลาฟื้นครั้งถัดไปของบอส {boss_name} เป็น {spawn_str}"
    )



# -------- Background Notification Task --------
async def check_spawn_notifications():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    while not bot.is_closed():
        now = datetime.now()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT no, name, locate, next_spawn FROM bosses WHERE next_spawn IS NOT NULL") as cursor:
                rows = await cursor.fetchall()
        for no, name, locate, next_spawn_str in rows:
            try:
                next_spawn_time = datetime.strptime(next_spawn_str, "%Y-%m-%d %H:%M")
                diff = (next_spawn_time - now).total_seconds()
                if 0 < diff <= 720:  # ภายใน 10 นาที
                    await channel.send(f"⏰ ใกล้ถึงเวลาเกิดของ **{name}** อยู่  {locate} แล้ว! อีก {int(diff // 60)} นาที")
            except Exception as e:
                print(f"Error parsing spawn time: {e}")
        await asyncio.sleep(180)

server_on()

bot.run(os.getenv('TOKEN'))
