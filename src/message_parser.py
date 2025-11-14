import asyncio
import logging
import time
from typing import List, Dict, Optional, AsyncIterator
from datetime import datetime
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename
from telethon.errors import RpcMcgetFailError


class MessageParser:
    def __init__(self, client, config_loader):
        self.client = client
        self.config = config_loader
        self.logger = logging.getLogger(__name__)
    
    async def get_channels_entities(self) -> List[tuple]:
        """Get entity objects for all configured channels"""
        channels = self.config.get_channels()
        entities = []
        
        for channel in channels:
            try:
                entity = await self.client.get_entity(channel)
                entities.append((channel, entity))
                self.logger.info(f"Channel entity retrieved: {channel} -> {entity.title}")
            except Exception as e:
                self.logger.error(f"Failed to get entity for {channel}: {e}")
        
        return entities
    
    async def parse_messages(self, entity, last_processed_id: Optional[int] = None, limit: Optional[int] = None, config_channel_id: Optional[str] = None) -> AsyncIterator[Dict]:
        """
        Parse messages from channel and extract media info (from oldest to newest)
        
        Args:
            entity: Channel entity
            last_processed_id: Last processed message ID (if any)
            limit: Maximum number of messages to process
            config_channel_id: Channel ID from config.yaml (optional, overrides entity.id)
            
        Returns:
            AsyncIterator with message info dictionaries
        """
        file_types = self.config.get_file_types()
        timeout = self.config.get_message_timeout()
        
        try:
            # Define parameters for iter_messages
            kwargs = {
                'limit': limit,
                'reverse': True  # From oldest to newest
            }
            
            # Get filter date from config
            date_filter = self.config.get_date_filter()
            date_from = date_filter.get('from')  # This is already a datetime object or None
            
            # If last_processed_id exists, use it (priority over date)
            if last_processed_id is not None and isinstance(last_processed_id, int) and last_processed_id > 0:
                kwargs['min_id'] = last_processed_id
                self.logger.info(f"Parsing messages from channel {entity.title} starting after message ID {last_processed_id}")
            # If there's no last_processed_id but date_from exists, use the date
            elif date_from is not None:
                kwargs['offset_date'] = date_from  # Telethon expects a datetime object
                self.logger.info(f"Parsing messages from channel {entity.title} starting from date {date_from.strftime('%Y-%m-%d')}")
            else:
                self.logger.info(f"Parsing messages from channel {entity.title} from the beginning")
            
            message_count = 0
            # Use kwargs to pass arguments
            async for message in self.client.iter_messages(entity, **kwargs):
                message_count += 1
                
                # Apply timeout between message processing
                if timeout > 0 and message_count > 1:
                    self.logger.debug(f"Waiting {timeout}s before processing next message...")
                    await asyncio.sleep(timeout)
                
                # Basic message info, always present
                # Use config_channel_id if provided, otherwise fall back to entity.id
                channel_id_to_use = config_channel_id if config_channel_id is not None else str(entity.id)
                message_info = {
                    'message_id': message.id,
                    'channel_id': channel_id_to_use,
                    'publish_date': message.date,
                    'has_media': bool(message.media),
                }
                
                # If the message has no media, just return basic info
                if not message.media:
                    self.logger.debug(f"Message {message.id} has no media")
                    yield message_info
                    continue
                
                # Extract media info
                media_info = await self._extract_media_info(message)
                if not media_info:
                    self.logger.debug(f"Failed to extract media info from message {message.id}")
                    yield message_info
                    continue
                
                # Combine basic info and media data
                full_info = {**message_info, **media_info}
                
                # Debug message
                self.logger.debug(f"Found media in message {message.id}: {full_info.get('filename', 'unknown')} ({full_info.get('type', 'unknown')})")
                
                yield full_info
                
        except RpcMcgetFailError as e:
            self.logger.warning(f"Telegram internal issues: {e}")
            self.logger.info("Waiting 60 seconds before retry...")
            await asyncio.sleep(60)
        except Exception as e:
            self.logger.error(f"Error parsing messages from {entity.title}: {e}")
    
    async def _extract_media_info(self, message) -> Optional[Dict]:
        """Extract relevant media information from message"""
        if not hasattr(message.media, 'document'):
            return None
        
        document = message.media.document
        if not document:
            return None
        
        # Determine media type
        media_type = None
        if document.mime_type and document.mime_type.startswith('audio/'):
            media_type = 'audio'
        else:
            media_type = 'document'
        
        # Extract filename
        filename = None
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
            elif isinstance(attr, DocumentAttributeAudio):
                if hasattr(attr, 'title') and attr.title:
                    filename = f"{attr.title}.{self._get_extension_from_mime(document.mime_type)}"
        
        # If no filename found, generate one
        if not filename:
            ext = self._get_extension_from_mime(document.mime_type)
            filename = f"file_{message.id}.{ext}"
        
        # Extract audio metadata (if available)
        audio_meta = None
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeAudio):
                audio_meta = {
                    'duration': getattr(attr, 'duration', None),
                    'title': getattr(attr, 'title', None),
                    'performer': getattr(attr, 'performer', None)
                }
                break
        
        return {
            'filename': filename,
            'file_size': document.size,
            'mime_type': document.mime_type,
            'type': media_type,
            'audio_meta': audio_meta,
            'document_id': document.id,
            'access_hash': document.access_hash,
            'file_reference': document.file_reference
        }
    
    def _get_extension_from_mime(self, mime_type: str) -> str:
        """Get file extension from MIME type"""
        mime_map = {
            'audio/flac': 'flac',
            'audio/wav': 'wav',
            'audio/x-wav': 'wav',
            'audio/aiff': 'aiff',
            'audio/x-aiff': 'aiff',
            'audio/mp4': 'm4a',
            'audio/m4a': 'm4a',
            'audio/x-m4a': 'm4a',
            'audio/mpeg': 'mp3',
            'audio/mp3': 'mp3',
        }
        
        return mime_map.get(mime_type, 'bin')
    
    async def get_channel_stats(self, entity) -> Dict:
        """Get basic statistics about channel"""
        try:
            total_messages = 0
            media_messages = 0
            audio_files = 0
            document_files = 0
            
            # Sample first 100 messages for stats
            async for message in self.client.iter_messages(entity, limit=100):
                total_messages += 1
                
                if message.media and hasattr(message.media, 'document'):
                    media_messages += 1
                    document = message.media.document
                    
                    if document.mime_type and document.mime_type.startswith('audio/'):
                        audio_files += 1
                    else:
                        document_files += 1
            
            return {
                'total_messages_sampled': total_messages,
                'media_messages': media_messages,
                'audio_files': audio_files,
                'document_files': document_files,
                'media_percentage': (media_messages / total_messages * 100) if total_messages > 0 else 0
            }
            
        except Exception as e:
            self.logger.error(f"Error getting channel stats: {e}")
            return {}


def create_message_parser(client, config_loader) -> MessageParser:
    """Create message parser instance"""
    return MessageParser(client, config_loader)