import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Iterator, Optional

import serial

log = logging.getLogger("opt.nfc")

READ_SIZE = 256
READ_MAX = 4096
RECONNECT_DELAY = 0.5

class SerialFrames:
	def __init__(self):
		self.buffer = bytearray()
		self.synchronized = False

	def feed(self, chunk: bytes) -> Iterator[bytes]:
		for byte in chunk:
			if byte == 10:
				if self.synchronized and self.buffer:
					raw = bytes(self.buffer)
					self.buffer.clear()
					yield raw
				self.buffer.clear()
				self.synchronized = True
			elif self.synchronized:
				self.buffer.append(byte)
				if len(self.buffer) >= READ_MAX:
					self.buffer.clear()
					self.synchronized = False


@dataclass(frozen=True)
class TagEvent:
	uid: Optional[str]


def _parse_event(raw: bytes) -> Optional[TagEvent]:
	# Decode JSON NFC event
	try:
		message = json.loads(raw.decode("utf-8"))
	except (ValueError, UnicodeError, RecursionError):
		log.exception("Failed to parse event")
		return None
	if not isinstance(message, dict) or type(message.get("v")) is not int:
		log.error("Unknown event format")
		return None
	# Validate NFC event version
	if message["v"] != 1:
		log.error("Unknown event version: given {}, expected {}", message["v"], 1)
		return None

	# TODO: better, more comprehensive parsing
	event = message.get("event")
	if event == "snapshot":
		if "tag" not in message:
			return None
		tag = message["tag"]
		if tag is None:
			return TagEvent(None) if message.get("reader_status") == "ready" else None
		if not isinstance(tag, dict):
			return None
		uid = tag.get("uid")
	elif event in ("tag_present", "tag_removed"):
		uid = message.get("uid")
	else:
		return None

	if not isinstance(uid, str) or len(uid) == 0:
		return None
	return TagEvent(None if event == "tag_removed" else uid)


class NFCReader:
	def __init__(self, port: str):
		self.port = port

	@staticmethod
	async def _io_task(function: Callable[..., Any], *args, **kwargs) -> Any:
		"""
		Run a blocking IO function in a worker thread.

		The callable is scheduled on a worker thread and awaited through a shielded task so cancellation of the awaiting coroutine does not immediately
		interrupt the underlying blocking operation. If cancellation is requested, the worker thread task is awaited before cancellation is propagated.

		:param function: Function to execute in a worker thread.
		:param args: Positional arguments passed to ``function``.
		
		:return: Result returned by ``function``.
		
		:raises asyncio.CancelledError: Raised when the awaiting coroutine is cancelled after the worker-thread task has been allowed to finish.
		:raises Exception: Propagates exceptions raised by ``function`` while it is awaited normally.
		"""
		
		task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
		try:
			return await asyncio.shield(task)
		except asyncio.CancelledError:
			# Let serial IO finish before closing
			try:
				await task
			except (serial.SerialException, OSError):
				pass
			raise

	async def events(self) -> AsyncGenerator[TagEvent, None]:
		"""Yields spool UID change events."""
		
		while True:
			port = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=1)
			port.dtr = False
			port.rts = False
			port.port = self.port
			try:
				await self._io_task(port.open)
				log.info("Connected to NFC reader: %s", self.port)
				frames = SerialFrames()
				last_event = None
				while True:
					chunk = await self._io_task(port.read, READ_SIZE)
					for raw in frames.feed(chunk):
						event = _parse_event(raw)
						if event is None:
							continue
						if event != last_event:
							last_event = event
							yield event
			except (serial.SerialException, OSError):
				log.warning("Lost connection to NFC reader %s; retrying", self.port, exc_info=True)
			finally:
				await self._io_task(port.close)
			await asyncio.sleep(RECONNECT_DELAY)