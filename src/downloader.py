import asyncio
import logging
from pathlib import Path
from datetime import datetime
import normalizer
from typing import Dict, Optional, Any
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename


class TelegramDownloader:
    def __init__(self, client, config_loader, file_tracker):
        self.client = client
        self.config = config_loader
        self.file_tracker = file_tracker
        self.logger = logging.getLogger(__name__)
        
        # Get configuration settings
        self.download_dir = Path(self.config.get_download_dir())
        self.naming_template = self.config.get_naming_template()
        self.date_format = self.config.get_date_format()
        
        # Ensure download directory exists
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    async def download_media_file(self, media_info: Dict[str, Any], file_info: str = "") -> Dict[str, Any]:
        """Download media file from Telegram and return result with status and details"""
        
        # Check if file should be skipped based on tracker
        should_skip, skip_reason = self.file_tracker.should_skip_file(media_info)
        if should_skip:
            self.logger.info(f"→ Skipping file: {media_info['filename']} {file_info} - {skip_reason}")
            return {
                'status': 'skipped',
                'reason': skip_reason,
                'file_path': None,
                'logged': True  # Indicates the message has already been logged by the tracker
            }
        
        try:
            # Generate filename
            filename = self._generate_filename(media_info)
            file_path = self.download_dir / filename
            
            # Check if a file with the same name already exists (regardless of the message)
            if file_path.exists():
                # Physical file existence check
                skip_reason = f"File with same name already exists: {file_path}"
                self.logger.info(f"→ Skipping file: {media_info['filename']} {file_info} - {skip_reason}")
                
                # Return info that file was skipped due to existing name
                return {
                    'status': 'skipped',
                    'reason': skip_reason,
                    'file_path': str(file_path),
                    'logged': True
                }
            
            # Download file from Telegram
            # Logging for download initiation is now handled in main.py
            
            # Create message object for download
            message = await self._get_message_by_id(media_info)
            if not message:
                self.logger.error(f"✗ Could not retrieve message {media_info['message_id']}")
                return {
                    'status': 'failed',
                    'reason': f"Could not retrieve message {media_info['message_id']}",
                    'file_path': None,
                    'logged': True
                }
            
            # Download without progress callback
            downloaded_file = await self.client.download_media(
                message.media.document,
                file=str(file_path)
            )
            
            if downloaded_file:
                # Update media_info with download date
                media_info['download_date'] = datetime.now()

                # Normalize track name if enabled in config
                if self.config.get_normalize_track_names():
                    original_name = Path(file_path.name).stem
                    original_suffix = Path(file_path.name).suffix
                    normalized_name = normalizer.normalize_track_name(original_name)
                    if normalized_name != original_name:
                        normalized_file_name = normalized_name + original_suffix
                        normalized_path = file_path.with_name(normalized_file_name)
                        file_path.rename(normalized_path)
                        self.logger.info(f"Track name normalized: '{original_name}' -> '{normalized_name}'")
                        file_path = normalized_path

                # Track downloaded file in file_tracker
                file_hash = await self.file_tracker.track_downloaded_file(media_info, str(file_path))
                
                self.logger.info(f"✓ Downloaded successfully: {file_path.name} {file_info} (hash: {file_hash[:8]}...)")
                
                return {
                    'status': 'success',
                    'file_path': str(file_path),
                    'file_hash': file_hash,
                    'already_existed': False,
                    'logged': True
                }
            else:
                self.logger.error(f"✗ Download failed: {filename} {file_info}")
                return {
                    'status': 'failed',
                    'reason': 'Download returned None',
                    'file_path': None,
                    'logged': True
                }
                
        except Exception as e:
            self.logger.error(f"✗ Download error for {media_info['filename']} {file_info}: {e}")
            # Add to blacklist on persistent errors
            if "flood" in str(e).lower() or "timeout" in str(e).lower():
                self.file_tracker.add_blacklisted_file(
                    media_info['message_id'], 
                    f"Download error: {str(e)[:100]}"
                )
            return {
                'status': 'failed',
                'reason': str(e),
                'file_path': None,
                'logged': True
            }
    
    async def _get_message_by_id(self, media_info: Dict[str, Any]) -> Optional[Any]:
        """Get message object by ID for downloading"""
        try:
            # We need to find the message in the channel
            # This is a simplified version - in real usage we'd need channel info
            
            # For now, we'll reconstruct the document from media_info
            # This is a workaround since we have document_id, access_hash, file_reference
            from telethon.tl.types import Document, DocumentAttributeFilename
            
            # Create document object from stored info
            document = Document(
                id=media_info['document_id'],
                access_hash=media_info['access_hash'],
                file_reference=media_info['file_reference'],
                size=media_info['file_size'],
                dc_id=1,  # This might need to be dynamic
                mime_type=media_info['mime_type'],
                attributes=[],
                date=None,
                thumbs=None,
                video_thumbs=None
            )
            
            # Create a mock message-like object
            class MockMessage:
                def __init__(self, doc):
                    self.media = doc
                    self.media.document = doc
            
            return MockMessage(document)
            
        except Exception as e:
            self.logger.error(f"Error creating message object: {e}")
            return None
    
    def _generate_filename(self, media_info: Dict[str, Any]) -> str:
        """Generate filename based on template"""
        try:
            # Get original filename without extension
            original_name = Path(media_info['filename']).stem
            file_extension = Path(media_info['filename']).suffix
            
            # Get dates
            publish_date = media_info.get('publish_date')
            download_date = media_info.get('download_date', datetime.now())
            
            # Format publish date
            publish_date_str = ""
            if publish_date:
                if isinstance(publish_date, str):
                    publish_date = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
                publish_date_str = publish_date.strftime(self.date_format)
            
            # Format download date
            download_date_str = ""
            if download_date:
                if isinstance(download_date, str):
                    download_date = datetime.fromisoformat(download_date.replace('Z', '+00:00'))
                download_date_str = download_date.strftime(self.date_format)
            
            # Prepare template variables
            template_vars = {
                'original_name': self._sanitize_filename(original_name),
                'message_id': media_info['message_id'],
                'publish_date': publish_date_str,
                'download_date': download_date_str,
                'file_size': media_info['file_size'],
                'mime_type': media_info['mime_type'].replace('/', '_')
            }
            
            # Add audio metadata if available
            audio_meta = media_info.get('audio_meta')
            if audio_meta:
                template_vars.update({
                    'artist': self._sanitize_filename(audio_meta.get('performer', '')),
                    'title': self._sanitize_filename(audio_meta.get('title', '')),
                    'duration': audio_meta.get('duration', 0)
                })
            
            # Generate filename from template
            filename = self.naming_template.format(**template_vars)
            
            # Add original extension
            filename = filename + file_extension
            
            # Ensure filename is valid
            filename = self._sanitize_filename(filename)
            
            # Ensure filename is not too long (max 255 chars for most filesystems)
            if len(filename) > 255:
                # Truncate while keeping extension
                max_name_length = 255 - len(file_extension)
                filename = filename[:max_name_length] + file_extension
            
            return filename
            
        except Exception as e:
            self.logger.error(f"Error generating filename: {e}")
            # Fallback to simple name
            return f"file_{media_info['message_id']}{Path(media_info['filename']).suffix}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        if not filename:
            return ""
        
        # Define invalid characters for Windows/Unix
        invalid_chars = '<>:"/\\|?*'
        
        # Replace invalid characters with underscore
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Remove control characters
        filename = ''.join(char for char in filename if ord(char) >= 32)
        
        # Strip spaces and dots from ends
        filename = filename.strip(' .')
        
        # Ensure filename is not empty
        if not filename:
            filename = "unnamed"
        
        return filename
    
    def get_download_statistics(self) -> Dict[str, Any]:
        """Get download statistics"""
        file_stats = self.file_tracker.get_statistics()
        
        return {
            'download_directory': str(self.download_dir),
            'naming_template': self.naming_template,
            'total_downloaded_files': file_stats['total_downloaded_files'],
            'total_blacklisted_files': file_stats['total_blacklisted_files']
        }


def create_downloader(client, config_loader, file_tracker) -> TelegramDownloader:
    """Create downloader instance"""
    return TelegramDownloader(client, config_loader, file_tracker)