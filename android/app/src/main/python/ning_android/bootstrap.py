"""Start one private loopback server for the lifetime of the Android process."""
import asyncio
import threading
from pathlib import Path

from .remote_runtime import RemoteRuntime


_loop = None
_runner = None
_thread = None


def start(directory, token, callback, remote_url="", remote_token=""):
    global _loop, _runner, _thread
    if _loop is not None:
        asyncio.run_coroutine_threadsafe(_runner.cleanup(), _loop).result(timeout=15)
        _loop.call_soon_threadsafe(_loop.stop)
        _thread.join(timeout=5)
        _loop = _runner = _thread = None
    root = Path(directory)
    callback.update('Connecting to your PC…')
    runtime = RemoteRuntime(remote_url, remote_token)
    runtime.load_model('turbo', 'int8', 4)
    from aiohttp import web
    from server import create_app
    ready = threading.Event()
    errors = []

    def serve():
        global _loop, _runner
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def launch():
            global _loop, _runner
            app = create_app('turbo', 4, 'int8', runtime=runtime, root=root / 'web',
                             database=root / 'sessions.sqlite3', auth_token=token)
            runner = web.AppRunner(app, shutdown_timeout=3)
            await runner.setup()
            await web.TCPSite(runner, '127.0.0.1', 8765).start()
            _loop, _runner = loop, runner
        try:
            loop.run_until_complete(launch())
        except Exception as error:
            errors.append(error)
            ready.set()
            loop.close()
            return
        ready.set()
        loop.run_forever()
        loop.close()

    _thread = threading.Thread(target=serve, name='listening-server', daemon=True)
    _thread.start()
    ready.wait()
    if errors:
        raise errors[0]
    return 'http://127.0.0.1:8765/'
