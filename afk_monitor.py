import time
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import tomllib
import os
import ctypes
import re
import argparse
try:
	from discord import SyncWebhook
	discord_enabled = True
except ImportError:
	discord_enabled = False
	print('Discord.py unavailable - operating with terminal output only\n')

def fallover(message):
	print(message)
	input('Press ENTER to exit')
	sys.exit()

# Internals
DEBUG_MODE = False
DISCORD_TEST = False
VERSION = "250325"
GITHUB_LINK = "https://github.com/PsiPab/ED-AFK-Monitor"
DUPE_MAX = 5
FUEL_LOW = 0.2		# 20%
FUEL_CRIT = 0.1		# 10%
TRUNC_FACTION = 30
SHIPS_EASY = ['Adder', 'Asp Explorer', 'Asp Scout', 'Cobra Mk III', 'Cobra Mk IV', 'Diamondback Explorer', 'Diamondback Scout', 'Eagle', 'Imperial Courier', 'Imperial Eagle', 'Krait Phantom', 'Sidewinder', 'Viper Mk III', 'Viper Mk IV']
SHIPS_HARD = ['Alliance Crusader', 'Alliance Challenger', 'Alliance Chieftain', 'Anaconda', 'Federal Assault Ship', 'Federal Dropship', 'Federal Gunship', 'Fer-de-Lance', 'Imperial Clipper', 'Krait MK II', 'Python', 'Vulture', 'Type-10 Defender']
BAIT_MESSAGES = ['$Pirate_ThreatTooHigh', '$Pirate_NotEnoughCargo', '$Pirate_OnNoCargoFound']
LOGLEVEL_DEFAULTS = {'ScanEasy': 1, 'ScanHard': 2, 'KillEasy': 2, 'KillHard': 2, 'FighterHull': 2, 'FighterDown': 3, 'ShipShields': 3, 'ShipHull': 3, 'Died': 3, 'CargoLost': 3, 'BaitValueLow': 2, 'SecurityScan': 2, 'SecurityAttack': 3, 'FuelLow': 2, 'FuelCritical': 3, 'Missions': 2, 'MissionsAll': 3, 'SummaryKills': 2, 'SummaryBounties': 1, 'SummaryMerits': 0, 'Inactivity': 3}

# Load config file
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
	configfile = Path(__file__).parents[1] / 'afk_monitor.toml'
else:
	configfile = Path(__file__).parent / 'afk_monitor.toml'
if configfile.is_file():
	with open(configfile, "rb") as f:
		config = tomllib.load(f)
else:
	fallover('Config file not found - copy and rename afk_monitor.example.toml to afk_monitor.toml\n')

# Command line overrides
parser = argparse.ArgumentParser(
    prog='ED AFK Monitor',
    description='Live monitoring of Elite Dangerous AFK sessions to terminal and Discord')
parser.add_argument('-p', '--profile', help='Custom profile for config settings')
parser.add_argument('-j', '--journal', help='Override for path to journal folder')
parser.add_argument('-w', '--webhook', help='Override for Discord webhook URL')
parser.add_argument('-m', '--missions', type=int, help='Set number of missions remaining')
parser.add_argument('-t', '--test', action='store_true', default=None, help='Re-routes Discord messages to terminal')
parser.add_argument('-d', '--debug', action='store_true', default=None, help='Print information for debugging')

args = parser.parse_args()

# Get a setting from config
def getconfig(category, setting, default=None):
	if profile and config.get(profile, {}).get(category, {}).get(setting) is not None:
		return config.get(profile, {}).get(category, {}).get(setting)
	elif config.get(category, {}).get(setting) is not None:
		return config.get(category, {}).get(setting)
	else:
		return default if default is not None else None

# Get settings from config unless argument
profile = args.profile if args.profile is not None else None
setting_journal = args.journal if args.journal is not None else getconfig('Settings', 'JournalFolder')
setting_utc = getconfig('Settings', 'UseUTC', False)
setting_fueltank = getconfig('Settings', 'FuelTank', 64)
setting_lowkillrate = getconfig('Settings', 'LowKillRate', 20)
setting_inactivitymax = getconfig('Settings', 'InactivityMax', 15)
setting_missions = args.missions if args.missions is not None else getconfig('Settings', 'MissionTotal', 20)
setting_bountyfaction = getconfig('Settings', 'BountyFaction', True)
setting_bountyvalue = getconfig('Settings', 'BountyValue', False)
setting_dynamictitle = getconfig('Settings', 'DynamicTitle', True)
discord_webhook = args.webhook if args.webhook is not None else getconfig('Discord', 'WebhookURL', '')
discord_user = getconfig('Discord', 'UserID', 0)
discord_timestamp = getconfig('Discord', 'Timestamp', True)
discord_identity = getconfig('Discord', 'Identity', True)
loglevel = {}
for level in LOGLEVEL_DEFAULTS:
	loglevel[level] = getconfig('LogLevels', level, LOGLEVEL_DEFAULTS[level])
