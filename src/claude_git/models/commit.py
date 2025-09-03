"""Commit model for Claude Git repository."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class Commit(BaseModel):
    """Represents a commit in the Claude Git repository."""
    
    id: str
    session_id: str
    timestamp: datetime
    message: str
    change_ids: List[str]
    parent_commit_id: Optional[str] = None
    branch_name: str
    
    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
        }