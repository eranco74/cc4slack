# cc4slack - Claude Code for Slack

Interact with Claude Code directly from Slack. This app brings the full power of Claude Code's agentic coding assistant capabilities to your Slack workspace.

## Features

- **Full Agent Mode**: Claude can read files, write code, run commands, and help with any coding task
- **Thread-Based Sessions**: Each Slack thread maintains its own conversation context
- **Tool Approvals**: Interactive buttons to approve or reject potentially dangerous operations (file writes, bash commands)
- **Streaming Responses**: See Claude's responses as they're generated
- **Socket Mode**: No public URL required - easy local development and deployment

## Quick Start

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click "Create New App"
2. Choose "From scratch" and give it a name (e.g., "Claude Code")
3. Select your workspace

### 2. Configure the Slack App

#### Enable Socket Mode
1. Go to **Settings > Socket Mode**
2. Enable Socket Mode
3. Create an App-Level Token with `connections:write` scope
4. Save the token (starts with `xapp-`)

#### Add Bot Scopes
1. Go to **OAuth & Permissions**
2. Under "Bot Token Scopes", add:
   - `app_mentions:read` - Read mentions of the bot
   - `chat:write` - Send messages
   - `im:history` - Read direct message history
   - `im:read` - Access direct messages
   - `im:write` - Send direct messages

#### Subscribe to Events
1. Go to **Event Subscriptions**
2. Enable Events
3. Under "Subscribe to bot events", add:
   - `app_mention` - When someone mentions the bot
   - `message.im` - Direct messages to the bot

#### Enable Interactivity
1. Go to **Interactivity & Shortcuts**
2. Turn on Interactivity (no URL needed for Socket Mode)

#### Install to Workspace
1. Go to **OAuth & Permissions**
2. Click "Install to Workspace"
3. Copy the "Bot User OAuth Token" (starts with `xoxb-`)

### 3. Set Up the App

```bash
# Clone or navigate to the project
cd cc4slack

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy example env file
cp .env.example .env
```

### 4. Configure Environment Variables

Edit `.env` with your tokens:

```env
# Required - Slack tokens
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Optional - Anthropic API key (if not using default auth)
ANTHROPIC_API_KEY=sk-ant-your-api-key

# Optional - Working directory for Claude
WORKING_DIRECTORY=/path/to/your/project
```

### 5. Run the App

```bash
python -m src.main
```

Or if installed:

```bash
cc4slack
```

## Usage

### In Channels
Mention the bot with your request:
```
@Claude Code Help me write a function to parse JSON
```

### In Direct Messages
Just send a message directly to the bot:
```
Can you review this code for security issues?
```

### In Threads
Continue conversations in threads - each thread maintains its own session context.

## Interactive Buttons

The app uses Slack Block Kit for rich interactions:

- **Approve/Reject**: When Claude wants to run a command or write a file, you'll see approve/reject buttons
- **Cancel**: Stop an ongoing operation
- **Clear Session**: Reset the conversation context
- **Status**: Check the current session status

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_BOT_TOKEN` | Required | Slack bot token (xoxb-...) |
| `SLACK_APP_TOKEN` | Required | Slack app token (xapp-...) |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |
| `CLAUDE_MODEL` | claude-sonnet-4-20250514 | Claude model to use |
| `CLAUDE_MAX_TURNS` | 50 | Maximum conversation turns |
| `AUTO_APPROVE_READ_ONLY` | true | Auto-approve read-only operations |
| `REQUIRE_APPROVAL_FOR_BASH` | true | Require approval for bash commands |
| `REQUIRE_APPROVAL_FOR_WRITE` | true | Require approval for file writes |
| `SESSION_STORAGE` | memory | Storage backend (memory/redis) |
| `SESSION_TTL_SECONDS` | 86400 | Session lifetime (24 hours) |
| `WORKING_DIRECTORY` | . | Working directory for Claude |
| `LOG_LEVEL` | INFO | Logging level |

## Architecture

```
src/
├── main.py                 # Entry point
├── config.py               # Configuration
├── slack/
│   ├── app.py              # Slack Bolt app setup
│   ├── events.py           # Event handlers (mentions, DMs)
│   ├── actions.py          # Button click handlers
│   ├── blocks.py           # Block Kit UI components
│   └── message_updater.py  # Streaming message updates
├── claude/
│   ├── agent.py            # Claude Code SDK wrapper
│   └── tool_approval.py    # Approval coordination
└── sessions/
    ├── manager.py          # Session lifecycle
    └── storage.py          # Storage implementations
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src

# Linting
ruff check src
```

## License

MIT