discord_test = args.test if args.test is not None else DISCORD_TEST
debug_mode = args.debug if args.debug is not None else DEBUG_MODE

def debug(message):
	if debug_mode:
		print(f'[Debug] {message}')

debug(f'Arguments: {args}\nConfig: {config}\nJournal: {setting_journal}\nWebhook: {discord_webhook}\nMissions: {setting_missions}\nLog levels: {loglevel}')

class Instance:
	def __init__(self):
		self.scans = []
		self.lastkill = 0
		self.killstime = 0
		self.kills = 0
		self.bounties = 0
		self.merits = 0
		self.lastsecurity = ''

	def reset(self):
		self.scans = []
		self.lastkill = 0
		self.killstime = 0
		self.kills = 0
		self.bounties = 0
		self.merits = 0
		self.lastsecurity = ''
		updatetitle()

class Tracking():
	def __init__(self):
		self.totalkills = 0
		self.totaltime = 0
		self.totalbounties = 0
		self.totalmerits = 0
		self.fighterhull = 0
		self.logged = 0
		self.missions = False
		self.missionsactive = []
		self.missionredirects = 0
		self.lastevent = ''
		self.dupemsg = ''
		self.duperepeats = 1
		self.dupewarn = False
		self.lastactivity = None
		self.inactivitywarn = True

session = Instance()
track = Tracking()

class Col:
	CYAN = '\033[96m'
	YELL = '\033[93m'
	EASY = '\x1b[38;5;157m'
	HARD = '\x1b[38;5;217m'
	WARN = '\x1b[38;5;215m'
	BAD = '\x1b[38;5;15m\x1b[48;5;1m'
	GOOD = '\x1b[38;5;15m\x1b[48;5;2m'
	WHITE = '\033[97m'
	END = '\x1b[0m'

# Set journal folder
if not setting_journal:
	journal_dir = Path.home() / 'Saved Games' / 'Frontier Developments' / 'Elite Dangerous'
else:
	journal_dir = Path(setting_journal)

# Get latest journal file
if not journal_dir.is_dir():
	fallover(f"Directory {journal_dir} not found")

journal_file = ''
reg = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
for entry in sorted(journal_dir.iterdir(), reverse=True):
	if entry.is_file() and re.search(reg, entry.name):
		journal_file = entry.name
		break

if not journal_file:
	fallover(f"Directory {journal_dir} does not contain any journal file")

# Check webhook appears valid before starting
reg = r'^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api\/webhooks\/\d+\/[A-z0-9_-]+$'
if discord_enabled and re.search(reg, discord_webhook):
	webhook = SyncWebhook.from_url(discord_webhook)
elif discord_enabled:
	discord_enabled = False
	discord_test = False
	print('Discord webhook missing or invalid - operating with terminal output only\n')

# Send a webhook message or (don't) die trying
def discordsend(message=''):
	if discord_enabled and message and not discord_test:
		try:
			if discord_identity:
				webhook.send(content=message, username="ED AFK Monitor", avatar_url="https://cdn.discordapp.com/attachments/1339930614064877570/1354083225923883038/t10.png")
			else:
				webhook.send(content=message)
		except Exception as e:
			print(f"Webhook send went wrong: {e}")
	elif discord_enabled and message and discord_test:
		print(f'{Col.WHITE}DISCORD:{Col.END} {message}')

# Log events
def logevent(msg_term, msg_discord=None, emoji='', timestamp=None, loglevel=2):
	loglevel = int(loglevel)
	if timestamp:
		logtime = timestamp if setting_utc else timestamp.astimezone()
	else:
		logtime = datetime.now(timezone.utc) if setting_utc else datetime.now()
	logtime = datetime.strftime(logtime, '%H:%M:%S')
	if loglevel > 0 and not discord_test: print(f'[{logtime}]{emoji} {msg_term}')
	track.logged +=1
	if discord_enabled and loglevel > 1:
		if track.dupemsg == msg_term:
			track.duperepeats += 1
		else:
			track.duperepeats = 1
			track.dupewarn = False
		track.dupemsg = msg_term
		discord_message = msg_discord if msg_discord else f'**{msg_term}**'
		ping = f' <@{discord_user}>' if loglevel > 2 and track.duperepeats == 1 else ''
		logtime = f' {{{logtime}}}' if discord_timestamp else ''
		if track.duperepeats <= DUPE_MAX:
			discordsend(f'{emoji} {discord_message}{logtime}{ping}')
		elif not track.dupewarn:
			discordsend(f'⏸️ **Suppressing further duplicate messages**{logtime}')
			track.dupewarn = True
	track.inactivitywarn = True

