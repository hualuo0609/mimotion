import hashlib
import json
import os
import random
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import fcntl


class DailyStepState:
    """Persist the last successful step for each account and Beijing date."""

    def __init__(self, state_path, rng=None):
        self.state_path = Path(state_path)
        self.rng = rng or random.randint
        self._data_lock = threading.Lock()
        self._account_locks_lock = threading.Lock()
        self._account_locks = {}

    @staticmethod
    def _account_key(account):
        return hashlib.sha256(str(account).encode("utf-8")).hexdigest()

    @staticmethod
    def _date_key(day):
        return day.isoformat() if hasattr(day, "isoformat") else str(day)

    def _load_unlocked(self):
        if not self.state_path.exists():
            return {"version": 1, "accounts": {}}
        try:
            with self.state_path.open("r", encoding="utf-8") as state_file:
                data = json.load(state_file)
            if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
                raise ValueError("invalid state structure")
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"version": 1, "accounts": {}}

    @contextmanager
    def _file_lock(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @contextmanager
    def _state_guard(self):
        lock_path = self.state_path.with_name(f".{self.state_path.name}.lock")
        with self._data_lock:
            with self._file_lock(lock_path):
                yield

    def _account_thread_lock(self, account_key):
        with self._account_locks_lock:
            return self._account_locks.setdefault(account_key, threading.Lock())

    def _account_lock_path(self, account_key):
        return self.state_path.with_name(
            f".{self.state_path.name}.{account_key}.account.lock"
        )

    def _last_success_from_data(self, data, account, day):
        account_state = data["accounts"].get(self._account_key(account), {})
        if account_state.get("date") != self._date_key(day):
            return None
        step = account_state.get("step")
        return step if isinstance(step, int) and step >= 0 else None

    def _select_from_data(self, data, account, day, min_step, max_step, daily_max):
        candidate = self.rng(int(min_step), int(max_step))
        daily_max = int(daily_max)
        last_step = self._last_success_from_data(data, account, day)
        if last_step is None:
            return min(candidate, daily_max)
        if last_step >= daily_max:
            return daily_max
        return min(max(candidate, last_step + 1), daily_max)

    def select_step(self, account, day, min_step, max_step, daily_max):
        with self._state_guard():
            data = self._load_unlocked()
            return self._select_from_data(
                data, account, day, min_step, max_step, daily_max
            )

    def record_success(self, account, day, step):
        with self._state_guard():
            data = self._load_unlocked()
            data["accounts"][self._account_key(account)] = {
                "date": self._date_key(day),
                "step": int(step),
            }
            self._write_unlocked(data)

    def _write_unlocked(self, data):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                os.fchmod(temp_file.fileno(), 0o600)
                json.dump(data, temp_file, ensure_ascii=False, separators=(",", ":"))
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.state_path)
            os.chmod(self.state_path, 0o600)
            directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def submit(self, account, day, min_step, max_step, daily_max, post_step):
        account_key = self._account_key(account)
        account_lock = self._account_thread_lock(account_key)
        with account_lock:
            with self._file_lock(self._account_lock_path(account_key)):
                with self._state_guard():
                    data = self._load_unlocked()
                    previous_state = data["accounts"].get(account_key)
                    step = self._select_from_data(
                        data, account, day, min_step, max_step, daily_max
                    )
                    reservation = {"date": self._date_key(day), "step": step}
                    data["accounts"][account_key] = reservation
                    self._write_unlocked(data)

                try:
                    ok, message = post_step(str(step))
                except Exception:
                    # The server may have accepted the update even when its response
                    # was lost. Keep the durable reservation to prevent regression.
                    raise
                if not ok:
                    self._rollback_reservation(account_key, reservation, previous_state)
                return step, ok, message

    def _rollback_reservation(self, account_key, reservation, previous_state):
        with self._state_guard():
            data = self._load_unlocked()
            if data["accounts"].get(account_key) != reservation:
                return
            if previous_state is None:
                data["accounts"].pop(account_key, None)
            else:
                data["accounts"][account_key] = previous_state
            self._write_unlocked(data)
