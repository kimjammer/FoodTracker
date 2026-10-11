# **Autonomous Kitchen & Meal Planning System**

# **Architecture & Implementation Handoff Specification**

# **1\. Executive Summary & Objective**

This specification document serves as the formal engineering handoff for an autonomous, event-driven personal meal planning and kitchen inventory management system. The primary goal of the system is to completely remove the daily cognitive burden associated with meal planning, grocery list compilation, inventory management, and cooking execution.

## **Operational Loops**

* **Weekly Autonomous Loop**: Proactively generates a tailored 7-day meal plan every Saturday afternoon, manages user revision dialogues via natural language, compiles a consolidated, aisle-categorized grocery list on Sunday morning, ingests receipts multimodally via computer vision, and outputs actionable bulk component prep tasks.  
* **Daily Autonomous Loop**: Delivers an early morning briefing identifying prerequisite tasks (e.g., thawing frozen proteins) and an evening execution dispatch containing quick assembly instructions with interactive state buttons that execute atomic inventory deductions.  
* **Core Engine Architecture**: Built around Google Gemini 3.5 Flash Lite (utilizing the Google AI Studio API key context) orchestration interacting with a self-hosted [Grocy](https://grocy.info/) instance via the `attmous/grocy-mcp` Model Context Protocol (MCP) server, managed by an async Python daemon linked to a Discord bot interface.

# **2\. Platform Handoff Choice: Antigravity vs. AI Studio**

To ensure smooth execution during system construction, the deployment workflow distinguishes between the developer environment setup and the target implementation platform.

| Dimension | Google AI Studio | Google Antigravity |
| :---- | :---- | :---- |
| **Primary Function** | API Key Provisioning & Model Prototyping | Autonomous Agentic Software Engineering |
| **Operational Role** | Manual prompt evaluation, model parameter tuning, system instruction experimentation, and API credential management. | End-to-end repository creation, multi-file code editing, Docker orchestration, tool construction, and automated test execution. |
| **Handoff Workflow** | Provision free Gemini API key; evaluate system prompts in playground. | Ingest this specification document as context to generate, test, and deploy the codebase autonomously. |

# **3\. System Architecture & Tech Stack**

## **3.1 Technology Stack Specification**

* **Data & Domain Store**: [Grocy](https://grocy.info/) v4.4+ running as a self-hosted containerized Docker service backed by an isolated SQLite engine.  
* **Orchestration Daemon**: Python 3.11+ async runtime utilizing `discord.py` (v2.4+), `pydantic` v2 for configuration and schema modeling, and `APScheduler` (`AsyncIOScheduler`) for cron jobs.  
* **AI Engine & Multimodal Processing**: Google Gemini API via the modern `google-genai` SDK using `gemini-3.5-flash-lite` for high-throughput, low-latency structured tool calling and image inspection.  
* **Domain Integration Layer**: Model Context Protocol (MCP) client connecting to the [`attmous/grocy-mcp`](https://github.com/attmous/grocy-mcp) server, providing 80+ high-level Grocy tools with human-friendly entity resolution for stock, shopping lists, meal plans, and recipes.  
* **External Context Services**: Google Calendar API (v3) using service-account or OAuth2 read-only access to evaluate evening availability.

## **3.2 High-Level System Architecture**

+--------------------------------------------------------------------------+
|                               Discord Bot                                |
|        (Channel Messages, Interactive Views/Buttons, Receipt Photos)    |
+------------------------------------+-------------------------------------+
                                     |
                                     v
+------------------------------------+-------------------------------------+
|                     Python Agent Daemon (AsyncIO)                        |
|                                                                          |
|  +------------------------+  +-------------------+  +-----------------+  |
|  |       APScheduler      |  | Gemini 3.5 Flash  |  | Google Calendar |  |
|  | (Sat Plan, Sun Grocery,|  | Lite Engine       |  | Client (v3)     |  |
|  |  Daily 8AM & 5:30PM)   |  | (Tools + Vision)  |  | (Evening Events)|  |
|  +-----------+------------+  +--------+----------+  +--------+--------+  |
|              |                        |                      |           |
|              +------------------------+----------------------+           |
|                                       |                                  |
|                                       v                                  |
|                          [Grocy MCP Client Bridge]                       |
+---------------------------------------+----------------------------------+
                                        | MCP Protocol (stdio / SSE)
                                        v
+---------------------------------------+----------------------------------+
|                      attmous/grocy-mcp Server                            |
|             (Translates MCP Tool Invocations to Grocy REST)              |
+---------------------------------------+----------------------------------+
                                        | HTTP REST (API Key)
                                        v
+---------------------------------------+----------------------------------+
|                          Grocy Server (Docker)                           |
|      (SQLite: Stock, Batches, Locations, Recipes, Meal Plan Calendar)    |
+--------------------------------------------------------------------------+

# **4\. Repository & Directory Structure**

kitchen-agent/
├── docker-compose.yml              # Grocy container + Grocy MCP server + Agent Daemon container
├── Dockerfile                      # Multistage uv container image for Python 3.15 runtime
├── README.md                       # Comprehensive setup guide, API keys, and deployment instructions
├── ARCHITECTURE.md                 # System architecture specification and milestone roadmap
├── pyproject.toml                  # Python 3.15 dependencies & tooling pinned with uv
├── .env.example                    # Template for secrets and environment variables
├── config.py                       # Pydantic Settings (Discord, Gemini, Grocy MCP, Calendar, Timezone)
├── main.py                         # Application entrypoint & graceful signal handling
├── app/
│   ├── bot/
│   │   ├── client.py               # KitchenBot client, event listeners & slash commands
│   │   ├── handlers.py             # Message routing, photo inspection, and user dialogues
│   │   ├── views.py                # Discord UI components (MealPlanApprovalView, DailyCookView, ReceiptConfirmationView)
│   │   └── schedule_views.py       # Interactive ScheduleManagementView & schedule status embed
│   ├── scheduler/
│   │   ├── jobs.py                 # Scheduled routines (Sat plan, Sun grocery/prep, Daily morning/evening)
│   │   ├── scheduler_service.py    # APScheduler lifecycle management
│   │   └── schedule_manager.py     # Job metadata, enabled/disabled state toggles & persistence
│   ├── llm/
│   │   ├── client.py               # Gemini 3.5 Flash Lite client with autonomous tool loops & vision
│   │   ├── prompts.py              # System prompts for planner, vision intake, briefings, dispatches
│   │   ├── rate_limiter.py         # Sliding-window rate limiter (60+ RPM) with exponential backoff
│   │   └── tools.py                # Schema sanitization and Grocy MCP + local web tools bridge
│   ├── services/
│   │   ├── mcp_client.py           # Async FastMCP client connecting to attmous/grocy-mcp
│   │   ├── recipe_scraper.py       # Web recipe scraper (Schema.org/Recipe JSON-LD & clean text)
│   │   ├── profile_service.py      # Persistent user culinary profile & preference manager
│   │   └── calendar_service.py     # Google Calendar evening conflict checks
│   └── models/
│       ├── meal.py                 # Meal plan models & enums
│       └── inventory.py            # Stock, receipt item, and ingredient models
├── scripts/
│   └── init_grocy.py               # Automated Grocy master data seeder (locations & units)
└── tests/
    ├── test_discord_bot.py         # Discord bot events, attachments, slash commands, and views
    ├── test_grocy_config.py        # Configuration and Grocy master data seeding
    ├── test_llm_tools.py           # Gemini tool bindings and recipe link scraper
    ├── test_mcp_bridge.py          # Grocy MCP client connection and tools
    ├── test_rate_limiter.py        # Rate limiter pacing and exponential backoff
    ├── test_scheduler.py           # APScheduler routines, toggles, and Google Calendar service
    └── test_user_profile.py        # User profile storage, tools, and selective agent injection

# **5\. Domain Modeling & Grocy Engine Configuration**

## **5.1 Grocy Master Data Configuration**

To maintain strict data integrity without over-complicating human input, Grocy must be configured with specific master domain primitives:

1. **Storage Locations**:  
   * `Fridge` (Location ID 1): Perishables, dairy, opened sauces, and ready-to-eat prepped components.  
   * `Freezer` (Location ID 2): Vacuum-sealed bulk meats, portioned proteins, homemade stocks, and frozen goods.  
   * `Pantry` (Location ID 3): Grains, dry noodles, canned goods, condiments, spices, and oils.  
2. **Quantity Units**:  
   * Standardize on direct unit metrics: `Pack`, `Piece`, `Bottle`, `g`, `kg`, `oz`.  
   * Complex unit conversion rules are disabled in Grocy; natural language quantities are converted directly into main purchase units by Gemini 3.5 Flash Lite during extraction.  
3. **Product Management & Min Stock**:  
   * Core staples (`Rice`, `Eggs`, `Scallions`, `Chili Crisp`, `Garlic`, `Soy Sauce`) carry explicit `min_stock_amount` values in Grocy to trigger auto-replenishment on grocery lists.  
4. **Recipe System & Metadata**:  
   * Recipes stored in Grocy must contain standard duration and structural annotations within their description fields: `prep_time`, `active_cook_time`, and `style` (`component_assembly` vs. `from_scratch`).

# **6\. Autonomous Weekly Loop Logic**

## **6.1 Saturday 2:00 PM — Plan Generation & Dialogue**

   [Cron: Sat 14:00] ---> Fetch Volatile Stock (Grocy MCP)

                            ---> Fetch 14-Day History (Grocy MCP)

                            ---> Fetch Evening Events (Google Calendar API)

                                     |

                                     v

                        Pass Context to Gemini 3.5 Flash Lite

                                     |

                                     v

                     Structured 7-Day Plan Generated

                                     |

                                     v

                   Send Discord Embed + Action Buttons (View)

1. **Cron Event Trigger**: Initiated by `APScheduler` at `0 14 * * 6`.  
2. **Context Aggregation**:  
   * Grocy MCP queries expiring items approaching their expiration date.  
   * Grocy MCP queries recent meal plan entries to prevent dish repetition.  
   * `CalendarService.get_events(next_monday, next_sunday, hours=(17, 21))` identifies potential conflicts during dinner hours.  
3. **LLM Execution**:  
   * Synthesizes aggregated context into `MEAL_PLANNER_SYSTEM_PROMPT`.  
   * Gemini 3.5 Flash Lite returns a validated 7-day JSON plan adhering to structural rules: 4–5 quick component-assembly meals (<15 mins), 1–2 emergency meals (<8 mins), and `EAT_OUT` designations on calendar-conflicted evenings.  
4. **User Interaction**:  
   * Dispatches formatted rich embed to Discord channel with `[Approve Plan]` and `[Modify Plan]` interactive buttons (`discord.ui.View`).  
   * User natural language feedback in Discord (e.g., *"Swap Thursday for Korean beef bowls"*) invokes the planner module to re-evaluate requirements and re-issue the schedule.

## **6.2 Sunday Morning — Grocery Compilation, Multimodal Intake & Recipe Import**

1. **Consolidated Purchase List**: At 9:00 AM on Sunday, the scheduler calculates missing items for planned meals plus minimum baseline thresholds, emitting an aisle-sorted checklist via Discord embed.  
2. **Multimodal Computer Vision Intake**:  
   * User uploads an image of a paper receipt OR a photo of fresh groceries laid out on a kitchen counter or table.  
   * Discord event listener detects the image attachment, retrieves raw bytes, and transmits them to Gemini 3.5 Flash Lite utilizing `IMAGE_INTAKE_PROMPT`.  
   * Gemini detects the image type (`receipt` vs. `grocery_haul`), normalizes abbreviations, infers best storage locations (`Fridge`, `Freezer`, `Pantry`), and presents an interactive `ReceiptConfirmationView` with an `[Add All to Grocy]` button.  
   * On confirmation, the bot executes `stock_add_tool` to batch ingest the items into Grocy.
3. **Web Recipe Link Importing**:
   * Users can paste any recipe URL from the web (e.g. Serious Eats, NYT Cooking, food blogs) directly into Discord.
   * The bot executes `fetch_recipe_from_url_tool` via `app/services/recipe_scraper.py` to extract structured `Schema.org/Recipe` JSON-LD metadata (title, ingredients, instructions, prep times).
   * It then calls Grocy MCP's `recipe_create_by_name_tool` to persist the recipe and ingredients, and can automatically invoke `recipe_add_to_shopping_tool` for missing items.

## **6.3 Sunday Afternoon — Bulk Component Prep Directives**

1. **Prep Task Generation**: Following receipt ingestion, Gemini 3.5 Flash Lite analyzes the upcoming week's raw ingredients and outputs a list of high-leverage bulk prep steps designed to keep weeknight assembly under 15 minutes.  
2. **Execution Categories**:  
   * *Portion & Freeze*: Divide bulk meats into single-meal portions.  
   * *Base Grain Batches*: Cook multi-use grains or rice bases and store in the `Fridge`.  
   * *Sauces & Marinades*: Pre-mix high-use stir-fry liquids, dressings, and marinades.

## **6.4 Monday–Sunday — Daily Touchpoint Workflows**

1. **Morning Briefing (8:00 AM)**:  
   * Dispatches the current day's menu schedule to Discord.  
   * Identifies required advance steps: *"Move marinated chicken breast from Freezer to Fridge for evening thaw."*  
2. **Evening Execution Prompt (5:30 PM)**:  
   * Delivers concise, 4-step assembly instructions optimized for under 15 minutes of active cooking.  
   * Displays dynamic Discord interactive button controls (`discord.ui.View`):  
     * `[Cooked]`: Calls Grocy MCP to consume the recipe and deduct all required ingredients atomically.  
     * `[Eating Out / Skip]`: Defers the meal and notifies the user if fresh ingredients require immediate freezing to prevent decay.  
     * `[Swap Dinner]`: Scans current stock via Grocy MCP for a quick alternative meal option.

## **6.4 Persistent Culinary Profile & Preference Engine**

To tailor meal planning and recipes without hardcoding individual user preferences in source code:

1. **Storage & Decoupling**:
   * Preferences are saved to `data/user_profile.json` (persisted on disk and through Docker volume mounts).
   * Application source code remains completely generic with no hardcoded personal preferences.
2. **Selective Context Injection**:
   * **Meal Planner Agent** (`generate_weekly_meal_plan`): Automatically injects the user profile into the context prompt so proposed dishes align with preferred cuisines, flavor profiles, and cooking constraints.
   * **Conversational Agent** (`run_agent_loop`): Automatically injects the profile into system instructions for direct chat interactions.
   * **Grocery List Compiler** (`generate_sunday_grocery_list`): Excludes the profile to conserve LLM context tokens and maintain lean prompts.
3. **Autonomous LLM Management Tools**:
   * `user_profile_get_tool`: Inspects the active profile.
   * `user_profile_update_tool`: Autonomously called during conversational chat when the user expresses new dietary preferences, restrictions, or cuisine interests.
4. **Discord Slash Commands**:
   * `/profile [text]`: Inspects current profile metadata or updates it directly.
   * `/set_profile <text>`: Explicit command to replace or update profile preferences.
5. **Soft Length Enforcement**:
   * Enforces a soft guideline of $\le 1,000$ characters (~150 words) to ensure concise prompts, with a hard maximum cap of $2,000$ characters to guard against token bloat.

# **7\. Implementation Roadmap for Agentic Execution**

+-----------------------------------------------------------------------------------+

|                        MILESTONE 1: Environment & Container Base                 |

| - Docker Compose deployment for Grocy, attmous/grocy-mcp, and Python daemon       |

| - Environment parsing configuration via Pydantic Settings                         |

+-----------------------------------------------------------------------------------+

                                          |

                                          v

+-----------------------------------------------------------------------------------+

|                        MILESTONE 2: Grocy MCP Client Integration                  |

| - MCP client layer connecting the daemon to attmous/grocy-mcp                    |

| - Tool discovery and wrappers for stock, shopping lists, meal plan, and recipes   |

+-----------------------------------------------------------------------------------+

                                          |

                                          v

+-----------------------------------------------------------------------------------+

|                        MILESTONE 3: LLM Integration & Visual Vision Tools         |

| - Google Gemini 3.5 Flash Lite tool-calling and schema configuration              |

| - Multimodal receipt processing and structured item extraction                    |

+-----------------------------------------------------------------------------------+

                                          |

                                          v

+-----------------------------------------------------------------------------------+

|                        MILESTONE 4: Discord Interface & Event State               |

| - discord.py client for slash commands, message dialogues, and photo uploads     |

| - Interactive discord.ui.View button components (Approve, Cooked, Swap, etc.)     |

+-----------------------------------------------------------------------------------+

                                          |

                                          v

+-----------------------------------------------------------------------------------+

|                        MILESTONE 5: Cron Scheduler & Calendar Integration         |

| - APScheduler integration for weekly schedules and daily Discord dispatches       |

| - Google Calendar read-only integration for schedule conflict analysis             |

+-----------------------------------------------------------------------------------+

## **Action Items**

- [x] **Milestone 1: Environment & Base Setup**  
      * Write `docker-compose.yml` configuring `linuxserver/grocy`, `attmous/grocy-mcp`, and the custom Python daemon runtime container.  
      * Implement `config.py` using `pydantic-settings` to manage `GEMINI_API_KEY`, `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `GROCY_API_URL`, and `GROCY_API_KEY`.  
- [x] **Milestone 2: Grocy MCP Integration Layer**  
      * Build `mcp_client.py` connecting the Python daemon to `attmous/grocy-mcp` (stdio or SSE transport).  
      * Expose Grocy MCP tools covering stock management, meal plan entries, and recipe consumption.  
      * Write unit tests verifying MCP client connectivity and response formatting.  
- [x] **Milestone 3: Gemini LLM Engine & Tools**  
      * Bind Gemini function calling to Grocy MCP tools (`add_stock_batch`, `set_meal_plan`, `consume_recipe`, `get_expiring_stock`).  
      * Implement image byte handling and multimodal receipt extraction pipelines using `gemini-3.5-flash-lite`.  
- [x] **Milestone 4: Discord Interface & Views**  
      * Build Discord bot handlers for commands, text dialogues, photo receipt uploads, and `discord.ui.View` button callbacks (`Approve`, `Cooked`, `Swap`).  
      * Create rich Discord embed templates for weekly meal schedules, grocery checklists, and daily cooking steps.  
- [x] **Milestone 5: Scheduler & Dispatch Pipeline**  
      * Configure `APScheduler` tasks for Saturday plan generation, Sunday grocery & prep reminders, and daily morning/evening prompts to Discord.  
      * Support interactive toggling and manual triggering of all automated routines via Discord `/schedules`, `/toggle_schedule`, and `/run_schedule`.  
      * Integrate read-only Google Calendar dinner conflict checks.

