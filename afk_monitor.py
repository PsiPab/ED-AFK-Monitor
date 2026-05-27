import argparse
import ctypes
import json
import os
import re
import sys
import time
import tomllib
import traceback
import unicodedata
from bisect import bisect_left
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen

try:
    from discord_webhook import DiscordWebhook
    discord_enabled = True
except ImportError:
    discord_enabled = False
    print("discord-webhook unavailable - operating with terminal output only\n")

def fallover(message):
    print(message)
    if sys.argv[0].count("\\") > 1:
        input("Press ENTER to exit")
    sys.exit()

# Internals
DEBUG_MODE = False
DISCORD_TEST = False
VERSION = 260421
GITHUB_REPO = "PsiPab/ED-AFK-Monitor"
DUPE_MAX = 5
FUEL_LOW = 0.2		# 20%
FUEL_CRIT = 0.1		# 10%
UNKNOWN = "[Unknown]"
REG_JOURNAL = r"^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$"
REG_WEBHOOK = r"^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api\/webhooks\/\d+\/[A-z0-9_-]+$"
SHIPS_EASY = ["adder", "asp", "asp_scout", "cobramkiii", "cobramkiv", "diamondback", "diamondbackxl", "eagle", "empire_courier", "empire_eagle", "krait_light", "sidewinder", "viper", "viper_mkiv"]
SHIPS_HARD = ["typex", "typex_2", "typex_3", "anaconda", "federation_dropship_mkii", "federation_dropship", "federation_gunship", "ferdelance", "empire_trader", "krait_mkii", "python", "vulture", "type9_military"]
BAIT_MESSAGES = ["$Pirate_ThreatTooHigh", "$Pirate_NotEnoughCargo", "$Pirate_OnNoCargoFound"]
COMBAT_RANKS = ["Harmless", "Mostly Harmless", "Novice", "Competent", "Expert", "Master", "Dangerous", "Deadly", "Elite", "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V"]
# Config defaults
DEFAULTS_SETTINGS = {"JournalFolder": "", "UseUTC": False, "LiveStatus": True, "DynamicTitle": True, "WarnKillRate": 20, "WarnNoKills": 20, "PirateNames": False, "BountyFaction": False, "BountyValue": False, "ExtendedStats": False, "MinScanLevel": 1}
DEFAULTS_EXTRA = {"RecentFiles": 10, "TruncatePirate": 25, "TruncateFaction": 30, "WarnNoKillsInitial": 5, "WarnKillRateDelay": 5, "WarnCooldown": 30, "RecentIntervals": [15, 30, 60], "StatusPadChar": " ", "StatusColBG": "5;236", "StatusColFG": "5;254", "StatusSafeMargin": 2}
DEFAULTS_DISCORD = {"WebhookURL": "", "UserID": 0, "PrependCmdrName": False, "ForumChannel": False, "ThreadCmdrNames": False, "Timestamp": True, "Identity": True}
DEFAULTS_LOG_LEVELS = {"ScanIncoming": 1, "ScanEasy": 1, "ScanHard": 2, "KillEasy": 2, "KillHard": 2, "FighterHull": 2, "FighterDown": 3, "ShipShields": 3, "ShipHull": 3, "Died": 3, "CargoLost": 3, "BaitValueLow": 2, "SecurityScan": 2, "SecurityAttack": 3, "FuelReport": 1, "FuelLow": 2, "FuelCritical": 3, "Missions": 2, "MissionsAll": 3, "Merits": 0, "NoKills": 3, "KillRate": 3, "SummaryKills": 2, "SummaryFaction": 0, "SummaryScans": 0, "SummaryBounties": 2, "SummaryMerits": 2}

class Col:
    CYAN = "\x1b[96m"
    YELL = "\x1b[93m"
    EASY = "\x1b[38;5;157m"
    HARD = "\x1b[38;5;217m"
    WARN = "\x1b[38;5;215m"
    BAD = "\x1b[38;5;15m\x1b[48;5;1m"
    GOOD = "\x1b[38;5;15m\x1b[48;5;2m"
    WHITE = "\x1b[97m"
    END = "\x1b[0m"

WARNING = f"{Col.WARN}Warning:{Col.END}"

class StatusLogger:
    """Logs messages to console, with support for a persistent status line
    Supports emojis, ANSI colours, padding and truncation based on terminal width
    Imports: sys, unicodedata, re"""
    
    ANSI_CLEAR_LINE =  "\x1b[2K"
    ANSI_COL_END = "\x1b[0m"
    ANSI_CURSOR_UP = "\x1b[A"
    ANSI_HIDE_CURSOR = "\x1b[?25l"
    ANSI_SHOW_CURSOR = "\x1b[?25h"
    ANSI_REGEX_STRIP = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    
    def __init__(self, clear_cols=False, pad_char="", safe_margin=2):
        self.endcol = self.ANSI_COL_END if clear_cols else ""
        self.pad = "" if not pad_char else str(pad_char)
        self.safe = safe_margin
        self._stream = sys.stdout
        self._status = ""
        self._prev = False
        self._con_prev = 0

    def _write(self, text):
        self._stream.write(text)
        self._stream.flush()
    
    def get_columns(self, input: str):
        """Returns string column width, accounting for ANSI escape sequences and emojis"""
        
        length = 0
        
        # Strip ANSI sequences
        input = self.ANSI_REGEX_STRIP.sub("", input)  
        
        # Calculate width including emojis
        for char in input:
            width = unicodedata.east_asian_width(char)
            length += 2 if width in ["F", "W"] else 1
        
        return length
    
    def _clear_lines(self):
        """Calculate line clears based on lines previous status now occupies"""
        
        con_width = os.get_terminal_size().columns
        prev_width = self.get_columns(self._status)
        prev_lines = prev_width // con_width
        clear_lines = self.ANSI_CLEAR_LINE
        
        # Clear another line for every wrap
        for _ in range(prev_lines):
            clear_lines += f"{self.ANSI_CURSOR_UP}{self.ANSI_CLEAR_LINE}"
        
        return clear_lines

    def set_status(self, msg):
        """Sets/updates a persistent status line"""
        
        # Get line clears 
        clear_lines = self._clear_lines()
        
        # Truncate status as needed based on terminal width
        con_width = os.get_terminal_size().columns
        msg_width = self.get_columns(msg)
        output = f"{msg}"
        msg_width = self.get_columns(msg)
        
        if msg_width > (con_width - self.safe):
            # Shrink status by 1 character until actual width fits within terminal
            while not self.get_columns(output) <= (con_width - self.safe - 1):
                output = output[:-1]
            output = output + ">"
        else:
            output = msg + (self.pad * (con_width - msg_width - self.safe))

        self._write(f"{clear_lines}\r{output}{self.endcol}")
        self._status = output
        self._prev = True
        self._con_prev = con_width

    def clear_status(self):
        if self._prev:
            # Clear status line
            self._write(f"{self.ANSI_CLEAR_LINE}\r")
            self._status = ""
            self._prev = False

    def log(self, msg):
        """Outputs a new line, while clearing and repeating status if set"""
        
        # Get line clears 
        clear_lines = self._clear_lines()
        
        log_line = str(msg)
        if self._prev:
            # Overwrite existing status line with new log + status
            out = f"{clear_lines}\r{log_line}\n{self._status}{self.endcol}"
            self._write(out)
        else:
            self._write(f"{log_line}\n")
    
    def hide_cursor(self):
        self._write(self.ANSI_HIDE_CURSOR)

    def show_cursor(self):
        self._write(self.ANSI_SHOW_CURSOR)