# Get log level from config or use default
def getloglevel(key=None) -> int:
	if key in loglevel and isinstance(loglevel[key], int):
		return loglevel[key]
	else:
		level = LOGLEVEL_DEFAULTS.get(key, 1)
		print(f'{Col.WHITE}Warning:{Col.END} \'{key}\' not found in \'LogLevels\' (using default of {level})')
		return level

# Process incoming journal entries
def processevent(line):
	try:
		this_json = json.loads(line)
	except ValueError:
		print(f'{Col.WHITE}Warning:{Col.END} Journal parsing error, skipping line')
		return

	logtime = datetime.fromisoformat(this_json['timestamp']) if 'timestamp' in this_json else None
	match this_json['event']:
		case 'ShipTargeted' if 'Ship' in this_json:
			ship = this_json['Ship_Localised'] if 'Ship_Localised' in this_json else this_json['Ship'].title()
			rank = '' if not 'PilotRank' in this_json else f' ({this_json['PilotRank']})'
			if ship != session.lastsecurity and 'PilotName' in this_json and '$ShipName_Police' in this_json['PilotName']:
				session.lastsecurity = ship
				logevent(msg_term=f'{Col.WARN}Scanned security{Col.END} ({ship})',
						msg_discord=f'**Scanned security** ({ship})',
						emoji='🚨', timestamp=logtime, loglevel=getloglevel('SecurityScan'))
			elif not ship in session.scans and (ship in SHIPS_EASY or ship in SHIPS_HARD):
				session.scans.append(ship)
				if ship in SHIPS_EASY:
					col = Col.EASY
					log = getloglevel('ScanEasy')
					hard = ''
				else:
					col = Col.HARD
					log = getloglevel('ScanHard')
					hard = ' ☠️'
				logevent(msg_term=f'{col}Scan{Col.END}: {ship}{rank}',
						msg_discord=f'**{ship}**{hard}{rank}',
						emoji='🔎', timestamp=logtime, loglevel=log)
		case 'Bounty':
			session.scans.clear()
			session.kills +=1
			track.totalkills +=1
			session.bounties += this_json['Rewards'][0]['Reward']
			track.totalbounties += this_json['Rewards'][0]['Reward']
			thiskill = logtime
			killtime = ''

			if session.lastkill:
				seconds = (thiskill-session.lastkill).total_seconds()
				killtime = f' (+{time_format(seconds)})'
				session.killstime += seconds
				track.totaltime += seconds
			session.lastkill = logtime

			ship = this_json['Target_Localised'] if 'Target_Localised' in this_json else this_json['Target'].title()
			if ship in SHIPS_EASY:
				col = Col.EASY
				log = getloglevel('KillEasy')
				hard = ''
			else:
				col = Col.HARD
				log = getloglevel('KillHard')
				hard = ' ☠️'
			
			bountyvalue = f' [{num_format(this_json['Rewards'][0]['Reward'])} cr]' if setting_bountyvalue else ''
			bountyfaction = this_json['VictimFaction'] if len(this_json['VictimFaction']) <= TRUNC_FACTION+3 else f'{this_json['VictimFaction'][:TRUNC_FACTION].rstrip()}...'
			bountyfaction = f' [{bountyfaction}]' if setting_bountyfaction else ''
			logevent(msg_term=f"{col}Kill{Col.END}: {ship}{killtime}{bountyvalue}{bountyfaction}",
					msg_discord=f"**{ship}{hard}{killtime}**{bountyvalue}{bountyfaction}",
					emoji='💥', timestamp=logtime, loglevel=log)
			
			if session.kills % 10 == 0 and this_json['event'] == 'Bounty':
				avgseconds = session.killstime / (session.kills - 1)
				kills_hour = round(3600 / avgseconds, 1)
				avgbounty = session.bounties // session.kills
				bounties_hour = round(3600 / (session.killstime / session.bounties))
				avgmerits = session.merits // session.kills
				merits_hour = round(3600 / (session.killstime / session.merits)) if session.merits > 0 else 0
				log = getloglevel('SummaryKills') if kills_hour > setting_lowkillrate else getloglevel('SummaryKills')+1
				logevent(msg_term=f'Session kills: {session.kills} ({kills_hour}/hr | {time_format(avgseconds)}/kill)',
						emoji='📝', timestamp=logtime, loglevel=log)
				logevent(msg_term=f'Session bounties: {num_format(session.bounties)} ({num_format(bounties_hour)}/hr | {num_format(avgbounty)}/kill)',
						emoji='📝', timestamp=logtime, loglevel=getloglevel('SummaryBounties'))
				logevent(msg_term=f'Session merits: {num_format(session.merits)} ({num_format(merits_hour)}/hr | {num_format(avgmerits)}/kill)',
						emoji='📝', timestamp=logtime, loglevel=getloglevel('SummaryMerits'))
			
			updatetitle()
		case 'MissionRedirected' if 'Mission_Massacre' in this_json['Name']:
			track.missionredirects += 1
			msg = 'a mission'
			if track.missions:
				missions = f'{track.missionredirects}/{len(track.missionsactive)}'
				if len(track.missionsactive) != track.missionredirects:
					log = getloglevel('Missions')
				else:
					log = getloglevel('MissionsAll')
					msg = 'all missions!'
			else:
				missions = f'x{track.missionredirects}'
				log = getloglevel('Missions') if track.missionredirects != setting_missions else getloglevel('MissionsAll')
			logevent(msg_term=f'Completed kills for {msg} ({missions})',
					emoji='✅', timestamp=logtime, loglevel=log)
			updatetitle()
		case 'ReservoirReplenished' if this_json['FuelMain'] < setting_fueltank * FUEL_LOW:
			if this_json['FuelMain'] < setting_fueltank * FUEL_CRIT:
				col = Col.BAD
				fuel_loglevel = getloglevel('FuelCritical')
				level = 'critical!'
			else:
				col = Col.WARN
				fuel_loglevel = getloglevel('FuelLow')
				level = 'low'
			fuelremaining = round((this_json['FuelMain'] / setting_fueltank) * 100)
			logevent(msg_term=f'{col}Fuel reserves {level}{Col.END} (Remaining: {fuelremaining}%)',
					msg_discord=f'**Fuel reserves {level}** (Remaining: {fuelremaining}%)',
					emoji='⛽', timestamp=logtime, loglevel=fuel_loglevel)
		case 'FighterDestroyed' if track.lastevent != 'StartJump':
			logevent(msg_term=f'{Col.BAD}Fighter destroyed!{Col.END}',
					msg_discord=f'**Fighter destroyed!**',
					emoji='🕹️', timestamp=logtime, loglevel=getloglevel('FighterDown'))
		case 'LaunchFighter' if not this_json['PlayerControlled']:
			logevent(msg_term='Fighter launched',
					emoji='🕹️', timestamp=logtime, loglevel=2)
		case 'ShieldState':
			if this_json['ShieldsUp']:
				shields = 'back up'
				col = Col.GOOD
			else:
				shields = 'down!'
				col = Col.BAD
			logevent(msg_term=f'{col}Ship shields {shields}{Col.END}',
					msg_discord=f'**Ship shields {shields}**',
					emoji='🛡️', timestamp=logtime, loglevel=getloglevel('ShipShields'))
		case 'HullDamage':
			hullhealth = round(this_json['Health'] * 100)
			if this_json['Fighter'] and not this_json['PlayerPilot'] and track.fighterhull != this_json['Health']:
				track.fighterhull = this_json['Health']
				logevent(msg_term=f'{Col.WARN}Fighter hull damaged!{Col.END} (Integrity: {hullhealth}%)',
					msg_discord=f'**Fighter hull damaged!** (Integrity: {hullhealth}%)',
					emoji='🕹️', timestamp=logtime, loglevel=getloglevel('FighterHull'))
			elif this_json['PlayerPilot'] and not this_json['Fighter']:
				logevent(msg_term=f'{Col.BAD}Ship hull damaged!{Col.END} (Integrity: {hullhealth}%)',
					msg_discord=f'**Ship hull damaged!** (Integrity: {hullhealth}%)',
					emoji='🛠️', timestamp=logtime, loglevel=getloglevel('ShipHull'))
		case 'Died':
			logevent(msg_term=f'{Col.BAD}Ship destroyed!{Col.END}',
					msg_discord='**Ship destroyed!**',
					emoji='💀', timestamp=logtime, loglevel=getloglevel('Died'))
		case 'Music' if this_json['MusicTrack'] == 'MainMenu':
			logevent(msg_term='Exited to main menu',
				emoji='🚪', timestamp=logtime, loglevel=2)
			track.inactivitywarn = False
			session.reset()
		case 'LoadGame':
			ship = this_json['Ship'] if 'Ship_Localised' not in this_json else this_json['Ship_Localised']
			mode = 'Private' if this_json['GameMode'] == 'Group' else this_json['GameMode']
			logevent(msg_term=f"Loaded CMDR {this_json['Commander']} ({ship}) [{mode}]",
					msg_discord=f"**Loaded CMDR {this_json['Commander']}** ({ship}) [{mode}]",
					emoji='🔄', timestamp=logtime, loglevel=2)
			session.reset()
		case 'SupercruiseDestinationDrop' if '$MULTIPLAYER' in this_json['Type']:
			logevent(msg_term=f"Dropped at {this_json['Type_Localised']}",
					emoji='🚀', timestamp=logtime, loglevel=2)
			session.reset()
		case 'ReceiveText' if this_json['Channel'] == 'npc':
			if any(x in this_json['Message'] for x in BAIT_MESSAGES):
				logevent(msg_term=f'{Col.WARN}Pirate didn\'t engage due to insufficient cargo value{Col.END}',
			 			msg_discord='**Pirate didn\'t engage due to insufficient cargo value**',
						emoji='🎣', timestamp=logtime, loglevel=getloglevel('BaitValueLow'))
			elif 'Police_Attack' in this_json['Message']:
				logevent(msg_term=f'{Col.BAD}Under attack by security services!{Col.END}',
			 			msg_discord=f'**Under attack by security services!**',
						emoji='🚨', timestamp=logtime, loglevel=getloglevel('SecurityAttack'))
		case 'EjectCargo' if not this_json["Abandoned"] and this_json['Count'] == 1:
			name = this_json['Type_Localised'] if 'Type_Localised' in this_json else this_json['Type'].title()
			logevent(msg_term=f'{Col.BAD}Cargo stolen!{Col.END} ({name})',
					msg_discord=f'**Cargo stolen!** ({name})',
					emoji='📦', timestamp=logtime, loglevel=getloglevel('CargoLost'))
		case 'Missions' if 'Active' in this_json and not track.missions:
			track.missionsactive.clear()
			track.missionredirects = 0
			for mission in this_json['Active']:
				if 'Mission_Massacre' in mission['Name'] and mission['Expires'] > 0:
					track.missionsactive.append(mission['MissionID'])
			track.missions = True
			logevent(msg_term=f'Missions loaded (active massacres: {len(track.missionsactive)})',
					emoji='🎯', timestamp=logtime, loglevel=getloglevel('Missions'))
			updatetitle()
		case 'MissionAccepted' if 'Mission_Massacre' in this_json['Name'] and track.missions:
			track.missionsactive.append(this_json['MissionID'])
			logevent(msg_term=f'Accepted massacre mission (active: {len(track.missionsactive)})',
					emoji='🎯', timestamp=logtime, loglevel=getloglevel('Missions'))
			updatetitle()
		case 'MissionAbandoned' | 'MissionCompleted' | 'MissionFailed' if track.missions and this_json['MissionID'] in track.missionsactive:
			track.missionsactive.remove(this_json['MissionID'])
			if track.missionredirects > 0: track.missionredirects -= 1
			event = this_json['event'][7:].lower()
			logevent(msg_term=f'Massacre mission {event} (active: {len(track.missionsactive)})',
					emoji='🎯', timestamp=logtime, loglevel=getloglevel('Missions'))
			updatetitle()
		case 'PowerplayMerits':
			session.merits += this_json['MeritsGained']
			track.totalmerits += this_json['MeritsGained']
		case 'Shutdown':
			logevent(msg_term='Quit to desktop',
					emoji='🛑', timestamp=logtime, loglevel=2)
			if __name__ == "__main__": sys.exit()
		case 'SupercruiseEntry':
			session.reset()
	track.lastevent = this_json['event']

