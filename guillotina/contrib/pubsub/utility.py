from guillotina.profile import profilable
from guillotina.utils import resolve_dotted_name
from guillotina.contrib.pubsub.exceptions import NoPubSubDriver
from typing import Any
from typing import Callable
import pickle
import asyncio
import logging


logger = logging.getLogger('guillotina')


class PubSubUtility:

    def __init__(self, settings=None, loop=None):
        self._loop = loop
        self._settings = settings
        self._subscribers = {}
        self._initialized = False
        self._driver = None
        self._tasks = {}

    async def initialized(self):
        while not self._initialized:
            await asyncio.sleep(0.5)

    @profilable
    async def initialize(self, app=None):
        driver = self._settings['driver']
        klass = resolve_dotted_name(driver)
        if klass is not None:
            self._driver = await klass.get_driver()
            await self._driver.initialize(self._loop)
            self._initialized = True

    async def finalize(self, app):
        for channel in self._tasks.values():
            if not channel.done():
                channel.cancel()
        self._initialized = False
        await asyncio.sleep(0.1)

    async def real_subscribe(self, channel_name):
        channel = await self._driver.subscribe(channel_name)
        try:
            while channel_name in self._subscribers:
                async for msg in channel:
                    try:
                        data = pickle.loads(msg)
                    except (TypeError, pickle.UnpicklingError):
                        logger.warning("Invalid message")
                        continue
                    for req, callback in self._subscribers[channel_name].items():
                        if data.get('ruid') != req:
                            await callback(data=data['data'], sender=data['ruid'])
        except asyncio.CancelledError:
            logger.error(f'Subscriber cancelled')
        except Exception:
            logger.error(f'Problem with pubsub', exc_info=True)
        finally:
            try:
                await self._driver.unsubscribe(channel_name)
            except Exception:
                pass

    async def subscribe(
            self, channel_name: str, rid: str,
            callback: Callable[[str], None]):
        if self._driver is None:
            raise NoPubSubDriver()
        if channel_name in self._subscribers:
            self._subscribers[channel_name][rid] = callback
        else:
            self._subscribers[channel_name] = {
                rid: callback
            }
            task = asyncio.ensure_future(
                self.real_subscribe(channel_name))
            self._tasks[channel_name] = task

    async def unsubscribe(self, channel_name: str, req_id: str):
        if self._driver is None:
            raise NoPubSubDriver()

        if channel_name in self._subscribers:
            if req_id in self._subscribers[channel_name]:
                del self._subscribers[channel_name][req_id]

            if len(self._subscribers[channel_name]) == 0:
                if not self._tasks[channel_name].done():
                    self._tasks[channel_name].cancel()
                del self._tasks[channel_name]

                await self._driver.unsubscribe(channel_name)
                del self._subscribers[channel_name]

    async def publish(self, channel_name: str, rid: str, data: Any):
        if self._driver is not None:
            await self._driver.publish(channel_name, pickle.dumps({
                'ruid': rid,
                'data': data
            }))
