import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import aiohttp
import re
import requests

from myServer import server_on

TOKEN = os.getenv('TOKEN')
DB_PATH = "bosses.db"
CHANNEL_ID = 847486457509576718
API_KEY = "K89378558488957"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

async def ocr_space_file(filepath, api_key=API_KEY, language='tha'):
    url = 'https://api.ocr.space/parse/image'
    with open(filepath, 'rb') as f:
        response = requests.post(
            url,
            files={os.path.basename(filepath): f},
            data={'apikey': api_key, 'language': language},
        )
    result = response.json()
    return result['ParsedResults'][0]['ParsedText'] if 'ParsedResults' in result else None

def parse_ocr_text(ocr_text):
    lines = ocr_text.strip().split("\n")
    boss_data = []
    for line in lines:
        parts = re.split(r'\s{2,}|\t', line.strip())
        if len(parts) >= 6:
            try:
                no = int(parts[0])
                name = parts[1].strip()
                period_raw = parts[3].strip()
                spawn_time_raw = parts[4].strip()
                chance = int(parts[5].replace('%', '').strip())

                period_parts = period_raw.split(":")
                if len(period_parts) >= 2:
                    period = f"{int(period_parts[0]):02}:{int(period_parts[1]):02}"
                else:
                    continue

                spawn_time = f"2025-07-10 {spawn_time_raw[:5]}" if ":" in spawn_time_raw else None

                boss_data.append((name, None, period, spawn_time, chance))
            except:
                pass
    return boss_data

async def save_bosses_to_db(boss_data):
    async with aiosqlite.connect(DB_PATH) as db:
        for row in boss_data:
            name, locate, period, next_spawn, chance = row
            cursor = await db.execute("SELECT no FROM bosses WHERE name = ?", (name,))
            result = await cursor.fetchone()
            if result:
                await db.execute("""
                    UPDATE bosses
                    SET locate = ?, period = ?, next_spawn = ?, chance = ?
                    WHERE name = ?
                """, (locate, period, next_spawn, chance, name))
            else:
                await db.execute("""
                    INSERT INTO bosses (name, locate, period, next_spawn, chance)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, locate, period, next_spawn, chance))
        await db.commit()

async def boss_name_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name FROM bosses WHERE name LIKE ?", (f"%{current}%",))
        names = [row[0] for row in await cursor.fetchall()]
    return [app_commands.Choice(name=name, value=name) for name in names]

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    check_spawn_notifications.start()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bosses (
                no INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                locate TEXT,
                period TEXT NOT NULL,
                next_spawn TEXT,
                chance INTEGER DEFAULT 100
            )
        """)
        await db.commit()

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

@bot.tree.command(name="deleteboss", description="ลบบอส")
@app_commands.describe(boss_name="ชื่อบอสที่จะลบ")
@app_commands.autocomplete(boss_name=boss_name_autocomplete)
async def deleteboss(interaction: discord.Interaction, boss_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bosses WHERE name = ?", (boss_name,))
        await db.commit()
    await interaction.response.send_message(f"🗑️ ลบบอส {boss_name} แล้ว")

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
    killed_datetime = today_killed - timedelta(days=1) if today_killed > now else today_killed
    next_spawn = killed_datetime + timedelta(hours=period.hour, minutes=period.minute)
    spawn_str = next_spawn.strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bosses SET next_spawn = ? WHERE no = ?", (spawn_str, no))
        await db.commit()
    await interaction.response.send_message(f"✅ ตั้งเวลาฟื้นครั้งถัดไปของบอส {boss_name} เป็น {spawn_str} (เวลาไทย)")

@bot.tree.command(name="incoming", description="ดูบอสที่ใกล้จะเกิด เรียงตามลำดับเวลา")
async def incoming(interaction: discord.Interaction):
    await interaction.response.defer()
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name, next_spawn FROM bosses WHERE next_spawn IS NOT NULL")
        rows = await cursor.fetchall()
    upcoming = []
    past = []
    for name, next_spawn_str in rows:
        try:
            next_spawn = datetime.strptime(next_spawn_str, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Bangkok"))
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

@bot.event
async def on_message(message):
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                await message.channel.send("📥 กำลังประมวลผลภาพ OCR...")
                filepath = f"temp_{attachment.filename}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment.url) as resp:
                        with open(filepath, 'wb') as f:
                            f.write(await resp.read())
                ocr_text = await ocr_space_file(filepath)
                if not ocr_text:
                    await message.channel.send("❌ ไม่สามารถดึงข้อความจากภาพได้")
                    return
                boss_data = parse_ocr_text(ocr_text)
                await save_bosses_to_db(boss_data)
                await message.channel.send(f"✅ เพิ่มข้อมูลบอสจากภาพเรียบร้อยแล้ว ({len(boss_data)} ตัว)")
                os.remove(filepath)
    await bot.process_commands(message)

@tasks.loop(seconds=60)
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
            if 0 < diff <= 120:
                await channel.send(f"⏰ ใกล้ถึงเวลาเกิดของ **{name}** (อยู่ {locate}) แล้ว! อีก {int(diff // 60)} นาที")
        except Exception as e:
            print(f"❌ Error parsing spawn time: {e}")

server_on()

async def main():
    await init_db()
    await bot.start(TOKEN)

asyncio.run(main())
