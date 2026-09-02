"""
FireHire RS — Discord Bot
- يشتغل مرة واحدة، يعمل check، ويقفل
- GitHub Actions بيشغله كل دقيقة (عن طريق 5 checks جوه run واحد كل 5 دقايق)
- الـ state محفوظ في GitHub Actions Cache
"""

import os
import json
import time
import asyncio
import traceback
import gspread
import discord
from google.oauth2.service_account import Credentials
from supabase import create_client
from datetime import datetime, timezone

# ═══════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════

DISCORD_TOKEN  = os.environ["DISCORD_TOKEN"]
CHANNEL_ID     = 1511896531786268712
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME     = "The Validation"

# الفلو الجديد (صفحة Apply) بيكتب مباشرة في Supabase من غير ما يعدي على الشيت،
# فالبوت دلوقتي بيراقب المصدرين مع بعض على نفس القناة.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
sb = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
if not sb:
    print("⚠️ SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping Supabase monitoring, sheet-only mode.")

FEEDBACK_COLS    = [
    "Feedback of VN",
    "Feedback of Call",
    "Company Feedback",
]
FEEDBACK_COLS_SB = ["vn_feedback", "call_feedback", "company_feedback"]

NOTIFY_VALUES = ["accepted", "rejected", "rescheduled", "no show", "not interested", "not clarified"]

STATE_FILE = "last_state.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CHECK_INTERVAL_SECONDS = 60
MAX_RUNTIME_MINUTES = int(os.environ.get("BOT_MAX_RUNTIME_MINUTES", "330"))

# ═══════════════════════════════════════════
#  GOOGLE SHEETS
# ═══════════════════════════════════════════

def get_sheet_data():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS is empty!")

    creds_dict = json.loads(creds_json)
    creds      = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc         = gspread.authorize(creds)
    sh         = gc.open_by_key(SPREADSHEET_ID)
    ws         = sh.worksheet(SHEET_NAME)

    rows = ws.get_all_values()
    if not rows:
        return []

    headers = [h.strip() for h in rows[0]]
    data    = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        row_dict = {}
        for i, val in enumerate(row):
            if i < len(headers):
                key = headers[i] if headers[i] else f"_col_{i}"
                row_dict[key] = val
        data.append(row_dict)

    print(f"✅ Sheet OK — got {len(data)} rows.")
    return data

# ═══════════════════════════════════════════
#  SUPABASE (candidates table — الفلو الجديد اللي بيتخطى الشيت)
# ═══════════════════════════════════════════

def get_supabase_rows():
    if not sb:
        return []
    resp = sb.table("candidates").select("*").order("created_at", desc=False).execute()
    return resp.data or []

def normalize_supabase_row(row):
    """بتحوّل صف candidates (Supabase) لنفس شكل الديكشنري اللي embed builders
    اتصممت عليه أصلاً على شيت الـ Google (نفس أسماء المفاتيح بالظبط)،
    مع الاحتفاظ بالـ id وأعمدة الفيدباك الأصلية جوه نفس الديكت."""
    return {
        "Full Name": row.get("name", ""),
        "Company Name you are applying for": row.get("company", ""),
        "Recruiter Name": row.get("recruiter_name", ""),
        "Team Leader Name ": row.get("team_leader", ""),
        "Phone Number": row.get("phone", ""),
        "Email": row.get("email", ""),
        "Nationality": row.get("nationality", ""),
        "Graduation": row.get("graduation", ""),
        "Experience In Customer Services/Telesales/CC": row.get("cc_experience", ""),
        "Meeting Link": row.get("vocaroo_link", ""),
        "CV Link": row.get("cv_link", ""),
        "_id": row.get("id"),
        "vn_feedback": row.get("vn_feedback", ""),
        "call_feedback": row.get("call_feedback", ""),
        "company_feedback": row.get("company_feedback", ""),
    }

def get_row_key_sb(row):
    return f"sb:{row.get('_id')}" if row.get("_id") is not None else ""

# ═══════════════════════════════════════════
#  STATE MANAGEMENT
# ═══════════════════════════════════════════

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = {}

    # توافق مع الشكل القديم (فلات، شيت بس) — لو لسه موجود، بيتحط تحت "sheet"
    # وقسم "supabase" بيبدأ فاضي (يعني first-run seed هيحصل له لوحده من غير
    # ما يعيد إشعار أي حاجة من الشيت القديمة).
    if "sheet" not in raw and "supabase" not in raw:
        raw = {
            "sheet":    {"notified_rows": raw.get("notified_rows", []), "feedback_states": raw.get("feedback_states", {})},
            "supabase": {"notified_rows": [],                            "feedback_states": {}},
        }
    raw.setdefault("sheet",    {"notified_rows": [], "feedback_states": {}})
    raw.setdefault("supabase", {"notified_rows": [], "feedback_states": {}})
    return raw

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_row_key(row):
    timestamp = str(row.get("Timestamp", "")).strip()
    email     = str(row.get("Email", "")).strip().lower()
    name      = str(row.get("Full Name", "")).strip().lower()
    phone     = str(row.get("Phone Number", "") or row.get("Phone", "")).strip()

    if timestamp:
        return f"ts:{timestamp}"
    if email:
        return f"email:{email}"
    return f"name_phone:{name}|{phone}"

