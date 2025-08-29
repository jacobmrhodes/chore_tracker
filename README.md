# 🧹 chore_tracker
Manage your household chores in Home Assistant

---

## ✨ Features
- Create chores directly from the **Home Assistant UI** (no YAML required).
- Each chore is represented as a `switch.chore_*` entity.
- **States**:
  - **ON** → Chore is **Due**  
  - **OFF** → Chore is **Not Due** (recently completed)
- **Attributes include**:
  - `Friendly_Name` – The display name of the chore
  - `Interval` – How often the chore should repeat (e.g., `1 week`, `3 days`, `2 months`)
  - `Assigned_To` – Who is responsible
  - `Room` – Location for context
  - `Last_Completed` – ISO timestamp of when the chore was last marked done
  - `Next_Due` – When the chore is due again
  - `Is Due` – Boolean for easy filtering
- Automatic rearming at the scheduled due date.
- Fully configurable through the UI (Config Flow + Options Flow).

---

## 📦 Installation

### HACS (Recommended)
1. Go to **HACS → Integrations**.
2. Click the **three dots menu** → **Custom repositories**.
3. Add your repo URL and select category **Integration**.
4. Install **Chore Manager**.
5. Restart Home Assistant.

### Manual
1. Copy this repository into:
2. Restart Home Assistant.

---

## ⚙️ Configuration
After installation:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Chore Manager**.
3. Enter the details for your first chore:
- **Friendly Name** → e.g. `"Take out trash"`
- **Interval** → e.g. `"1 week"`, `"2 days"`
- **Assigned To** → e.g. `"Scarlett"`
- **Room** → e.g. `"Kitchen"`
- **Next Due** → Defaults to tomorrow, but can be set manually
4. Click **Submit** → A `switch.chore_take_out_trash` entity will be created.

You can add multiple chores by repeating the process.

---

## 🖥️ Example Usage

### Lovelace Card
```yaml
type: entities
title: 🧹 Chores
entities:
- entity: switch.chore_take_out_trash
- entity: switch.chore_clean_bathroom