msg = StatusLogger()

# Update check
url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
latest_version = 0
try:
    with urlopen(url, timeout=1) as response:
        if response.status == 200:
            release_data = json.loads(response.read())
            latest_version = int(release_data["tag_name"][1:])
except Exception:
    pass

# Print header
title = f"ED AFK Monitor v{VERSION} by CMDR PSIPAB"
msg.log(f"{Col.CYAN}{'='*len(title)}")
msg.log(f"{title}")
msg.log(f"{'='*len(title)}{Col.END}\n")
if VERSION < latest_version:
    msg.log(f"{Col.YELL}Update v{latest_version} is available!{Col.END}\n{Col.WHITE}Download:{Col.END} https://github.com/{GITHUB_REPO}/releases\n")

# Load config file
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    configfile = Path(__file__).parents[1] / "afk_monitor.toml"
else:
    configfile = Path(__file__).parent / "afk_monitor.toml"
if configfile.is_file():
    with open(configfile, mode="rb") as f:
        try:
            config = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            fallover(f"Config decode error: {e}")
else:
    fallover("Config file not found: copy and rename afk_monitor.example.toml to afk_monitor.toml\n")

# Command line overrides
parser = argparse.ArgumentParser(
    prog="ED AFK Monitor",
    description="Live monitoring of Elite Dangerous AFK sessions to terminal and Discord")
parser.add_argument("-p", "--profile", help="Load a specific profile for config settings")
parser.add_argument("-j", "--journal", help="Override for path to journal folder")
parser.add_argument("-w", "--webhook", help="Override for Discord webhook URL")
parser.add_argument("-r", "--resetsession", action="store_true", default=None, help="Reset session stats after preloading")
parser.add_argument("-t", "--test", action="store_true", default=None, help="Re-routes Discord messages to terminal")
parser.add_argument("-d", "--debug", action="store_true", default=None, help="Print information for debugging")
file_group = parser.add_mutually_exclusive_group()
file_group.add_argument("-s", "--setfile", help="Set specific journal file to use")
file_group.add_argument("-f", "--fileselect", action="store_true", default=None, help="Show list of recent journals to chose from")
args = parser.parse_args()

# Get settings from config
def getconfig(category: str, defaults: dict, warn_missing = True) -> dict:
    settings = {}
    for setting in defaults:
        this_setting = None
        # Check if setting exists in custom profile if one is set
        if profile and config.get(profile, {}).get(category, {}).get(setting) is not None:
            this_setting = config.get(profile, {}).get(category, {}).get(setting)
        # Check if setting exists under regular settings
        elif config.get(category, {}).get(setting) is not None:
            this_setting = config.get(category, {}).get(setting)
        # Otherwise use provided default
        else:
            this_setting = defaults[setting]
            if warn_missing:
                msg.log(f"{WARNING} Config '{category}' -> '{setting}' not found (using default: {defaults[setting]})")
        
        # Check setting matches type provided in defaults
        if type(this_setting) is not type(defaults[setting]):
            msg.log(f"{WARNING} Config '{category}' -> '{setting}' expected type {type(defaults[setting]).__name__} but got {type(this_setting).__name__} (using default: {defaults[setting]})")
            this_setting =  defaults[setting]
            
        settings[setting] = this_setting
    return(settings)

# Get settings from arguments
profile = args.profile if args.profile is not None else None
setting_fileselect = args.fileselect if args.fileselect is not None else False
setting_journal_dir = args.journal if args.journal is not None else getconfig("Settings", {"JournalFolder": ""}, False)["JournalFolder"]
setting_recent_files = getconfig("Settings", {"RecentFiles": DEFAULTS_EXTRA["RecentFiles"]}, False)["RecentFiles"]
setting_journal_file = args.setfile if args.setfile is not None else None
discord_test = args.test if args.test is not None else DISCORD_TEST
debug_mode = args.debug if args.debug is not None else DEBUG_MODE

def debug(message):
    if debug_mode:
        msg.log(f"{Col.WHITE}[Debug]{Col.END} {message} [{datetime.strftime(datetime.now(), '%H:%M:%S')}]")

debug(f"Arguments: {args}")
debug(f"Config: {config}")

class Stats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.scansinrecents = []
        self.scansoutrecents = []
        self.lastkillutc = 0
        self.lastkillmono = 0
        self.killstime = 0
        self.kill_times = []
        self.scansin = 0
        self.scanstime = 0
        self.scan_times = []
        self.lastscanutc = 0
        self.lastscanmono = 0
        self.kills = 0
        self.bounties = 0
        self.factions = {}
        self.merits = 0
        self.lastsecurity = ""
        self.baitfails = 0
        self.fuellasttime = 0
        self.fuellastremain = 0
        self.meritstoreport = 0

class Tracking:
    def __init__(self):
        self.deploytime = None
        self.warnednokills = None
        self.warnedkillrate = None
        self.fuelcapacity = 64
        self.killtype = "bounties"
        self.fighterhull = 0
        self.logged = 0
        self.lines = 0
        self.missions = False
        self.missionsactive = []
        self.missionredirects = 0
        self.lasteventname = None
        self.thiseventtime = None
        self.dupeevent = ""
        self.duperepeats = 1
        self.dupewarn = False
        self.preloading = True
        self.cmdrname = None
        self.cmdrship = None
        self.cmdrcombatrank = None
        self.cmdrcombatprogress = None
        self.cmdrgamemode = None
        self.cmdrlocation = None
        self.lastcheck = None
    
    def sessionstart(self, reset=False, delta=0):
        if not self.deploytime or reset:
            if not delta:
                self.deploytime = self.thiseventtime
            else:
                self.deploytime = self.thiseventtime - timedelta(seconds=delta)
            session.reset()
            debug(f"Session tracking started at {self.deploytime}")
            session.kill_times.append(self.deploytime)
            session.scan_times.append(self.deploytime)
            self.warnednokills = None
            self.warnedkillrate = None
            self.lastcheck = time.monotonic()
            update_status()

    def sessionend(self):
        if self.deploytime:
            debug(f"Session tracking ended at {self.thiseventtime} ({time_format((self.thiseventtime-self.deploytime).total_seconds())})")
            self.deploytime = None
            update_status(True)

