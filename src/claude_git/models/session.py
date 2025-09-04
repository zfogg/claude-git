"""Session model for tracking Claude conversations."""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


class Session(BaseModel):
    """Represents a Claude coding session."""

    id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    branch_name: str
    project_path: Path
    description: Optional[str] = None
    change_ids: List[str] = []

    @property
    def is_active(self) -> bool:
        """Check if session is currently active."""
        return self.end_time is None

    @property
    def duration(self) -> Optional[float]:
        """Get session duration in seconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    model_config = {"arbitrary_types_allowed": True}
