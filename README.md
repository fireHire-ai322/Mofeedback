# 🔥 FireHire RS — Discord Bot

بوت Python بيراقب Google Sheet ويبعت notifications على Discord.

---

## ⚙️ خطوات الإعداد

### 1. عمل Discord Bot

1. افتح [Discord Developer Portal](https://discord.com/developers/applications)
2. اضغط **New Application** → اديه اسم (FireHire RS)
3. روح **Bot** → اضغط **Add Bot**
4. اضغط **Reset Token** → انسخ الـ Token (ده هو `DISCORD_TOKEN`)
5. في **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`
6. افتح الرابط اللي اتعمل وأضف البوت لـ Server بتاعك
7. **مهم:** امسح الـ Webhook القديم من الـ Channel وأضف البوت بدله

---

### 2. عمل Google Service Account

1. روح [Google Cloud Console](https://console.cloud.google.com/)
2. عمل Project جديد أو استخدم موجود
3. فعّل **Google Sheets API** و **Google Drive API**
4. روح **IAM & Admin → Service Accounts** → عمل Service Account جديد
5. من **Keys** → اضغط **Add Key → JSON** → نزّل الملف
6. افتح Google Sheet بتاعك → **Share** → أضف إيميل الـ Service Account بصلاحية **Viewer**

---

### 3. رفع الكود على GitHub

```bash
git init
git add .
git commit -m "initial: FireHire Discord Bot"
git remote add origin https://github.com/YOUR_USERNAME/firehire-bot.git
git push -u origin main
```

---

### 4. إضافة Secrets على GitHub

روح **Settings → Secrets and variables → Actions → New repository secret**:

| Secret Name         | القيمة                                          |
|---------------------|-------------------------------------------------|
| `DISCORD_TOKEN`     | Token البوت من Developer Portal                 |
| `SPREADSHEET_ID`    | الـ ID من رابط الشيت (بين `/d/` و `/edit`)     |
| `GOOGLE_CREDENTIALS`| محتوى ملف الـ JSON كامل (copy & paste)          |

**مثال SPREADSHEET_ID:**
```
https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                       ده هو الـ SPREADSHEET_ID
```

---

### 5. تشغيل يدوي للتجربة

روح **Actions** → اختار **FireHire Discord Bot** → اضغط **Run workflow**

---

## 🔄 إزاي بيشتغل

- GitHub Actions بيشغله كل **5 دقايق** (أقل وقت مسموح)
- داخل كل run، بيشتغل **5 مرات بفارق دقيقة** → فعلياً كل دقيقة
- بيحفظ آخر state في `last_state.json` في الـ repo
- مش بيبعت نفس الرسالة مرتين

## 📋 الـ Notifications

| الحدث                | الرسالة                              |
|----------------------|--------------------------------------|
| سابميشن جديد         | 🔥 New Application Submitted!        |
| VN Feedback اتغير   | 🎙️ Voice Note Stage Update          |
| Call Feedback اتغير | 📞 Call Interview Stage Update       |
| Company Feedback    | 🏢 Company Feedback Stage Update     |
