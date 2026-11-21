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
		async def method(*args, **kwargs):
			log.debug(f"Stubbing {name} call: args={args} kwargs={kwargs}")
			return {}
		return method

class MoonrakerConnection:
	def __init__(self, socket_path: Path):
		self.socket_path = socket_path
		
		self.connected = False
		self.writer: Optional[asyncio.StreamWriter]	= None
		
		self._loop: Optional[asyncio.AbstractEventLoop] = None
		self._read_task: Optional[asyncio.Task] = None
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
			except asyncio.CancelledError:
				raise
			except Exception:
				log.exception(f"Failed to connect to Moonraker: {self.socket_path}")
				await asyncio.sleep(1)
				continue
			self.writer = writer
			self.connected = True
			self._read_task = asyncio.create_task(self._read_stream(reader))
			log.info("Connected to Moonraker")
			return
	
	async def disconnect(self):
		self.connected = False
		for fut in self._pending_reqs.values():
			if not fut.done():
				fut.set_exception(ConnectionError("Disconnected from Moonraker"))
		self._pending_reqs.clear()
		task, self._read_task = self._read_task, None
		if task is not None and task is not asyncio.current_task():
			task.cancel()
			try:
				await task
			except asyncio.CancelledError:
				pass
		writer, self.writer = self.writer, None
		if writer is not None:
			writer.close()
			await writer.wait_closed()
	
	async def _read_stream(self, reader: asyncio.StreamReader):
		try:
			while not reader.at_eof():
				data = await reader.readuntil(b"\x03")
				data = data[:-1].decode(encoding="utf-8")
				log.debug(f"Received data: {data}")
				data_json: Dict[str, Any] = json.loads(data)
				if "id" in data_json:
					fut = self._pending_reqs.pop(data_json["id"], None)
					if fut is not None and not fut.done():
						fut.set_result(data_json)
		except asyncio.CancelledError:
			raise
		except asyncio.IncompleteReadError:
			pass
		except Exception:
			log.exception("Failed to read data from Moonraker")
		finally:
			log.info("Disconnected from Moonraker")
			await self.disconnect()
	
	async def _write_message(self, message: Dict[str, Any]):
		if not self.connected or self.writer is None:
			raise ConnectionError("Cannot write message to Moonraker while disconnected")
		
		data = json.dumps(message).encode() + b"\x03"
		try:
			self.writer.write(data)
			await self.writer.drain()
		except asyncio.CancelledError:
			raise
		except Exception:
			log.exception("Failed to write data to Moonraker")
			raise

	@staticmethod
	async def _as_rpc_message(method: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
		msg: Dict[str, Any] = {
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
			raise ConnectionError("Cannot send message to Moonraker before connecting")

		msg = await self._as_rpc_message(method, kwargs)
		log.debug(f"Sending message to Moonraker: {msg}")
		
		fut = self._loop.create_future()
		self._pending_reqs[msg["id"]] = fut
		try:
			await self._write_message(msg)
			return await fut
		finally:
			self._pending_reqs.pop(msg["id"], None)
	
	#
	# Register methods
	#

	async def register_method(self, method: str, callback: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]) -> None:
		self._registered_methods[method] = callback
		await self.send_message("connection/register_remote_method", method_name=method)