def get_feedback_state(row):
    return {col: str(row.get(col, "")).strip() for col in FEEDBACK_COLS}

def get_feedback_state_sb(row):
    return {col: str(row.get(col) or "").strip() for col in FEEDBACK_COLS_SB}

def is_notifiable_feedback(value):
    v = value.lower().strip()
    if not v:
        return False
    if v.startswith("done"):
        return False
    return any(nv in v for nv in NOTIFY_VALUES)

# ═══════════════════════════════════════════
#  DISCORD EMBEDS
# ═══════════════════════════════════════════

def build_new_submission_embed(row):
    embed = discord.Embed(
        title="🔥 New Application Submitted!",
        color=0xFF4B2B,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="👤 Full Name",        value=row.get("Full Name", "N/A") or "N/A", inline=True)
    embed.add_field(name="🏢 Company",          value=row.get("Company Name you are applying for", "N/A") or "N/A", inline=True)
    embed.add_field(name="\u200B",              value="\u200B", inline=False)
    embed.add_field(name="🎯 Recruiter",        value=row.get("Recruiter Name", "N/A") or "N/A", inline=True)
    embed.add_field(name="👑 Team Leader",      value=str(row.get("Team Leader Name ", "") or row.get("Team Leader Name", "") or "N/A").strip() or "N/A", inline=True)
    embed.add_field(name="\u200B",              value="\u200B", inline=False)
    embed.add_field(name="📞 Phone",            value=str(row.get("Phone Number", "") or row.get("Phone", "") or "N/A"), inline=True)
    embed.add_field(name="📧 Email",            value=row.get("Email", "N/A") or "N/A", inline=True)
    embed.add_field(name="\u200B",              value="\u200B", inline=False)
    embed.add_field(name="🌍 Nationality",      value=row.get("Nationality", "N/A") or "N/A", inline=True)
    embed.add_field(name="🎓 Graduation",       value=row.get("Graduation", "N/A") or "N/A", inline=True)
    embed.add_field(name="💼 Experience in CS", value=row.get("Experience In Customer Services/Telesales/CC", "N/A") or "N/A", inline=False)
    vocaroo = row.get("Vocaroo Link \nNotice : on this link https://vocaroo.com , rec or Upload your Voice Note , and put here your Vocaroo Link To validate it", "") or row.get("Meeting Link", "")
    if vocaroo:
        embed.add_field(name="🎙️ Vocaroo Link", value=vocaroo, inline=False)
    cv = row.get("CV Link", "")
    if cv:
        embed.add_field(name="📄 CV", value=cv, inline=False)
    embed.set_footer(text="FireHire RS | Form Submission")
    return embed


def build_feedback_embed(row, col, new_val):
    name      = row.get("Full Name", "N/A")
    company   = row.get("Company Name you are applying for", "N/A")
    recruiter = row.get("Recruiter Name", "N/A")
    tl        = str(row.get("Team Leader Name ", "") or row.get("Team Leader Name", "") or "N/A").strip() or "N/A"

    val_lower = new_val.lower()
    if "accepted" in val_lower:
        color, emoji, label = 0x22C55E, "✅", "Accepted"
    elif "rejected" in val_lower:
        color, emoji, label = 0xEF4444, "❌", "Rejected"
    elif "rescheduled" in val_lower:
        color, emoji, label = 0xF59E0B, "📅", "Rescheduled"
    elif "no show" in val_lower:
        color, emoji, label = 0x94A3B8, "👻", "No Show"
    elif "not interested" in val_lower:
        color, emoji, label = 0x64748B, "🚪", "Not Interested"
    elif "not clarified" in val_lower:
        color, emoji, label = 0xF97316, "🎤", "Not Clarified"
    else:
        color, emoji, label = 0x2563EB, "🔔", new_val

    if "vn" in col.lower():
        stage = "🎙️ Voice Note Stage"
    elif "call" in col.lower():
        stage = "📞 Call Interview Stage"
    elif "company" in col.lower():
        stage = "🏢 Company Feedback Stage"
    else:
        stage = col

    embed = discord.Embed(
        title=f"{emoji} Feedback Update — {stage}",
        description="A candidate's status has been updated in the sheet.",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="👤 Candidate",   value=name      or "N/A", inline=True)
    embed.add_field(name="🏢 Company",     value=company   or "N/A", inline=True)
    embed.add_field(name="\u200B",         value="\u200B",            inline=False)
    embed.add_field(name="🎯 Recruiter",   value=recruiter or "N/A", inline=True)
    embed.add_field(name="👑 Team Leader", value=tl        or "N/A", inline=True)
    embed.add_field(name="\u200B",         value="\u200B",            inline=False)
    embed.add_field(name="📊 Stage",       value=stage,               inline=True)
    embed.add_field(name="🏁 Result",      value=f"**{label}**",      inline=True)
    embed.set_footer(text="FireHire RS | Feedback Update")
    return embed