def time_format(seconds: int) -> str:
	if seconds is not None:
		seconds = int(seconds)
		h = seconds // 3600 % 24
		m = seconds % 3600 // 60
		s = seconds % 3600 % 60
		if h > 0:
			return '{:d}h{:d}m{:d}s'.format(h, m, s)
		elif m > 0:
			return '{:d}m{:d}s'.format(m, s)
		else:
			return '{:d}s'.format(s)

def num_format(number: int) -> str:
    if number is not None:
        number = int(number)
        if number >= 999_500:
            return f'{round(number / 1_000_000, 1):g}m'
        elif number >= 1_000:
            return f'{round(number / 1_000):g}k'
        else:
            return number

def updatetitle():
	# Title (Windows-only)
	if setting_dynamictitle and os.name=='nt':
		missionsactive = len(track.missionsactive) if track.missions else '-'

		if session.kills > 1:
			kills_hour = round(3600 / (session.killstime / (session.kills - 1)), 1)
			if session.kills < 20:
				kills_hour = f'{kills_hour}*'
		else:
			kills_hour = '-'

		ctypes.windll.kernel32.SetConsoleTitleW(f'EDAFKM 🎯{track.missionredirects}/{missionsactive} 💥{kills_hour}/h')

def shutdown():
	if track.totalkills > 1:
		avgseconds = track.totaltime / (track.totalkills - 1)
		kills_hour = round(3600 / avgseconds, 1)
		avgbounty = track.totalbounties // track.totalkills
		bounties_hour = round(3600 / (track.totaltime / track.totalbounties))
		avgmerits = track.totalmerits // track.totalkills
		merits_hour = round(3600 / (track.totaltime / track.totalmerits)) if track.totalmerits > 0 else 0
		logevent(msg_term=f'Total kills: {track.totalkills} ({kills_hour}/hr | {time_format(avgseconds)}/kill)',
				emoji='📝', loglevel=getloglevel('SummaryKills'))
		logevent(msg_term=f'Total bounties: {num_format(track.totalbounties)} ({num_format(bounties_hour)}/hr | {num_format(avgbounty)}/kill)',
				emoji='📝', loglevel=getloglevel('SummaryBounties'))
		logevent(msg_term=f'Total merits: {num_format(track.totalmerits)} ({num_format(merits_hour)}/hr | {num_format(avgmerits)}/kill)',
				emoji='📝', loglevel=getloglevel('SummaryMerits'))
	logevent(msg_term=f'Monitor stopped ({journal_file})',
			msg_discord=f'**Monitor stopped** ({journal_file})',
			emoji='📕', loglevel=2)

