import json
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import Dict, Set, Optional, Any, Union
from datetime import datetime


class MessageTracker:
    """Tracks processed message IDs for a specific channel"""
    def __init__(self, tracker_file: str = "./data/message_tracker.json", channel_id: str = None):
        self.tracker_file = Path(tracker_file)
        self.channel_id = str(channel_id) if channel_id else None
        self.logger = logging.getLogger(__name__)
        
        # Data initialization
        self.last_processed_id = None  # last processed message ID
        self.total_messages_processed = 0  # counter of processed messages
        
        # Load existing data
        self._ensure_tracker_dir()
        self._load_tracker_data()
    
    def _ensure_tracker_dir(self) -> None:
        """Create tracker directory if it doesn't exist"""
        self.tracker_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_tracker_data(self) -> None:
        """Load tracking data from JSON file"""
        if not self.tracker_file.exists():
            self.logger.info(f"Message tracker file not found, starting fresh for channel {self.channel_id}")
            return
        
        try:
            with open(self.tracker_file, 'r', encoding='utf-8') as file:
                data = json.load(file)
                
                # Load last processed ID
                self.last_processed_id = data.get('last_processed_id')
                
                # Load total messages counter
                self.total_messages_processed = data.get('total_messages_processed', 0)
                
                self.logger.info(f"Loaded message tracker for channel {self.channel_id}: "
                               f"{self.total_messages_processed} messages tracked, "
                               f"last ID: {self.last_processed_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to load message tracker data: {e}")
            self.logger.warning("Starting with empty message tracker")
    
    def _save_tracker_data(self) -> None:
        """Save tracking data to JSON file"""
        try:
            # Prepare data structure (optimized - no arrays!)
            data = {
                'channel_id': self.channel_id,
                'last_processed_id': self.last_processed_id,
                'total_messages_processed': self.total_messages_processed,
                'last_updated': datetime.now().isoformat()
            }
            
            # Write to a temporary file
            temp_file = self.tracker_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
            
            # Replace the original file
            temp_file.replace(self.tracker_file)
            self.logger.debug(f"Message tracker data saved successfully for channel {self.channel_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to save message tracker data: {e}")
    
    def is_message_processed(self, message_id: int) -> bool:
        """
        Check if message was already processed.
        Note: With optimized storage, this checks if message_id <= last_processed_id.
        This assumes sequential processing from oldest to newest.
        """
        if self.last_processed_id is None:
            return False
        return message_id <= self.last_processed_id
    
    def mark_message_processed(self, message_id: int) -> None:
        """Mark message as processed"""
        # Increment counter
        self.total_messages_processed += 1
        
        # Update last processed ID if the current one is greater
        if self.last_processed_id is None or message_id > self.last_processed_id:
            self.last_processed_id = message_id
        
        self._save_tracker_data()
        self.logger.debug(f"Message {message_id} in channel {self.channel_id} marked as processed "
                         f"(total: {self.total_messages_processed})")
    
    def get_last_processed_id(self) -> Optional[int]:
        """Get last processed message ID for this channel"""
        return self.last_processed_id
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get tracker statistics"""
        return {
            'channel_id': self.channel_id,
            'total_messages_processed': self.total_messages_processed,
            'last_processed_id': self.last_processed_id,
            'tracker_file_path': str(self.tracker_file),
            'tracker_file_exists': self.tracker_file.exists()
        }


class FileTracker:
    """Tracks downloaded files information for a specific channel"""
    def __init__(self, tracker_file: str = "./data/file_tracker.json", channel_id: str = None):
        self.tracker_file = Path(tracker_file)
        self.channel_id = str(channel_id) if channel_id else None
        self.logger = logging.getLogger(__name__)
        
        # Initialize tracking data
        self.downloaded_files: Dict[str, Dict[str, Any]] = {}
        self.blacklisted_files: Set[int] = set()
        
        # Thread safety
        self._lock = asyncio.Lock()
        
        # Load existing data
        self._ensure_tracker_dir()
        self._load_tracker_data()
    
    def _ensure_tracker_dir(self) -> None:
        """Create tracker directory if it doesn't exist"""
        self.tracker_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_tracker_data(self) -> None:
        """Load tracking data from JSON file"""
        if not self.tracker_file.exists():
            self.logger.info(f"File tracker file not found, starting fresh for channel {self.channel_id}")
            return
        
        try:
            with open(self.tracker_file, 'r', encoding='utf-8') as file:
                data = json.load(file)
                
                # Load downloaded files info
                self.downloaded_files = data.get('downloaded_files', {})
                
                # Load blacklisted file IDs
                self.blacklisted_files = set(data.get('blacklisted_files', []))
                
                self.logger.info(f"Loaded file tracker for channel {self.channel_id}: "
                               f"{len(self.downloaded_files)} downloaded, "
                               f"{len(self.blacklisted_files)} blacklisted")
                
        except Exception as e:
            self.logger.error(f"Failed to load file tracker data: {e}")
            self.logger.warning("Starting with empty file tracker")
    
    def _save_tracker_data(self) -> None:
        """Save tracking data to JSON file"""
        try:
            data = {
                'channel_id': self.channel_id,
                'downloaded_files': self.downloaded_files,
                'blacklisted_files': list(self.blacklisted_files),
                'total_files': len(self.downloaded_files),
                'last_updated': datetime.now().isoformat()
            }
            
            # Write to temporary file first
            temp_file = self.tracker_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
            
            # Replace original file
            temp_file.replace(self.tracker_file)
            self.logger.debug("File tracker data saved successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to save file tracker data: {e}")
    
    def is_file_downloaded(self, file_hash: str) -> bool:
        """Check if file with this hash was already downloaded"""
        return file_hash in self.downloaded_files
    
    def is_file_blacklisted(self, message_id: int) -> bool:
        """Check if file is in blacklist"""
        return message_id in self.blacklisted_files
    
    def add_blacklisted_file(self, message_id: int, reason: str = "") -> None:
        """Add file to blacklist"""
        self.blacklisted_files.add(message_id)
        self._save_tracker_data()
        self.logger.info(f"File from message {message_id} blacklisted: {reason}")
    
    def remove_from_blacklist(self, message_id: int) -> None:
        """Remove file from blacklist"""
        if message_id in self.blacklisted_files:
            self.blacklisted_files.remove(message_id)
            self._save_tracker_data()
            self.logger.info(f"Message {message_id} removed from blacklist")
    
    async def track_downloaded_file(self, media_info: Dict[str, Any], file_path: str) -> str:
        """Track downloaded file and return its hash (thread-safe)"""
        async with self._lock:
            file_hash = self._calculate_file_hash(file_path)
            
            # Calculate file size in MB for storage
            file_size_mb = media_info.get('file_size', 0) / (1024 * 1024)
            
            # Get download date from media_info or use current time
            download_date = media_info.get('download_date', datetime.now())
            if isinstance(download_date, datetime):
                download_date_str = download_date.isoformat()
            else:
                download_date_str = download_date  # Already a string
            
            # Store file information
            self.downloaded_files[file_hash] = {
                'message_id': media_info['message_id'],
                'channel_id': media_info.get('channel_id', ''),
                'filename': media_info['filename'],
                'file_path': str(file_path),
                'file_size': media_info['file_size'],
                'file_size_mb': round(file_size_mb, 1),
                'mime_type': media_info['mime_type'],
                'download_date': download_date_str,
                'publish_date': media_info['publish_date'].isoformat() if media_info['publish_date'] else None
            }
            
            self._save_tracker_data()
            self.logger.info(f"File tracked: {media_info['filename']} -> {file_hash}")
            return file_hash
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate MD5 hash of file"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return ""
    
    def get_downloaded_file_by_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Find downloaded file by message ID"""
        for file_hash, file_info in self.downloaded_files.items():
            if file_info['message_id'] == message_id:
                return {**file_info, 'file_hash': file_hash}
        return None
    
    def should_skip_file(self, media_info: Dict[str, Any]) -> tuple[bool, str]:
        """Check if file should be skipped (already blacklisted or already downloaded)"""
        message_id = media_info['message_id']
        
        # Check blacklist first
        if self.is_file_blacklisted(message_id):
            return True, "File is blacklisted"
        
        # Check if file already downloaded
        existing_file = self.get_downloaded_file_by_message(message_id)
        if existing_file:
            file_path = Path(existing_file['file_path'])
            if file_path.exists():
                return True, f"File already downloaded: {existing_file['file_path']}"
            else:
                # File is tracked but missing on disk
                self.logger.warning(f"File tracked but missing on disk: {existing_file['file_path']}")
                return False, ""  # Allow re-download
        
        return False, ""
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get tracker statistics"""
        return {
            'channel_id': self.channel_id,
            'total_downloaded_files': len(self.downloaded_files),
            'total_blacklisted_files': len(self.blacklisted_files),
            'tracker_file_path': str(self.tracker_file),
            'tracker_file_exists': self.tracker_file.exists(),
            'tracker_file_size': self.tracker_file.stat().st_size if self.tracker_file.exists() else 0
        }
    
    def cleanup_missing_files(self) -> int:
        """Remove entries for files that no longer exist on disk"""
        removed_count = 0
        files_to_remove = []
        
        for file_hash, file_info in self.downloaded_files.items():
            file_path = Path(file_info['file_path'])
            if not file_path.exists():
                files_to_remove.append(file_hash)
                removed_count += 1
                self.logger.info(f"Removing missing file from tracker: {file_info['filename']}")
        
        for file_hash in files_to_remove:
            del self.downloaded_files[file_hash]
        
        if removed_count > 0:
            self._save_tracker_data()
            self.logger.info(f"Cleaned up {removed_count} missing files from tracker")
        
        return removed_count


