"""Async bidirectional channel between agents and simulation platforms.

This is the concurrency backbone of the simulation engine.  Multiple agents
share a single ``Channel`` instance.  The flow is:

1. **Agent side** calls ``write_to_receive_queue(data)`` which enqueues a
   message and returns a unique ``message_id``.
2. The agent then ``await``s ``read_from_send_queue(message_id)`` which
   blocks until the platform posts a response for that specific message.
3. **Platform side** iterates ``receive_from()`` (an async generator) to
   pull messages off the receive queue.
4. After processing, the platform calls ``send_to(message_id, result)``
   which resolves the ``Future`` the agent is waiting on.

All operations are fully async-safe; many agents can have in-flight
requests concurrently.
"""

import asyncio
import itertools
import logging
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class Channel:
    """Async message channel connecting agents to a simulation platform.

    The receive queue is an ``asyncio.Queue`` (unbounded by default).
    Per-message responses are tracked via a dict of ``asyncio.Future``
    objects keyed by ``message_id``.
    """

    def __init__(self, max_queue_size: int = 0) -> None:
        """
        Args:
            max_queue_size: Maximum items in the receive queue.  0 means
                unbounded (the default and recommended setting).
        """
        self._receive_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._id_counter = itertools.count(start=1)
        self._closed = False

    # ------------------------------------------------------------------
    # Agent side
    # ------------------------------------------------------------------

    async def write_to_receive_queue(self, data: Any) -> int:
        """Enqueue a message for the platform and return a ``message_id``.

        The caller should subsequently ``await read_from_send_queue(message_id)``
        to obtain the platform's response.

        Args:
            data: Arbitrary payload.  By convention this is a tuple of
                ``(agent_id, message_body, action_type)``.

        Returns:
            A unique integer ``message_id``.
        """
        if self._closed:
            raise RuntimeError("Channel is closed")

        message_id = next(self._id_counter)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_futures[message_id] = future

        await self._receive_queue.put((message_id, data))
        logger.debug("Channel: enqueued message_id=%d", message_id)
        return message_id

    async def read_from_send_queue(self, message_id: int) -> Any:
        """Block until the platform posts a response for *message_id*.

        Args:
            message_id: The id returned by ``write_to_receive_queue``.

        Returns:
            The result posted by the platform via ``send_to``.
        """
        future = self._pending_futures.get(message_id)
        if future is None:
            raise KeyError(f"No pending future for message_id={message_id}")

        try:
            result = await future
        finally:
            # Cleanup regardless of success or cancellation.
            self._pending_futures.pop(message_id, None)

        logger.debug("Channel: agent received response for message_id=%d", message_id)
        return result

    # ------------------------------------------------------------------
    # Platform side
    # ------------------------------------------------------------------

    async def receive_from(self) -> AsyncGenerator[Tuple[int, Any], None]:
        """Async generator yielding ``(message_id, data)`` from the receive queue.

        The platform loops over this to process incoming agent requests.
        The generator runs indefinitely until the channel is closed.
        """
        while not self._closed:
            try:
                item = await asyncio.wait_for(self._receive_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            yield item

    async def send_to(self, message_id: int, result: Any) -> None:
        """Post a platform response for the given *message_id*.

        This resolves the ``Future`` that the agent is awaiting in
        ``read_from_send_queue``.

        Args:
            message_id: Must match a previously enqueued message.
            result: The response payload.
        """
        future = self._pending_futures.get(message_id)
        if future is None:
            logger.warning(
                "Channel: send_to called for unknown message_id=%d (already consumed or never created)",
                message_id,
            )
            return

        if not future.done():
            future.set_result(result)
            logger.debug("Channel: platform sent response for message_id=%d", message_id)
        else:
            logger.warning("Channel: future already done for message_id=%d", message_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Mark the channel as closed and cancel any pending futures."""
        self._closed = True
        for mid, future in list(self._pending_futures.items()):
            if not future.done():
                future.cancel()
        self._pending_futures.clear()

    @property
    def pending_count(self) -> int:
        """Number of messages awaiting a platform response."""
        return len(self._pending_futures)

    @property
    def receive_queue_size(self) -> int:
        """Current number of items in the receive queue."""
        return self._receive_queue.qsize()

    @property
    def is_closed(self) -> bool:
        return self._closed
