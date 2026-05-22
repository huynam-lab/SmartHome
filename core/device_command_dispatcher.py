from __future__ import annotations

import copy
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Optional, Tuple


_RECENT_RESULT_TTL_SECONDS = 0.75


@dataclass
class _DispatchTask:
    controller_key: str
    dedupe_key: str
    execute_fn: Callable[[], Dict[str, Any]]
    done_event: threading.Event = field(default_factory=threading.Event)
    result: Optional[Dict[str, Any]] = None


class _ControllerWorker:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.queue: Deque[_DispatchTask] = deque()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread_started = False

    def start(self) -> None:
        if self.thread_started:
            return
        self.thread.start()
        self.thread_started = True

    def _run(self) -> None:
        while True:
            with self.condition:
                while not self.queue:
                    self.condition.wait()
                task = self.queue.popleft()

            try:
                result = task.execute_fn()
            except Exception as exc:
                result = {
                    "success": False,
                    "message": f"Thuc thi lenh that bai: {exc}",
                    "details": {"error": repr(exc)},
                }

            _COMMAND_DISPATCHER._complete_task(task, result)


class DeviceCommandDispatcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: Dict[str, _ControllerWorker] = {}
        self._pending_tasks: Dict[Tuple[str, str], _DispatchTask] = {}
        self._recent_results: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}

    def dispatch_and_wait(self, controller_key: str, dedupe_key: str, execute_fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        cache_key = (str(controller_key or "").strip().lower(), str(dedupe_key or "").strip().lower())
        now = time.monotonic()

        with self._lock:
            self._prune_recent_results(now)

            recent = self._recent_results.get(cache_key)
            if recent and now - recent[0] <= _RECENT_RESULT_TTL_SECONDS:
                return copy.deepcopy(recent[1])

            task = self._pending_tasks.get(cache_key)
            if task is None:
                task = _DispatchTask(
                    controller_key=cache_key[0],
                    dedupe_key=cache_key[1],
                    execute_fn=execute_fn,
                )
                self._pending_tasks[cache_key] = task

                worker = self._workers.get(cache_key[0])
                if worker is None:
                    worker = _ControllerWorker()
                    self._workers[cache_key[0]] = worker
                    worker.start()

                with worker.condition:
                    worker.queue.append(task)
                    worker.condition.notify()

        task.done_event.wait()
        return copy.deepcopy(task.result or {"success": False, "message": "Khong nhan duoc ket qua thuc thi lenh."})

    def _complete_task(self, task: _DispatchTask, result: Dict[str, Any]) -> None:
        completed_at = time.monotonic()
        cache_key = (task.controller_key, task.dedupe_key)

        with self._lock:
            self._pending_tasks.pop(cache_key, None)
            self._recent_results[cache_key] = (completed_at, copy.deepcopy(result))

        task.result = result
        task.done_event.set()

    def _prune_recent_results(self, now: float) -> None:
        expired_keys = [
            key
            for key, (completed_at, _) in self._recent_results.items()
            if now - completed_at > _RECENT_RESULT_TTL_SECONDS
        ]
        for key in expired_keys:
            self._recent_results.pop(key, None)


_COMMAND_DISPATCHER = DeviceCommandDispatcher()


def dispatch_device_command(controller_key: str, dedupe_key: str, execute_fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    return _COMMAND_DISPATCHER.dispatch_and_wait(controller_key=controller_key, dedupe_key=dedupe_key, execute_fn=execute_fn)