session = Stats()
total = Stats()
track = Tracking()

# Set journal directory
if not setting_journal_dir:
    journal_dir = Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
else:
    journal_dir = Path(setting_journal_dir)
if not journal_dir.is_dir():
    fallover(f"Directory {journal_dir} not found")

msg.log(f"{Col.YELL}Journal folder:{Col.END} {journal_dir}")

# Set journal file
if not setting_journal_file:
    journals = []
    journal_file = None

    # Get recent journals, newest first
    for entry in sorted(journal_dir.iterdir(), reverse=True):
        if entry.is_file() and bool(re.search(REG_JOURNAL, entry.name)):
            if not setting_fileselect:
                # Just the latest journal
                journal_file = entry.name
                break
            else:
                # Build list of recent journals
                journals.append(entry.name)
                if len(journals) == setting_recent_files:
                    break
    
    # Exit if no journals were found
    if not journal_file and len(journals) == 0:
        fallover("Journal folder does not contain any valid journal files")
    
    # Journal selector
    if setting_fileselect:
        msg.log("\nLatest journals:")

        # Get commander name from each journal and output list
        commanders = []
        for i, filename in enumerate(journals, start=1):
            commander = None
            with open(Path(journal_dir / filename), mode="r", encoding="utf-8") as file:
                for line in file:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as e:
                        msg.log(f"[Fileselect] JSON error in {filename}: {e}")
                    if entry["event"] == "Commander":
                        commander =  entry["Name"]
                        break

            num = f"{i:>{len(str(len(journals)))}}"
            msg.log(f"{num} | {filename} | CMDR {commander if commander else UNKNOWN}")
            commanders.append(commander)

        # Prompt for journal choice
        msg.log("\nInput journal number to load")
        selection = input("(ENTER for latest or any other input to quit)\n")
        if selection:
            try:
                selection = int(selection)
                if 1 <= selection <= setting_recent_files:
                    journal_file = journals[selection-1]
                    track.cmdrname = commanders[selection-1]
                else:
                    fallover("Invalid number, exiting...")
            except ValueError:
                fallover("Exiting...")
        else:
            journal_file = journals[0]
            track.cmdrname = commanders[0]
elif setting_journal_file:
    # Set specific journal file
    journal_file = setting_journal_file if bool(re.search(REG_JOURNAL, setting_journal_file)) else None
    if not journal_file or not (journal_dir / journal_file).is_file():
        fallover(f"Journal file '{setting_journal_file}' invalid or not found")

msg.log(f"{Col.YELL}Journal file:{Col.END} {journal_file}")

# Get commander name if not already known
if not track.cmdrname:
    try:
        with open(Path(journal_dir / journal_file), mode="r", encoding="utf-8") as file:
            for line in file:
                entry = json.loads(line)
                if entry["event"] == "Commander":
                    track.cmdrname = entry["Name"]
                    break
            
            # If we *still* don't have a commander name wait for it
            if not track.cmdrname:
                msg.log("Waiting for game load... (Press Ctrl+C to stop)")
                file.seek(0, 2)
                while True:
                    line = file.readline()
                    
                    if not line:
                        time.sleep(1)
                        continue
                    
                    entry = json.loads(line)
                    if entry["event"] == "Commander":
                        track.cmdrname = entry["Name"]
                        break
    except json.JSONDecodeError as e:
        msg.log(f"[CMDR Name] JSON error in {journal_file}: {e}")
    except(KeyboardInterrupt):
        fallover("Quitting...")

msg.log(f"{Col.YELL}Commander name:{Col.END} {track.cmdrname}")

# Check for a config profile if one is set
config_info = ""
if not args.profile:
    profile = track.cmdrname
    if profile in config:
        config_info = " (auto)"
if profile and profile not in config:
    debug(f"No config settings for '{profile}' found")
    profile = None

msg.log(f"{Col.YELL}Config profile:{Col.END} {profile if profile else 'Default'}{config_info}")
if profile:
    debug(f"Profile '{profile}': {config[profile]}")

# Get settings from config
conf_settings = getconfig("Settings", DEFAULTS_SETTINGS)
conf_settings.update(getconfig("Settings", DEFAULTS_EXTRA, False))
conf_discord = getconfig("Discord", DEFAULTS_DISCORD)
conf_log_levels = getconfig("LogLevels", DEFAULTS_LOG_LEVELS)

# Configure status line
status_col = f"\x1b[48;{conf_settings['StatusColBG']}m" if conf_settings["StatusColBG"] else ""
status_col += f"\x1b[38;{conf_settings['StatusColFG']}m" if conf_settings["StatusColFG"] else ""
msg.endcol = msg.ANSI_COL_END if status_col else ""
msg.safe = conf_settings["StatusSafeMargin"]
msg.pad = conf_settings["StatusPadChar"]

debug(f"Settings: {conf_settings}")
debug(f"Discord: {conf_discord}")
debug(f"Log levels: {conf_log_levels}")

msg.log("\nStarting... (Press Ctrl+C to stop)\n")

# Check webhook appears valid before starting
discord_webhook = args.webhook if args.webhook is not None else conf_discord["WebhookURL"]
if discord_enabled and re.search(REG_WEBHOOK, discord_webhook):
    webhook = DiscordWebhook(url=discord_webhook)
    if conf_discord["Identity"]:
        webhook.username = "ED AFK Monitor"
        webhook.avatar_url = "https://cdn.discordapp.com/attachments/1339930614064877570/1354083225923883038/t10.png"
    if conf_discord["ForumChannel"]:
        journal_start = datetime.fromisoformat(journal_file[8:-7])
        journal_start = datetime.strftime(journal_start, "%Y-%m-%d %H:%M:%S")
        if conf_discord["ThreadCmdrNames"]:
            webhook.thread_name = f"{track.cmdrname} {journal_start}"
        else:
            webhook.thread_name = journal_start
        #debug(f"webhook.thread_name: {webhook.thread_name}")
elif discord_enabled:
    discord_enabled = False
    discord_test = False
    msg.log(f"{Col.WHITE}Info:{Col.END} Discord webhook missing or invalid - operating with terminal output only\n")

# Send a webhook message or (don"t) die trying
def discordsend(message=""):
    if discord_enabled and message and not discord_test:
        try:
            webhook.content = message
            webhook.execute()
            if conf_discord["ForumChannel"] and webhook.thread_name and not webhook.thread_id:
                webhook.thread_name = None
                webhook.thread_id = webhook.id
                #debug(f"webhook.thread_id: {webhook.thread_id}")
        except Exception as e:
            msg.log(f"{Col.WHITE}Discord:{Col.END} Webhook send error: {e}")
    elif discord_enabled and message and discord_test:
        msg.log(f"{Col.WHITE}DISCORD:{Col.END} {message}")

