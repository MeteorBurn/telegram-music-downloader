import os
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
import copy


class ConfigLoader:
    def __init__(self, config_path: str = "config.yaml", local_config_name: str = "local_config.yaml"):
        self.base_config_path = Path(config_path)
        self.local_config_path = self.base_config_path.parent / local_config_name
        self._config: Dict[str, Any] = {}
        self._load_config()
        self._validate_config()
    
    def _deep_merge_dicts(self, source: Dict[str, Any], destination: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(destination)
        for key, value in source.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._deep_merge_dicts(value, merged[key])
            else:
                merged[key] = value
        return merged

    def _load_config(self) -> None:
        if not self.base_config_path.exists():
            raise FileNotFoundError(f"Base config file not found: {self.base_config_path}")
        
        with open(self.base_config_path, 'r', encoding='utf-8') as file:
            base_config = yaml.safe_load(file)
            if not isinstance(base_config, dict): 
                raise ValueError(f"Base config content is not a dictionary: {self.base_config_path}")
            self._config = base_config

        if self.local_config_path.exists():
            try:
                with open(self.local_config_path, 'r', encoding='utf-8') as file:
                    local_config = yaml.safe_load(file)
                    if local_config: 
                        if not isinstance(local_config, dict):
                            print(f"Warning: Local config content is not a dictionary, skipping: {self.local_config_path}")
                        else:
                            self._config = self._deep_merge_dicts(local_config, self._config)
                            print(f"Successfully loaded and merged local config: {self.local_config_path}")
                    else:
                        print(f"Warning: Local config file is empty, skipping: {self.local_config_path}")
            except Exception as e:
                print(f"Warning: Could not load or parse local config file {self.local_config_path}: {e}")
        else:
            print(f"Info: Local config file not found, using base config only: {self.local_config_path}")
        
        # Set normalization config defaults if not present
        if 'normalize_track_names' not in self._config:
            self._config['normalize_track_names'] = False
    
    def _validate_config(self) -> None:
        required_fields = {
            'telegram': ['api_id', 'api_hash'],
            'channels': [],
            'download': ['output_dir'],
            'filters': ['file_types', 'formats']
        }
        
        for section, fields in required_fields.items():
            if section not in self._config:
                raise ValueError(f"Missing section '{section}' in config")
            
            for field in fields:
                if field not in self._config[section]:
                    raise ValueError(f"Missing field '{field}' in section '{section}'")
        
        if not isinstance(self._config['telegram']['api_id'], int):
            raise ValueError("api_id must be an integer")
        
        os.makedirs(self.get_download_dir(), exist_ok=True)
        os.makedirs(self.get_log_dir(), exist_ok=True)
        os.makedirs(self.get_session_dir(), exist_ok=True)
    
    def get_api_id(self) -> int:
        return self._config['telegram']['api_id']
    
    def get_api_hash(self) -> str:
        return self._config['telegram']['api_hash']
    
    def get_session_name(self) -> str:
        return self._config['telegram'].get('session_name', 'downloader_session')
    
    def is_two_factor_enabled(self) -> bool:
        return self._config['telegram'].get('two_factor_auth', False)
    
    def get_channels(self) -> List[str]:
        return self._config['channels']
    
    def get_download_dir(self) -> str:
        return self._config['download']['output_dir']
    
    def get_message_timeout(self) -> float:
        return self._config['download'].get('timeout_between_messages', 1.0)
        
    def get_max_files_per_run(self) -> int:
        return self._config['download'].get('max_files_per_run', 0)
    
    def get_concurrent_downloads(self) -> int:
        return self._config['download'].get('concurrent_downloads', 3)
    
    def get_max_queue_size(self) -> int:
        return self._config['download'].get('max_queue_size', 100)
    
    def get_worker_timeout(self) -> int:
        return self._config['download'].get('worker_timeout', 300)
    
    def get_requests_per_second(self) -> float:
        return self._config['download'].get('rate_limit', {}).get('requests_per_second', 2.0)
    
    def get_burst_size(self) -> int:
        return self._config['download'].get('rate_limit', {}).get('burst_size', 5)
    
    def get_naming_template(self) -> str:
        return self._config.get('naming', {}).get('template', '{original_name}_{message_id}')
    
    def get_date_format(self) -> str:
        return self._config.get('naming', {}).get('date_format', '%Y%m%d_%H%M%S')
    
    def get_file_types(self) -> List[str]:
        return self._config['filters']['file_types']
    
    def get_allowed_formats(self) -> List[str]:
        return self._config['filters']['formats']
    
    def get_size_filter(self) -> Dict[str, Optional[int]]:
        size_config = self._config['filters'].get('size', {})
        return {
            'min_mb': size_config.get('min_mb'),
            'max_mb': size_config.get('max_mb')
        }
    
    def get_date_filter(self) -> Dict[str, Optional[datetime]]:
        date_config = self._config['filters'].get('date', {})
        date_from = date_config.get('from')
        date_to = date_config.get('to')
        
        return {
            'from': datetime.strptime(date_from, '%Y-%m-%d') if date_from else None,
            'to': datetime.strptime(date_to, '%Y-%m-%d') if date_to else None
        }
    

    def get_log_level(self) -> str:
        return self._config.get('logging', {}).get('level', 'INFO')
    
    def get_log_file(self) -> str:
        return self._config.get('logging', {}).get('file', './data/logs/downloader.log')
    
    def is_console_logging_enabled(self) -> bool:
        return self._config.get('logging', {}).get('console', True)
    
    def get_log_dir(self) -> str:
        return str(Path(self.get_log_file()).parent)
    
    def get_session_dir(self) -> str:
        return "./data/sessions"
    
    def get_full_session_path(self) -> str:
        return os.path.join(self.get_session_dir(), self.get_session_name())

    def get_normalize_track_names(self) -> bool:
        return bool(self._config.get('normalize_track_names', False))
