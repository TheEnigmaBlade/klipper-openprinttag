import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable

log = logging.getLogger("opt.moonraker")

class StubMoonrakerConnection:
	def __init__(self, *args, **kwargs):
		pass
	
	def __getattr__(self, name):
		def method(*args, **kwargs):
			log.debug(f"Stubbing {name} call")
		return method

class MoonrakerConnection:
	def __init__(self, socket_path: Path):
		self.socket_path = socket_path
		
		self.connected = False
		self.writer: Optional[asyncio.StreamWriter]	= None
		
		self._loop: Optional[asyncio.AbstractEventLoop] = None
		self._pending_reqs: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
		self._registered_methods: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {}
	
	#
	# Core IO
	#
	
	async def connect(self):
		self._loop = asyncio.get_running_loop()
		
		log.info(f"Connecting to Moonraker: {self.socket_path}")
		while True:
			try:
				reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=20 * 1024 * 1024)
				self.writer = writer
			except asyncio.CancelledError:
				raise
			except Exception:
				log.exception(f"Failed to connect to Moonraker: {self.socket_path}")
				await asyncio.sleep(1)
				continue
			break
		self.connected = True
		await self._loop.create_task(self._read_stream(reader))
		log.info("Connected to Moonraker")
	
	async def disconnect(self):
		if self.connected and self.writer:
			self.connected = False
			self.writer.close()
			await self.writer.wait_closed()
	
	async def _read_stream(self, reader: asyncio.StreamReader):
		while not reader.at_eof():
			try:
				data = await reader.readuntil(b"\x03")
				data = data[:-1].decode(encoding="utf-8")
				log.debug(f"Received data: {data}")
				data_json: Dict[str, Any] = json.loads(data)
			except asyncio.CancelledError:
				raise
			except Exception:
				log.exception("Failed to read data from Moonraker")
				break
				
			if "id" in data_json:
				fut = self._pending_reqs.pop(data_json["id"], None)
				if fut is not None:
					fut.set_result(data_json)
		
		log.info("Disconnected from Moonraker")
		await self.disconnect()
	
	async def _write_message(self, message: Dict[str, Any]):
		if self.writer is None:
			log.error("Cannot write message to Moonraker")
			return
		
		data = json.dumps(message).encode() + b"\x03"
		try:
			self.writer.write(data)
			await self.writer.drain()
		except asyncio.CancelledError:
			raise
		except Exception:
			log.exception("Failed to write data to Moonraker")

	@staticmethod
	async def _as_rpc_message(method: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
		msg = {
			"jsonrpc": "2.0",
			"method": method,
		}
		uid = id(msg)
		msg["id"] = uid
		
		if params:
			msg["params"] = params
		
		return msg
	
	async def send_message(self, method: str, **kwargs) -> Dict[str, Any]:
		if self._loop is None:
			log.error("Cannot send message to Moonraker")
			return {}

		msg = await self._as_rpc_message(method, kwargs)
		log.debug(f"Sending message to Moonraker: {msg}")
		
		fut = self._loop.create_future()
		self._pending_reqs[msg["id"]] = fut
		await self._write_message(msg)
		return await fut
	
	#
	# Register methods
	#

	async def register_method(self, method: str, callback: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]) -> None:
		self._registered_methods[method] = callback
		await self.send_message("connection/register_remote_method", method_name=method)