# Log events
def logevent(msg_term, msg_discord=None, emoji=None, timestamp=None, loglevel=2, event=None):
    emoji = f"{emoji} " if emoji else ""
    loglevel = int(loglevel)
    if track.preloading and not discord_test:
        loglevel = 1 if loglevel > 0 else 0
    if timestamp:
        logtime = timestamp if conf_settings["UseUTC"] else timestamp.astimezone()
    else:
        logtime = datetime.now(timezone.utc) if conf_settings["UseUTC"] else datetime.now().astimezone()
    logtime = datetime.strftime(logtime, "%H:%M:%S")
    track.logged +=1
    
    # Terminal
    if loglevel > 0 and not discord_test:
        msg.log(f"[{logtime}]{emoji}{msg_term}")
    
    # Discord
    if discord_enabled and loglevel > 1:
        if event is not None and track.dupeevent == event:
            track.duperepeats += 1
        else:
            track.duperepeats = 1
            track.dupewarn = False
        track.dupeevent = event
        discord_message = msg_discord if msg_discord else f"**{msg_term}**"
        ping = f" <@{conf_discord['UserID']}>" if loglevel > 2 and track.duperepeats == 1 else ""
        logtime = f" {{{logtime}}}" if conf_discord["Timestamp"] else ""
        cmdrname = "" if not conf_discord["PrependCmdrName"] else f"[{track.cmdrname}] "
        if track.duperepeats <= DUPE_MAX:
            discordsend(f"{cmdrname}{emoji}{discord_message}{logtime}{ping}")
        elif not track.dupewarn:
            discordsend(f"{cmdrname}⏸️ **Suppressing further duplicate messages**{logtime}")
            track.dupewarn = True

# Calculate somethings per hour
def per_hour(seconds=0, precision=None):
    if seconds > 0:
        return round(3600 / seconds, precision)
    else:
        return 0

def recent_rates(timestamps: list, checktime: datetime, intervals: list, precision=None):
    """Calculates the number of events per hour of a given time range"""
    
    if checktime is None:
        checktime = datetime.now(timezone.utc)
    
    try:
        rates_out = {}
        if len(timestamps) > 1:
            duration = checktime - timestamps[0]
            for i in intervals:
                if duration > timedelta(minutes=i):
                    delta = timedelta(minutes=i)
                    start = checktime - delta
                    time_since = (checktime - timestamps[-1]).total_seconds()
                    index_start = bisect_left(timestamps, start) - 1
                    index_end = bisect_left(timestamps, checktime)
                    num_events = max(0, index_end - index_start)
                    if num_events > 1:
                        per_hour = (3600 / (delta.total_seconds() + time_since)) * (num_events -1)
                        rates_out[str(i)] = str(round(per_hour, precision))
                    else:
                        rates_out[str(i)] = "0"
    except Exception as e:
        msg.log(f"Error: {e}")
    
    # Format output
    if rates_out:
        keys = "/".join(rates_out.keys())
        vals = "/".join(rates_out.values())
        return f"{keys}m: {vals}h"
    else:
        return None

# Shorten a string
def truncate(input: str, chars: int) -> str:
    if len(input) <= chars+1:
        return input
    else:
        return f"{input[:chars].rstrip()}…"