# ═══════════════════════════════════════════
#  MAIN BOT
# ═══════════════════════════════════════════

class FireHireBot(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self._start_time = time.monotonic()

    async def on_ready(self):
        print(f"✅ FireHire Bot online as {self.user}")
        await self.monitor_loop()

    async def monitor_loop(self):
        print(f"⏰ Monitor loop started — interval={CHECK_INTERVAL_SECONDS}s | max runtime={MAX_RUNTIME_MINUTES}min")

        while True:
            elapsed_min = (time.monotonic() - self._start_time) / 60
            if elapsed_min >= MAX_RUNTIME_MINUTES:
                print(f"⏳ Max runtime ({MAX_RUNTIME_MINUTES}min) reached. Closing gracefully...")
                await self.close()
                return

            print(f"🔍 Running check... (elapsed: {elapsed_min:.1f}min)")
            await self.run_check()
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def run_check(self):
        try:
            channel = await self.fetch_channel(CHANNEL_ID)
        except Exception as e:
            print(f"❌ Channel not found: {e}")
            return

        state = load_state()

        # ── مصدر 1: Google Sheet (الفلو القديم) ──
        try:
            rows = get_sheet_data()
            state["sheet"] = await self.process_source(
                channel, rows, state["sheet"],
                key_fn=get_row_key,
                fb_fn=get_feedback_state,
                fb_cols=FEEDBACK_COLS,
                new_row_valid_fn=lambda row: (row.get("Full Name", "").strip() or row.get("Email", "").strip()),
                source_label="Sheet",
            )
        except Exception as e:
            print(f"❌ Google Sheets error: {e}")
            print(traceback.format_exc())

        # ── مصدر 2: Supabase candidates (فلو Apply الجديد) ──
        if sb:
            try:
                sb_rows = get_supabase_rows()
                normalized = [normalize_supabase_row(r) for r in sb_rows]
                state["supabase"] = await self.process_source(
                    channel, normalized, state["supabase"],
                    key_fn=get_row_key_sb,
                    fb_fn=get_feedback_state_sb,
                    fb_cols=FEEDBACK_COLS_SB,
                    new_row_valid_fn=lambda row: (row.get("Full Name", "").strip() or row.get("Email", "").strip()),
                    source_label="Supabase",
                )
            except Exception as e:
                print(f"❌ Supabase error: {e}")
                print(traceback.format_exc())

        save_state(state)
        print("✅ Check complete.")

    async def process_source(self, channel, rows, source_state, key_fn, fb_fn, fb_cols, new_row_valid_fn, source_label):
        notified_rows   = set(source_state.get("notified_rows", []))
        feedback_states = source_state.get("feedback_states", {})
        new_notified    = set(notified_rows)
        new_feedback    = dict(feedback_states)

        # ── First Run لهذا المصدر بس: لو الـ state فاضي، seed بدون notifications ──
        is_first_run = len(notified_rows) == 0 and len(feedback_states) == 0
        if is_first_run:
            print(f"🚀 [{source_label}] First run — seeding {len(rows)} rows silently.")
            for row in rows:
                key = key_fn(row)
                if not key:
                    continue
                new_notified.add(key)
                new_feedback[key] = fb_fn(row)
            print(f"✅ [{source_label}] Seeded. Next check will notify new rows only.")
            return {"notified_rows": list(new_notified), "feedback_states": new_feedback}

        for row in rows:
            key = key_fn(row)
            if not key:
                continue

            # ── 1) صف جديد بالكامل لم يُشعَر به قبل ──
            if key not in notified_rows:
                if new_row_valid_fn(row):
                    print(f"🆕 [{source_label}] New row: {key}")
                    embed = build_new_submission_embed(row)
                    try:
                        await channel.send(
                            content="📣 **New Application** — Please review and assign!",
                            embed=embed
                        )
                    except Exception as e:
                        print(f"❌ Discord send error: {e}")
                    new_notified.add(key)

            # ── 2) فيدباك جديد يستحق إشعار ──
            current_fb = fb_fn(row)
            old_fb     = feedback_states.get(key, {})

            for col in fb_cols:
                old_val = old_fb.get(col, "")
                new_val = current_fb.get(col, "")

                if new_val != old_val and is_notifiable_feedback(new_val):
                    print(f"🔄 [{source_label}] Feedback changed [{col}]: row {key} → {new_val}")
                    embed = build_feedback_embed(row, col, new_val)
                    try:
                        await channel.send(
                            content="📣 **New Feedback Update** — Please review and notify the candidate if needed.",
                            embed=embed
                        )
                    except Exception as e:
                        print(f"❌ Discord send error: {e}")

            new_feedback[key] = current_fb

        print(f"✅ [{source_label}] {len(rows)} rows processed.")
        return {"notified_rows": list(new_notified), "feedback_states": new_feedback}


def main():
    bot = FireHireBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
