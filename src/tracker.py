import json
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import Dict, Set, Optional, Any
from datetime import datetime


class MessageTracker:
    """Tracks processed message IDs for each channel"""
    def __init__(self, tracker_file: str = "./data/message_tracker.json"):
        self.tracker_file = Path(tracker_file)
        self.logger = logging.getLogger(__name__)
        
        # Data initialization
        self.processed_messages = {}  # channel id -> set of processed messages
        self.last_processed_id = {}  # channel id -> last processed id
        
        # Load existing data
        self._load_tracker_data()
        self._ensure_tracker_dir()
    
    def _ensure_tracker_dir(self) -> None:
        """Create tracker directory if it doesn't exist"""
        self.tracker_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_tracker_data(self) -> None:
        """Load tracking data from JSON file"""
        if not self.tracker_file.exists():
            self.logger.info("Message tracker file not found, starting fresh")
            return
        
        try:
            with open(self.tracker_file, 'r', encoding='utf-8') as file:
                data = json.load(file)
                
                # Load processed messages for each channel
                for channel_id, messages in data.items():
                    # Convert channel IDs to strings for consistency
                    channel_id_str = str(channel_id)
                    
                    # Convert list of message IDs to set for fast lookup
                    self.processed_messages[channel_id_str] = set(messages)
                    
                    # Set last processed ID as the maximum from the set
                    if messages:
                        self.last_processed_id[channel_id_str] = max(messages)
                
                channel_count = len(self.processed_messages)
                total_messages = sum(len(msgs) for msgs in self.processed_messages.values())
                
                self.logger.info(f"Loaded message tracker: {channel_count} channels, "
                               f"{total_messages} total messages tracked")
                
        except Exception as e:
            self.logger.error(f"Failed to load message tracker data: {e}")
            self.logger.warning("Starting with empty message tracker")
    
    def _save_tracker_data(self) -> None:
        """Save tracking data to JSON file"""
        try:
            # Convert sets to lists for JSON serialization
            # Structure: channel_id -> [message_id1, message_id2, ...]
            processed_messages_json = {}
            for channel_id, messages in self.processed_messages.items():
                processed_messages_json[channel_id] = sorted(list(messages))
            
            # Write to a temporary file
            temp_file = self.tracker_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as file:
                json.dump(processed_messages_json, file, indent=2, ensure_ascii=False)
            
            # Replace the original file
            temp_file.replace(self.tracker_file)
            self.logger.debug("Message tracker data saved successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to save message tracker data: {e}")
    
    def is_message_processed(self, channel_id: str, message_id: int) -> bool:
        """Check if message was already processed"""
        channel_id_str = str(channel_id)
        if channel_id_str not in self.processed_messages:
            return False
        return message_id in self.processed_messages[channel_id_str]
    
    def mark_message_processed(self, channel_id: str, message_id: int) -> None:
        """Mark message as processed"""
        channel_id_str = str(channel_id)
        if channel_id_str not in self.processed_messages:
            self.processed_messages[channel_id_str] = set()
        
        # Add message ID to the set of processed for this channel
        self.processed_messages[channel_id_str].add(message_id)
        
        # Update last processed ID if the current one is greater
        current_last = self.last_processed_id.get(channel_id_str, 0)
        if message_id > current_last:
            self.last_processed_id[channel_id_str] = message_id
        
        self._save_tracker_data()
        self.logger.debug(f"Message {message_id} in channel {channel_id_str} marked as processed")
    
    def get_last_processed_id(self, channel_id: str) -> Optional[int]:
        """Get last processed message ID for a channel"""
        channel_id_str = str(channel_id)
        return self.last_processed_id.get(channel_id_str)


class FileTracker:
    """Tracks downloaded files information"""
    def __init__(self, tracker_file: str = "./data/file_tracker.json"):
        self.tracker_file = Path(tracker_file)
        self.logger = logging.getLogger(__name__)
        
        # Initialize tracking data
        self.downloaded_files: Dict[str, Dict[str, Any]] = {}
        self.blacklisted_files: Set[int] = set()
        
        # Thread safety
        self._lock = asyncio.Lock()
        
        # Load existing data
        self._load_tracker_data()
        self._ensure_tracker_dir()
    
    def _ensure_tracker_dir(self) -> None:
        """Create tracker directory if it doesn't exist"""
        self.tracker_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_tracker_data(self) -> None:
        """Load tracking data from JSON file"""
        if not self.tracker_file.exists():
            self.logger.info("File tracker file not found, starting fresh")
            return
        
        try:
            with open(self.tracker_file, 'r', encoding='utf-8') as file:
                data = json.load(file)
                
                # Load downloaded files info
                self.downloaded_files = data.get('downloaded_files', {})
                
                # Load blacklisted file IDs
                self.blacklisted_files = set(data.get('blacklisted_files', []))
                
                self.logger.info(f"Loaded file tracker: "
                               f"{len(self.downloaded_files)} downloaded, "
                               f"{len(self.blacklisted_files)} blacklisted")
                
        except Exception as e:
            self.logger.error(f"Failed to load file tracker data: {e}")
            self.logger.warning("Starting with empty file tracker")
    
    def _save_tracker_data(self) -> None:
        """Save tracking data to JSON file"""
        try:
            data = {
                'downloaded_files': self.downloaded_files,
                'blacklisted_files': list(self.blacklisted_files),
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
            
            # Store file information
            self.downloaded_files[file_hash] = {
                'message_id': media_info['message_id'],
                'channel_id': media_info.get('channel_id', ''),
                'filename': media_info['filename'],
                'file_path': str(file_path),
                'file_size': media_info['file_size'],
                'file_size_mb': round(file_size_mb, 1),
                'mime_type': media_info['mime_type'],
                'download_date': datetime.now().isoformat(),
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
    
    def get_downloaded_file_by_message(self, channel_id: str, message_id: int) -> Optional[Dict[str, Any]]:
        """Find downloaded file by channel ID and message ID"""
        channel_id_str = str(channel_id)
        for file_hash, file_info in self.downloaded_files.items():
            if file_info['message_id'] == message_id and file_info.get('channel_id', '') == channel_id_str:
                return {**file_info, 'file_hash': file_hash}
        return None
    
    def should_skip_file(self, media_info: Dict[str, Any]) -> tuple[bool, str]:
        """Check if file should be skipped (already blacklisted or already downloaded)"""
        message_id = media_info['message_id']
        channel_id = media_info.get('channel_id', '')
        
        # Check blacklist first
        if self.is_file_blacklisted(message_id):
            return True, "File is blacklisted"
        
        # Check if file already downloaded
        existing_file = self.get_downloaded_file_by_message(channel_id, message_id)
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


def create_message_tracker(config_loader=None) -> MessageTracker:
    """Create message tracker instance"""
    if config_loader:
        # Use data directory from config
        download_dir = Path(config_loader.get_download_dir())
        base_dir = download_dir.parent
        message_tracker_file = base_dir / "message_tracker.json"
    else:
        message_tracker_file = "./data/message_tracker.json"
    
    return MessageTracker(str(message_tracker_file))


def create_file_tracker(config_loader=None) -> FileTracker:
    """Create file tracker instance"""
    if config_loader:
        # Use data directory from config
        download_dir = Path(config_loader.get_download_dir())
        base_dir = download_dir.parent
        file_tracker_file = base_dir / "file_tracker.json"
    else:
        file_tracker_file = "./data/file_tracker.json"
    
    return FileTracker(str(file_tracker_file))
