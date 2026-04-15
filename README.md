# Elite Dangerous AFK Monitor

Real-time monitoring of Elite Dangerous journal files for logging AFK massacre farming events as they happen. Output is to terminal, Discord channel/thread or Discord with a user ping and each level can be configured on a per-event basis.

| Terminal output | Discord output |
| --- | --- |
| ![Terminal](images/v250205_terminal.png) | ![Discord](images/v250205_discord.png) |

*Screenshots of a simulated log being monitored*

## Contents
- [Elite Dangerous AFK Monitor](#elite-dangerous-afk-monitor)
  - [Contents](#contents)
  - [Events and information logged](#events-and-information-logged)
    - [Plus realtime reporting of...](#plus-realtime-reporting-of)
  - [Getting started](#getting-started)
    - [Standalone (EXE) version](#standalone-exe-version)
    - [Python version](#python-version)
  - [Configuring log levels](#configuring-log-levels)
  - [Launch Arguments](#launch-arguments)
  - [Common Issues](#common-issues)
    - [No new terminal output during a live session](#no-new-terminal-output-during-a-live-session)
    - [Some kills are not being logged](#some-kills-are-not-being-logged)
    - [Ships scans are reported when manually scanned](#ships-scans-are-reported-when-manually-scanned)
    - [Ship or fighter hull damage not logged](#ship-or-fighter-hull-damage-not-logged)
    - [Stolen cargo notifications when ejecting cargo](#stolen-cargo-notifications-when-ejecting-cargo)
    - [Garbled characters or repeated lines in terminal output](#garbled-characters-or-repeated-lines-in-terminal-output)

## Events and information logged
- Outgoing ship scans (by player or by NPC pilot in fighter)
- Incoming scans of ship cargo by pirates
- Bounties (i.e. kills) incl. faction and time since previous
- Kill/bounty/merit summary and recent average rates
- Mission kills completed and missions remaining
- Ship shields down/restored
- Ship/fighter hull damage
- Ship/fighter destroyed
- Pirates not engaging due to low cargo value
- Cargo stolen
- Fuel reserves low/critical
- Warnings about hostile security forces
- Low kill rate per hour warnings
- No kills in x minutes warnings

### Plus realtime reporting of...
- Kill rate, elapsed time since last kill & number of kills
- Cargo scan rate, elapsed time since last scan & number of scans
- Session time
- Mission status

## Getting started

**Standalone (EXE) version**: Recommended for Windows users that aren't familiar with Python.  
**Python version**: For everyone else, including Linux users.

> ℹ️ AFK Monitor uses features of modern terminal emulators such as [Windows Terminal](https://apps.microsoft.com/detail/9n0dx20hk701). Functionality will be degraded with older software such as the the Windows 10 console. For more information see [Terminal Support](https://github.com/PsiPab/ED-AFK-Monitor/wiki/Terminal-Support).

### Standalone (EXE) version

- Download and extract `afk_monitor_standalone.7z` from [releases](https://github.com/PsiPab/ED-AFK-Monitor/releases) to a folder
- Copy `afk_monitor.example.toml` and rename the copy to `afk_monitor.toml`
- (Optional) For Discord support edit `WebhookURL` and `UserID` under `[Discord]` in `afk_monitor.toml`
- Start Elite Dangerous then run `afk_monitor.exe`

For more detailed instructions see [Basic Setup](https://github.com/PsiPab/ED-AFK-Monitor/wiki/Basic-Setup).

### Python version

Requirements: [Python 3.12+](https://www.python.org/downloads/), [discord-webhook](https://github.com/lovvskillz/python-discord-webhook) (optional, required for Discord support)
- Download `Source code (zip)` from [releases](https://github.com/PsiPab/ED-AFK-Monitor/releases) and extract the contents to a folder
- Copy `afk_monitor.example.toml` and rename the copy to `afk_monitor.toml`
- (Optional) For Discord support edit `WebhookURL` and `UserID` under `[Discord]` in `afk_monitor.toml`
- Start Elite Dangerous then double-click `afk_monitor.py` *or* open a terminal and run `py afk_monitor.py`
  
## Configuring log levels

Each type of event can be set to one of four additive output levels - nothing (0), terminal (1), Discord (2) or Discord plus user ping (3). These can be configured by editing the values in `afk_monitor.toml` under the section `[LogLevels]`. Each event type is described in the config file.

Defaults are intended to be sensible for those new to AFK. For example, scans of hard ships are logged to Discord to aid with avoiding difficult instances.

To reset any log levels to defaults simply copy the appropriate values from `afk_monitor.example.toml`.

## Launch Arguments

You can pass the following arguments when launching AFK Monitor:
```
-p, --profile <profile_name>                  Load a specific profile for config settings
-j, --journal <journal_folder_path>           Override for path to journal folder
-w, --webhook <webhook_url>                   Override for Discord webhook URL
-r, --resetsession                            Reset session stats after preloading
-t, --test                                    Re-routes Discord messages to terminal
-d, --debug                                   Print information for debugging
-s, --setfile <journal_file_path>             Set specific journal file to use
-f, --fileselect                              Show list of recent journals to chose from
```

## Common Issues

### No new terminal output during a live session

By default AFK Monitor watches your latest journal, so make sure to start it after loading the game. To monitor a different journal pass `--fileselect` when starting AFK Monitor and a list of recent journals will be provided to chose from.

### Some kills are not being logged

ED does not log all bounties either in-game or to the journal (anywhere from 0-30% are missed). This is a game limitation. However, these 'ghost' kills are still counted towards your mission completions if they are for the target faction.

### Ships scans are reported when manually scanned

Scans by your NPC pilot are logged just like any other scans. To avoid erroneous logging of scans (e.g. of system security) while using AFK Monitor set and use a key bind for 'select next hostile target' instead of scanning any target. Alternatively, outgoing scan logs can be disabled by config.

### Ship or fighter hull damage not logged

ED only records hull damage in 20% increments, so if your ship or fighter hull was reduced to 81% for example that wouldn't be reported. Further damage that reduces the hull below 80% (or 60%, 40%, 20%) would be logged.

### Stolen cargo notifications when ejecting cargo

ED's journal does not differentiate between individual units of cargo jettisoned by the player or stolen by hatch breaker limpets. As a workaround if you want to get rid of cargo with AFK Monitor running and not be notified you can use 'Abandon' instead of 'Jettison', or jettison more than one unit at a time.

### Garbled characters or repeated lines in terminal output

The Windows 10 console doesn't support some of the modern terminal features AFK Monitor uses. It is recommended to install and use [Windows Terminal](https://apps.microsoft.com/detail/9n0dx20hk701) instead. For more information see [Terminal Support](https://github.com/PsiPab/ED-AFK-Monitor/wiki/Terminal-Support).