# Process incoming journal entries
def processevent(line):
    try:
        j = json.loads(line)
    except ValueError:
        msg.log(f"{Col.WHITE}Warning:{Col.END} Journal parsing error, skipping line")
        return

    try:
        logtime = datetime.fromisoformat(j["timestamp"]) if "timestamp" in j else None
        track.thiseventtime = logtime
        match j["event"]:
            case "ReceiveText" if j["Channel"] == "npc":
                if "$Pirate_OnStartScanCargo" in j["Message"]:
                    piratename = j["From_Localised"] if "From_Localised" in j else UNKNOWN
                    if piratename not in session.scansinrecents:
                        session.scansin += 1
                        total.scansin += 1
                        scansin = f" (x{session.scansin})" if conf_settings["ExtendedStats"] else ""
                        pirate = f" [{piratename}]" if conf_settings["PirateNames"] else ""
                        
                        if len(session.scansinrecents) == 5:
                            session.scansinrecents.pop(0)
                        session.scansinrecents.append(piratename)
                        
                        thisscan = logtime
                        if session.lastscanutc:
                            seconds = int((thisscan-session.lastscanutc).total_seconds())
                            session.scanstime += seconds
                            total.scanstime += seconds
                        session.lastscanutc = logtime
                        session.scan_times.append(logtime)
                        if not track.preloading:
                            session.lastscanmono = time.monotonic()
                        
                        logevent(msg_term=f"Cargo scan{scansin}{pirate}",
                                    msg_discord=f"**Cargo scan{scansin}**{pirate}",
                                emoji="📦", timestamp=logtime, loglevel=conf_log_levels["ScanIncoming"])
                elif any(x in j["Message"] for x in BAIT_MESSAGES):
                    session.baitfails += 1
                    baitfails = f" (x{session.baitfails})" if conf_settings["ExtendedStats"] else ""
                    logevent(msg_term=f"{Col.WARN}Pirate didn\"t engage due to insufficient cargo value{baitfails}{Col.END}",
                            msg_discord=f"**Pirate didn\"t engage due to insufficient cargo value**{baitfails}",
                            emoji="🎣", timestamp=logtime, loglevel=conf_log_levels["BaitValueLow"], event="BaitValueLow")
                elif "Police_Attack" in j["Message"]:
                    logevent(msg_term=f"{Col.BAD}Under attack by security services!{Col.END}",
                            msg_discord="**Under attack by security services!**",
                            emoji="🚨", timestamp=logtime, loglevel=conf_log_levels["SecurityAttack"])
            case "ShipTargeted" if "Ship" in j:
                ship = j["Ship_Localised"] if "Ship_Localised" in j else j["Ship"].title()
                rank = "" if "PilotRank" not in j else f" ({j['PilotRank']})"
                # Security
                if ship != session.lastsecurity and "PilotName" in j and "$ShipName_Police" in j["PilotName"]:
                    session.lastsecurity = ship
                    logevent(msg_term=f"{Col.WARN}Scanned security{Col.END} ({ship})",
                            msg_discord=f"**Scanned security** ({ship})",
                            emoji="🚨", timestamp=logtime, loglevel=conf_log_levels["SecurityScan"])
                # Pirates etc.
                elif j["Ship"] in SHIPS_EASY or j["Ship"] in SHIPS_HARD:
                    if not track.deploytime:
                        track.sessionstart(delta=30)
                    piratename = j["PilotName_Localised"] if "PilotName_Localised" in j else UNKNOWN
                    check = piratename if conf_settings["MinScanLevel"] != 0 else ship
                    scanstage = j["ScanStage"] if "ScanStage" in j else 0
                    if scanstage >= conf_settings["MinScanLevel"] and check not in session.scansoutrecents:
                        if len(session.scansoutrecents) == 10:
                            session.scansoutrecents.pop(0)
                        session.scansoutrecents.append(check)
                        pirate = f" [{piratename}]" if conf_settings["PirateNames"] and piratename != UNKNOWN else ""
                        hard = ""
                        log = conf_log_levels["ScanEasy"]
                        if j["Ship"] in SHIPS_EASY:
                            col = Col.EASY
                        elif j["Ship"] in SHIPS_HARD:
                            col = Col.HARD
                            log = conf_log_levels["ScanHard"]
                            hard = " ☠️"
                        else:
                            col = Col.WHITE
                        logevent(msg_term=f"{col}Scan{Col.END}: {ship}{rank}{pirate}",
                                msg_discord=f"**{ship}**{hard}{rank}{pirate}",
                                emoji="🔎", timestamp=logtime, loglevel=log)
            case "Bounty" | "FactionKillBond":
                if not track.deploytime:
                    track.sessionstart(delta=60)
                
                if conf_settings["MinScanLevel"] == 0:
                    session.scansoutrecents.clear()
                session.kills +=1
                total.kills +=1
                thiskill = logtime
                killtime = ""
                track.lastcheck = time.monotonic()
                session.meritstoreport +=1
                
                if session.lastkillutc:
                    seconds = int((thiskill-session.lastkillutc).total_seconds())
                    killtime = f" (+{time_format(seconds)})"
                    session.killstime += seconds
                    total.killstime += seconds
                session.lastkillutc = logtime
                session.kill_times.append(logtime)
                if not track.preloading:
                    session.lastkillmono = time.monotonic()
                
                hard = ""
                log = conf_log_levels["KillEasy"]
                col = Col.WHITE
                if j["event"] == "Bounty":
                    if j["Target"] in SHIPS_EASY:
                        col = Col.EASY
                    elif j["Target"] in SHIPS_HARD:
                        col = Col.HARD
                        log = conf_log_levels["KillHard"]
                        hard = " ☠️"
                    
                    bountyvalue = j["Rewards"][0]["Reward"]
                    ship = j["Target_Localised"] if "Target_Localised" in j else j["Target"].title()
                else:
                    bountyvalue = j["Reward"]
                    ship = "Bond"
                    track.killtype = "bonds"

                piratename = f" [{truncate(j['PilotName_Localised'], conf_settings['TruncatePirate'])}]" if "PilotName_Localised" in j and conf_settings["PirateNames"] else ""
                session.bounties += bountyvalue
                total.bounties += bountyvalue
                kills_t = f" x{session.kills}" if conf_settings["ExtendedStats"] else ""
                kills_d = f"x{session.kills} " if conf_settings["ExtendedStats"] else ""
                bountyvalue = f" [{num_format(bountyvalue)} cr]" if conf_settings["BountyValue"] else ""
                victimfaction = j["VictimFaction_Localised"] if "VictimFaction_Localised" in j else j["VictimFaction"]
                session.factions[victimfaction] = session.factions.get(victimfaction, 0) + 1
                total.factions[victimfaction] = total.factions.get(victimfaction, 0) + 1
                factioncount = f" x{session.factions[victimfaction]}" if conf_settings["ExtendedStats"] else ""
                bountyfaction = truncate(victimfaction, conf_settings["TruncateFaction"])
                bountyfaction = f" [{bountyfaction}{factioncount}]" if conf_settings["BountyFaction"] else ""
                logevent(msg_term=f"{col}Kill{Col.END}{kills_t}: {ship}{killtime}{piratename}{bountyvalue}{bountyfaction}",
                        msg_discord=f"{kills_d}**{ship}{hard}{killtime}**{piratename}{bountyvalue}{bountyfaction}",
                        emoji="💥", timestamp=logtime, loglevel=log)

                update_status()
                
                # Output stats every 10 kills
                if session.kills % 10 == 0:
                    summary(session, logtime=logtime)
            case "MissionRedirected" if "Mission_Massacre" in j["Name"]:
                track.missionredirects += 1
                type = "a mission"
                missions = f"{track.missionredirects}/{len(track.missionsactive)}"
                if len(track.missionsactive) != track.missionredirects:
                    log = conf_log_levels["Missions"]
                else:
                    log = conf_log_levels["MissionsAll"]
                    type = "all missions!"
                logevent(msg_term=f"Completed kills for {type} ({missions})",
                        emoji="✅", timestamp=logtime, loglevel=log)
                update_status()
            case "ReservoirReplenished":
                fuelremaining = round((j["FuelMain"] / track.fuelcapacity) * 100)
                if session.fuellasttime and track.deploytime and logtime > session.fuellasttime:
                    fuel_time = (logtime-session.fuellasttime).total_seconds()
                    fuel_hour = 3600 / fuel_time * (session.fuellastremain-j["FuelMain"])
                    fuel_time_remain = time_format(j["FuelMain"] / fuel_hour * 3600)
                    fuel_time_remain = f" (~{fuel_time_remain})"
                    #debug(f"Fuel used since previous: {round(session.fuellastremain-j["FuelMain"],2)}t in {time_format(fuel_time)}")
                else:
                    fuel_time_remain = ""

                session.fuellasttime = logtime
                session.fuellastremain = j["FuelMain"]

                col = ""
                level = ":"
                fuel_loglevel = 0
                if j["FuelMain"] < track.fuelcapacity * FUEL_CRIT:
                    col = Col.BAD
                    fuel_loglevel = conf_log_levels["FuelCritical"]
                    level = " critical!"
                elif j["FuelMain"] < track.fuelcapacity * FUEL_LOW:
                    col = Col.WARN
                    fuel_loglevel = conf_log_levels["FuelLow"]
                    level = " low:"
                elif track.deploytime:
                    fuel_loglevel = conf_log_levels["FuelReport"]

                logevent(msg_term=f"{col}Fuel: {fuelremaining}% remaining{Col.END}{fuel_time_remain}",
                    msg_discord=f"**Fuel{level} {fuelremaining}% remaining**{fuel_time_remain}",
                    emoji="⛽", timestamp=logtime, loglevel=fuel_loglevel)
            case "FighterDestroyed" if track.lasteventname != "StartJump":
                logevent(msg_term=f"{Col.BAD}Fighter destroyed!{Col.END}",
                        msg_discord="**Fighter destroyed!**",
                        emoji="🕹️", timestamp=logtime, loglevel=conf_log_levels["FighterDown"])
            case "LaunchFighter" if not j["PlayerControlled"]:
                logevent(msg_term="Fighter launched",
                        emoji="🕹️", timestamp=logtime, loglevel=2)
            case "ShieldState":
                if j["ShieldsUp"]:
                    shields = "back up"
                    col = Col.GOOD
                else:
                    shields = "down!"
                    col = Col.BAD
                logevent(msg_term=f"{col}Ship shields {shields}{Col.END}",
                        msg_discord=f"**Ship shields {shields}**",
                        emoji="🛡️", timestamp=logtime, loglevel=conf_log_levels["ShipShields"])
            case "HullDamage":
                hullhealth = round(j["Health"] * 100)
                if j["Fighter"] and not j["PlayerPilot"] and track.fighterhull != j["Health"]:
                    track.fighterhull = j["Health"]
                    logevent(msg_term=f"{Col.WARN}Fighter hull damaged!{Col.END} (Integrity: {hullhealth}%)",
                        msg_discord=f"**Fighter hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="🕹️", timestamp=logtime, loglevel=conf_log_levels["FighterHull"])
                elif j["PlayerPilot"] and not j["Fighter"]:
                    logevent(msg_term=f"{Col.BAD}Ship hull damaged!{Col.END} (Integrity: {hullhealth}%)",
                        msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="🛠️", timestamp=logtime, loglevel=conf_log_levels["ShipHull"])
            case "Died":
                logevent(msg_term=f"{Col.BAD}Ship destroyed!{Col.END}",
                        msg_discord="**Ship destroyed!**",
                        emoji="💀", timestamp=logtime, loglevel=conf_log_levels["Died"])
            case "Music" if j["MusicTrack"] == "MainMenu":
                track.sessionend()
                logevent(msg_term="Exited to main menu",
                    emoji="🚪", timestamp=logtime, loglevel=2)
            case "LoadGame":
                if "Ship_Localised" in j:
                    track.cmdrship = j["Ship_Localised"]
                elif "Ship" in j:
                    track.cmdrship = j["Ship"]

                if "GameMode" in j:
                    track.cmdrgamemode = "Private Group" if j["GameMode"] == "Group" else j["GameMode"]

                cmdrinfo =  f"{track.cmdrship} / {track.cmdrgamemode} / {track.cmdrcombatrank} +{track.cmdrcombatprogress}%"
                
                logevent(msg_term=f"CMDR {track.cmdrname} ({cmdrinfo})",
                            msg_discord=f"**CMDR {track.cmdrname}** ({cmdrinfo})",
                            emoji="🔄", timestamp=logtime, loglevel=2)
            case "Loadout":
                track.fuelcapacity = j["FuelCapacity"]["Main"] if j["FuelCapacity"]["Main"] >= 2 else 64
                #debug(f"Fuel capacity: {track.fuelcapacity}")
            case "SupercruiseDestinationDrop" if any(x in j["Type"] for x in ["$MULTIPLAYER", "$Warzone"]):
                track.sessionstart(True)
                type = j["Type_Localised"] if "Type_Localised" in j else UNKNOWN
                if "Resource Extraction Site" in type:
                    emoji = "🪐"
                else:
                    emoji = "⚔️"
                logevent(msg_term=f"Dropped at {type}",
                        emoji=emoji, timestamp=logtime, loglevel=2)
                debug(f"Deploy time by supercruise drop: {track.deploytime}")
            case "EjectCargo" if not j["Abandoned"] and j["Count"] == 1:
                name = j["Type_Localised"] if "Type_Localised" in j else j["Type"].title()
                logevent(msg_term=f"{Col.BAD}Cargo stolen!{Col.END} ({name})",
                        msg_discord=f"**Cargo stolen!** ({name})",
                        emoji="🪓", timestamp=logtime, loglevel=conf_log_levels["CargoLost"], event="CargoLost")
            case "Rank":
                track.cmdrcombatrank = COMBAT_RANKS[j["Combat"]]
            case "Progress":
                track.cmdrcombatprogress = j["Combat"]
            case "Missions" if "Active" in j and not track.missions:
                track.missionsactive.clear()
                track.missionredirects = 0
                for mission in j["Active"]:
                    if "Mission_Massacre" in mission["Name"] and mission["Expires"] > 0:
                        track.missionsactive.append(mission["MissionID"])
                track.missions = True
                logevent(msg_term=f"Missions loaded (active massacres: {len(track.missionsactive)})",
                        emoji="🎯", timestamp=logtime, loglevel=conf_log_levels["Missions"])
            case "MissionAccepted" if "Mission_Massacre" in j["Name"] and track.missions:
                track.missionsactive.append(j["MissionID"])
                logevent(msg_term=f"Accepted massacre mission (active: {len(track.missionsactive)})",
                        emoji="🎯", timestamp=logtime, loglevel=conf_log_levels["Missions"])
            case "MissionAbandoned" | "MissionCompleted" | "MissionFailed" if track.missions and j["MissionID"] in track.missionsactive:
                track.missionsactive.remove(j["MissionID"])
                if track.missionredirects > 0:
                    track.missionredirects -= 1
                event = j["event"][7:].lower()
                logevent(msg_term=f"Massacre mission {event} (active: {len(track.missionsactive)})",
                        emoji="🎯", timestamp=logtime, loglevel=conf_log_levels["Missions"])
            case "PowerplayMerits":
                if session.meritstoreport > 0 and j["MeritsGained"] < 500:
                    session.merits += j["MeritsGained"]
                    total.merits += j["MeritsGained"]
                    logevent(msg_term=f"Merits: +{j['MeritsGained']} ({j['Power']})",
                                emoji="🎫", timestamp=logtime, loglevel=conf_log_levels["Merits"])
                    session.meritstoreport -= 1
            case "Location":
                #track.cmdrlocation = j["StarSystem"]
                if j["BodyType"] == "PlanetaryRing":
                    track.sessionstart()
                    #debug(f"Deploy time by location (planetary ring) {track.deploytime}")
            case "ShipyardSwap":
                track.cmdrship = j["ShipType"].title() if "ShipType_Localised" not in j else j["ShipType_Localised"]
                logevent(msg_term=f"Swapped ship to {track.cmdrship}",
                        emoji="🚢", timestamp=logtime, loglevel=2)
            case "Shutdown":
                logevent(msg_term="Quit to desktop",
                        emoji="🛑", timestamp=logtime, loglevel=2)
                if __name__ == "__main__":
                    sys.exit()
            case "SupercruiseEntry" | "FSDJump":
                if j["event"] == "SupercruiseEntry":
                    event = "Supercruise entry in"
                    emoji = "🚀"
                else:
                    event = "FSD jump to"
                    emoji = "☀️"
                logevent(msg_term=f"{event} {j['StarSystem']}",
                        emoji=emoji, timestamp=logtime, loglevel=2)
                track.sessionend()
        track.lasteventname = j["event"]
    except Exception as e:
        event = j["event"] if "event" in j else UNKNOWN
        logtime = datetime.strftime(logtime, "%H:%M:%S") if logtime else UNKNOWN
        msg.log(f"{Col.WARN}Warning:{Col.END} Process event error for [{event}]: {e} (logtime: {logtime})")
        debug(line)

def time_format(seconds: int) -> str:
	if seconds is not None and seconds >= 0:
		seconds = int(seconds)
		h = seconds // 3600
		m = seconds % 3600 // 60
		s = seconds % 3600 % 60
		if h > 0:
			return '{:d}h{:d}m'.format(h, m)
		elif m > 0:
			return '{:d}m{:d}s'.format(m, s)
		else:
			return '{:d}s'.format(s)
	else:
		return "-"

def num_format(number: int) -> str:
    if number is not None:
        number = int(number)
        if number >= 999_500:
            return f"{round(number / 1_000_000, 1):g}m"
        elif number >= 1_000:
            return f"{round(number / 1_000):g}k"
        else:
            return number

def update_status(reset=False):
    """Outputs realtime info to status line and window title"""
    
    if conf_settings["LiveStatus"] or conf_settings["DynamicTitle"]:
        if not track.preloading and track.deploytime:
            # Time
            time_utc = datetime.now(timezone.utc)
            log_time = datetime.now(timezone.utc) if conf_settings["UseUTC"] else datetime.now().astimezone()
            time_clock = datetime.strftime(log_time, "%H:%M:%S")
            session_secs = int((time_utc - track.deploytime).total_seconds())
            time_sesh = time_format(session_secs)

            # Kills
            if session.kills > 0:
                kills_hour = per_hour((time_utc - track.deploytime).total_seconds() / session.kills, 1)
            else:
                kills_hour = "-"
            
            if session.lastkillmono:
                last_kill = time_format(time.monotonic() - session.lastkillmono)
            elif session.kills > 0:
                last_kill = time_format((time_utc - session.lastkillutc).total_seconds())
            else:
                last_kill = time_format((time_utc - track.deploytime).total_seconds())
            
            # Scans
            if session.scansin > 0:
                scans_hour = per_hour((time_utc - track.deploytime).total_seconds() / session.scansin, 1)
            else:
                scans_hour = "-"
            
            if session.lastscanmono:
                lastscan = time_format(time.monotonic() - session.lastscanmono)
            elif session.scansin > 0:
                lastscan = time_format((time_utc - session.lastscanutc).total_seconds())
            else:
                lastscan = time_format((time_utc - track.deploytime).total_seconds())

            # Recent rates
            intervals = conf_settings["RecentIntervals"]
            kills_hour_recent = recent_rates(session.kill_times, None, intervals)
            scans_hour_recent = recent_rates(session.scan_times, None, intervals)

            # Status bar
            show_alt = (int(time.time()) // 5) % 2 if conf_settings["ExtendedStats"] else None
            
            if show_alt and kills_hour_recent:
                s_kills = kills_hour_recent
            else:
                s_kills = f"{kills_hour}/h (+{last_kill}) [x{session.kills}]"
            
            if show_alt and scans_hour_recent:
                s_scans = scans_hour_recent
            else:
                s_scans = f"{scans_hour}/h (+{lastscan}) [x{session.scansin}]"
            
            s_missions = f"{track.missionredirects}/{len(track.missionsactive)}"
            
            if conf_settings["LiveStatus"]:
                msg.set_status(f"{status_col}[{time_clock:>8}]💥 {s_kills:<23} | 📦 {s_scans:<23} | ⏱️ {time_sesh:<5} | 🎯 {s_missions}")
            
            # Window title (Windows only)
            if conf_settings["DynamicTitle"] and os.name=="nt":
                ctypes.windll.kernel32.SetConsoleTitleW(f"💥{kills_hour}/h ⌚{last_kill} 🎯 {s_missions}")
            
        elif reset:
            if conf_settings["DynamicTitle"] and os.name=="nt":
                ctypes.windll.kernel32.SetConsoleTitleW(f"ED AFK Monitor v{VERSION}")
            if conf_settings["LiveStatus"]:
                msg.clear_status()

# Output stats for kills, bounties and merits
def summary(stats, logtime=None, session=True):
    kill_type = track.killtype.capitalize()
    log_levels = {"Kills": conf_log_levels["SummaryKills"], "Faction": conf_log_levels["SummaryFaction"],
                  kill_type: conf_log_levels["SummaryBounties"], "Merits": conf_log_levels["SummaryMerits"],
                  "Scans": conf_log_levels["SummaryScans"]}
    log_max = max(log_levels.values())
    
    if stats.kills < 2 or log_max == 0:
        return
    
    stats_out = {}
    
    # Shared function for cargo scan and kill summaries
    def recents(duration, count, events):
        average_time = duration / (count - 1)
        hourly_rate = per_hour(average_time, 1)
        
        recent = ""
        
        # Recent rates
        if session and conf_settings["ExtendedStats"]:
            intervals = conf_settings["RecentIntervals"]
            recents = recent_rates(events, logtime, intervals)
            if recents:
                recent = f" [{recents}]"
        
        return f"{count:,} ({hourly_rate}/h | {time_format(average_time)}){recent}"
    
    # Kills
    if log_levels["Kills"] > 0:
        stats_out["Kills"] = recents(stats.killstime, stats.kills, stats.kill_times)
    
    # Faction #1 kills
    faction_kills = max(stats.factions.values())
    if log_levels["Faction"] > 0 and faction_kills > 1:
        faction_kills = max(stats.factions.values())
        faction_kills_hour = per_hour(stats.killstime / (faction_kills - 1), 1)
        faction_kills_percent = round((faction_kills / stats.kills) * 100)
        faction_name = max(stats.factions, key=stats.factions.get)

        stats_out["Faction"] = f"{faction_kills:,} ({faction_kills_hour}/h | {faction_kills_percent}%) [{faction_name}]"

    # Cargo scans
    if log_levels["Scans"] > 0 and stats.scansin > 1:
        stats_out["Scans"] = recents(stats.scanstime, stats.scansin, stats.scan_times)
    
    # Bounties
    if log_levels[kill_type] > 0:
        bounties_hour = per_hour(stats.killstime / stats.bounties)
        bounties_average = num_format(stats.bounties // stats.kills)

        stats_out[kill_type] = f"{num_format(stats.bounties)} ({num_format(bounties_hour)}/h | {bounties_average}/kill)"
    
    # Merits
    if log_levels["Merits"] > 0 and stats.merits > 0:
        merits_hour = per_hour(stats.killstime / stats.merits) if stats.merits > 0 else 0
        merits_average = round(stats.merits / stats.kills, 1)
        
        stats_out["Merits"] = f"{stats.merits:,} ({merits_hour:,}/h | {merits_average:,}/kill)"
    
    # Output
    if stats_out:
        type = "Session" if session else "Total"
        
        session_time = f" ({time_format(stats.killstime)})"
        missions_completed = f" [{track.missionredirects}/{len(track.missionsactive)}]" if len(track.missionsactive) > 0 else ""
        
        out_terminal = f"{type} Stats{session_time}{missions_completed}"
        out_discord = f"**{type} Stats**{session_time}{missions_completed}"
        
        for k, v in stats_out.items():
            if log_levels[k] >= 1:
                out_terminal += f"\n{' '*10}-> {k}: {v}"
            if log_levels[k] >= 2:
                out_discord += f"\n:white_small_square: **{k}:** {v}"

        logevent(msg_term=f"{out_terminal}",
            msg_discord=f"{out_discord}",
            emoji="📝", timestamp=logtime, loglevel=log_max)

if __name__ == "__main__":
    try:
        msg.hide_cursor()
        
        # Journal preloading
        if track.preloading:
            with open(journal_dir / journal_file, mode="r", encoding="utf-8") as file:
                for line in file:
                    processevent(line)
                    track.lines += 1
            track.preloading = False
            if args.resetsession:
                session.reset()
                track.sessionstart(reset=True)
                logevent(msg_term="Session stats reset",
                        emoji="🔄", loglevel=1)
            update_status(True)

        # Send Discord startup
        update_notice = f"\n:arrow_up: Update **[v{latest_version}](https://github.com/{GITHUB_REPO}/releases)** available!" if VERSION < latest_version else ""

        if discord_enabled:
            if conf_discord["ForumChannel"]:
                discordsend(f"💥 **ED AFK Monitor** 💥 by CMDR PSIPAB ([v{VERSION}](https://github.com/{GITHUB_REPO})){update_notice}")
                webhook.content += f" <@{conf_discord['UserID']}>"
                webhook.edit()
            else:
                discordsend(f"# 💥 ED AFK Monitor 💥\n-# **by CMDR PSIPAB ([v{VERSION}](https://github.com/{GITHUB_REPO})){update_notice}**")
        
        logevent(msg_term=f"Monitor started ({journal_file})",
                    msg_discord=f"**Monitor started** ({journal_file})",
                    emoji="📖", loglevel=2)
        
        # Open journal from end and watch for new lines
        trackingerror = None
        cooldown = conf_settings["WarnCooldown"]
        
        with open(journal_dir / journal_file, mode="r", encoding="utf-8") as file:
            file.seek(0, 2)

            while True:
                line = file.readline()
                if not line:
                    try:
                        if track.deploytime:
                            # Check for instance problems every minute
                            timemono = time.monotonic()
                            if not track.lastcheck or timemono - track.lastcheck >= 60:
                                timeutc = datetime.now(timezone.utc)
                                sessionsecs = (timeutc - track.deploytime).total_seconds()
                                if sessionsecs == 0:
                                    sessionsecs = 1	# Avoid divide-by-zero if session started by first kill
                                #if track.lastcheck: debug(f"Last: {track.lastcheck} / This: {timemono} / Drift: {60-(timemono - track.lastcheck)}")
                                timemono = timemono + (60 - (timemono - track.lastcheck)) if track.lastcheck else timemono	# Account for drift
                                track.lastcheck = timemono
                                
                                if session.kills:
                                    # Clear last warned time if past cooldown
                                    if track.warnedkillrate and timemono - track.warnedkillrate >= (cooldown * 60):
                                        cooldown *= 2
                                        track.warnedkillrate = None
                                    
                                    # Check average kill rate
                                    kills_hour = per_hour(sessionsecs / session.kills, 1)
                                    #debug(f"Kills per hour {kills_hour}")
                                    if kills_hour < conf_settings["WarnKillRate"]:
                                        if not track.warnedkillrate and sessionsecs >= (conf_settings["WarnKillRateDelay"] * 60) and (not track.warnednokills or timemono - track.warnednokills >= (cooldown * 60)):
                                            logevent(msg_term=f"Kill rate of {kills_hour}/h is below {conf_settings['WarnKillRate']}/h threshold",
                                                    emoji="⚠️", loglevel=conf_log_levels["KillRate"])
                                            track.warnedkillrate = timemono
                                    else:
                                    # Check time since last kill
                                        lastkill = int((timeutc - session.lastkillutc).total_seconds() / 60)
                                        #debug(f"timeutc: {timeutc} | lastkill: {lastkill} | track.warnedkillrate: {track.warnedkillrate} | conf_settings["WarnNoKills"]: {conf_settings["WarnNoKills"]}")
                                        if not track.warnedkillrate and lastkill >= (conf_settings["WarnNoKills"]):
                                            logevent(msg_term=f"Last logged kill was {lastkill} minutes ago",
                                                emoji="⚠️", loglevel=conf_log_levels["NoKills"])
                                            track.warnedkillrate = timemono
                                else:
                                    # Clear last warned time if past cooldown
                                    if track.warnednokills and timemono - track.warnednokills >= (cooldown * 60):
                                        cooldown *= 2
                                        track.warnednokills = None

                                    # Check time since deployment if no kills yet
                                    sessionmins = int(sessionsecs / 60)
                                    #debug(f"No kills logged since start of session {sessionmins} ({sessionsecs / 60}) minutes ago [conf_settings["WarnNoKillsInitial"]*60: {conf_settings["WarnNoKillsInitial"] * 60}]")
                                    if not track.warnednokills and sessionsecs >= (conf_settings["WarnNoKillsInitial"] * 60):
                                        logevent(msg_term=f"No kills logged for {sessionmins} minutes",
                                                emoji="⚠️", loglevel=conf_log_levels["NoKills"])
                                        track.warnednokills = timemono
                    except Exception as e:
                        if repr(e) != trackingerror:
                            msg.log(f"{Col.WARN}Warning:{Col.END} Kill rate tracking error: {e} [{datetime.strftime(datetime.now(), '%H:%M:%S')}])")
                            trackingerror = repr(e)
                    
                    time.sleep(1)
                    update_status()
                    continue

                processevent(line)
                track.lines += 1

    except (KeyboardInterrupt, SystemExit):
        summary(total, session=False)
        logevent(msg_term=f"Monitor stopped ({journal_file})",
        msg_discord=f"**Monitor stopped** ({journal_file})",
        emoji="📕", loglevel=2)
        debug(f"\nTrack: {track.__dict__}")
        
        track.sessionend()
        msg.show_cursor()
        
        if sys.argv[0].count("\\") > 1:
            input("\nPress ENTER to exit")	# This is *still* horrible
            sys.exit()
    except Exception as e:
        msg.log(f"{Col.WARN}Warning:{Col.END} Something went wrong: {e} (journal line #{track.lines})")
        traceback.print_tb(e.__traceback__)
        input("Press ENTER to exit")
