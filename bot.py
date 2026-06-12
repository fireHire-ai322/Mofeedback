"""
FireHire RS — Discord Bot
- يشتغل مرة واحدة، يعمل check، ويقفل
- GitHub Actions بيشغله كل دقيقة (عن طريق 5 checks جوه run واحد كل 5 دقايق)
- الـ state محفوظ في GitHub Actions Cache
"""

import os
import json
import traceback
import gspread
import discord
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

# ═══════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════

DISCORD_TOKEN  = os.environ["DISCORD_TOKEN"]
CHANNEL_ID     = 1511896531786268712
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME     = "The Validation"

FEEDBACK_COLS = [
    "Feedback of VN",
    "Feedback of Call",
    "Company Feedback",
]

# القيم اللي تستحق إشعار فيدباك (الحالة الخام في الشيت لسه ماحصلهاش "done")
NOTIFY_VALUES = ["accepted", "rejected", "rescheduled", "no show", "not interested", "not clarified"]

STATE_FILE = "last_state.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

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
#  STATE MANAGEMENT
# ═══════════════════════════════════════════

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notified_rows": [], "feedback_states": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_row_key(row):
    """مفتاح فريد للصف بناءً على المحتوى — بيفضل ثابت حتى لو الصف اتنقل أو الإيميل اتكرر"""
    timestamp = str(row.get("Timestamp", "")).strip()
    email     = str(row.get("Email", "")).strip().lower()
    name      = str(row.get("Full Name", "")).strip().lower()
    phone     = str(row.get("Phone Number", "") or row.get("Phone", "")).strip()

    if timestamp:
        # التايمستامب وحده مميز بما يكفي لكل سابميشن (كل سابميشن وقته مختلف)
        return f"ts:{timestamp}"
    if email:
        return f"email:{email}"
    return f"name_phone:{name}|{phone}"

def get_feedback_state(row):
    return {col: str(row.get(col, "")).strip() for col in FEEDBACK_COLS}

def is_notifiable_feedback(value):
    """القيمة دي تستحق إشعار؟ (accepted/rejected/... بدون done)"""
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

    if "VN" in col or "vn" in col.lower():
        stage = "🎙️ Voice Note Stage"
    elif "Call" in col:
        stage = "📞 Call Interview Stage"
    elif "Company" in col:
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

    async def on_ready(self):
        print(f"✅ FireHire Bot online as {self.user}")
        await self.run_check()
        await self.close()

    async def run_check(self):
        try:
            channel = await self.fetch_channel(CHANNEL_ID)
        except Exception as e:
            print(f"❌ Channel not found: {e}")
            return

        try:
            rows = get_sheet_data()
        except Exception as e:
            print(f"❌ Google Sheets error: {e}")
            print(traceback.format_exc())
            return

        state           = load_state()
        notified_rows   = set(state.get("notified_rows", []))
        feedback_states = state.get("feedback_states", {})
        new_notified    = set(notified_rows)
        new_feedback    = dict(feedback_states)

        for row in rows:
            key = get_row_key(row)
            if not key:
                continue

            # ── 1) صف جديد بالكامل لم يُشعَر به قبل ──
            if key not in notified_rows:
                # نتأكد إن الصف فيه بيانات أساسية (مش صف فاضي اتقرا غلط)
                if (row.get("Full Name", "").strip() or row.get("Email", "").strip()):
                    print(f"🆕 New row: {key}")
                    embed = build_new_submission_embed(row)
                    try:
                        await channel.send(
                            content="📣 **New Application** — Please review and assign!",
                            embed=embed
                        )
                    except Exception as e:
                        print(f"❌ Discord send error: {e}")
                    new_notified.add(key)

            # ── 2) فيدباك جديد يستحق إشعار (accepted/rejected/... بدون done) ──
            current_fb = get_feedback_state(row)
            old_fb     = feedback_states.get(key, {})

            for col in FEEDBACK_COLS:
                old_val = old_fb.get(col, "")
                new_val = current_fb.get(col, "")

                if new_val != old_val and is_notifiable_feedback(new_val):
                    print(f"🔄 Feedback changed [{col}]: row {key} → {new_val}")
                    embed = build_feedback_embed(row, col, new_val)
                    try:
                        await channel.send(
                            content="📣 **New Feedback Update** — Please review and notify the candidate if needed.",
                            embed=embed
                        )
                    except Exception as e:
                        print(f"❌ Discord send error: {e}")

            new_feedback[key] = current_fb

        save_state({
            "notified_rows":   list(new_notified),
            "feedback_states": new_feedback
        })
        print(f"✅ Check complete — {len(rows)} rows processed.")


def main():
    bot = FireHireBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
