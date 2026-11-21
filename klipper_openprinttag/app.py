import argparse
import asyncio
import sys
import logging
from contextlib import aclosing
from pathlib import Path

from . import APP_NAME, __version__
from .moonraker_connection import StubMoonrakerConnection, MoonrakerConnection
from .nfc_reader import NFCReader

log = logging.getLogger("opt.app")

class App:
	def __init__(self, socket_path: Path, dev_mode: bool, port: str):
		self.dev_mode = dev_mode
		self.moonraker = (StubMoonrakerConnection if dev_mode else MoonrakerConnection)(socket_path)
		self.nfc_reader = NFCReader(port)
	
	async def run(self):
		try:
			await self.moonraker.connect()
			async with aclosing(self.nfc_reader.events()) as events:
				async for event in events:
					log.info("Posting spool ID: %s", event.uid)
					await self.moonraker.send_message("server.spoolman.post_spool_id", spool_id=event.uid)
		finally:
			await self.moonraker.disconnect()
	
def main():
	# Prepare argument parsing
	parser = argparse.ArgumentParser(description=f"{APP_NAME} - OpenPrintTag implementation for Klipper")
	parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
	parser.add_argument("-s", "--socketfile", default="~/printer_data/comms/moonraker.sock",
						help="Path to the Moonraker socket file")
	parser.add_argument("-p", "--nfc-port", required=True,
						help="NFC reader serial port (i.e. /dev/serial/by-id/...)")
	parser.add_argument("-l", "--log-file", default="~/printer_data/logs/klipper-openprinttag.log",
						help="Path to the log file")
	parser.add_argument("-d", "--debug", action="store_true", default=False,
						help="Enable debug logging")
	parser.add_argument("--dev-mode", action="store_true", default=False,
						help="Enable development mode")
	args = parser.parse_args()
	
	# Validate arguments
	dev_mode = args.dev_mode
	debug = args.debug or dev_mode
	
	socket_path = Path(args.socketfile).expanduser().resolve()
	if not dev_mode and not socket_path.exists():
		print(f"Error: Socket file '{socket_path}' does not exist.")
		return 1
	
	log_path = Path(args.log_file).expanduser().resolve()
	if dev_mode:
		log_path = Path("./logs/app.log")
		log_path.parent.mkdir(parents=True, exist_ok=True)
	elif not log_path.parent.exists():
		print(f"Error: Log file directory '{log_path.parent}' does not exist.")
		return 1
	
	# Basic logging setup for now
	handlers = [
		logging.StreamHandler(sys.stdout),
		logging.FileHandler(log_path),
	]
	logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers, style="{")
	
	# Run app
	app = App(socket_path, dev_mode, args.port)
	try:
		asyncio.run(app.run())
	except KeyboardInterrupt:
		log.info("KeyboardInterrupt; exiting...")
		pass
	
	return 0

if __name__ == "__main__":
	sys.exit(main())