def header():
	if os.name=='nt': ctypes.windll.kernel32.SetConsoleTitleW(f'ED AFK Monitor v{VERSION}')
	# Print header
	title = f'ED AFK Monitor v{VERSION} by CMDR PSIPAB'
	print(f"{Col.CYAN}{'='*len(title)}{Col.END}")
	print(f'{Col.CYAN}{title}{Col.END}')
	print(f"{Col.CYAN}{'='*len(title)}{Col.END}\n")
	print(f'{Col.YELL}Journal folder:{Col.END} {journal_dir}')
	print(f'{Col.YELL}Latest journal:{Col.END} {journal_file}')
	if profile: print(f'{Col.YELL}Config profile:{Col.END} {profile}')
	print('\nStarting... (Press Ctrl+C to stop)\n')

if __name__ == '__main__':
	header()
	discordsend(f'# 💥 ED AFK Monitor 💥\n-# by CMDR PSIPAB ([v{VERSION}]({GITHUB_LINK}))')
	logevent(msg_term=f'Monitor started ({journal_file})',
			msg_discord=f'**Monitor started** ({journal_file})',
			emoji='📖', loglevel=2)
	
	track.lastactivity = datetime.now()
	
	# Open journal from end and watch for new lines
	with open(journal_dir / journal_file, encoding="utf-8") as file:
		file.seek(0, 2)

		try:
			while True:
				line = file.readline()
				if not line:
					time.sleep(1)
					if setting_inactivitymax and track.inactivitywarn and (datetime.now() - track.lastactivity).total_seconds() > (setting_inactivitymax * 60):
						logevent(msg_term=f'No journal activity detected for {setting_inactivitymax} minutes',
								emoji='⚠️', loglevel=getloglevel('Inactivity'))
						track.inactivitywarn = False
					continue

				processevent(line)
				track.lastactivity = datetime.now()

		except (KeyboardInterrupt, SystemExit):
			shutdown()
			if sys.argv[0].count('\\') > 1:
				input('\nPress ENTER to exit')	# This is *still* horrible
				sys.exit()
		except Exception as e:
			print(f"Something went wrong: {e}")
			input("Press ENTER to exit")
