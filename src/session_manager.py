import os
from pathlib import Path
from typing import Optional

from logger import get_logger


class SessionManager:
    def __init__(self, session_dir: str = "."):
        self.session_dir = Path(session_dir)
        self.logger = get_logger()
        self._ensure_session_dir()

    def _ensure_session_dir(self) -> None:
        """Create session directory if it doesn't exist"""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.logger.debug(f"Session directory ensured: {self.session_dir}")

    def get_session_path(self, session_name: str) -> str:
        """Get full path for session file"""
        return str(self.session_dir / session_name)

    def session_exists(self, session_name: str) -> bool:
        """Check if session file exists"""
        session_path = Path(self.get_session_path(session_name))
        session_file = session_path.with_suffix(".session")
        exists = session_file.exists()
        self.logger.debug(f"Session {session_name} exists: {exists}")
        return exists

    def get_session_info(self, session_name: str) -> Optional[dict]:
        """Get session file information"""
        if not self.session_exists(session_name):
            return None

        session_path = Path(self.get_session_path(session_name))
        session_file = session_path.with_suffix(".session")

        stat = session_file.stat()
        return {
            "name": session_name,
            "path": str(session_file),
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
        }

    def delete_session(self, session_name: str) -> bool:
        """Delete session file"""
        try:
            session_path = Path(self.get_session_path(session_name))
            session_file = session_path.with_suffix(".session")

            if session_file.exists():
                session_file.unlink()
                self.logger.info(f"Session deleted: {session_name}")
                return True
            else:
                self.logger.warning(f"Session file not found: {session_name}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to delete session {session_name}: {e}")
            return False

    def list_sessions(self) -> list[dict]:
        """List all available sessions"""
        sessions = []

        for session_file in self.session_dir.glob("*.session"):
            session_name = session_file.stem
            session_info = self.get_session_info(session_name)
            if session_info:
                sessions.append(session_info)

        self.logger.debug(f"Found {len(sessions)} sessions")
        return sessions

    def backup_session(
        self, session_name: str, backup_dir: Optional[str] = None
    ) -> bool:
        """Create backup of session file"""
        try:
            if not self.session_exists(session_name):
                self.logger.error(f"Session not found: {session_name}")
                return False

            backup_location = (
                Path(backup_dir) if backup_dir else self.session_dir / "backups"
            )
            backup_location.mkdir(parents=True, exist_ok=True)

            session_path = Path(self.get_session_path(session_name))
            session_file = session_path.with_suffix(".session")

            import shutil
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{session_name}_{timestamp}.session"
            backup_path = backup_location / backup_name

            shutil.copy2(session_file, backup_path)
            self.logger.info(f"Session backed up: {session_name} -> {backup_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to backup session {session_name}: {e}")
            return False


def create_session_manager(config_loader) -> SessionManager:
    """Create session manager from config"""
    session_dir = config_loader.get_session_dir()
    return SessionManager(session_dir)
