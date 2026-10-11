# Autonomous Kitchen & Meal Planning System

Autonomous, event-driven personal kitchen inventory management, meal planning, and cooking assistant powered by **Discord**, **Google Gemini 3.5 Flash Lite**, and **Grocy MCP**.

---

## Architecture Overview

```
Discord Bot (Channel, DMs, Slash Commands, Photo Hauls)
   │
   ▼
Python 3.15 Daemon (uv, AsyncIO, APScheduler)
   │
   ├─► Google Gemini 3.5 Flash Lite (Structured Planning, Vision OCR, Web Tools)
   ├─► Google Calendar API (Read-only evening conflict detection)
   └─► attmous/grocy-mcp (80+ tools over stdio/HTTP)
         │
         ▼
       Grocy Server (Docker + SQLite: Stock, Recipes, Meal Plans, Chores)
```

For detailed engineering architecture and roadmap specifications, see [ARCHITECTURE.md](file:///home/server/food-tracker/ARCHITECTURE.md).

---

## 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- [Astral `uv`](https://github.com/astral-sh/uv) (for ultra-fast Python 3.15 virtualenv and dependency management)
- Python 3.15+ (managed automatically by `uv`)
- A [Google AI Studio API Key](https://aistudio.google.com/)
- A [Discord Developer Portal](https://discord.com/developers/applications) Bot Account

---

## 2. Environment Configuration (`.env`)

Copy the template to initialize your configuration:
```bash
cp .env.example .env
```

### Configuration Parameters

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `GROCY_URL` | URL of your running Grocy instance | `http://localhost:9283` |
| `GROCY_API_KEY` | API key generated in Grocy | *Required* |
| `GROCY_MCP_TRANSPORT` | MCP communication transport (`stdio` or `http`) | `stdio` |
| `GROCY_MCP_HTTP_URL` | FastMCP endpoint (used only if transport is `http`) | `http://localhost:8000/mcp` |
| `GEMINI_API_KEY` | Google Gemini API key from Google AI Studio | *Required* |
| `GEMINI_MODEL` | Core language and vision model | `gemini-3.5-flash-lite` |
| `GEMINI_MAX_RPM` | Maximum requests per minute for rate limiter | `60` (paid plan) or `15` (free) |
| `GEMINI_MIN_INTERVAL` | Minimum delay in seconds between Gemini API requests | `0.2` (paid) or `2.0` (free) |
| `DISCORD_BOT_TOKEN` | Discord Bot Token from Developer Portal | *Required* |
| `DISCORD_CHANNEL_ID` | Dedicated text channel ID for free chat & scheduled dispatches | `123456789012345678` (optional) |
| `GOOGLE_CALENDAR_CREDENTIALS_PATH` | Path to Google Cloud Service Account JSON key | `credentials.json` |
| `GOOGLE_CALENDAR_ID` | Calendar ID (`primary` or `...group.calendar.google.com`) | `primary` |
| `TIMEZONE` | IANA timezone for cron schedules and reminders | `America/New_York` |

---

## 3. Step-by-Step Setup Guide

### Step 1: Start Grocy & Seed Master Data

1. **Launch Grocy**:
   ```bash
   docker compose up -d grocy
   ```
   Open **http://localhost:9283** in your browser. Default login: `admin` / `admin`.

2. **Generate API Key**:
   - In Grocy's top-right profile menu, select **Manage API Keys**.
   - Click **Add** and copy your generated API key.
   - Paste it into `.env` as `GROCY_API_KEY`.

3. **Seed Locations & Quantity Units**:
   Run the master data initialization script to create standardized storage locations (`Fridge`, `Freezer`, `Pantry`) and units (`Piece`, `Pack`, `Bottle`, `g`, `kg`, `oz`):
   ```bash
   uv run python scripts/init_grocy.py
   ```

4. **Verify Grocy MCP Connectivity**:
   ```bash
   uv run grocy stock overview
   ```

---

### Step 2: Configure Gemini AI

1. Visit [Google AI Studio](https://aistudio.google.com/) and create an API key.
2. Add your key to `.env` as `GEMINI_API_KEY`.
3. If you have a paid billing account (or Gemini AI Pro plan credits), rate limits are configured for high throughput:
   ```ini
   GEMINI_MAX_RPM=60
   GEMINI_MIN_INTERVAL=0.2
   ```

---

### Step 3: Configure Discord Bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Go to the **Bot** tab:
   - Click **Reset Token** and copy your **Bot Token** into `.env` (`DISCORD_BOT_TOKEN`).
   - Under **Privileged Gateway Intents**, turn **ON** **Message Content Intent**.
3. Go to **OAuth2 $\rightarrow$ URL Generator**:
   - Select scopes: `bot` and `applications.commands`.
   - Select permissions:
     - `Send Messages`
     - `Send Messages in Threads` *(Required for threaded conversations)*
     - `Create Public Threads` *(Required to spawn threads for user queries)*
     - `Embed Links`
     - `Attach Files`
     - `Read Message History`
     - `Use Slash Commands`
   - Copy the generated URL and open it to invite the bot to your Discord server as a **Guild App**.
4. (Recommended) Set a dedicated channel:
   - Enable Developer Mode in Discord (*Settings $\rightarrow$ Advanced $\rightarrow$ Developer Mode*).
   - Right-click your kitchen channel and select **Copy Channel ID**.
   - Paste into `.env` as `DISCORD_CHANNEL_ID`.
   > **Note**: In your dedicated channel, the bot responds freely to messages. In other channels or if no channel is set, the bot only responds when `@mentioned` or in direct messages.

### Threaded Conversations & Follow-ups
- **User Queries**: For questions asked in the main channel, the bot automatically spawns a dedicated thread and posts its response inside it.
- **Full Conversation Context**: Replying inside the thread gives Gemini the full prior discussion history across turns.
- **Non-User Queries (Announcements)**: Users can create a thread on any bot announcement (e.g. daily briefing or meal plan) to ask follow-up questions.
- **5-Message Guardrail**: Each thread conversation tracks a 5-message counter (appended as `(x/5)`). Once 5 turns are reached, the bot gracefully informs the user that the thread limit has been reached without calling the LLM, protecting your token budget.

---

### Step 4: Configure Google Calendar (Optional)

The assistant checks evening hours (5:00 PM – 9:00 PM) for calendar events to avoid planning complex meals when you're busy or dining out.

1. **Enable the Google Calendar API**:
   - In the [Google Cloud Console](https://console.cloud.google.com/), select your project.
   - Go to **APIs & Services $\rightarrow$ Library**, search for **Google Calendar API**, and click **Enable**.

2. **Create a Service Account & Download Key**:
   - Go to **APIs & Services $\rightarrow$ Credentials $\rightarrow$ Create Credentials $\rightarrow$ Service Account**.
   - Name it `kitchen-agent` and click **Done**.
   - Click on the created service account $\rightarrow$ **Keys** tab $\rightarrow$ **Add Key $\rightarrow$ Create new key $\rightarrow$ JSON**.
   - Save the downloaded file as `credentials.json` in this repository root.

3. **Share Your Calendar with the Service Account**:
   - Copy the service account's email (e.g. `kitchen-agent@your-project.iam.gserviceaccount.com`).
   - In [Google Calendar](https://calendar.google.com/), click the three dots (`⋮`) next to your calendar $\rightarrow$ **Settings and sharing**.
   - Under **Share with specific people or groups**, add the service account email with permission **See all event details**.

4. **Set Calendar ID in `.env`**:
   - If using your default primary calendar:
     ```ini
     GOOGLE_CALENDAR_ID=your_email@gmail.com
     ```
   - If using a secondary calendar (e.g. *"Shovel"*):
     - Go to that calendar's **Settings and sharing $\rightarrow$ Integrate calendar $\rightarrow$ Calendar ID**.
     - Copy the ID (looks like `c_...group.calendar.google.com`) and paste it:
     ```ini
     GOOGLE_CALENDAR_ID=c_188a9b2c3d4e5f...@group.calendar.google.com
     ```

---

## 4. Running the Assistant

### Option A: Direct Host Execution with `uv` (Recommended for Development)
```bash
# Install dependencies
uv sync --extra dev

# Run the test suite
uv run pytest

# Start the agent daemon
uv run python main.py
```

### Option B: Docker Container Deployment
```bash
# Build and start the bot container
docker compose up -d --build agent

# View live bot logs
docker compose logs -f agent
```

---

## 5. Features & Discord Commands

### Interactive Slash Commands

| Command | Description |
| :--- | :--- |
| `/plan [notes]` | Generates a balanced 7-day meal plan with interactive `[Approve Plan]` and `[Modify Plan]` buttons. |
| `/inventory [query]` | Inspects current Grocy stock overview or searches for products. |
| `/shopping` | Displays the current Grocy shopping list. |
| `/cook [dish]` | Sends tonight's rapid 4-step assembly guide with interactive `[Cooked!]`, `[Eating Out / Skip]`, and `[Swap Dinner]` buttons. Deducts stock on confirmation! |
| `/status` | Tests live health connectivity to Grocy MCP, Gemini AI, and Google Calendar. |
| `/schedules` | Opens the interactive Schedule Control Panel with live indicators (🟢 / 🔴), dropdown selector, and toggle buttons. |
| `/toggle_schedule [routine]` | Quickly toggles an automated routine on or off from the keyboard. |
| `/run_schedule [routine]` | Manually triggers any scheduled routine on demand in the channel for instant testing. |
| `/profile [text]` | Views your current culinary profile and preferences, or updates it if text is provided. |
| `/set_profile <text>` | Directly sets your persistent culinary profile (cuisines, flavors, restrictions, cooking constraints). |

---

### Persistent Culinary Profile & Preferences

The system stores your personalized culinary preferences in `data/user_profile.json` (persisted across restarts):
- **Automatic Context Injection**: The meal planner and conversational sous-chef automatically receive your profile so dishes match your preferred cuisines, flavor profiles, and constraints.
- **Selective Injection**: Agents that don't need it (like the grocery shopping list compiler) do not receive it, keeping prompts lean.
- **Two-Way Editing**:
  - **Conversational**: Tell the bot *"Remember that I love Korean food and spicy stews"* or *"Update my profile: I don't eat shellfish"*, and Gemini will autonomously invoke `user_profile_update_tool`.
  - **Slash Commands**: Use `/profile` to view or `/set_profile <text>` to update directly.
- **Soft Length Guideline**: Recommends keeping profiles under ~1,000 characters (~150 words) for optimal AI prompt efficiency.

---

### Multimodal Vision: Receipts & Countertop Food Photos

Upload any photo to Discord:
1. **Paper Receipts**: Scans item names, prices, and quantities; converts brand abbreviations into clean product names.
2. **Countertop Food Photos**: Lay fresh groceries on a table or kitchen counter and take a photo. Gemini detects all distinct items and estimates counts.
3. The bot presents a rich embed with storage location inferences (`Fridge`, `Freezer`, `Pantry`) and an interactive `[Add All to Grocy]` confirmation button!

---

### Web Recipe Link Importing

Paste any recipe URL from the web (NYT Cooking, Serious Eats, food blogs, etc.) into the channel:
> *"Can you import this recipe? https://www.seriouseats.com/easy-pan-pizza-recipe"*

The bot:
1. Scrapes the page using `Schema.org/Recipe` JSON-LD metadata extraction.
2. Creates the recipe in Grocy with parsed ingredients using `recipe_create_by_name_tool`.
3. Offers an instant button to add any missing ingredients to your shopping list!

---

### Automated Scheduled Routines

The bot runs 5 background cron routines configured in [`app/scheduler/`](file:///home/server/food-tracker/app/scheduler/):

1. **Saturday 2:00 PM (`saturday_plan`)**: Proactively evaluates volatile stock and calendar commitments to propose a 7-day dinner plan.
2. **Sunday 9:00 AM (`sunday_grocery`)**: Compiles an aisle-categorized shopping checklist for missing items and low staples.
3. **Sunday 3:00 PM (`sunday_prep`)**: Dispatches actionable bulk prep tasks (portions, grains, marinades) for <15m weeknight dinners.
4. **Daily 8:00 AM (`daily_morning`)**: Morning briefing with protein thaw alerts and dinner confirmation.
5. **Daily 5:30 PM (`daily_evening`)**: Dinner guide with 4-step instructions and interactive `[Cooked!]` deduction buttons.

**All routines are toggleable via `/schedules`**, and state persists across reboots in `data/schedules_state.json`.

---

## 6. Testing & Quality Assurance

Run the comprehensive test suite with `uv`:
```bash
uv run pytest
```
Run code formatting and linting:
```bash
uv run ruff check
```
