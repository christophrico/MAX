import threading
from typing import Dict, Any, Optional


class ThreadSafeState:
    """
    A thread-safe state container that provides dictionary-like access.
    """

    def __init__(self, initial_state: Optional[Dict[str, Any]] = None):
        """
        Initialize the state container.

        Args:
            initial_state: Initial state dictionary
        """
        self._lock = threading.RLock()
        self._state = initial_state or {}

    def __getitem__(self, key: str) -> Any:
        """
        Get a value from the state using dictionary syntax.

        Args:
            key: The state key to retrieve

        Returns:
            The value for the key
        """
        with self._lock:
            return self._state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Set a value in the state using dictionary syntax.

        Args:
            key: The state key to set
            value: The value to set
        """
        with self._lock:
            self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a value from the state with a default fallback.

        Args:
            key: The state key to retrieve
            default: Default value if key doesn't exist

        Returns:
            The value from state or default
        """
        with self._lock:
            return self._state.get(key, default)

    def update(self, updates: Dict[str, Any]) -> None:
        """
        Update multiple values in the state.

        Args:
            updates: Dictionary of key-value pairs to update
        """
        with self._lock:
            self._state.update(updates)

    def get_all(self) -> Dict[str, Any]:
        """
        Get a copy of the entire state.

        Returns:
            A copy of the current state dictionary
        """
        with self._lock:
            return dict(self._state)

    @property
    def lock(self):
        """
        Get the state lock for use in with statements.

        Returns:
            The lock object
        """
        return self._lock
