"""
FireHire RS — Discord Bot (Python)
- يراقب Google Sheet كل دقيقة
- يبعت رسالة لما يجي سابميشن جديد
- يبعت رسالة لما يتغير أي فيدباك
- بيشتغل 24/7 على GitHub Actions
"""

import os
import json
import traceback
import asyncio
import gspread
import discord
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

# ═══════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════

DISCORD_TOKEN      = os.environ["DISCORD_TOKEN"]
CHANNEL_ID         = 1511896531786268712
SPREADSHEET_ID     = os.environ["SPREADSHEET_ID"]
SHEET_NAME         = "The Validation"

FEEDBACK_COLS = [
    "Feedback of VN",
    "Feedback of Call",
    "Company Feedback",
]

STATE_FILE = "last_state.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ═══════════════════════════════════════════
#  GOOGLE SHEETS
# ═══════════════════════════════════════════

def get_sheet_data():
    try:
        print("🔍 Step 1: Reading GOOGLE_CREDENTIALS...")
        creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
        if not creds_json:
            raise ValueError("GOOGLE_CREDENTIALS is empty!")
        print(f"🔍 Step 2: Credentials length = {len(creds_json)} chars")

        print("🔍 Step 3: Parsing JSON...")
        creds_dict = json.loads(creds_json)
        print(f"🔍 Step 4: type={creds_dict.get('type')} | email={creds_dict.get('client_email')}")

        print("🔍 Step 5: Creating credentials object...")
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

        print("🔍 Step 6: Authorizing gspread...")
        gc = gspread.authorize(creds)

        print(f"🔍 Step 7: Opening spreadsheet ID={SPREADSHEET_ID}...")
        sh = gc.open_by_key(SPREADSHEET_ID)

        print(f"🔍 Step 8: Opening worksheet '{SHEET_NAME}'...")
        ws = sh.worksheet(SHEET_NAME)

        print("🔍 Step 9: Getting all records...")
        records = ws.get_all_records()
        print(f"✅ Sheet OK — got {len(records)} rows.")
        return records

    except Exception as e:
        print(f"❌ get_sheet_data FAILED at: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        raise

# ═══════════════════════════════════════════
#  STATE MANAGEMENT
# ═══════════════════════════════════════════

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_emails": [], "feedback_states": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_row_key(row):
    email = str(row.get("Email", "")).strip().lower()
    name  = str(row.get("Full Name", "")).strip()
    return email if email else name

def get_feedback_state(row):
    return {col: str(row.get(col, "")).strip() for col in FEEDBACK_COLS}

# ═══════════════════════════════════════════
#  DISCORD EMBEDS
# ═══════════════════════════════════════════

def build_new_submission_embed(row):
    now = datetime.now(timezone.utc).strftime("%m/%d/%Y %I:%M %p")
    embed = discord.Embed(
        title="🔥 New Application Submitted!",
        color=0xFF4B2B,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="👤 Full Name",        value=row.get("Full Name", "N/A")    or "N/A", inline=True)
    embed.add_field(name="🏢 Company",          value=row.get("Company Name you are applying for", "N/A") or "N/A", inline=True)
    embed.add_field(name="\u200B",              value="\u200B", inline=False)
    embed.add_field(name="🎯 Recruiter",        value=row.get("Recruiter Name", "N/A") or "N/A", inline=True)
    embed.add_field(name="👑 Team Leader",      value=str(row.get("Team Leader Name", "") or row.get("TL Name", "") or row.get("Team Leader", "") or "N/A").strip() or "N/A", inline=True)
    embed.add_field(name="\u200B",              value="\u200B", inline=False)
    embed.add_field(name="📞 Phone",            value=str(row.get("Phone", "") or row.get("Mobile", "") or "N/A"), inline=True)
    embed.add_field(name="📧 Email",            value=row.get("Email", "N/A") or "N/A", inline=True)
    embed.add_field(name="\u200B",              value="\u200B", inline=False)
    embed.add_field(name="🌍 Nationality",      value=row.get("Nationality", "N/A") or "N/A", inline=True)
    embed.add_field(name="🎓 Graduation",       value=row.get("Graduation", "N/A") or "N/A", inline=True)
    embed.add_field(name="💼 Experience in CS", value=row.get("Experience In Customer Services/Telesales/CC", "N/A") or "N/A", inline=False)
    vocaroo = row.get("Meeting Link", "") or row.get("Vocaroo", "")
    if vocaroo:
        embed.add_field(name="🎙️ Vocaroo Link", value=vocaroo, inline=False)
    embed.set_footer(text=f"FireHire RS | Form Submission • {now}")
    return embed


def build_feedback_embed(row, col, old_val, new_val):
    name      = row.get("Full Name", "N/A")
    company   = row.get("Company Name you are applying for", "N/A")
    recruiter = row.get("Recruiter Name", "N/A")
    tl        = row.get("Team Leader Name", "N/A")
    now       = datetime.now(timezone.utc).strftime("%m/%d/%Y %I:%M %p")

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
    embed.set_footer(text=f"FireHire RS | Feedback Update • {now}")
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
        channel = self.get_channel(CHANNEL_ID)
        if channel is None:
            print(f"❌ Channel {CHANNEL_ID} not found!")
            return

        try:
            rows = get_sheet_data()
        except Exception as e:
            print(f"❌ Google Sheets error: {type(e).__name__}: {e}")
            return

        state = load_state()
        seen_emails     = set(state.get("seen_emails", []))
        feedback_states = state.get("feedback_states", {})

        new_seen     = set(seen_emails)
        new_feedback = dict(feedback_states)

        for row in rows:
            key = get_row_key(row)
            if not key:
                continue

            if key not in seen_emails:
                print(f"🆕 New submission: {key}")
                embed = build_new_submission_embed(row)
                try:
                    await channel.send(
                        content="📣 **New Application** — Please review and assign!",
                        embed=embed
                    )
                except Exception as e:
                    print(f"❌ Discord send error: {e}")
                new_seen.add(key)

            current_fb = get_feedback_state(row)
            old_fb     = feedback_states.get(key, {})

            for col in FEEDBACK_COLS:
                old_val = old_fb.get(col, "")
                new_val = current_fb.get(col, "")
                if new_val and new_val != old_val:
                    print(f"🔄 Feedback changed [{col}]: {key} → {new_val}")
                    embed = build_feedback_embed(row, col, old_val, new_val)
                    try:
                        await channel.send(
                            content="📣 **New Feedback Update** — Please review and notify the candidate if needed.",
                            embed=embed
                        )
                    except Exception as e:
                        print(f"❌ Discord send error: {e}")

            new_feedback[key] = current_fb

        save_state({
            "seen_emails":     list(new_seen),
            "feedback_states": new_feedback
        })
        print("✅ Check complete.")


def main():
    bot = FireHireBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
