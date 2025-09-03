"""Change model for tracking Claude modifications."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class ChangeType(str, Enum):
    """Type of change made by Claude."""
    
    EDIT = "edit"
    WRITE = "write"
    MULTI_EDIT = "multi_edit"


class Change(BaseModel):
    """Represents a single change made by Claude."""
    
    id: str
    session_id: str
    timestamp: datetime
    change_type: ChangeType
    file_path: Path
    old_content: Optional[str] = None
    new_content: str
    old_string: Optional[str] = None  # For edit operations
    new_string: Optional[str] = None  # For edit operations
    tool_input: dict  # Raw tool input from hook
    parent_repo_hash: Optional[str] = None  # Git hash of parent repo when change was made
    
    model_config = {
        "arbitrary_types_allowed": True
    }