def create_message_tracker(tracker_file: str, channel_id: str) -> MessageTracker:
    """Create message tracker instance for a specific channel"""
    return MessageTracker(tracker_file, channel_id)


def create_file_tracker(tracker_file: str, channel_id: str) -> FileTracker:
    """Create file tracker instance for a specific channel"""
    return FileTracker(tracker_file, channel_id)


class TrackerManager:
    """Manages per-channel trackers"""
    def __init__(self, base_download_dir: str):
        self.base_download_dir = Path(base_download_dir)
        self.message_trackers: Dict[str, MessageTracker] = {}
        self.file_trackers: Dict[str, FileTracker] = {}
        self.logger = logging.getLogger(__name__)
    
    def get_or_create_trackers(self, channel_title: str, channel_id: Union[str, int]) -> tuple[MessageTracker, FileTracker]:
        """
        Get or create trackers for a specific channel
        
        Args:
            channel_title: Channel title
            channel_id: Channel ID
            
        Returns:
            Tuple of (message_tracker, file_tracker)
        """
        from channel_utils import get_channel_tracker_path, get_channel_downloads_dir
        
        channel_id_str = str(channel_id)
        
        # Check if trackers already exist for this channel
        if channel_id_str in self.message_trackers and channel_id_str in self.file_trackers:
            return self.message_trackers[channel_id_str], self.file_trackers[channel_id_str]
        
        # Create tracker paths
        message_tracker_path = get_channel_tracker_path(
            self.base_download_dir, channel_title, channel_id, 'message'
        )
        file_tracker_path = get_channel_tracker_path(
            self.base_download_dir, channel_title, channel_id, 'file'
        )
        
        # Create trackers
        message_tracker = create_message_tracker(str(message_tracker_path), channel_id_str)
        file_tracker = create_file_tracker(str(file_tracker_path), channel_id_str)
        
        # Store in cache
        self.message_trackers[channel_id_str] = message_tracker
        self.file_trackers[channel_id_str] = file_tracker
        
        self.logger.info(f"Created trackers for channel {channel_title} ({channel_id_str})")
        
        return message_tracker, file_tracker
    
    def get_channel_download_dir(self, channel_title: str, channel_id: Union[str, int]) -> Path:
        """Get download directory for a specific channel"""
        from channel_utils import get_channel_downloads_dir
        return get_channel_downloads_dir(self.base_download_dir, channel_title, channel_id)
