"""Start one private loopback server for the lifetime of the Android process."""
import asyncio
import threading
from pathlib import Path

from .download import ensure_models
from .runtime import Runtime


def start(directory, token, callback):
    root = Path(directory)
    ensure_models(root / 'models', callback.update)
    callback.update('Loading Turbo INT8…')
    runtime = Runtime(root)
    runtime.load_model('turbo', 'int8', 4)
    from aiohttp import web
    from server import create_app
    ready = threading.Event()
    errors = []

    def serve():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def launch():
            app = create_app('turbo', 4, 'int8', runtime=runtime, root=root / 'web',
                             database=root / 'sessions.sqlite3', auth_token=token)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, '127.0.0.1', 8765).start()
        try:
            loop.run_until_complete(launch())
        except Exception as error:
            errors.append(error)
            ready.set()
            loop.close()
            return
        ready.set()
        loop.run_forever()

    threading.Thread(target=serve, name='listening-server', daemon=True).start()
    ready.wait()
    if errors:
        raise errors[0]
    return 'http://127.0.0.1:8765/'
