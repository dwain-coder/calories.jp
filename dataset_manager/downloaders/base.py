from abc import ABC, abstractmethod
from typing import Dict, Any, Callable
from pathlib import Path

class BaseDownloader(ABC):
    @abstractmethod
    def download(self, dataset_config: Dict[str, Any], download_dir: Path, progress_callback: Callable[[int, int, float], None] = None) -> bool:
        """
        Downloads a dataset.
        
        Args:
            dataset_config: Configuration dictionary for the dataset.
            download_dir: The directory where the dataset should be downloaded.
            progress_callback: A callback function receiving (downloaded_bytes, total_bytes, speed_bytes_per_sec).
            
        Returns:
            True if download succeeds, False otherwise.
        """
        pass

    def get_estimated_size(self, dataset_config: Dict[str, Any]) -> int:
        """
        Returns the estimated download size in bytes.
        """
        pass

    def check_robots_txt(self, url: str, user_agent: str = "*") -> bool:
        """
        Strictly enforces robots.txt for the given URL.
        """
        try:
            from urllib.parse import urlparse
            import urllib.robotparser
            parsed_url = urlparse(url)
            robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
            
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            
            allowed = rp.can_fetch(user_agent, url)
            return allowed
        except Exception as e:
            print(f"Warning: Exception while checking robots.txt for {url}: {e}")
            # If there's an actual exception (not a 404), default to False for strictness.
            return False
